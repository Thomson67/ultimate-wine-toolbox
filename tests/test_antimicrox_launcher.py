import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'toolbox/helpers'))
import antimicrox_launcher as launcher


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.home = Path(self.folder.name)
        self.store = launcher.Store(self.home)
        self.rom = '/userdata/roms/windows/New Game.wsquashfs'
        self.launcher = self.home/'Launcher.amgp'
        self.game = self.home/'Game.amgp'
        for path in (self.launcher, self.game):
            path.write_text('<gamecontroller configversion="19"><sets/></gamecontroller>')
        self.rule = {'field': 'title', 'match': 'exact', 'value': 'New Game - Configuration'}

    def config(self, mode='launcher', game_rule=None):
        return self.store.save(self.rom, mode, str(self.launcher), self.rule,
                               str(self.game), game_rule)

    def window(self, title='New Game - Configuration', **extra):
        return dict({'title': title, 'class': 'game.exe / game.exe', 'exe': 'game.exe',
                     'window': 50, 'pid': 200, 'stamp': '101', 'prefix': '/tmp/prefix'}, **extra)

    def test_same_executable_pid_and_window_can_change_title(self):
        cfg = self.config('profiles')
        first = self.window()
        second = dict(first, title='New Game')
        self.assertEqual(launcher.selected_profile(cfg, first), str(self.launcher))
        self.assertEqual(launcher.selected_profile(cfg, second), str(self.game))
        self.assertEqual(launcher.selected_profile(cfg, first), str(self.launcher))

    def test_launcher_only_disables_mapping_in_game_and_other_apps(self):
        cfg = self.config()
        self.assertEqual(launcher.selected_profile(cfg, self.window()), str(self.launcher))
        self.assertEqual(launcher.selected_profile(cfg, self.window('New Game')), '')
        self.assertEqual(launcher.selected_profile(cfg, None), '')

    def test_explicit_game_rule_does_not_map_splash_or_error_dialog(self):
        cfg = self.config('profiles', {'field': 'title', 'match': 'exact', 'value': 'New Game'})
        self.assertEqual(launcher.selected_profile(cfg, self.window('New Game')), str(self.game))
        self.assertEqual(launcher.selected_profile(cfg, self.window('Loading…')), '')
        self.assertEqual(launcher.selected_profile(cfg, self.window('Wine error')), '')

    def test_partial_title_and_case_insensitive_executable(self):
        rule = {'field': 'title', 'match': 'contains', 'value': 'Configuration'}
        self.assertTrue(launcher.matches(rule, self.window('New Game - Configuration v2')))
        self.assertFalse(launcher.matches(rule, self.window('New Game')))
        rule = {'field': 'exe', 'match': 'exact', 'value': 'GAME.EXE'}
        self.assertTrue(launcher.matches(rule, self.window()))

    def test_scope_excludes_baseline_old_process_missing_prefix_and_other_prefix(self):
        scope = launcher.Scope('100', [40])
        for row in (dict(self.window(), window=40), dict(self.window(), stamp='99'),
                    dict(self.window(), prefix=''), None):
            self.assertIsNone(scope.accept(row))
        self.assertEqual(scope.accept(self.window()), self.window())
        self.assertIsNone(scope.accept(dict(self.window(), prefix='/other/prefix')))

    def test_short_title_fluctuations_do_not_switch_profile(self):
        state = launcher.StableChoice(.4)
        self.assertIsNone(state.observe('launcher', 0))
        self.assertIsNone(state.observe('game', .2))
        self.assertIsNone(state.observe('launcher', .3))
        self.assertIsNone(state.observe('launcher', .6))
        self.assertEqual(state.observe('launcher', .8), 'launcher')

    def test_rule_validation_rejects_empty_unknown_and_control_characters(self):
        for rule in ({}, dict(self.rule, field='command'), dict(self.rule, match='regex'),
                     dict(self.rule, value=''), dict(self.rule, value='a\nb')):
            with self.assertRaises(ValueError):
                launcher.validate_rule(rule)

    def test_normal_profile_reassignment_supersedes_old_launcher_rules(self):
        self.config()
        self.assertIsNotNone(self.store.load(self.rom, str(self.launcher)))
        self.assertIsNone(self.store.load(self.rom, str(self.game)))

    def test_invalid_profile_and_missing_secondary_profile_are_refused(self):
        self.game.write_text('<not-a-profile/>')
        with self.assertRaises(ValueError):
            self.config('profiles')
        self.assertFalse(self.store.path(self.rom).exists())
        self.game.unlink()
        with self.assertRaises(OSError):
            self.config('profiles')

    def test_empty_profile_has_no_actions_and_does_not_replace_real_profiles(self):
        self.config()
        empty = Path(self.store.empty())
        self.assertTrue(launcher.valid_profile(empty))
        self.assertNotIn('<slot>', empty.read_text())
        self.assertEqual(self.launcher.read_text(), '<gamecontroller configversion="19"><sets/></gamecontroller>')

    def run_watch(self, learning=False, mode='profiles', api_sequence=None):
        self.config(mode)
        self.store.learn(self.rom)
        now = [0.0]
        session = Mock(home=self.home, rom=self.rom, pid=42, stamp='100')
        session.active.side_effect = lambda: now[0] < 4
        rows = [(0, self.window()), (1, self.window('New Game')),
                (2, None), (3, self.window())]
        windows = Mock()
        windows.snapshot.side_effect = lambda _: next(row for start, row in reversed(rows) if now[0] >= start)
        api = Mock()
        api.running.side_effect = api_sequence or (lambda: (200, self.rom))
        calls = []
        def apply(owner, profile, binary):
            calls.append((round(now[0], 2), profile))
            return True
        launcher.watch(session, windows, [], learning=learning, api=api,
                       clock=lambda: now[0], sleep=lambda delay: now.__setitem__(0, now[0]+delay),
                       apply=apply)
        return calls

    def test_runtime_roundtrip_and_foreign_focus_reset(self):
        calls = self.run_watch()
        self.assertEqual([p for _, p in calls], [str(self.launcher), str(self.game),
                                               self.store.empty(), str(self.launcher)])

    def test_launcher_only_runtime_never_applies_a_game_profile(self):
        calls = self.run_watch(mode='launcher')
        self.assertEqual([p for _, p in calls], [str(self.launcher), self.store.empty(), str(self.launcher)])

    def test_learning_records_title_changes_without_switching_any_mapping(self):
        calls = self.run_watch(learning=True)
        self.assertEqual(calls, [])
        rows = self.store.observations(self.rom)
        self.assertEqual([row['title'] for row in rows], ['New Game - Configuration', 'New Game'])
        self.assertEqual(rows[0]['pid'], rows[1]['pid'])
        self.assertEqual(self.store.observations('/other-game'), [])

    def test_startup_allows_es_to_publish_the_new_game_after_the_hook(self):
        self.run_watch(learning=True, api_sequence=[(200, '/toolbox'), (200, self.rom),
                                                    (200, self.rom), (200, self.rom)])
        self.assertTrue(self.store.observations(self.rom))

    def test_session_change_stops_observer_and_clears_mapping(self):
        calls = self.run_watch(api_sequence=[(200, self.rom), (200, self.rom),
                                             (200, '/other-game')])
        self.assertEqual(calls[-1][1], self.store.empty())

    def test_temporary_api_failure_clears_profile_then_can_recover(self):
        calls = self.run_watch(api_sequence=[(200, self.rom), (None, ''),
                                             (200, self.rom), (200, self.rom)])
        profiles = [profile for _, profile in calls]
        self.assertEqual(profiles[:2], [str(self.launcher), self.store.empty()])
        self.assertEqual(profiles[-1], str(self.launcher))

    def test_es_game_closed_clears_mapping_even_without_a_game_stop_hook(self):
        calls = self.run_watch(api_sequence=[(200, self.rom), (201, '')])
        self.assertEqual(calls[-1][1], self.store.empty())


if __name__ == '__main__':
    unittest.main()
