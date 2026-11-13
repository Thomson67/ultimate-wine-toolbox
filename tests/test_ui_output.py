import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class UIOutputTests(unittest.TestCase):
    def test_nested_umu_launch_uses_own_launcher_and_keeps_exit_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            main = root / 'umu-toolbox.sh'
            main.write_text('#!/bin/bash\nprintf legacy\n')
            main.chmod(0o755)
            launcher = root / 'ports' / 'UMU Runner Toolbox.sh'
            launcher.parent.mkdir()
            launcher.write_text('#!/bin/bash\ncat "$UMU_TOOLBOX_ROOT/config/font-size"\nexit 7\n')
            (root / 'config').mkdir()
            preference = root / 'config/font-size'
            for size in ('16', '20'):
                preference.write_text(size)
                result = subprocess.run(['bash', '-c', '''
source toolbox/modules/umu.sh
UMU_TOOLBOX_ROOT="$TEST_UMU_ROOT"
UMU_TOOLBOX_MAIN="$UMU_TOOLBOX_ROOT/umu-toolbox.sh"
export UMU_TOOLBOX_ROOT
launch_umu_toolbox
'''], cwd=ROOT, capture_output=True, text=True,
                    env=os.environ | {'TEST_UMU_ROOT': directory})
                self.assertEqual(result.stdout, size)
                self.assertEqual(result.returncode, 7)
            launcher.unlink()
            result = subprocess.run(['bash', '-c', '''
source toolbox/modules/umu.sh
UMU_TOOLBOX_ROOT="$TEST_UMU_ROOT"
UMU_TOOLBOX_MAIN="$UMU_TOOLBOX_ROOT/umu-toolbox.sh"
launch_umu_toolbox
'''], cwd=ROOT, capture_output=True, text=True,
                env=os.environ | {'TEST_UMU_ROOT': directory})
            self.assertEqual(result.stdout, 'legacy')
            self.assertEqual(result.returncode, 0)

    def test_confirmation_screen_is_visible_inside_captured_selector(self):
        for function in ('yesno', 'yesno_default_no'):
            for answer in (0, 1):
                with self.subTest(function=function, answer=answer):
                    result = subprocess.run(['bash', '-c', r'''
source toolbox/lib/common.sh
have_dialog() { return 0; }
wt_clear_tty() { :; }
i18n() { printf '%s' "$1"; }
dialog() { printf '\033[?1049hConfirm launch\033[?1049l'; return "$ANSWER"; }
selector() {
    "$CONFIRM_FUNCTION" ReShade Continue || return 1
    printf diagnostic
}
selected="$(selector)"
rc=$?
printf '%s:%s' "$rc" "$selected"
'''], cwd=ROOT, capture_output=True, text=True,
                        env=os.environ | {'CONFIRM_FUNCTION': function, 'ANSWER':str(answer)}, check=True)
                    self.assertEqual(result.stdout, '0:diagnostic' if answer == 0 else '1:')
                    self.assertIn('Confirm launch', result.stderr)

    def test_missing_executable_message_does_not_pollute_selection(self):
        result = subprocess.run(
            ["bash", "-c", r'''
source toolbox/lib/common.sh
source toolbox/modules/wsquashfs-update.sh
have_dialog() { return 0; }
wt_clear_tty() { :; }
i18n() { printf '%s' "$1"; }
# Model dialog's screen output, including terminal escape sequences.
menu_select() { printf '%s\n' "$2" >&2; printf other; }
python3() {
    case "$2" in
        exe) printf ''; ;;
        game-dir) printf 'drive_c/game\n'; ;;
        *) return 1 ;;
    esac
}
wsq_select_executable() { printf 'drive_c/game/New folder/Game.exe\n'; }
selected="$(wsq_update_select_executable '/tmp/Game.wine')" || exit
printf '%s' "$selected"
'''],
            cwd=ROOT, capture_output=True, text=True, check=True,
        )
        self.assertEqual(result.stdout, "drive_c/game/New folder/Game.exe")
        self.assertIn("wsq_update_exe_missing", result.stderr)

    def test_wsquashfs_yad_selection_and_current_executable_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prefix = root / 'My Game.wine'
            game = prefix / 'drive_c/game'
            game.mkdir(parents=True)
            current = game / 'Current Game.exe'
            current.touch()
            (prefix/'autorun.cmd').write_text('DIR=drive_c/game\nCMD="Current Game.exe" --original\n')
            hidden = game / '.launch'
            hidden.mkdir()
            selected = hidden / 'Start Game.CmD'
            selected.touch()
            outside = root / 'Outside.exe'
            outside.touch()
            link = game / 'Link.exe'
            link.symlink_to(outside)
            scripts = root / 'bin'
            scripts.mkdir()
            yad = scripts/'yad'
            yad.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > "$YAD_ARGS"\n'
                           '[ "$MODE" != cancel ] || exit 1\nprintf "%s\\n" "$FILE"\n')
            yad.chmod(0o755)

            for mode, file in [('review', selected), ('create', selected), ('same', current),
                               ('cancel', selected), ('escape', link), ('outside', outside),
                               ('autorun', prefix/'autorun.cmd')]:
                with self.subTest(mode=mode):
                    count = root/'count'
                    count.unlink(missing_ok=True)
                    result = subprocess.run(['bash', '-uc', r'''
source toolbox/lib/common.sh
WT_ROOT="$PWD/toolbox"
WT_HOME="$TEST_HOME"
WT_LANGUAGE=fr
load_i18n
source toolbox/modules/wsquashfs.sh
msgbox() { printf '%s\n' "$2" >&2; }
menu_select() {
    local count=0
    if [ -f "$COUNT" ]; then read -r count < "$COUNT"; fi
    printf '%s\n' "$((count + 1))" > "$COUNT"
    case "$MODE:$count" in
        review:0) printf current ;;
        review:1|*:0)
            [[ " $* " = *' browse '* ]] || return 1
            printf browse ;;
        *) printf back ;;
    esac
}
if [ "$MODE" = create ]; then
    wsq_select_executable "$PREFIX"
else
    wsq_update_select_executable "$PREFIX"
fi
'''], cwd=ROOT, capture_output=True, text=True, env=os.environ | {
                        'PATH': f'{scripts}:{os.environ["PATH"]}', 'TEST_HOME': str(root),
                        'COUNT': str(count), 'MODE': mode, 'PREFIX': str(prefix),
                        'FILE': str(file), 'YAD_ARGS': str(root/'yad-args'),
                    })
                    if mode in ('review', 'create'):
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result.stdout, 'drive_c/game/.launch/Start Game.CmD\n')
                    else:
                        self.assertEqual(result.returncode, 1, result.stderr)
                        self.assertEqual(result.stdout, '')
                    if mode == 'review':
                        self.assertIn('drive_c/game/Current Game.exe', result.stderr)
                        self.assertIn(f'--filename={game}/', (root/'yad-args').read_text())
                    if mode in ('escape', 'outside', 'autorun'):
                        self.assertIn('Fichier sélectionné', result.stderr)
                    self.assertIn('CMD="Current Game.exe" --original', (prefix/'autorun.cmd').read_text())


if __name__ == "__main__":
    unittest.main()
