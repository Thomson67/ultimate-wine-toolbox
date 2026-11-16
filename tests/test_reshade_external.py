import os
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'toolbox/helpers'))
import reshade_external as e
import reshade_manager as r
import reshade_api as a


def dll(supported=True, arch=64):
    machine = {32: 0x14c, 64: 0x8664}[arch]
    data=bytearray(200);data[:2]=b'MZ';data[60:64]=(64).to_bytes(4,'little');data[64:68]=b'PE\0\0';data[68:70]=machine.to_bytes(2,'little')
    data.extend(f"crosire's ReShade post-processing injector for {arch}-bit".encode('utf-16le'))
    if supported: data.extend(b'additional exports')
    return bytes(data)


class ExternalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.base=Path(self.temp.name)
        self.home=self.base/'home';self.rom=self.base/'Game.wine'
        self.folder=self.rom/'drive_c/game';self.folder.mkdir(parents=True)
        self.binary=self.folder/'dxgi.dll';self.binary.write_bytes(dll())
        self.autorun=self.rom/'autorun.cmd'
        self.original='ENV=MANGOHUD=1 WINEDLLOVERRIDES="dxgi=n,b"\nDIR=drive_c/game\nCMD="Game.exe"\nSAVEDIR=drive_c/Saved\n'
        self.autorun.write_text(self.original)
        self.preset=self.folder/'MyPreset.ini';self.preset.write_text('Techniques=CRT\n')

    def tearDown(self): self.temp.cleanup()

    def test_strong_injector_signature_not_dll_name_or_compiler(self):
        self.assertEqual(e.identify(dll()), {'arch':64,'controllable':True})
        self.assertEqual(e.identify(dll(False)), {'arch':64,'controllable':True})
        self.assertIsNone(e.identify(b'MZReShade compiler dxgi.dll'))
        self.binary.write_bytes(b'DXVK dxgi.dll')
        self.assertEqual(e.scan_game(self.home,self.rom)['files'],[])

    def test_disable_enable_release_preserve_dll_presets_overrides_and_user_variables(self):
        before=self.binary.read_bytes();preset=self.preset.read_bytes()
        e.toggle(self.home,self.rom,False)
        self.assertEqual(e.state(r.read_json(e.config_path(self.home,self.rom))), 'external-disabled')
        self.assertFalse(self.binary.exists())
        self.assertEqual(self.autorun.read_text(),self.original)
        self.assertEqual(self.preset.read_bytes(),preset)
        e.toggle(self.home,self.rom,True)
        self.assertEqual(self.binary.read_bytes(),before)
        e.toggle(self.home,self.rom,False)
        e.release(self.home,self.rom)
        self.assertEqual(self.binary.read_bytes(),before)
        self.assertEqual(self.autorun.read_text(),self.original)

    def test_es_disables_embedded_reshade_for_each_session_without_changing_toolbox_settings(self):
        before, preset = self.binary.read_bytes(), self.preset.read_bytes()
        with patch('es_options.Overrides') as overrides:
            overrides.return_value.get.return_value = 'off'
            for _ in range(2):
                r.event(self.home, self.rom, 'gameStart', es=True)
                self.assertFalse(self.binary.exists())
                self.assertEqual(self.preset.read_bytes(), preset)
                self.assertEqual(self.autorun.read_text(), self.original)
                self.assertFalse(r.read_json(e.config_path(self.home, self.rom))['controlled'])
                r.event(self.home, self.rom, 'gameStop', es=True)
                self.assertEqual(self.binary.read_bytes(), before)
            overrides.return_value.get.return_value = 'on'
            r.event(self.home, self.rom, 'gameStart', es=True)
            self.assertEqual(self.binary.read_bytes(), before)

    def test_reenabling_in_es_recovers_a_mask_left_by_an_interrupted_session(self):
        before = self.binary.read_bytes()
        with patch('es_options.Overrides') as overrides:
            overrides.return_value.get.return_value = 'off'
            r.event(self.home, self.rom, 'gameStart', es=True)
            self.assertFalse(self.binary.exists())
            overrides.return_value.get.return_value = None
            r.event(self.home, self.rom, 'gameStart', es=True)
        self.assertEqual(self.binary.read_bytes(), before)

    def test_changed_dll_is_not_overwritten_on_restore(self):
        e.toggle(self.home,self.rom,False)
        self.binary.write_bytes(b'new DLL installed by user')
        with self.assertRaises(ValueError): e.release(self.home,self.rom)
        self.assertEqual(self.binary.read_bytes(),b'new DLL installed by user')
        self.assertTrue(list((self.home/'reshade/external-journals').rglob('*.json')))

    def test_unsupported_and_active_games_are_not_modified(self):
        self.binary.rename(self.folder/'ReShade64.dll')
        self.assertEqual(e.state(e.scan_game(self.home,self.rom)), 'external-unsupported')
        with self.assertRaises(ValueError): e.toggle(self.home,self.rom,False)
        self.assertEqual(self.autorun.read_text(),self.original)
        (self.folder/'ReShade64.dll').rename(self.binary)
        with patch.object(e,'ensure_idle',side_effect=ValueError('active')):
            with self.assertRaises(ValueError): e.toggle(self.home,self.rom,False)
        self.assertEqual(self.autorun.read_text(),self.original)
        self.assertFalse(r.read_json(e.config_path(self.home,self.rom))['controlled'])

    def test_masks_only_verified_reshade_asi_plugins_and_restores_them(self):
        self.binary.write_bytes(b'third-party Direct3D wrapper')
        fov = self.folder/'FOV.asi'
        unrelated = self.folder/'Other'/'ReShade32.asi'
        unrelated.parent.mkdir()
        fov.write_bytes(b'FOV plugin')
        unrelated.write_bytes(dll().replace(b'i\0n\0j\0e\0c\0t\0o\0r\0', b'other resource!!'))
        plugin = self.folder/'ReShade.asi'
        named_x86 = self.folder/'ReShade32.asi'
        x64 = self.folder/'ReShade64.asi'
        x86 = dll(arch=32)
        plugin.write_bytes(x86)
        named_x86.write_bytes(x86)
        x64.write_bytes(dll())
        cfg = e.scan_game(self.home, self.rom)
        self.assertEqual({Path(f['path']).name: f['arch'] for f in cfg['files']},
                         {'ReShade.asi': 32, 'ReShade32.asi': 32, 'ReShade64.asi': 64})
        e.toggle(self.home, self.rom, False)
        self.assertFalse(plugin.exists())
        self.assertFalse(named_x86.exists())
        self.assertFalse(x64.exists())
        self.assertEqual(self.binary.read_bytes(), b'third-party Direct3D wrapper')
        self.assertEqual(fov.read_bytes(), b'FOV plugin')
        self.assertTrue(unrelated.is_file())
        e.toggle(self.home, self.rom, True)
        self.assertEqual(plugin.read_bytes(), x86)
        self.assertEqual(named_x86.read_bytes(), x86)
        self.assertEqual(x64.read_bytes(), dll())

    def test_cached_lists_include_external_and_managed_without_scanning(self):
        cfg=e.scan_game(self.home,self.rom)
        with patch.object(e,'scan_game',side_effect=AssertionError('scan in list')):
            self.assertEqual(r.configured_games(self.home),[(str(self.rom),'external-enabled')])
            self.assertEqual(r.list_statuses(self.home,[str(self.rom)]),[(str(self.rom),'external-enabled')])
        r.save_json(self.home/'reshade/games'/(r.key(self.rom)+'.json'),{'rom':str(self.rom),'enabled':False})
        self.assertEqual(r.configured_games(self.home),[(str(self.rom),'disabled')])

    def test_global_installer_payload_is_not_a_game_installation(self):
        resources = self.rom/'drive_c/ProgramData/ReShade'
        resources.mkdir(parents=True)
        for name in ('ReShade32.dll', 'ReShade64.dll'):
            (resources/name).write_bytes(dll())
        self.assertEqual([f['path'] for f in e.scan_game(self.home,self.rom)['files']],
                         ['drive_c/game/dxgi.dll'])
        self.binary.unlink()
        self.assertEqual(e.state(e.scan_game(self.home,self.rom)), 'missing')
        # Other ProgramData directories can contain actual game installations.
        game = self.rom/'drive_c/ProgramData/SomeGame'; game.mkdir()
        (game/'d3d9.dll').write_bytes(dll())
        self.assertEqual(e.state(e.scan_game(self.home,self.rom)), 'external-enabled')

    def test_stale_archive_index_is_filtered_without_reopening_archive(self):
        archive = self.base/'AC2.wsquashfs'; archive.touch()
        files = [{'path':'drive_c/PROGRAMDATA/reshade/ReShade32.dll','controllable':False}]
        cfg = {'rom':str(archive),'signature':e.signature(archive),'scan_version':e.SCAN_VERSION,
               'files':files,'enabled':True}
        r.save_json(e.config_path(self.home,archive),cfg)
        with patch.object(e,'find_dlls',side_effect=AssertionError('archive reopened')):
            self.assertEqual(r.configured_games(self.home), [])
            self.assertEqual(r.list_statuses(self.home,[str(archive)]),[(str(archive),'missing')])
            self.assertEqual(e.scan_game(self.home,archive)['files'], [])
        self.assertEqual(r.read_json(e.config_path(self.home,archive))['files'], [])

    def test_archive_mask_and_restore_do_not_change_archive_or_autorun(self):
        archive=self.base/'Packed.wsquashfs';archive.write_bytes(b'archive untouched')
        upper=self.base/'bottle.wine';upper.mkdir()
        cfg={'rom':str(archive),'files':[{'path':'drive_c/game/dxgi.dll','controllable':True}],'controlled':True,'enabled':False}
        r.save_json(e.config_path(self.home,archive),cfg)
        # Model whiteout creation where the test runner lacks CAP_MKNOD.
        whiteouts=set();original_id=e.file_id
        def create(path,*_): Path(path).touch();whiteouts.add(str(path))
        def identify_file(path):
            if path.name=='dxgi.dll' and path.exists(): return {'whiteout':True}
            return original_id(path)
        original_read=Path.read_text
        read=lambda path,*args,**kwargs: 'mount -t overlay upperdir=' if str(path)=='/usr/bin/batocera-wine' else original_read(path,*args,**kwargs)
        with patch.object(e,'locations',return_value=(upper,upper)),patch.object(Path,'read_text',read),patch.object(e.os,'mknod',side_effect=create):
            # Direct helper exercise uses the actual config and a mocked mount-capability probe.
            r.event(self.home,archive,'gameStart')
        target=upper/'drive_c/game/dxgi.dll'
        self.assertTrue(target.exists())
        self.assertFalse((upper/'autorun.cmd').exists())
        with patch.object(e,'file_id',side_effect=identify_file),patch.object(e,'locations',return_value=(upper,upper)),patch.object(Path,'read_text',read):
            r.event(self.home,archive,'gameStart')
            e.release(self.home,archive)
        self.assertFalse(target.exists())
        self.assertEqual(archive.read_bytes(),b'archive untouched')

    def test_whiteout_failure_keeps_existing_dll_and_state(self):
        archive=self.base/'Packed.wsquashfs';archive.touch()
        upper=self.base/'bottle.wine';(upper/'drive_c/game').mkdir(parents=True)
        target=upper/'drive_c/game/dxgi.dll';target.write_bytes(dll())
        cfg={'files':[{'path':'drive_c/game/dxgi.dll','controllable':True}], 'controlled':True,'enabled':False}
        with patch.object(e,'locations',return_value=(upper,upper)),patch.object(Path,'read_text',return_value='mount -t overlay upperdir='),patch.object(e.os,'mknod',side_effect=PermissionError()):
            with self.assertRaises(ValueError): e.apply(self.home,archive,desired=cfg)
        self.assertEqual(target.read_bytes(),dll())

    def test_es_masks_the_archived_injector_in_the_bottle_only(self):
        archive = self.base/'Packed.wsquashfs'
        original = b'unchanged SquashFS archive'
        archive.write_bytes(original)
        upper = self.base/'runner-bottle.wine'
        upper.mkdir()
        plugin = 'drive_c/Beyond Good and Evil/ReShade.asi'
        target = upper/plugin
        r.save_json(e.config_path(self.home, archive), {
            'rom': str(archive), 'signature': e.signature(archive), 'controlled': False,
            'enabled': True, 'files': [],
        })
        read = Path.read_text
        file_id = e.file_id
        with patch('es_options.Overrides') as options, \
                patch.object(e, 'find_dlls', return_value=[plugin]) as scan, \
                patch.object(e, 'source_header', return_value=dll(arch=32)) as read_dll, \
                patch.object(e, 'locations', return_value=(upper, upper)), \
                patch.object(Path, 'read_text', lambda path, *a, **kw:
                             'mount -t overlay upperdir=' if str(path) == '/usr/bin/batocera-wine'
                             else read(path, *a, **kw)), \
                patch.object(e.os, 'mknod', lambda path, *_: Path(path).touch()), \
                patch.object(e, 'file_id', lambda path:
                             {'whiteout': True} if path == target and path.exists() else file_id(path)):
            options.return_value.get.return_value = 'off'
            r.event(self.home, archive, 'gameStart', es=True)
            scan.assert_called_once_with(archive)
            read_dll.assert_called_once_with(archive, plugin, 64*1024*1024)
            self.assertTrue(target.exists())
            self.assertEqual(archive.read_bytes(), original)
            r.event(self.home, archive, 'gameStop', es=True)
            self.assertFalse(target.exists())
            options.return_value.get.return_value = 'on'
            r.event(self.home, archive, 'gameStart', es=True)
            self.assertFalse(target.exists())
        self.assertEqual(archive.read_bytes(), original)

    def test_es_masks_the_archived_injector_after_restoring_a_managed_install(self):
        archive = self.base/'Managed.wsquashfs'
        archive.write_bytes(b'original archive')
        upper = self.base/'runner-bottle.wine'
        target = upper/'drive_c/game/d3d9.dll'
        target.parent.mkdir(parents=True)
        config = self.home/'reshade/games'/(r.key(archive)+'.json')
        journal = r.journal_path(self.home, archive, upper, upper)
        r.save_json(e.config_path(self.home, archive), {
            'rom': str(archive), 'signature': e.signature(archive), 'controlled': False,
            'scan_version': e.SCAN_VERSION,
            'enabled': True, 'files': [{'path': 'drive_c/game/d3d9.dll', 'controllable': True}],
        })
        original_read = Path.read_text
        file_id = e.file_id

        def restore_install(home, path):
            self.assertEqual((home, path), (self.home, journal))
            self.assertEqual(target.read_bytes(), b'managed injector')
            target.unlink()
            path.unlink()

        with patch('es_options.Overrides') as options, \
                patch.object(r, 'restore_install', side_effect=restore_install) as restore, \
                patch.object(e, 'locations', return_value=(upper, upper)), \
                patch.object(Path, 'read_text', lambda path, *a, **kw:
                             'mount -t overlay upperdir=' if str(path) == '/usr/bin/batocera-wine'
                             else original_read(path, *a, **kw)), \
                patch.object(e.os, 'mknod', lambda path, *_: Path(path).touch()), \
                patch.object(e, 'file_id', lambda path: {'whiteout': True}
                             if path == target and path.is_file() and path.stat().st_size == 0 else file_id(path)):
            for override, enabled in [('off', True), (None, False)]:
                with self.subTest(override=override, enabled=enabled):
                    target.write_bytes(b'managed injector')
                    r.save_json(journal, {})
                    r.save_json(config, {'enabled': enabled})
                    options.return_value.get.return_value = override
                    r.event(self.home, archive, 'gameStart', es=True)
                    self.assertEqual(target.read_bytes(), b'')
                    self.assertEqual(r.read_json(config)['enabled'], enabled)
                    r.event(self.home, archive, 'gameStop', es=True)
                    self.assertFalse(target.exists())
            self.assertEqual(restore.call_count, 2)
        self.assertEqual(archive.read_bytes(), b'original archive')

    def test_wiki_matching_removes_runner_and_keeps_game_edition(self):
        self.assertEqual(a.game_title('Denshattack[Wine-11.5].wsquashfs'),'Denshattack')
        self.assertEqual(a.game_title('Game_Remastered[GE-Proton11-7-UMU].pc'),'Game Remastered')
        self.assertEqual(a.rank_titles('Game Remastered',['Game 2','Game','Game Remastered'])[0],'Game Remastered')
        self.assertEqual(a.rank_titles('DIRT_4[Wine-11.5].wsquashfs',['Dirt 5','DiRT 4','Dirt'])[0],'DiRT 4')

    def test_real_archive_detection_and_cache(self):
        import shutil
        if not shutil.which('mksquashfs'): self.skipTest('squashfs-tools unavailable')
        archive=self.base/'Beyond+Good+and+Evil[L][AmX].wsquashfs'
        (self.folder/'ReShade32.asi').write_bytes(dll(arch=32))
        (self.folder/'FOV.asi').write_bytes(b'FOV plugin')
        subprocess.run(['mksquashfs',str(self.rom),str(archive),'-noappend','-processors','1'],check=True,capture_output=True)
        cfg=e.scan_game(self.home,archive)
        self.assertEqual({row['path'] for row in cfg['files']},
                         {'drive_c/game/dxgi.dll', 'drive_c/game/ReShade32.asi'})
        with patch.object(e,'find_dlls',side_effect=AssertionError('unchanged archive rescanned')):
            self.assertEqual(e.scan_game(self.home,archive),cfg)

class DiscoveryResultTests(unittest.TestCase):
    def test_individual_failure_does_not_cancel_scan_and_reason_is_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)/'home'; output=io.StringIO()
            paths=['/games/Good.wine','/games/Bad.wsquashfs','/games/Next.wine']
            with patch.object(e,'scan_game',side_effect=[{},ValueError('archive metadata unreadable'),{}]) as scan,contextlib.redirect_stderr(output):
                self.assertEqual(r.scan_external_games(home,paths),(3,2,1))
            self.assertEqual(scan.call_count,3)
            self.assertIn('/games/Bad.wsquashfs',output.getvalue())
            self.assertIn('Reason: archive metadata unreadable',output.getvalue())

    def test_unsquashfs_error_output_is_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);exe=folder/'unsquashfs'
            exe.write_text('#!/bin/sh\necho "Failed to read superblock" >&2\nexit 1\n');exe.chmod(0o755)
            with patch.dict(os.environ,PATH=str(folder)+os.pathsep+os.environ['PATH']):
                with self.assertRaisesRegex(ValueError,'Failed to read superblock'):
                    list(e.find_dlls(folder/'Broken.wsquashfs'))
