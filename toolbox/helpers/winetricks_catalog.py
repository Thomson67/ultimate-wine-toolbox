#!/usr/bin/env python3
"""Read the real Winetricks catalogue without opening a game prefix."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

VERB = re.compile(r'[a-z0-9][a-z0-9_+-]*(?:=[a-zA-Z0-9_.+-]*)?')
CATEGORIES = {'apps', 'benchmarks', 'dlls', 'fonts', 'settings'}


def valid_verb(value):
    return bool(VERB.fullmatch(value)) and value.split('=', 1)[0] not in ('prefix', 'arch')


def parse_catalog(text):
    category = ''
    entries = {}
    for line in text.splitlines():
        header = re.fullmatch(r'=====\s+(\w+)\s+=====', line.strip())
        if header:
            category = header[1]
            continue
        fields = line.strip().split(None, 1)
        if category not in CATEGORIES or len(fields) != 2 or not valid_verb(fields[0]):
            continue
        verb, description = fields
        entries[verb] = dict(verb=verb, category=category, description=' '.join(description.split()))
    if not entries:
        raise ValueError('Winetricks list-all returned no component catalogue')
    return sorted(entries.values(), key=lambda item: (item['category'], item['verb']))


def script_for(home, runner, system=Path('/usr/wine'), custom=Path('/userdata/system/wine/custom')):
    directory = system if runner in ('__SYSTEM__', 'wine-tkg', 'wine-proton', 'lutris', 'proton') else custom
    installed = directory / 'winetricks'
    if installed.is_file():
        return installed
    command = shutil.which('winetricks')
    if command:
        return Path(command)
    cache = home / 'cache/winetricks'
    cache.mkdir(parents=True, exist_ok=True)
    script = cache / 'winetricks'
    if not script.is_file():
        request = urllib.request.Request(
            'https://raw.githubusercontent.com/Winetricks/winetricks/master/src/winetricks',
            headers={'User-Agent': 'Ultimate-Wine-Toolbox'})
        fd, temporary = tempfile.mkstemp(prefix='.download-', dir=cache)
        try:
            with os.fdopen(fd, 'wb') as output, urllib.request.urlopen(request, timeout=30) as response:
                shutil.copyfileobj(response, output)
            subprocess.run(['bash', '-n', temporary], check=True, capture_output=True)
            os.replace(temporary, script)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return script


def catalogue(script, cache):
    stat = script.stat()
    identity = [str(script), stat.st_size, stat.st_mtime_ns]
    try:
        previous = json.loads(cache.read_text())
        if previous.get('script') == identity and previous.get('entries'):
            return previous['entries']
    except (OSError, ValueError):
        pass
    with tempfile.TemporaryDirectory(prefix='uwt-winetricks-list-') as folder:
        env = dict(os.environ, WINEPREFIX=folder + '/prefix', WINE='false', WINESERVER='false',
                   XDG_CACHE_HOME=folder + '/cache', XDG_CONFIG_HOME=folder + '/config',
                   XDG_DATA_HOME=folder + '/data', WINETRICKS_OPT_NO_STATS='1',
                   LANG='C', LC_ALL='C', LANGUAGE='C')
        for key in ('WINETRICKS_LIB', 'WINETRICKS_CURMENU', 'WINETRICKS_METADATA'):
            env.pop(key, None)
        result = subprocess.run(['bash', str(script), 'list-all'], env=env,
                                capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise ValueError(result.stderr.strip()[-1500:] or 'Winetricks list-all failed')
        entries = parse_catalog(result.stdout)
    cache.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.catalog-', dir=cache.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            json.dump(dict(script=identity, entries=entries), output)
        os.replace(temporary, cache)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return entries


def official_catalogue(home):
    """Use upstream's generated list first; keep list-all as offline fallback."""
    cache = home / 'cache/winetricks/catalog.json'
    previous = None
    try:
        previous = json.loads(cache.read_text())
        if previous.get('source') == 'official-all' and time.time() - previous.get('fetched', 0) < 86400:
            return previous['entries']
    except (OSError, ValueError, KeyError):
        pass
    try:
        request = urllib.request.Request(
            'https://raw.githubusercontent.com/Winetricks/winetricks/master/files/verbs/all.txt',
            headers={'User-Agent': 'Ultimate-Wine-Toolbox'})
        with urllib.request.urlopen(request, timeout=15) as response:
            entries = parse_catalog(response.read().decode('utf-8'))
    except (OSError, ValueError):
        if previous and previous.get('entries'):
            return previous['entries']
        raise
    cache.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.catalog-', dir=cache.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            json.dump(dict(source='official-all', fetched=time.time(), entries=entries), output)
        os.replace(name, cache)
    finally:
        Path(name).unlink(missing_ok=True)
    return entries


def pending_components(prefix, verbs, catalog=None):
    try:
        installed = set((prefix / 'winetricks.log').read_text().split())
    except FileNotFoundError:
        installed = set()
    settings = set()
    if catalog:
        try:
            settings = {item['verb'] for item in json.loads(Path(catalog).read_text())['entries']
                        if item['category'] == 'settings'}
        except (OSError, ValueError, KeyError, TypeError):
            pass
    pending = []
    for verb in dict.fromkeys(verbs):
        # Settings are commands, not installed packages: they may need to be
        # reapplied even when they occurred earlier in Winetricks' history.
        if verb in installed and '=' not in verb and verb not in settings:
            print(f'winetricks_skipped_installed={verb}', flush=True)
        else:
            pending.append(verb)
    return pending


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--runner', default='__SYSTEM__')
    args = parser.parse_args()
    try:
        try:
            entries = official_catalogue(args.home)
        except (OSError, ValueError):
            script = script_for(args.home, args.runner)
            entries = catalogue(script, args.home / 'cache/winetricks/catalog.json')
        for item in entries:
            print(item['verb'] + '\t[' + item['category'] + '] ' + item['description'])
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'Winetricks catalogue: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
