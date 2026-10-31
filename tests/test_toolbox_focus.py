import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'toolbox/helpers'))
import toolbox_focus as helper


class Clock:
    now = 0
    def clock(self): return self.now
    def sleep(self, seconds): self.now += seconds


class Windows:
    root = 1
    target = 20
    active = 10
    def __init__(self): self.calls = []
    def editor_window(self, pid): return self.target
    def cardinal(self, window, name):
        return self.active if name == '_NET_ACTIVE_WINDOW' else 100
    def activate(self, target):
        self.calls.append(target)
        self.active = target


class ToolboxFocusTests(unittest.TestCase):
    def run_focus(self, windows, clock, identity=lambda pid: 'same'):
        return helper.activate_return(200, 201, windows, identity=identity,
                                     es=lambda pid: pid == 100,
                                     clock=clock.clock, sleep=clock.sleep,
                                     log=lambda text: None)

    def test_hidden_terminal_is_activated_and_confirmation_stops_worker(self):
        windows, clock = Windows(), Clock()
        self.assertTrue(self.run_focus(windows, clock))
        self.assertEqual(windows.calls, [20])
        self.assertLess(clock.now, 2)

    def test_never_steals_focus_from_another_application(self):
        windows, clock = Windows(), Clock()
        windows.cardinal = lambda window, name: 99 if name == '_NET_WM_PID' else 10
        self.assertFalse(self.run_focus(windows, clock))
        self.assertEqual(windows.calls, [])

    def test_pid_reuse_or_closed_session_prevents_activation(self):
        windows, clock = Windows(), Clock()
        count = 0
        def identity(pid):
            nonlocal count
            count += 1
            return 'old' if count <= 2 else 'new'
        self.assertFalse(self.run_focus(windows, clock, identity))
        self.assertEqual(windows.calls, [])

    def test_ignored_requests_are_bounded(self):
        windows, clock = Windows(), Clock()
        windows.activate = lambda target: windows.calls.append(target)
        self.assertFalse(self.run_focus(windows, clock))
        self.assertEqual(windows.calls, [20, 20, 20])
        self.assertLess(clock.now, 8.2)

    def test_initial_focus_loss_to_es_can_be_retried(self):
        windows, clock = Windows(), Clock()
        def activate(target):
            windows.calls.append(target)
            if len(windows.calls) > 1:
                windows.active = target
        windows.activate = activate
        self.assertTrue(self.run_focus(windows, clock))
        self.assertEqual(windows.calls, [20, 20])

    def test_missing_window_times_out_without_activation(self):
        windows, clock = Windows(), Clock()
        windows.target = 0
        self.assertFalse(self.run_focus(windows, clock))
        self.assertEqual(windows.calls, [])
        self.assertLess(clock.now, 8.2)
