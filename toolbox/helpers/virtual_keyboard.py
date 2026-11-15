"""Opt-in virtual input policy and owned, detached game lifecycle.

This feature never edits Batocera hotkeys, autorun.cmd or ROM Pad2Key files.
One watcher handles the keyboard and mouse shortcuts for a Windows game.
"""
import argparse
from contextlib import contextmanager
import fcntl
import json
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from antimicrox_live import atomic

HOME = Path('/userdata/system/ultimate-wine-toolbox')
FORMATS = {'.wine', '.pc', '.wsquashfs', '.wtgz'}


def rom_key(rom):
    path = Path(rom)
    if not path.is_absolute() or '..' in path.parts or any(c in str(path) for c in '\n\r\t'):
        raise ValueError('Invalid game path')
    return str(path)


class Settings:
    def __init__(self, home=HOME, feature='keyboard'):
        self.home = Path(home)
        self.feature = feature
        self.path = self.home/'config'/f'virtual-{feature}.json'

    def read(self):
        if not self.path.exists():
            return {'global': False, 'games': {}}
        data = json.loads(self.path.read_text())
        if (not isinstance(data, dict) or type(data.get('global')) is not bool
                or not isinstance(data.get('games'), dict)
                or any(v not in ('on', 'off') for v in data['games'].values())):
            raise ValueError(f'Invalid settings in {self.path.name}; preserved')
        return data

    def override(self, rom):
        return self.read()['games'].get(rom_key(rom), 'inherit')

    def enabled(self, rom):
        from es_options import Overrides
        data = self.read()
        override = Overrides(rom).get(self.feature, toolbox_game=data['games'].get(rom_key(rom)))
        return {'on': True, 'off': False}.get(override, data['global'])

    def game_states(self, roms):
        """Read the settings once for a complete game picker."""
        data = self.read()
        for rom in roms:
            rom = rom.rstrip('\n')
            if rom:
                key = rom_key(rom)
                yield data['games'].get(key, 'inherit'), key

    def configured_game_states(self):
        """List explicit per-game rules without scanning the ROM library."""
        games = self.read()['games']
        for rom in sorted(games, key=lambda p: (Path(p).name.casefold(), p.casefold())):
            yield games[rom], rom_key(rom)

    def set(self, value, rom=None):
        if value not in ('on', 'off', 'inherit') or (rom is None and value == 'inherit'):
            raise ValueError('Invalid virtual input activation')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = self.read()
            if rom is None:
                data['global'] = value == 'on'
            elif value == 'inherit':
                data['games'].pop(rom_key(rom), None)
            else:
                data['games'][rom_key(rom)] = value
            atomic(self.path, (json.dumps(data, ensure_ascii=False, indent=2)+'\n').encode())


def chord_conflicts(actions, button='select', batocera_defaults=False):
    """A single-button mapping can also fire with the modifier held."""
    if not isinstance(actions, list):
        raise ValueError('Invalid Pad2Key actions')
    for action in actions:
        if not isinstance(action, dict):
            raise ValueError('Invalid Pad2Key action')
        trigger = action.get('trigger')
        trigger = [trigger] if isinstance(trigger, str) else trigger
        if not isinstance(trigger, list):
            raise ValueError('Invalid Pad2Key trigger')
        target = action.get('target')
        if not target:
            continue
        # Wine has no next_disk action. Only exempt Batocera's stock
        # Hotkey + L3 event, never an override or another action in that file.
        if (batocera_defaults and button == 'l3' and len(trigger) == 2
                and 'hotkey' in trigger and 'l3' in trigger
                and action.get('type') == 'key' and action.get('mode', 'all') == 'all'
                and target in ('KEY_VIDEO_NEXT', ['KEY_VIDEO_NEXT'])):
            continue
        if button == 'select':
            if ('select' in trigger or trigger == ['hotkey']
                    or ('hotkey' in trigger and action.get('mode') == 'any')):
                return True
        elif (trigger and set(trigger) <= {'hotkey', button}
              or (action.get('mode') == 'any' and {'hotkey', button}.intersection(trigger))):
            return True
    return False


def conflict(home, rom, global_keys=None, system_keys=Path('/usr/share/evmapy/hotkeys.keys'),
             modifiers=None, button='select'):
    """Refuse conflicting user bindings instead of silently replacing them."""
    home, rom = Path(home), Path(rom)
    global_keys = global_keys or Path('/userdata/system/configs/hotkeys.keys')
    global_path = global_keys if global_keys.exists() else system_keys
    paths = [global_path, rom/'padto.keys' if rom.is_dir() else Path(str(rom)+'.keys')]
    for path in paths:
        if path.exists():
            actions = json.loads(path.read_text()).get('actions_player1', [])
            if chord_conflicts(actions, button, batocera_defaults=path == system_keys):
                return f'Hotkey + {button.upper()} conflicts with Pad2Key in {path}'
    # Check the assigned AMX profile, including alternate sets. Global enable
    # must not grab a controller while the same chord runs a mapped action.
    from es_options import Overrides
    if (not (home/'state/antimicrox-live.json').exists()
            and Overrides(rom).get('antimicrox') == 'off'):
        return ''
    profiles = []
    association = home/'config/antimicrox-games.tsv'
    if association.exists():
        for line in association.read_text().splitlines():
            fields = line.split('\t')
            if len(fields) == 2 and fields[0] == str(rom):
                profiles.append(Path(fields[1]))
    rules = home/'config/antimicrox-launchers'/(hashlib.sha256(str(rom).encode()).hexdigest()+'.json')
    if rules.exists():
        data = json.loads(rules.read_text())
        if not isinstance(data, dict) or data.get('rom') != str(rom):
            raise ValueError('Invalid launcher configuration')
        profiles.extend(Path(data[key]) for key in ('launcher_profile', 'game_profile') if data.get(key))
    from virtual_keyboard_antimicrox import active_modifiers, reserved_profile, INDICES
    # One snapshot for all profiles. The watcher passes its already-open
    # controllers so opening the keyboard never re-enumerates input devices.
    if profiles and modifiers is None:
        modifiers = active_modifiers() if button == 'select' else active_modifiers(button=button)
    for path in dict.fromkeys(profiles):
        try:
            if button == 'select':
                reserved_profile(path, modifiers=modifiers)
            else:
                reserved_profile(path, modifiers=modifiers, buttons=(INDICES[button],))
        except ValueError as exc:
            return f'AntiMicroX: {exc}'
    return ''


