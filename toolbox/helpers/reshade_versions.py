#!/usr/bin/env python3
"""Versioned, separate ReShade payloads; shader/ compiler setup stays upstream."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import urllib.request
import zipfile

CATALOG = Path(__file__).resolve().parents[1] / 'data/reshade-versions.json'
LIMIT = 64 * 1024 * 1024


def catalog(path=CATALOG):
    data = json.loads(Path(path).read_text())
    if data.get('schema') != 1:
        raise ValueError('unsupported ReShade catalogue')
    entries = data['entries']
    seen = set()
    for entry in entries:
        if (not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-no-startup-banner)?', entry['id'])
                or entry['id'] in seen or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', entry['version'])
                or entry['variant'] not in ('standard', 'no-startup-banner')
                or not re.fullmatch(r'[a-f0-9]{64}', entry['sha256'])
                or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', entry['backend_version'])):
            raise ValueError('invalid ReShade catalogue entry')
        expected = entry['version'] + ('-no-startup-banner' if entry['variant'] != 'standard' else '')
        if entry['id'] != expected:
            raise ValueError('inconsistent ReShade version/variant')
        urls = (f'https://reshade.me/downloads/ReShade_Setup_{entry["version"]}.exe',
                f'https://github.com/fienestar/OverlayDisabledReShade/releases/download/v{entry["version"]}-patched/ReShade.Setup.exe')
        if entry['url'] != urls[entry['variant'] != 'standard']:
            raise ValueError('unexpected ReShade download source')
        seen.add(entry['id'])
    return entries


def selection(identity, entries=None):
    for entry in catalog() if entries is None else entries:
        if entry['id'] == identity:
            return entry
    raise ValueError(f'unknown ReShade release: {identity}')


def download(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Ultimate-Wine-Toolbox'})
    with urllib.request.urlopen(request, timeout=45) as response:
        data = response.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError('ReShade setup exceeds download limit')
    return data


def payload(home, identity, arch, fetch=download, entries=None):
    from reshade_manager import atomic_bytes, pe_arch, read_json, save_json
    entry = selection(identity, entries)
    if arch not in (32, 64):
        raise ValueError('unsupported ReShade architecture')
    root = Path(home) / 'reshade/runtime/builds'
    target = root / entry['id']
    # Never follow a redirected cache or overwrite unrelated game files.
    for path in (root.parent, root, target):
        if path.is_symlink() or path.resolve() != path.absolute():
            raise ValueError('redirected ReShade payload cache')
    manifest_path = target / 'provenance.json'
    if manifest_path.is_symlink():
        raise ValueError('redirected ReShade payload journal')
    manifest = read_json(manifest_path)
    valid = manifest.get('setup_sha256') == entry['sha256'] and manifest.get('id') == entry['id']
    for bits in (32, 64):
        path = target / f'ReShade{bits}.dll'
        if path.is_symlink():
            raise ValueError('redirected ReShade DLL cache')
        valid = (valid and path.is_file()
                 and hashlib.sha256(path.read_bytes()).hexdigest() == manifest.get(str(bits))
                 and pe_arch(path.read_bytes()) == bits)
    if valid:
        return target / f'ReShade{arch}.dll'
    data = fetch(entry['url'])
    if len(data) > LIMIT or hashlib.sha256(data).hexdigest() != entry['sha256']:
        raise ValueError('ReShade setup checksum mismatch; existing installation preserved')
    payloads = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for bits in (32, 64):
            name = f'ReShade{bits}.dll'
            if archive.namelist().count(name) != 1 or archive.getinfo(name).file_size > LIMIT:
                raise ValueError('missing, duplicated or oversized ReShade DLL')
            content = archive.read(name)
            if pe_arch(content) != bits:
                raise ValueError('wrong ReShade DLL architecture')
            payloads[bits] = content
    # Validate both architectures before writing either one. Variants never
    # replace the standard build's cache and existing game configs are untouched.
    target.mkdir(parents=True, exist_ok=True)
    for bits, content in payloads.items():
        atomic_bytes(target / f'ReShade{bits}.dll', content)
    license_path = CATALOG.parent / 'reshade-runtime-LICENSE.md'
    atomic_bytes(target / 'LICENSE.md', license_path.read_bytes())
    save_json(manifest_path, dict(id=entry['id'], version=entry['version'], variant=entry['variant'],
                                 source=entry['url'], provider=entry['provider'], setup_sha256=entry['sha256'],
                                 **{str(bits): hashlib.sha256(content).hexdigest() for bits, content in payloads.items()}))
    return target / f'ReShade{arch}.dll'


def current(home, rom):
    from reshade_manager import key, read_json
    return read_json(Path(home) / 'reshade/games' / (key(rom) + '.json')).get('release_id', '')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path('/userdata/system/ultimate-wine-toolbox'))
    parser.add_argument('command', choices=('versions', 'variants', 'info'))
    parser.add_argument('value', nargs='?')
    parser.add_argument('--rom', type=Path)
    args = parser.parse_args()
    entries = catalog()
    installed = current(args.home, args.rom) if args.rom else ''
    if args.command == 'versions':
        versions = sorted({e['version'] for e in entries}, key=lambda v: tuple(map(int, v.split('.'))), reverse=True)
        for version in versions:
            present = any(e['id'] == installed and e['version'] == version for e in entries)
            print(version + '\t' + str(int(present)))
    elif args.command == 'variants':
        for entry in entries:
            if entry['version'] == args.value:
                print('\t'.join((entry['id'], entry['variant'], entry['provider'], str(int(entry['id'] == installed)))))
    else:
        entry = selection(args.value, entries)
        print('\t'.join((entry['version'], entry['variant'], entry['backend_version'])))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        raise SystemExit(f'ReShade catalogue: {error}')
