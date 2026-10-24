"""Refresh Wine focus after returning from the managed live profile editor."""
import argparse
import ctypes as C
import ctypes.util
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from antimicrox_handoff import EsApi


def switch_log(message):
    print(f'[{datetime.now().astimezone().isoformat(timespec="milliseconds")}] '
          f'AntiMicroX live direct switch {message}', flush=True)


def process_start(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(') ', 1)[1].split()
        return fields[19] if fields[0] != 'Z' else ''
    except (OSError, IndexError):
        return ''


class Owner:
    def __init__(self, home, rom, pid, stamp):
        self.home, self.rom, self.pid, self.stamp = Path(home), rom, pid, stamp
        self.session_id = self.read().get('session_id')

    def read(self):
        try:
            data = json.loads((self.home/'state/antimicrox-live.json').read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def active(self):
        data = self.read()
        try:
            owned = (self.home/'state/antimicrox/session').read_text().strip().split('\t')
        except OSError:
            return False
        return (data.get('rom') == self.rom and data.get('session_id') == self.session_id
                and data.get('phase') == 'running'
                and owned == [self.rom, str(self.pid), self.stamp]
                and process_start(self.pid) == self.stamp)

    def user_switched(self):
        """A pending or completed explicit switch takes priority over startup."""
        try:
            with (self.home/'state/antimicrox/toggle.lock').open() as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
                except BlockingIOError:
                    return True
                return lock.read().split('\t', 1)[0] == self.session_id
        except OSError:
            return False


class XWindows:
    """Observe XWayland windows and request initial activation through the WM."""
    def __init__(self):
        self.x = C.CDLL(ctypes.util.find_library('X11') or 'libX11.so.6')
        self.x.XOpenDisplay.argtypes = [C.c_char_p]
        self.x.XOpenDisplay.restype = C.c_void_p
        self.x.XDefaultRootWindow.argtypes = [C.c_void_p]
        self.x.XDefaultRootWindow.restype = C.c_ulong
        self.x.XInternAtom.argtypes = [C.c_void_p, C.c_char_p, C.c_int]
        self.x.XInternAtom.restype = C.c_ulong
        self.x.XGetWindowProperty.argtypes = [C.c_void_p, C.c_ulong, C.c_ulong,
            C.c_long, C.c_long, C.c_int, C.c_ulong, C.POINTER(C.c_ulong),
            C.POINTER(C.c_int), C.POINTER(C.c_ulong), C.POINTER(C.c_ulong),
            C.POINTER(C.c_void_p)]
        self.x.XFree.argtypes = [C.c_void_p]
        self.x.XCloseDisplay.argtypes = [C.c_void_p]
        self.x.XSendEvent.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.c_long, C.c_void_p]
        self.x.XFlush.argtypes = [C.c_void_p]
        # Windows may disappear between activation and PID lookup.
        self.error = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_void_p)(lambda *_: 0)
        self.x.XSetErrorHandler.argtypes = [C.c_void_p]
        self.x.XSetErrorHandler(self.error)
        self.display = self.x.XOpenDisplay(os.environ.get('DISPLAY', ':0').encode())
        if not self.display:
            raise RuntimeError('Cannot observe XWayland activation')
        self.root = self.x.XDefaultRootWindow(self.display)
        self.atoms = {name: self.x.XInternAtom(self.display, name.encode(), 0)
                      for name in ('_NET_ACTIVE_WINDOW', '_NET_WM_PID', '_NET_CLIENT_LIST_STACKING')}
        self.kinds = {}

    def cardinals(self, window, name, limit=1):
        actual, count, remaining = C.c_ulong(), C.c_ulong(), C.c_ulong()
        fmt, data = C.c_int(), C.c_void_p()
        try:
            status = self.x.XGetWindowProperty(self.display, window, self.atoms[name],
                0, limit, 0, 0, C.byref(actual), C.byref(fmt), C.byref(count),
                C.byref(remaining), C.byref(data))
            if status == 0 and fmt.value == 32 and count.value and data.value:
                return list(C.cast(data, C.POINTER(C.c_ulong))[:count.value])
            return []
        finally:
            if data.value:
                self.x.XFree(data)

    def cardinal(self, window, name):
        return next(iter(self.cardinals(window, name)), 0)

    def current(self, editor_pid):
        window = self.cardinal(self.root, '_NET_ACTIVE_WINDOW')
        if not window:
            return 'unknown', 0
        return self.kind(window, editor_pid), window

    def kind(self, window, editor_pid):
        pid = self.cardinal(window, '_NET_WM_PID')
        if pid == editor_pid:
            return 'editor'
        identity = (pid, process_start(pid))
        if identity in self.kinds:
            return self.kinds[identity]
        kind = 'other'
        try:
            maps = Path(f'/proc/{pid}/maps').read_text()
            if 'winex11.drv' in maps:
                kind = 'game'
        except OSError:
            pass
        if len(self.kinds) >= 128:
            self.kinds.clear()
        self.kinds[identity] = kind
        return kind

    def client_windows(self):
        return self.cardinals(self.root, '_NET_CLIENT_LIST_STACKING', 4096)

    def game_window(self, editor_pid):
        for window in reversed(self.client_windows()):
            if self.kind(window, editor_pid) == 'game':
                return window
        return 0

    def editor_window(self, editor_pid):
        for window in reversed(self.client_windows()):
            if self.cardinal(window, '_NET_WM_PID') == editor_pid:
                return window
        return 0

    def activate(self, window):
        # EWMH client message: ask labwc/X11 WM, without injecting Alt+Tab/keys.
        class Message(C.Structure):
            _fields_ = [('type', C.c_int), ('serial', C.c_ulong), ('send_event', C.c_int),
                        ('display', C.c_void_p), ('window', C.c_ulong),
                        ('message_type', C.c_ulong), ('format', C.c_int), ('data', C.c_long*5)]
        class Event(C.Union):
            _fields_ = [('message', Message), ('pad', C.c_long*24)]
        event = Event()
        event.message = Message(33, 0, 1, self.display, window,
                                self.atoms['_NET_ACTIVE_WINDOW'], 32, (C.c_long*5)(2, 0, 0, 0, 0))
        self.x.XSendEvent(self.display, self.root, 0, (1 << 20) | (1 << 19), C.byref(event))
        self.x.XFlush(self.display)

    def close(self):
        self.x.XCloseDisplay(self.display)


