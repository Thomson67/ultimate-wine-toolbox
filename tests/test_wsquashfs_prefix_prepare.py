"""Prefix creation under an inherited low open-file limit."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PrefixPreparationTests(unittest.TestCase):
    def run_prepare(self, failure=False):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            source = home / 'Source game'
            source.mkdir()
            (source / 'game.exe').write_bytes(b'game data')
            (source / '.hidden').write_bytes(b'hidden data')
            bindir = home / 'bin'
            bindir.mkdir()
            command = bindir / 'unsquashfs'
            command.write_text('''#!/bin/bash
[ "$(ulimit -Sn)" = 128 ] || exit 71
[ "$1" = -processors ] && [ "$2" = 1 ] || exit 72
if [ "$FAIL_EXTRACTION" = 1 ]; then
    echo 'FATAL ERROR: simulated extraction failure' >&2
    exit 73
fi
while [ "$#" -gt 0 ]; do
    if [ "$1" = -d ]; then dest="$2"; break; fi
    shift
done
mkdir -p "$dest/drive_c/users/steamuser"
''')
            command.chmod(0o755)
            result = subprocess.run(['bash', '-c', r'''
WT_ROOT="$REPO/toolbox"; WT_HOME="$TEST_HOME"
source "$WT_ROOT/modules/wsquashfs.sh"
ulimit -Sn 32
ulimit -Hn 128
wsq_prepare_prefix "$TEST_HOME/Source game" template Game "$TEST_HOME/Game.wine" > "$TEST_HOME/prepare.log" 2>&1
rc=$?
[ "$(ulimit -Sn)" = 32 ] || exit 74
printf '%s\n' "$rc"
'''], env=dict(os.environ, REPO=str(ROOT), TEST_HOME=tmp,
                 FAIL_EXTRACTION=str(int(failure)), PATH=f'{bindir}:'+os.environ['PATH']),
                 capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            log = (home / 'prepare.log').read_text()
            self.assertIn('soft=128 hard=128', log)
            if failure:
                self.assertEqual(result.stdout.strip(), '3')
                self.assertIn('FATAL ERROR: simulated extraction failure', log)
                self.assertEqual((source / 'game.exe').read_bytes(), b'game data')
                self.assertFalse((home / 'Game.wine').exists())
                self.assertFalse(list(home.glob('.uwt-prefix-*')))
            else:
                self.assertEqual(result.stdout.strip(), '0')
                game = home / 'Game.wine/drive_c/game'
                self.assertEqual((game / 'game.exe').read_bytes(), b'game data')
                self.assertEqual((game / '.hidden').read_bytes(), b'hidden data')
                self.assertFalse(source.exists())
                self.assertEqual(os.readlink(home / 'Game.wine/drive_c/users/root'), 'steamuser')

    def test_low_limit_extraction_succeeds_without_changing_parent_limit(self):
        self.run_prepare()

    def test_failed_extraction_is_logged_and_keeps_source_intact(self):
        self.run_prepare(failure=True)

    def test_creation_failure_shows_captured_error_and_report_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / 'Source game').mkdir()
            result = subprocess.run(['bash', '-c', r'''
WT_ROOT="$REPO/toolbox"; WT_HOME="$TEST_HOME"
source "$WT_ROOT/lib/common.sh"
source "$WT_ROOT/lang/fr.sh"
source "$WT_ROOT/modules/wsquashfs.sh"
WSQ_STATE_DIR="$TEST_HOME/state"; WT_SESSION_LOG="$TEST_HOME/session.log"
unsquashfs() { :; }
wsq_pending_guard() { return 0; }
wsq_select_source_game() { echo "$TEST_HOME/Source game"; }
wsq_select_template() { WSQ_SELECTED_TEMPLATE=template; }
wsq_clean_name() { echo Game; }
yesno_default_no() { return 0; }
wsq_prepare_prefix() {
    echo 'output from preparation'
    echo 'FATAL ERROR: Too many open files' >&2
    return 3
}
msgbox() { printf '%s\n' "$2"; }
wsq_create_new
'''], env=dict(os.environ, REPO=str(ROOT), TEST_HOME=tmp),
                capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('FATAL ERROR: Too many open files', result.stdout)
            self.assertIn(str(home / 'session.log'), result.stdout)
            log = (home / 'session.log').read_text()
            self.assertIn('output from preparation', log)
            self.assertIn('FATAL ERROR: Too many open files', log)
