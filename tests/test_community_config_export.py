import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'toolbox/helpers'))
import community_profiles as cp
from antimicrox_launcher import Store

PROFILE = b'<gamecontroller><uniqueID>private-pad</uniqueID><sets><set index="1"><button index="1"><slots><slot><code>65</code><mode>keyboard</mode></slot></slots></button></set></sets></gamecontroller>'
RULE = {'field': 'title', 'match': 'exact', 'value': 'Launcher title'}
GAME_RULE = {'field': 'exe', 'match': 'exact', 'value': 'Game.exe'}


class ConfigExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root/'original'; self.home.mkdir()
        self.launcher = self.home/'Launcher.amgp'; self.launcher.write_bytes(PROFILE)
        self.game = self.home/'Game.amgp'; self.game.write_bytes(PROFILE.replace(b'65', b'66'))
        self.standard = self.home/'Standard.amgp'; self.standard.write_bytes(PROFILE.replace(b'65', b'67'))
        self.roms = ['/userdata/roms/windows/Adventure[L][GE-Proton11-7-UMU].wine', '/userdata/roms/windows/Another game.pc']
        config = self.home/'config'; config.mkdir()
        (config/'antimicrox-games.tsv').write_text(self.roms[0]+'\t'+str(self.launcher)+'\n'+self.roms[1]+'\t'+str(self.standard)+'\n')
        Store(self.home).save(self.roms[0], 'profiles', str(self.launcher), RULE, str(self.game), GAME_RULE)

    def shell(self, script, **extra):
        return subprocess.run(['bash', '-c', 'source "$ROOT/toolbox/modules/community.sh"\ni18n() { echo Back; }\n'+script],
            capture_output=True, text=True, timeout=5,
            env=dict(os.environ, ROOT=str(ROOT), WT_HOME=str(self.home), WT_LANGUAGE='fr', **extra))

    def test_one_zip_contains_multiple_complete_portable_configurations(self):
        before = {p: p.read_bytes() for p in [self.launcher, self.game, self.standard]}
        path = cp.export_configs(self.home, self.roms)
        self.assertEqual(cp.config_export_type(path), 'configurations')
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(set(archive.namelist()), {'configurations.json', 'profiles/0001.amgp', 'profiles/0002.amgp'})
            raw = b''.join(archive.read(name) for name in archive.namelist())
            self.assertNotIn(str(self.home).encode(), raw)
            self.assertNotIn(b'/userdata/', raw)
            self.assertNotIn(b'private-pad', raw)
        items = cp.read_config_export(path)
        self.assertEqual([item['game'] for item, _ in items], ['Adventure', 'Another game'])
        self.assertEqual([item['rom_name'] for item, _ in items], [Path(r).name for r in self.roms])
        self.assertIsNotNone(cp.launcher_payload(ET.fromstring(items[0][1])))
        self.assertIsNone(cp.launcher_payload(ET.fromstring(items[1][1])))
        target = cp.Community(self.root/'target-machine')
        imported = target.import_configs(path)
        self.assertEqual(len(imported), 2)
        self.assertFalse((target.home/'config/antimicrox-games.tsv').exists())
        cp.apply_launcher_import(target.home, imported[0][2], '/userdata/roms/windows/Different.wsquashfs')
        config = Store(target.home).load('/userdata/roms/windows/Different.wsquashfs')
        self.assertEqual(config['launcher_rule'], RULE)
        self.assertEqual(config['game_rule'], GAME_RULE)
        self.assertIn(b'<code>66</code>', Path(config['game_profile']).read_bytes())
        self.assertIsNone(cp.imported_launcher(target.home, imported[1][2]))
        self.assertEqual(target.import_configs(path), imported)
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_disabled_launcher_rules_are_not_resurrected_by_backup(self):
        path = cp.export_configs(self.home, self.roms[:1])
        target = cp.Community(self.root/'target-machine')
        profile = target.import_configs(path)[0][2]
        rom = '/userdata/roms/windows/Target.wine'
        cp.apply_launcher_import(target.home, profile, rom)
        Store(target.home).path(rom).unlink()
        (target.home/'config/antimicrox-games.tsv').write_text(rom+'\t'+str(profile)+'\n')
        exported = cp.export_configs(target.home, [rom])
        _, data = cp.read_config_export(exported)[0]
        self.assertIsNone(cp.launcher_payload(ET.fromstring(data)))

    def test_single_game_uses_same_format_without_public_sharing_metadata(self):
        path = cp.export_configs(self.home, self.roms[:1])
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read('configurations.json'))
            self.assertEqual(len(manifest['games']), 1)
            self.assertNotIn('author', manifest['games'][0])
            self.assertNotIn('description', manifest['games'][0])
        self.assertEqual(len(list((self.home/'exports').rglob('*.zip'))), 1)

    def test_validation_failure_creates_no_partial_export(self):
        self.standard.write_text('not an XML profile')
        with self.assertRaises(ET.ParseError):
            cp.export_configs(self.home, self.roms)
        self.assertFalse((self.home/'exports').exists())

    def test_missing_association_is_not_silently_omitted(self):
        with self.assertRaisesRegex(ValueError, 'no available assigned profile'):
            cp.export_configs(self.home, self.roms+['/userdata/roms/windows/Unconfigured.wine'])
        self.assertFalse((self.home/'exports').exists())

    def test_all_members_are_checked_before_importing_any_profiles(self):
        path = cp.export_configs(self.home, self.roms)
        with zipfile.ZipFile(path) as archive:
            values = {name: archive.read(name) for name in archive.namelist()}
        values['profiles/0002.amgp'] += b'\n'
        bad = self.root/'tampered.zip'
        with zipfile.ZipFile(bad, 'w') as archive:
            for name, value in values.items(): archive.writestr(name, value)
        target = cp.Community(self.root/'target-machine')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            target.import_configs(bad)
        self.assertFalse((target.home/'config').exists())

    def test_unexpected_members_and_traversal_are_refused(self):
        path = cp.export_configs(self.home, self.roms[:1])
        with zipfile.ZipFile(path) as archive:
            values = {name: archive.read(name) for name in archive.namelist()}
        bad = self.root/'traversal.zip'
        with zipfile.ZipFile(bad, 'w') as archive:
            for name, value in values.items(): archive.writestr(name, value)
            archive.writestr('../outside', b'bad')
        with self.assertRaisesRegex(ValueError, 'Unexpected'):
            cp.read_config_export(bad)
        self.assertFalse((self.root/'outside').exists())

    def test_bulk_export_has_only_a_game_checklist_and_exports_the_selected_rows(self):
        result = self.shell(r'''
amx_associations() { printf '%s\t%s\n%s\t%s\n/games/missing.wine\t/not-found.amgp\n' "$ROM_A" "$PROFILE_A" "$ROM_B" "$PROFILE_B"; }
amx_launcher_cmd() { [ "$2" != "$ROM_A" ] || echo 1; }
checklist_select() { printf '%s\0' "$@" > "$WT_HOME/checklist"; printf '1\n2\n'; }
input_text() { touch "$WT_HOME/unwanted-metadata-question"; return 99; }
community_send_package() { touch "$WT_HOME/unwanted-submission"; }
msgbox() { printf '%s' "$2" > "$WT_HOME/result"; }
community_cmd() { printf '%s\0' "$@" > "$WT_HOME/export-command"; echo /userdata/export.zip; }
community_share_game_config AntiMicroX '' local
''', ROM_A=self.roms[0], ROM_B=self.roms[1], PROFILE_A=str(self.launcher), PROFILE_B=str(self.standard))
        self.assertEqual(result.returncode, 0, result.stderr)
        args = (self.home/'export-command').read_bytes().decode().split('\0')[:-1]
        self.assertEqual(args, ['export-configs', *self.roms])
        self.assertFalse((self.home/'unwanted-metadata-question').exists())
        self.assertFalse((self.home/'unwanted-submission').exists())
        options = (self.home/'checklist').read_bytes().decode()
        self.assertIn('[Launcher]', options)
        self.assertNotIn('missing.wine', options)
        self.assertIn('2 configuration(s)', (self.home/'result').read_text())

    def test_export_from_game_menu_has_no_picker_or_metadata_questions(self):
        result = self.shell(r'''
checklist_select() { touch "$WT_HOME/unwanted-picker"; return 99; }
input_text() { touch "$WT_HOME/unwanted-metadata-question"; return 99; }
msgbox() { :; }
community_cmd() { printf '%s\0' "$@" > "$WT_HOME/export-command"; echo /userdata/export.zip; }
community_share antimicrox AntiMicroX "$ROM_A" "$PROFILE_A" local
''', ROM_A=self.roms[0], PROFILE_A=str(self.launcher))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.home/'export-command').read_bytes().decode().split('\0')[:-1], ['export-configs', self.roms[0]])
        self.assertFalse((self.home/'unwanted-picker').exists())
        self.assertFalse((self.home/'unwanted-metadata-question').exists())

    def test_cancelled_or_empty_checklist_creates_no_export(self):
        for mode in ('cancel', 'empty'):
            result = self.shell(r'''
amx_associations() { printf '%s\t%s\n' "$ROM_A" "$PROFILE_A"; }
amx_launcher_cmd() { :; }
checklist_select() { [ "$MODE" = empty ]; }
community_cmd() { touch "$WT_HOME/unwanted-export"; }
community_export_configs AntiMicroX
''', MODE=mode, ROM_A=self.roms[0], PROFILE_A=str(self.launcher))
            self.assertFalse((self.home/'unwanted-export').exists(), result.stderr)

    def test_imported_batch_lists_configurations_without_assigning_them_to_one_wrong_game(self):
        result = self.shell(r'''
community_cmd() { printf 'Adventure\tFirst.wine\t/profiles/first.amgp\nOther\tSecond.pc\t/profiles/second.amgp\n'; }
menu_select() { if [ -f "$WT_HOME/asked" ]; then echo back; else touch "$WT_HOME/asked"; echo 2; fi; }
community_import_actions() { printf '%s\0' "$@" > "$WT_HOME/imported-choice"; }
community_import_config_batch AntiMicroX /userdata/backup.zip /userdata/roms/windows/Context.wine
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.home/'imported-choice').read_bytes().decode().split('\0')[:-1], ['antimicrox', '/profiles/second.amgp', 'AntiMicroX'])


if __name__ == '__main__':
    unittest.main()
