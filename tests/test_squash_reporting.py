"""Archive failures must be visible in the report linked by the error screen."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SquashReportingTests(unittest.TestCase):
    def run_failure(self, graphical, phase='compression', code=1):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        root = Path(temp.name); private = root / 'bin'; private.mkdir()
        source = root / 'Large game.wine'; source.mkdir()
        destination = root / 'Large game.wsquashfs'; destination.write_bytes(b'original archive')
        log = root / 'update.log'
        squash = private / 'mksquashfs'
        squash.write_text('''#!/bin/bash
printf 'partial output' > "$2"
printf '0\\n42\\n'
if [ "$FAILURE_PHASE" = compression ]; then
    [ "$FAILURE_CODE" != 137 ] || kill -KILL "$$"
    echo 'Write failed because No space left on device' >&2
    echo 'FATAL ERROR: Probably out of space on output filesystem' >&2
    exit "$FAILURE_CODE"
fi
exit 0
''')
        squash.chmod(0o755)
        probe = private / 'unsquashfs'; probe.write_text('#!/bin/bash\nexit 0\n'); probe.chmod(0o755)
        script = '''
WT_ROOT="$ROOT/toolbox"; WT_LANGUAGE=fr
source "$WT_ROOT/lib/common.sh"
source "$WT_ROOT/lang/fr.sh"
source "$WT_ROOT/modules/maintenance.sh"
source "$WT_ROOT/modules/wsquashfs.sh"
WT_SESSION_LOG="$TEST_HOME/session.log"
have_dialog() { [ "$GRAPHICAL" = 1 ]; }
dialog() { cat > "$TEST_HOME/gauge"; }
clear() { :; }; wt_clear_tty() { :; }
python3() {
 case "$1" in
  */archive_publish.py)
    echo 'Atomic archive publication failed; temporary archive retained: [Errno 18] Invalid cross-device link' >&2
    return 1 ;;
  *) command python3 "$@" ;;
 esac
}
maintenance_squash_wine "$SOURCE" "$DESTINATION" quick "$REPORT"
rc=$?
printf '%s' "$rc" > "$TEST_HOME/status"
i18n wsq_update_failed "$SOURCE" "$REPORT" "$(wsq_update_log_detail "$REPORT")" > "$TEST_HOME/message"
'''
        result = subprocess.run(['bash', '-c', script], capture_output=True, text=True, timeout=10,
            env=dict(os.environ, ROOT=str(ROOT), TEST_HOME=str(root), WT_HOME=str(root),
                     PATH=str(private) + os.pathsep + os.environ['PATH'], SOURCE=str(source),
                     DESTINATION=str(destination), REPORT=str(log), GRAPHICAL=str(int(graphical)),
                     FAILURE_PHASE=phase, FAILURE_CODE=str(code)))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(destination.read_bytes(), b'original archive')
        self.assertTrue(source.is_dir())
        return root, log.read_text(), (root / 'message').read_text()

    def test_no_space_error_and_exit_status_are_in_the_linked_report_and_screen(self):
        for graphical in (False, True):
            with self.subTest(dialog=graphical):
                root, report, message = self.run_failure(graphical)
                self.assertEqual((root / 'status').read_text(), '1')
                self.assertIn('No space left on device', report)
                self.assertIn('FATAL ERROR: Probably out of space', report)
                self.assertIn('Compression exit=1', report)
                self.assertIn('operation_exit_code=1', report)
                self.assertIn('FATAL ERROR: Probably out of space', message)
                self.assertIn(str(root / 'update.log'), message)
                self.assertFalse(list(root.glob('*.tmp-*')))

    def test_signal_style_failure_is_not_hidden_by_successful_tee(self):
        root, report, message = self.run_failure(True, code=137)
        self.assertEqual((root / 'status').read_text(), '1')
        self.assertIn('Compression exit=137', report)
        self.assertIn('exit=137', message)

    def test_atomic_publication_failure_is_reported_and_keeps_completed_output(self):
        root, report, message = self.run_failure(True, phase='publication')
        self.assertIn('Compression exit=0', report)
        self.assertIn('Publication exit=1', report)
        self.assertIn('Invalid cross-device link', report)
        self.assertIn('Invalid cross-device link', message)
        self.assertTrue(list(root.glob('*.tmp-*')))

    def test_retry_detail_does_not_show_old_unrelated_failure(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        log = Path(temp.name) / 'retry.log'
        log.write_text('operation_started=mksquashfs\nFATAL ERROR: No space left on device\n'
                       '[2026-10-22 22:00:00] Publication started\noperation_started=python3\n'
                       'Atomic archive publication failed: Invalid cross-device link\n'
                       'operation_exit_code=1\nPublication exit=1 elapsed_seconds=0\n')
        result = subprocess.run(['bash', '-c', 'WT_ROOT="$ROOT/toolbox"; WT_HOME="$TEST_HOME"; '
                                 'source "$WT_ROOT/modules/wsquashfs-update.sh"; wsq_update_log_detail "$REPORT"'],
            capture_output=True, text=True, env=dict(os.environ, ROOT=str(ROOT), TEST_HOME=temp.name, REPORT=str(log)))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Invalid cross-device link', result.stdout)
        self.assertNotIn('No space left on device', result.stdout)
