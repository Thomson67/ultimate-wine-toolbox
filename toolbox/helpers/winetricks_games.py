#!/usr/bin/env python3
"""Discover editable game prefixes and their configured Batocera runner."""
import argparse
from pathlib import Path


def valid_prefix(path):
    return (not path.is_symlink() and path.is_dir()
            and path.suffix.casefold() == '.wine'
            and not path.name.startswith('.')
            and not any(c in str(path) for c in '\n\r\t')
            and (path / 'system.reg').is_file()
            and (path / 'autorun.cmd').is_file()
            and not (path / 'drive_c').is_symlink()
            and not (path / 'drive_c/windows').is_symlink()
            and (path / 'drive_c/windows').is_dir())


def prefixes(directory):
    if not directory.is_dir():
        return []
    return sorted((p for p in directory.iterdir() if valid_game(p)),
                  key=lambda p: p.name.casefold())


def valid_game(path):
    if path.is_symlink() or path.name.startswith('.') or any(c in str(path) for c in '\n\r\t'):
        return False
    kind = path.suffix.casefold()
    return (valid_prefix(path) if kind == '.wine' else
            path.is_dir() if kind == '.pc' else
            path.is_file() if kind == '.wsquashfs' else False)


def configured_runner(prefix, conf):
    values = {}
    if conf.is_file():
        for line in conf.read_text(errors='surrogateescape').splitlines():
            if '=' in line and not line.lstrip().startswith(('#', ';')):
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip()
    for key in (f'windows["{prefix.name}"].wine-runner', 'windows.wine-runner'):
        value = values.get(key, '')
        if value:
            return value
    return '__SYSTEM__'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('list', 'runner', 'validate'))
    parser.add_argument('path', type=Path)
    parser.add_argument('--conf', type=Path, default=Path('/userdata/system/batocera.conf'))
    args = parser.parse_args()
    if args.action == 'list':
        for prefix in prefixes(args.path):
            print(prefix)
    elif args.action == 'validate':
        return 0 if valid_game(args.path) else 1
    else:
        print(configured_runner(args.path, args.conf))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
