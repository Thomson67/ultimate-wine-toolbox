#!/usr/bin/env python3
"""Versioned, separate ReShade payloads; shader/ compiler setup stays upstream."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import struct
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
    providers = {
        'fienestar/OverlayDisabledReShade', 'ovitus/OverlayDisabledReShade',
        'Knitby/OverlayDisabledReShade', 'Adam-Darlow/OverlayDisabledReShade',
        'AndrewGDX/OverlayDisabledReShade', 'altes21/OverlayDisabledReShade',
        'mjd4219/reshade-no-intro',
    }
    for entry in entries:
        if (not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9]+(?:-[a-z0-9]+)*)?', entry['id'])
                or entry['id'] in seen or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', entry['version'])
                or entry['variant'] not in ('standard', 'standard-addons', 'no-startup-banner')
                or not re.fullmatch(r'[a-f0-9]{64}', entry['sha256'])
                or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', entry['backend_version'])):
            raise ValueError('invalid ReShade catalogue entry')
        if entry['variant'] in ('standard', 'standard-addons'):
            addons = entry['variant'] == 'standard-addons'
            if addons and tuple(map(int, entry['version'].split('.'))) < (5, 0, 0):
                raise ValueError('full add-ons require ReShade 5.0 or newer')
            expected = entry['version'] + ('-addons' if addons else '')
            url = f'https://reshade.me/downloads/ReShade_Setup_{entry["version"]}' + ('_Addon.exe' if addons else '.exe')
            if entry['provider'] != 'crosire/reshade' or entry['url'] != url:
                raise ValueError('unexpected ReShade download source')
        else:
            if entry['provider'] not in providers:
                raise ValueError('unexpected ReShade download source')
            owner = entry['provider'].split('/')[0].lower()
            expected = entry['version'] + ('' if owner == 'fienestar' else '-' + owner) + '-no-startup-banner'
            tag = entry.get('tag', 'v' + entry['version'] + '-patched')
            asset = entry.get('asset', 'ReShade.Setup.exe')
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', tag) or not re.fullmatch(r'[A-Za-z0-9_.-]+\.(?:exe|zip)', asset):
                raise ValueError('invalid ReShade release asset')
            url = f'https://github.com/{entry["provider"]}/releases/download/{tag}/{asset}'
            if entry['url'] != url:
                raise ValueError('unexpected ReShade download source')
        if entry['id'] != expected:
            raise ValueError('inconsistent ReShade version/variant/provider')
        containers = entry.get('containers', [])
        if not isinstance(containers, list) or len(containers) > 2 or any(
                not isinstance(n, str) or not re.fullmatch(r'[A-Za-z0-9_. /-]+', n)
                or n.startswith('/') or '..' in n.split('/') for n in containers):
            raise ValueError('invalid nested ReShade container')
        for name in ('dll_sha256', 'binary_versions'):
            if name in entry:
                pattern = r'[a-f0-9]{64}' if name == 'dll_sha256' else re.escape(entry['version']) + r'\.[0-9]+'
                if set(entry[name]) != {'32', '64'} or any(not re.fullmatch(pattern, v) for v in entry[name].values()):
                    raise ValueError('invalid ReShade binary verification data')
        seen.add(entry['id'])
    return entries


def selection(identity, entries=None):
    for entry in catalog() if entries is None else entries:
        if entry['id'] == identity:
            return entry
    raise ValueError(f'unknown ReShade release: {identity}')


def supports_api(entry, api):
    # Vulkan DLLs/manifests first appeared in the official 4.4.0 setup.
    return api != 'vulkan' or tuple(map(int, entry['version'].split('.'))) >= (4, 4, 0)


def download(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Ultimate-Wine-Toolbox'})
    with urllib.request.urlopen(request, timeout=45) as response:
        data = response.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError('ReShade setup exceeds download limit')
    return data


def binary_matches(content, entry, bits):
    expected_hash = entry.get('dll_sha256', {}).get(str(bits))
    if expected_hash and hashlib.sha256(content).hexdigest() != expected_hash:
        return False
    expected_version = entry.get('binary_versions', {}).get(str(bits))
    if expected_version:
        versions = []
        for match in re.finditer(b'\xbd\x04\xef\xfe\x00\x00\x01\x00', content):
            if match.start() + 16 > len(content):
                continue
            ms, ls = struct.unpack_from('<II', content, match.start() + 8)
            versions.append('.'.join(map(str, (ms >> 16, ms & 65535, ls >> 16, ls & 65535))))
        if versions != [expected_version]:
            return False
    return True


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
                 and pe_arch(path.read_bytes()) == bits
                 and binary_matches(path.read_bytes(), entry, bits))
    if valid:
        return target / f'ReShade{arch}.dll'
    data = fetch(entry['url'])
    if len(data) > LIMIT or hashlib.sha256(data).hexdigest() != entry['sha256']:
        raise ValueError('ReShade setup checksum mismatch; existing installation preserved')
    for name in entry.get('containers', []):
        with zipfile.ZipFile(io.BytesIO(data)) as outer:
            if outer.namelist().count(name) != 1 or outer.getinfo(name).file_size > LIMIT:
                raise ValueError('missing, duplicated or oversized ReShade container')
            data = outer.read(name)
    payloads = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for bits in (32, 64):
            name = f'ReShade{bits}.dll'
            if archive.namelist().count(name) != 1 or archive.getinfo(name).file_size > LIMIT:
                raise ValueError('missing, duplicated or oversized ReShade DLL')
            content = archive.read(name)
            if pe_arch(content) != bits:
                raise ValueError('wrong ReShade DLL architecture')
            if not binary_matches(content, entry, bits):
                raise ValueError('ReShade DLL version or checksum mismatch')
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
                                 addon_support=entry.get('addon_support', 'restricted'),
                                 source_available=entry.get('source_available', True),
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
    parser.add_argument('--api', choices=('dxgi', 'd3d9', 'opengl32', 'vulkan'), default='dxgi')
    args = parser.parse_args()
    entries = [entry for entry in catalog() if supports_api(entry, args.api)]
    installed = current(args.home, args.rom) if args.rom else ''
    if args.command == 'versions':
        versions = sorted({e['version'] for e in entries}, key=lambda v: tuple(map(int, v.split('.'))), reverse=True)
        for version in versions:
            present = any(e['id'] == installed and e['version'] == version for e in entries)
            no_banner = any(e['version'] == version and e['variant'] == 'no-startup-banner' for e in entries)
            print('\t'.join((version, str(int(present)), str(int(no_banner)))))
    elif args.command == 'variants':
        for entry in sorted(entries, key=lambda e: {'standard': 0, 'standard-addons': 1, 'no-startup-banner': 2}[e['variant']]):
            if entry['version'] == args.value:
                print('\t'.join((entry['id'], entry['variant'], entry['provider'], str(int(entry['id'] == installed)),
                                 ','.join(note for note, condition in (
                                     ('full-addons', entry.get('addon_support') == 'full' and entry['variant'] != 'standard-addons'),
                                     ('binary-archive', entry.get('source_available') is False),
                                     ('older-gui', entry.get('source_note') == 'gui-6.4.1')) if condition))))
    else:
        entry = selection(args.value, entries)
        print('\t'.join((entry['version'], entry['variant'], entry['backend_version'])))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        raise SystemExit(f'ReShade catalogue: {error}')
