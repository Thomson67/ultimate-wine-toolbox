"""X11/XWayland live-session trace; optional, explicit WM_TAKE_FOCUS probe."""
import argparse
import ctypes as C
from datetime import datetime
import json
import os
from pathlib import Path
import time

from antimicrox_focus import Owner, XWindows
from antimicrox_handoff import EsApi

HEAD = [('type', C.c_int), ('serial', C.c_ulong), ('send_event', C.c_int),
        ('display', C.c_void_p)]


class FocusEvent(C.Structure):
    _fields_ = HEAD + [('window', C.c_ulong), ('mode', C.c_int), ('detail', C.c_int)]


class PropertyEvent(C.Structure):
    _fields_ = HEAD + [('window', C.c_ulong), ('atom', C.c_ulong),
                      ('time', C.c_ulong), ('state', C.c_int)]


class StructureEvent(C.Structure):
    _fields_ = HEAD + [('event', C.c_ulong), ('window', C.c_ulong)]


class ConfigureEvent(C.Structure):
    _fields_ = StructureEvent._fields_ + [('x', C.c_int), ('y', C.c_int),
        ('width', C.c_int), ('height', C.c_int), ('border_width', C.c_int),
        ('above', C.c_ulong), ('override_redirect', C.c_int)]


class ClientMessageEvent(C.Structure):
    _fields_ = HEAD + [('window', C.c_ulong), ('message_type', C.c_ulong),
                      ('format', C.c_int), ('data', C.c_long*5)]


class Event(C.Union):
    _fields_ = [('type', C.c_int), ('focus', FocusEvent), ('property', PropertyEvent),
                ('structure', StructureEvent), ('configure', ConfigureEvent),
                ('message', ClientMessageEvent),
                ('pad', C.c_long*24)]