def shortcut_problem(home, rom, **options):
    try:
        return conflict(home, rom, **options)
    except (OSError, ValueError, ET.ParseError) as exc:
        return str(exc)


def process_identity(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(') ', 1)[1].split()
        if fields[0] in ('Z', 'X'):
            return ''
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        return boot+':'+fields[19]
    except (OSError, IndexError):
        return ''


@contextmanager
def lifecycle_lock(home):
    state = Path(home)/'state/virtual-keyboard'
    state.mkdir(parents=True, exist_ok=True)
    with (state/'lifecycle.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield state


def stop(home, rom=None):
    with lifecycle_lock(home) as state:
        path = state/'session.json'
        if not path.exists(): return
        data = json.loads(path.read_text())
        if rom is not None and data.get('rom') != rom_key(rom): return
        pid, token = data.get('pid'), data.get('token')
        if type(pid) is int and pid > 1 and token and process_identity(pid) == token:
            # Read the command line only to confirm our own daemon before
            # signalling a retained PID; never target Wine or another keyboard.
            cmd = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
            if str(Path(__file__).resolve()).encode() in cmd and b'run' in cmd:
                os.kill(pid, signal.SIGTERM)
                for _ in range(40):
                    if process_identity(pid) != token: break
                    time.sleep(.05)
                else:
                    # Closing its process-owned uinput/evdev FDs also releases
                    # all exclusive grabs if GTK fails to respond to SIGTERM.
                    os.kill(pid, signal.SIGKILL)
        path.unlink(missing_ok=True)


def start(home, rom, log=None):
    rom = rom_key(rom)
    keyboard = Settings(home).enabled(rom)
    mouse = Settings(home, 'mouse').enabled(rom)
    if not (keyboard or mouse): return
    if Path(rom).suffix.lower() not in FORMATS:
        raise ValueError('Unsupported game format')
    problem = shortcut_problem(home, rom) if keyboard else ''
    mouse_problem = shortcut_problem(home, rom, button='l3') if mouse else ''
    if problem: print(f'virtual_keyboard_refused={problem}', flush=True)
    if mouse_problem: print(f'virtual_mouse_refused={mouse_problem}', flush=True)
    if not ((keyboard and not problem) or (mouse and not mouse_problem)):
        raise ValueError(problem or mouse_problem)
    stop(home)
    log = Path(log or '/userdata/system/logs/ultimate-wine-toolbox/virtual-keyboard.log')
    log.parent.mkdir(parents=True, exist_ok=True)
    with lifecycle_lock(home) as state:
        with log.open('ab', buffering=0) as output:
            child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--home', str(home),
                                      'run', '--rom', rom], stdin=subprocess.DEVNULL, stdout=output,
                                     stderr=subprocess.STDOUT, close_fds=True, start_new_session=True)
        token = process_identity(child.pid)
        if not token:
            child.terminate()
            raise RuntimeError('Cannot identify virtual input watcher')
        atomic(state/'session.json', json.dumps({'rom': rom, 'pid': child.pid, 'token': token}).encode())



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', type=Path, default=Path(os.environ.get('WT_HOME', HOME)))
    parser.add_argument('--feature', choices=('keyboard', 'mouse'), default='keyboard')
    parser.add_argument('action', choices=('get', 'set', 'start', 'stop', 'run', 'diagnose', 'preview', 'profile', 'game-states', 'configured-games'))
    parser.add_argument('--rom')
    parser.add_argument('--profile')
    parser.add_argument('--value', choices=('on', 'off', 'inherit'))
    args = parser.parse_args()
    settings = Settings(args.home, args.feature)
    if args.action == 'get':
        print(settings.override(args.rom) if args.rom else ('on' if settings.read()['global'] else 'off'))
    elif args.action == 'configured-games':
        for state, rom in settings.configured_game_states():
            print(state+'\t'+rom)
    elif args.action == 'game-states':
        for state, rom in settings.game_states(sys.stdin):
            print(state+'\t'+rom)
    elif args.action == 'set': settings.set(args.value, args.rom)
    elif args.action == 'stop': stop(args.home, args.rom)
    elif args.action == 'start': start(args.home, args.rom)
    elif args.action == 'profile':
        from virtual_keyboard_antimicrox import runtime_profile
        print(runtime_profile(args.home, args.rom, args.profile))
    else:
        from virtual_keyboard_runtime import diagnose, run, preview
        if args.action == 'diagnose': diagnose(args.home)
        elif args.action == 'preview': preview(args.home)
        elif not args.rom: parser.error('run requires --rom')
        else: run(args.home, rom_key(args.rom))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, ImportError, RuntimeError, ET.ParseError) as exc:
        print(f'virtual_keyboard_error={exc}', file=sys.stderr)
        raise SystemExit(1)
