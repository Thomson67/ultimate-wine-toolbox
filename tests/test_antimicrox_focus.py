import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

HELPERS = Path(__file__).resolve().parents[1]/'toolbox/helpers'
sys.path.insert(0, str(HELPERS))
import antimicrox_focus as focus


class FocusTests(unittest.TestCase):
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
                    sleep=sleep, run=runner)
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
        focus.watch(owner, windows, api, clock=iter([0, 1, 1.3]).__next__, sleep=lambda _: None, run=run)
        run.assert_called_once()