class Returns:
    def __init__(self):
        self.armed = False
        self.candidate = None
        self.since = 0

    def observe(self, current, now):
        kind, window = current
        if kind == 'editor':
            self.armed = True
            self.candidate = None
        elif kind == 'game' and self.armed:
            if self.candidate != window:
                self.candidate, self.since = window, now
            elif now-self.since >= .25:
                self.armed = False
                self.candidate = None
                return window
        else:
            self.candidate = None
            if kind != 'unknown':
                self.armed = False
        return None


def toggle_window(owner, windows, api=None):
    """Switch only within the active live session, without synthetic Alt+Tab."""
    def skipped(reason):
        switch_log(f'skipped: {reason}')
        return False

    if not owner.active():
        return skipped('session inactive')
    current = windows.current(owner.pid)
    fallback = False
    if current[0] == 'editor':
        target = windows.game_window(owner.pid)
    elif current[0] == 'game':
        target = windows.editor_window(owner.pid)
    else:
        # labwc may leave _NET_ACTIVE_WINDOW pointing at an unlisted window
        # while the game is visible. Recover only when a Wine game window is
        # still listed; keep refusing a real unrelated managed application.
        if current[1] in windows.client_windows() or not windows.game_window(owner.pid):
            return skipped(f'unrelated or unavailable foreground {current}')
        fallback = True
        target = windows.editor_window(owner.pid)
    if not target:
        return skipped('target window missing')
    running = (api or EsApi()).running()
    if running != (200, owner.rom):
        return skipped(f'ES no longer runs this game: {running}')
    if not owner.active() or windows.current(owner.pid) != current:
        return skipped('session or foreground changed during switch')
    if fallback and (current[1] in windows.client_windows() or not windows.game_window(owner.pid)):
        return skipped('foreground became managed or game window disappeared')
    windows.activate(target)
    switch_log(f'from={current[0]} source={current[1]} target={target}')
    return True


class ControllerKeys:
    """Only EVIOCGKEY: no device-name queries, event reads, or exclusive grabs."""
    def __init__(self, path):
        self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)

    def active_keys(self):
        keys = bytearray(96)  # Linux KEY_MAX = 0x2ff, including Guide buttons.
        request = (2 << 30) | (len(keys) << 16) | (ord('E') << 8) | 0x18
        fcntl.ioctl(self.fd, request, keys, True)
        return [index*8+bit for index, value in enumerate(keys)
                for bit in range(8) if value & (1 << bit)]

    def close(self):
        os.close(self.fd)


