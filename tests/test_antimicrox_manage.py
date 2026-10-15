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
