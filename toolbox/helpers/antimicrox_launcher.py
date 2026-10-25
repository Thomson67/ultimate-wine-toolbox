"""Per-game launcher rules and owned X11/XWayland runtime profile switching.

Learning records window metadata only. It never changes an existing prefix or
imports/executes Windows AutoProfile settings. Live editing keeps its own profile.
"""
import argparse
import ctypes as C
from contextlib import contextmanager
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from antimicrox_focus import XWindows, process_start
from antimicrox_handoff import EsApi
from antimicrox_live import LiveSession, atomic, valid_profile


def log(message):
    print(f'[{datetime.now().astimezone().isoformat(timespec="seconds")}] '
          f'AntiMicroX launcher {message}', flush=True)


def read_json(path, default=None):
    try:
        if path.stat().st_size > 1024*1024:
            raise ValueError('Launcher JSON exceeds 1 MiB')
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def clean(text):
    return ''.join(c if ord(c) >= 32 and ord(c) != 127 else ' ' for c in str(text))[:512]


def validate_rule(rule):
    if not isinstance(rule, dict) or set(rule) != {'field', 'match', 'value'}:
        raise ValueError('Invalid window rule')
    if rule['field'] not in ('title', 'class', 'exe') or rule['match'] not in ('exact', 'contains'):
        raise ValueError('Unknown window rule type')
    value = rule['value']
    if not isinstance(value, str) or not value.strip() or len(value) > 512 or clean(value) != value:
        raise ValueError('Enter a non-empty window rule (maximum 512 characters)')
    return dict(rule)


def matches(rule, window):
    value = window.get(rule['field'], '')
    expected = rule['value']
    if rule['field'] == 'exe':
        value, expected = value.casefold(), expected.casefold()
    return expected == value if rule['match'] == 'exact' else expected in value


def selected_profile(config, window):
    """Unrecognized and foreign focus always means no emulated input."""
    if window is None:
        return ''
    if matches(config['launcher_rule'], window):
        return config['launcher_profile']
    if config['mode'] == 'profiles':
        rule = config.get('game_rule')
        if rule is None or matches(rule, window):
            return config['game_profile']
    return ''


class StableChoice:
    def __init__(self, delay=.4):
        self.delay, self.pending, self.since = delay, None, 0

    def observe(self, value, now):
        if value != self.pending:
            self.pending, self.since = value, now
        return value if now - self.since >= self.delay else None


