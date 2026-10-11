#!/usr/bin/env python3
"""Index existing ReShade proxies; mask them reversibly without replacing renderers."""
import os
from pathlib import Path, PurePosixPath
import hashlib
import stat
import tempfile
import shutil
import subprocess
from reshade_manager import (atomic_bytes, directory_id, ensure_idle, key, locations, pe_arch,
                             read_json, relative, safe_leaf, save_json, source_header, valid_rom)

NAMES = {'dxgi.dll', 'd3d9.dll', 'd3d10.dll', 'd3d11.dll', 'opengl32.dll', 'ddraw.dll', 'd3d8.dll', 'reshade.dll', 'reshade32.dll', 'reshade64.dll'}


def game_files(cfg):
    """Exclude prefix-wide installer resources, also when reading old indexes.

    DLLs in ProgramData/ReShade do not establish injection into a game.
    Other ProgramData folders may contain actual game installations.
    """
    return [f for f in cfg.get('files', [])
            if tuple(p.casefold() for p in PurePosixPath(f['path']).parts[:3])
            != ('drive_c', 'programdata', 'reshade')]


def signature(rom):
    s = rom.stat()
    return [s.st_size, s.st_mtime_ns, s.st_ino]


def identify(data):
    try:
        arch = pe_arch(data)
    except ValueError:
        return None
    # ProductName alone also identifies the compiler. Require injector metadata.
    lower = data.lower()
    marker = "reshade post-processing injector"
    if marker.encode() not in lower and marker.encode('utf-16le') not in lower:
        return None
    return {'arch': arch, 'controllable': True}


def config_path(home, rom):
    return home / 'reshade/external' / (key(rom)+'.json')


def find_dlls(rom):
    if rom.suffix.casefold() == '.wsquashfs':
        with tempfile.TemporaryFile() as errors:
            proc = subprocess.Popen(['unsquashfs', '-ls', str(rom)], stdout=subprocess.PIPE,
                                    stderr=errors, text=True)
            with proc:
                for line in proc.stdout:
                    if line.startswith('squashfs-root/'):
                        path = line.strip()[len('squashfs-root/'):]
                        if PurePosixPath(path).name.casefold() in NAMES:
                            try:
                                yield relative(path)
                            except ValueError:
                                pass
                code = proc.wait()
                if code:
                    errors.seek(0)
                    detail = errors.read(4096).decode(errors='replace').strip()
                    raise ValueError(f'unsquashfs listing failed (exit {code}): {detail or "no diagnostic output"}')
    else:
        for folder, dirs, names in os.walk(rom, followlinks=False):
            dirs[:] = [name for name in dirs if name.casefold() not in ('windows', 'users', 'dosdevices')
                       and not (Path(folder)/name).is_symlink()]
            for name in names:
                path = Path(folder)/name
                if name.casefold() in NAMES and not path.is_symlink():
                    yield path.relative_to(rom).as_posix()


def scan_game(home, rom, force=False):
    if rom.is_symlink():
        raise ValueError(f'game path is a symbolic link: {rom} -> {os.readlink(rom)}; this scanner expects the original game path')
    if not rom.exists():
        raise FileNotFoundError(f'game path no longer exists: {rom}')
    valid_rom(rom)
    path = config_path(home, rom)
    old = read_json(path)
    if not force and rom.suffix.casefold() == '.wsquashfs' and old.get('signature') == signature(rom):
        filtered = game_files(old)
        if filtered != old.get('files', []):
            old['files'] = filtered
            save_json(path, old)
        return old
    found = []
    for rel in find_dlls(rom):
        if any(p.casefold() in ('windows', 'users', 'dosdevices') for p in PurePosixPath(rel).parts):
            continue
        try:
            dll = identify(source_header(rom, rel, 64*1024*1024))
            if dll:
                found.append(dict(dll, path=rel, controllable=PurePosixPath(rel).name.casefold() in {'dxgi.dll','d3d9.dll','d3d10.dll','d3d11.dll','opengl32.dll','ddraw.dll','d3d8.dll'}))
        except (OSError, ValueError):
            continue
    if old.get('controlled') and rom.suffix.casefold() != '.wsquashfs':
        # Disabled proxies are saved outside the game; keep their indexed paths.
        known = {f['path'] for f in found}
        found.extend(f for f in old.get('files', []) if f['path'] not in known)
    data = {'rom': str(rom), 'signature': signature(rom), 'files': found,
            'controlled': old.get('controlled', False), 'enabled': old.get('enabled', True)}
    data['files'] = game_files(data)
    save_json(path, data)
    return data


def state(cfg):
    files = game_files(cfg)
    if not files:
        return 'missing'
    if not all(f['controllable'] for f in files):
        return 'external-unsupported'
    return 'external-enabled' if cfg.get('enabled', True) else 'external-disabled'


