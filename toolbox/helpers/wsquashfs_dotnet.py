#!/usr/bin/env python3
"""Inspect and manage .NET in a working bottle, never in Batocera or runners."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import urllib.request

import wsquashfs_winetricks as tricks
from wsquashfs_update import game_directory
from wsquashfs_dotnet_storage import stage, publish, filesystem, exchange_probe


def microsoft_clr_files(prefix, win32=False):
    """Require Microsoft PE loaders and CLR libraries, not just registry labels."""
    paths = ['system32/mscoree.dll', 'Microsoft.NET/Framework/v4.0.30319/clr.dll']
    if not win32:
        paths += ['syswow64/mscoree.dll', 'Microsoft.NET/Framework64/v4.0.30319/clr.dll']
    result = {}
    for relative in paths:
        path = prefix / 'drive_c/windows' / relative
        try:
            if not path.resolve().is_relative_to(prefix.resolve()):
                raise ValueError('external DLL')
            data = path.read_bytes()
            offset = int.from_bytes(data[60:64], 'little')
            result[relative] = (data[:2] == b'MZ' and offset >= 64
                and data[offset:offset + 4] == b'PE\0\0'
                and 'Microsoft Corporation'.encode('utf-16le') in data
                and b'WINE_MONO_OVERRIDES' not in data
                and b'Wine builtin DLL' not in data)
        except (OSError, ValueError):
            result[relative] = False
    return result


def inspect(prefix, shared_roots=None):
    if prefix.is_symlink() or not (prefix / 'drive_c/windows').is_dir():
        raise ValueError('Expected an initialized working prefix')
    text = (prefix / 'system.reg').read_text(errors='replace')
    entries = []
    for section in re.split(r'(?m)^\[', text)[1:]:
        if 'uninstall' not in section.splitlines()[0].lower():
            continue
        values = dict(re.findall(r'^"(DisplayName|DisplayVersion)"="(.*?)"$', section, re.M))
        if values.get('DisplayName'):
            entries.append(values)
    mono = [e for e in entries if e['DisplayName'].startswith('Wine Mono')]
    native = [e for e in entries if re.search(r'Microsoft.*\.NET Framework', e['DisplayName'], re.I)]
    marker = (prefix / 'drive_c/windows/dotnet48.installed.workaround').is_file()
    ndp = any('NET Framework Setup' in section.splitlines()[0] and
              re.search(r'^"Release"=dword:', section, re.M)
              for section in re.split(r'(?m)^\[', text)[1:])
    # Mono also registers NDP values. A Release value alone is not proof of
    # native .NET, but blocks blindly installing Mono when its origin is unclear.
    status = 'mixed' if mono and (native or marker) else (
        'microsoft' if native or marker else 'mono' if mono else 'uncertain' if ndp else 'absent')
    support_only = bool(mono) and all(e['DisplayName'] == 'Wine Mono Windows Support' for e in mono)
    clr = microsoft_clr_files(prefix, '#arch=win32' in text) if marker and native else {}
    # Old MSI Support registrations can survive Mono removal. Keep them visible,
    # but do not treat them as an active Mono runtime when Microsoft's loader,
    # CLR files, 4.8 identity and Winetricks marker are all present.
    support_residue = bool(support_only and marker and clr and all(clr.values())
        and any(re.search(r'\.NET Framework 4\.8(?:\D|$)', e['DisplayName'], re.I) for e in native))
    if support_residue:
        status = 'microsoft'
    roots = shared_roots if shared_roots is not None else [
        Path('/usr/share/wine'), *Path('/usr/wine').glob('*/share/wine')]
    shared = []
    for root in roots:
        for pattern in ('wine-mono-*', 'mono/wine-mono-*'):
            shared.extend(str(p) for p in root.glob(pattern) if p.is_dir())
    return dict(status=status, mono=mono, microsoft=native,
                dotnet48_marker=marker, ndp_release=ndp, shared=sorted(set(shared)),
                mono_support_residue=support_residue, microsoft_clr_files=clr)


def prefix_fingerprint(prefix, game_relative):
    """Compare a retained install's original snapshot without reading game data."""
    result = {}
    for directory, dirs, files in os.walk(prefix, followlinks=False):
        root = Path(directory)
        dirs[:] = [name for name in dirs if (root / name).relative_to(prefix) != game_relative]
        for name in dirs + files:
            path = root / name
            relative = path.relative_to(prefix).as_posix()
            if path.is_symlink():
                result[relative] = ('link', os.readlink(path))
            elif path.is_dir():
                result[relative] = ('directory',)
            elif path.is_file():
                with path.open('rb') as stream:
                    result[relative] = ('file', hashlib.file_digest(stream, 'sha256').hexdigest())
            else:
                raise ValueError(f'Unsupported prefix entry: {path}')
    return result


