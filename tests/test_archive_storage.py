"""Archive placement uses individual writable mergerfs disks, never pool totals."""
import errno
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'toolbox/helpers'))
import archive_storage as storage


class ArchiveStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pool = self.root / 'pool'; self.pool.mkdir()
        self.source = self.root / 'Game.wine'; self.source.mkdir()
        (self.source / 'data').write_bytes(b'data')
        self.relative = Path('windows')
        (self.pool / self.relative).mkdir()
        self.output = self.pool / self.relative / 'Game.wsquashfs.tmp'
        self.disks = [self.root / ('disk' + str(i)) for i in range(4)]
        for disk in self.disks: disk.mkdir()
        self.free = [100, 800, 500, 900]
        self.modes = ['RW', 'RW', 'NC', 'RO']
        self.sizes = lambda disk: SimpleNamespace(f_bavail=self.free[self.disks.index(disk)], f_frsize=1, f_flag=0)
        self.attrs = {
            (self.pool / '.mergerfs', 'user.mergerfs.branches'): ':'.join(str(d) + '=' + m for d, m in zip(self.disks, self.modes)).encode(),
            (self.pool / '.mergerfs', 'user.mergerfs.minfreespace'): b'20',
        }
        def xattr(path, key):
            if key == 'user.mergerfs.allpaths':
                return b'\0'.join(os.fsencode(d / self.relative / self.output.name) for d in self.disks if (d / self.relative / self.output.name).exists())
            return self.attrs[(path, key)]
        for mock in (patch.object(storage, 'pool_for', return_value=(self.pool, self.relative)),
                     patch.object(storage, 'source_bound', return_value=600),
                     patch.object(storage.os, 'statvfs', side_effect=self.sizes),
                     patch.object(storage.os, 'getxattr', side_effect=xattr)):
            mock.start(); self.addCleanup(mock.stop)
        # Model the FUSE view of an exclusively created physical output.
        self.is_file = Path.is_file
        def visible(path):
            if path == self.output:
                return any(self.is_file(d / self.relative / path.name) for d in self.disks)
            return self.is_file(path)
        mock = patch.object(Path, 'is_file', visible); mock.start(); self.addCleanup(mock.stop)

    def test_selects_best_writable_disk_and_creates_missing_game_directory(self):
        storage.prepare(self.source, self.output)
        self.assertTrue((self.disks[1] / self.relative / self.output.name).is_file())
        self.assertFalse((self.disks[0] / self.relative).exists())
        self.assertFalse((self.disks[2] / self.relative).exists())
        self.assertFalse((self.disks[3] / self.relative).exists())

    def test_aggregate_free_space_is_never_used_to_accept_a_too_small_disk(self):
        self.free = [500, 500, 9000, 9000]
        with self.assertRaises(OSError) as error:
            storage.prepare(self.source, self.output)
        self.assertEqual(error.exception.errno, errno.ENOSPC)
        self.assertFalse(any((d / self.relative).exists() for d in self.disks))

    def test_respects_branch_reserve_and_rejects_symlink_redirects(self):
        self.free = [100, 610, 9000, 9000]
        with self.assertRaises(OSError): storage.prepare(self.source, self.output)
        self.free[1] = 800
        (self.disks[1] / self.relative).symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(OSError): storage.prepare(self.source, self.output)
        self.assertFalse((self.source / self.output.name).exists())

    def test_branch_specific_reserve(self):
        self.attrs[(self.pool / '.mergerfs', 'user.mergerfs.branches')] = (str(self.disks[0]) + '=RW,0:' + str(self.disks[1]) + '=RW,300').encode()
        self.free[0] = 650
        storage.prepare(self.source, self.output)
        self.assertTrue((self.disks[0] / self.relative / self.output.name).exists())

    def test_normal_disk_keeps_original_path_without_scanning_game(self):
        with patch.object(storage, 'pool_for', return_value=None), patch.object(storage, 'source_bound') as bound:
            storage.prepare(self.source, self.output)
        bound.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_payload_estimate_does_not_follow_symlinks(self):
        external = self.root / 'external'; external.write_bytes(b'x' * 1000)
        (self.source / 'link').symlink_to(external)
        # Call the original function despite the placement-test bound patch.
        with patch.object(storage, 'source_bound', self.real_bound):
            self.assertEqual(storage.source_bound(self.source), storage.MARGIN + 4)

    def test_read_only_filesystem_is_excluded_even_if_branch_says_rw(self):
        self.sizes = None
        with patch.object(storage.os, 'statvfs', return_value=SimpleNamespace(
                f_bavail=9000, f_frsize=1, f_flag=os.ST_RDONLY)):
            with self.assertRaises(OSError): storage.prepare(self.source, self.output)
        self.assertFalse(any((d / self.relative).exists() for d in self.disks))

    def test_normal_disk_detection_does_not_trust_mergerfs_xattrs(self):
        with patch.object(storage, 'pool_for', wraps=self.real_pool), \
                patch.object(storage, 'is_mergerfs_mount', return_value=False), \
                patch.object(storage, 'relative_and_mount') as attrs:
            storage.prepare(self.source, self.output)
        attrs.assert_not_called()

    def test_existing_output_is_never_overwritten_without_explicit_retry(self):
        self.output.write_bytes(b'keep completed output')
        with self.assertRaises(ValueError): storage.prepare(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), b'keep completed output')

    def test_failed_retry_preflight_preserves_retained_output(self):
        self.output.write_bytes(b'logical view')
        physical = self.disks[1] / self.relative / self.output.name
        physical.parent.mkdir(); physical.touch()
        self.free = [0, 0, 0, 0]
        with self.assertRaises(OSError):
            storage.prepare(self.source, self.output, replace_existing=True)
        self.assertTrue(self.output.exists())
        self.assertTrue(physical.exists())

    def test_retry_can_reclaim_only_its_owned_temporary_output(self):
        self.output.write_bytes(b'logical view')
        physical = self.disks[1] / self.relative / self.output.name
        physical.parent.mkdir(); physical.write_bytes(b'incomplete')
        self.free = [0, 0, 0, 0]
        real_unlink = Path.unlink
        def unlink(path, **kwargs):
            if path == self.output:
                real_unlink(physical, **kwargs)
            real_unlink(path, **kwargs)
        with patch.object(Path, 'unlink', unlink):
            storage.prepare(self.source, self.output, replace_existing=True)
        self.assertEqual(physical.stat().st_size, 0)

    def test_archive_parent_can_be_the_pool_mount_root(self):
        with patch.object(storage, 'pool_for', wraps=self.real_pool), \
                patch.object(storage, 'is_mergerfs_mount', side_effect=lambda path: path == self.pool):
            self.assertEqual(storage.pool_for(self.pool), (self.pool, Path('.')))

    real_pool = staticmethod(storage.pool_for)
    real_bound = staticmethod(storage.source_bound)
