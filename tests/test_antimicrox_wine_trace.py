import base64
import json
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'toolbox/helpers'))
import antimicrox_wine_trace as trace


class WineTraceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.rom = self.base/'Call of Juarez.wine'; self.rom.mkdir()
        self.autorun = self.rom/'autorun.cmd'
        self.raw = b'DIR=drive_c/game\r\nCMD=CoJ.exe\r\nENV=UMU_DIRECT_GAME=1 WINEDEBUG=-all\r\n'
        self.autorun.write_bytes(self.raw); self.autorun.chmod(0o640)
        self.tool = trace.WineTrace(self.base/'home')

    def test_rewrite_changes_only_debug_variable_and_keeps_existing_environment(self):
        raw = b'CMD=game.exe\nENV=UMU_DIRECT_GAME=1\nENV=PROTON_SONY_AUTO_XINPUT=0 WINEDEBUG=-all\n'
        result = trace.rewrite(raw).decode()
        env = [line[4:] for line in result.splitlines() if line.startswith('ENV=')]
        self.assertEqual(len(env), 1)
        tokens = shlex.split(env[0])
        self.assertIn('UMU_DIRECT_GAME=1', tokens)
        self.assertIn('PROTON_SONY_AUTO_XINPUT=0', tokens)
        self.assertEqual([v for v in tokens if v.startswith('WINEDEBUG=')], ['WINEDEBUG='+trace.DEBUG])
        self.assertIn('CMD=game.exe', result)

    def test_original_bytes_and_permissions_are_restored(self):
        self.tool._prepare(self.rom)
        data = json.loads(self.tool.backup.read_text())
        self.assertEqual(base64.b64decode(data['original']), self.raw)
        self.assertEqual(self.tool.backup.stat().st_mode & 0o777, 0o600)
        self.assertIn(trace.DEBUG.encode(), self.autorun.read_bytes())
        self.tool.restore(); self.tool.restore()
        self.assertEqual(self.autorun.read_bytes(), self.raw)
        self.assertEqual(self.autorun.stat().st_mode & 0o777, 0o640)
        self.assertFalse(self.tool.backup.exists())

    def test_concurrent_edits_are_preserved_and_backup_retained(self):
        self.tool._prepare(self.rom)
        self.autorun.write_bytes(self.autorun.read_bytes()+b'# user edit\n')
        with self.assertRaises(ValueError): self.tool.restore()
        self.assertTrue(self.tool.backup.exists())
        self.assertTrue(self.autorun.read_bytes().endswith(b'# user edit\n'))

    def test_prepare_refuses_active_live_session_before_touching_autorun(self):
        with patch.object(trace, 'LiveSession') as session:
            session.return_value.read.return_value = {'phase': 'running'}
            with self.assertRaises(ValueError): self.tool.prepare(self.rom)
        self.assertEqual(self.autorun.read_bytes(), self.raw)
        self.assertFalse(self.tool.backup.exists())

    def test_existing_backup_is_not_overwritten(self):
        self.tool._prepare(self.rom)
        backup = self.tool.backup.read_bytes()
        with self.assertRaises(ValueError): self.tool.prepare(self.rom)
        self.assertEqual(self.tool.backup.read_bytes(), backup)

    def test_collection_copies_logs_then_restores_autorun_without_archiving_backup(self):
        self.tool._prepare(self.rom)
        logs = self.base/'logs'; logs.mkdir()
        (logs/'es_launch_stderr.log').write_text('trace:event:FocusIn\n')
        (logs/'es_launch_stdout.log').write_text('launcher\n')
        umu = logs/'umu-runner'; umu.mkdir()
        (umu/'runner-20261025-old.log').write_text('unrelated game log')
        path = self.tool.collect(self.base/'output', metadata={'test': True}, system_logdir=logs)
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(json.loads(archive.read('metadata.json')), {'test': True})
            self.assertEqual(archive.read('logs/es_launch_stderr.log'), b'trace:event:FocusIn\n')
            self.assertNotIn('antimicrox-wine-trace.json', archive.namelist())
            self.assertFalse(any('runner-' in name for name in archive.namelist()))
        self.assertEqual(self.autorun.read_bytes(), self.raw)
        self.assertFalse(self.tool.backup.exists())

    def test_failed_archive_write_keeps_backup_for_recovery(self):
        self.tool._prepare(self.rom)
        with patch.object(trace.zipfile, 'ZipFile', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.tool.collect(self.base/'output', metadata={}, system_logdir=self.base/'logs')
        self.assertTrue(self.tool.backup.exists())
        self.tool.restore()
        self.assertEqual(self.autorun.read_bytes(), self.raw)

    def test_autorun_symlink_is_not_overwritten(self):
        other = self.base/'other.cmd'; other.write_bytes(self.raw)
        self.autorun.unlink(); self.autorun.symlink_to(other)
        with self.assertRaises(ValueError): self.tool._prepare(self.rom)
        self.assertTrue(self.autorun.is_symlink())


if __name__ == '__main__':
    unittest.main()
