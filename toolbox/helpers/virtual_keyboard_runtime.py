"""Non-focus-stealing GTK keyboard with controller navigation and uinput keys.

GTK/evdev are imported only at runtime, leaving policy and model testable on
ordinary Linux hosts. No clipboard, background text scraping or game injection.
"""
import ctypes as C
import ctypes.util
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import urllib.request
import xml.etree.ElementTree as ET

from antimicrox_live import atomic
from virtual_keyboard import Settings, conflict, process_identity


class KeyboardModel:
    def __init__(self, french=True):
        self.french, self.upper, self.symbols = french, False, False
        self.row = self.col = 0

    def rows(self):
        if self.symbols:
            rows = [list('1234567890'), list('-_@./:!?+='), list('()[]#%,;\'"')]
        elif self.french:
            rows = [list('azertyuiop'), list('qsdfghjklm'), list('wxcvbn')+list('éèàç')]
        else:
            rows = [list('qwertyuiop'), list('asdfghjkl'), list('zxcvbnm')]
        if self.upper and not self.symbols:
            rows = [[char.upper() for char in row] for row in rows]
        return rows+[['cursor_left', 'cursor_down', 'cursor_up', 'cursor_right', 'home', 'end', 'delete'],
                     ['shift', 'symbols', 'backspace', 'space', 'enter', 'close']]

    def selected(self):
        rows = self.rows()
        self.row %= len(rows)
        self.col = min(self.col, len(rows[self.row])-1)
        return rows[self.row][self.col]

    def move(self, direction):
        if direction in ('up', 'down'):
            self.row = (self.row+(1 if direction == 'down' else -1)) % len(self.rows())
            self.col = min(self.col, len(self.rows()[self.row])-1)
        else:
            self.col = (self.col+(1 if direction == 'right' else -1)) % len(self.rows()[self.row])

    def activate(self, action=None):
        action = action or self.selected()
        if action == 'shift': self.upper = not self.upper
        elif action == 'symbols': self.symbols = not self.symbols
        else: return action
        self.selected()
        return None


def bindings(config, hat_axes=None):
    """Use Linux event codes recorded by ES; never guess a controller layout."""
    result = {}
    for item in config.findall('input'):
        name, kind = item.get('name'), item.get('type')
        try:
            value = int(item.get('value', '1'))
            code = int(item.get('code', '-1'))
        except (TypeError, ValueError):
            continue
        if kind not in ('button', 'axis', 'hat'): continue
        if kind == 'hat':
            # Some ES entries store only the SDL hat id (or code=0), not an
            # evdev ABS_HAT code. Resolve its index against the actual device's
            # available X/Y hat pairs instead of confusing it with stick axes.
            if 16 <= code <= 23:
                base = code if code % 2 == 0 else code-1
            else:
                try: index = int(item.get('id', str(code)))
                except (TypeError, ValueError): continue
                pairs = [axis for axis in range(16, 24, 2)
                         if axis in (hat_axes or []) and axis+1 in (hat_axes or [])]
                if not 0 <= index < len(pairs): continue
                base = pairs[index]
            for direction, axis, sign in [('up', base+1, -1), ('down', base+1, 1),
                                           ('left', base, -1), ('right', base, 1)]:
                bit = {'up': 1, 'right': 2, 'down': 4, 'left': 8}[direction]
                if value & bit: result[name] = ('axis', axis, sign)
        else:
            if code < 0 or (kind == 'button' and code < 0x100): continue
            result[name] = (kind, code, 1 if value >= 0 else -1)
    if (result.get('hotkey') is None or result.get('select') is None
            or result['hotkey'] == result['select']):
        raise ValueError('Hotkey and Select require distinct recorded Linux event codes')
    if any(result[k][0] != 'button' for k in ('hotkey', 'select')):
        raise ValueError('Hotkey and Select must be buttons')
    for name in ('b', 'a', 'start'):
        if name not in result: raise ValueError(f'Missing Linux input mapping: {name}')
    for source, first, second in [('joystick1left', 'left', 'right'), ('joystick1up', 'up', 'down')]:
        if source in result:
            kind, code, sign = result[source]
            result.setdefault('joystick1'+second, (kind, code, -sign))
            if first not in result:
                result[first] = kind, code, sign
                result[second] = kind, code, -sign
    return result


