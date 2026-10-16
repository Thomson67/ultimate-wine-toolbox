"""Show live-session instructions without activating a desktop window."""
import os
import sys


def show(message, Gtk, Gdk, GLib, layer=None):
    # Wayland requires a non-interactive layer surface. Never substitute a
    # regular toplevel there: old DirectInput games can crash on focus loss.
    if os.environ.get('WAYLAND_DISPLAY') and (layer is None or not layer.is_supported()):
        raise RuntimeError('Non-interactive Wayland overlay unavailable; notice skipped')
    window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL if layer else Gtk.WindowType.POPUP)
    window.set_title('UWT AntiMicroX instructions')
    window.set_decorated(False)
    window.set_accept_focus(False)
    window.set_focus_on_map(False)
    window.set_skip_taskbar_hint(True)
    window.set_skip_pager_hint(True)
    if layer:
        layer.init_for_window(window)
        layer.set_namespace(window, 'uwt-antimicrox-notice')
        layer.set_layer(window, layer.Layer.OVERLAY)
        layer.set_keyboard_mode(window, layer.KeyboardMode.NONE)
        layer.set_exclusive_zone(window, 0)
        layer.set_anchor(window, layer.Edge.TOP, True)
        layer.set_margin(window, layer.Edge.TOP, 24)
    else:
        window.set_type_hint(Gdk.WindowTypeHint.NOTIFICATION)

    display = Gdk.Display.get_default()
    monitor = display.get_primary_monitor() or display.get_monitor(0)
    bounds = monitor.get_geometry() if monitor else None
    width = min(1280, max(1, bounds.width-48)) if bounds else 960
    window.set_size_request(width, -1)
    if layer and monitor:
        layer.set_monitor(window, monitor)
    elif bounds:
        window.move(bounds.x+(bounds.width-width)//2, bounds.y+24)
    label = Gtk.Label(label=message)
    label.set_line_wrap(True)
    label.set_justify(Gtk.Justification.CENTER)
    for side in ('top', 'bottom', 'start', 'end'):
        getattr(label, f'set_margin_{side}')(12)
    window.add(label)
    css = Gtk.CssProvider()
    css.load_from_data(b'window { background-color: #20242a; } label { color: white; font-size: 18pt; }')
    Gtk.StyleContext.add_provider_for_screen(window.get_screen(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def realized(widget):
        # Empty pointer/touch input region; controller/keyboard stay with game.
        widget.get_window().set_pass_through(True)
    window.connect('realize', realized)
    window.connect('destroy', lambda *_: Gtk.main_quit())
    def close():
        window.destroy()
        return False
    GLib.timeout_add_seconds(6, close)
    window.show_all()
    Gtk.main()


def main():
    os.environ.setdefault('NO_AT_BRIDGE', '1')
    if os.environ.get('WAYLAND_DISPLAY'):
        os.environ['GDK_BACKEND'] = 'wayland'
    else:
        os.environ['GDK_BACKEND'] = 'x11'
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
    from gi.repository import Gtk, Gdk, GLib
    layer = None
    if os.environ.get('WAYLAND_DISPLAY'):
        gi.require_version('GtkLayerShell', '0.1')
        from gi.repository import GtkLayerShell
        layer = GtkLayerShell
    ok, _ = Gtk.init_check(sys.argv)
    if not ok:
        raise RuntimeError('No GTK display; notice skipped')
    show(sys.argv[1], Gtk, Gdk, GLib, layer)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ImportError, ValueError, RuntimeError) as exc:
        print(f'AntiMicroX passive notice unavailable: {exc}', file=sys.stderr)
        raise SystemExit(1)
