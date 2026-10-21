import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'toolbox/helpers'))
import wsquashfs_dotnet_storage as storage
import wsquashfs_winetricks as tricks


class DotnetStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.prefix = self.base / 'Game with spaces.wine'
        self.game = self.prefix / 'drive_c/game'
        self.windows = self.prefix / 'drive_c/windows'
        self.game.mkdir(parents=True)
        self.windows.mkdir()
        (self.game / 'game.exe').write_text('GAME MUST STAY')
        (self.prefix / 'system.reg').write_text('old registry')
        (self.prefix / 'autorun.cmd').write_text('DIR=drive_c/game\nCMD=game.exe\n')
        (self.windows / 'original.dll').write_text('old DLL')
        self.work = self.base / 'local'

    def local_stage(self):
        with patch.object(storage, 'filesystem', return_value='ext4'), patch.object(storage, 'exchange_probe', return_value=0):
            return storage.stage(self.prefix, self.game, self.work)

    def reparse_links(self):
        mono = self.windows / 'mono'
        metadata = mono / '.REPARSE_POINT/A.dll/encoded'
        metadata.mkdir(parents=True)
        anchor = metadata / '${WINEPREFIX}'
        anchor.symlink_to(self.prefix, target_is_directory=True)
        (metadata / '0').symlink_to('${WINEPREFIX}/drive_c/windows/original.dll')
        front = mono / 'A.dll'
        front.symlink_to('.REPARSE_POINT/A.dll/encoded/0')
        return anchor, front

    def test_tkg_reparse_metadata_and_native_link_remain_intact(self):
        anchor, front = self.reparse_links()
        tricks.prepare(self.prefix)
        self.assertTrue(front.is_symlink())
        self.assertTrue(anchor.is_symlink())
        self.assertEqual(front.read_text(), 'old DLL')

    def test_reparse_name_does_not_bypass_external_directory_protection(self):
        external = self.base / 'external'
        external.mkdir()
        (self.windows / '.REPARSE_POINT').symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'directory alias'):
            tricks.prepare(self.prefix)

    def test_readonly_prepare_does_not_detach_shared_runner_file(self):
        shared = self.base / 'runner.dll'
        shared.write_text('runner')
        dll = self.windows / 'shared.dll'
        dll.symlink_to(shared)
        tricks.prepare(self.prefix, detach=False)
        self.assertTrue(dll.is_symlink())

    def test_local_stage_keeps_runner_identity_and_relocates_links(self):
        anchor, front = self.reparse_links()
        save = self.base / 'external saves'
        save.mkdir()
        (self.prefix / 'save-link').symlink_to(save, target_is_directory=True)
        staged = self.local_stage()
        self.assertEqual(staged.name, self.prefix.name)
        self.assertFalse((staged / 'drive_c/game').exists())
        relocated = staged / anchor.relative_to(self.prefix)
        self.assertEqual(relocated.resolve(), staged)
        self.assertEqual((staged / front.relative_to(self.prefix)).read_text(), 'old DLL')
        self.assertEqual((staged / 'save-link').resolve(), save)
        self.assertEqual(anchor.resolve(), self.prefix)

    def test_fuse_or_failed_exchange_refused_before_prefix_copy(self):
        for kind, result in [('fuse.mergerfs', 0), ('ext4', 22)]:
            with patch.object(storage, 'filesystem', return_value=kind), patch.object(storage, 'exchange_probe', return_value=result):
                with self.assertRaisesRegex(ValueError, 'local filesystem'):
                    storage.stage(self.prefix, self.game, self.work)
        self.assertFalse(list(self.work.glob('install-*')))

    def test_staging_inside_original_prefix_refused(self):
        with self.assertRaises(ValueError):
            storage.stage(self.prefix, self.game, self.prefix / 'bad')

    def test_mounted_prefix_publication_keeps_transaction_inside_mount(self):
        staged = self.local_stage()
        (staged / 'system.reg').write_text('new registry')
        (staged / 'drive_c/windows/new.dll').write_text('installed')
        original_mkdtemp = tempfile.mkdtemp
        locations = []
        def mkdtemp(*args, **kwargs):
            locations.append(kwargs['dir'])
            return original_mkdtemp(*args, **kwargs)
        with patch.dict(os.environ, UWT_COMPONENT_MOUNTED_PREFIX=str(self.prefix)):
            with patch.object(storage.tempfile, 'mkdtemp', side_effect=mkdtemp):
                storage.publish(staged, self.prefix, self.game)
        self.assertEqual(locations, [self.prefix])
        self.assertEqual((self.prefix / 'system.reg').read_text(), 'new registry')
        self.assertEqual((self.windows / 'new.dll').read_text(), 'installed')
        self.assertEqual((self.game / 'game.exe').read_text(), 'GAME MUST STAY')
        self.assertFalse(list(self.prefix.glob('.uwt-dotnet-commit-*')))

    def test_success_publishes_runtime_and_reanchors_tkg_links_without_game_copy(self):
        anchor, front = self.reparse_links()
        staged = self.local_stage()
        (staged / 'system.reg').write_text('new registry')
        (staged / 'drive_c/windows/original.dll').write_text('new DLL')
        storage.publish(staged, self.prefix, self.game)
        self.assertEqual((self.prefix / 'system.reg').read_text(), 'new registry')
        self.assertEqual((self.game / 'game.exe').read_text(), 'GAME MUST STAY')
        self.assertEqual(anchor.resolve(), self.prefix)
        self.assertEqual(front.read_text(), 'new DLL')
        self.assertFalse(list(self.prefix.parent.glob('.uwt-dotnet-commit-*')))

    def test_failed_copy_never_changes_working_prefix(self):
        staged = self.local_stage()
        with patch.object(storage.shutil, 'copytree', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                storage.publish(staged, self.prefix, self.game)
        self.assertEqual((self.prefix / 'system.reg').read_text(), 'old registry')
        self.assertEqual((self.game / 'game.exe').read_text(), 'GAME MUST STAY')

    def test_failed_promotion_rolls_back_all_prior_entries(self):
        staged = self.local_stage()
        (staged / 'system.reg').write_text('new registry')
        (staged / 'drive_c/windows/original.dll').write_text('new DLL')
        actual = storage.os.replace
        def fail_once(source, target):
            if 'incoming' in Path(source).parts and Path(target) == self.prefix / 'system.reg':
                raise OSError('simulated promotion failure')
            return actual(source, target)
        with patch.object(storage.os, 'replace', side_effect=fail_once):
            with self.assertRaises(OSError):
                storage.publish(staged, self.prefix, self.game)
        self.assertEqual((self.prefix / 'system.reg').read_text(), 'old registry')
        self.assertEqual((self.windows / 'original.dll').read_text(), 'old DLL')
        self.assertEqual((self.game / 'game.exe').read_text(), 'GAME MUST STAY')

    def test_unexpected_game_data_in_staged_prefix_refused(self):
        staged = self.local_stage()
        (staged / 'drive_c/game').mkdir()
        with self.assertRaisesRegex(ValueError, 'game data'):
            storage.publish(staged, self.prefix, self.game)
        self.assertEqual((self.game / 'game.exe').read_text(), 'GAME MUST STAY')
