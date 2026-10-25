import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT/'toolbox/modules/antimicrox.sh'


class AssociationManagerTests(unittest.TestCase):
    def bash(self, home, code, **extra):
        return subprocess.run(['bash', '-c', 'source "$MODULE"\n'+code],
            env=dict(os.environ, WT_HOME=str(home), WT_LANGUAGE='fr', MODULE=str(MODULE), **extra),
            text=True, capture_output=True, timeout=10)

    def setup_games(self, home):
        (home/'config').mkdir()
        first = home/'Oddworld [GE].wsquashfs'; first.touch()
        missing = home/'Missing game.wine'
        profile = home/'Shared profile.amgp'
        profile.write_text('<gamecontroller><sets><slot/><slot/></sets></gamecontroller>')
        cfg = home/'config/antimicrox-games.tsv'
        cfg.write_text(f'{first}\t{profile}\n{missing}\t{profile}\n')
        return first, missing, profile, cfg

    def test_existing_assignment_selects_profile_before_related_game(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            result = self.bash(home, r'''
amx_ensure_installed() { echo ensure >> "$WT_HOME/order"; }
amx_profile_file() { echo profile >> "$WT_HOME/order"; echo '/userdata/Max Payne.amgp'; }
amx_validate_profile() { printf '%s' "$1"; }
community_cmd() { [ "$*" = 'suggest-game antimicrox /userdata/Max Payne.amgp' ] || return 1; echo 'Max Payne'; }
community_pick_game() { [ "$2" = 'Max Payne' ] || return 1; echo game >> "$WT_HOME/order"; printf '/games/Max Payne 2.wine\tMax Payne 2'; }
amx_assign_profile_for() { printf '%s\n' "$@" > "$WT_HOME/assigned"; }
amx_assign_existing
''')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((home/'order').read_text().splitlines(), ['ensure', 'profile', 'game'])
            self.assertEqual((home/'assigned').read_text().splitlines(), ['/games/Max Payne 2.wine', '/userdata/Max Payne.amgp'])

    def test_cancel_profile_or_game_selection_never_changes_assignments(self):
        for stage in ('profile', 'game'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as folder:
                home = Path(folder)
                result = self.bash(home, r'''
amx_ensure_installed() { return 0; }
amx_profile_file() { [ "$STAGE" != profile ] || return 1; echo /userdata/MaxPayne.amgp; }
amx_validate_profile() { echo "$1"; }
amx_game_for_profile() { return 1; }
amx_assign_profile_for() { touch "$WT_HOME/changed"; }
amx_assign_existing
''', STAGE=stage)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((home/'changed').exists())

    def test_profile_selector_lists_saved_profiles_and_offers_manual_browsing(self):
        for manual in (False, True):
            with self.subTest(manual=manual), tempfile.TemporaryDirectory() as folder:
                home = Path(folder)
                result = self.bash(home, r'''
i18n() { echo Back; }
amx_profiles_cmd() { printf '/userdata/Max Payne.amgp\n/userdata/Other.amgp\n'; }
menu_select() { printf '%s\n' "$@" > "$WT_HOME/options"; echo "$PICK"; }
amx_browse_profile() { echo /userdata/manual.amgp; }
amx_profile_file
''', PICK='manual' if manual else '1')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), '/userdata/manual.amgp' if manual else '/userdata/Max Payne.amgp')
                self.assertIn('Other.amgp', (home/'options').read_text())
                self.assertIn('manual', (home/'options').read_text())

    def test_missing_runtime_installation_accept_decline_and_failure(self):
        for outcome in ('accept', 'decline', 'fail', 'installed'):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as folder:
                home = Path(folder); helpers = home/'helpers'; helpers.mkdir()
                (helpers/'install-antimicrox.sh').write_text("""#!/bin/bash
[ "$OUTCOME" != fail ] || exit 1
mkdir -p "$WT_HOME/tools/antimicrox"
printf '#!/bin/sh\nexit 0\n' > "$WT_HOME/tools/antimicrox/antimicrox"
chmod +x "$WT_HOME/tools/antimicrox/antimicrox"
touch "$WT_HOME/installed"
""")
                result = self.bash(home, r'''
WT_ROOT="$WT_HOME"
yesno() { touch "$WT_HOME/prompted"; [ "$OUTCOME" != decline ]; }
msgbox() { :; }
if [ "$OUTCOME" = installed ]; then amx_binary() { echo /fake/antimicrox; }; fi
amx_ensure_installed && touch "$WT_HOME/continued"
:
''', OUTCOME=outcome)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((home/'continued').exists(), outcome in ('accept', 'installed'))
                self.assertEqual((home/'prompted').exists(), outcome != 'installed')
                self.assertEqual((home/'installed').exists(), outcome == 'accept')

    def test_list_shows_assigned_games_including_missing_and_last_duplicate(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder); first, missing, profile, cfg = self.setup_games(home)
            absent_profile = home/'Absent profile.amgp'
            with cfg.open('a') as stream:
                stream.write(f'{first}\t{absent_profile}\n')
            result = self.bash(home, '''
i18n() { echo Retour; }
menu_select() { printf '%s\\n' "$@" > "$WT_HOME/menu"; echo back; }
amx_manage_associations
''')
            self.assertEqual(result.returncode, 0, result.stderr)
            menu = (home/'menu').read_text()
            self.assertIn(first.name, menu)
            self.assertIn(missing.name, menu)
            self.assertIn('[jeu absent]', menu)
            self.assertIn('[profil absent]', menu)
            self.assertIn('profil associé : 2', menu)
            self.assertEqual(menu.count(first.name), 1)

    def test_remove_only_selected_assignment_preserves_shared_file(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder); first, missing, profile, cfg = self.setup_games(home)
            result = self.bash(home, '''
i18n() { echo Retour; }
menu_select() { printf '%s\\n' "$@" > "$WT_HOME/menu"; echo remove; }
yesno() { return 0; }
amx_manage_game "$GAME"
''', GAME=str(first))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(cfg.read_text(), f'{missing}\t{profile}\n')
            self.assertTrue(profile.is_file())
            self.assertIn('partagé par 2 jeux', (home/'menu').read_text())

    def test_cancel_remove_keeps_association(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder); first, _, _, cfg = self.setup_games(home)
            before = cfg.read_bytes()
            result = self.bash(home, '''
i18n() { echo Retour; }
menu_select() { if [ -f "$WT_HOME/asked" ]; then echo back; else touch "$WT_HOME/asked"; echo remove; fi; }
yesno() { return 1; }
amx_manage_game "$GAME"
''', GAME=str(first))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(cfg.read_bytes(), before)

    def test_editor_opens_the_selected_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder); _, _, profile, _ = self.setup_games(home)
            binary = home/'fake-editor'
            binary.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > "$WT_HOME/args"\n')
            binary.chmod(0o755)
            result = self.bash(home, '''
amx_binary() { echo "$WT_HOME/fake-editor"; }
amx_running() { return 1; }
amx_log_path() { echo "$WT_HOME/editor.log"; }
amx_validate_profile() { printf '%s\\n' "$1"; }
msgbox() { return 0; }
amx_editor "$PROFILE"
''', PROFILE=str(profile))
            self.assertEqual(result.returncode, 0, result.stderr)
            args = (home/'args').read_text().splitlines()
            self.assertEqual(args[args.index('--profile')+1], str(profile))
            self.assertNotIn('--no-tray', args)

    def test_replace_changes_only_selected_game(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder); first, missing, profile, cfg = self.setup_games(home)
            replacement = home/'Replacement [new].amgp'; replacement.write_text('<gamecontroller/>')
            result = self.bash(home, '''
amx_binary() { echo /fake/antimicrox; }
amx_running() { return 1; }
amx_profile_file() { echo "$REPLACEMENT"; }
amx_validate_profile() { printf '%s\\n' "$1"; }
msgbox() { return 0; }
amx_assign_profile_for "$GAME"
''', GAME=str(first), REPLACEMENT=str(replacement))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(dict(line.split('\t') for line in cfg.read_text().splitlines()),
                             {str(first): str(replacement), str(missing): str(profile)})

    def test_missing_game_can_be_removed_but_not_launched(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder); _, missing, _, _ = self.setup_games(home)
            result = self.bash(home, '''
i18n() { echo Retour; }
menu_select() { if [ -f "$WT_HOME/asked" ]; then echo back; else touch "$WT_HOME/asked"; echo live; fi; }
amx_live_start_for() { touch "$WT_HOME/launched"; }
msgbox() { printf '%s\\n' "$2"; }
amx_manage_game "$GAME"
''', GAME=str(missing))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Jeu introuvable', result.stdout)
            self.assertFalse((home/'launched').exists())


