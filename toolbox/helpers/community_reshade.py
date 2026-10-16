"""Read shareable presets from managed, directory and archived ReShade games."""
import configparser
import hashlib
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import subprocess

from reshade_manager import (atomic_bytes, configured_games, export_preset, key, read_json,
                             relative, safe_leaf, source_header, valid_rom)

LIMIT = 2*1024*1024
SCAN_LIMIT = 32*1024*1024
BOTTLES = Path('/userdata/system/wine-bottles/windows')


def games(home, managed_only=False):
    return [(path, state) for path, state in configured_games(Path(home))
            if not managed_only or state in ('enabled', 'disabled')]


def roots(rom, bottles=None):
    bottles = Path(bottles) if bottles is not None else BOTTLES
    result = [('archive' if rom.suffix.casefold() == '.wsquashfs' else 'game', rom)]
    if rom.suffix.casefold() in ('.wsquashfs', '.pc') and bottles.is_dir():
        possible = [(rom.name, bottles/rom.name)]
        possible += [(runner.name, runner/(rom.name+'.wine')) for runner in bottles.iterdir()
                     if runner.is_dir() and not runner.is_symlink()]
        for label, path in possible:
            if path.is_dir() and not path.is_symlink(): result.append(('runtime:'+label, path))
    return result


def safe_relative(value):
    result = relative(value)
    if any(ord(c) < 32 or ord(c) == 127 for c in result): raise ValueError('Invalid preset path')
    return result


def ini_paths(root, folders, archive):
    """List only INI files near known injectors; never extract a game archive."""
    def accepted(path):
        parts = PurePosixPath(path).parts
        return (path.casefold().endswith('.ini') and
                not any(p.casefold() in ('windows', 'users', 'dosdevices') for p in parts) and
                any(folder == '.' or path.startswith(folder+'/') for folder in folders))
    if archive:
        with subprocess.Popen(['unsquashfs', '-ls', str(root)], stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, text=True) as process:
            for line in process.stdout:
                if not line.startswith('squashfs-root/'): continue
                path = line.rstrip('\n')[len('squashfs-root/'):]
                if accepted(path):
                    try: yield safe_relative(path)
                    except ValueError: continue
            if process.wait(): raise ValueError('Cannot list ReShade presets in the game archive')
    else:
        seen = set()
        for folder in folders:
            start = root if folder == '.' else root/folder
            if not start.is_dir() or start.is_symlink() or not start.resolve().is_relative_to(root.resolve()): continue
            for current, dirs, files in os.walk(start, followlinks=False):
                dirs[:] = [d for d in dirs if d.casefold() not in ('windows','users','dosdevices') and not (Path(current)/d).is_symlink()]
                for filename in files:
                    path = Path(current)/filename
                    if path.is_symlink(): continue
                    rel = path.relative_to(root).as_posix()
                    if rel in seen or not accepted(rel): continue
                    seen.add(rel)
                    try: yield safe_relative(rel)
                    except ValueError: continue


def read(root, rel, archive):
    if not archive:
        path = safe_leaf(root, rel)
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()): raise ValueError('Preset link escapes game')
        if path.stat().st_size > LIMIT: raise ValueError('Preset exceeds 2 MiB')
    data = source_header(root, rel, LIMIT+1)
    if len(data) > LIMIT: raise ValueError('Preset exceeds 2 MiB')
    return data


def preset_target(config, rel):
    """Resolve only a path inside the same game/prefix, without executing variables."""
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try: parser.read_string('[UWT_GLOBAL]\n'+config.decode('utf-8-sig'))
    except (ValueError, UnicodeError, configparser.Error): return None
    value = next((v for section in parser.sections() for k,v in parser.items(section)
                  if k.casefold() == 'presetpath'), '').strip().strip('"').replace('\\','/')
    if not value: return None
    if re.match(r'^[Cc]:/', value): value = 'drive_c/'+value[3:]
    elif re.match(r'^[A-Za-z]:|^/|^\$', value): return None
    else: value = posixpath.join(str(PurePosixPath(rel).parent), value)
    try: return safe_relative(posixpath.normpath(value))
    except ValueError: return None


def presets(home, rom, fr=True):
    home, rom = Path(home), Path(rom); valid_rom(rom)
    if read_json(home/'reshade/games'/(key(rom)+'.json')):
        return [{'id':'managed', 'label':'Preset actuel géré par la Toolbox' if fr else 'Current Toolbox-managed preset'}]
    import reshade_external
    cfg = reshade_external.scan_game(home, rom)
    folders = {str(PurePosixPath(f['path']).parent) for f in reshade_external.game_files(cfg)}
    if not folders: raise ValueError('No integrated ReShade injector detected for this game')
    result = []
    for origin, root in roots(rom):
        archive = origin == 'archive'
        paths = list(dict.fromkeys(ini_paths(root, folders, archive)))
        if len(paths) > 3000: raise ValueError('Too many INI files; choose a preset file manually')
        active = set(); values = {}; total = 0
        for rel in paths:
            try:
                data = read(root, rel, archive)
                total += len(data)
                if total > SCAN_LIMIT: raise RuntimeError('Too much INI data; choose a preset file manually')
                values[rel] = data
                target = preset_target(data, rel)
                if target: active.add(target)
            except (OSError, ValueError, subprocess.SubprocessError): continue
        for target in active - set(values):
            try:
                data = read(root, target, archive)
                total += len(data)
                if total > SCAN_LIMIT: raise RuntimeError('Too much INI data; choose a preset file manually')
                values[target] = data
            except (OSError, ValueError, subprocess.SubprocessError): continue
        for rel, data in values.items():
            try: text = data.decode('utf-8-sig')
            except UnicodeError: continue
            if not re.search(r'^\s*Techniques\s*=', text, re.M|re.I) or '\0' in text: continue
            name = ('Archive du jeu' if fr else 'Game archive') if archive else (
                'Jeu' if fr else 'Game') if origin == 'game' else (
                ('Réglages enregistrés — ' if fr else 'Saved settings — ')+origin.split(':',1)[1])
            if rel in active: name += ' — actif' if fr else ' — active'
            identifier = hashlib.sha256((str(root)+'\0'+rel).encode()).hexdigest()[:24]
            result.append({'id':identifier,'label':name+' : '+rel,'root':str(root),'path':rel,'archive':archive,'active':rel in active})
    return sorted(result, key=lambda item:(not item['active'], item['label'].casefold()))


def export(home, rom, identifier, destination):
    home, rom, destination = Path(home), Path(rom), Path(destination)
    if destination.is_symlink() or destination.suffix.casefold() != '.ini': raise ValueError('Choose a regular .ini export file')
    for _, root in roots(rom):
        if destination.resolve() == root.resolve() or (root.is_dir() and destination.resolve().is_relative_to(root.resolve())):
            raise ValueError('Export must be outside the original game and its runtime prefix')
    values = presets(home, rom)
    item = next((v for v in values if v['id'] == identifier), None)
    if item is None: raise ValueError('Preset list changed; select the preset again')
    if identifier == 'managed':
        export_preset(home, rom, destination, overwrite=True)
    else:
        atomic_bytes(destination, read(Path(item['root']), item['path'], item['archive']))
    return destination
