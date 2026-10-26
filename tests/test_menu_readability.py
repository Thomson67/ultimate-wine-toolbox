import fcntl
import json
import os
from pathlib import Path
import pty
import select
import shutil
import struct
import subprocess
import tempfile
import termios
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MenuReadabilityTests(unittest.TestCase):
    def shell(self, home, code, **extra):
        return subprocess.run(['bash', '-c', 'source "$WT_ROOT/lib/common.sh"\nWT_LANGUAGE=fr\nload_i18n\nwt_clear_tty() { :; }\n'+code],
            env=dict(os.environ, WT_ROOT=str(ROOT/'toolbox'), TEST_HOME=str(home), **extra),
            text=True, capture_output=True, timeout=8)

    def test_available_width_hidden_internal_tags_and_selection_are_preserved(self):
        for cols in ('80', '160', 'unknown'):
            with self.subTest(cols=cols), tempfile.TemporaryDirectory() as folder:
                home = Path(folder)
                result = self.shell(home, r'''
have_dialog() { return 0; }
tput() { echo "$TEST_COLS"; }
dialog() { printf '%s\0' "$@" > "$TEST_HOME/args"; printf '%s' 'tag with spaces'; }
menu_select Title Prompt 'tag with spaces' 'A long game title' back Back
''', TEST_COLS=cols)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, 'tag with spaces')
                args = (home/'args').read_bytes().decode().split('\0')[:-1]
                self.assertIn('--no-tags', args)
                self.assertIn('--help-button', args)
                self.assertEqual(args[args.index('--menu')+3], str(int(cols)-4) if cols.isdigit() else '100')

    def test_details_does_not_activate_action_and_returns_to_the_same_item(self):
        for quote in ('plain', 'quoted'):
            with self.subTest(quote=quote), tempfile.TemporaryDirectory() as folder:
                home = Path(folder)
                result = self.shell(home, r'''
have_dialog() { return 0; }; tput() { echo 80; }
dialog() {
  if [ ! -f "$TEST_HOME/help" ]; then
    touch "$TEST_HOME/help"
    if [ "$QUOTE" = quoted ]; then printf 'HELP "tag with spaces"'; else printf 'HELP tag with spaces'; fi
    return 2
  fi
  printf '%s\0' "$@" > "$TEST_HOME/returned-menu"
  printf '%s' 'tag with spaces'
}
wt_menu_item_details() { printf '%s' "$2" > "$TEST_HOME/details"; }
menu_select Title Prompt 'tag with spaces' 'Full description with a long game name' back Back
''', QUOTE=quote)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, 'tag with spaces')
                self.assertEqual((home/'details').read_text(), 'Full description with a long game name')
                args = (home/'returned-menu').read_bytes().decode().split('\0')
                self.assertEqual(args[args.index('--default-item')+1], 'tag with spaces')

    def test_cancel_returns_no_tag(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.shell(Path(folder), 'have_dialog() { return 0; }; dialog() { return 1; }; menu_select Title Prompt back Back')
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, '')

    @unittest.skipUnless(shutil.which('dialog'), 'Real Dialog required for terminal interaction')
    def test_real_dialog_small_terminal_full_text_then_return_and_select(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            wrapper = home/'dialog'
            wrapper.write_text('''#!/bin/bash
if [ \"${1:-}\" = --create-rc ]; then exec \"$REAL_DIALOG\" \"$@\"; fi
if [ -n \"${DIALOGRC:-}\" ]; then cp -- \"$DIALOGRC\" \"$DIALOG_LOG.rc\"; printf '%s' \"$DIALOGRC\" > \"$DIALOG_LOG.theme-path\"; fi
python3 - "$DIALOG_LOG" "$@" <<'ARGUMENTS'
import json,sys
from pathlib import Path
with open(sys.argv[1], 'a') as f: f.write(json.dumps(sys.argv[2:])+"\\n")
if '--textbox' in sys.argv:
    Path(sys.argv[1]+'.text').write_bytes(Path(sys.argv[sys.argv.index('--textbox')+1]).read_bytes())
ARGUMENTS
exec "$REAL_DIALOG" "$@"
''')
            wrapper.chmod(0o755)
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 80, 0, 0))
            script = r'''
source "$WT_ROOT/lib/common.sh"
WT_LANGUAGE=fr; load_i18n
wt_clear_tty() { :; }
menu_select Title Prompt 'tag with spaces' "$DESCRIPTION" back Back > "$SELECTION"
'''
            description = '[Launcher] '+('Un nom de jeu très long et sa description détaillée. '*20)
            env = dict(os.environ, TERM='xterm', PATH=str(home)+os.pathsep+os.environ['PATH'],
                       REAL_DIALOG=shutil.which('dialog'), DIALOG_LOG=str(home/'log'),
                       WT_ROOT=str(ROOT/'toolbox'), DESCRIPTION=description, SELECTION=str(home/'selected'))
            proc = subprocess.Popen(['bash', '-c', script], stdin=slave, stdout=slave, stderr=slave, env=env)
            os.close(slave)
            output = b''; stage = 0; deadline = time.monotonic()+8
            try:
                while proc.poll() is None and time.monotonic() < deadline:
                    if select.select([master], [], [], .1)[0]:
                        try: output += os.read(master, 65536)
                        except OSError: break
                    elif len(output) > 200:
                        calls = [json.loads(line) for line in (home/'log').read_text().splitlines()]
                        if stage == 0 and len(calls) == 1:
                            os.write(master, b'\t\t\r'); stage = 1
                        elif stage == 1 and len(calls) == 2:
                            os.write(master, b'\r'); stage = 2
                        elif stage == 2 and len(calls) == 3:
                            os.write(master, b'\r'); stage = 3
                proc.wait(timeout=1)
                self.assertEqual(proc.returncode, 0, output[-500:])
                self.assertEqual(stage, 3, output[-500:])
                self.assertEqual((home/'selected').read_text(), 'tag with spaces')
                calls = [json.loads(line) for line in (home/'log').read_text().splitlines()]
                first = calls[0]; index = first.index('--menu')
                self.assertEqual(first[index+2:index+4], ['22', '76'])
                self.assertIn('--textbox', calls[1])
                theme = (home/'log.rc').read_text()
                self.assertIn('item_selected_color = button_active_color', theme)
                self.assertIn('button_active_color = (WHITE,BLUE,OFF)', theme)
                self.assertIn('title_color = (BLUE,WHITE,ON)', theme)
                self.assertIn('dialog_color = (BLACK,WHITE,OFF)', theme)
                self.assertIn('tag_color = dialog_color', theme)
                self.assertIn('item_color = dialog_color', theme)
                self.assertFalse(Path((home/'log.theme-path').read_text()).exists())
                wrapped = (home/'log.text').read_text()
                self.assertTrue(all(len(line) <= 68 for line in wrapped.splitlines()))
                self.assertEqual(' '.join(wrapped.split()), ' '.join(description.split()))
                self.assertFalse(Path(calls[1][calls[1].index('--textbox')+1]).exists())
            finally:
                if proc.poll() is None: proc.kill(); proc.wait()
                os.close(master)


if __name__ == '__main__':
    unittest.main()
