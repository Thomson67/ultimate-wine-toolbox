import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'toolbox/helpers'))
import v41_savedir as saves
import v41_savedir_patch as patcher
import v41_savedir_service as service


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
        self.version = self.base / 'batocera.version'
        self.release.write_text('PRETTY_NAME="Batocera.linux 41"\nVERSION_ID=2024.11\n')
        self.original = '#!/bin/bash\n' + ''.join(
            name + '() {\n    WINE_ENV=$(getWine_var "${WINEPOINT}" "ENV" "")\n    echo launch\n}\n'
            for name in ('play_wine', 'play_squashfs'))
        self.target.write_text(self.original); self.target.chmod(0o755)
        self.helper = Path(saves.__file__)

    def manage(self, action):
        patcher.manage(action, self.target, self.state, self.release, self.helper, self.version)

    def test_official_version_file_works_without_version_in_pretty_name(self):
        self.release.write_text('PRETTY_NAME="Batocera.linux"\nVERSION_ID=2024.11\n')
        for version in ('41 2025/03/01 12:00', '41copu.1 2025/03/01', '41-dev abc', '41.1', '41'):
            with self.subTest(version=version):
                self.version.write_text(version)
                self.manage('install')
                self.assertEqual(self.target.read_text().count(patcher.MARKER), 2)
                self.manage('remove')

    def test_official_file_takes_priority_and_rejects_other_major_versions(self):
        for version in ('40', '42', '43copuv.1', '410', '2024.11'):
            with self.subTest(version=version):
                self.version.write_text(version)
                with self.assertRaisesRegex(ValueError, 'detected:'):
                    self.manage('install')
                self.assertEqual(self.target.read_text(), self.original)

    def test_pretty_name_fallback_accepts_v41_custom_suffix(self):
        self.release.write_text('PRETTY_NAME="Batocera.linux 41copu.1"\n')
        self.manage('install')
        self.assertEqual(self.target.read_text().count(patcher.MARKER), 2)

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


class BootTests(unittest.TestCase):
    def setUp(self):
        PatchTests.setUp(self)
        self.service_file = self.base / 'services/uwt_v41_savedir'
        self.registry = {'other_service'}
        self.fail_enable = False
        original_run = subprocess.run
        original_output = subprocess.check_output

        def run(args, **kwargs):
            if args[0] != 'services':
                return original_run(args, **kwargs)
            if args[1] == 'enable':
                if self.fail_enable:
                    raise subprocess.CalledProcessError(1, args)
                self.registry.add(args[2])
            elif args[1] == 'disable':
                self.registry.discard(args[2])
            return subprocess.CompletedProcess(args, 0)

        def output(args, **kwargs):
            if args[0] == 'settings':
                return ' '.join(sorted(self.registry))
            return original_output(args, **kwargs)

        self.mock_run = patch.object(subprocess, 'run', side_effect=run)
        self.mock_output = patch.object(subprocess, 'check_output', side_effect=output)
        self.mock_run.start(); self.addCleanup(self.mock_run.stop)
        self.mock_output.start(); self.addCleanup(self.mock_output.stop)

    def call(self, action):
        service.persistent(action, self.target, self.state, self.release, self.version,
                           self.service_file, self.helper.parent, 'services', 'settings')

    def test_enable_reboot_and_disable_keep_other_services(self):
        self.call('enable')
        self.assertEqual(self.registry, {'other_service', service.SERVICE})
        self.assertTrue((self.state / 'enabled').is_file())
        self.assertIn(service.SERVICE_MARKER, self.service_file.read_text())
        self.assertTrue((self.state / 'v41_savedir_service.py').is_file())
        self.target.write_text(self.original)  # Simulate the OS resetting /usr on reboot.
        self.call('boot')
        self.assertEqual(self.target.read_text().count(patcher.MARKER), 2)
        self.call('disable')
        self.assertEqual(self.target.read_text(), self.original)
        self.assertEqual(self.registry, {'other_service'})
        self.assertFalse(self.service_file.exists())
        self.assertFalse((self.state / 'enabled').exists())
        self.call('boot')
        self.assertEqual(self.target.read_text(), self.original)

    def test_upgrade_to_v42_is_skipped_and_disable_preserves_new_launcher(self):
        self.call('enable')
        self.version.write_text('42 2026/01/01')
        self.target.write_text('#!/bin/bash\n# native v42 launcher\n')
        self.call('boot')
        self.assertEqual(self.target.read_text(), '#!/bin/bash\n# native v42 launcher\n')
        self.call('disable')
        self.assertEqual(self.target.read_text(), '#!/bin/bash\n# native v42 launcher\n')
        self.assertFalse((self.state / 'state.json').exists())

    def test_foreign_service_collision_is_preserved(self):
        self.service_file.parent.mkdir()
        self.service_file.write_text('another service')
        with self.assertRaises(ValueError): self.call('enable')
        self.assertEqual(self.target.read_text(), self.original)
        self.assertEqual(self.service_file.read_text(), 'another service')

    def test_registry_failure_rolls_back_new_activation(self):
        self.fail_enable = True
        with self.assertRaises(subprocess.CalledProcessError): self.call('enable')
        self.assertEqual(self.target.read_text(), self.original)
        self.assertEqual(self.registry, {'other_service'})
        self.assertFalse(self.service_file.exists())
        self.assertFalse((self.state / 'enabled').exists())

    def test_changed_launcher_blocks_restore_but_disables_boot(self):
        self.call('enable')
        self.target.write_text(self.target.read_text() + '# other edit\n')
        with self.assertRaises(ValueError): self.call('disable')
        self.assertNotIn(service.SERVICE, self.registry)
        self.assertFalse((self.state / 'enabled').exists())
        self.assertTrue(self.target.read_text().endswith('# other edit\n'))
        self.assertTrue((self.state / 'original.sh').exists())

    def test_refresh_only_updates_previously_enabled_installations(self):
        self.call('refresh')
        self.assertEqual(self.target.read_text(), self.original)
        self.call('enable')
        self.call('refresh')
        self.assertTrue((self.state / 'enabled').is_file())
        self.assertIn(service.SERVICE, self.registry)
