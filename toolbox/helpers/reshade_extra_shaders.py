#!/usr/bin/env python3
"""Install small pinned shader additions without changing the upstream backend."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

PACK = 'uwt-retro-extras'
CATALOG = Path(__file__).resolve().parents[1] / 'data/reshade-extra-shaders.json'


def backend_packs(selection):
    names = selection.split(',')
    if not all(re.fullmatch(r'[a-z0-9_-]+', name) for name in names):
        raise ValueError('invalid shader selection')
    return ','.join(name for name in names if name != PACK) or 'none'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def payload(home, entry):
    cache = home / 'reshade/runtime/extra-shaders'
    cache.mkdir(parents=True, exist_ok=True)
    if cache.is_symlink():
        raise ValueError('extra shader cache must be a real directory')
    target = cache / (entry['sha256'] + '.fx')
    if target.is_symlink():
        raise ValueError('extra shader cache file must not be a link')
    if target.exists():
        data = target.read_bytes()
        if digest(data) != entry['sha256']:
            raise ValueError(f"extra shader cache changed: {entry['file']}")
        return data
    with tempfile.TemporaryDirectory(dir=cache) as folder:
        download = Path(folder) / 'shader.fx'
        subprocess.run(['curl', '-fsSL', '--retry', '2', '--connect-timeout', '15',
                        '--max-time', '90', '--max-filesize', '1048576',
                        entry['url'], '-o', str(download)], check=True)
        data = download.read_bytes()
        if len(data) > 1048576 or digest(data) != entry['sha256']:
            raise ValueError(f"extra shader SHA-256 check failed: {entry['file']}")
        from reshade_manager import atomic_bytes
        atomic_bytes(target, data)
        return data


def install(home, shaders, catalog=CATALOG):
    from reshade_manager import atomic_bytes, read_json, save_json, safe_leaf
    entries = json.loads(catalog.read_text())['effects']
    journal = shaders / 'uwt-extra-shaders.json'
    previous = read_json(journal).get('files', {})
    planned = []
    for entry in entries:
        if (not re.fullmatch(r'[A-Za-z0-9_-]+\.fx', entry['file']) or
                not re.fullmatch(r'[0-9a-f]{64}', entry['sha256']) or
                not re.fullmatch(r'https://raw\.githubusercontent\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/[0-9a-f]{40}/[^\s?#]+', entry['url'])):
            raise ValueError('invalid pinned extra shader entry')
        target = safe_leaf(shaders, 'Merged/Shaders/' + entry['file'])
        if target.is_symlink():
            raise ValueError(f'extra shader collides with a shader pack: {target}')
        if target.exists() and digest(target.read_bytes()) not in (
                entry['sha256'], previous.get(entry['file'], {}).get('sha256')):
            raise ValueError(f'extra shader edited; existing file preserved: {target}')
        planned.append((target, payload(home, entry)))
    # Verify all downloads and collisions before changing the merged effects.
    for target, data in planned:
        atomic_bytes(target, data)
    save_json(journal, {'pack': PACK, 'files': {e['file']: e for e in entries}})
