"""Refresh Wine focus after returning from the managed live profile editor."""
import argparse
import ctypes as C
import ctypes.util
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from antimicrox_handoff import EsApi


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


class XWindows:
    """Observe XWayland activation without changing windows or sending keys."""
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
        # Windows may disappear between activation and PID lookup.
        self.error = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_void_p)(lambda *_: 0)
        self.x.XSetErrorHandler.argtypes = [C.c_void_p]
        self.x.XSetErrorHandler(self.error)
        self.display = self.x.XOpenDisplay(os.environ.get('DISPLAY', ':0').encode())
        if not self.display:
            raise RuntimeError('Cannot observe XWayland activation')
        self.root = self.x.XDefaultRootWindow(self.display)
        self.atoms = {name: self.x.XInternAtom(self.display, name.encode(), 0)
                      for name in ('_NET_ACTIVE_WINDOW', '_NET_WM_PID')}
        self.kinds = {}

    def cardinal(self, window, name):
        actual, count, remaining = C.c_ulong(), C.c_ulong(), C.c_ulong()
        fmt, data = C.c_int(), C.c_void_p()
        try:
            status = self.x.XGetWindowProperty(self.display, window, self.atoms[name],
                0, 1, 0, 0, C.byref(actual), C.byref(fmt), C.byref(count),
                C.byref(remaining), C.byref(data))
            if status == 0 and fmt.value == 32 and count.value and data.value:
                return C.cast(data, C.POINTER(C.c_ulong))[0]
            return 0
        finally:
            if data.value:
                self.x.XFree(data)

    def current(self, editor_pid):
        window = self.cardinal(self.root, '_NET_ACTIVE_WINDOW')
        if not window:
            return 'unknown', 0
        pid = self.cardinal(window, '_NET_WM_PID')
        if pid == editor_pid:
            return 'editor', window
        identity = (pid, process_start(pid))
        if identity in self.kinds:
            return self.kinds[identity], window
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
        return kind, window

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


def watch(owner, windows, api=None, clock=time.monotonic, sleep=time.sleep,
          run=subprocess.run):
    api, returns = api or EsApi(), Returns()
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
    parser.add_argument('mode', choices=('spawn', 'run'))
    parser.add_argument('rom')
    parser.add_argument('pid', type=int)
    parser.add_argument('stamp')
    parser.add_argument('--home', default=os.environ.get('WT_HOME', '/userdata/system/ultimate-wine-toolbox'))
    args = parser.parse_args()
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
