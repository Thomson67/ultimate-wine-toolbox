"""Manage just two INI files alongside an existing injector, never its DLL/shaders."""
import hashlib
from pathlib import Path, PurePosixPath
import re

from reshade_manager import (atomic_bytes, directory_id, ensure_idle, key,
                             locations, read_json, safe_leaf, save_json, valid_rom)


def config_path(home, rom):
    return Path(home)/'reshade/existing-presets'/(key(rom)+'.json')


def targets(home, rom):
    import reshade_external
    cfg = reshade_external.scan_game(Path(home), Path(rom))
    return sorted({str(PurePosixPath(f['path']).parent) for f in reshade_external.game_files(cfg)})


def patch_ini(data, preset):
    text = data.decode('utf-8-sig')
    if '\0' in text: raise ValueError('Invalid ReShade configuration')
    lines = text.splitlines(); output = []; general = True; inserted = False
    for line in lines:
        section = re.match(r'^\s*\[([^]]+)\]', line)
        if section:
            general = section[1].casefold() == 'general'
            output.append(line)
            if general and not inserted:
                output.append('PresetPath=.\\'+preset); inserted = True
        elif general and re.match(r'^\s*PresetPath\s*=', line, re.I):
            continue
        else: output.append(line)
    if not inserted: output[:0] = ['[GENERAL]', 'PresetPath=.\\'+preset]
    return ('\n'.join(output)+'\n').encode()


def source_path(home, rom):
    return Path(home)/'reshade/existing-presets'/key(rom)/'preset.ini'


def journal_path(home, rom, root):
    return Path(home)/'reshade/existing-preset-journals'/key(rom)/(key(root)+'.json')


def current_bytes(path):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f'Expected a regular ReShade file: {path}')
    if not path.exists(): return None
    if path.stat().st_size > 2*1024*1024: raise ValueError('ReShade INI exceeds 2 MiB')
    return path.read_bytes()


def apply(home, rom, root, prefix, force=False):
    home, rom, root, prefix = map(Path, (home, rom, root, prefix))
    cfg = read_json(config_path(home, rom))
    if not cfg: return
    if root.is_symlink(): raise ValueError('Game/bottle root must be a real directory')
    ensure_idle(rom, root, prefix)
    jp = journal_path(home, rom, root); old = read_json(jp)
    if old and old.get('root_id') == directory_id(root) and not force: return
    if old and old.get('root_id') != directory_id(root): old = {}
    ini_rel = cfg['ini']
    preset_rel = (PurePosixPath(cfg['folder'])/cfg['filename']).as_posix()
    ini, preset = safe_leaf(root, ini_rel), safe_leaf(root, preset_rel)
    previous = {ini_rel: current_bytes(ini), preset_rel: current_bytes(preset)}
    base = previous[ini_rel]
    if base is None and rom.suffix.casefold() == '.wsquashfs' and cfg.get('archived_ini'):
        from community_reshade import read
        base = read(rom, ini_rel, True)
    updates = {ini_rel:patch_ini(base or b'', cfg['filename']), preset_rel:source_path(home, rom).read_bytes()}
    root.mkdir(parents=True, exist_ok=True)
    journal = old or {'rom':str(rom),'root':str(root),'prefix':str(prefix),'root_id':directory_id(root),'files':{}}
    backup_dir = jp.parent/(jp.stem+'-backups')
    for rel, data in updates.items():
        if rel not in journal['files']:
            backup = backup_dir/hashlib.sha256(rel.encode()).hexdigest()
            original = previous[rel]
            if original is not None: atomic_bytes(backup, original)
            journal['files'][rel] = {'backup':str(backup) if original is not None else '',
                                    'original':hashlib.sha256(original).hexdigest() if original is not None else None}
        journal['files'][rel]['installed'] = hashlib.sha256(data).hexdigest()
    # Recovery state exists before changing the game or OverlayFS upperdir.
    save_json(jp, journal)
    try:
        for rel, data in updates.items(): atomic_bytes(safe_leaf(root, rel), data)
    except OSError:
        for rel, data in previous.items():
            target = safe_leaf(root, rel)
            if data is None: target.unlink(missing_ok=True)
            else: atomic_bytes(target, data)
        raise


