"""Archive editing retains originals and resumable work until a checked commit."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'toolbox/helpers'))
import winetricks_archive as archive


class ArchiveEditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.original = self.root / 'Game [Runner].wsquashfs'
        self.original.write_bytes(b'original archive')
        self.home = self.root / 'home'
        self.edit = archive.ArchiveEdit(self.original, self.home)
        self.log = self.root / 'build.log'
        self.idle = patch.object(archive, 'ensure_idle'); self.idle.start(); self.addCleanup(self.idle.stop)

    def command(self, args, **kwargs):
        if args[0] == 'unsquashfs':
            prefix = Path(args[args.index('-d') + 1])
            (prefix / 'drive_c/windows').mkdir(parents=True, exist_ok=True)
            (prefix / 'drive_c/game').mkdir(exist_ok=True)
            (prefix / 'autorun.cmd').write_text('DIR=drive_c/game\n')
            (prefix / 'system.reg').write_text('original registry')
        else:
            Path(args[2]).write_bytes(b'new checked archive')
        return subprocess.CompletedProcess(args, 0)

    def prepare(self):
        with patch.object(archive.subprocess, 'run', side_effect=self.command):
            self.edit.prepare()

    def test_prepare_and_resume_keep_original_and_pending_builder(self):
        builder = self.home / 'state/wsquashfs-builder.json'
        builder.parent.mkdir(parents=True)
        builder.write_text('unrelated pending builder')
        self.prepare()
        with patch.object(archive.subprocess, 'run') as run:
            self.edit.prepare()
        run.assert_not_called()
        self.assertEqual(self.original.read_bytes(), b'original archive')
        self.assertEqual(builder.read_text(), 'unrelated pending builder')
        self.assertEqual(self.edit.load()['phase'], 'ready')

    def test_unowned_workspace_is_never_overwritten(self):
        self.edit.workspace.mkdir()
        with self.assertRaisesRegex(ValueError, 'unowned'):
            self.prepare()
        self.assertFalse(self.edit.state.exists())

    def test_failed_extraction_retains_original_and_state_for_retry(self):
        with patch.object(archive.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, ['unsquashfs'])):
            with self.assertRaises(subprocess.CalledProcessError):
                self.edit.prepare()
        self.assertEqual(self.original.read_bytes(), b'original archive')
        self.assertEqual(self.edit.load()['phase'], 'extracting')
        self.prepare()
        self.assertEqual(self.edit.load()['phase'], 'ready')

    def test_failed_integrity_keeps_original_and_reuses_output_on_retry(self):
        self.prepare()
        with patch.object(archive.subprocess, 'run', side_effect=self.command), patch.object(archive, 'check', return_value=1):
            with self.assertRaisesRegex(ValueError, 'verification failed'):
                self.edit.build(self.log)
        data = self.edit.load()
        output = Path(data['output'])
        self.assertTrue(output.exists())
        self.assertTrue(self.edit.prefix.is_dir())
        self.assertEqual(self.original.read_bytes(), b'original archive')
        with patch.object(archive.subprocess, 'run', side_effect=self.command), patch.object(archive, 'check', return_value=0):
            self.edit.build(self.log)
        self.assertEqual(self.original.read_bytes(), b'new checked archive')
        self.assertFalse(output.exists())
        self.assertFalse(self.edit.workspace.exists())
        self.assertFalse(self.edit.state.exists())

    def test_changed_original_is_never_replaced(self):
        self.prepare()
        def verify(*args):
            self.original.write_bytes(b'concurrent update')
            return 0
        with patch.object(archive.subprocess, 'run', side_effect=self.command), patch.object(archive, 'check', side_effect=verify):
            with self.assertRaisesRegex(ValueError, 'has changed'):
                self.edit.build(self.log)
        self.assertEqual(self.original.read_bytes(), b'concurrent update')
        self.assertTrue(self.edit.prefix.exists())

    def test_failed_rename_keeps_original_and_verified_output(self):
        self.prepare()
        original_replace = archive.os.replace
        def replace(source, destination):
            if Path(destination) == self.original:
                raise OSError('EXDEV')
            return original_replace(source, destination)
        with patch.object(archive.subprocess, 'run', side_effect=self.command), patch.object(archive, 'check', return_value=0):
            with patch.object(archive.os, 'replace', side_effect=replace):
                with self.assertRaisesRegex(OSError, 'EXDEV'):
                    self.edit.build(self.log)
        self.assertEqual(self.original.read_bytes(), b'original archive')
        self.assertTrue(Path(self.edit.load()['output']).is_file())

    def test_cleanup_refuses_uncommitted_prefix(self):
        self.prepare()
        with self.assertRaisesRegex(ValueError, 'Only a committed'):
            self.edit.cleanup()
        self.assertTrue(self.edit.prefix.is_dir())

    @unittest.skipUnless(shutil.which('mksquashfs') and shutil.which('unsquashfs'), 'squashfs-tools required')
    def test_real_extract_modify_verify_and_recompress_round_trip(self):
        source = self.root / 'source.wine'
        (source / 'drive_c/windows').mkdir(parents=True)
        (source / 'drive_c/game').mkdir()
        (source / 'drive_c/game/game.exe').write_bytes(b'game content')
        (source / 'system.reg').write_text('registry')
        (source / 'autorun.cmd').write_text('DIR=drive_c/game\n')
        subprocess.run(['mksquashfs', str(source), str(self.original), '-noappend', '-processors', '1'],
                       check=True, capture_output=True)
        self.original.chmod(0o644)
        self.edit.prepare()
        (self.edit.prefix / 'drive_c/windows/new.dll').write_bytes(b'new component')
        self.edit.build(self.log)
        destination = self.root / 'verification'
        subprocess.run(['unsquashfs', '-d', str(destination), str(self.original)], check=True, capture_output=True)
        self.assertEqual((destination / 'drive_c/windows/new.dll').read_bytes(), b'new component')
        self.assertEqual((destination / 'drive_c/game/game.exe').read_bytes(), b'game content')
        self.assertEqual(self.original.stat().st_mode & 0o777, 0o644)
        self.assertFalse(self.edit.workspace.exists())
