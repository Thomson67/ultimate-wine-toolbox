"""Custom ES detection and real hook execution against disposable prefixes."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'toolbox/helpers/wine_systems.py'
HOOK = ROOT / 'toolbox/hooks/mangohud-game-event.sh'
spec = importlib.util.spec_from_file_location('wine_systems', HELPER)
ws = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ws)


class WineSystemsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / 'toolbox'
        self.es = self.base / 'es'; self.es.mkdir()
        self.stock = self.base / 'stock.cfg'
        self.roms = self.base / 'roms'
        self.bottles = self.base / 'bottles'
        self.config = self.home / 'config'; self.config.mkdir(parents=True)
        installed = self.home / 'toolbox/helpers'; installed.mkdir(parents=True)
        shutil.copy2(HELPER, installed / HELPER.name)
        self.system('teknoparrot', platform='windows', emulators=('linuxloader-dcg', 'wine', 'windows-arcade-loader'))
        self.system('windows_squash', platform='windows_squash')
        self.fakebin = self.base / 'bin'; self.fakebin.mkdir()
        self.settings = self.base / 'settings.json'; self.settings.write_text('{}')
        self.command('batocera-version', '#!/bin/sh\necho "${TEST_MAJOR:-43}"\n')
        self.command('batocera-settings-get', '#!/usr/bin/env python3\nimport json,os,sys\nd=json.load(open(os.environ["TEST_SETTINGS"]))\nfor k in sys.argv[1:]:\n if d.get(k):\n  print(d[k]);sys.exit(0)\nsys.exit(1)\n')
        self.command('unsquashfs', '#!/usr/bin/env python3\nimport os,sys\nassert sys.argv[1]=="-cat" and sys.argv[3]=="autorun.cmd", sys.argv\nopen(os.environ["TEST_EXTRACT_CALLS"],"a").write(repr(sys.argv[1:])+"\\n")\nprint("DIR=drive_c/game\\nCMD=game.exe\\nENV=KEEP=original")\n')
        self.env = dict(os.environ, WT_HOME=str(self.home),
                        WT_ES_USER_DIR=str(self.es), WT_ES_SYSTEM_FILE=str(self.stock),
                        WT_WINE_BOTTLES_ROOT=str(self.bottles), WT_MANGOHUD_LOG_DIR=str(self.base/'logs'),
                        TEST_SETTINGS=str(self.settings), TEST_EXTRACT_CALLS=str(self.base/'extract.log'),
                        PATH=str(self.fakebin)+os.pathsep+os.environ['PATH'])
        (self.config/'mangohud-global').write_text('1\n')

    def command(self, name, content):
        p=self.fakebin/name; p.write_text(content); p.chmod(0o755)

    def system(self, name, platform='windows', emulators=('wine',), command=None, extensions=None, file=None):
        path=self.roms/name; path.mkdir(parents=True, exist_ok=True)
        root=ET.Element('systemList'); s=ET.SubElement(root, 'system')
        for key,value in {'name':name, 'fullname':name, 'path':str(path), 'platform':platform,
                          'command':command or 'python /userdata/system/dcg/configgen/run.py -system %SYSTEM% -emulator %EMULATOR%',
                          'extension':extensions or '.pc .exe .wine .wsquashfs .wtgz .squashfs .windowsloader'}.items():
            ET.SubElement(s,key).text=value
        es=ET.SubElement(s,'emulators')
        for name_ in emulators: ET.SubElement(es,'emulator',name=name_)
        ET.ElementTree(root).write(file or self.es/f'es_systems_{name}.cfg')
        return path

    def systems(self):
        return ws.discover(self.es,self.stock)

    def select(self,*names):
        ws.atomic_json(self.config/'custom-wine-systems.json',{'enabled':list(names)})

    def game(self, system='teknoparrot', name='Same game.wine'):
        p=self.roms/system/name
        if p.suffix in {'.wine','.pc'}:
            p.mkdir(parents=True,exist_ok=True); (p/'autorun.cmd').write_text('DIR=drive_c/game\nCMD=game.exe\nENV=KEEP=original\n')
        else: p.write_bytes(b'original archive bytes')
        return p

    def ctx(self, rom, system='teknoparrot', emulator='wine', core='wine-tkg', major=43, event='gameStart'):
        return ws.context(argparse.Namespace(home=self.home, rom=str(rom), system=system,
                          emulator=emulator, core=core, major=major, event=event),self.systems())

    def hook(self, rom, system='teknoparrot', emulator='wine', core='wine-tkg', event='gameStart', major=43):
        return subprocess.run(['bash',str(HOOK),event,system,emulator,core,str(rom)],
                              env=dict(self.env,TEST_MAJOR=str(major)),text=True,capture_output=True,check=True)

    def test_both_supplied_system_shapes_and_opt_in(self):
        systems=self.systems()
        self.assertTrue(ws.supported(systems['teknoparrot']))
        self.assertTrue(ws.supported(systems['windows_squash']))
        p=self.game(); self.assertIsNone(self.ctx(p))
        self.select('teknoparrot'); self.assertEqual(self.ctx(p),('teknoparrot','dcg',''))

    def test_platform_alone_and_unknown_launcher_do_not_enable_hooks(self):
        self.system('metadata_only',emulators=('linuxloader-dcg',))
        self.system('unknown',command='/userdata/custom-launcher %ROM%')
        self.select('metadata_only','unknown')
        self.assertIsNone(self.ctx(self.game('metadata_only'),system='metadata_only'))
        self.assertIsNone(self.ctx(self.game('unknown'),system='unknown'))
        self.assertEqual(ws.launcher_kind('echo /userdata/system/dcg/configgen/run.py'),'unknown')
        self.assertEqual(ws.launcher_kind('echo /usr/bin/emulatorlauncher'),'unknown')

    def test_native_custom_launcher(self):
        self.system('custom_native',platform='other',command='/usr/bin/emulatorlauncher -system %SYSTEM%')
        self.select('custom_native')
        self.assertEqual(self.ctx(self.game('custom_native'),system='custom_native'),('custom_native','native',''))

    def test_actual_mixed_emulator_and_core_are_filtered(self):
        self.select('teknoparrot'); p=self.game()
        for emu in ('linuxloader-dcg','windows-arcade-loader','', 'retroarch'):
            self.assertIsNone(self.ctx(p,emulator=emu))
        self.assertIsNone(self.ctx(p,core='linuxloader-dcg'))

    def test_unsupported_formats_and_wrong_root(self):
        self.select('teknoparrot')
        for ext in ('.exe','.squashfs','.windowsloader','.wtgz'):
            self.assertIsNone(self.ctx(self.game(name='Game'+ext)))
        self.assertIsNone(self.ctx(self.game('windows_squash')))

    def test_extensions_declared_in_xml_are_respected(self):
        self.system('restricted',extensions='.wine')
        self.select('restricted')
        self.assertIsNone(self.ctx(self.game('restricted','Game.pc'),system='restricted'))

    def test_windows_alias_cannot_bypass_opt_out(self):
        p=self.game()
        self.assertIsNone(self.ctx(p,system='windows'))
        self.select('teknoparrot')
        self.assertEqual(self.ctx(p,system='windows')[0],'teknoparrot')
        outside=self.base/'Outside.wine';outside.mkdir()
        self.assertEqual(self.ctx(outside,system='windows'),('windows','native',''))

    def test_symlink_escape_and_lexical_escape_are_refused(self):
        self.select('teknoparrot')
        outside=self.base/'Other.wine';outside.mkdir()
        p=self.roms/'teknoparrot'/'Escape.wine';p.symlink_to(outside)
        self.assertIsNone(self.ctx(p))
        self.assertIsNone(self.ctx(self.roms/'teknoparrot'/'..'/'windows_squash'/'Game.wine'))

    def test_xml_override_and_malformed_neighbor(self):
        self.system('teknoparrot',command='/unknown',file=self.stock)
        (self.es/'es_systems_broken.cfg').write_text('<bad')
        self.assertEqual(self.systems()['teknoparrot']['backend'],'dcg')

    def test_v44_dcg_routing_is_not_guessed(self):
        self.select('teknoparrot')
        self.assertIsNotNone(self.ctx(self.game(),major=44))
        self.system('other_dcg');self.select('other_dcg');p=self.game('other_dcg')
        self.assertIsNone(self.ctx(p,system='other_dcg',major=44))
        self.assertIsNotNone(self.ctx(p,system='other_dcg',emulator='wine-dcg',major=44))

    def test_listing_prunes_prefixes_and_omits_unsupported_formats(self):
        self.select('teknoparrot');p=self.game();nested=p/'inside.wine';nested.mkdir()
        archive=self.game(name='Archive.wsquashfs')
        self.game(name='Direct.exe');self.game(name='Tar.wtgz')
        self.assertEqual(set(ws.game_paths(self.systems()['teknoparrot'])),{str(p),str(archive)})

    def test_cli_selection_can_clear_all_and_survives_bad_update(self):
        args=['--home',str(self.home),'--es-user-dir',str(self.es),'--es-system-file',str(self.stock)]
        self.assertEqual(ws.main(args+['select','teknoparrot']),0)
        self.assertEqual(ws.main(args+['select','missing']),1)
        self.assertEqual(ws.enabled(self.home),{'teknoparrot'})
        self.assertEqual(ws.main(args+['select']),0)
        self.assertEqual(ws.enabled(self.home),set())

    def test_direct_prefix_hook_preserves_other_env_and_cleans_on_stop(self):
        self.select('teknoparrot');p=self.game()
        self.hook(p)
        text=(p/'autorun.cmd').read_text();self.assertIn('MANGOHUD=1',text);self.assertIn('KEEP=original',text)
        self.hook(p,event='gameStop')
        text=(p/'autorun.cmd').read_text();self.assertNotIn('MANGOHUD=1',text);self.assertIn('KEEP=original',text)

    def test_cleanup_uses_session_after_deselection_and_xml_removal(self):
        self.select('teknoparrot');p=self.game();self.hook(p)
        self.select();(self.es/'es_systems_teknoparrot.cfg').unlink()
        self.hook(p,event='gameStop',emulator='')
        self.assertNotIn('MANGOHUD=1',(p/'autorun.cmd').read_text())
        self.assertFalse(ws.session_file(self.home,str(p)).exists())

    def test_selected_system_only_and_mixed_native_loader_untouched(self):
        self.select('teknoparrot');p=self.game();original=(p/'autorun.cmd').read_bytes()
        self.hook(p,emulator='linuxloader-dcg');self.assertEqual((p/'autorun.cmd').read_bytes(),original)
        other=self.game('windows_squash');self.hook(other,system='windows_squash')
        self.assertNotIn('MANGOHUD=1',(other/'autorun.cmd').read_text())

    def test_dcg_archive_correct_system_runner_and_no_archive_changes(self):
        self.select('windows_squash');p=self.game('windows_squash','Same.wsquashfs');before=p.read_bytes()
        self.settings.write_text(json.dumps({'windows_squash.core':'wine-proton','windows.wine-runner':'wine-tkg'}))
        self.hook(p,system='windows_squash')
        target=self.bottles/'windows_squash'/'wine-proton'/'Same.wsquashfs.wine'/'autorun.cmd'
        self.assertIn('MANGOHUD=1',target.read_text())
        self.assertEqual(p.read_bytes(),before)
        self.assertFalse((self.bottles/'windows').exists())
        self.settings.write_text(json.dumps({'windows_squash.core':'wine-tkg'}))
        self.hook(p,system='windows_squash',event='gameStop')
        self.assertNotIn('MANGOHUD=1',target.read_text())
        self.assertEqual(len((self.base/'extract.log').read_text().splitlines()),1)

    def test_dcg_42_uses_per_runner_overlay_while_native_42_stays_legacy(self):
        self.select('teknoparrot');p=self.game(name='Game.wsquashfs')
        self.hook(p,major=42)
        self.assertTrue((self.bottles/'teknoparrot/wine-tkg/Game.wsquashfs.wine/autorun.cmd').is_file())
        native=self.base/'Native.wsquashfs';native.write_bytes(b'native')
        self.hook(native,system='windows',major=42)
        self.assertTrue((self.bottles/'windows/Native.wsquashfs/autorun.cmd').is_file())

    def test_native_windows_43_and_per_game_override(self):
        p=self.base/'Native.wsquashfs';p.write_bytes(b'native')
        self.settings.write_text(json.dumps({'windows.core':'proton'}))
        self.hook(p,system='windows')
        target=self.bottles/'windows/wine-proton/Native.wsquashfs.wine/autorun.cmd'
        self.assertIn('MANGOHUD=1',target.read_text())
        self.hook(p,system='windows',event='gameStop')
        self.assertNotIn('MANGOHUD=1',target.read_text())
        self.select('teknoparrot');a=self.game()
        (self.config/'mangohud-games.tsv').write_text('off\t'+str(a)+'\n')
        self.hook(a);self.assertNotIn('MANGOHUD=1',(a/'autorun.cmd').read_text())

    def test_custom_collection_with_stock_wine_uses_windows_namespace(self):
        self.system('native_collection',command='/usr/bin/emulatorlauncher -system windows -emulator wine')
        self.select('native_collection');p=self.game('native_collection','Game.wsquashfs')
        self.settings.write_text(json.dumps({'windows.core':'wine-proton','native_collection.core':'wine-tkg'}))
        self.hook(p,system='windows')
        target=self.bottles/'windows/wine-proton/Game.wsquashfs.wine/autorun.cmd'
        self.assertIn('MANGOHUD=1',target.read_text())
        self.assertFalse((self.bottles/'native_collection').exists())

    def test_native_custom_runner_names_keep_spaces_and_brackets(self):
        p=self.base/'Native.wsquashfs';p.write_bytes(b'native')
        self.settings.write_text(json.dumps({'windows.wine-runner':'My runner [custom]'}))
        self.hook(p,system='windows')
        target=self.bottles/'windows'/'My runner [custom]'/'Native.wsquashfs.wine'/'autorun.cmd'
        self.assertIn('MANGOHUD=1',target.read_text())

    def test_game_labels_distinguish_systems(self):
        p=self.game()
        cmd='source toolbox/modules/graphics.sh\nMANGOHUD_CUSTOM_SYSTEMS="$(mangohud_systems_cmd systems)"\nmangohud_game_label "$TEST_ROM"'
        env=dict(self.env,WT_ROOT=str(ROOT/'toolbox'),TEST_ROM=str(p))
        # Menu invocation uses the standard ES paths; override its small CLI
        # wrapper for this fixture, rather than touching host Batocera paths.
        cmd=cmd.replace('MANGOHUD_CUSTOM_SYSTEMS=', 'mangohud_systems_cmd() { python3 "$WT_ROOT/helpers/wine_systems.py" --home "$WT_HOME" --es-user-dir "$WT_ES_USER_DIR" --es-system-file "$WT_ES_SYSTEM_FILE" "$@"; }\nMANGOHUD_CUSTOM_SYSTEMS=',1)
        p=subprocess.run(['bash','-c',cmd],cwd=ROOT,env=env,capture_output=True,text=True,check=True)
        self.assertEqual(p.stdout,'[teknoparrot] Same game.wine')


if __name__=='__main__':
    unittest.main()
