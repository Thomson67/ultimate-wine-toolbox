"""Opt-in controller keyboard policy and owned, detached game lifecycle.

This feature never edits Batocera hotkeys, autorun.cmd or ROM Pad2Key files.
The watcher observes the otherwise unused Hotkey+Select chord itself.
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
    def __init__(self, home=HOME):
        self.home = Path(home)
        self.path = self.home/'config/virtual-keyboard.json'

    def read(self):
        if not self.path.exists():
            return {'global': False, 'games': {}}
        data = json.loads(self.path.read_text())
        if (not isinstance(data, dict) or type(data.get('global')) is not bool
                or not isinstance(data.get('games'), dict)
                or any(v not in ('on', 'off') for v in data['games'].values())):
            raise ValueError('Invalid virtual keyboard settings; preserved')
        return data

    def override(self, rom):
        return self.read()['games'].get(rom_key(rom), 'inherit')

    def enabled(self, rom):
        data = self.read()
        return {'on': True, 'off': False}.get(data['games'].get(rom_key(rom)), data['global'])

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
            raise ValueError('Invalid keyboard activation')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with (self.path.parent/'virtual-keyboard.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = self.read()
            if rom is None:
                data['global'] = value == 'on'
            elif value == 'inherit':
                data['games'].pop(rom_key(rom), None)
            else:
                data['games'][rom_key(rom)] = value
            atomic(self.path, (json.dumps(data, ensure_ascii=False, indent=2)+'\n').encode())


def chord_conflicts(actions):
    """A Select-only mapping also fires while the modifier is held in evmapy."""
    if not isinstance(actions, list):
        raise ValueError('Invalid Pad2Key actions')
    for action in actions:
        if not isinstance(action, dict):
            raise ValueError('Invalid Pad2Key action')
        trigger = action.get('trigger')
        trigger = [trigger] if isinstance(trigger, str) else trigger
        if not isinstance(trigger, list):
            raise ValueError('Invalid Pad2Key trigger')
        if action.get('target') and ('select' in trigger or trigger == ['hotkey']
                                     or ('hotkey' in trigger and action.get('mode') == 'any')):
            return True
    return False


def conflict(home, rom, global_keys=None, system_keys=Path('/usr/share/evmapy/hotkeys.keys'), modifiers=None):
    """Refuse conflicting user bindings instead of silently replacing them."""
    home, rom = Path(home), Path(rom)
    global_keys = global_keys or Path('/userdata/system/configs/hotkeys.keys')
    global_path = global_keys if global_keys.exists() else system_keys
    paths = [global_path, rom/'padto.keys' if rom.is_dir() else Path(str(rom)+'.keys')]
    for path in paths:
        if path.exists():
            if chord_conflicts(json.loads(path.read_text()).get('actions_player1', [])):
                return f'Hotkey + Select / Select already mapped in {path}'
    # Check the assigned AMX profile, including alternate sets. Global enable
    # must not grab a controller while the same chord runs a mapped action.
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
    from virtual_keyboard_antimicrox import active_modifiers, reserved_profile
    # One snapshot for all profiles. The watcher passes its already-open
    # controllers so opening the keyboard never re-enumerates input devices.
    if profiles and modifiers is None:
        modifiers = active_modifiers()
    for path in dict.fromkeys(profiles):
        try:
            reserved_profile(path, modifiers=modifiers)
        except ValueError as exc:
            return f'AntiMicroX: {exc}'
    return ''


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
    if not Settings(home).enabled(rom): return
    if Path(rom).suffix.lower() not in FORMATS:
        raise ValueError('Unsupported game format')
    problem = conflict(home, rom)
    if problem: raise ValueError(problem)
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
            raise RuntimeError('Cannot identify keyboard watcher')
        atomic(state/'session.json', json.dumps({'rom': rom, 'pid': child.pid, 'token': token}).encode())



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', type=Path, default=Path(os.environ.get('WT_HOME', HOME)))
    parser.add_argument('action', choices=('get', 'set', 'start', 'stop', 'run', 'diagnose', 'preview', 'profile', 'game-states', 'configured-games'))
    parser.add_argument('--rom')
    parser.add_argument('--profile')
    parser.add_argument('--value', choices=('on', 'off', 'inherit'))
    args = parser.parse_args()
    settings = Settings(args.home)
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
