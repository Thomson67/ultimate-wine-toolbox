"""Reversible per-game Pad2Key suspension for converted AntiMicroX profiles."""
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat

from antimicrox_live import atomic


class Pad2KeyStore:
    def __init__(self, home, userdata='/userdata'):
        self.home, self.userdata = Path(home), Path(userdata).resolve()
        self.cfg = self.home/'config/antimicrox-games.tsv'
        self.state = self.home/'state/antimicrox-pad2key-backups.json'
        self.registry = self.home/'state/antimicrox-pad2key-conversions.json'

    def read(self, path):
        value = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(value, dict):
            raise ValueError(f'Invalid Pad2Key state: {path}')
        return value

    def keys_path(self, rom):
        rom = Path(rom).absolute()
        if '..' in rom.parts or not rom.is_relative_to(self.userdata):
            raise ValueError('Game must be under /userdata')
        if rom.suffix.lower() in ('.wine', '.pc'):
            return rom/'padto.keys'
        if rom.suffix.lower() == '.wsquashfs':
            return Path(str(rom)+'.keys')
        raise ValueError('Select a .wine, .pc or .wsquashfs game')

    @contextmanager
    def locked(self):
        self.cfg.parent.mkdir(parents=True, exist_ok=True)
        with (self.cfg.parent/'antimicrox-games.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    @contextmanager
    def transaction(self, roms=(), extra=()):
        paths = set([self.cfg, self.state, self.registry, *extra])
        suspended = self.read(self.state)
        paths.update(self.keys_path(rom) for rom in roms if rom in suspended)
        before = {}
        for path in paths:
            if path.is_symlink():
                raise ValueError(f'Refusing to replace symlink: {path}')
            before[path] = (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) if path.exists() else None
        try:
            yield
        except BaseException:
            # Restore ROM files first; keep the backup manifest until last.
            for path in sorted(paths, key=lambda p: p == self.state):
                original = before[path]
                if original is None:
                    path.unlink(missing_ok=True)
                elif not path.exists() or path.read_bytes() != original[0] or stat.S_IMODE(path.stat().st_mode) != original[1]:
                    atomic(path, *original)
            raise

    def suspend(self, rom, extra_triggers=()):
        entries = self.read(self.state)
        path = self.keys_path(rom)
        if path.is_symlink():
            raise ValueError(f'Refusing a symlinked Pad2Key file: {path}')
        if rom in entries:
            expected = base64.b64decode(entries[rom]['disabled'])
            if not path.exists() or path.read_bytes() != expected:
                raise ValueError('Pad2Key changed while suspended; backup retained. Restore it before changing this assignment.')
            config = json.loads(expected)
        else:
            original = path.read_bytes() if path.exists() else None
            config = json.loads(original) if original is not None else {}
            if not isinstance(config, dict) or not isinstance(config.get('actions_player1', []), list):
                raise ValueError('Invalid existing Pad2Key JSON; file preserved')
            entries[rom] = {'path': str(path), 'original': base64.b64encode(original).decode() if original is not None else None,
                            'mode': stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644}
        # Empty-target actions override equal triggers in Batocera's merged
        # global Pad2Key files without emitting keys, clicks or mouse movement.
        triggers = [action.get('trigger') for action in config.get('actions_player1', []) if isinstance(action, dict)]
        triggers.extend(extra_triggers)
        masks = {}
        for trigger in triggers:
            if not isinstance(trigger, str) and not (isinstance(trigger, list) and all(isinstance(t, str) for t in trigger)):
                continue
            identity = json.dumps(sorted(trigger) if isinstance(trigger, list) else trigger)
            masks[identity] = {'trigger': trigger, 'type': 'key', 'target': []}
        config['actions_player1'] = list(masks.values())
        disabled = (json.dumps(config, ensure_ascii=False, indent=2)+'\n').encode()
        entries[rom]['disabled'] = base64.b64encode(disabled).decode()
        atomic(self.state, json.dumps(entries, ensure_ascii=False, indent=2).encode())
        atomic(path, disabled, entries[rom]['mode'])

    def restore(self, roms):
        entries = self.read(self.state)
        count = len(entries)
        for rom in roms:
            entry = entries.get(rom)
            if not entry:
                continue
            path = self.keys_path(rom)
            if str(path) != entry.get('path') or path.is_symlink():
                raise ValueError('Invalid Pad2Key backup path; backup retained')
            original = base64.b64decode(entry['original'], validate=True) if entry['original'] is not None else None
            disabled = base64.b64decode(entry['disabled'], validate=True)
            current = path.read_bytes() if path.exists() else None
            if current not in (disabled, original):
                raise ValueError(f'Pad2Key modified externally: {path}. Backup retained; no overwrite.')
            if original is None:
                path.unlink(missing_ok=True)
            elif current != original:
                atomic(path, original, entry['mode'])
            del entries[rom]
        if len(entries) != count:
            atomic(self.state, json.dumps(entries, ensure_ascii=False, indent=2).encode())

    def assign(self, rom, profile):
        if any(c in rom+profile for c in '\t\r\n'):
            raise ValueError('Paths cannot contain tabs or line breaks')
        if profile:
            selected = Path(profile).resolve()
            if not selected.is_file() or selected.suffix.lower() != '.amgp' or not selected.is_relative_to(self.userdata):
                raise ValueError('Select an existing .amgp profile under /userdata')
        with self.locked():
            registry = self.read(self.registry)
            suspended = self.read(self.state)
            converted = bool(profile) and str(Path(profile).resolve()) in registry
            extra = [self.keys_path(rom)] if converted or rom in suspended else []
            if converted and rom not in suspended:
                metadata = registry[str(Path(profile).resolve())]
                source = Path(metadata['source'])
                if source.exists():
                    content = source.read_bytes()
                    for entry in suspended.values():
                        if Path(entry['path']).resolve() == source.resolve() and content == base64.b64decode(entry['disabled']):
                            content = base64.b64decode(entry['original']) if entry['original'] is not None else b''
                            break
                    if hashlib.sha256(content).hexdigest() != metadata.get('sha256'):
                        raise ValueError('Pad2Key changed after conversion. Convert the updated file before activating it.')
            with self.transaction([rom], extra):
                self._assign(rom, profile, converted, suspended, registry)

    def _assign(self, rom, profile, converted, suspended, registry):
        if not profile:
            self.restore([rom])
        elif converted or rom in suspended:
            metadata = registry.get(str(Path(profile).resolve()), {})
            self.suspend(rom, metadata.get('triggers', []))
        raw = self.cfg.read_text() if self.cfg.exists() else ''
        lines = [line for line in raw.splitlines(keepends=True) if line.rstrip('\r\n').split('\t', 1)[0] != rom]
        if profile:
            if lines and not lines[-1].endswith('\n'):
                lines[-1] += '\n'
            lines.append(f'{rom}\t{profile}\n')
        atomic(self.cfg, ''.join(lines).encode())

    def restore_all(self):
        with self.locked():
            roms = list(self.read(self.state))
            with self.transaction(roms):
                self.restore(roms)
