import os
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


def dll(supported=True):
    data=bytearray(200);data[:2]=b'MZ';data[60:64]=(64).to_bytes(4,'little');data[64:68]=b'PE\0\0';data[68:70]=(0x8664).to_bytes(2,'little')
    data.extend("crosire's ReShade post-processing injector for 64-bit".encode('utf-16le'))
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

    def test_cached_lists_include_external_and_managed_without_scanning(self):
        cfg=e.scan_game(self.home,self.rom)
        with patch.object(e,'scan_game',side_effect=AssertionError('scan in list')):
            self.assertEqual(r.configured_games(self.home),[(str(self.rom),'external-enabled')])
            self.assertEqual(r.list_statuses(self.home,[str(self.rom)]),[(str(self.rom),'external-enabled')])
        r.save_json(self.home/'reshade/games'/(r.key(self.rom)+'.json'),{'rom':str(self.rom),'enabled':False})
        self.assertEqual(r.configured_games(self.home),[(str(self.rom),'disabled')])

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

    def test_wiki_matching_removes_runner_and_keeps_game_edition(self):
        self.assertEqual(a.game_title('Denshattack[Wine-11.5].wsquashfs'),'Denshattack')
        self.assertEqual(a.game_title('Game_Remastered[GE-Proton11-7-UMU].pc'),'Game Remastered')
        self.assertEqual(a.rank_titles('Game Remastered',['Game 2','Game','Game Remastered'])[0],'Game Remastered')
        self.assertEqual(a.rank_titles('DIRT_4[Wine-11.5].wsquashfs',['Dirt 5','DiRT 4','Dirt'])[0],'DiRT 4')

    def test_real_archive_detection_and_cache(self):
        import shutil
        if not shutil.which('mksquashfs'): self.skipTest('squashfs-tools unavailable')
        archive=self.base/'Game.wsquashfs'
        subprocess.run(['mksquashfs',str(self.rom),str(archive),'-noappend','-processors','1'],check=True,capture_output=True)
        cfg=e.scan_game(self.home,archive)
        self.assertEqual(cfg['files'][0]['path'],'drive_c/game/dxgi.dll')
        with patch.object(e,'find_dlls',side_effect=AssertionError('unchanged archive rescanned')):
            self.assertEqual(e.scan_game(self.home,archive),cfg)
