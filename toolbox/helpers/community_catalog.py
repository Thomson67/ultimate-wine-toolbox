#!/usr/bin/env python3
"""Cache public community listings and publish choices for EmulationStation."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import xml.etree.ElementTree as ET
import time

from community_packs import Packs
from community_profiles import Community, atomic, catalogue, dump
from es_options import refresh as refresh_es_options

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


def cached_entries(home, kind):
    entries = {}
    try:
        community = Community(home)
        if community.cache.is_file():
            saved = json.loads(community.cache.read_text(encoding='utf-8'))
            if saved['source'] == community.base:
                entries.update((row['id'], row) for row in catalogue(saved['catalog'])['entries']
                               if row['kind'] == kind)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'Profiles cache: {error}', file=sys.stderr)
    if kind == 'reshade':
        try:
            packs = Packs(home)
            path = pack_cache(packs)
            if path.is_file():
                saved = json.loads(path.read_text(encoding='utf-8'))
                if saved['source'] == packs.api:
                    entries.update(('zip:' + row['id'], row) for row in saved['entries'])
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f'Packs cache: {error}', file=sys.stderr)
    return entries


def es_choices(home, kind):
    labels = []
    for identifier, row in cached_entries(home, kind).items():
        if kind == 'reshade':
            if identifier.startswith('zip:'):
                title = row['title']
                label = title if title.casefold().endswith('.zip') else title + '.zip'
            else:
                label = Path(row['file']).name
        else:
            label = Path(row['file']).name
            if 'UWT launcher-package-v1' in row.get('requirements', ()):
                label += ' [Launcher]'
        labels.append((identifier, label, row['game'].casefold() if kind == 'reshade' else ''))
    return [(identifier, label) for identifier, label, _ in
            sorted(labels, key=lambda row: (row[2], row[1].casefold(), row[0]))]


def sync_catalogues(home):
    while Path(__file__).is_file():
        try:
            succeeded = refresh(Community(home), lambda: Packs(home))
            refresh_es_options(home=home)
        except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as error:
            print(error, file=sys.stderr)
            succeeded = False
        time.sleep(REFRESH_INTERVAL if succeeded else RETRY_INTERVAL)


def serve(home):
    from community_es import Selections

    threading.Thread(target=sync_catalogues, args=(home,), daemon=True).start()
    selections = Selections(home, cached_entries)
    while Path(__file__).is_file():
        try:
            selections.poll()
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
            print(f'ES community: {error}', file=sys.stderr)
            time.sleep(15)
        time.sleep(.2)


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
                                       stderr=output, start_new_session=True, cwd=home,
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
    parser.add_argument('action', nargs='?', choices=('start', 'stop', 'status', 'refresh'))
    args = parser.parse_args()
    if args.serve:
        serve(args.home)
    if args.action == 'refresh':
        return 0 if refresh(Community(args.home), lambda: Packs(args.home)) else 1
    return service(args.home, args.action, args.log)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(str(exc))