class MainMenuRouteTests(unittest.TestCase):
    def test_numbered_choices_launch_the_expected_actions_in_both_languages(self):
        expected=['live','manage','assign','community:antimicrox','convert','editor','controllers','delete','install']
        for language in ('fr','en'):
            for number, action in enumerate(expected,1):
                with self.subTest(language=language,choice=number), tempfile.TemporaryDirectory() as folder:
                    home=Path(folder); helpers=home/'helpers'; helpers.mkdir()
                    installer=helpers/'install-antimicrox.sh'
                    installer.write_text('#!/bin/bash\nprintf "install\\n" > "$ROUTE"\n');installer.chmod(0o755)
                    code=r'''source "$MODULE"
i18n() { echo Back; }
amx_binary() { echo /fake/antimicrox; }
msgbox() { :; }; yesno() { return 0; }
menu_select() {
 if [ -f "$WT_HOME/menu" ]; then echo 0; else printf '%s\0' "$@" > "$WT_HOME/menu"; echo "$CHOICE"; fi
}
amx_live_choose() { echo live > "$ROUTE"; }
amx_manage_associations() { echo manage > "$ROUTE"; }
amx_choose_game() { echo /games/Game.wine; }
amx_assign_existing() { echo assign > "$ROUTE"; }
community_menu() { echo "community:$1" > "$ROUTE"; }
amx_convert_pad2key() { echo convert > "$ROUTE"; }
amx_editor() { echo editor > "$ROUTE"; }
timeout() { echo controllers > "$ROUTE"; echo 'Fake Controller'; }
amx_delete_profiles() { echo delete > "$ROUTE"; }
amx_launchers_menu() { echo launchers > "$ROUTE"; }
antimicrox_menu
'''
                    result=subprocess.run(['bash','-c',code],capture_output=True,text=True,timeout=5,
                        env=dict(os.environ,MODULE=str(MODULE),WT_HOME=str(home),WT_ROOT=str(home),WT_LANGUAGE=language,
                                 CHOICE=str(number),ROUTE=str(home/'route')))
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertEqual((home/'route').read_text().strip(),action)
                    args=(home/'menu').read_bytes().decode().split('\0')[:-1]
                    self.assertEqual(args[2::2],[str(n) for n in range(1,10)]+['0'])
                    self.assertNotIn('/dev/uinput',args[1])