def controller_devices(sysroot=Path('/sys/class/input'), factory=ControllerKeys):
    """Filter sysfs key bitmaps before opening only joystick/gamepad devices."""
    opened = []
    word_bits = C.sizeof(C.c_ulong)*8
    try:
        for event in sorted(sysroot.glob('event*')):
            try:
                words = (event/'device/capabilities/key').read_text().split()
            except FileNotFoundError:
                continue  # Hot unplug during discovery.
            mask = sum(int(word, 16) << (word_bits*index)
                       for index, word in enumerate(reversed(words)))
            if any(mask & (1 << key) for key in range(0x120, 0x140)):
                opened.append(factory('/dev/input/'+event.name))
        return opened
    except BaseException:
        for device in opened:
            device.close()
        raise


def wait_controller_release(valid, devices=None, clock=time.monotonic, sleep=time.sleep, timeout=10):
    """Read controller key state without grabbing devices or injecting events.

    Experimental: wait for all controller buttons, including Guide/Hotkey,
    then leave 120 ms for AntiMicroX to process its own release events.
    """
    opened = []
    started = clock()
    quiet = None
    try:
        if devices is None:
            opened = controller_devices()
            devices = opened
        if not devices:
            switch_log('release wait cancelled: no controller can be observed')
            return False
        switch_log(f'waiting for controller release devices={len(devices)} discovery={clock()-started:.3f}s')
        while clock()-started < timeout:
            if not valid():
                switch_log('release wait cancelled: session or foreground changed')
                return False
            pressed = [key for device in devices for key in device.active_keys()]
            now = clock()
            if pressed:
                quiet = None
            elif quiet is None:
                quiet = now
            elif now-quiet >= .12:
                switch_log(f'controller release confirmed after {now-started:.3f}s')
                return True
            sleep(.02)
        switch_log('release wait cancelled: buttons still held after 10 seconds')
        return False
    except (OSError, ValueError) as exc:
        switch_log(f'release wait cancelled: {exc}')
        return False
    finally:
        for device in opened:
            device.close()