def configure(home, rom, folder, source, runner='', bottles=Path('/userdata/system/wine-bottles/windows'), legacy=False):
    home, rom, source = Path(home), Path(rom), Path(source); valid_rom(rom)
    from community_profiles import profile_bytes
    data = profile_bytes('reshade', source.read_bytes())
    if folder not in targets(home, rom): raise ValueError('Select a detected ReShade injector folder')
    if read_json(home/'reshade/games'/(key(rom)+'.json')): raise ValueError('Use the managed ReShade importer for this game')
    existing = read_json(config_path(home, rom))
    if existing and existing['folder'] != folder: raise ValueError('Restore the previous imported preset before changing injector folder')
    root, prefix = locations(rom, runner, bottles, legacy)
    from community_reshade import roots
    destinations = {str(root):(root,prefix)}
    if rom.suffix.casefold() == '.wsquashfs':
        for origin, extra in roots(rom, bottles):
            if origin.startswith('runtime:'): destinations[str(extra)] = (extra, extra)
    for current, pfx in destinations.values(): ensure_idle(rom, current, pfx)
    if rom.suffix.casefold() == '.wsquashfs':
        launcher = Path('/usr/bin/batocera-wine').read_text()
        if 'mount -t overlay' not in launcher or 'upperdir=' not in launcher:
            raise ValueError('This archive launcher does not support the ReShade preset overlay')
    from community_reshade import ini_paths
    configs = [p for p in ini_paths(rom, {folder}, rom.suffix.casefold() == '.wsquashfs')
               if str(PurePosixPath(p).parent) == folder and PurePosixPath(p).name.casefold() == 'reshade.ini']
    if len(configs) > 1: raise ValueError('Ambiguous ReShade.ini configuration names')
    ini = configs[0] if configs else (PurePosixPath(folder)/'ReShade.ini').as_posix()
    # Validate every existing destination before saving a persistent launch rule.
    for current, _ in destinations.values():
        base = current_bytes(safe_leaf(current, ini))
        if base is None and rom.suffix.casefold() == '.wsquashfs' and configs:
            from community_reshade import read
            base = read(rom, ini, True)
        current_bytes(safe_leaf(current, (PurePosixPath(folder)/('UWTCommunityPreset-'+key(rom)[:8]+'.ini')).as_posix()))
        patch_ini(base or b'', 'UWTCommunityPreset-'+key(rom)[:8]+'.ini')
    atomic_bytes(source_path(home, rom), data)
    save_json(config_path(home, rom), {'rom':str(rom),'folder':folder,'ini':ini,'archived_ini':bool(configs),'filename':'UWTCommunityPreset-'+key(rom)[:8]+'.ini'})
    for current, pfx in destinations.values(): apply(home, rom, current, pfx, force=True)
    return home/'reshade/existing-preset-journals'/key(rom)


def event(home, rom, action, runner='', bottles=Path('/userdata/system/wine-bottles/windows'), legacy=False):
    if not read_json(config_path(home, rom)): return
    root, prefix = locations(rom, runner, bottles, legacy)
    if action == 'gameStart': apply(home, rom, root, prefix)
    elif action == 'gameStop':
        cfg = read_json(config_path(home, rom)); jp = read_json(journal_path(home, rom, root))
        if jp.get('root_id') == directory_id(root):
            data = current_bytes(safe_leaf(root, (PurePosixPath(cfg['folder'])/cfg['filename']).as_posix()))
            if data is not None: atomic_bytes(source_path(home, rom), data)


def restore(home, rom):
    home, rom = Path(home), Path(rom); planned = []
    for jp in (home/'reshade/existing-preset-journals'/key(rom)).glob('*.json'):
        journal = read_json(jp); root = Path(journal['root'])
        ensure_idle(rom, root, Path(journal['prefix']))
        if directory_id(root) != journal['root_id']: continue
        for rel, record in journal['files'].items():
            target = safe_leaf(root, rel); data = current_bytes(target)
            sha = hashlib.sha256(data).hexdigest() if data is not None else None
            if sha not in (record['installed'], record['original']):
                raise ValueError(f'ReShade file was edited; backup retained: {target}')
            original = Path(record['backup']).read_bytes() if record['backup'] else None
            if original is not None and hashlib.sha256(original).hexdigest() != record['original']:
                raise ValueError('ReShade backup checksum mismatch; original files retained')
            planned.append((target, original))
    for target, original in planned:
        if original is None: target.unlink(missing_ok=True)
        else: atomic_bytes(target, original)
    config_path(home, rom).unlink(missing_ok=True)
    # Keep journals/backups as recovery copies; a new import takes a fresh baseline.
    for jp in (home/'reshade/existing-preset-journals'/key(rom)).glob('*.json'): jp.unlink()