class Controller:
    def __init__(self, device, mapping, ecodes):
        self.device, self.mapping, self.e = device, mapping, ecodes
        self.values, self.down = {}, set(device.active_keys())
        self.captured = False
        # A held shortcut at process startup must first be released.
        self.armed = not bool(device.active_keys())
        self.chord = False
        self.syncing = False
        self.repeat_at, self.repeated = 0, None
        self.limits = {code: device.absinfo(code) for kind, code, _ in mapping.values() if kind == 'axis'}
        self.values = {code: info.value for code, info in self.limits.items()}

    def logical(self):
        down = set()
        for name, (kind, code, sign) in self.mapping.items():
            if name in ('joystick1left', 'joystick1right', 'joystick1up', 'joystick1down'):
                name = name[len('joystick1'):]
            if kind == 'button':
                if code in self.down: down.add(name)
            else:
                limits = self.limits[code]
                center = (limits.min+limits.max)/2
                radius = max(1, (limits.max-limits.min)/2)
                if sign*(self.values.get(code, center)-center)/radius > .55: down.add(name)
        return down

    def poll(self):
        actions, events = [], []
        # DualSense sensor traffic can exceed one evdev batch per GTK tick.
        # Drain the backlog with a bound so input cannot starve the GUI.
        for _ in range(64):
            try:
                batch = list(self.device.read())
            except BlockingIOError:
                break
            if not batch:
                break
            events.extend(batch)
        dropped = [i for i, e in enumerate(events)
                   if e.type == self.e.EV_SYN and e.code == self.e.SYN_DROPPED]
        if self.syncing or dropped:
            self.syncing = True
            self.repeated = None
            start = dropped[-1]+1 if dropped else 0
            # Ignore the damaged frame through SYN_REPORT, then query the
            # kernel's authoritative state instead of replaying partial input.
            if any(e.type == self.e.EV_SYN and e.code == self.e.SYN_REPORT for e in events[start:]):
                self.down = set(self.device.active_keys())
                self.limits = {code: self.device.absinfo(code) for code in self.limits}
                self.values = {code: info.value for code, info in self.limits.items()}
                held = self.logical()
                self.chord = {'hotkey', 'select'} <= held
                self.armed = not bool(held)
                self.syncing = False
                print('virtual_keyboard_controller_resynced', flush=True)
            return []
        for event in events:
            before = self.logical()
            if event.type == self.e.EV_KEY:
                if event.value: self.down.add(event.code)
                else: self.down.discard(event.code)
            elif event.type == self.e.EV_ABS: self.values[event.code] = event.value
            after = self.logical()
            if not after: self.armed = True
            chord = {'hotkey', 'select'} <= after
            if self.armed and chord and not self.chord: actions.append('toggle')
            self.chord = chord
            if self.armed and {'hotkey', 'start'} <= after and 'start' not in before:
                actions.append('exit')
            if self.captured and 'hotkey' not in after:
                actions.extend(k for k in ('up', 'down', 'left', 'right', 'b', 'a', 'x', 'y', 'start', 'pageup', 'pagedown') if k in after-before)
            if self.captured:
                direction = next((k for k in ('up', 'down', 'left', 'right') if k in after), None)
                if direction != self.repeated:
                    self.repeated, self.repeat_at = direction, time.monotonic()+.38
        if self.captured and self.repeated and time.monotonic() >= self.repeat_at:
            if 'hotkey' not in self.logical(): actions.append(self.repeated)
            self.repeat_at = time.monotonic()+.10
        return actions

    def released(self):
        return not self.syncing and not self.device.active_keys() and not self.logical()

    def grab(self):
        if not self.captured:
            self.device.grab()
            self.captured = True

    def ungrab(self):
        if self.captured:
            self.device.ungrab()
            self.captured = False
        self.repeated = None

    def close(self):
        try: self.ungrab()
        finally: self.device.close()


def guid_identity(value):
    """Linux SDL GUID hardware fields, ignoring name CRC and driver markers."""
    try:
        raw = bytes.fromhex(value)
        if len(raw) != 16: return None
        return tuple(int.from_bytes(raw[offset:offset+2], 'little') for offset in (0, 4, 8, 12))
    except (TypeError, ValueError):
        return None


