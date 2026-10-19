"""Physical mergerfs renames stay on their branches and never copy game data."""
import errno
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'toolbox/helpers'))
import mergerfs_move as helper


class MergerfsMoveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.pool = self.base / 'pool'; self.pool.mkdir()
        self.branches = [self.base / 'ROMS', self.base / 'ROMS2']
        self.source = self.pool / 'windows/Marvels Spider-Man 2'
        self.target = self.pool / "windows/Marvel's Spider-Man 2.wine/drive_c/Marvels Spider-Man 2"
        self.source_rel = self.source.relative_to(self.pool)
        self.parent_rel = self.target.parent.relative_to(self.pool)
        self.physical = []
        for index, branch in enumerate(self.branches):
            src = branch / self.source_rel; src.mkdir(parents=True)
            (src / f'part{index}.bin').write_bytes(b'game data')
            self.physical.append(src)
        self.attrs = {
            (self.source, 'user.mergerfs.relpath'): ('/' + str(self.source_rel)).encode(),
            (self.target.parent, 'user.mergerfs.relpath'): ('/' + str(self.parent_rel)).encode(),
            (self.pool / '.mergerfs', 'user.mergerfs.branches'):
                ':'.join(str(branch)+'=RW' for branch in self.branches).encode(),
            (self.source, 'user.mergerfs.allpaths'):
                b'\0'.join(bytes(src) for src in self.physical),
        }
        self.xattr = patch.object(helper.os, 'getxattr', side_effect=lambda path, key: self.attrs[(Path(path), key)])
        self.xattr.start(); self.addCleanup(self.xattr.stop)
        self.mount = patch.object(helper, 'is_mergerfs_mount', side_effect=lambda path: path == self.pool)
        self.mount.start(); self.addCleanup(self.mount.stop)

    def test_multiple_branches_are_renamed_in_place_and_journaled(self):
        inodes = [(src / f'part{i}.bin').stat().st_ino for i, src in enumerate(self.physical)]
        records = []
        helper.rename_in_branches(self.source, self.target,
                                  lambda plan: records.append(json.loads(json.dumps(plan))))
        for i, branch in enumerate(self.branches):
            self.assertFalse(self.physical[i].exists())
            target = branch / self.target.relative_to(self.pool)
            self.assertEqual((target / f'part{i}.bin').stat().st_ino, inodes[i])
        self.assertEqual([row['moved'] for row in records[0]], [False, False])
        self.assertEqual([row['moved'] for row in records[-1]], [True, True])

    def test_single_source_branch_creates_parents_without_touching_other_branches(self):
        self.attrs[(self.source, 'user.mergerfs.allpaths')] = bytes(self.physical[0])
        helper.rename_in_branches(self.source, self.target)
        self.assertTrue(self.physical[1].exists())
        self.assertFalse((self.branches[1] / self.parent_rel).exists())

    def test_failed_second_move_rolls_back_first_and_removes_empty_created_parents(self):
        original = Path.rename
        def rename(path, target):
            if path == self.physical[1]: raise OSError(errno.EACCES, 'permission denied')
            return original(path, target)
        with patch.object(Path, 'rename', rename):
            with self.assertRaises(OSError): helper.rename_in_branches(self.source, self.target)
        for src, branch in zip(self.physical, self.branches):
            self.assertTrue(src.exists())
            self.assertFalse((branch / self.parent_rel).exists())

    def test_rollback_failure_retains_recovery_journal(self):
        original = Path.rename
        target0 = self.branches[0] / self.target.relative_to(self.pool)
        def rename(path, target):
            if path in (self.physical[1], target0): raise OSError(errno.EIO, 'disk error')
            return original(path, target)
        records = []
        with patch.object(Path, 'rename', rename):
            with self.assertRaises(helper.MoveRecoveryRequired):
                helper.rename_in_branches(self.source, self.target,
                                          lambda plan: records.append(json.loads(json.dumps(plan))))
        self.assertTrue(target0.exists())
        self.assertEqual([row['moved'] for row in records[-1]], [True, False])

    def test_existing_destination_is_rejected_before_any_move(self):
        target = self.branches[1] / self.target.relative_to(self.pool)
        target.mkdir(parents=True); (target / 'keep').write_text('untouched')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            helper.rename_in_branches(self.source, self.target)
        self.assertTrue(all(src.exists() for src in self.physical))
        self.assertEqual((target / 'keep').read_text(), 'untouched')

    def test_destination_symlink_is_rejected(self):
        parent = self.branches[0] / self.parent_rel
        parent.parent.mkdir(parents=True)
        external = self.base / 'external'; external.mkdir()
        parent.symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'redirect'):
            helper.rename_in_branches(self.source, self.target)
        self.assertEqual(list(external.iterdir()), [])
        self.assertTrue(all(src.exists() for src in self.physical))

    def test_unknown_or_read_only_branch_is_rejected(self):
        for branches in (str(self.branches[0])+'=RO', str(self.branches[0])+'=NC', str(self.base/'unknown')+'=RW'):
            self.attrs[(self.pool / '.mergerfs', 'user.mergerfs.branches')] = branches.encode()
            with self.assertRaisesRegex(ValueError, 'writable branch'):
                helper.rename_in_branches(self.source, self.target)
        self.assertTrue(all(src.exists() for src in self.physical))

    def test_fake_mergerfs_attributes_on_normal_filesystem_are_rejected(self):
        self.mount.stop()
        with patch.object(helper, 'is_mergerfs_mount', return_value=False):
            with self.assertRaisesRegex(ValueError, 'verified mergerfs'):
                helper.rename_in_branches(self.source, self.target)
        self.assertTrue(all(src.exists() for src in self.physical))


if __name__ == '__main__': unittest.main()