def toggle(home, session_id):
    home = Path(home)
    # Serialize controller duplicates and refuse stale shortcuts from an older
    # session, including after its ROM is launched again.
    with (home/'state/antimicrox/toggle.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        data = json.loads((home/'state/antimicrox-live.json').read_text())
        if data.get('session_id') != session_id:
            return False
        rom, pid, stamp = (home/'state/antimicrox/session').read_text().strip().split('\t')
        owner = Owner(home, rom, int(pid), stamp)
        if owner.session_id != session_id or not owner.active():
            return False
        now = time.monotonic()
        lock.seek(0)
        previous = lock.read().strip().split('\t')
        if len(previous) == 2 and previous[0] == session_id and now-float(previous[1]) < .4:
            switch_log('skipped: duplicate request within 400 ms')
            return False
        os.environ.setdefault('DISPLAY', ':0')
        os.environ.setdefault('XAUTHORITY', '/var/lib/.Xauthority')
        windows = XWindows()
        try:
            if (home/'state/antimicrox-wait-release.enabled').exists():
                initial = windows.current(owner.pid)
                if not wait_controller_release(lambda: owner.active() and windows.current(owner.pid) == initial):
                    return False
            switched = toggle_window(owner, windows)
            if switched:
                lock.seek(0)
                lock.truncate()
                lock.write(f'{session_id}\t{time.monotonic()}\n')
                lock.flush()
            return switched
        finally:
            windows.close()


def introduction(owner, windows, api, clock=time.monotonic, sleep=time.sleep,
                 run=subprocess.run, timeout=120):
    """Give the game initial focus once; later user switches remain untouched."""
    deadline = clock()+timeout
    candidate, since, requested = 0, 0, False
    while owner.active() and clock() < deadline:
        if owner.user_switched():
            print('AntiMicroX live introduction cancelled: manual switch takes priority', flush=True)
            return
        kind, current = windows.current(owner.pid)
        target = current if kind == 'game' else windows.game_window(owner.pid)
        if target != candidate:
            candidate, since = target, clock()
        if candidate and clock()-since >= 1 and kind in ('editor', 'game'):
            if api.running() == (200, owner.rom) and owner.active() and not owner.user_switched():
                # Recheck after the HTTP call; never raise over another app.
                observed = windows.current(owner.pid)
                if observed[0] == 'editor' and not requested:
                    windows.activate(candidate)
                    requested = True
                    deadline = min(deadline, clock()+5)
                elif observed == ('game', candidate):
                    try:
                        language = (owner.home/'config/language').read_text().strip()
                    except OSError:
                        language = 'fr' if os.environ.get('LANG', '').startswith('fr') else 'en'
                    shortcut = owner.read().get('switch_fr' if language == 'fr' else 'switch_en', 'Alt+Tab')
                    message = (f'Configurer avec AntiMicroX : {shortcut}'
                               '\nRelâchez les boutons après la bascule. Enregistrez le profil avant de quitter.'
                               if language == 'fr' else
                               f'Configure with AntiMicroX: {shortcut}'
                               '\nRelease the buttons after switching. Save the profile before quitting.')
                    try:
                        result = run([sys.executable, str(Path(__file__).with_name('antimicrox_notice.py')), message],
                                     timeout=9, check=False, stdin=subprocess.DEVNULL)
                        print(f'AntiMicroX live passive introduction exit={result.returncode}', flush=True)
                    except (OSError, subprocess.TimeoutExpired) as exc:
                        print(f'AntiMicroX live introduction failed: {exc}', flush=True)
                    return
        sleep(.1)
    print('AntiMicroX live introduction skipped: game focus unavailable or session ended', flush=True)


def watch(owner, windows, api=None, clock=time.monotonic, sleep=time.sleep,
          run=subprocess.run, show_intro=True):
    api, returns = api or EsApi(), Returns()
    if show_intro:
        introduction(owner, windows, api, clock, sleep, run)
    data = owner.read()
    action = data.get('action') if isinstance(data, dict) else None
    if isinstance(action, dict) and action.get('type') == 'exec':
        # The direct shortcut already requests activation from the compositor.
        # Opening a flash window after each return creates another focus change
        # and can hand focus back to the editor. Keep this legacy workaround
        # only for older sessions that still synthesize Alt+Tab.
        print('AntiMicroX live direct mode: automatic focus refresh disabled', flush=True)
        return
    while owner.active():
        target = returns.observe(windows.current(owner.pid), clock())
        if target:
            # Confirm ES still runs this ROM, then recheck focus after its API call.
            if (api.running() == (200, owner.rom) and owner.active()
                    and windows.current(owner.pid) == ('game', target)):
                try:
                    result = run(['batocera-flash-screen', '0.3', 'white', 'Retour au jeu', '12'],
                                 timeout=3, check=False, stdin=subprocess.DEVNULL)
                    print(f'AntiMicroX live focus refresh window={target} exit={result.returncode}', flush=True)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    print(f'AntiMicroX live focus refresh failed: {exc}', flush=True)
        sleep(.1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('spawn', 'run', 'toggle'))
    parser.add_argument('rom', nargs='?')
    parser.add_argument('pid', nargs='?', type=int)
    parser.add_argument('stamp', nargs='?')
    parser.add_argument('--home', default=os.environ.get('WT_HOME', '/userdata/system/ultimate-wine-toolbox'))
    parser.add_argument('--session-id')
    args = parser.parse_args()
    if args.mode == 'toggle':
        if not args.session_id:
            parser.error('toggle requires --session-id')
        try:
            toggle(args.home, args.session_id)
        except (OSError, ValueError, RuntimeError) as exc:
            print(f'AntiMicroX live direct switch unavailable: {exc}', flush=True)
        return
    if args.rom is None or args.pid is None or args.stamp is None:
        parser.error('spawn/run require rom, pid and stamp')
    if args.mode == 'spawn':
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'run',
                          args.rom, str(args.pid), args.stamp, '--home', args.home],
                         start_new_session=True, close_fds=True, stdin=subprocess.DEVNULL)
        return
    os.environ.setdefault('DISPLAY', ':0')
    os.environ.setdefault('XAUTHORITY', '/var/lib/.Xauthority')
    lockpath = Path(args.home)/'state/antimicrox/focus.lock'
    with lockpath.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        windows = None
        try:
            owner = Owner(args.home, args.rom, args.pid, args.stamp)
            if not owner.active():
                return
            windows = XWindows()
            print('AntiMicroX live XWayland focus observer started', flush=True)
            watch(owner, windows)
        except (OSError, RuntimeError) as exc:
            print(f'AntiMicroX live focus observer unavailable: {exc}', flush=True)
        finally:
            if windows:
                windows.close()


if __name__ == '__main__':
    main()
