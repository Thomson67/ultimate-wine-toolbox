import ctypes as C
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'toolbox/helpers'))
import antimicrox_trace as trace


class RecorderTests(unittest.TestCase):
    def test_only_changed_snapshots_are_recorded_with_relative_times(self):
        output = io.StringIO()
        now = [10.0]
        recorder = trace.Recorder(output, clock=lambda: now[0])
        value = {'active': '0x10', 'keyboard_focus': '0x10', 'windows': []}
        recorder.snapshot(value); recorder.snapshot(dict(value))
        now[0] = 10.125
        recorder.snapshot(dict(value, keyboard_focus='0x20'))
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(rows), 2)
        self.assertEqual([row['elapsed'] for row in rows], [0, .125])
        self.assertEqual(rows[1]['keyboard_focus'], '0x20')


class TraceEventTests(unittest.TestCase):
    def window(self, events):
        window = trace.TraceWindows.__new__(trace.TraceWindows)
        window.display = 1; window.subscribed = {0x10}
        window.atoms = {'_NET_WM_STATE': 7}
        window.atom_name = lambda atom: '_NET_WM_STATE' if atom == 7 else 'unrelated'
        window.x = Mock()
        window.x.XPending.side_effect = lambda _: len(events)
        def read(_, pointer):
            item = events.pop(0)
            C.memmove(pointer, C.byref(item), C.sizeof(trace.Event))
        window.x.XNextEvent.side_effect = read
        return window

    def test_focus_modes_and_geometry_transition_are_retained(self):
        out, small, large, inside = (trace.Event() for _ in range(4))
        out.focus.type = 10; out.focus.window = 0x10; out.focus.mode = 1
        inside.focus.type = 9; inside.focus.window = 0x10; inside.focus.mode = 2
        for event, width, height in [(small, 100, 80), (large, 1920, 1080)]:
            event.configure.type = 22; event.configure.window = 0x10
            event.configure.width, event.configure.height = width, height
        window = self.window([out, small, large, inside])
        rows = window.events()
        self.assertEqual([r['event'] for r in rows],
                         ['FocusOut', 'ConfigureNotify', 'ConfigureNotify', 'FocusIn'])
        self.assertEqual(rows[0]['mode'], 'grab')
        self.assertEqual(rows[1]['geometry'], [0, 0, 100, 80])
        self.assertEqual(rows[2]['geometry'], [0, 0, 1920, 1080])
        self.assertEqual(rows[3]['mode'], 'ungrab')
        window.x.XSendEvent.assert_not_called()
        window.x.XSetInputFocus.assert_not_called()

    def test_mapping_and_destroy_events_keep_window_identity(self):
        events = []
        for kind in (18, 19, 17):
            event = trace.Event(); event.structure.type = kind; event.structure.window = 0x10
            events.append(event)
        window = self.window(events)
        rows = window.events()
        self.assertEqual([r['event'] for r in rows], ['UnmapNotify', 'MapNotify', 'DestroyNotify'])
        self.assertTrue(all(row['window'] == '0x10' for row in rows))
        self.assertNotIn(0x10, window.subscribed)

    def test_properties_are_filtered_and_batches_are_bounded(self):
        events = []
        for atom in (7, 8, 7):
            event = trace.Event(); event.property.type = 28; event.property.window = 0x10
            event.property.atom = atom; events.append(event)
        window = self.window(events)
        self.assertEqual(len(window.events(limit=2)), 1)
        self.assertEqual(len(events), 1)
        self.assertEqual(window.events()[0]['property'], '_NET_WM_STATE')

    def test_only_e_and_escape_are_observed_in_keyboard_snapshot(self):
        window = self.window([])
        window.root = 1; window.watched = {'E': 26, 'Escape': 9}
        window.client_windows = lambda: []
        window.cardinal = lambda *_: 0
        def query(_, keys):
            for code in (9, 30):
                keys[code//8] |= 1 << (code % 8)
        window.x.XQueryKeymap.side_effect = query
        snapshot = window.snapshot(42)
        self.assertEqual(snapshot['watched_keys_down'], ['Escape'])
        self.assertEqual(snapshot['active'], '0x0')
        window.x.XSendEvent.assert_not_called()

    def test_explicit_focus_probe_sends_protocol_to_game_with_server_timestamp(self):
        window = self.window([])
        window.atoms['WM_PROTOCOLS'] = 12
        window.x.XInternAtom.return_value = 55
        window.cardinals = Mock(return_value=[55])
        window.server_time = Mock(return_value=123456)
        window.x.XSendEvent.return_value = 1
        sent = []
        def capture(display, target, propagate, mask, pointer):
            event = trace.Event()
            C.memmove(C.byref(event), pointer, C.sizeof(event))
            sent.append((target, mask, event.message.message_type, list(event.message.data)))
            return 1
        window.x.XSendEvent.side_effect = capture
        self.assertTrue(window.offer_focus(0x10))
        self.assertEqual(sent, [(0x10, 0, 12, [55, 123456, 0, 0, 0])])
        window.x.XSetInputFocus.assert_not_called()

    def test_focus_probe_refuses_clients_without_the_protocol(self):
        window = self.window([])
        window.x.XInternAtom.return_value = 55
        window.cardinals = Mock(return_value=[])
        with self.assertRaises(RuntimeError):
            window.offer_focus(0x10)
        window.x.XSendEvent.assert_not_called()

    def test_timestamp_window_is_never_mapped_and_is_destroyed(self):
        window = self.window([])
        window.root = 1
        window.x.XCreateSimpleWindow.return_value = 99
        def timestamp(display, target, mask, pointer):
            event = trace.Event()
            event.property.type = 28; event.property.time = 654321
            C.memmove(pointer, C.byref(event), C.sizeof(event))
            return 0
        window.x.XWindowEvent.side_effect = timestamp
        self.assertEqual(window.server_time(), 654321)
        window.x.XDestroyWindow.assert_called_once_with(1, 99)
        window.x.XMapWindow.assert_not_called()
        window.x.XMapRaised.assert_not_called()


if __name__ == '__main__':
    unittest.main()
