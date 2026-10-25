import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT/'toolbox/modules/antimicrox.sh'


class LauncherMenuTests(unittest.TestCase):
    def bash(self, home, code, **extra):
        return subprocess.run(['bash', '-c', 'source "$MODULE"\ni18n() { echo Back; }\n'+code],
                              env=dict(os.environ, MODULE=str(MODULE), WT_HOME=str(home),
                                       WT_ROOT=str(ROOT/'toolbox'), WT_LANGUAGE='fr', **extra),
                              text=True, capture_output=True, timeout=10)

    def test_create_submenu_routes_classic_and_launcher_without_changing_main_numbering(self):
        for choice, expected in [('standard', 'classic'), ('launcher', 'launcher')]:
            with self.subTest(choice=choice), tempfile.TemporaryDirectory() as folder:
                home = Path(folder)
                result = self.bash(home, '''
menu_select() { echo "$CHOICE"; }
amx_live_choose_standard() { echo classic; }
amx_launchers_menu() { echo launcher; }
amx_live_choose
''', CHOICE=choice)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), expected)

    def test_registered_launcher_goes_directly_to_specific_management(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.bash(Path(folder), '''
amx_current_profile() { echo /userdata/Launcher.amgp; }
amx_launcher_cmd() { [ "$1" != configured ] || echo 1; }
amx_manage_launcher_game() { printf 'launcher:%s' "$1"; }
menu_select() { echo 'wrong ordinary menu'; }
amx_manage_game /userdata/roms/windows/New.wine
''')
            self.assertEqual(result.stdout, 'launcher:/userdata/roms/windows/New.wine')

    def test_specific_menu_only_offers_game_profile_when_one_is_assigned(self):
        for game in ('', '/userdata/Game.amgp'):
            with self.subTest(game=game), tempfile.TemporaryDirectory() as folder:
                home = Path(folder)
                result = self.bash(home, '''
amx_current_profile() { echo /userdata/Launcher.amgp; }
amx_launcher_cmd() { [ "$1" != game-profile ] || printf '%s' "$GAME_PROFILE"; }
menu_select() { printf '%s\\0' "$@" > "$WT_HOME/menu"; echo back; }
amx_manage_launcher_game /userdata/roms/windows/New.wine
''', GAME_PROFILE=game)
                self.assertEqual(result.returncode, 0, result.stderr)
                args = (home/'menu').read_bytes().decode().split('\0')[:-1]
                choices = args[2::2]
                self.assertIn('test', choices)
                self.assertIn('rules', choices)
                self.assertIn('edit_launcher', choices)
                self.assertEqual('edit_game' in choices, bool(game))

    def test_game_profile_edit_does_not_reassign_the_launcher_association(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            result = self.bash(home, '''
amx_current_profile() { echo /userdata/Launcher.amgp; }
amx_launcher_cmd() { [ "$1" != game-profile ] || echo /userdata/Game.amgp; }
menu_select() { if [ -f "$WT_HOME/asked" ]; then echo back; else touch "$WT_HOME/asked"; echo edit_game; fi; }
amx_editor() { printf '%s' "$1" > "$WT_HOME/edited"; }
amx_set_profile() { touch "$WT_HOME/incorrect-reassignment"; }
amx_manage_launcher_game /userdata/roms/windows/New.wine
''')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((home/'edited').read_text(), '/userdata/Game.amgp')
            self.assertFalse((home/'incorrect-reassignment').exists())

    def test_disabling_rules_returns_to_classic_management_without_removing_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            result = self.bash(home, '''
amx_current_profile() { echo /userdata/Launcher.amgp; }
amx_launcher_cmd() { if [ "$1" = disable ]; then echo "$2" > "$WT_HOME/disabled"; fi; }
menu_select() { echo classic; }
yesno() { return 0; }; amx_running() { return 1; }
amx_manage_game() { echo "$1" > "$WT_HOME/classic-menu"; }
amx_set_profile() { touch "$WT_HOME/incorrect-reassignment"; }
amx_manage_launcher_game /userdata/roms/windows/New.wine
''')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((home/'disabled').read_text().strip(), '/userdata/roms/windows/New.wine')
            self.assertTrue((home/'classic-menu').exists())
            self.assertFalse((home/'incorrect-reassignment').exists())

    def test_launcher_mode_menu_has_no_duplicate_full_session_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            result = self.bash(home, '''
amx_running() { return 1; }
menu_select() { printf '%s\\0' "$@" > "$WT_HOME/menu"; echo back; }
amx_launcher_setup /userdata/roms/windows/New.wine
''')
            self.assertEqual(result.returncode, 0, result.stderr)
            choices = (home/'menu').read_bytes().decode().split('\0')[2:-1:2]
            self.assertEqual(choices, ['launcher', 'profiles', 'back'])


    def test_direct_share_passes_current_rom_and_profile_in_both_menus(self):
        for launcher in (False, True):
            for accept in (False, True):
                with self.subTest(launcher=launcher, accept=accept), tempfile.TemporaryDirectory() as folder:
                    home = Path(folder)
                    code = r'''
amx_current_profile() { echo /userdata/Launcher.amgp; }
amx_launcher_cmd() { :; }
amx_associations() { :; }
menu_select() {
  if [ -f "$WT_HOME/asked" ]; then echo back;
  else printf '%s\0' "$@" > "$WT_HOME/menu"; touch "$WT_HOME/asked"; echo share; fi
}
yesno() { printf '%s' "$2" > "$WT_HOME/notice"; [ "$ACCEPT" = 1 ]; }
community_share() { printf '%s\0' "$@" > "$WT_HOME/shared"; }
"$MANAGE" /userdata/roms/windows/New.wine
'''
                    result = self.bash(home, code, MANAGE='amx_manage_launcher_game' if launcher else 'amx_manage_game', ACCEPT=str(int(accept)))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('share', (home/'menu').read_bytes().decode().split('\0')[2:-1:2])
                    self.assertTrue((home/'shared').exists())
                    if (home/'shared').exists():
                        self.assertEqual((home/'shared').read_bytes().decode().split('\0')[:-1],
                                         ['antimicrox', 'AntiMicroX', '/userdata/roms/windows/New.wine', '/userdata/Launcher.amgp'])
                    self.assertFalse((home/'notice').exists())

    def test_community_direct_share_does_not_ask_to_select_the_profile_again(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            result = self.bash(home, r'''
source "$WT_ROOT/modules/community.sh"
amx_profile_file() { touch "$WT_HOME/unwanted-picker"; return 1; }
community_share_game() { printf '%s\n%s' "$2" "$4" > "$WT_HOME/context"; echo 'My game'; }
input_text() { echo 'Example'; }
yesno() { return 0; }
community_cmd() { printf '%s\0' "$@" > "$WT_HOME/export"; echo package; }
community_send_package() { echo "$2" > "$WT_HOME/submitted"; }
community_share antimicrox AntiMicroX /userdata/roms/windows/New.wine /userdata/Launcher.amgp
''')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((home/'unwanted-picker').exists())
            self.assertEqual((home/'context').read_text(), '/userdata/Launcher.amgp\n/userdata/roms/windows/New.wine')
            self.assertEqual((home/'export').read_bytes().decode().split('\0')[:3], ['share', 'antimicrox', '/userdata/Launcher.amgp'])
            self.assertEqual((home/'submitted').read_text().strip(), 'package')


if __name__ == '__main__':
    unittest.main()
