import os
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReShadeUiTests(unittest.TestCase):
    def environment(self, base):
        return dict(os.environ, WT_ROOT=str(ROOT / 'toolbox'), TEST_HOME=str(base/'home'),
                    WT_LANGUAGE='fr', SUMMARY=str(base/'summary'), CHECKLIST=str(base/'checklist'))

    def test_game_menu_only_offers_actions_valid_for_its_installation_state(self):
        for state in ('missing', 'enabled', 'disabled'):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as folder:
                base = Path(folder)
                result = subprocess.run(['bash', '-c', r'''
WT_HOME="$TEST_HOME"
source "$WT_ROOT/modules/reshade.sh"
i18n() { echo "$1"; }
resh_cmd() {
 case "$1" in
  status) echo "$STATE";;
  external-info) echo missing;;
  details) printf '6.6.0\tx86\td3d9\tGame.exe\tstandard';;
 esac
}
menu_select() { printf '%s\n' "$@" > "$CHECKLIST"; echo back; }
resh_game_menu /games/Game.wine
'''], env=dict(self.environment(base), STATE=state), capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                actions = (base/'checklist').read_text().splitlines()[2::2]
                self.assertIn('install', actions)
                self.assertEqual('import-export' in actions, state != 'missing')
                self.assertIn('community', actions)
                self.assertNotIn('preset', actions)
                self.assertNotIn('export', actions)
                self.assertNotIn('pack', actions)
                self.assertEqual('presets' in actions, state != 'missing')
                self.assertEqual('enable' in actions, state == 'disabled')
                self.assertEqual('disable' in actions, state == 'enabled')
                self.assertEqual('launch' in actions, state == 'enabled')

    def test_installation_offers_launch_only_after_enable_and_preserves_game_path(self):
        for mode in ('launch', 'later', 'failed', 'pending'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                base = Path(folder)
                state = base/'home/state'
                state.mkdir(parents=True)
                request = state/'launch-game.request'
                if mode == 'pending':
                    request.write_text('/games/Other.wine\n')
                script = r'''
WT_HOME="$TEST_HOME"
WT_LOG_DIR="$WT_HOME/logs"
source "$WT_ROOT/modules/reshade.sh"
RESH_BACKEND=/dev/null
i18n() { printf '%s' "$1"; }
community_txt() { printf '%s' "$1"; }
msgbox() { printf '%s\n' "$2" >> "$SUMMARY"; }
yesno_default_no() { :; }
resh_api_select() { printf dxgi; }
resh_version_select() { printf 6.3.3-addons; }
resh_backend_ready() { mkdir -p "$WT_HOME/reshade"; }
resh_prepare_tools() { :; }
menu_select() {
    if [ "$2" = resh_model_prompt ]; then
        printf standard
    else
        printf '%s\n' "$@" > "$CHECKLIST"
        if [ "$MODE" = later ]; then printf later; else printf launch; fi
    fi
}
resh_cmd() {
    case "$1" in
        exes) printf 'Game.exe\n';;
        backend-packs) printf '%s' "$2";;
        status) printf missing;;
        prepare) printf '%s/workspace' "$WT_HOME";;
        enable) [ "$MODE" != failed ];;
    esac
}
resh_install_game '/games/My Game.wsquashfs'
'''
                result = subprocess.run(['bash', '-uc', script],
                                        env=dict(self.environment(base), MODE=mode),
                                        capture_output=True, text=True)
                self.assertEqual(result.stderr, '')
                self.assertEqual(result.returncode, int(mode == 'failed'))
                self.assertEqual((base/'checklist').exists(), mode != 'failed')
                if mode == 'launch':
                    self.assertEqual(request.read_text(), '/games/My Game.wsquashfs\n\nreshade-preset\n')
                elif mode == 'pending':
                    self.assertEqual(request.read_text(), '/games/Other.wine\n')
                    self.assertIn('resh_launch_pending', (base/'summary').read_text())
                else:
                    self.assertFalse(request.exists())

    def test_import_export_routes_actions_with_the_selected_game_context(self):
        expected = {
            'import-ini': ['import-ini', '/games/My Game.wine', '/userdata/My preset.ini'],
            'import-pack': ['pack', '/games/My Game.wine'],
            'export-ini': ['export-ini', '/games/My Game.wine'],
            'export-pack': ['pack-export', 'resh_title — Import / Export', '/games/My Game.wine', 'local'],
        }
        for action, arguments in expected.items():
            with self.subTest(action=action), tempfile.TemporaryDirectory() as folder:
                base = Path(folder)
                script = r'''
source "$WT_ROOT/modules/reshade.sh"
community_txt() { printf '%s' "$1"; }
i18n() { printf '%s' "$1"; }
record() { printf '%s\n' "$@" > "$SUMMARY"; }
resh_cmd() { if [ "$1" = status ]; then printf enabled; else record "$@"; fi; }
menu_select() { if [ -f "$CHECKLIST" ]; then printf back; else printf '%s\n' "$@" > "$CHECKLIST"; printf '%s' "$ACTION"; fi; }
resh_preset_file() { printf '/userdata/My preset.ini'; }
resh_pack_source() { printf '/userdata/My bundle'; }
resh_import_ini() { record import-ini "$@"; }
resh_pack_menu() { record pack "$@"; }
resh_export_game_preset() { record export-ini "$@"; }
community_export_reshade_pack() { record pack-export "$@"; }
community_share() { record share "$@"; }
community_menu() { record catalogue "$@"; }
community_import_package() { record package "$@"; }
resh_import_export_menu '/games/My Game.wine'
'''
                result = subprocess.run(['bash', '-c', script], env=dict(self.environment(base), ACTION=action), capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((base/'summary').read_text().splitlines(), arguments)
                for redundant in ('share-pack','share-ini','community','import-package','pack-presets'):
                    self.assertNotIn(redundant,(base/'checklist').read_text().splitlines())

    def test_local_ini_export_can_choose_an_inactive_variant_without_activating_it(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            script = r'''
source "$WT_ROOT/modules/reshade.sh"
community_txt() { printf '%s' "$1"; }
i18n() { printf '%s' "$1"; }
resh_cmd() {
 case "$1" in
  presets-list) printf '[{"id":"active","name":"Current","active":true},{"id":"other","name":"Other","active":false}]';;
  profile) printf '/userdata/profiles/0123456789abcdef';;
  presets-global-export) printf '%s\n' "$@" > "$SUMMARY";;
  *) echo 'Unexpected mutation' >&2; return 1;;
 esac
}
menu_select() { printf other; }
resh_preset_file() { printf '/userdata/Other preset.ini'; }
msgbox() { :; }
resh_export_game_preset '/games/My Game.wine'
'''
            result = subprocess.run(['bash','-c',script], env=self.environment(base), capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual((base/'summary').read_text().splitlines(), ['presets-global-export','0123456789abcdef','other','/userdata/Other preset.ini','overwrite'])

    def test_diagnostic_resume_returns_to_api_for_the_chosen_executable(self):
        for remembered, changed in [('drive_c/game/Chosen Game.exe',False),('drive_c/game/Removed.exe',True)]:
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as folder:
                base=Path(folder);state=base/'home/state';state.mkdir(parents=True)
                (state/'reshade-diagnostic.json').write_text(json.dumps({'rom':'/games/Game.wine','installation_exe':remembered}))
                result=subprocess.run(['bash','-c','''source "$WT_ROOT/lib/common.sh"
WT_HOME="$TEST_HOME"
source "$WT_ROOT/lang/fr.sh"
source "$WT_ROOT/modules/community.sh"
source "$WT_ROOT/modules/reshade.sh"
msgbox() { return 0; }
resh_cmd() { [ "$1" = exes ] && printf 'drive_c/game/Chosen Game.exe\\ndrive_c/game/Other.exe\\n'; }
menu_select() { printf '%s' "$2" > "$CHECKLIST"; printf 1; }
resh_api_select() { printf 'api:%s\\n' "$2" >> "$SUMMARY"; return 1; }
resh_game_menu() { printf 'game-menu\\n' >> "$SUMMARY"; }
resh_resume_diagnostic
'''],env=self.environment(base),capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual((base/'summary').read_text(),'api:drive_c/game/Chosen Game.exe\ngame-menu\n')
                self.assertEqual((base/'checklist').exists(),changed)
                self.assertFalse((state/'reshade-diagnostic.json').exists())

    def test_community_preset_survives_diagnostic_and_is_offered_after_setup(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); state = base/'home/state'; state.mkdir(parents=True)
            preset = base/'Community preset.ini'; preset.write_text('Techniques=CRT\n')
            env = dict(self.environment(base), PRESET=str(preset))
            result = subprocess.run(['bash','-c','''source "$WT_ROOT/lib/common.sh"
WT_HOME="$TEST_HOME"
source "$WT_ROOT/lang/fr.sh"
source "$WT_ROOT/modules/community.sh"
source "$WT_ROOT/modules/reshade.sh"
resh_cmd() { [ "$1" = exes ] && echo drive_c/game/Game.exe; }
menu_select() { echo 1; }
resh_api_select() {
 python3 - "$WT_HOME/state/reshade-diagnostic.json" <<'JSON_STATE'
import json,sys
json.dump({'rom':'/games/Game.wine','installation_exe':'drive_c/game/Game.exe'},open(sys.argv[1],'w'))
JSON_STATE
 return 1
}
resh_install_game /games/Game.wine '' "$PRESET"
'''], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            saved = json.loads((state/'reshade-diagnostic.json').read_text())
            self.assertEqual(saved['community_preset'], str(preset))
            result = subprocess.run(['bash','-c','''source "$WT_ROOT/lib/common.sh"
WT_HOME="$TEST_HOME"
source "$WT_ROOT/lang/fr.sh"
source "$WT_ROOT/modules/community.sh"
source "$WT_ROOT/modules/community.sh"
source "$WT_ROOT/modules/reshade.sh"
msgbox() { :; }
resh_install_game() { printf 'setup:%s:%s:%s\n' "$1" "$2" "$3" >> "$SUMMARY"; }
community_import_actions() { printf 'import:%s:%s:%s\n' "$1" "$2" "$4" >> "$SUMMARY"; }
resh_game_menu() { echo menu >> "$SUMMARY"; }
resh_resume_diagnostic
'''], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((base/'summary').read_text().splitlines(),
                [f'setup:/games/Game.wine:drive_c/game/Game.exe:{preset}',
                 f'import:reshade:{preset}:/games/Game.wine', 'menu'])
            self.assertFalse((state/'reshade-diagnostic.json').exists())

    def test_named_templates_go_straight_to_confirmation_without_checklist(self):
        for model, expected in [('retro', ['crt-royale', 'rsretroarch-shaders', 'scaling-shaders', 'reshade-shaders-legacy', 'guestrr-shaders', 'uwt-retro-extras']),
                                ('thomson', ['sweetfx-shaders', 'reshade-shaders-legacy', 'fubax-shaders',
                                             'quintfx', 'prod80-shaders', 'astrayfx-shaders', 'immerse-shaders'])]:
            with tempfile.TemporaryDirectory() as folder:
                base = Path(folder)
                env = dict(self.environment(base), MODEL=model)
                script = '''source "$WT_ROOT/lib/common.sh"
WT_HOME="$TEST_HOME"
source "$WT_ROOT/lang/fr.sh"
source "$WT_ROOT/modules/community.sh"
source "$WT_ROOT/modules/reshade.sh"
resh_cmd() { case "$1" in exes) printf 'Game.exe\\n' ;; details) return 0 ;; backend-packs) python3 "$RESH_HELPER" backend-packs "$2" ;; *) return 1 ;; esac; }
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

    def test_downloaded_preset_skips_models_and_auto_selects_packs_or_requests_review(self):
        for mode in ('known','unknown','standard-community'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                base=Path(folder); preset=base/'Downloaded.ini'
                preset.write_text('Techniques=CAS@CAS.fx\n' if mode!='unknown' else 'Techniques=Custom@Private.fx\n')
                backend=base/'backend.sh';backend.write_text("#!/bin/bash\nprintf 'reshade-shaders\tStandard\nsweetfx-shaders\tSweetFX\n'\n")
                env=dict(self.environment(base),MODE=mode,PRESET=str(preset),BACKEND=str(backend))
                script='''source "$WT_ROOT/lib/common.sh"
WT_HOME="$TEST_HOME"
source "$WT_ROOT/lang/fr.sh"
source "$WT_ROOT/modules/community.sh"
source "$WT_ROOT/modules/reshade.sh"
RESH_BACKEND="$BACKEND"
resh_cmd() { case "$1" in exes) echo Game.exe;; details) :;; backend-packs) echo "$2";; *) return 1;; esac; }
resh_api_select() { echo dxgi; }
resh_backend_ready() { :; }
input_text() { echo latest; }
msgbox() { printf '%s\n' "$2" >> "$SUMMARY"; }
menu_select() {
 if [ "$2" = "$(i18n resh_model_prompt)" ]; then echo model >> "$SUMMARY"; echo community; else echo 1; fi
}
community_choose_reshade_preset() { echo catalogue >> "$SUMMARY"; printf '%s' "$PRESET"; }
checklist_select() { printf '%s\n' "$@" > "$CHECKLIST"; echo sweetfx-shaders; }
yesno_default_no() { printf '%s\n' "$2" >> "$SUMMARY"; return 1; }
if [ "$MODE" = standard-community ]; then resh_install_game /games/Test.wine; else resh_install_game /games/Test.wine '' "$PRESET"; fi
'''
                result=subprocess.run(['bash','-c',script],env=env,capture_output=True,text=True,timeout=10)
                self.assertEqual(result.stderr,'')
                summary=(base/'summary').read_text()
                self.assertEqual('model\n' in summary,mode=='standard-community')
                self.assertEqual('catalogue\n' in summary,mode=='standard-community')
                self.assertEqual((base/'checklist').exists(),mode=='unknown')
                self.assertIn('sweetfx-shaders',summary)
                if mode=='unknown': self.assertIn('Private.fx',summary)

    def test_yad_import_and_export_have_correct_modes_and_keep_paths_with_spaces(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            private = base/'bin'
            private.mkdir()
            yad = private/'yad'
            yad.write_text('#!/bin/bash\n[ "$1" = --file ] || exit 255\nprintf "%s\\0" "$@" > "$SUMMARY"\nprintf "%s" "$SELECTED"\n')
            yad.chmod(0o755)
            for mode in ['import', 'export']:
                env = dict(self.environment(base), PATH=str(private)+':'+os.environ['PATH'],
                           MODE=mode, SELECTED=str(base/'My preset.ini'))
                result = subprocess.run(['bash', '-c', '''source "$WT_ROOT/lib/common.sh"
WT_HOME="$TEST_HOME"
WT_LANGUAGE=fr
source "$WT_ROOT/lang/fr.sh"
source "$WT_ROOT/modules/community.sh"
source "$WT_ROOT/modules/reshade.sh"
resh_preset_file "$MODE" '/games/Example[Runner].wsquashfs'
'''], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, env['SELECTED'])
                flags = (base/'summary').read_bytes().decode().split('\0')
                self.assertIn('--file', flags)
                self.assertEqual('--save' in flags, mode == 'export')
                self.assertEqual('--confirm-overwrite' in flags, mode == 'export')

    def test_active_menu_does_not_scan_the_entire_library(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            env=self.environment(base)
            result=subprocess.run(['bash','-c','''source "$WT_ROOT/lib/common.sh"
WT_HOME="$TEST_HOME"
source "$WT_ROOT/lang/fr.sh"
source "$WT_ROOT/modules/community.sh"
source "$WT_ROOT/modules/reshade.sh"
mangohud_list_games() { printf 'library traversal was called' > "$SUMMARY"; return 1; }
resh_game_rows enabled
'''],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertFalse((base/'summary').exists())


if __name__ == '__main__':
    unittest.main()
