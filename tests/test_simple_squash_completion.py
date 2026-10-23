"""Exercise the actual simple-squash menu through delayed publication and cleanup."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SimpleSquashCompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.roms = self.home / 'roms'; self.roms.mkdir()
        self.source = self.roms / 'Game.wine'; self.source.mkdir()
        (self.source / 'game.data').write_bytes(b'game contents')
        self.external = self.home / 'saves'; self.external.mkdir()
        (self.external / 'slot').write_bytes(b'progression')
        (self.source / 'Saved').symlink_to(self.external, target_is_directory=True)
        self.archive = self.roms / 'Game.wsquashfs'; self.archive.write_bytes(b'original archive')
        self.bin = self.home / 'bin'; self.bin.mkdir()
        for name, body in [('mksquashfs', 'printf "new archive" > "$2"\nprintf "100\\n"\n'),
                           ('unsquashfs', 'exit 0\n')]:
            tool = self.bin / name; tool.write_text('#!/bin/sh\n' + body); tool.chmod(0o755)
        wrapper = self.bin / 'python3'
        wrapper.write_text(f'#!{sys.executable}\n' + r'''
import os, sys, time
from pathlib import Path
home = Path(os.environ['TEST_HOME'])
def gate(stage):
    (home / (stage + '.started')).touch()
    deadline = time.monotonic() + 10
    while not (home / (stage + '.allow')).exists():
        if time.monotonic() > deadline: raise TimeoutError(stage)
        time.sleep(0.01)
if sys.argv[1].endswith('/archive_publish.py'):
    gate('publication')
    if os.environ['FAIL_PHASE'] == 'publication':
        print('Atomic archive publication failed: Invalid cross-device link', file=sys.stderr)
        raise SystemExit(1)
elif sys.argv[1] == '-':
    code = sys.stdin.read()
    unlink = os.unlink
    def delayed_unlink(path, *args, **kwargs):
        gate('cleanup')
        if os.environ['FAIL_PHASE'] == 'cleanup': raise PermissionError('cleanup test: Permission denied')
        return unlink(path, *args, **kwargs)
    os.unlink = delayed_unlink
    sys.argv = sys.argv[1:]
    exec(compile(code, '<source-cleanup>', 'exec'))
    raise SystemExit(0)
os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
''')
        wrapper.chmod(0o755)

    def launch(self, graphical=False, failure='', delete=True):
        script = r'''
read -r UWT_SESSION_OWNER _ < /proc/self/stat
export UWT_SESSION_OWNER
WT_ROOT="$ROOT/toolbox"; WT_HOME="$TEST_HOME"
source "$WT_ROOT/lib/common.sh"
source "$WT_ROOT/lang/$TEST_LANGUAGE.sh"
source "$WT_ROOT/modules/maintenance.sh"
source "$WT_ROOT/modules/wsquashfs.sh"
WINDOWS_ROMS_DIR="$TEST_HOME/roms"; WT_SESSION_LOG="$TEST_HOME/session.log"
clear() { :; }; wt_clear_tty() { :; }
have_dialog() { [ "$GRAPHICAL" = 1 ]; }
dialog() { cat > /dev/null; }
checklist_select() { printf 1; }; yesno() { return 0; }
yesno_default_no() { [ "$DELETE_SOURCE" = 1 ]; }
menu_select() { printf 2; }
wt_log() { :; }
msgbox() {
    printf '%s\n' "$2" >> "$TEST_HOME/messages"
    case "$2" in
      'Squash summary.'*|'Bilan du squashage.'*)
        printf '%s' "$2" > "$TEST_HOME/summary" ;;
    esac
}
maintenance_select_and_squash
'''
        self.process = subprocess.Popen(['bash', '-c', script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=dict(os.environ, ROOT=str(ROOT), TEST_HOME=str(self.home), GRAPHICAL=str(int(graphical)),
                     TEST_LANGUAGE='en', DELETE_SOURCE=str(int(delete)), FAIL_PHASE=failure,
                     PATH=str(self.bin) + os.pathsep + os.environ['PATH']))
        def stop():
            for stage in ('publication', 'cleanup'): (self.home / (stage + '.allow')).touch()
            try: self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait(timeout=3)
        self.addCleanup(stop)

    def wait_for(self, name):
        deadline = time.monotonic() + 7
        while time.monotonic() < deadline:
            if (self.home / name).exists(): return
            if self.process.poll() is not None: break
            time.sleep(0.01)
        self.fail(f'{name} not reached; session log: ' +
                  ((self.home / 'session.log').read_text() if (self.home / 'session.log').exists() else 'none'))

    def allow(self, stage):
        (self.home / (stage + '.allow')).touch()

    def test_summary_waits_for_publication_then_source_cleanup(self, graphical=False):
        self.launch(graphical=graphical)
        self.wait_for('publication.started')
        self.assertEqual(self.archive.read_bytes(), b'original archive')
        self.assertTrue(list(self.roms.glob('*.tmp-*')))
        self.assertFalse((self.home / 'summary').exists())
        self.assertFalse((self.home / 'cleanup.started').exists())
        self.allow('publication')
        self.wait_for('cleanup.started')
        self.assertEqual(self.archive.read_bytes(), b'new archive')
        self.assertFalse(list(self.roms.glob('*.tmp-*')))
        self.assertTrue(self.source.is_dir())
        self.assertFalse((self.home / 'summary').exists())
        self.allow('cleanup')
        self.assertEqual(self.process.wait(timeout=7), 0)
        self.assertFalse(self.source.exists())
        self.assertEqual((self.external / 'slot').read_bytes(), b'progression')
        summary = (self.home / 'summary').read_text()
        self.assertIn('Replaced: 1', summary)
        self.assertIn('Incomplete cleanups: 0', summary)
        log = (self.home / 'session.log').read_text()
        self.assertIn('Publication exit=0', log)
        self.assertIn('SourceCleanup exit=0', log)

    def test_graphical_summary_also_waits_for_every_worker(self):
        self.test_summary_waits_for_publication_then_source_cleanup(graphical=True)

    def test_publication_failure_keeps_archive_and_prefix_and_shows_report(self):
        self.launch(failure='publication')
        self.allow('publication'); self.allow('cleanup')
        self.assertEqual(self.process.wait(timeout=7), 0)
        self.assertEqual(self.archive.read_bytes(), b'original archive')
        self.assertTrue(self.source.is_dir())
        self.assertTrue(list(self.roms.glob('*.tmp-*')))
        self.assertFalse((self.home / 'cleanup.started').exists())
        self.assertIn('Failures: 1', (self.home / 'summary').read_text())
        message = (self.home / 'messages').read_text()
        self.assertIn('Invalid cross-device link', message)
        self.assertIn(str(self.home / 'session.log'), message)

    def test_cleanup_failure_is_counted_without_hiding_published_archive(self):
        self.launch(failure='cleanup')
        self.allow('publication'); self.allow('cleanup')
        self.assertEqual(self.process.wait(timeout=7), 0)
        self.assertEqual(self.archive.read_bytes(), b'new archive')
        self.assertTrue(self.source.is_dir())
        self.assertFalse(list(self.roms.glob('*.tmp-*')))
        summary = (self.home / 'summary').read_text()
        self.assertIn('Replaced: 1', summary)
        self.assertIn('Failures: 0', summary)
        self.assertIn('Incomplete cleanups: 1', summary)
        self.assertIn('Permission denied', (self.home / 'session.log').read_text())

    def test_declining_deletion_keeps_prefix_and_still_waits_for_publication(self):
        self.launch(delete=False)
        self.wait_for('publication.started')
        self.assertFalse((self.home / 'summary').exists())
        self.allow('publication')
        self.assertEqual(self.process.wait(timeout=7), 0)
        self.assertTrue(self.source.is_dir())
        self.assertFalse((self.home / 'cleanup.started').exists())
        self.assertFalse(list(self.roms.glob('*.tmp-*')))
        self.assertIn('Incomplete cleanups: 0', (self.home / 'summary').read_text())
