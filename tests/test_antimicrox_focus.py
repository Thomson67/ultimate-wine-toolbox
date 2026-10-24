import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

HELPERS = Path(__file__).resolve().parents[1]/'toolbox/helpers'
sys.path.insert(0, str(HELPERS))
import antimicrox_focus as focus


class DirectSwitchTests(unittest.TestCase):
    def setUp(self):
        self.owner = Mock(pid=42, rom='/userdata/roms/windows/Game.wine')
        self.owner.active.return_value = True
        self.windows = Mock()
        self.windows.current.return_value = ('game', 20)
        self.windows.game_window.return_value = 20
        self.windows.editor_window.return_value = 10
        self.windows.client_windows.return_value = [10, 20, 30]
        self.api = Mock()
        self.api.running.return_value = (200, self.owner.rom)

    def switch(self):
        return focus.toggle_window(self.owner, self.windows, self.api)

    def test_direct_activation_reaches_editor_without_alt_tab(self):
        self.assertTrue(self.switch())
        self.windows.activate.assert_called_once_with(10)

    def test_same_shortcut_returns_from_editor_to_game(self):
        self.windows.current.return_value = ('editor', 10)
        self.assertTrue(self.switch())
        self.windows.activate.assert_called_once_with(20)

    def test_other_foreground_apps_or_unknown_focus_are_not_interrupted(self):
        for kind in ('other', 'unknown'):
            self.windows.current.return_value = (kind, 30)
            self.assertFalse(self.switch())
        self.windows.activate.assert_not_called()

    def test_unlisted_active_window_does_not_block_editor_activation(self):
        self.windows.current.return_value = ('other', 2097157)
        self.assertTrue(self.switch())
        self.windows.activate.assert_called_once_with(10)

    def test_no_active_x11_window_can_recover_editor_when_game_is_present(self):
        self.windows.current.return_value = ('unknown', 0)
        self.assertTrue(self.switch())
        self.windows.activate.assert_called_once_with(10)

    def test_unlisted_focus_requires_game_editor_and_matching_es_session(self):
        self.windows.current.return_value = ('other', 2097157)
        self.windows.game_window.return_value = 0
        self.assertFalse(self.switch())
        self.windows.game_window.return_value = 20
        self.windows.editor_window.return_value = 0
        self.assertFalse(self.switch())
        self.windows.editor_window.return_value = 10
        self.api.running.return_value = (200, '/another/game.wine')
        self.assertFalse(self.switch())
        self.windows.activate.assert_not_called()

    def test_foreign_window_becoming_managed_during_es_check_cancels_recovery(self):
        self.windows.current.return_value = ('other', 2097157)
        self.windows.client_windows.side_effect = [[10, 20], [10, 20, 2097157]]
        self.assertFalse(self.switch())
        self.windows.activate.assert_not_called()

    def test_game_window_disappearing_during_es_check_cancels_recovery(self):
        self.windows.current.return_value = ('other', 2097157)
        self.windows.game_window.side_effect = [20, 0]
        self.assertFalse(self.switch())
        self.windows.activate.assert_not_called()

    def test_wrong_rom_or_missing_target_is_not_activated(self):
        self.api.running.return_value = (200, '/another/game.wine')
        self.assertFalse(self.switch())
        self.api.running.return_value = (200, self.owner.rom)
        self.windows.editor_window.return_value = 0
        self.assertFalse(self.switch())
        self.windows.activate.assert_not_called()

    def test_session_or_focus_change_during_api_call_cancels_activation(self):
        self.owner.active.side_effect = [True, False]
        self.assertFalse(self.switch())
        self.owner.active.side_effect = None
        self.windows.current.side_effect = [('game', 20), ('other', 30)]
        self.assertFalse(self.switch())
        self.windows.activate.assert_not_called()

    def test_stale_session_token_and_duplicate_controller_events_are_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder); state = home/'state'; (state/'antimicrox').mkdir(parents=True)
            data = {'rom': self.owner.rom, 'phase': 'running', 'session_id': 'current'}
            (state/'antimicrox-live.json').write_text(json.dumps(data))
            (state/'antimicrox/session').write_text(f'{self.owner.rom}\t42\t123\n')
            with patch.object(focus, 'process_start', return_value='123'), \
                 patch.object(focus, 'XWindows', return_value=self.windows) as factory, \
                 patch.object(focus, 'EsApi', return_value=self.api):
                self.assertFalse(focus.toggle(home, 'previous'))
                factory.assert_not_called()
                self.assertTrue(focus.toggle(home, 'current'))
                self.assertFalse(focus.toggle(home, 'current'))
                self.windows.activate.assert_called_once_with(10)
                self.windows.close.assert_called_once()


