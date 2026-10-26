"""Unassigned profile cleanup must never remove a game's controls."""
import json
from pathlib import Path
import tempfile
import unittest
import test_antimicrox_profiles as profiles_tests
import test_antimicrox_launcher_menus as menu_tests


class UnassignedProfilesTests(unittest.TestCase):
    fixture = profiles_tests.ProfileTests.fixture

    def test_classic_and_alias_assignments_are_excluded(self):
        with tempfile.TemporaryDirectory() as folder:
            service, profile, cfg = self.fixture(folder)
            orphan = profile.parent/'Unused.amgp'; orphan.write_text('<joystick/>')
            alias = service.userdata/'alias.amgp'; alias.symlink_to(profile)
            cfg.write_text(f'/games/Missing.wine\t{alias}\n')
            self.assertEqual(service.list_unassigned(), [orphan])
            self.assertIn(profile, service.list())

    def test_both_launcher_roles_are_protected_without_tsv(self):
        with tempfile.TemporaryDirectory() as folder:
            service, launcher, cfg = self.fixture(folder)
            game = launcher.parent/'Game.amgp'; game.write_text('<joystick/>')
            orphan = launcher.parent/'Unused.amgp'; orphan.write_text('<joystick/>')
            directory = service.home/'config/antimicrox-launchers'; directory.mkdir()
            (directory/'game.json').write_text(json.dumps({'launcher_profile': str(launcher), 'game_profile': str(game)}))
            cfg.unlink()
            self.assertEqual(service.list_unassigned(), [orphan])
            (directory/'game.json').unlink()
            self.assertEqual(set(service.list_unassigned()), {launcher, game, orphan})

    def test_secondary_of_stored_import_is_kept_until_owner_is_deleted(self):
        with tempfile.TemporaryDirectory() as folder:
            service, launcher, cfg = self.fixture(folder)
            game = launcher.parent/'Game.amgp'; game.write_text('<joystick/>'); cfg.unlink()
            registry = service.home/'state/community/imports.json'; registry.parent.mkdir(parents=True)
            registry.write_text(json.dumps({str(launcher): {'launcher_config': {'game_profile': str(game)}}}))
            self.assertEqual(service.list_unassigned(), [launcher])
            service.delete(launcher, service.plan(launcher, unassigned=True)[-1], unassigned=True)
            self.assertEqual(service.list_unassigned(), [game])

    def test_game_assigned_after_confirmation_blocks_deletion(self):
        with tempfile.TemporaryDirectory() as folder:
            service, profile, cfg = self.fixture(folder); cfg.unlink()
            token = service.plan(profile, unassigned=True)[-1]
            cfg.write_text(f'/games/New.wine\t{profile}\n'); before = cfg.read_bytes()
            with self.assertRaisesRegex(ValueError, 'assigned to a game'):
                service.delete(profile, token, unassigned=True)
            self.assertTrue(profile.is_file()); self.assertEqual(cfg.read_bytes(), before)

    def test_launcher_added_after_confirmation_blocks_deletion(self):
        with tempfile.TemporaryDirectory() as folder:
            service, profile, cfg = self.fixture(folder); cfg.unlink()
            token = service.plan(profile, unassigned=True)[-1]
            directory = service.home/'config/antimicrox-launchers'; directory.mkdir()
            (directory/'game.json').write_text(json.dumps({'game_profile': str(profile)}))
            with self.assertRaisesRegex(ValueError, 'launcher configuration'):
                service.delete(profile, token, unassigned=True)
            self.assertTrue(profile.is_file())

    def test_invalid_configuration_error_is_not_silently_hidden(self):
        with tempfile.TemporaryDirectory() as folder:
            service, profile, cfg = self.fixture(folder); cfg.unlink()
            directory = service.home/'config/antimicrox-launchers'; directory.mkdir()
            (directory/'bad.json').write_text('[]')
            with self.assertRaisesRegex(ValueError, 'Invalid launcher configuration'):
                service.list_unassigned()


class UnassignedMenuTests(unittest.TestCase):
    bash = menu_tests.LauncherMenuTests.bash

    def test_picker_only_requests_unassigned_profiles_and_cannot_browse_others(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            result = self.bash(home, r'''
amx_profiles_cmd() { printf '%s\n' "$*" >> "$WT_HOME/calls"; echo /userdata/Unused.amgp; }
menu_select() {
  printf '%s\0' "$@" > "$WT_HOME/options"
  if [ ! -f "$WT_HOME/selected" ]; then touch "$WT_HOME/selected"; echo 1; else echo back; fi
}
amx_delete_profile_for() { printf '%s\0' "$@" > "$WT_HOME/deleted"; }
amx_delete_profiles
''')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((home/'calls').read_text().splitlines(), ['list-unassigned', 'list-unassigned'])
            options = (home/'options').read_bytes().decode().split('\0')
            self.assertIn('Unused.amgp', options[3]); self.assertNotIn('other', options)
            self.assertEqual((home/'deleted').read_bytes().decode().split('\0')[:-1], ['/userdata/Unused.amgp', '1'])

    def test_empty_list_shows_message_without_opening_picker(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            result = self.bash(home, r'''
amx_profiles_cmd() { :; }
menu_select() { touch "$WT_HOME/wrong-picker"; }
msgbox() { printf '%s' "$2" > "$WT_HOME/message"; }
amx_delete_profiles
''')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((home/'wrong-picker').exists())
            self.assertIn('Aucun profil sans jeu associé', (home/'message').read_text())

    def test_preview_and_deletion_both_require_unassigned_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            result = self.bash(home, r'''
amx_running() { return 1; }
amx_profiles_cmd() {
  printf '%s\n' "$*" >> "$WT_HOME/calls"
  [ "$1" != plan ] || printf 'review-token\nUnused.amgp\n'
  return 0
}
yesno() { printf '%s' "$2" > "$WT_HOME/confirmation"; return 0; }
msgbox() { :; }
amx_delete_profile_for /userdata/Unused.amgp 1
''')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((home/'calls').read_text().splitlines(),
                             ['plan /userdata/Unused.amgp --unassigned', 'delete /userdata/Unused.amgp review-token --unassigned'])
            self.assertIn('aucun jeu', (home/'confirmation').read_text())
            self.assertNotIn('Toutes ses associations', (home/'confirmation').read_text())


if __name__ == '__main__':
    unittest.main()
