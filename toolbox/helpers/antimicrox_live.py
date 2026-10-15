"""Transactional, per-ROM evmapy shortcut for an AntiMicroX editing session."""
import argparse
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import xml.etree.ElementTree as ET

MARKER = 'UWT AntiMicroX live Alt-Tab'
ACTION = {'trigger': ['hotkey', 'b'], 'type': 'key',
          'target': ['KEY_LEFTALT', 'KEY_TAB'], 'description': MARKER}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic(path, data, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.uwt-amx-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def trigger(action):
    value = action.get('trigger')
    return sorted(value) if isinstance(value, list) else value


def valid_profile(path):
    path = Path(path)
    if path.is_file() and path.stat().st_size <= 8*1024*1024:
        return ET.parse(path).getroot().tag in ('gamecontroller', 'joystick')
    return False


class LiveSession:
    def __init__(self, home, rom_root='/userdata/roms/windows'):
        self.home = Path(home)
        self.rom_root = Path(rom_root).absolute()
        self.state = self.home/'state/antimicrox-live.json'

    @contextmanager
    def locked(self):
        self.state.parent.mkdir(parents=True, exist_ok=True)
        with (self.state.parent/'antimicrox-live.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def read(self):
        return json.loads(self.state.read_text()) if self.state.exists() else None

    def write(self, data):
        atomic(self.state, json.dumps(data, ensure_ascii=False, indent=2).encode())

    def prepare(self, rom, profile=None):
        with self.locked():
            if self.state.exists():
                raise ValueError('A previous live session must be recovered first.')
            rom = Path(rom).absolute()
            if '..' in rom.parts or not rom.is_relative_to(self.rom_root) or not rom.exists():
                raise ValueError('Select an existing Windows ROM.')
            if rom.is_dir() and rom.suffix.lower() in ('.wine', '.pc'):
                keys = rom/'padto.keys'
            elif rom.is_file() and rom.suffix.lower() == '.wsquashfs':
                keys = rom.with_name(rom.name+'.keys')
            else:
                raise ValueError('Only .wine, .pc and .wsquashfs games can be launched.')
            if keys.is_symlink():
                raise ValueError('Refusing to replace a symlinked keys file.')
            original = keys.read_bytes() if keys.exists() else None
            config = json.loads(original) if original is not None else {}
            if not isinstance(config, dict) or not isinstance(config.get('actions_player1', []), list):
                raise ValueError('Invalid existing evmapy configuration; preserved.')
            actions = config.get('actions_player1', [])
            if any(not isinstance(action, dict) for action in actions):
                raise ValueError('Invalid player 1 actions; preserved.')
            displaced = [action for action in actions if trigger(action) == trigger(ACTION)]
            config['actions_player1'] = [ACTION] + [action for action in actions if trigger(action) != trigger(ACTION)]
            injected = (json.dumps(config, ensure_ascii=False, indent=2)+'\n').encode()
            new = profile is None
            if new:
                label = ''.join(c if c.isalnum() or c in ' -_[]' else '_' for c in rom.stem)[:100]
                profile = self.home/'config/antimicrox-profiles'/f'{label}-{digest(str(rom).encode())[:8]}.amgp'
                # Never overwrite an earlier unassociated profile.
                if not profile.exists():
                    atomic(profile, b'<?xml version="1.0"?>\n<gamecontroller configversion="19" appversion="3.6.1"><sets/></gamecontroller>\n', 0o644)
            else:
                profile = Path(profile).resolve(strict=True)
                if not profile.is_relative_to(Path('/userdata')) and not profile.is_relative_to(self.home.resolve()):
                    raise ValueError('Profiles must remain under /userdata.')
            if not valid_profile(profile):
                raise ValueError('Invalid AntiMicroX XML profile.')
            mode = stat.S_IMODE(keys.stat().st_mode) if keys.exists() else 0o644
            data = {'rom': str(rom), 'profile': str(profile), 'phase': 'preparing',
                    'keys': str(keys), 'original': base64.b64encode(original).decode() if original is not None else None,
                    'mode': mode, 'injected_sha256': digest(injected), 'displaced': displaced,
                    'result': '', 'error': ''}
            # Persist the original before any change, including power-loss recovery.
            self.write(data)
            try:
                atomic(keys, injected, mode)
                data['phase'] = 'prepared'
                self.write(data)
            except BaseException:
                if original is None:
                    keys.unlink(missing_ok=True)
                else:
                    atomic(keys, original, mode)
                self.state.unlink(missing_ok=True)
                raise
            return data

    def profile(self, rom):
        with self.locked():
            data = self.read()
            if data and data['rom'] == rom and data['phase'] in ('prepared', 'running'):
                return data['profile']
            return ''

    def mark(self, rom, phase=None, error=None):
        with self.locked():
            data = self.read()
            if data and data['rom'] == rom:
                if phase:
                    data['phase'] = phase
                if error:
                    data['error'] = error
                self.write(data)

    def finish(self, result='stopped', rom=None):
        with self.locked():
            data = self.read()
            if not data or (rom is not None and data['rom'] != rom):
                return data
            if data['phase'] == 'finished':
                return data
            keys = Path(data['keys'])
            if keys.is_symlink():
                raise ValueError('Keys path became a symlink; original retained in session state.')
            original = base64.b64decode(data['original']) if data['original'] is not None else None
            current = keys.read_bytes() if keys.exists() else None
            if current is not None and digest(current) == data['injected_sha256']:
                if original is None:
                    keys.unlink()
                else:
                    atomic(keys, original, data['mode'])
            elif current != original and current is not None:
                # Preserve edits made during the session; remove only our marked rule.
                config = json.loads(current)
                actions = config.get('actions_player1', [])
                ours = [a for a in actions if a == ACTION]
                if ours:
                    actions = [a for a in actions if a != ACTION]
                    for action in data['displaced']:
                        if not any(trigger(a) == trigger(action) for a in actions):
                            actions.append(action)
                    config['actions_player1'] = actions
                    atomic(keys, (json.dumps(config, ensure_ascii=False, indent=2)+'\n').encode(), data['mode'])
            data['phase'] = 'finished'
            data['result'] = result
            self.write(data)
            return data

    def clear(self):
        with self.locked():
            data = self.read()
            if data and data['phase'] != 'finished':
                raise ValueError('Restore the temporary keys before clearing the session.')
            self.state.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', default='/userdata/system/ultimate-wine-toolbox')
    sub = parser.add_subparsers(dest='command', required=True)
    prepare = sub.add_parser('prepare'); prepare.add_argument('rom'); prepare.add_argument('--profile')
    profile = sub.add_parser('profile'); profile.add_argument('rom')
    mark = sub.add_parser('mark'); mark.add_argument('rom'); mark.add_argument('--phase'); mark.add_argument('--error')
    finish = sub.add_parser('finish'); finish.add_argument('--rom'); finish.add_argument('--result', default='stopped')
    field = sub.add_parser('field'); field.add_argument('name')
    sub.add_parser('clear')
    args = parser.parse_args()
    session = LiveSession(args.home)
    if args.command == 'prepare':
        print(session.prepare(args.rom, args.profile)['profile'])
    elif args.command == 'profile':
        print(session.profile(args.rom))
    elif args.command == 'mark':
        session.mark(args.rom, args.phase, args.error)
    elif args.command == 'finish':
        session.finish(args.result, args.rom)
    elif args.command == 'field':
        print((session.read() or {}).get(args.name, ''))
    elif args.command == 'clear':
        session.clear()


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, ET.ParseError) as exc:
        raise SystemExit(str(exc))
