import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'toolbox/helpers'))
import v41_savedir as saves
import v41_savedir_patch as patcher


class SavesTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.prefix = self.base / 'Game.wine'
        (self.prefix / 'drive_c/game').mkdir(parents=True)
        self.root = self.base / 'saves'

    def run_save(self, rules, rom='Game.wsquashfs'):
        (self.prefix / 'autorun.cmd').write_text(rules)
        saves.prepare(self.prefix, rom, self.root)

    def test_directory_preserves_external_priority_and_local_backup(self):
        local = self.prefix / 'drive_c/game/save'; local.mkdir()
        (local / 'slot').write_text('archive')
        (local / 'new').write_text('seed')
        external = self.root / 'Game'; external.mkdir(parents=True)
        (external / 'slot').write_text('progress')
        self.run_save('SAVEDIR=drive_c/game/save/\r\n')
        self.assertEqual(local.resolve(), external)
        self.assertEqual((local / 'slot').read_text(), 'progress')
        self.assertEqual((external / 'new').read_text(), 'seed')
        backups = list((external / '.uwt-v41-backups').glob('savedir-*/original/slot'))
        self.assertEqual(backups[0].read_text(), 'archive')
        self.run_save('SAVEDIR=drive_c/game/save/\n')
        self.assertEqual(len(list((external / '.uwt-v41-backups').iterdir())), 1)

    def test_registry_files_preserve_other_prefix_data(self):
        (self.prefix / 'user.reg').write_text('initial registry')
        (self.prefix / 'system.reg').write_text('system')
        self.run_save('SAVEDIR=.\nSAVEFILES=user.reg\n', 'Game.wine')
        self.assertTrue((self.prefix / 'user.reg').is_symlink())
        self.assertEqual((self.root / 'Game/user.reg').read_text(), 'initial registry')
        (self.prefix / 'user.reg').write_text('updated')
        self.run_save('SAVEDIR=.\nSAVEFILES=user.reg\n', 'Game.wine')
        self.assertEqual((self.root / 'Game/user.reg').read_text(), 'updated')
        self.assertEqual((self.prefix / 'system.reg').read_text(), 'system')

    def test_explicit_missing_files_and_patterns(self):
        local = self.prefix / 'drive_c/game/save'; local.mkdir()
        (local / 'slot 1.dat').write_text('one')
        self.run_save('SAVEDIR=drive_c/game/save\nSAVEFILES=slot*.dat;future.dat\n')
        self.assertTrue((local / 'slot 1.dat').is_symlink())
        self.assertTrue((local / 'future.dat').is_symlink())
        (local / 'future.dat').write_text('future')
        self.assertEqual((self.root / 'Game/future.dat').read_text(), 'future')

    def test_profile_alias(self):
        users = self.prefix / 'drive_c/users'; (users / 'root/Saved').mkdir(parents=True)
        (users / 'steamuser').symlink_to('root')
        self.run_save('SAVEDIR=drive_c/users/steamuser/Saved\n')
        self.assertEqual((users / 'root/Saved').resolve(), self.root / 'Game')

    def test_external_links_and_general_directories_are_refused(self):
        local = self.prefix / 'drive_c/game/save'; local.mkdir()
        (local / 'slot').write_text('kept')
        outside = self.base / 'outside'; outside.mkdir()
        (local / 'link').symlink_to(outside)
        with self.assertRaises(ValueError):
            self.run_save('SAVEDIR=drive_c/game/save\n')
        self.assertEqual((local / 'slot').read_text(), 'kept')
        self.assertFalse(local.is_symlink())
        for rule in ('../outside', '.', 'drive_c', 'drive_c/users/root'):
            with self.subTest(rule=rule), self.assertRaises(ValueError):
                self.run_save('SAVEDIR=' + rule + '\n')

    def test_no_rules_do_not_create_save_directory(self):
        self.run_save('DIR=drive_c/game\nCMD=game.exe\n')
        self.assertFalse(self.root.exists())

    def test_existing_foreign_savedir_link_is_preserved(self):
        outside = self.base / 'outside'; outside.mkdir()
        local = self.prefix / 'drive_c/game/save'; local.symlink_to(outside)
        with self.assertRaises(ValueError):
            self.run_save('SAVEDIR=drive_c/game/save\n')
        self.assertEqual(local.resolve(), outside)


class PatchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.base = Path(temp.name); self.target = self.base / 'batocera-wine'
        self.state = self.base / 'state'; self.release = self.base / 'os-release'
        self.release.write_text('PRETTY_NAME="Batocera.linux 41"\nVERSION_ID=2024.11\n')
        self.original = '#!/bin/bash\n' + ''.join(
            name + '() {\n    WINE_ENV=$(getWine_var "${WINEPOINT}" "ENV" "")\n    echo launch\n}\n'
            for name in ('play_wine', 'play_squashfs'))
        self.target.write_text(self.original); self.target.chmod(0o755)
        self.helper = Path(saves.__file__)

    def manage(self, action):
        patcher.manage(action, self.target, self.state, self.release, self.helper)

    def test_install_is_idempotent_and_remove_restores_exact_script(self):
        self.manage('install')
        changed = self.target.read_text()
        self.assertEqual(changed.count(patcher.MARKER), 2)
        self.manage('install'); self.assertEqual(self.target.read_text(), changed)
        self.manage('remove'); self.assertEqual(self.target.read_text(), self.original)
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o755)
        self.manage('remove')

    def test_non_v41_and_unknown_scripts_are_refused(self):
        for version in ('40', '42', '43.1'):
            self.release.write_text(f'PRETTY_NAME="Batocera.linux {version}"\n')
            with self.assertRaises(ValueError): self.manage('install')
            self.assertEqual(self.target.read_text(), self.original)
        self.release.write_text('PRETTY_NAME="Batocera.linux 41"\n')
        self.target.write_text('modified\n')
        with self.assertRaises(ValueError): self.manage('install')
        self.assertEqual(self.target.read_text(), 'modified\n')

    def test_changed_script_is_not_overwritten_on_remove(self):
        self.manage('install'); self.target.write_text(self.target.read_text() + '# other edit\n')
        with self.assertRaises(ValueError): self.manage('remove')
        self.assertTrue(self.target.read_text().endswith('# other edit\n'))
        self.assertTrue((self.state / 'original.sh').exists())

    def test_after_reboot_original_can_be_patched_again(self):
        self.manage('install'); self.target.write_text(self.original)
        self.manage('install'); self.assertEqual(self.target.read_text().count(patcher.MARKER), 2)

    def test_native_save_support_is_not_patched(self):
        self.target.write_text(self.original + '\nsaveFilesToUserdata() { :; }\n')
        with self.assertRaises(ValueError): self.manage('install')
