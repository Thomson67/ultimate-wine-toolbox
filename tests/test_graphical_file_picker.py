"""Exercise file/directory pickers against YAD's current option parser contract."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FilePickerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.bin = self.base/'bin'
        self.bin.mkdir()
        tool = self.bin/'yad'
        tool.write_text('''#!/bin/bash
[ "$1" = --file ] || { echo 'Unknown option' >&2; exit 255; }
printf '%s\\0' "$@" > "$PICKER_ARGS"
[ "$PICKER_RC" = 0 ] || exit "$PICKER_RC"
printf '%s\\n' "$SELECTED"
''')
        tool.chmod(0o755)
        self.prefix = self.base/'Game [Runner].wine'
        self.save = self.prefix/'drive_c/users/root/Saved Game'
        self.save.mkdir(parents=True)

    def run_picker(self, action, selected, rc=0):
        env = dict(os.environ, WT_ROOT=str(ROOT/'toolbox'), TEST_HOME=str(self.base),
                   PATH=str(self.bin)+os.pathsep+os.environ['PATH'], SELECTED=str(selected),
                   PICKER_ARGS=str(self.base/'args'), PICKER_RC=str(rc), PREFIX=str(self.prefix))
        script = '''set -u
source "$WT_ROOT/lib/common.sh"
WT_HOME="$TEST_HOME"; WT_LANGUAGE=fr
source "$WT_ROOT/modules/wsquashfs.sh"
source "$WT_ROOT/modules/antimicrox.sh"
WSQ_WINDOWS_DIR="$TEST_HOME"; WSQ_SAVE_ROOT="$TEST_HOME/saves"
prefix="$PREFIX"; exe_rel=drive_c/game/Game.exe
i18n() { printf '%s' "$1"; }
menu_select() { printf browse; }
msgbox() { echo 'Unexpected error message' >&2; exit 90; }
wlr-randr() { printf '1920x1080 current\\n'; }
wsq_browse_save_terminal() { echo 'Unexpected terminal fallback' >&2; return 91; }
'''+action
        return subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True)

    def test_save_folder_picker_keeps_validation_and_paths_with_spaces(self):
        result = self.run_picker('wsq_browse_save && printf "%s" "$WSQ_SELECTED_SAVE"', self.save)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'drive_c/users/root/Saved Game')
        self.assertIn(b'--directory\0', (self.base/'args').read_bytes())

    def test_save_picker_cancel_does_not_select_a_path_or_fall_back(self):
        result = self.run_picker('wsq_browse_save', self.save, rc=1)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr, '')

    def test_update_source_folder_picker_returns_selected_path(self):
        result = self.run_picker('wsq_update_select_source', self.base/'Updated Game')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(self.base/'Updated Game'))
        self.assertIn(b'--directory\0', (self.base/'args').read_bytes())

    def test_pad2key_file_picker_preserves_filter(self):
        selected = self.base/'Game [Runner].wsquashfs.keys'
        result = self.run_picker('amx_pad2key_source', selected)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(selected))
        self.assertIn(b'--file-filter=Pad2Key | *.keys\0', (self.base/'args').read_bytes())


if __name__ == '__main__':
    unittest.main()