def file_id(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISCHR(info.st_mode) and info.st_rdev == os.makedev(0, 0):
        return {'whiteout': True}
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f'unsupported ReShade file or link: {path}')
    return {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def restore(home, rom):
    for jp in (home/'reshade/external-journals'/key(rom)).glob('*.json'):
        j = read_json(jp)
        root, prefix = Path(j['root']), Path(j['prefix'])
        ensure_idle(rom, root, prefix)
        if directory_id(root) == j.get('root_id'):
            planned = []
            for rel, rec in j['files'].items():
                target = safe_leaf(root, rel)
                current = file_id(target)
                if current not in (rec['disabled'], rec['original']):
                    raise ValueError(f'ReShade DLL changed; recovery preserved: {target}')
                backup = Path(rec['backup']) if rec['backup'] else None
                if backup and file_id(backup) != rec['original']:
                    raise ValueError('original ReShade backup missing or changed')
                planned.append((target, backup))
            for target, backup in planned:
                if backup:
                    atomic_bytes(target, backup.read_bytes())
                else:
                    target.unlink(missing_ok=True)
        jp.unlink()
        shutil.rmtree(jp.parent/(jp.stem+'-backups'), ignore_errors=True)


def apply(home, rom, runner='', bottles=Path('/userdata/system/wine-bottles/windows'), legacy=False, desired=None):
    cfg = desired if desired is not None else read_json(config_path(home, rom))
    if not cfg.get('controlled'):
        return
    if cfg.get('enabled'):
        restore(home, rom)
        return
    if not cfg.get('files') or not all(f['controllable'] for f in cfg['files']):
        raise ValueError('existing ReShade proxy cannot be safely masked')
    root, prefix = locations(rom, runner, bottles, legacy)
    ensure_idle(rom, root, prefix)
    if root.is_symlink():
        raise ValueError('game/bottle root must be a real directory')
    # Batocera mounts this per-runner directory as OverlayFS upperdir.
    # A 0:0 whiteout hides an archived DLL; deleting it restores the lower DLL.
    archived = rom.suffix.casefold() == '.wsquashfs'
    if archived:
        launcher = Path('/usr/bin/batocera-wine').read_text()
        if 'mount -t overlay' not in launcher or 'upperdir=' not in launcher:
            raise ValueError('this Batocera archive launcher is not supported')
    root.mkdir(parents=True, exist_ok=True)
    root_id = directory_id(root)
    ident = key(str(root)+'|'+str(root_id))
    jp = home/'reshade/external-journals'/key(rom)/(ident+'.json')
    j = read_json(jp, {'rom':str(rom),'root':str(root),'prefix':str(prefix),'root_id':root_id,'files':{}})
    backups = jp.parent/(jp.stem+'-backups')
    staged = []
    try:
        for f in cfg['files']:
            rel = relative(f['path']); target = safe_leaf(root, rel)
            current = file_id(target); rec = j['files'].get(rel)
            disabled = {'whiteout':True} if archived else None
            if rec:
                if current == rec['disabled']:
                    continue
                if current != rec['original']:
                    raise ValueError(f'ReShade DLL changed; backup retained: {target}')
            else:
                if current and (current.get('whiteout') or not identify(target.read_bytes())):
                    raise ValueError(f'local DLL does not match indexed ReShade: {target}')
                if current is None and not archived:
                    raise ValueError(f'indexed ReShade is missing: {target}')
                backups.mkdir(parents=True, exist_ok=True)
                backup = backups/hashlib.sha256(rel.encode()).hexdigest() if current else None
                if backup:
                    atomic_bytes(backup, target.read_bytes())
                rec={'original':current,'backup':str(backup) if backup else '', 'disabled':disabled}
                j['files'][rel]=rec
            temporary = None
            if archived:
                target.parent.mkdir(parents=True, exist_ok=True)
                fd, name = tempfile.mkstemp(prefix='.uwt-whiteout-',dir=target.parent)
                os.close(fd); os.unlink(name)
                try:
                    os.mknod(name, stat.S_IFCHR | 0o600, os.makedev(0,0))
                except OSError as error:
                    raise ValueError('cannot create OverlayFS whiteout; existing ReShade preserved') from error
                temporary = Path(name)
            staged.append((target, temporary))
        # Journal all originals before changing any DLL. Preserve shaders/INI files.
        save_json(jp,j)
        for target, temporary in staged:
            if temporary:
                os.replace(temporary,target)
            else:
                target.unlink()
    finally:
        for _, temporary in staged:
            if temporary:
                temporary.unlink(missing_ok=True)


def release(home, rom):
    restore(home, rom)
    cfg = read_json(config_path(home, rom))
    if cfg:
        cfg.update(controlled=False, enabled=True)
        save_json(config_path(home,rom),cfg)


def toggle(home, rom, enabled, runner='', bottles=Path('/userdata/system/wine-bottles/windows'), legacy=False):
    cfg = scan_game(home,rom,force=True)
    if not cfg['files'] or not all(f['controllable'] for f in cfg['files']):
        raise ValueError('nonstandard ReShade loader: listed, but cannot be toggled safely')
    cfg.update(controlled=True,enabled=enabled)
    apply(home,rom,runner,bottles,legacy,desired=cfg)
    save_json(config_path(home,rom),cfg)