class TraceWindows(XWindows):
    def __init__(self):
        super().__init__()
        self.x.XSelectInput.argtypes = [C.c_void_p, C.c_ulong, C.c_long]
        self.x.XPending.argtypes = [C.c_void_p]
        self.x.XNextEvent.argtypes = [C.c_void_p, C.POINTER(Event)]
        self.x.XGetInputFocus.argtypes = [C.c_void_p, C.POINTER(C.c_ulong), C.POINTER(C.c_int)]
        self.x.XGetGeometry.argtypes = [C.c_void_p, C.c_ulong, C.POINTER(C.c_ulong),
            C.POINTER(C.c_int), C.POINTER(C.c_int), C.POINTER(C.c_uint),
            C.POINTER(C.c_uint), C.POINTER(C.c_uint), C.POINTER(C.c_uint)]
        self.x.XGetAtomName.argtypes = [C.c_void_p, C.c_ulong]
        self.x.XGetAtomName.restype = C.c_void_p
        self.x.XFetchName.argtypes = [C.c_void_p, C.c_ulong, C.POINTER(C.c_void_p)]
        self.x.XStringToKeysym.argtypes = [C.c_char_p]
        self.x.XStringToKeysym.restype = C.c_ulong
        self.x.XKeysymToKeycode.argtypes = [C.c_void_p, C.c_ulong]
        self.x.XKeysymToKeycode.restype = C.c_ubyte
        self.x.XQueryKeymap.argtypes = [C.c_void_p, C.c_void_p]
        for name in ('_NET_WM_STATE', '_NET_WM_WINDOW_TYPE', 'WM_STATE', 'WM_HINTS',
                     'WM_PROTOCOLS', 'WM_TRANSIENT_FOR'):
            self.atoms[name] = self.x.XInternAtom(self.display, name.encode(), 0)
        self.watched = {'E': self.x.XKeysymToKeycode(self.display, self.x.XStringToKeysym(b'e')),
                        'Escape': self.x.XKeysymToKeycode(self.display, self.x.XStringToKeysym(b'Escape'))}
        self.subscribed = set()
        # Select notifications only. No grabs, focus requests or key injection.
        self.x.XSelectInput(self.display, self.root, (1 << 19) | (1 << 22))

    def atom_name(self, atom):
        value = self.x.XGetAtomName(self.display, atom) if atom else None
        if not value:
            return str(atom)
        try:
            return C.string_at(value).decode(errors='replace')
        finally:
            self.x.XFree(value)

    def server_time(self):
        """Obtain an actual X timestamp from an unmapped scratch window."""
        self.x.XCreateSimpleWindow.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.c_int,
                                              C.c_uint, C.c_uint, C.c_uint, C.c_ulong, C.c_ulong]
        self.x.XCreateSimpleWindow.restype = C.c_ulong
        self.x.XChangeProperty.argtypes = [C.c_void_p, C.c_ulong, C.c_ulong, C.c_ulong,
                                           C.c_int, C.c_int, C.c_void_p, C.c_int]
        self.x.XWindowEvent.argtypes = [C.c_void_p, C.c_ulong, C.c_long, C.POINTER(Event)]
        self.x.XDestroyWindow.argtypes = [C.c_void_p, C.c_ulong]
        window = self.x.XCreateSimpleWindow(self.display, self.root, 0, 0, 1, 1, 0, 0, 0)
        if not window:
            raise RuntimeError('Cannot obtain X11 server timestamp')
        try:
            self.x.XSelectInput(self.display, window, 1 << 22)
            atom = self.x.XInternAtom(self.display, b'_UWT_FOCUS_TIMESTAMP', 0)
            value = C.c_ubyte(1)
            self.x.XChangeProperty(self.display, window, atom, 19, 8, 0, C.byref(value), 1)
            event = Event()
            self.x.XWindowEvent(self.display, window, 1 << 22, C.byref(event))
            return event.property.time
        finally:
            self.x.XDestroyWindow(self.display, window)

    def offer_focus(self, window):
        """Explicit diagnostic probe: ask the client to take focus via ICCCM."""
        protocol = self.x.XInternAtom(self.display, b'WM_TAKE_FOCUS', 0)
        if protocol not in self.cardinals(window, 'WM_PROTOCOLS', 32):
            raise RuntimeError('The game does not advertise WM_TAKE_FOCUS')
        event = Event()
        event.message = ClientMessageEvent(33, 0, 1, self.display, window,
            self.atoms['WM_PROTOCOLS'], 32, (C.c_long*5)(protocol, self.server_time(), 0, 0, 0))
        sent = self.x.XSendEvent(self.display, window, 0, 0, C.byref(event))
        self.x.XFlush(self.display)
        return bool(sent)

    def title(self, window):
        value = C.c_void_p()
        self.x.XFetchName(self.display, window, C.byref(value))
        try:
            return C.string_at(value).decode(errors='replace') if value.value else ''
        finally:
            if value.value:
                self.x.XFree(value)

    def geometry(self, window):
        root = C.c_ulong(); x, y = C.c_int(), C.c_int()
        width, height, border, depth = (C.c_uint() for _ in range(4))
        if not self.x.XGetGeometry(self.display, window, C.byref(root), C.byref(x), C.byref(y),
                C.byref(width), C.byref(height), C.byref(border), C.byref(depth)):
            return None
        return [x.value, y.value, width.value, height.value]

    def snapshot(self, editor_pid):
        focus, revert = C.c_ulong(), C.c_int()
        self.x.XGetInputFocus(self.display, C.byref(focus), C.byref(revert))
        active = self.cardinal(self.root, '_NET_ACTIVE_WINDOW')
        clients = self.client_windows()
        for window in set(clients + [active, focus.value]) - self.subscribed:
            if window > 1:
                self.x.XSelectInput(self.display, window, (1 << 17) | (1 << 21) | (1 << 22))
                self.subscribed.add(window)
        windows = []
        for window in clients:
            hints = self.cardinals(window, 'WM_HINTS', 9)
            windows.append({'id': hex(window), 'pid': self.cardinal(window, '_NET_WM_PID'),
                'kind': self.kind(window, editor_pid), 'title': self.title(window),
                'geometry': self.geometry(window),
                'states': [self.atom_name(a) for a in self.cardinals(window, '_NET_WM_STATE', 64)],
                'types': [self.atom_name(a) for a in self.cardinals(window, '_NET_WM_WINDOW_TYPE', 16)],
                'protocols': [self.atom_name(a) for a in self.cardinals(window, 'WM_PROTOCOLS', 32)],
                'wm_state': self.cardinals(window, 'WM_STATE', 2),
                'transient_for': [hex(v) for v in self.cardinals(window, 'WM_TRANSIENT_FOR', 1)],
                'accepts_input': bool(hints[1]) if len(hints) > 1 and hints[0] & 1 else None})
        keys = (C.c_ubyte*32)()
        self.x.XQueryKeymap(self.display, keys)
        down = [name for name, code in self.watched.items() if code and keys[code//8] & (1 << (code % 8))]
        return {'active': hex(active), 'keyboard_focus': hex(focus.value),
                'watched_keys_down': down, 'windows': windows}

    def events(self, limit=500):
        result = []
        for _ in range(limit):
            if not self.x.XPending(self.display):
                break
            event = Event()
            self.x.XNextEvent(self.display, C.byref(event))
            kind = event.type
            if kind in (9, 10):
                modes = {0: 'normal', 1: 'grab', 2: 'ungrab', 3: 'while-grabbed'}
                result.append({'event': 'FocusIn' if kind == 9 else 'FocusOut',
                    'window': hex(event.focus.window), 'mode': modes.get(event.focus.mode, event.focus.mode),
                    'detail': event.focus.detail, 'synthetic': bool(event.focus.send_event)})
            elif kind == 28:
                name = self.atom_name(event.property.atom)
                if name in self.atoms:
                    result.append({'event': 'PropertyNotify', 'window': hex(event.property.window),
                                   'property': name, 'state': event.property.state})
            elif kind in (17, 18, 19, 22):
                window = event.structure.window
                if window not in self.subscribed:
                    continue
                names = {17: 'DestroyNotify', 18: 'UnmapNotify', 19: 'MapNotify', 22: 'ConfigureNotify'}
                item = {'event': names[kind], 'window': hex(window)}
                if kind == 22:
                    e = event.configure
                    item['geometry'] = [e.x, e.y, e.width, e.height]
                result.append(item)
                if kind == 17:
                    self.subscribed.discard(window)
        return result


class Recorder:
    def __init__(self, output, clock=time.monotonic):
        self.output, self.clock = output, clock
        self.start = clock()
        self.previous = None
        self.count = 0

    def write(self, kind, **fields):
        self.output.write(json.dumps({'time': datetime.now().astimezone().isoformat(timespec='milliseconds'),
            'elapsed': round(self.clock()-self.start, 4), 'kind': kind, **fields}, ensure_ascii=False)+'\n')
        self.output.flush()
        self.count += 1

    def snapshot(self, value):
        if value != self.previous:
            self.write('snapshot', **value)
            self.previous = value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path('/userdata/system/ultimate-wine-toolbox'))
    parser.add_argument('--seconds', type=int, default=45)
    parser.add_argument('--request-focus', action='store_true',
                        help='Explicitly send WM_TAKE_FOCUS to the already active game (diagnostic test)')
    args = parser.parse_args()
    if not 5 <= args.seconds <= 120:
        parser.error('--seconds must be between 5 and 120')
    rom, pid, stamp = (args.home/'state/antimicrox/session').read_text().strip().split('\t')
    owner = Owner(args.home, rom, int(pid), stamp)
    if not owner.active():
        raise RuntimeError('Start a live AntiMicroX editing session first')
    os.environ.setdefault('DISPLAY', ':0')
    os.environ.setdefault('XAUTHORITY', '/var/lib/.Xauthority')
    logdir = Path('/userdata/system/logs/ultimate-wine-toolbox')
    logdir.mkdir(parents=True, exist_ok=True)
    path = logdir/f'antimicrox-focus-trace-{datetime.now():%Y%m%d-%H%M%S}-{os.getpid()}.jsonl'
    windows, api = TraceWindows(), EsApi()
    source = logdir/'antimicrox.log'
    position = source.stat().st_size if source.exists() else 0
    print(f'Trace pendant {args.seconds} s : {path}', flush=True)
    if args.request_focus:
        print('Test du protocole de focus sur le jeu actif, sans injection de touches.', flush=True)
    else:
        print('Faire 2 ou 3 allers-retours Hotkey+R1. Si les touches bloquent, attendre 2 s puis appuyer sur E ou Échap.', flush=True)
    with path.open('x', encoding='utf-8') as output:
        os.chmod(path, 0o600)
        recorder = Recorder(output)
        recorder.write('start', rom=rom, editor_pid=int(pid), session_id=owner.session_id,
                       backend='X11/XWayland', watched_keys=['E', 'Escape'],
                       request_focus=args.request_focus)
        deadline, next_api = time.monotonic()+args.seconds, 0
        try:
            if args.request_focus:
                recorder.snapshot(windows.snapshot(owner.pid))
                kind, game = windows.current(owner.pid)
                if kind != 'game' or not owner.active() or api.running() != (200, rom):
                    raise RuntimeError('Focus probe requires this live game to be in the foreground')
                if windows.current(owner.pid) != ('game', game) or not owner.active():
                    raise RuntimeError('Foreground changed; focus probe cancelled')
                sent = windows.offer_focus(game)
                recorder.write('focus_probe', window=hex(game), sent=sent)
                print(f'WM_TAKE_FOCUS envoyé au jeu : {sent}. Tester les déplacements.', flush=True)
            while time.monotonic() < deadline and recorder.count < 10000:
                recorder.snapshot(windows.snapshot(owner.pid))
                for event in windows.events():
                    recorder.write('x11_event', **event)
                if time.monotonic() >= next_api:
                    recorder.write('es_state', running=api.running(), session_active=owner.active())
                    next_api = time.monotonic()+1
                    if source.exists():
                        if source.stat().st_size < position:
                            position = 0
                        with source.open('rb') as stream:
                            stream.seek(position)
                            for raw in stream:
                                line = raw.decode(errors='replace').strip()
                                if 'AntiMicroX live' in line:
                                    recorder.write('helper_log', message=line)
                            position = stream.tell()
                    if not owner.active():
                        break
                time.sleep(.02)
        except KeyboardInterrupt:
            recorder.write('interrupted')
        finally:
            recorder.write('end', records=recorder.count)
            windows.close()
    print(f'Trace terminée. Fichier à joindre : {path}', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc))
