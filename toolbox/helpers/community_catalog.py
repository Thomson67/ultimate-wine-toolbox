#!/usr/bin/env python3
"""Cache public community listings and serve the game-specific ES picker."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from community_packs import Packs
from community_profiles import Community, atomic, dump, entry_label, game_key

REFRESH_INTERVAL = 6 * 60 * 60
RETRY_INTERVAL = 15 * 60


def pack_cache(packs):
    return packs.home / 'state/community/packs-catalog.json'


def refresh(community, packs_factory):
    failed = False
    for source, update in (
        ('profiles', community.refresh),
        ('packs', lambda: refresh_packs(packs_factory())),
    ):
        try:
            update()
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f'{source}: {error}', file=sys.stderr)
            failed = True
    return not failed


def refresh_packs(packs):
    rows = packs.listing()
    atomic(pack_cache(packs), dump({'source': packs.api, 'entries': rows}))
    return rows


def load_packs(packs):
    path = pack_cache(packs)
    if path.is_file():
        saved = json.loads(path.read_text(encoding='utf-8'))
        if saved.get('source') == packs.api:
            return saved['entries']
    return refresh_packs(packs)


def game_entries(rows, rom, name):
    keys = {game_key(rom), game_key(name)} - {''}
    return [row for row in rows if game_key(row['game']) in keys]


def list_for_game(home, kind, rom, name):
    sources = [('profiles', '', lambda: (row for row in Community(home).load()['entries']
                                          if row['kind'] == kind))]
    if kind == 'reshade':
        sources.append(('packs', 'zip:', lambda: load_packs(Packs(home))))
    results = []
    errors = []
    for source, prefix, load in sources:
        try:
            for row in game_entries(load(), rom, name):
                suffix = ' [Pack ZIP]' if prefix else ''
                results.append((prefix + row['id'], entry_label(row) + suffix))
        except (OSError, ValueError, KeyError, TypeError) as error:
            errors.append(f'{source}: {error}')
    return sorted(results, key=lambda row: row[1].casefold()), errors


def serve(home):
    while Path(__file__).is_file():
        try:
            succeeded = refresh(Community(home), lambda: Packs(home))
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(error, file=sys.stderr)
            succeeded = False
        time.sleep(REFRESH_INTERVAL if succeeded else RETRY_INTERVAL)


def service(home, action, log):
    state = home / 'state/community'
    state.mkdir(parents=True, exist_ok=True)
    with (state / 'catalog-sync.lock').open('a+', encoding='utf-8') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if action == 'stop':
                lock.seek(0)
                pid = int(lock.read().strip() or '0')
                if pid > 0:
                    try:
                        command = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
                        if b'--serve' in command and os.fsencode(Path(__file__).resolve()) in command:
                            os.kill(pid, signal.SIGTERM)
                            for _ in range(30):
                                time.sleep(0.1)
                                try:
                                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                                    return 0
                                except BlockingIOError:
                                    continue
                            raise OSError('Community catalogue service did not stop')
                    except (FileNotFoundError, ProcessLookupError):
                        pass
            return 0
        if action != 'start':
            return int(action == 'status')
        log.parent.mkdir(parents=True, exist_ok=True)
        if log.is_file() and log.stat().st_size > 1024 * 1024:
            log.replace(log.with_suffix('.log.old'))
        command = [sys.executable, str(Path(__file__).resolve()), '--home', str(home), '--serve']
        with log.open('a', encoding='utf-8') as output:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output,
                                       stderr=output, start_new_session=True,
                                       pass_fds=(lock.fileno(),))
        lock.seek(0)
        lock.truncate()
        lock.write(str(process.pid))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--log', type=Path)
    parser.add_argument('--serve', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('action', nargs='?', choices=('start', 'stop', 'status', 'refresh', 'list'))
    parser.add_argument('kind', nargs='?', choices=('reshade', 'antimicrox'))
    parser.add_argument('rom', nargs='?')
    parser.add_argument('name', nargs='?')
    args = parser.parse_args()
    if args.serve:
        serve(args.home)
    if args.action == 'refresh':
        return 0 if refresh(Community(args.home), lambda: Packs(args.home)) else 1
    if args.action == 'list':
        rows, errors = list_for_game(args.home, args.kind, args.rom, args.name)
        for identifier, label in rows:
            print(f'{identifier}\t{label}')
        if errors and not rows:
            print('\n'.join(errors), file=sys.stderr)
            return 1
        return 0
    return service(args.home, args.action, args.log)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(str(exc))