def controllers(paths=None):
    import evdev
    paths = paths or [Path('/userdata/system/configs/emulationstation/es_input.cfg'),
                      Path('/usr/share/emulationstation/es_input.cfg')]
    configs, seen = [], set()
    for path in paths:
        if path.exists():
            for config in ET.parse(path).getroot().findall('inputConfig'):
                if config.get('type') == 'joystick':
                    identity = (config.get('deviceGUID'), config.get('deviceName'))
                    if identity not in seen:
                        configs.append(config)
                        seen.add(identity)
    result = []
    for path in evdev.list_devices():
        device = evdev.InputDevice(path)
        try:
            caps = device.capabilities(absinfo=False)
            if not any(0x120 <= key < 0x140 for key in caps.get(evdev.ecodes.EV_KEY, [])):
                device.close(); continue
            hardware = tuple(getattr(device.info, key) for key in ('bustype', 'vendor', 'product', 'version'))
            # SDL can name a DualSense differently from the kernel. Match its
            # recorded hardware GUID as well; all event codes are checked below.
            config = next((item for item in configs if item.get('deviceName') == device.name
                           or guid_identity(item.get('deviceGUID')) == hardware), None)
            if config is None:
                device.close(); continue
            mapping = bindings(config, hat_axes=caps.get(evdev.ecodes.EV_ABS, []))
            keys = caps.get(evdev.ecodes.EV_KEY, [])
            if any(code not in keys for kind, code, _ in mapping.values() if kind == 'button'):
                raise ValueError('Recorded button code does not match physical device')
            axes = caps.get(evdev.ecodes.EV_ABS, [])
            if any(code not in axes for kind, code, _ in mapping.values() if kind == 'axis'):
                raise ValueError('Recorded axis code does not match physical device')
            from antimicrox_hotkey import logical_hotkey
            controller = Controller(device, mapping, evdev.ecodes)
            controller.amx_hotkey = logical_hotkey(config)
            result.append(controller)
        except (ValueError, OSError) as exc:
            print(f'virtual_keyboard_controller_skipped name={device.name!r} reason={exc}', flush=True)
            device.close()
    return result


class KeySender:
    """Resolve characters against the desktop XKB map, then send Linux keys.

    The overlay never takes keyboard focus. Its uinput keyboard sends to the
    already-focused game, so there is no Alt+Tab or clipboard dependency.
    """
    def __init__(self):
        import evdev
        self.e = evdev.ecodes
        self.x = C.CDLL(ctypes.util.find_library('X11') or 'libX11.so.6')
        self.x.XOpenDisplay.argtypes = [C.c_char_p]; self.x.XOpenDisplay.restype = C.c_void_p
        self.x.XkbKeycodeToKeysym.argtypes = [C.c_void_p, C.c_ubyte, C.c_int, C.c_int]
        self.x.XkbKeycodeToKeysym.restype = C.c_ulong
        self.x.XCloseDisplay.argtypes = [C.c_void_p]
        self.display = self.x.XOpenDisplay(os.environ.get('DISPLAY', ':0').encode())
        if not self.display: raise RuntimeError('Desktop XKB map unavailable')
        self.characters = {}
        for level, mods in [(0, ()), (1, (42,)), (2, (100,)), (3, (42, 100))]:
            for code in range(8, 256):
                symbol = self.x.XkbKeycodeToKeysym(self.display, code, 0, level)
                if 0x20 <= symbol <= 0xff:
                    self.characters.setdefault(chr(symbol), (code-8, mods))
                elif symbol & 0xff000000 == 0x01000000:
                    self.characters.setdefault(chr(symbol & 0xffffff), (code-8, mods))
        try:
            self.ui = evdev.UInput({self.e.EV_KEY: list(range(1, 256))}, name='UWT Virtual Keyboard')
        except BaseException:
            self.x.XCloseDisplay(self.display)
            raise

    def send(self, action):
        special = {'backspace': 14, 'space': 57, 'enter': 28, 'delete': 111,
                   'cursor_left': 105, 'cursor_right': 106, 'cursor_up': 103,
                   'cursor_down': 108, 'home': 102, 'end': 107}
        if action in special: key, mods = special[action], ()
        elif action in self.characters: key, mods = self.characters[action]
        else: raise ValueError('Character unavailable in the current desktop keyboard layout')
        pressed = []
        try:
            for code in (*mods, key):
                self.ui.write(self.e.EV_KEY, code, 1); self.ui.syn(); pressed.append(code)
            # Allow Wine's polled keyboard path to observe a complete key press.
            time.sleep(.025)
        finally:
            for code in reversed(pressed): self.ui.write(self.e.EV_KEY, code, 0)
            self.ui.syn()

    def close(self):
        self.ui.close()
        self.x.XCloseDisplay(self.display)


