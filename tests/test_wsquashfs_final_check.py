"""Final archive choices preserve the destination until compression/check succeeds."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FinalCheckTests(unittest.TestCase):
    def run_choice(self, mode, choice, check_rc=0, compression_rc=0):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            source = base / 'Game.wine'; source.mkdir()
            dest = base / 'Game.wsquashfs'; dest.write_text('original')
            calls = base / 'calls'; log = base / 'check.log'
            q = shlex.quote
            script = f'''
WT_ROOT={q(str(ROOT / 'toolbox'))}; WT_HOME={q(str(base))}
source "$WT_ROOT/modules/maintenance.sh"
source "$WT_ROOT/modules/wsquashfs.sh"
WT_LOG_DIR={q(str(base / 'logs'))}
i18n() {{ printf '%s' "$1"; }}
menu_select() {{ printf '%s' "$CHOICE"; }}
maintenance_run_progress() {{ shift 2; "$@"; }}
mksquashfs() {{ printf new > "$2"; return "$COMPRESSION_RC"; }}
unsquashfs() {{ printf 'quick\\n' >> "$CALLS"; return "$CHECK_RC"; }}
wsq_update_run() {{
    shift 3
    if [ "$1" = python3 ]; then
        printf 'full\\n' >> "$CALLS"; return "$CHECK_RC"
    fi
    "$@"
}}
maintenance_squash_wine {q(str(source))} {q(str(dest))} {q(mode)} {q(str(log))}
'''
            result = subprocess.run(['bash', '-c', script], capture_output=True, text=True,
                                    env=dict(os.environ, CHOICE=choice, CHECK_RC=str(check_rc),
                                             COMPRESSION_RC=str(compression_rc), CALLS=str(calls)))
            return (result.returncode, dest.read_text(),
                    calls.read_text() if calls.exists() else '',
                    list(base.glob('*.tmp-*')))

    def test_skip_finalizes_both_workflows_without_running_check(self):
        for mode in ('ask-quick', 'ask-full'):
            with self.subTest(mode=mode):
                self.assertEqual(self.run_choice(mode, 'skip')[:3], (0, 'new', ''))

    def test_selected_check_runs_once_before_finalizing(self):
        for mode, expected in (('ask-quick', 'quick\n'), ('ask-full', 'full\n')):
            with self.subTest(mode=mode):
                self.assertEqual(self.run_choice(mode, 'check')[:3], (0, 'new', expected))

    def test_failure_and_cancellation_preserve_existing_archive(self):
        for mode in ('ask-quick', 'ask-full'):
            for choice, check_rc, compression_rc in (('check', 1, 0), ('cancel', 0, 0),
                                                       ('skip', 0, 1), ('unknown', 0, 0)):
                with self.subTest(mode=mode, choice=choice, compression_rc=compression_rc):
                    rc, dest, _, leftovers = self.run_choice(mode, choice, check_rc, compression_rc)
                    self.assertNotEqual(rc, 0)
                    self.assertEqual(dest, 'original')
                    self.assertFalse(leftovers)

    def test_plain_compression_keeps_existing_quick_check(self):
        self.assertEqual(self.run_choice('quick', 'skip')[:3], (0, 'new', 'quick\n'))
