"""Closing a Toolbox session must stop archive workers, including detached checks."""
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'toolbox/helpers'))
from attached_operation import process_identity
from winetricks_archive import ArchiveEdit, identity


class AttachedOperationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'home'
        self.original = self.root / 'Game.wsquashfs'
        self.original.write_bytes(b'original archive')
        self.bin = self.root / 'bin'; self.bin.mkdir()
        self.worker_pid = self.root / 'worker.pid'
        self.done = self.root / 'unexpected-completion'
        self.log = self.root / 'operation.log'
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        WT_ROOT=str(ROOT / 'toolbox'), WORKER_PID=str(self.worker_pid),
                        DONE=str(self.done), WT_HOME=str(self.home))

    def tool(self, name, body):
        path = self.bin / name
        path.write_text(f'#!{sys.executable}\n' + body)
        path.chmod(0o755)

    def launch(self, command):
        script = '''
read -r UWT_SESSION_OWNER _ < /proc/self/stat
export UWT_SESSION_OWNER
source "$WT_ROOT/modules/maintenance.sh"
source "$WT_ROOT/modules/wsquashfs-update.sh"
have_dialog() { return 1; }
wt_clear_tty() { :; }; clear() { :; }; i18n() { printf '%s' "$1"; }
''' + command
        process = subprocess.Popen(['bash', '-c', script], env=self.env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        return process

    def wait_for(self, predicate, message):
        deadline = time.monotonic() + 7
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.03)
        self.fail(message + '\n' + (self.log.read_text() if self.log.exists() else 'no operation log'))

    def stop_session_and_check(self, owner, signum):
        self.wait_for(self.worker_pid.exists, 'Archive worker did not start')
        worker = json.loads(self.worker_pid.read_text())
        pid = worker['proc']
        self.addCleanup(lambda: process_identity(pid) is not None and os.kill(worker['pid'], signal.SIGKILL))
        owner.send_signal(signum); owner.wait(timeout=5)
        self.wait_for(lambda: process_identity(pid) is None, 'Orphan archive worker survived session closure')
        self.assertEqual(self.original.read_bytes(), b'original archive')
        self.assertFalse(self.done.exists())

    def test_source_cleanup_stops_when_toolbox_session_is_closed(self):
        self.tool('python3', """import os, sys, time, json
from pathlib import Path
if sys.argv[1] != '-':
    os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
code = sys.stdin.read()
original_unlink = os.unlink
def slow_unlink(*args, **kwargs):
    Path(os.environ['WORKER_PID']).write_text(json.dumps(dict(pid=os.getpid(), proc=int(Path('/proc/self/stat').read_text().split()[0]))))
    time.sleep(60)
    Path(os.environ['DONE']).touch()
    return original_unlink(*args, **kwargs)
os.unlink = slow_unlink
sys.argv = sys.argv[1:]
exec(compile(code, '<cleanup>', 'exec'))
""")
        source = self.root / 'Game.wine'; source.mkdir()
        (source / 'game.data').write_bytes(b'working game')
        external = self.root / 'saves'; external.mkdir()
        (external / 'slot').write_bytes(b'save')
        (source / 'Saved').symlink_to(external, target_is_directory=True)
        owner = self.launch('WINDOWS_ROMS_DIR=' + shlex.quote(str(self.root)) +
                            '; yesno_default_no() { return 0; }; msgbox() { :; }; '
                            'maintenance_offer_source_deletion ' + shlex.quote(str(source)) + ' ' + shlex.quote(str(self.log)))
        self.stop_session_and_check(owner, signal.SIGKILL)
        self.assertTrue(source.exists())
        self.assertEqual((external / 'slot').read_bytes(), b'save')

    def test_compression_stops_even_when_session_is_killed_without_a_trap(self):
        self.tool('mksquashfs', '''import os, sys, time
from pathlib import Path
Path(sys.argv[2]).write_bytes(b'incomplete output')
Path(os.environ['WORKER_PID']).write_text(__import__('json').dumps(dict(pid=os.getpid(), proc=int(Path('/proc/self/stat').read_text().split()[0]))))
time.sleep(60)
Path(os.environ['DONE']).touch()
''')
        source = self.root / 'Game.wine'; source.mkdir()
        owner = self.launch(f'maintenance_squash_wine {shlex.quote(str(source))} {shlex.quote(str(self.original))}')
        self.stop_session_and_check(owner, signal.SIGKILL)
        self.assertTrue(source.exists())

    def test_components_verification_reader_stops_and_state_remains_resumable(self):
        edit = ArchiveEdit(self.original, self.home)
        (edit.prefix / 'drive_c/windows').mkdir(parents=True)
        (edit.prefix / 'autorun.cmd').write_text('DIR=drive_c/game\n')
        (edit.prefix / 'system.reg').write_text('registry')
        edit.save(dict(archive=str(self.original), prefix=str(edit.prefix),
                       original=identity(self.original), phase='ready'))
        self.tool('mksquashfs', '''import sys
from pathlib import Path
Path(sys.argv[2]).write_bytes(b'new compressed archive')
''')
        self.tool('unsquashfs', '''import os, sys, time
from pathlib import Path
if sys.argv[1].startswith('-help'):
    print('-pf FILE')
elif sys.argv[1] == '-pf':
    Path(os.environ['WORKER_PID']).write_text(__import__('json').dumps(dict(pid=os.getpid(), proc=int(Path('/proc/self/stat').read_text().split()[0]))))
    time.sleep(60)
    Path(os.environ['DONE']).touch()
''')
        q = shlex.quote
        shim = 'import os,sys; sys.path.insert(0,os.environ["WT_ROOT"]+"/helpers"); import winetricks_archive as a; a.ensure_idle=lambda *args: None; sys.exit(a.main())'
        owner = self.launch(f'wsq_update_run title body {q(str(self.log))} python3 -c {q(shim)} '
                            f'--home "$WT_HOME" --log {q(str(self.log))} build {q(str(self.original))}')
        self.stop_session_and_check(owner, signal.SIGTERM)
        self.wait_for(lambda: 'operation_interrupted=' in self.log.read_text(), 'Missing interruption report')
        data = edit.load()
        self.assertEqual(data['phase'], 'building')
        self.assertTrue(edit.prefix.exists())
        self.assertTrue(Path(data['output']).exists())
        self.assertNotIn('components_archive_replaced=', self.log.read_text())
        owner = self.launch(f'wsq_update_run title body {q(str(self.log))} python3 -c "raise SystemExit(7)"; exit $?')
        self.assertEqual(owner.wait(timeout=5), 7)

    def test_normal_completion_and_failure_are_reported_only_after_worker_exit(self):
        for code in (0, 7):
            with self.subTest(code=code):
                owner = self.launch(f'wt_operation_run python3 -c "import time; time.sleep(.1); raise SystemExit({code})"; exit $?')
                self.assertEqual(owner.wait(timeout=5), code)


class ArchivePublicationTests(unittest.TestCase):
    def test_cross_disk_rename_refuses_copy_and_preserves_original_and_output(self):
        import errno
        from unittest.mock import patch
        from archive_publish import publish
        with tempfile.TemporaryDirectory() as folder:
            original = Path(folder) / 'Game.wsquashfs'
            staged = Path(folder) / 'Game.tmp'
            original.write_bytes(b'original')
            staged.write_bytes(b'new')
            with patch('archive_publish.os.replace', side_effect=OSError(errno.EXDEV, 'cross-device')):
                with self.assertRaises(OSError):
                    publish(staged, original)
            self.assertEqual(original.read_bytes(), b'original')
            self.assertEqual(staged.read_bytes(), b'new')
