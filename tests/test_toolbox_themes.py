import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ToolboxThemeTests(unittest.TestCase):
    def shell(self, home, code, **extra):
        return subprocess.run(['bash', '-c', '''source "$WT_ROOT/lib/common.sh"
WT_CONFIG="$TEST_HOME/config"; mkdir -p "$WT_CONFIG"
WT_LANGUAGE=fr; load_i18n
source "$WT_ROOT/modules/settings.sh"
'''+code], env=dict(os.environ, WT_ROOT=str(ROOT/'toolbox'), TEST_HOME=str(home), **extra),
            text=True, capture_output=True, timeout=10)

    @unittest.skipUnless(shutil.which('dialog'), 'Dialog required for its complete theme schema')
    def test_palettes_cover_all_roles_and_selected_backgrounds_remain_distinct(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            for preset in ('standard', 'dark', 'colorblind', 'contrast'):
                for columns in ('0', '1'):
                    with self.subTest(preset=preset, columns=columns):
                        result = self.shell(home, '''printf '%s\\n' "$PRESET" > "$WT_CONFIG/theme"
command dialog --create-rc "$TEST_HOME/theme.rc"
WT_MENU_GAME_COLUMNS="$COLUMNS_FLAG" wt_apply_dialog_theme "$TEST_HOME/theme.rc"
''', PRESET=preset, COLUMNS_FLAG=columns, TERM='xterm')
                        self.assertEqual(result.returncode, 0, result.stderr)
                        colors = dict(re.findall(r'^(\w+_color)\s*=\s*(.*)$', (home/'theme.rc').read_text(), re.M))
                        self.assertGreater(len(colors), 30)
                        if preset == 'standard':
                            continue
                        tuples = {key: re.fullmatch(r'\((BLACK|WHITE|BLUE|CYAN|YELLOW),(BLACK|WHITE|BLUE|CYAN|YELLOW),(ON|OFF)\)', val)
                                  for key, val in colors.items()}
                        self.assertTrue(all(tuples.values()), colors)
                        self.assertNotEqual(tuples['dialog_color'][2], tuples['item_selected_color'][2])
                        self.assertNotEqual(tuples['dialog_color'][2], tuples['button_active_color'][2])
                        for key, match in tuples.items():
                            if key != 'shadow_color':
                                self.assertNotEqual(match[1], match[2], key)
                        if preset == 'colorblind':
                            self.assertNotRegex(str(colors), r'RED|GREEN')
                        if preset == 'contrast':
                            self.assertNotRegex(str(colors), r'BLUE|CYAN|YELLOW|RED|GREEN')
                        if columns == '1':
                            self.assertEqual(tuples['tag_color'][3], 'ON')

    def test_preview_confirmation_keeps_or_restores_choice_and_invalid_config_falls_back(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            for answer in ('yes', 'no', 'escape'):
                with self.subTest(answer=answer):
                    (home/'step').unlink(missing_ok=True)
                    result = self.shell(home, '''printf '%s\\n' standard > "$WT_CONFIG/theme"
menu_select() {
 if [ ! -f "$TEST_HOME/step" ]; then touch "$TEST_HOME/step"; printf dark; else printf back; fi
}
yesno_default_no() {
 wt_theme_name > "$TEST_HOME/preview"
 case "$ANSWER" in yes) return 0;; no) return 1;; *) return 255;; esac
}
theme_menu
wt_theme_name
''', ANSWER=answer)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual((home/'preview').read_text(), 'dark')
                    self.assertEqual(result.stdout, 'dark' if answer == 'yes' else 'standard')
                    # A new process reloads the saved selection.
                    self.assertEqual(self.shell(home, 'wt_theme_name').stdout, result.stdout)
                    self.assertEqual(list((home/'config').glob('*.tmp.*')), [])
            result = self.shell(home, '''printf '%s\\n' '../invalid' > "$WT_CONFIG/theme"; wt_theme_name''')
            self.assertEqual(result.stdout, 'standard')

    def test_theme_is_nested_in_display_and_keyboard_remains_in_tools(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            result = self.shell(home, '''menu_select() { printf '%s\\n' "$@" > "$TEST_HOME/menu"; printf 0; }
settings_menu
cp "$TEST_HOME/menu" "$TEST_HOME/settings"
display_mode_menu
''')
            self.assertEqual(result.returncode, 0, result.stderr)
            settings = (home/'settings').read_text().splitlines()
            display = (home/'menu').read_text().splitlines()
            self.assertIn('Affichage / Display', settings)
            self.assertNotIn('Thème de la Toolbox', settings)
            self.assertNotIn('k', settings)
            self.assertIn('Thème de la Toolbox', display)
            self.assertIn('virtual_keyboard_menu', (ROOT/'toolbox/modules/graphics.sh').read_text())


if __name__ == '__main__':
    unittest.main()