def gtk_dependencies():
    os.environ.setdefault('DISPLAY', ':0')
    if 'XAUTHORITY' not in os.environ and Path('/var/lib/.Xauthority').is_file():
        os.environ['XAUTHORITY'] = '/var/lib/.Xauthority'
    os.environ.setdefault('NO_AT_BRIDGE', '1')
    os.environ['GDK_BACKEND'] = 'wayland' if os.environ.get('WAYLAND_DISPLAY') else 'x11'
    import gi
    gi.require_version('Gtk', '3.0'); gi.require_version('Gdk', '3.0')
    from gi.repository import Gtk, Gdk, GLib
    if not Gtk.init_check()[0]: raise RuntimeError('GTK display unavailable')
    layer = None
    if os.environ.get('WAYLAND_DISPLAY'):
        gi.require_version('GtkLayerShell', '0.1')
        from gi.repository import GtkLayerShell
        if not GtkLayerShell.is_supported():
            raise RuntimeError('Non-focus-stealing Wayland layer unavailable')
        layer = GtkLayerShell
    return Gtk, Gdk, GLib, layer


class Overlay:
    def __init__(self, dependencies, action, french=True):
        self.Gtk, self.Gdk, self.GLib, layer = dependencies
        Gtk, Gdk = self.Gtk, self.Gdk
        self.model, self.action = KeyboardModel(french), action
        self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL if layer else Gtk.WindowType.POPUP)
        self.window.set_title('UWT Virtual Keyboard')
        self.window.set_decorated(False)
        self.window.set_accept_focus(False); self.window.set_focus_on_map(False)
        self.window.set_skip_taskbar_hint(True); self.window.set_skip_pager_hint(True)
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        if layer:
            layer.init_for_window(self.window)
            layer.set_namespace(self.window, 'uwt-virtual-keyboard')
            layer.set_layer(self.window, layer.Layer.OVERLAY)
            layer.set_keyboard_mode(self.window, layer.KeyboardMode.NONE)
            layer.set_exclusive_zone(self.window, 0)
            layer.set_anchor(self.window, layer.Edge.BOTTOM, True)
            layer.set_margin(self.window, layer.Edge.BOTTOM, 16)
            if monitor: layer.set_monitor(self.window, monitor)
        else:
            self.window.set_type_hint(Gdk.WindowTypeHint.NOTIFICATION)
            self.window.set_keep_above(True)
        bounds = monitor.get_geometry() if monitor else None
        width = min(1040, max(420, bounds.width-40)) if bounds else 960
        height = min(440, max(280, int(bounds.height*.42))) if bounds else 400
        self.window.set_size_request(width, height)
        if not layer and bounds:
            self.window.move(bounds.x+(bounds.width-width)//2, bounds.y+bounds.height-height-16)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for side in ('top', 'bottom', 'start', 'end'): getattr(box, 'set_margin_'+side)(12)
        self.window.add(box)
        title = ('Clavier — Hotkey + Select : afficher / masquer' if french else
                 'Keyboard — Hotkey + Select: show / hide')
        box.pack_start(Gtk.Label(label=title), False, False, 0)
        self.grid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.pack_start(self.grid, True, True, 0)
        legend = ('Croix/bas : saisir · Rond/droite : fermer · Carré/gauche : effacer · Triangle/haut : espace\nL1 : majuscules · R1 : chiffres · Start : Entrée · Hotkey + Start : quitter le jeu' if french else
                  'South: type · East: close · West: backspace · North: space\nL1: shift · R1: numbers · Start: Enter · Hotkey + Start: quit game')
        self.message = Gtk.Label(label=legend); self.message.set_line_wrap(True)
        box.pack_start(self.message, False, False, 0)
        css = Gtk.CssProvider()
        css.load_from_data(b'window { background-color: #182230; } label { color: #edf4ff; font-size: 14pt; } button { background-image: none; background-color: #304158; color: white; border: 1px solid #59708e; border-radius: 8px; font-size: 19pt; } button.selected { background-color: #148082; border: 3px solid #a7f4e7; }')
        Gtk.StyleContext.add_provider_for_screen(self.window.get_screen(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.labels = {'shift': '⇧', 'symbols': 'ABC / 123', 'backspace': '⌫',
                       'cursor_left': '←', 'cursor_right': '→', 'cursor_up': '↑', 'cursor_down': '↓',
                       'home': 'Début' if french else 'Home', 'end': 'Fin' if french else 'End',
                       'delete': 'Suppr' if french else 'Delete',
                       'space': 'Espace' if french else 'Space', 'enter': 'Entrée' if french else 'Enter',
                       'close': 'Fermer' if french else 'Close'}
        self.render()

    def render(self):
        for child in self.grid.get_children(): self.grid.remove(child)
        for row, keys in enumerate(self.model.rows()):
            line = self.Gtk.Box(orientation=self.Gtk.Orientation.HORIZONTAL, spacing=6)
            line.set_homogeneous(True)
            self.grid.pack_start(line, True, True, 0)
            for col, key in enumerate(keys):
                button = self.Gtk.Button(label=self.labels.get(key, key))
                button.set_can_focus(False)
                button.connect('clicked', lambda _, action=key: self.action(action))
                if (row, col) == (self.model.row, self.model.col):
                    button.get_style_context().add_class('selected')
                line.pack_start(button, True, True, 0)
        self.grid.show_all()

    def visible(self): return self.window.get_visible()
    def show(self): self.window.show_all()
    def hide(self): self.window.hide()
    def close(self): self.window.destroy()


def language(home):
    try: return (Path(home)/'config/language').read_text().strip() == 'fr'
    except OSError: return os.environ.get('LANG', '').startswith('fr')


def running_game():
    try:
        with urllib.request.urlopen('http://127.0.0.1:1234/runningGame', timeout=.35) as response:
            data = json.loads(response.read(1024*1024))
            return data.get('path', '') if isinstance(data, dict) else ''
    except (OSError, ValueError): return None


def diagnose(home):
    import importlib.util
    for name in ('gi', 'evdev'):
        print(f'{name}={"available" if importlib.util.find_spec(name) else "MISSING"}')
    print(f'uinput={"writable" if os.access("/dev/uinput", os.W_OK) else "MISSING / not writable"}')
    print(f'wayland={os.environ.get("WAYLAND_DISPLAY", "no")} DISPLAY={os.environ.get("DISPLAY", ":0")}')
    deps = gtk_dependencies()
    print(f'nonfocus_overlay={"Wayland layer" if deps[3] else "X11 popup"}')
    devices = controllers()
    try:
        for device in devices: print(f'controller={device.device.name} shortcut=Hotkey+Select')
        if not devices: raise RuntimeError('No supported controller: check es_input.cfg Linux code attributes')
        sender = KeySender(); sender.close()
        print('keymap/uinput=ready; no keys sent')
    finally:
        for device in devices: device.close()


def preview(home):
    deps = gtk_dependencies()
    overlay = None
    def action(key):
        if key == 'close': deps[0].main_quit()
        elif key in ('shift', 'symbols'):
            overlay.model.activate(key); overlay.render()
    overlay = Overlay(deps, action, language(home))
    overlay.show()
    deps[2].timeout_add_seconds(10, lambda: (deps[0].main_quit(), False)[1])
    deps[0].main()
    overlay.close()


def run(home, rom):
    import fcntl
    from virtual_keyboard import conflict, lifecycle_lock
    from virtual_keyboard_antimicrox import INDICES, priority
    home = Path(home)
    state = home/'state/virtual-keyboard'; state.mkdir(parents=True, exist_ok=True)
    with (state/'runtime.lock').open('a') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return
        token = process_identity(os.getpid())
        session = state/'session.json'
        with lifecycle_lock(home):
            if not session.exists(): return
            owner = json.loads(session.read_text())
            if owner != {'rom': rom, 'pid': os.getpid(), 'token': token}: return
        if not Settings(home).enabled(rom): return
        deps = gtk_dependencies()
        Gtk, _, GLib, _ = deps
        devices, sender, overlay, windows = [], None, None, None
        try:
            devices = controllers()
            if not devices: raise RuntimeError('No configured controller with distinct Hotkey/Select and Linux codes')
            modifiers = sorted({INDICES[d.amx_hotkey] for d in devices
                                if getattr(d, 'amx_hotkey', None) in INDICES})
            sender = KeySender()
            from antimicrox_focus import XWindows
            windows = XWindows()
            def safe_foreground(): return windows.current(0)[0] == 'game'
            pending = None
            quiet_since = None
            def hide():
                overlay.hide()
                for device in devices: device.ungrab()
                try: priority(home, rom, False)
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                    print(f'virtual_keyboard_restore_error={exc}', flush=True)
            def action(key):
                nonlocal pending
                if key == 'close': pending = 'hide'; return
                if key in ('shift', 'symbols'):
                    overlay.model.activate(key); overlay.render(); return
                if not safe_foreground():
                    hide(); return
                try: sender.send(key)
                except ValueError as exc: overlay.message.set_text(str(exc))
                if key == 'enter': pending = 'hide'
            overlay = Overlay(deps, action, language(home))
            print(f'virtual_keyboard_ready rom={rom} shortcut=Hotkey+Select controllers={len(devices)}', flush=True)
            started, seen_game, last_poll, unknown_since = time.monotonic(), False, float('-inf'), None
            current_rom = None
            def tick():
                nonlocal pending, quiet_since, last_poll, current_rom, seen_game, unknown_since
                now = time.monotonic()
                try:
                    if now-last_poll >= 1:
                        current_rom = running_game(); last_poll = now
                        if current_rom == rom: seen_game = True; unknown_since = None
                        elif current_rom is None:
                            unknown_since = unknown_since or now
                            if overlay.visible(): hide()
                        elif seen_game or (current_rom and current_rom != rom and now-started > 10):
                            Gtk.main_quit(); return False
                        if (not seen_game and now-started > 120) or (unknown_since and now-unknown_since > 10):
                            Gtk.main_quit(); return False
                    if overlay.visible() and (current_rom != rom or not safe_foreground()): hide()
                    for device in devices:
                        for key in device.poll():
                            if key == 'exit' and overlay.visible():
                                hide()
                                command = ['hotkeygen', '--send', 'exit'] if __import__('shutil').which('hotkeygen') else ['batocera-wine', 'windows', 'stop']
                                subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
                                Gtk.main_quit(); return False
                            if key == 'toggle' and current_rom == rom:
                                if overlay.visible():
                                    pending = 'hide'
                                elif safe_foreground():
                                    priority(home, rom, True)
                                    pending = 'show'
                                quiet_since = None
                            elif overlay.visible() and pending is None:
                                if key in ('up', 'down', 'left', 'right'):
                                    overlay.model.move(key); overlay.render()
                                elif key in {'b', 'a', 'x', 'y', 'start', 'pageup', 'pagedown'}:
                                    action({'b': overlay.model.selected(), 'a': 'close', 'x': 'space',
                                            'y': 'backspace', 'start': 'enter', 'pageup': 'shift', 'pagedown': 'symbols'}[key])
                    if pending:
                        if all(device.released() for device in devices):
                            quiet_since = quiet_since or now
                            if now-quiet_since >= .12:
                                if pending == 'hide': hide()
                                elif current_rom == rom and safe_foreground():
                                    problem = conflict(home, rom, modifiers=modifiers)
                                    if problem: raise RuntimeError(problem)
                                    for device in devices: device.grab()
                                    overlay.show()
                                    print('virtual_keyboard_shown', flush=True)
                                else:
                                    priority(home, rom, False)
                                    print('virtual_keyboard_refused=No active Wine X11/XWayland window', flush=True)
                                pending, quiet_since = None, None
                        else: quiet_since = None
                    return True
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                    print(f'virtual_keyboard_runtime_error={exc}', flush=True)
                    hide(); Gtk.main_quit(); return False
            GLib.timeout_add(25, tick)
            for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
                GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: (Gtk.main_quit(), False)[1])
            Gtk.main()
        finally:
            if overlay: overlay.close()
            try: priority(home, rom, False)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                print(f'virtual_keyboard_restore_error={exc}', flush=True)
            for device in devices: device.close()
            if sender: sender.close()
            if windows: windows.close()
            if session.exists():
                data = json.loads(session.read_text())
                if data.get('token') == token and data.get('pid') == os.getpid(): session.unlink()
            print('virtual_keyboard_stopped controllers_released=1', flush=True)