class Store:
    def __init__(self, home):
        self.home = Path(home)
        self.directory = self.home/'config/antimicrox-launchers'
        self.learning = self.home/'state/antimicrox-launcher-learning.json'

    def path(self, rom):
        return self.directory/(hashlib.sha256(rom.encode()).hexdigest()+'.json')

    @contextmanager
    def locked(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory/'config.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def profile(self, value):
        if not isinstance(value, str) or not value:
            raise ValueError('Missing profile path')
        path = Path(value).resolve(strict=True)
        if not (path.is_relative_to(Path('/userdata')) or path.is_relative_to(self.home.resolve())):
            raise ValueError('Profile must remain under /userdata')
        if path.suffix.lower() != '.amgp' or not valid_profile(path):
            raise ValueError('Invalid AntiMicroX profile')
        return str(path)

    def load(self, rom, assigned=None):
        value = read_json(self.path(rom))
        if value is None:
            return None
        if not isinstance(value, dict) or value.get('version') != 1 or value.get('rom') != rom:
            raise ValueError('Invalid launcher configuration')
        if value.get('mode') not in ('launcher', 'profiles'):
            raise ValueError('Invalid launcher mode')
        value['launcher_rule'] = validate_rule(value.get('launcher_rule'))
        value['launcher_profile'] = self.profile(value.get('launcher_profile', ''))
        if assigned is not None and value['launcher_profile'] != str(Path(assigned).resolve()):
            return None  # A normal profile reassignment supersedes stale rules.
        if value['mode'] == 'profiles':
            value['game_profile'] = self.profile(value.get('game_profile', ''))
        if value.get('game_rule') is not None:
            value['game_rule'] = validate_rule(value['game_rule'])
        return value

    def save(self, rom, mode, launcher_profile, launcher_rule, game_profile='', game_rule=None,
             validate_only=False):
        if mode not in ('launcher', 'profiles'):
            raise ValueError('Invalid launcher mode')
        if not Path(rom).is_absolute() or any(c in rom for c in '\r\n\t'):
            raise ValueError('Invalid ROM path')
        value = {'version': 1, 'rom': rom, 'mode': mode,
                 'launcher_profile': self.profile(launcher_profile),
                 'launcher_rule': validate_rule(launcher_rule), 'game_profile': '',
                 'game_rule': validate_rule(game_rule) if game_rule else None}
        if mode == 'profiles':
            value['game_profile'] = self.profile(game_profile)
        if validate_only:
            return value
        with self.locked():
            atomic(self.path(rom), json.dumps(value, ensure_ascii=False, indent=2).encode())
        return value

    def empty(self):
        path = self.home/'state/antimicrox/launcher-empty.amgp'
        data = b'<?xml version="1.0"?><gamecontroller configversion="19" appversion="3.6.1"><sets/></gamecontroller>\n'
        if not path.exists() or path.read_bytes() != data:
            atomic(path, data, 0o644)
        return str(path)

    def learn(self, rom):
        atomic(self.learning, json.dumps({'version': 1, 'rom': rom, 'pending': True,
                                         'observations': []}).encode())

    def observations(self, rom):
        value = read_json(self.learning, {})
        return value.get('observations', []) if value.get('rom') == rom else []


class Session:
    def __init__(self, home, rom, pid, stamp):
        self.home, self.rom, self.pid, self.stamp = Path(home), rom, pid, stamp

    def active(self):
        try:
            return ((self.home/'state/antimicrox/session').read_text().rstrip('\n').split('\t')
                    == [self.rom, str(self.pid), self.stamp]
                    and process_start(self.pid) == self.stamp)
        except OSError:
            return False


class Windows(XWindows):
    def text(self, window, name):
        if name not in self.atoms:
            self.atoms[name] = self.x.XInternAtom(self.display, name.encode(), 0)
        actual, count, remaining = C.c_ulong(), C.c_ulong(), C.c_ulong()
        fmt, data = C.c_int(), C.c_void_p()
        try:
            status = self.x.XGetWindowProperty(self.display, window, self.atoms[name],
                0, 512, 0, 0, C.byref(actual), C.byref(fmt), C.byref(count),
                C.byref(remaining), C.byref(data))
            if status == 0 and fmt.value == 8 and data.value:
                return C.string_at(data, count.value).decode('utf-8', errors='replace')
            return ''
        finally:
            if data.value:
                self.x.XFree(data)

    def snapshot(self, editor_pid):
        window = self.cardinal(self.root, '_NET_ACTIVE_WINDOW')
        if not window or self.kind(window, editor_pid) != 'game':
            return None
        pid = self.cardinal(window, '_NET_WM_PID')
        try:
            proc = Path('/proc')/str(pid)
            fields = dict(item.split('=', 1) for item in
                          (proc/'environ').read_bytes().decode(errors='replace').split('\0') if '=' in item)
            arguments = (proc/'cmdline').read_bytes().decode(errors='replace').split('\0')
            exe = next((arg.replace('\\', '/').rsplit('/', 1)[-1] for arg in arguments
                        if arg.lower().endswith('.exe')), '')
            return {'window': window, 'pid': pid, 'stamp': process_start(pid),
                    'prefix': fields.get('WINEPREFIX', ''), 'exe': clean(exe),
                    'title': clean(self.text(window, '_NET_WM_NAME') or self.text(window, 'WM_NAME')),
                    'class': clean(' / '.join(filter(None, self.text(window, 'WM_CLASS').split('\0'))))}
        except OSError:
            return None


class Scope:
    """Only newly launched Wine windows of the current ES game session."""
    def __init__(self, stamp, baseline):
        self.stamp, self.baseline, self.prefix = int(stamp), set(baseline), None

    def accept(self, window):
        if not window or window['window'] in self.baseline:
            return None
        if not window.get('stamp') or int(window['stamp']) < self.stamp:
            return None
        prefix = window.get('prefix')
        if not prefix:
            return None  # Never guess session ownership if Wine omits its prefix.
        if self.prefix is None:
            self.prefix = prefix
        return window if prefix == self.prefix else None


def apply_profile(session, profile, binary):
    # Serialise IPC against the existing lifecycle hook's exclusive session lock.
    with (session.home/'state/antimicrox/lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        if not session.active():
            return False
        subprocess.run([str(binary), '--hidden', '--no-tray', '--profile', profile],
                       check=True, timeout=5, stdin=subprocess.DEVNULL,
                       close_fds=True)
        return session.active()


def watch(session, windows, baseline, learning=False, api=None, clock=time.monotonic,
          sleep=time.sleep, apply=apply_profile):
    store = Store(session.home)
    scope, stable = Scope(session.stamp, baseline), StableChoice()
    api = api or EsApi()
    config = None if learning else store.load(session.rom)
    if not learning and config is None:
        return
    empty = store.empty() if not learning else ''
    binary = session.home/'tools/antimicrox/antimicrox'
    current, seen, started, api_at, api_ok = empty, set(), clock(), -1, False
    saw_game, missing_since = False, started
    log('learning started' if learning else 'runtime started (initial empty profile)')
    while session.active():
        now = clock()
        if now - api_at >= 1:
            status, rom = api.running()
            api_at, api_ok = now, status == 200 and rom == session.rom
            if api_ok:
                saw_game = True
                missing_since = None
            if status == 200 and rom != session.rom and saw_game:
                break
        # gameStart can precede ES publishing the running ROM.
        if not api_ok:
            if not learning and current != empty:
                try:
                    if apply(session, empty, binary):
                        current = empty
                except (OSError, subprocess.SubprocessError):
                    break
            if saw_game and status in (201, 404):
                break
            if missing_since is None:
                missing_since = now
            if now - missing_since > (5 if saw_game else 30):
                break
            sleep(.2)
            continue
        window = scope.accept(windows.snapshot(session.pid))
        if learning:
            if window:
                identity = tuple(window[k] for k in ('title', 'class', 'exe'))
                if identity not in seen and len(seen) < 128:
                    state = read_json(store.learning, {})
                    if state.get('rom') != session.rom:
                        break
                    state.setdefault('observations', []).append(window)
                    atomic(store.learning, json.dumps(state, ensure_ascii=False, indent=2).encode())
                    seen.add(identity)
                    log('observed '+json.dumps({k: window[k] for k in ('title', 'class', 'exe')}, ensure_ascii=False))
        else:
            desired = selected_profile(config, window) or empty
            choice = stable.observe(desired, now)
            if choice is not None and choice != current:
                try:
                    if apply(session, choice, binary):
                        current = choice
                        log('profile='+str(Path(choice).name)+' window='+str(window and window['title']))
                except (OSError, subprocess.SubprocessError) as exc:
                    log('profile switch failed: '+str(exc))
                    break
        sleep(.2)
    # Leave no emulated commands active when focus/session validation fails.
    if not learning and current != empty and session.active():
        try:
            apply(session, empty, binary)
        except (OSError, subprocess.SubprocessError):
            pass
    log('observer stopped')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', default=os.environ.get('WT_HOME', '/userdata/system/ultimate-wine-toolbox'))
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('show', 'disable', 'learn', 'observations', 'initial', 'prepare-test', 'is-test'):
        p = sub.add_parser(name)
        p.add_argument('rom')
        if name in ('initial', 'prepare-test'):
            p.add_argument('assigned')
    p = sub.add_parser('save')
    p.add_argument('rom'); p.add_argument('mode', choices=('launcher', 'profiles'))
    p.add_argument('launcher_profile'); p.add_argument('launcher_rule')
    p.add_argument('--game-profile', default=''); p.add_argument('--game-rule')
    p.add_argument('--check', action='store_true')
    p = sub.add_parser('rule')
    p.add_argument('field', choices=('title', 'class', 'exe'))
    p.add_argument('match', choices=('exact', 'contains')); p.add_argument('value')
    p = sub.add_parser('observation-rule')
    p.add_argument('rom'); p.add_argument('index', type=int)
    p.add_argument('field', choices=('title', 'class', 'exe'))
    for name in ('spawn', 'run'):
        p = sub.add_parser(name)
        p.add_argument('rom'); p.add_argument('pid', type=int); p.add_argument('stamp')
        p.add_argument('--learning', action='store_true')
        p.add_argument('--baseline', default='[]')
    args = parser.parse_args()
    store = Store(args.home)
    if args.command == 'rule':
        print(json.dumps(validate_rule({'field': args.field, 'match': args.match, 'value': args.value}), ensure_ascii=False))
    elif args.command == 'observation-rule':
        rows = store.observations(args.rom)
        if not 1 <= args.index <= len(rows):
            raise ValueError('Observation not found')
        print(json.dumps(validate_rule({'field': args.field, 'match': 'exact',
                         'value': rows[args.index-1][args.field]}), ensure_ascii=False))
    elif args.command == 'save':
        store.save(args.rom, args.mode, args.launcher_profile, json.loads(args.launcher_rule),
                   args.game_profile, json.loads(args.game_rule) if args.game_rule else None,
                   args.check)
    elif args.command == 'show':
        print(json.dumps(store.load(args.rom), ensure_ascii=False, indent=2))
    elif args.command == 'disable':
        with store.locked():
            store.path(args.rom).unlink(missing_ok=True)
    elif args.command == 'learn':
        store.learn(args.rom)
    elif args.command == 'observations':
        for index, row in enumerate(store.observations(args.rom), 1):
            print(str(index)+'\t'+clean(row['title'] or '—')+'\t'+clean(row['class'] or '—')+'\t'+clean(row['exe'] or '—'))
    elif args.command == 'initial':
        if store.load(args.rom, args.assigned):
            print(store.empty())
    elif args.command == 'prepare-test':
        config = store.load(args.rom, args.assigned)
        if config is None:
            raise ValueError('No active launcher rules for this game')
        session = LiveSession(args.home)
        previous = session.read()
        if previous:
            if previous.get('phase') != 'finished':
                raise ValueError('Finish or recover the preceding session before testing')
            session.clear()
        print(session.prepare(args.rom, config['launcher_profile'], runtime_test=True)['profile'])
    elif args.command == 'is-test':
        data = LiveSession(args.home).read() or {}
        if data.get('rom') == args.rom and data.get('phase') in ('prepared', 'running') and data.get('runtime_test'):
            print('1')
    else:
        os.environ.setdefault('DISPLAY', ':0')
        os.environ.setdefault('XAUTHORITY', '/var/lib/.Xauthority')
        session = Session(args.home, args.rom, args.pid, args.stamp)
        if not session.active():
            return
        if args.learning:
            data = read_json(store.learning, {})
            if data.get('rom') != args.rom:
                return
            if args.command == 'spawn':
                if not data.get('pending'):
                    return
                data.update(pending=False, pid=args.pid, stamp=args.stamp)
                atomic(store.learning, json.dumps(data, ensure_ascii=False).encode())
            elif data.get('pid') != args.pid or data.get('stamp') != args.stamp:
                return
        elif store.load(args.rom) is None:
            return
        if args.command == 'spawn':
            windows = Windows()
            try:
                baseline = windows.client_windows()
            finally:
                windows.close()
            command = [sys.executable, str(Path(__file__).resolve()), '--home', args.home,
                       'run', args.rom, str(args.pid), args.stamp,
                       '--baseline', json.dumps(baseline)]
            if args.learning:
                command.append('--learning')
            subprocess.Popen(command, start_new_session=True, close_fds=True,
                             stdin=subprocess.DEVNULL)
        else:
            with (session.home/'state/antimicrox/launcher-observer.lock').open('a') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return
                windows = Windows()
                try:
                    watch(session, windows, json.loads(args.baseline), args.learning)
                finally:
                    windows.close()


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print('AntiMicroX launcher: '+str(exc), file=sys.stderr, flush=True)
        sys.exit(1)
