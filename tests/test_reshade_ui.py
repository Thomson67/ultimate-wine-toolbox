import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReShadeUiTests(unittest.TestCase):
    def environment(self, base):
        return dict(os.environ, WT_ROOT=str(ROOT / 'toolbox'), TEST_HOME=str(base/'home'),
                    WT_LANGUAGE='fr', SUMMARY=str(base/'summary'), CHECKLIST=str(base/'checklist'))

    def test_named_templates_go_straight_to_confirmation_without_checklist(self):
        for model, expected in [('retro', ['crt-royale', 'rsretroarch-shaders', 'scaling-shaders', 'reshade-bur']),
                                ('thomson', ['sweetfx-shaders', 'reshade-shaders-legacy', 'fubax-shaders',
                                             'quintfx', 'prod80-shaders', 'astrayfx-shaders', 'immerse-shaders'])]:
            with tempfile.TemporaryDirectory() as folder:
                base = Path(folder)
                env = dict(self.environment(base), MODEL=model)
                script = '''source "$WT_ROOT/lib/common.sh"
WT_HOME="$TEST_HOME"
source "$WT_ROOT/lang/fr.sh"
source "$WT_ROOT/modules/reshade.sh"
resh_cmd() { case "$1" in exes) printf 'Game.exe\\n' ;; details) return 0 ;; *) return 1 ;; esac; }
resh_api_select() { printf dxgi; }
resh_backend_ready() { return 0; }
input_text() { printf latest; }
menu_select() { if [ "$2" = "$(i18n resh_model_prompt)" ]; then printf '%s' "$MODEL"; else printf 1; fi; }
checklist_select() { touch "$CHECKLIST"; return 1; }
yesno_default_no() { printf '%s' "$2" > "$SUMMARY"; return 1; }
resh_install_game '/games/Test.wine'
'''
                result = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True)
                self.assertEqual(result.stderr, '')
                self.assertFalse((base/'checklist').exists())
                for pack in expected:
                    self.assertIn(pack, (base/'summary').read_text())

    def test_yad_import_and_export_have_correct_modes_and_keep_paths_with_spaces(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            private = base/'bin'
            private.mkdir()
            yad = private/'yad'
            yad.write_text('#!/bin/bash\nprintf "%s\\0" "$@" > "$SUMMARY"\nprintf "%s" "$SELECTED"\n')
            yad.chmod(0o755)
            for mode in ['import', 'export']:
                env = dict(self.environment(base), PATH=str(private)+':'+os.environ['PATH'],
                           MODE=mode, SELECTED=str(base/'My preset.ini'))
                result = subprocess.run(['bash', '-c', '''source "$WT_ROOT/lib/common.sh"
WT_HOME="$TEST_HOME"
WT_LANGUAGE=fr
source "$WT_ROOT/lang/fr.sh"
source "$WT_ROOT/modules/reshade.sh"
resh_preset_file "$MODE" '/games/Example[Runner].wsquashfs'
'''], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, env['SELECTED'])
                flags = (base/'summary').read_bytes().decode().split('\0')
                self.assertIn('--file-selection', flags)
                self.assertEqual('--save' in flags, mode == 'export')
                self.assertEqual('--confirm-overwrite' in flags, mode == 'export')

    def test_active_menu_does_not_scan_the_entire_library(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            env=self.environment(base)
            result=subprocess.run(['bash','-c','''source "$WT_ROOT/lib/common.sh"
WT_HOME="$TEST_HOME"
source "$WT_ROOT/lang/fr.sh"
source "$WT_ROOT/modules/reshade.sh"
mangohud_list_games() { printf 'library traversal was called' > "$SUMMARY"; return 1; }
resh_game_rows enabled
'''],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertFalse((base/'summary').exists())


if __name__ == '__main__':
    unittest.main()
