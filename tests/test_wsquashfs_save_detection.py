"""SAVEDIR discovery and evidence ranking, independent of SAVEFILES selection."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'toolbox/helpers'))
import wsquashfs_builder as builder
import wsquashfs_savefiles as individual


class SaveDirectoryDetectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.prefix = Path(self.temp.name)/'Game.wine'
        self.game = self.prefix/'drive_c/game'; self.game.mkdir(parents=True)
        (self.game/'Game.exe').write_bytes(b'executable')

    def write(self, rel, content='progress'):
        path = self.prefix/rel; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def test_arbitrary_game_subdirectory_is_detected_as_savedir(self):
        before = builder.snapshot(self.prefix)
        self.write('drive_c/game/storage/slot.SAV')
        rows = builder.diff_snapshots(self.prefix, before, builder.snapshot(self.prefix))
        self.assertEqual([row[1] for row in rows], ['drive_c/game/storage'])
        self.assertEqual(rows[0][2], 1)
        self.assertEqual(builder.safe_save_dir(self.prefix, rows[0][1], 'drive_c/game/Game.exe'), rows[0][1])

    def test_custom_autorun_game_directory_and_deep_nested_save(self):
        custom = self.prefix/'drive_c/Program Files/Publisher/Game'
        custom.mkdir(parents=True); (custom/'Game.exe').write_bytes(b'exe')
        (self.prefix/'autorun.cmd').write_text('DIR=drive_c/Program Files/Publisher/Game\nCMD=Game.exe\n')
        before = builder.snapshot(self.prefix)
        rel = 'drive_c/Program Files/Publisher/Game/data/players/01'
        self.write(rel+'/checkpoint')
        rows = builder.diff_snapshots(self.prefix, before, builder.snapshot(self.prefix))
        self.assertIn(rel, [row[1] for row in rows])
        self.assertEqual(builder.safe_save_dir(self.prefix, rel, 'drive_c/Program Files/Publisher/Game/Game.exe'), rel)

    def test_existing_save_file_changes_in_non_save_named_game_folder(self):
        rel = 'drive_c/game/data/user/progress.txt'
        self.write(rel, 'old'); before = builder.snapshot(self.prefix)
        self.write(rel, 'new progress data')
        rows = builder.diff_snapshots(self.prefix, before, builder.snapshot(self.prefix))
        self.assertIn('drive_c/game/data/user', [row[1] for row in rows])

    def test_filename_and_sav_extension_rank_above_generic_data(self):
        before = builder.snapshot(self.prefix)
        self.write('drive_c/game/a/data.json')
        self.write('drive_c/game/b/save_slot.txt')
        self.write('drive_c/game/c/slot.sav')
        rows = builder.diff_snapshots(self.prefix, before, builder.snapshot(self.prefix))
        scores = {row[1]: row[0] for row in rows}
        self.assertGreater(scores['drive_c/game/b'], scores['drive_c/game/a'])
        self.assertGreater(scores['drive_c/game/c'], scores['drive_c/game/a'])

    def test_slot_in_filenames_ranks_higher_including_text_and_extensionless_files(self):
        before = builder.snapshot(self.prefix)
        self.write('drive_c/game/generic/state.dat')
        for folder, filename in [('a', 'slot01.dat'), ('b', 'SLOT_2.txt'), ('c', 'slot3')]:
            self.write('drive_c/game/'+folder+'/'+filename)
        self.write('drive_c/game/temporary/slot4.tmp')
        rows = builder.diff_snapshots(self.prefix, before, builder.snapshot(self.prefix))
        scores = {row[1]: row[0] for row in rows}
        for folder in ('a', 'b', 'c'):
            self.assertGreater(scores['drive_c/game/'+folder], scores['drive_c/game/generic'])
        self.assertNotIn('drive_c/game/temporary', scores)

    def test_executable_folder_and_ancestors_rejected_but_save_children_and_siblings_allowed(self):
        executable = 'drive_c/game/bin/Game.exe'
        self.write(executable, 'executable')
        for folder in ('drive_c/game/bin/saves', 'drive_c/game/saves', 'drive_c/OtherSaves'):
            self.write(folder+'/slot1.txt')
            self.assertEqual(builder.safe_save_dir(self.prefix, folder, executable), folder)
        for folder in ('drive_c/game/bin', 'drive_c/game', 'drive_c'):
            with self.assertRaises(ValueError, msg=folder):
                builder.safe_save_dir(self.prefix, folder, executable)

    def test_temp_only_folders_are_ignored_even_if_their_name_suggests_saves(self):
        before = builder.snapshot(self.prefix)
        for name in ('game.LOG','save_slot.tmp','crash.dmp','report.etl'):
            self.write('drive_c/game/Saves/'+name)
        self.assertEqual(builder.diff_snapshots(self.prefix, before, builder.snapshot(self.prefix)), [])

    def test_text_extensionless_and_unfamiliar_data_are_retained(self):
        before = builder.snapshot(self.prefix)
        for folder, name in [('a','state.txt'),('b','progress'),('c','state.custom')]:
            self.write('drive_c/game/'+folder+'/'+name)
        rows = builder.diff_snapshots(self.prefix, before, builder.snapshot(self.prefix))
        self.assertEqual({row[1] for row in rows}, {'drive_c/game/a','drive_c/game/b','drive_c/game/c'})

    def test_mixed_folder_and_unchanged_saves_are_not_discarded_as_temp_only(self):
        self.write('drive_c/game/storage/slot.sav')
        before = builder.snapshot(self.prefix)
        self.write('drive_c/game/storage/game.log')
        rows = builder.diff_snapshots(self.prefix, before, builder.snapshot(self.prefix))
        self.assertIn('drive_c/game/storage', [row[1] for row in rows])

    def test_log_like_folder_with_text_data_is_not_rejected_as_temp_only(self):
        before = builder.snapshot(self.prefix)
        self.write('drive_c/game/logs/state.txt')
        self.write('drive_c/game/logs/run.tmp')
        rows = builder.diff_snapshots(self.prefix, before, builder.snapshot(self.prefix))
        self.assertIn('drive_c/game/logs', [row[1] for row in rows])

    def test_game_root_remains_savefiles_only_and_inventory_is_unchanged(self):
        before = builder.snapshot(self.prefix)
        self.write('drive_c/game/slot.sav')
        after = builder.snapshot(self.prefix)
        self.assertEqual(after['__game_files__'], individual.inventory(self.prefix))
        self.assertIn('drive_c/game', [row[1] for row in builder.diff_snapshots(self.prefix, before, after)])
        self.assertIn('drive_c/game/slot.sav', after['__game_files__'])
        with self.assertRaises(ValueError):
            builder.safe_save_dir(self.prefix, 'drive_c/game', 'drive_c/game/Game.exe')

    def test_game_folder_symlinks_are_not_followed(self):
        outside = Path(self.temp.name)/'outside'; outside.mkdir()
        (self.game/'linked').symlink_to(outside, target_is_directory=True)
        before = builder.snapshot(self.prefix)
        (outside/'slot.sav').write_text('external data')
        self.assertEqual(builder.diff_snapshots(self.prefix, before, builder.snapshot(self.prefix)), [])

    def test_temple_and_logan_game_names_are_not_treated_as_temp_or_logs(self):
        before = builder.snapshot(self.prefix)
        rel = 'drive_c/users/root/AppData/Local/Temple of Logan/storage/state.txt'
        self.write(rel)
        rows = builder.diff_snapshots(self.prefix, before, builder.snapshot(self.prefix))
        self.assertIn(str(Path(rel).parent), [row[1] for row in rows])
        plain = builder.score_save_dir('drive_c/game/Storage', ['state.txt'])[0]
        named = builder.score_save_dir('drive_c/game/Logan', ['state.txt'])[0]
        self.assertEqual(plain, named)