def recover(prefix, staged, snapshot, backups, work_root):
    """Publish an already installed .NET 4.8 copy after strict validation."""
    if (staged.is_symlink() or staged.parent.is_symlink()
            or staged.resolve().parent.parent != work_root.resolve()
            or not staged.parent.name.startswith('install-') or staged.name != prefix.name):
        raise ValueError('Expected a retained Toolbox installer copy for this prefix')
    if snapshot.is_symlink() or not snapshot.resolve().is_relative_to(backups.resolve()):
        raise ValueError('Expected the original Toolbox backup')
    game = game_directory(prefix)
    relative = game.relative_to(prefix)
    metadata = json.loads((snapshot / 'backup.json').read_text())
    if metadata.get('prefix') != str(prefix.resolve()) or metadata.get('excluded_game') != str(relative):
        raise ValueError('Backup does not belong to this prefix/game')
    original_root = snapshot / 'prefix'
    if original_root.is_symlink() or not (original_root / 'drive_c/windows').is_dir():
        raise ValueError('Original backup prefix is missing or invalid')
    if (staged / relative).exists() or (staged / relative).is_symlink():
        raise ValueError('Installer copy unexpectedly contains game data')
    for root in (prefix, staged):
        tricks.prepare(root, detach=False)
    state = inspect(staged)
    print('dotnet_recovery_state=' + json.dumps(state), flush=True)
    if (state['status'] != 'microsoft' or not state['dotnet48_marker']
            or not state['microsoft_clr_files'] or not all(state['microsoft_clr_files'].values())
            or not any(re.search(r'\.NET Framework 4\.8(?:\D|$)', e['DisplayName'], re.I) for e in state['microsoft'])):
        raise ValueError('Retained copy does not contain confirmed Microsoft .NET 4.8 files')
    original = prefix_fingerprint(original_root, relative)
    if prefix_fingerprint(prefix, relative) != original:
        raise ValueError('Working prefix changed since the installation backup; recovery refused')
    if (staged / 'autorun.cmd').read_bytes() != (prefix / 'autorun.cmd').read_bytes():
        raise ValueError('Installer copy has a different game configuration')
    backup(prefix, backups)
    for root in (prefix, staged):
        tricks.prepare(root, detach=False)
    publish(staged, prefix, game)
    # Keep the retained copy available for diagnosis after manual recovery.
    print('dotnet_recovered=' + str(prefix), flush=True)
    print(json.dumps(inspect(prefix), ensure_ascii=False, indent=2), flush=True)


def latest_asset(data):
    tag = data.get('tag_name', '')
    if data.get('prerelease') or not re.fullmatch(r'wine-mono-\d+\.\d+\.\d+', tag):
        raise ValueError('Invalid Wine Mono release')
    name = tag + '-x86.msi'  # The x86 MSI also includes x86-64 support.
    for asset in data.get('assets', []):
        if asset.get('name') == name:
            digest = asset.get('digest', '') or ''
            expected_url = f'https://github.com/wine-mono/wine-mono/releases/download/{tag}/{name}'
            if asset.get('browser_download_url') != expected_url or not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
                raise ValueError('Wine Mono asset has no trusted SHA-256 digest')
            return tag.removeprefix('wine-mono-'), expected_url, digest[7:]
    raise ValueError('No x86 Wine Mono MSI in release')


