import hashlib
import json
from pathlib import Path
import sys
import os
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'toolbox/helpers'))
import community_profiles as cp
from community_service import package_data
from antimicrox_launcher import Store, selected_profile

LAUNCHER = b'<gamecontroller><uniqueID>private-controller</uniqueID><sets><set index="1"><button index="1"><slots><slot><code>65</code><mode>keyboard</mode></slot></slots></button></set></sets></gamecontroller>'
GAME = LAUNCHER.replace(b'65', b'66')
RULE = {'field': 'title', 'match': 'exact', 'value': 'Configuration launcher'}
GAME_RULE = {'field': 'exe', 'match': 'exact', 'value': 'Game.exe'}


class PortableLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root/'source-machine'
        self.home.mkdir()
        self.launcher = self.home/'launcher.amgp'; self.launcher.write_bytes(LAUNCHER)
        self.game = self.home/'game.amgp'; self.game.write_bytes(GAME)
        self.rom = '/userdata/roms/windows/Source-name.wine'
        self.community = cp.Community(self.home)

    def package(self, mode='profiles', rule=GAME_RULE):
        Store(self.home).save(self.rom, mode, str(self.launcher), RULE, str(self.game), rule)
        return self.community.share('antimicrox', self.launcher, 'My Game', 'Complete config', 'Tester', rom=self.rom)[0]

    def test_round_trip_on_another_machine_rebinds_every_path_and_runtime_rule(self):
        for mode, game_rule in [('launcher', None), ('profiles', None), ('profiles', GAME_RULE)]:
            with self.subTest(mode=mode, rule=game_rule):
                package = self.package(mode, game_rule)
                value = package_data(package)
                text = value['profile']
                self.assertNotIn(self.rom, text)
                self.assertNotIn(str(self.home), text)
                self.assertNotIn('private-controller', text)
                self.assertIn('UWT launcher-package-v1', value['metadata']['requirements'])
                # Older clients see an empty mapping at the ordinary root.
                self.assertEqual(len(ET.fromstring(text).find('sets')), 0)
                target_home = self.root/('target-'+package.stem)
                target = cp.Community(target_home)
                path = target.import_package(package, 'antimicrox')
                self.assertIsNone(ET.fromstring(path.read_bytes()).find('uwt_launcher'))
                self.assertIsNone(Store(target_home).load('/userdata/roms/windows/Other.pc'))
                cp.apply_launcher_import(target_home, path, '/userdata/roms/windows/Other.pc', check=True)
                self.assertFalse(Store(target_home).path('/userdata/roms/windows/Other.pc').exists())
                cp.apply_launcher_import(target_home, path, '/userdata/roms/windows/Other.pc')
                config = Store(target_home).load('/userdata/roms/windows/Other.pc', str(path))
                self.assertEqual(config['launcher_rule'], RULE)
                self.assertEqual(config['game_rule'], game_rule)
                self.assertEqual(selected_profile(config, {'title': RULE['value']}), str(path))
                self.assertEqual(selected_profile(config, {'exe': 'Game.exe'}), config['game_profile'] if mode == 'profiles' else '')
                self.assertTrue(Path(config['launcher_profile']).is_relative_to(target_home))
                if mode == 'profiles':
                    self.assertTrue(Path(config['game_profile']).is_relative_to(target_home))
                    self.assertIn(b'<code>66</code>', Path(config['game_profile']).read_bytes())
                self.assertEqual(target.local_profile(value['metadata']), (path, False))
                # Re-exporting an unassigned download must also preserve the bundle.
                second = target.share('antimicrox', path, 'My Game', 'Copy', 'Tester')[0]
                self.assertIsNotNone(cp.launcher_payload(ET.fromstring(package_data(second)['profile'])))

    def test_profile_edited_locally_can_be_assigned_and_exported_without_leaking_identity(self):
        target = cp.Community(self.root/'target')
        path = target.import_package(self.package())
        path.write_bytes(path.read_bytes().replace(b'<sets>', b'<uniqueID>local-pad</uniqueID><sets>', 1))
        cp.apply_launcher_import(target.home, path, '/userdata/roms/windows/Target.wine')
        self.assertIn(b'local-pad', path.read_bytes())
        exported = cp.launcher_export(target.home, path, '/userdata/roms/windows/Target.wine')
        self.assertNotIn(b'local-pad', exported)

    def test_fetch_uses_same_unpacking_as_offline_import(self):
        package = self.package()
        payload = package_data(package)
        target = cp.Community(self.root/'download-machine')
        target.find = lambda *args: payload['metadata']
        target.download = lambda *args: payload['profile'].encode()
        path = target.fetch('antimicrox', payload['metadata']['id'])
        self.assertIsNotNone(cp.imported_launcher(target.home, path))
        path.write_bytes(path.read_bytes()+b'\n')
        self.assertEqual(target.local_profile(payload['metadata']), (path, True))

    def test_missing_second_profile_is_refused_before_rules_are_written(self):
        package = self.package()
        target = cp.Community(self.root/'target')
        path = target.import_package(package)
        config = cp.imported_launcher(target.home, path)
        Path(config['game_profile']).unlink()
        with self.assertRaises(FileNotFoundError):
            cp.apply_launcher_import(target.home, path, '/userdata/roms/windows/Target.wsquashfs', check=True)
        self.assertFalse(Store(target.home).path('/userdata/roms/windows/Target.wsquashfs').exists())

    def test_unknown_schema_duplicate_bundle_and_unsafe_secondary_mapping_are_rejected(self):
        raw = package_data(self.package())['profile']
        for changed in [raw.replace('version="1"', 'version="9"'),
                        raw.replace('</gamecontroller>', '<uwt_launcher version="1"/></gamecontroller>', 1),
                        raw.replace('<mode>keyboard</mode>', '<mode>execute</mode>')]:
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):
                    cp.profile_bytes('antimicrox', changed.encode())

    def test_local_rule_paths_are_refused_and_original_profiles_remain_unchanged(self):
        Store(self.home).save(self.rom, 'launcher', str(self.launcher), dict(RULE, value='/userdata/private'))
        with self.assertRaisesRegex(ValueError, 'local paths'):
            self.community.share('antimicrox', self.launcher, 'Game', 'Test', 'Tester', rom=self.rom)
        self.assertEqual(self.launcher.read_bytes(), LAUNCHER)

    def test_tampered_zip_is_rejected_and_wrong_tool_cannot_be_imported(self):
        package = self.package()
        target = cp.Community(self.root/'target')
        with self.assertRaisesRegex(ValueError, 'different tool'):
            target.import_package(package, 'reshade')
        with zipfile.ZipFile(package) as original:
            contents = {name: original.read(name) for name in original.namelist()}
        contents['profile.amgp'] += b'\n'
        bad = self.root/'tampered.zip'
        with zipfile.ZipFile(bad, 'w') as archive:
            for name, data in contents.items(): archive.writestr(name, data)
        with self.assertRaisesRegex(ValueError, 'checksum'):
            target.import_package(bad)
        self.assertFalse((target.home/'config').exists())

    def test_generic_profile_reused_by_two_launcher_games_requires_game_context(self):
        self.package()
        other = '/userdata/roms/windows/Different.wine'
        Store(self.home).save(other, 'launcher', str(self.launcher), dict(RULE, value='Other launcher'))
        (self.home/'config/antimicrox-games.tsv').write_text(self.rom+'\t'+str(self.launcher)+'\n'+other+'\t'+str(self.launcher)+'\n')
        with self.assertRaisesRegex(ValueError, 'Several launcher games'):
            cp.launcher_export(self.home, self.launcher)
        self.assertIsNotNone(cp.launcher_payload(ET.fromstring(cp.launcher_export(self.home, self.launcher, other))))


    def test_standard_profile_offline_import_does_not_add_launcher_rules(self):
        package = self.community.share('antimicrox', self.launcher, 'Game', 'Standard', 'Tester')[0]
        target = cp.Community(self.root/'target')
        path = target.import_package(package)
        self.assertIsNone(cp.imported_launcher(target.home, path))
        cp.apply_launcher_import(target.home, path, '/userdata/roms/windows/Other.wine')
        self.assertFalse(Store(target.home).path('/userdata/roms/windows/Other.wine').exists())

    def test_large_complete_package_remains_transferable_offline_but_cannot_be_submitted(self):
        self.game.write_bytes(b'<gamecontroller><profilename>'+b'X'*66000+b'</profilename><sets/></gamecontroller>')
        package = self.package()
        with self.assertRaisesRegex(ValueError, '64 KiB'):
            package_data(package)
        target = cp.Community(self.root/'target')
        path = target.import_package(package)
        self.assertIsNotNone(cp.imported_launcher(target.home, path))

    def test_import_menu_restores_previous_assignment_when_rules_cannot_be_saved(self):
        script = r'''
source "$ROOT/toolbox/modules/community.sh"
i18n() { echo Back; }
menu_select() { if [ -f "$WT_HOME/asked" ]; then echo back; else touch "$WT_HOME/asked"; echo assign; fi; }
amx_ensure_installed() { return 0; }; amx_running() { return 1; }
amx_current_profile() { echo /userdata/old.amgp; }
amx_set_profile() { printf '%s\n' "$2" >> "$WT_HOME/assigned"; }
yesno() { return 0; }; msgbox() { :; }
community_cmd() {
  if [ "$1" = launcher-info ]; then echo launcher-package-v1;
  elif [ "$1" = launcher-import ]; then [ "${4:-}" = --check ]; fi
}
community_import_actions antimicrox /userdata/new.amgp AntiMicroX /userdata/roms/windows/Game.wine
'''
        result = subprocess.run(['bash', '-c', script], capture_output=True, text=True, timeout=5,
                                env=dict(os.environ, ROOT=str(ROOT), WT_HOME=str(self.home), WT_LANGUAGE='fr'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.home/'assigned').read_text().splitlines(), ['/userdata/new.amgp', '/userdata/old.amgp'])

    def test_offline_export_has_no_network_submission(self):
        script = r'''
source "$ROOT/toolbox/modules/community.sh"
community_share_game() { echo Game; }
input_text() { echo Example; }
msgbox() { printf '%s' "$2" > "$WT_HOME/result"; }
community_send_package() { touch "$WT_HOME/unwanted-submission"; }
community_cmd() { printf '%s\0' "$@" > "$WT_HOME/export-command"; printf '/userdata/export.zip\nhttps://example.invalid'; }
community_share antimicrox AntiMicroX /userdata/roms/windows/Game.wine /userdata/launcher.amgp local
'''
        result = subprocess.run(['bash', '-c', script], capture_output=True, text=True, timeout=5,
                                env=dict(os.environ, ROOT=str(ROOT), WT_HOME=str(self.home), WT_LANGUAGE='fr'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.home/'unwanted-submission').exists())
        self.assertIn('/userdata/export.zip', (self.home/'result').read_text())
        self.assertEqual((self.home/'export-command').read_bytes().decode().split('\0')[-3:-1], ['--rom', '/userdata/roms/windows/Game.wine'])


    def test_community_menu_exposes_complete_sharing_and_offline_export_in_both_languages(self):
        for language in ('fr', 'en'):
            for action, destination in [('share_game', 'community'), ('export', 'local')]:
                with self.subTest(language=language, action=action), tempfile.TemporaryDirectory() as folder:
                    home = Path(folder)
                    script = r'''
source "$ROOT/toolbox/modules/community.sh"
i18n() { echo Back; }
menu_select() {
  if [ -f "$WT_HOME/asked" ]; then echo back;
  else touch "$WT_HOME/asked"; printf '%s\0' "$@" > "$WT_HOME/options"; echo "$ACTION"; fi
}
amx_choose_game() { echo /userdata/roms/windows/Launcher.wine; }
amx_current_profile() { printf '%s' "$1" > "$WT_HOME/selected"; echo /userdata/launcher.amgp; }
community_share() { printf '%s\0' "$@" > "$WT_HOME/shared"; }
community_menu antimicrox
'''
                    result = subprocess.run(['bash', '-c', script], capture_output=True, text=True, timeout=5,
                        env=dict(os.environ, ROOT=str(ROOT), WT_HOME=str(home), WT_LANGUAGE=language, ACTION=action))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    options = (home/'options').read_bytes().decode().split('\0')
                    self.assertIn('share_game', options[2:-1:2])
                    self.assertIn('export', options[2:-1:2])
                    args = (home/'shared').read_bytes().decode().split('\0')[:-1]
                    self.assertEqual(args[0], 'antimicrox')
                    self.assertEqual(args[2:], ['/userdata/roms/windows/Launcher.wine', '/userdata/launcher.amgp', destination])
                    self.assertEqual((home/'selected').read_text(), '/userdata/roms/windows/Launcher.wine')

    def test_game_configuration_share_does_not_fall_back_to_an_unrelated_profile(self):
        script = r'''
source "$ROOT/toolbox/modules/community.sh"
amx_choose_game() { echo /userdata/roms/windows/Unconfigured.wine; }
amx_current_profile() { :; }
msgbox() { echo "$2"; }
community_share() { touch "$WT_HOME/unwanted-share"; }
community_share_game_config AntiMicroX
'''
        result = subprocess.run(['bash', '-c', script], capture_output=True, text=True, timeout=5,
            env=dict(os.environ, ROOT=str(ROOT), WT_HOME=str(self.home), WT_LANGUAGE='fr'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('pas encore de profil', result.stdout)
        self.assertFalse((self.home/'unwanted-share').exists())


if __name__ == '__main__':
    unittest.main()
