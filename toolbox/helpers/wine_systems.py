#!/usr/bin/env python3
"""Discover ES Wine systems without executing their commands or scanning archives.

Shared discovery API; only MangoHud opts into custom systems for now.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import tempfile
import xml.etree.ElementTree as ET

DEFAULT_HOME = Path('/userdata/system/ultimate-wine-toolbox')
DEFAULT_ES_USER = Path('/userdata/system/configs/emulationstation')
DEFAULT_ES_SYSTEM = Path('/usr/share/emulationstation/es_systems.cfg')
DIRECT_FORMATS = {'.wine', '.pc'}
CUSTOM_FORMATS = DIRECT_FORMATS | {'.wsquashfs'}
WINE_EMULATORS = {'wine', 'wine-dcg'}


def clean(value: str) -> bool:
    return bool(value) and not any(c in value for c in '\t\r\n\0')


def launcher_kind(command: str) -> str:
    try:
        words = shlex.split(command)
    except ValueError:
        return 'unknown'
    if (len(words) >= 2 and words[0] in {'python', 'python3', '/usr/bin/python', '/usr/bin/python3'}
            and words[1] == '/userdata/system/dcg/configgen/run.py'):
        return 'dcg'
    if words and words[0] in {'/usr/bin/emulatorlauncher', '/usr/bin/batocera-launch'}:
        return 'native'
    return 'unknown'


def discover(user_dir: Path = DEFAULT_ES_USER, system_file: Path = DEFAULT_ES_SYSTEM) -> dict:
    # User definitions override stock definitions, then custom files override
    # the user monolithic file. Malformed files do not hide other valid files.
    sources = [system_file, user_dir / 'es_systems.cfg']
    sources += sorted(user_dir.glob('es_systems_*.cfg'))
    definitions = {}
    for source in sources:
        try:
            root = ET.parse(source).getroot()
        except (OSError, ET.ParseError):
            continue
        for element in root.findall('system'):
            name = (element.findtext('name') or '').strip()
            if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', name) or name in {'.', '..'}:
                continue
            path = (element.findtext('path') or '').strip()
            emulators = sorted({e.get('name', '').strip() for e in element.findall('./emulators/emulator')})
            platform = re.split(r'[,\s]+', (element.findtext('platform') or '').strip().lower())
            backend = launcher_kind(element.findtext('command') or '')
            definitions[name] = {
                'name': name, 'label': (element.findtext('fullname') or name).strip(),
                'path': os.path.normpath(path), 'emulators': emulators,
                'extensions': sorted({e.lower() for e in (element.findtext('extension') or '').split()}),
                'backend': backend, 'platform': platform,
                'candidate': 'windows' in platform or bool(WINE_EMULATORS.intersection(emulators)),
            }
    return {name: row for name, row in definitions.items()
            if name != 'windows' and row['candidate'] and clean(row['path'])
            and Path(row['path']).is_absolute() and row['path'] != '/'
            and clean(row['label'])}


def supported(row: dict) -> bool:
    return row['backend'] in {'native', 'dcg'} and bool(WINE_EMULATORS.intersection(row['emulators']))


def enabled(home: Path) -> set[str]:
    try:
        data = json.loads((home / 'config/custom-wine-systems.json').read_text())
        values = data.get('enabled', [])
        return {name for name in values if isinstance(name, str)} if isinstance(values, list) else set()
    except (OSError, ValueError, AttributeError):
        return set()


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def within(rom: Path, root: str) -> bool:
    try:
        rom.absolute().relative_to(Path(root))
        # Reject lexical escapes as well as links into another collection.
        rom.resolve().relative_to(Path(root).resolve())
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def session_file(home: Path, rom: str) -> Path:
    key = hashlib.sha256(rom.encode()).hexdigest()
    return home / 'state/mangohud-custom' / (key + '.json')


def context(args, systems: dict) -> tuple[str, str, str] | None:
    if not clean(args.rom):
        return None
    if args.event == 'gameStop':
        try:
            saved = json.loads(session_file(args.home, args.rom).read_text())
            if saved['rom'] == args.rom and all(clean(saved[k]) for k in ('system', 'backend', 'autorun')):
                return saved['system'], saved['backend'], saved['autorun']
        except (OSError, ValueError, KeyError, TypeError):
            pass
    rom = Path(args.rom)
    # Some DCG fallbacks report system=windows. Locate a declared custom root
    # before accepting that as a native Windows launch; opt-out must still win.
    if args.system == 'windows':
        matches = [r for r in systems.values() if within(rom, r['path'])]
        if not matches:
            return 'windows', 'native', ''
        length = max(len(r['path']) for r in matches)
        matches = [r for r in matches if len(r['path']) == length]
        if len(matches) != 1:
            return None
        row = matches[0]
    else:
        row = systems.get(args.system)
        if row is None or not within(rom, row['path']):
            return None
    if row['name'] not in enabled(args.home) or not supported(row):
        return None
    # Actual event emulator/core win over XML defaults. Never apply the Wine
    # autorun adapter to the native/arcade alternatives in a mixed system.
    if args.emulator not in WINE_EMULATORS:
        return None
    if args.core in {'linuxloader', 'linuxloader-dcg', 'windows-arcade-loader'}:
        return None
    suffix = rom.suffix.lower()
    if suffix not in CUSTOM_FORMATS or suffix not in row['extensions']:
        return None
    if (suffix in DIRECT_FORMATS and not rom.is_dir()) or (suffix == '.wsquashfs' and not rom.is_file()):
        return None
    if row['backend'] == 'dcg' and args.emulator == 'wine' and args.major >= 44:
        # Current DCG explicitly redirects only these two systems on v44.
        # Other systems need an actual wine-dcg event, not a guessed routing.
        if row['name'] not in {'teknoparrot', 'windows_squash'}:
            return None
    return row['name'], row['backend'], ''


def game_paths(row: dict):
    extensions = CUSTOM_FORMATS.intersection(row['extensions'])
    for directory, dirs, files in os.walk(row['path'], followlinks=False):
        keep = []
        for name in dirs:
            path = Path(directory) / name
            if name.startswith('.') or name.lower() in {'images', 'videos', 'thumbnails', 'media', 'medias'}:
                continue
            if path.suffix.lower() in DIRECT_FORMATS:
                if path.suffix.lower() in extensions and not path.is_symlink() and clean(str(path)):
                    yield str(path)
            elif not path.is_symlink():
                keep.append(name)
        dirs[:] = keep
        for name in files:
            path = Path(directory) / name
            if not name.startswith('.') and path.suffix.lower() == '.wsquashfs' and '.wsquashfs' in extensions and clean(str(path)):
                yield str(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=DEFAULT_HOME)
    parser.add_argument('--es-user-dir', type=Path, default=DEFAULT_ES_USER)
    parser.add_argument('--es-system-file', type=Path, default=DEFAULT_ES_SYSTEM)
    commands = parser.add_subparsers(dest='action', required=True)
    commands.add_parser('systems')
    select = commands.add_parser('select')
    select.add_argument('names', nargs='*')
    commands.add_parser('games')
    event = commands.add_parser('context')
    event.add_argument('--event', choices=('gameStart', 'gameStop'), required=True)
    event.add_argument('--system', required=True)
    event.add_argument('--emulator', default='')
    event.add_argument('--core', default='')
    event.add_argument('--rom', required=True)
    event.add_argument('--major', type=int, default=0)
    remember = commands.add_parser('remember')
    remember.add_argument('system')
    remember.add_argument('backend', choices=('native', 'dcg'))
    remember.add_argument('rom')
    remember.add_argument('autorun')
    forget = commands.add_parser('forget')
    forget.add_argument('rom')
    args = parser.parse_args(argv)
    if args.action == 'remember':
        if not all(clean(v) for v in (args.system, args.rom, args.autorun)) or not Path(args.autorun).is_absolute():
            return 1
        atomic_json(session_file(args.home, args.rom), {k: getattr(args, k) for k in ('system', 'backend', 'rom', 'autorun')})
        return 0
    if args.action == 'forget':
        session_file(args.home, args.rom).unlink(missing_ok=True)
        return 0
    systems = discover(args.es_user_dir, args.es_system_file)
    selected = enabled(args.home)
    if args.action == 'systems':
        for name, row in sorted(systems.items()):
            if supported(row):
                print('\t'.join((name, row['path'], row['label'], row['backend'], 'on' if name in selected else 'off')))
    elif args.action == 'select':
        if any(name not in systems or not supported(systems[name]) for name in args.names):
            return 1
        atomic_json(args.home / 'config/custom-wine-systems.json', {'version': 1, 'enabled': sorted(set(args.names))})
    elif args.action == 'games':
        paths = {path for name, row in systems.items() if name in selected and supported(row) for path in game_paths(row)}
        for path in sorted(paths, key=str.casefold):
            print(path)
    elif args.action == 'context':
        result = context(args, systems)
        if result is None:
            return 1
        print('\n'.join(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