class FocusTests(unittest.TestCase):
    def test_direct_mode_never_opens_a_refresh_window_after_returns(self):
        owner = Mock(pid=42, rom='/game')
        owner.read.return_value = {'action': {'type': 'exec'}}
        windows, run = Mock(), Mock()
        focus.watch(owner, windows, run=run, show_intro=False)
        windows.current.assert_not_called()
        run.assert_not_called()

    def test_user_switch_marker_is_scoped_to_this_session(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder); state = home/'state'; (state/'antimicrox').mkdir(parents=True)
            (state/'antimicrox-live.json').write_text(json.dumps({'session_id': 'current'}))
            owner = focus.Owner(home, '/game', 42, '123')
            self.assertFalse(owner.user_switched())
            marker = state/'antimicrox/toggle.lock'
            marker.write_text('old\t1.0\n')
            self.assertFalse(owner.user_switched())
            marker.write_text('current\t2.0\n')
            self.assertTrue(owner.user_switched())

    def test_initial_game_and_other_apps_do_not_trigger(self):
        tracker = focus.Returns()
        for kind, now in [('game', 0), ('game', 1), ('editor', 2),
                          ('other', 3), ('game', 4), ('game', 5)]:
            self.assertIsNone(tracker.observe((kind, 10), now))

    def test_one_refresh_per_stable_return_and_rearm(self):
        tracker = focus.Returns()
        for current, now in [(('editor', 1), 0), (('unknown', 0), .1),
                              (('game', 2), .2), (('game', 2), .3)]:
            self.assertIsNone(tracker.observe(current, now))
        self.assertEqual(tracker.observe(('game', 2), .5), 2)
        self.assertIsNone(tracker.observe(('game', 2), 1))
        self.assertIsNone(tracker.observe(('other', 3), 2))  # our own GTK popup
        self.assertIsNone(tracker.observe(('game', 2), 3))
        tracker.observe(('editor', 1), 4)
        tracker.observe(('game', 2), 5)
        self.assertEqual(tracker.observe(('game', 2), 5.3), 2)

    def test_changing_game_windows_resets_stability_timer(self):
        tracker = focus.Returns()
        tracker.observe(('editor', 1), 0)
        tracker.observe(('game', 2), 1)
        self.assertIsNone(tracker.observe(('game', 3), 1.3))
        self.assertIsNone(tracker.observe(('game', 3), 1.4))
        self.assertEqual(tracker.observe(('game', 3), 1.6), 3)

    def run_watcher(self, api, window_after_api=('game', 2), cancel=False):
        owner = Mock(pid=42, rom='/userdata/roms/windows/Game.wsquashfs')
        owner.active.return_value = True
        windows = Mock()
        windows.current.side_effect = [('editor', 1), ('game', 2), ('game', 2), window_after_api]
        def running():
            if cancel:
                owner.active.return_value = False
            return api
        service = Mock(); service.running.side_effect = running
        runner = Mock(return_value=Mock(returncode=0))
        calls = []
        def sleep(_):
            calls.append(1)
            if len(calls) == 3:
                owner.active.return_value = False
        focus.watch(owner, windows, service, clock=iter([0, 1, 1.3]).__next__,
                    sleep=sleep, run=runner, show_intro=False)
        return runner

    def test_verified_return_runs_only_the_timed_popup(self):
        runner = self.run_watcher((200, '/userdata/roms/windows/Game.wsquashfs'))
        runner.assert_called_once()
        self.assertEqual(runner.call_args.args[0],
                         ['batocera-flash-screen', '0.3', 'white', 'Retour au jeu', '12'])
        self.assertEqual(runner.call_args.kwargs['timeout'], 3)

    def test_other_rom_and_focus_changes_skip_refresh(self):
        self.run_watcher((200, '/another.wine')).assert_not_called()
        self.run_watcher((201, '')).assert_not_called()
        self.run_watcher((200, '/userdata/roms/windows/Game.wsquashfs'),
                         ('other', 3)).assert_not_called()

    def test_cancelled_session_skips_refresh(self):
        self.run_watcher((200, '/userdata/roms/windows/Game.wsquashfs'), cancel=True).assert_not_called()

    def test_owner_requires_pid_stamp_rom_and_session_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); (base/'state/antimicrox').mkdir(parents=True)
            state = base/'state/antimicrox-live.json'
            data = {'rom': '/game.wsquashfs', 'session_id': 'abc', 'phase': 'running'}
            state.write_text(json.dumps(data))
            (base/'state/antimicrox/session').write_text('/game.wsquashfs\t42\t123\n')
            owner = focus.Owner(base, '/game.wsquashfs', 42, '123')
            with patch.object(focus, 'process_start', return_value='123'):
                self.assertTrue(owner.active())
                data['session_id'] = 'replacement'; state.write_text(json.dumps(data))
                self.assertFalse(owner.active())
                data['session_id'] = 'abc'; state.write_text(json.dumps(data))
            with patch.object(focus, 'process_start', return_value='456'):
                self.assertFalse(owner.active())

    def test_failed_popup_does_not_loop_or_crash_session(self):
        owner = Mock(pid=42, rom='/game')
        owner.active.side_effect = [True, True, True, True, False]
        windows = Mock(); windows.current.side_effect = [('editor', 1), ('game', 2), ('game', 2), ('game', 2)]
        api = Mock(); api.running.return_value = (200, '/game')
        run = Mock(side_effect=OSError('not available'))
        focus.watch(owner, windows, api, clock=iter([0, 1, 1.3]).__next__, sleep=lambda _: None, run=run,
                    show_intro=False)
        run.assert_called_once()


class IntroductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        home = Path(self.temp.name); (home/'config').mkdir()
        (home/'config/language').write_text('fr\n')
        self.owner = Mock(pid=42, rom='/userdata/roms/windows/Game.wsquashfs', home=home)
        self.owner.active.return_value = True
        self.owner.user_switched.return_value = False
        self.owner.read.return_value = {'switch_fr': 'Hotkey + Select', 'switch_en': 'Hotkey + R1 / RB'}
        self.now = 0
        self.windows = Mock()
        self.windows.current.return_value = ('editor', 1)
        self.windows.game_window.return_value = 0
        self.api = Mock(); self.api.running.return_value = (200, self.owner.rom)
        self.run = Mock()

    def intro(self, advance=None, timeout=5):
        def sleep(seconds):
            self.now += seconds
            if advance: advance(self.now)
        focus.introduction(self.owner, self.windows, self.api, clock=lambda: self.now,
                           sleep=sleep, run=self.run, timeout=timeout)

    def test_waits_for_game_then_activates_once_and_shows_switch_instructions(self):
        self.windows.activate.side_effect = lambda _: setattr(self.windows.current, 'return_value', ('game', 2))
        def advance(now):
            if now >= 1: self.windows.game_window.return_value = 2
        self.intro(advance)
        self.windows.activate.assert_called_once_with(2)
        self.run.assert_called_once()
        command = self.run.call_args.args[0]
        self.assertEqual(Path(command[1]).name, 'antimicrox_notice.py')
        self.assertNotIn('batocera-flash-screen', command)
        self.assertIn('Hotkey + Select', command[2])

    def test_already_foreground_game_only_shows_popup_once_in_english(self):
        (self.owner.home/'config/language').write_text('en\n')
        self.windows.current.return_value = ('game', 2)
        self.intro()
        self.windows.activate.assert_not_called()
        self.run.assert_called_once()
        self.assertIn('Hotkey + R1 / RB', self.run.call_args.args[0][2])

    def test_other_app_is_not_interrupted_and_wrong_rom_gets_no_popup(self):
        self.windows.game_window.return_value = 2
        self.windows.current.return_value = ('other', 3)
        self.intro()
        self.windows.activate.assert_not_called(); self.run.assert_not_called()
        self.now = 0; self.windows.current.return_value = ('editor', 1)
        self.api.running.return_value = (200, '/other.wine')
        self.intro()
        self.windows.activate.assert_not_called(); self.run.assert_not_called()

    def test_failed_activation_never_displays_popup_over_editor_or_retries(self):
        self.windows.game_window.return_value = 2
        self.intro(timeout=10)
        self.windows.activate.assert_called_once_with(2)
        self.run.assert_not_called()

    def test_session_stops_before_game_appears(self):
        self.intro(lambda now: setattr(self.owner.active, 'return_value', False))
        self.windows.activate.assert_not_called(); self.run.assert_not_called()

    def test_focus_changes_during_api_call_do_not_raise_game(self):
        self.windows.game_window.return_value = 2
        def running():
            self.windows.current.return_value = ('other', 3)
            return 200, self.owner.rom
        self.api.running.side_effect = running
        self.intro()
        self.windows.activate.assert_not_called(); self.run.assert_not_called()

    def test_missing_popup_tool_does_not_repeat_or_stop_session(self):
        self.windows.current.return_value = ('game', 2)
        self.run.side_effect = OSError('missing')
        self.intro()
        self.run.assert_called_once()
        self.assertTrue(self.owner.active())

    def test_manual_switch_cancels_delayed_startup_activation(self):
        self.windows.game_window.return_value = 2
        self.intro(lambda now: setattr(self.owner.user_switched, 'return_value', now >= .5))
        self.windows.activate.assert_not_called()
        self.run.assert_not_called()

    def test_manual_switch_during_es_check_prevents_startup_activation(self):
        self.windows.game_window.return_value = 2
        def running():
            self.owner.user_switched.return_value = True
            return 200, self.owner.rom
        self.api.running.side_effect = running
        self.intro()
        self.windows.activate.assert_not_called()
        self.run.assert_not_called()
