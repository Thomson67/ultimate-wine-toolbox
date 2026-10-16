import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'toolbox/helpers'))
import antimicrox_notice as notice


class NoticeTests(unittest.TestCase):
    def setUp(self):
        self.gtk, self.gdk, self.glib, self.layer = Mock(), Mock(), Mock(), Mock()
        self.window = self.gtk.Window.return_value
        self.gdk.Display.get_default.return_value.get_primary_monitor.return_value.get_geometry.return_value = \
            Mock(x=0, y=0, width=1920, height=1080)

    def show(self, wayland=True, layer=True):
        with patch.dict(os.environ, {'WAYLAND_DISPLAY': 'wayland-0' if wayland else ''}):
            notice.show('Alt+Tab or Hotkey + A', self.gtk, self.gdk, self.glib,
                        self.layer if layer else None)

    def test_wayland_banner_cannot_acquire_keyboard_or_pointer_focus(self):
        self.show()
        self.window.set_accept_focus.assert_called_once_with(False)
        self.window.set_focus_on_map.assert_called_once_with(False)
        self.layer.set_keyboard_mode.assert_called_once_with(self.window, self.layer.KeyboardMode.NONE)
        self.layer.set_exclusive_zone.assert_called_once_with(self.window, 0)
        self.layer.set_layer.assert_called_once_with(self.window, self.layer.Layer.OVERLAY)
        self.window.present.assert_not_called()
        handlers = {call.args[0]: call.args[1] for call in self.window.connect.call_args_list}
        handlers['realize'](self.window)
        self.window.get_window.return_value.set_pass_through.assert_called_once_with(True)
        self.window.show_all.assert_called_once()

    def test_missing_or_unsupported_layer_never_creates_a_wayland_toplevel(self):
        with self.assertRaises(RuntimeError):
            self.show(layer=False)
        self.gtk.Window.assert_not_called()
        self.layer.is_supported.return_value = False
        with self.assertRaises(RuntimeError):
            self.show()
        self.gtk.Window.assert_not_called()

    def test_x11_uses_unmanaged_popup_with_no_focus(self):
        self.show(wayland=False, layer=False)
        self.gtk.Window.assert_called_once_with(type=self.gtk.WindowType.POPUP)
        self.window.set_accept_focus.assert_called_once_with(False)
        self.window.set_focus_on_map.assert_called_once_with(False)
        self.layer.init_for_window.assert_not_called()

    def test_notice_closes_itself_without_user_action(self):
        self.show()
        duration, close = self.glib.timeout_add_seconds.call_args.args
        self.assertEqual(duration, 6)
        self.assertFalse(close())
        self.window.destroy.assert_called_once()


if __name__ == '__main__':
    unittest.main()