def fetch_mono(cache):
    def request(url):
        return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Ultimate-Wine-Toolbox'}), timeout=60)
    with request('https://api.github.com/repos/wine-mono/wine-mono/releases/latest') as response:
        version, url, digest = latest_asset(json.load(response))
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / f'wine-mono-{version}-x86.msi'
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
        return version, target
    with tempfile.NamedTemporaryFile(dir=cache, delete=False) as out:
        temporary = Path(out.name)
        try:
            with request(url) as response:
                shutil.copyfileobj(response, out)
            out.close()
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
                raise ValueError('Wine Mono download checksum mismatch')
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    return version, target


def backup(prefix, destination):
    root = prefix.resolve()
    if destination.resolve().is_relative_to(root):
        raise ValueError('Backup must be outside the working prefix')
    game = game_directory(prefix)
    destination.mkdir(parents=True, exist_ok=True)
    snapshot = Path(tempfile.mkdtemp(prefix='dotnet-', dir=destination))
    def ignore(folder, names):
        return [game.name] if Path(folder) == game.parent else []
    try:
        shutil.copytree(prefix, snapshot / 'prefix', symlinks=True, ignore=ignore)
        (snapshot / 'backup.json').write_text(json.dumps(dict(prefix=str(root), excluded_game=str(game.relative_to(prefix))), indent=2))
    except BaseException:
        shutil.rmtree(snapshot)
        raise
    print(f'backup={snapshot}', flush=True)
    return snapshot


def restore(prefix, snapshot, backups):
    if snapshot.is_symlink() or not snapshot.resolve().is_relative_to(backups.resolve()):
        raise ValueError('Expected a snapshot from the Toolbox backup directory')
    data = json.loads((snapshot / 'backup.json').read_text())
    game = game_directory(prefix)
    if data.get('prefix') != str(prefix.resolve()) or data.get('excluded_game') != str(game.relative_to(prefix)):
        raise ValueError('Snapshot does not belong to this working prefix/game directory')
    source = snapshot / 'prefix'
    if source.is_symlink() or not (source / 'system.reg').is_file():
        raise ValueError('Snapshot prefix is missing or invalid')
    tricks.prepare(prefix, detach=False)
    backup(prefix, backups)  # Preserve the current state before explicit recovery.
    publish(source, prefix, game)
    print(f'dotnet_restored_snapshot={snapshot}', flush=True)


