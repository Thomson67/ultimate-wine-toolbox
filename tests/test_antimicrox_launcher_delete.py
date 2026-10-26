import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'toolbox/helpers'))
from antimicrox_launcher import Store, ConfigDeletion
from antimicrox_profiles import Profiles

RULE = {'field': 'title', 'match': 'exact', 'value': 'Launcher'}
PROFILE = '<gamecontroller><sets/></gamecontroller>'


class LauncherDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.userdata = Path(self.temp.name)/'userdata'
        self.home = self.userdata/'system/toolbox'
        self.folder = self.home/'config/antimicrox-profiles'; self.folder.mkdir(parents=True)
        self.launcher = self.folder/'Launcher.amgp'; self.launcher.write_text(PROFILE)
        self.game = self.folder/'Game.amgp'; self.game.write_text(PROFILE)
        self.rom = str(self.userdata/'roms/windows/Main.wine'); Path(self.rom).mkdir(parents=True)
        self.other = str(self.userdata/'roms/windows/Other.wine')
        self.store = Store(self.home)
        self.store.save(self.rom, 'profiles', str(self.launcher), RULE, str(self.game))
        self.delete = ConfigDeletion(self.home, self.userdata, active=lambda: False)
        self.cfg = self.home/'config/antimicrox-games.tsv'
        self.cfg.write_text(self.rom+'\t'+str(self.launcher)+'\n')

    def plan(self, profiles=True):
        return self.delete.plan(self.rom, profiles)

    def actions(self, plan):
        return {item['path']: item['action'] for item in plan['profiles']}

    def test_deletes_complete_unshared_pair_configuration_and_assignment(self):
        plan = self.plan()
        self.assertEqual(set(self.actions(plan).values()), {'delete'})
        self.delete.delete(self.rom, plan['token'], True)
        self.assertFalse(self.launcher.exists())
        self.assertFalse(self.game.exists())
        self.assertFalse(self.store.path(self.rom).exists())
        self.assertNotIn(self.rom, self.cfg.read_text())

    def test_shared_primary_profile_and_other_game_assignment_are_kept(self):
        self.cfg.write_text(self.cfg.read_text()+self.other+'\t'+str(self.launcher)+'\n')
        plan = self.plan()
        self.assertEqual(self.actions(plan)[str(self.launcher)], 'keep')
        self.assertEqual(self.actions(plan)[str(self.game)], 'delete')
        self.delete.delete(self.rom, plan['token'], True)
        self.assertTrue(self.launcher.exists())
        self.assertFalse(self.game.exists())
        self.assertEqual(self.cfg.read_text(), self.other+'\t'+str(self.launcher)+'\n')

    def test_secondary_profile_used_by_another_launcher_is_kept(self):
        other_profile = self.folder/'Other.amgp'; other_profile.write_text(PROFILE)
        self.store.save(self.other, 'profiles', str(other_profile), RULE, str(self.game))
        other_config = self.store.path(self.other).read_bytes()
        self.cfg.write_text(self.cfg.read_text()+self.other+'\t'+str(other_profile)+'\n')
        plan = self.plan()
        self.assertEqual(self.actions(plan)[str(self.game)], 'keep')
        self.delete.delete(self.rom, plan['token'], True)
        self.assertFalse(self.launcher.exists())
        self.assertTrue(self.game.exists())
        self.assertEqual(self.store.path(self.other).read_bytes(), other_config)

    def test_retained_imported_primary_also_retains_its_game_profile(self):
        self.cfg.write_text(self.cfg.read_text()+self.other+'\t'+str(self.launcher)+'\n')
        self.delete.imports.parent.mkdir(parents=True)
        imports = {str(self.launcher): {'kind': 'antimicrox', 'launcher_config': {'mode': 'profiles', 'game_profile': str(self.game)}}}
        self.delete.imports.write_text(json.dumps(imports))
        plan = self.plan()
        self.assertEqual(set(self.actions(plan).values()), {'keep'})
        self.delete.delete(self.rom, plan['token'], True)
        self.assertTrue(self.launcher.exists()); self.assertTrue(self.game.exists())
        self.assertEqual(json.loads(self.delete.imports.read_text()), imports)

    def test_removing_configuration_only_restores_pad2key_and_keeps_both_profiles(self):
        keys = Path(self.rom)/'padto.keys'
        original = b'{"actions_player1":[{"trigger":"a","type":"key","target":"KEY_ENTER"}]}'
        keys.write_bytes(original)
        self.delete.pad.suspend(self.rom)
        self.assertNotEqual(keys.read_bytes(), original)
        self.store.learn(self.rom)
        plan = self.plan(False)
        self.delete.delete(self.rom, plan['token'], False)
        self.assertEqual(keys.read_bytes(), original)
        self.assertTrue(self.launcher.exists()); self.assertTrue(self.game.exists())
        self.assertFalse(self.store.learning.exists())
        self.assertEqual(self.delete.pad.read(self.delete.pad.state), {})

    def test_deletion_cleans_only_registry_entries_for_deleted_profiles(self):
        self.delete.imports.parent.mkdir(parents=True)
        other_profile = self.folder/'Other.amgp'; other_profile.write_text(PROFILE)
        for path in (self.delete.imports, self.delete.pad.registry):
            path.write_text(json.dumps({str(self.launcher): {'old': True}, str(self.game): {'old': True}, str(other_profile): {'keep': True}}))
        plan = self.plan(); self.delete.delete(self.rom, plan['token'], True)
        for path in (self.delete.imports, self.delete.pad.registry):
            self.assertEqual(json.loads(path.read_text()), {str(other_profile): {'keep': True}})

    def test_same_profile_in_both_roles_is_deleted_only_once(self):
        self.store.save(self.rom, 'profiles', str(self.launcher), RULE, str(self.launcher))
        plan = self.plan(); self.assertEqual(len(plan['profiles']), 1)
        self.delete.delete(self.rom, plan['token'], True)
        self.assertFalse(self.launcher.exists()); self.assertTrue(self.game.exists())

    def test_missing_secondary_profile_does_not_prevent_cleaning_configuration(self):
        self.game.unlink()
        plan = self.plan()
        self.assertEqual(self.actions(plan)[str(self.game)], 'missing')
        self.delete.delete(self.rom, plan['token'], True)
        self.assertFalse(self.store.path(self.rom).exists())
        self.assertFalse(self.launcher.exists())

    def test_new_external_reference_after_confirmation_requires_a_new_plan(self):
        plan = self.plan()
        other_profile = self.folder/'Other.amgp'; other_profile.write_text(PROFILE)
        self.store.save(self.other, 'profiles', str(other_profile), RULE, str(self.game))
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.delete.delete(self.rom, plan['token'], True)
        self.assertTrue(self.game.exists()); self.assertTrue(self.launcher.exists())
        self.assertTrue(self.store.path(self.rom).exists())

    def test_changed_pad2key_is_preserved_and_deletion_is_cancelled(self):
        keys = Path(self.rom)/'padto.keys'
        keys.write_text('{"actions_player1":[]}')
        self.delete.pad.suspend(self.rom)
        keys.write_text('{"actions_player1":[],"custom":true}')
        custom = keys.read_bytes()
        plan = self.plan()
        with self.assertRaisesRegex(ValueError, 'modified externally'):
            self.delete.delete(self.rom, plan['token'], True)
        self.assertEqual(keys.read_bytes(), custom)
        self.assertTrue(self.store.path(self.rom).exists())
        self.assertTrue(self.launcher.exists()); self.assertTrue(self.game.exists())

    def test_io_failure_after_first_profile_deletion_rolls_back_everything(self):
        plan = self.plan()
        before = {p: p.read_bytes() for p in (self.launcher, self.game, self.cfg, self.store.path(self.rom))}
        real_unlink = Path.unlink
        def failing_unlink(path, *args, **kwargs):
            if path == self.launcher: raise OSError('simulated deletion failure')
            return real_unlink(path, *args, **kwargs)
        with patch.object(Path, 'unlink', failing_unlink):
            with self.assertRaisesRegex(OSError, 'simulated'):
                self.delete.delete(self.rom, plan['token'], True)
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_symlinked_profiles_are_refused_without_touching_the_target(self):
        self.game.unlink()
        outside = Path(self.temp.name)/'Outside.amgp'; outside.write_text(PROFILE)
        self.game.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.plan()
        self.assertEqual(outside.read_text(), PROFILE)
        self.assertTrue(self.store.path(self.rom).exists())

    def test_running_or_pending_live_session_blocks_deletion(self):
        plan = self.plan()
        busy = ConfigDeletion(self.home, self.userdata, active=lambda: True)
        with self.assertRaisesRegex(ValueError, 'Close the game'):
            busy.delete(self.rom, plan['token'], True)
        state = self.home/'state/antimicrox-live.json'; state.parent.mkdir(exist_ok=True)
        state.write_text('{"phase":"prepared"}')
        with self.assertRaisesRegex(ValueError, 'live editing'):
            self.delete.delete(self.rom, plan['token'], True)
        self.assertTrue(self.launcher.exists()); self.assertTrue(self.game.exists())

    def test_individual_profile_deletion_cannot_break_a_launcher_pair(self):
        manager = Profiles(self.home, self.userdata, active=lambda: False)
        for path in (self.launcher, self.game):
            with self.assertRaisesRegex(ValueError, 'launcher configuration'):
                manager.plan(path)
        self.assertTrue(self.launcher.exists()); self.assertTrue(self.game.exists())


    def test_individual_secondary_deletion_also_protects_an_unassigned_imported_pair(self):
        self.store.path(self.rom).unlink()
        self.delete.imports.parent.mkdir(parents=True)
        self.delete.imports.write_text(json.dumps({str(self.launcher): {'launcher_config': {'game_profile': str(self.game)}}}))
        manager = Profiles(self.home, self.userdata, active=lambda: False)
        with self.assertRaisesRegex(ValueError, 'stored launcher profile'):
            manager.plan(self.game)
        self.assertTrue(self.game.exists())


if __name__ == '__main__':
    unittest.main()
