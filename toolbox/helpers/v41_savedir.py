#!/usr/bin/env python3
"""Experimental Batocera 41 save redirection for Wine prefixes and WSquashFS overlays."""
import argparse
import fnmatch
import os
from pathlib import Path
import shutil
import tempfile


def regular(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'expected a regular file: {path}')


def safe_parent(path, root):
    if not path.parent.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'path leaves its storage root: {path}')


def seed(source, target, root):
    """Populate missing external files; never overwrite an existing save."""
    safe_parent(target, root)
    if source.is_symlink() or target.is_symlink():
        raise ValueError(f'unexpected save link: {source} -> {target}')
    if source.is_dir():
        if target.exists() and not target.is_dir():
            raise ValueError(f'save file/directory conflict: {target}')
        target.mkdir(exist_ok=True)
        for child in source.iterdir():
            seed(child, target / child.name, root)
    else:
        regular(source)
        if target.exists():
            regular(target)
            return
        fd, tmp = tempfile.mkstemp(prefix='.uwt-v41-copy-', dir=target.parent)
        os.close(fd)
        try:
            shutil.copy2(source, tmp)
            os.replace(tmp, target)
        finally:
            Path(tmp).unlink(missing_ok=True)


def check_tree(source, target, root):
    safe_parent(target, root)
    if source.is_symlink() or target.is_symlink():
        raise ValueError(f'unexpected save link: {source} -> {target}')
    if source.is_dir():
        if target.exists() and not target.is_dir():
            raise ValueError(f'save file/directory conflict: {target}')
        for child in source.iterdir():
            check_tree(child, target / child.name, root)
    else:
        regular(source)
        if target.exists():
            regular(target)


def prepare(prefix, rom_name, save_root):
    prefix = Path(prefix).resolve(strict=True)
    if not prefix.is_dir() or not (prefix / 'drive_c').is_dir():
        raise ValueError('expected a Wine prefix')
    autorun = prefix / 'autorun.cmd'
    if not autorun.exists():
        return
    regular(autorun)
    values = {}
    for line in autorun.read_text(errors='surrogateescape').splitlines():
        key, sep, value = line.partition('=')
        if sep and key in ('SAVEDIR', 'SAVEFILES'):
            values.setdefault(key, value.strip())
    value = values.get('SAVEDIR', '')
    if not value:
        if values.get('SAVEFILES'):
            raise ValueError('SAVEFILES requires SAVEDIR')
        return
    relative = Path(value.strip('"').replace('\\', '/'))
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('SAVEDIR must be relative to the Wine prefix')
    if Path(rom_name).name != rom_name or not rom_name.endswith(('.wine', '.wsquashfs')):
        raise ValueError('only .wine and .wsquashfs are supported')
    save_root = Path(save_root)
    if save_root.is_symlink():
        raise ValueError('save root must be a real directory')
    save_root.mkdir(parents=True, exist_ok=True)
    save_root = save_root.resolve()
    external = save_root / rom_name.rsplit('.', 1)[0]
    if external.is_symlink() or (external.exists() and not external.is_dir()):
        raise ValueError('external saves must be a real directory')
    location = prefix / relative
    files = values.get('SAVEFILES', '')
    if not files:
        if relative == Path('.'):
            raise ValueError('redirecting the whole prefix requires SAVEFILES')
        safe_parent(location, prefix)
        if location.is_symlink():
            if location.resolve() != external.resolve():
                raise ValueError('existing SAVEDIR link points elsewhere')
            external.mkdir(exist_ok=True)
            return
        if location.exists() and not location.is_dir():
            raise ValueError('SAVEDIR must be a directory')
        # Only dedicated save folders may be redirected.
        if (relative.parts in (('drive_c',), ('drive_c', 'users'), ('drive_c', 'windows'))
                or (relative.parts[:2] == ('drive_c', 'users') and len(relative.parts) <= 3)):
            raise ValueError('SAVEDIR is a general Wine directory')
        resolved = location.resolve()
        if external.resolve().is_relative_to(resolved) or resolved.is_relative_to(external.resolve()):
            raise ValueError('local and external save directories overlap')
        if location.exists():
            check_tree(location, external, save_root)
        external.mkdir(exist_ok=True)
        if location.exists():
            seed(location, external, save_root)
            backup_root = external / '.uwt-v41-backups'
            if backup_root.is_symlink():
                raise ValueError('save backup directory must not be a link')
            backup_root.mkdir(exist_ok=True)
            backup = Path(tempfile.mkdtemp(prefix='savedir-', dir=backup_root)) / 'original'
            shutil.copytree(location, backup, symlinks=True)
            shutil.rmtree(location)
        location.parent.mkdir(parents=True, exist_ok=True)
        location.symlink_to(external, target_is_directory=True)
    else:
        if not location.resolve().is_relative_to(prefix):
            raise ValueError('SAVEFILES directory leaves the prefix')
        if location.is_symlink():
            raise ValueError('SAVEFILES directory must be real')
        patterns = files.split(';')
        if any(not p or '/' in p or '\\' in p or p in ('.', '..') for p in patterns):
            raise ValueError('SAVEFILES entries must be filenames in one directory')
        names = set()
        existing = {p.name for folder in (location, external) if folder.is_dir() for p in folder.iterdir()}
        for pattern in patterns:
            if any(c in pattern for c in '*?['):
                found = {name for name in existing if fnmatch.fnmatchcase(name, pattern)}
                if not found:
                    raise ValueError(f'SAVEFILES pattern matches no file: {pattern}')
                names.update(found)
            else:
                names.add(pattern)
        for name in names:
            source, target = location / name, external / name
            safe_parent(source, prefix)
            if source.is_symlink():
                if source.resolve() != target.resolve():
                    raise ValueError(f'existing SAVEFILES link points elsewhere: {source}')
            elif source.exists():
                regular(source)
            if target.exists() or target.is_symlink():
                regular(target)
        external.mkdir(exist_ok=True)
        location.mkdir(parents=True, exist_ok=True)
        backup_root = external / '.uwt-v41-backups'
        if backup_root.is_symlink():
            raise ValueError('save backup directory must not be a link')
        backup = None
        for name in sorted(names):
            source, target = location / name, external / name
            if source.is_symlink():
                continue
            if source.exists():
                seed(source, target, save_root)
                if backup is None:
                    backup_root.mkdir(exist_ok=True)
                    backup = Path(tempfile.mkdtemp(prefix='savefiles-', dir=backup_root))
                shutil.copy2(source, backup / name)
                source.unlink()
            source.symlink_to(target)
    print(f'Batocera 41 save compatibility: {rom_name} -> {external}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prefix', type=Path)
    parser.add_argument('rom_name')
    parser.add_argument('--save-root', type=Path, default=Path('/userdata/saves/windows'))
    args = parser.parse_args()
    try:
        prepare(args.prefix, args.rom_name, args.save_root)
    except (OSError, ValueError) as error:
        parser.exit(1, f'Batocera 41 save compatibility failed: {error}\n')