def change(prefix, action, backups, cache, work_root=None):
    state = inspect(prefix)
    print('dotnet_initial_state=' + json.dumps(state, ensure_ascii=False), flush=True)
    if state['status'] in ('mixed', 'uncertain'):
        raise ValueError('Ambiguous .NET state; inspect the prefix before changing it')
    if state['status'] == 'microsoft':
        raise ValueError('Microsoft .NET is already detected; no automatic replacement')
    for name in ('Program Files', 'Program Files (x86)', 'ProgramData'):
        directory = prefix / 'drive_c' / name
        if directory.is_symlink():
            raise ValueError(f'Installer directory must not point outside the prefix: {directory}')
    version = package = None
    if action == 'mono':
        version, package = fetch_mono(cache)  # Download before modifying the bottle.
        installed = [e.get('DisplayVersion', '') for e in state['mono'] if e['DisplayName'] in ('Wine Mono Runtime', 'Wine Mono')]
        if any(re.fullmatch(r'\d+\.\d+\.\d+', v) and tuple(map(int, v.split('.'))) >= tuple(map(int, version.split('.'))) for v in installed):
            print('Wine Mono already up to date', flush=True)
            return
    tricks.prepare(prefix, detach=False)  # Refuse running prefixes; leave source DLLs intact.
    game = game_directory(prefix)
    print(f'dotnet_source_filesystem={filesystem(prefix)} exchange_errno={exchange_probe(prefix)}', flush=True)
    snapshot = backup(prefix, backups)
    local_root = work_root or Path(os.environ.get('UWT_DOTNET_WORK_ROOT', str(cache.parent.parent / 'state/dotnet-work')))
    staged = stage(prefix, game, local_root)
    try:
        tricks.prepare(staged)
        if action == 'microsoft':
            rc = tricks.install(staged, ['remove_mono', 'dotnet48'], native_runner=True, unattended=False, mono_cleanup=True)
            after = inspect(staged)
            print('dotnet_installed_state=' + json.dumps(after), flush=True)
            if rc or after['status'] != 'microsoft' or not after['dotnet48_marker']:
                raise ValueError(f'.NET Framework installation incomplete (rc={rc})')
        else:
            # Wine's Unix namespace also works when sandboxing removed Z:.
            (staged / 'drive_c/windows/temp').mkdir(exist_ok=True)
            rc = tricks.install(staged, ['msiexec', '/i', '//?/unix' + str(package.resolve()),
                '/norestart', '/l*vx', 'C:\\windows\\temp\\uwt-mono-install.log'], wine_command=True, native_runner=True, unattended=False)
            after = inspect(staged)
            print('dotnet_installed_state=' + json.dumps(after), flush=True)
            if rc or not any(e.get('DisplayVersion') == version for e in after['mono']):
                raise ValueError(f'Wine Mono installation not confirmed (rc={rc})')
        tricks.prepare(staged, detach=False)  # No installer process may remain active.
        tricks.prepare(prefix, detach=False)  # Refuse publication if the game was started meanwhile.
        publish(staged, prefix, game)
    except (OSError, ValueError) as error:
        raise ValueError(f'{error}; installer copy retained: {staged}; backup={snapshot}') from error
    shutil.rmtree(staged.parent)
    print(json.dumps(inspect(prefix), ensure_ascii=False, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('inspect', 'mono', 'microsoft', 'restore', 'backups', 'recover'))
    parser.add_argument('prefix', type=Path)
    parser.add_argument('--backups', type=Path)
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--runner-root', type=Path)
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--staged', type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'inspect':
            roots = [Path('/usr/share/wine'), *Path('/usr/wine').glob('*/share/wine')]
            if args.runner_root:
                roots.extend(args.runner_root / p for p in ('share/wine', 'files/share/wine', 'dist/share/wine'))
            print(json.dumps(inspect(args.prefix, roots), ensure_ascii=False, indent=2))
        elif args.action == 'backups':
            if args.backups is None:
                raise ValueError('Backup directory required')
            for snapshot in sorted(args.backups.glob('dotnet-*'), key=lambda p: p.stat().st_mtime):
                try:
                    data = json.loads((snapshot / 'backup.json').read_text())
                    if data.get('prefix') == str(args.prefix.resolve()):
                        print(snapshot.name)
                except (OSError, ValueError):
                    pass
        elif args.action == 'recover':
            if args.backups is None or args.snapshot is None or args.staged is None or args.cache is None:
                raise ValueError('Backup, retained copy and cache paths required')
            work_root = Path(os.environ.get('UWT_DOTNET_WORK_ROOT', str(args.cache.parent.parent / 'state/dotnet-work')))
            recover(args.prefix, args.staged, args.snapshot, args.backups, work_root)
        elif args.action == 'restore':
            if args.backups is None or args.snapshot is None:
                raise ValueError('Backup directory and snapshot required')
            restore(args.prefix, args.snapshot, args.backups)
        else:
            if args.backups is None or args.cache is None:
                raise ValueError('Backup and cache directories are required')
            change(args.prefix, args.action, args.backups, args.cache)
        return 0
    except (OSError, ValueError) as error:
        print(f'.NET: {error}', flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
