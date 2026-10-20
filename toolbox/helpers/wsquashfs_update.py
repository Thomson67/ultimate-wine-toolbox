#!/usr/bin/env python3
"""Prepare an isolated game update; preserve launch directives and commit safely."""
import argparse
import errno
import fnmatch
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from mergerfs_move import MoveRecoveryRequired, rename_in_branches


def game_name(name):
    for suffix in ('.wsquashfs', '.wine', '.pc'):
        if name.casefold().endswith(suffix):
            name = name[:-len(suffix)]
            break
    name = re.sub(r'(?:\s*\[[^\[\]]*\])+\s*$', '', name)
    return ' '.join(name.split()).casefold()


def update_listing(directory, kind, preferred='', exclude=''):
    """One shallow scan: prefer exact names; suggest first-word matches only as fallback."""
    entries = list(os.scandir(directory))
    ignored = {'media', 'medias', 'médias', 'image', 'images', 'video', 'videos', 'vidéos',
               'manual', 'manuals', 'music', 'musiques', 'marquee', 'marquees', 'thumbnail',
               'thumbnails', 'screenshot', 'screenshots', 'fanart', 'fanarts', 'boxart',
               'boxarts', 'boxback', 'boxbacks', 'wheel', 'wheels', 'mix', 'mixes',
               'titleshot', 'titleshots', 'cover', 'covers', 'snap', 'snaps',
               'downloaded_images', 'downloaded_videos'}
    folders = [entry for entry in entries if entry.is_dir(follow_symlinks=False)
               and not entry.name.startswith('.') and entry.name.casefold() not in ignored]
    names = {game_name(entry.name) for entry in folders}
    candidates = folders if kind == 'sources' else [entry for entry in entries
        if entry.is_file(follow_symlinks=False) and entry.name.casefold().endswith('.wsquashfs')]
    if kind == 'bases':
        candidates += [entry for entry in folders if entry.name.casefold().endswith('.wine')
                       and (Path(entry.path) / 'system.reg').is_file()
                       and (Path(entry.path) / 'autorun.cmd').is_file()
                       and (Path(entry.path) / 'drive_c').is_dir()]
    candidates = [entry for entry in candidates if entry.path != exclude]
    reference_names = {game_name(preferred)} if kind == 'sources' else names
    reference_names.discard('')
    first_words = {name.split()[0] for name in reference_names}
    use_first_word = not any(game_name(entry.name) in reference_names for entry in candidates)

    def rank(entry):
        name = game_name(entry.name)
        if name and name in reference_names:
            return 0
        if use_first_word and name and name.split()[0] in first_words:
            return 1
        return 2

    candidates.sort(key=lambda entry: (rank(entry), entry.name.casefold(), entry.path))
    return [(entry.path, rank(entry) < 2) for entry in candidates]


def ensure_root_alias(prefix):
    root = prefix.resolve(strict=True)
    users = root / 'drive_c/users'
    if not users.resolve().is_relative_to(root):
        raise ValueError('Wine users directory escapes the prefix')
    users.mkdir(parents=True, exist_ok=True)
    steam = users / 'steamuser'
    alias = users / 'root'
    if steam.is_symlink():
        # Older prefixes use the opposite alias. Move the real profile without
        # copying or following its save links, then recreate the canonical alias.
        if (alias.is_symlink() or not alias.is_dir()
                or steam.resolve() != alias.resolve()):
            raise ValueError('steamuser must be an internal real directory or a link to the root profile')
        original = os.readlink(steam)
        steam.unlink()
        try:
            alias.rename(steam)
        except OSError:
            steam.symlink_to(original, target_is_directory=True)
            raise
        alias.symlink_to('steamuser', target_is_directory=True)
        return
    if steam.exists() and not steam.is_dir():
        raise ValueError('steamuser must be an internal real directory')
    if alias.is_symlink() and alias.resolve() == steam.resolve():
        steam.mkdir(exist_ok=True)
        return
    if not steam.exists() and alias.is_dir() and not alias.is_symlink():
        alias.rename(steam)  # No copy is needed if only root exists.
    else:
        steam.mkdir(exist_ok=True)
        if alias.is_symlink() or alias.is_file():
            alias.unlink()
        elif alias.exists():
            shutil.rmtree(alias)  # Do not follow save links inside the old profile.
    alias.symlink_to('steamuser', target_is_directory=True)


def signature(path):
    st = path.stat()
    return [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns]


def save_json(path, data):
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)


def directives(prefix):
    path = prefix / 'autorun.cmd'
    if path.is_symlink():
        raise ValueError('autorun.cmd must be an internal regular file')
    text = path.read_text(encoding='utf-8', errors='surrogateescape') if path.exists() else ''
    values = {}
    for line in text.splitlines():
        if '=' in line and not line.lstrip().startswith(('#', ';')):
            key, value = line.split('=', 1)
            values[key.strip().upper()] = value.strip()
    return text, values


def relative_path(value):
    value = value.strip().strip('"').replace('\\', '/').rstrip('/') or '.'
    path = Path(value)
    if path.is_absolute() or '..' in path.parts or any(c in value for c in '\t\n\r'):
        raise ValueError('save path must stay inside the prefix')
    return path


def validate_source(source, prefix):
    source = source.resolve(strict=True)
    prefix = prefix.resolve(strict=True)
    if not source.is_dir() or source == Path('/'):
        raise ValueError('choose a game-content directory')
    if source.is_relative_to(prefix) or prefix.is_relative_to(source):
        raise ValueError('source and working prefix must not overlap')
    if (source / 'drive_c').is_dir() and (source / 'system.reg').exists():
        raise ValueError('choose drive_c/game rather than a full Wine prefix')
    if not any(source.iterdir()):
        raise ValueError('the replacement directory is empty')
    for root, dirs, files in os.walk(source, followlinks=False):
        for name in dirs + files:
            path = Path(root) / name
            if path.is_symlink() and (Path(os.readlink(path)).is_absolute() or not path.resolve().is_relative_to(source)):
                raise ValueError(f'game-content link escapes the source: {path}')
    return source


def redirect_saves(prefix, old, new, excluded=None):
    """Never let the test prefix retain a link to the original game's saves."""
    old = old.resolve()
    for root, dirs, files in os.walk(prefix, followlinks=False):
        dirs[:] = [name for name in dirs if Path(root) / name != excluded]
        for name in dirs + files:
            path = Path(root) / name
            if path.is_symlink():
                target = path.resolve()
                if target.is_relative_to(old):
                    replacement = new / target.relative_to(old)
                    path.unlink()
                    path.symlink_to(replacement, target_is_directory=replacement.is_dir())


def launch_executable(prefix):
    """Resolve the existing CMD without evaluating shell/batch commands."""
    _, values = directives(prefix)
    cmd = values.get('CMD', '').strip()
    match = re.match(r'^"([^"\n]+)"', cmd)
    if match:
        executable = match.group(1)
    else:
        match = re.match(r'^(.+?\.(?:exe|bat|cmd))(?:\s|$)', cmd, re.I)
        if not match:
            return ''
        executable = match.group(1)
    directory_value = values.get('DIR', '.').strip().strip('"').replace('\\', '/')
    directory = Path('drive_c') / directory_value[3:] if directory_value.lower().startswith('c:/') else relative_path(directory_value)
    executable = executable.replace('\\', '/')
    if executable.lower().startswith('c:/'):
        path = Path('drive_c') / executable[3:]
    else:
        path = directory / relative_path(executable)
    absolute = prefix / path
    if absolute.is_file() and absolute.resolve().is_relative_to(prefix.resolve()) and absolute.name.casefold() != 'autorun.cmd':
        return path.as_posix()
    return ''


def game_directory(prefix):
    """Keep the archive's existing layout rather than forcing drive_c/game."""
    _, values = directives(prefix)
    value = values.get('DIR', '').strip().strip('"').replace('\\', '/')
    directory = Path('drive_c') / value[3:] if value.lower().startswith('c:/') else relative_path(value)
    if directory.parts and directory.parts[0] == 'drive_c' and len(directory.parts) > 1:
        if directory.parts[1].casefold() not in ('windows', 'users', 'programdata', 'program files', 'program files (x86)'):
            candidate = prefix / Path(*directory.parts[:2])
            if candidate.is_dir() and not candidate.is_symlink():
                return candidate
    candidate = prefix / 'drive_c/game'
    if candidate.is_dir() and not candidate.is_symlink():
        return candidate
    raise ValueError('cannot identify a dedicated game directory from autorun.cmd')


def save_links(prefix, save_root):
    result = []
    base = save_root.resolve()
    for root, dirs, files in os.walk(prefix, followlinks=False):
        # dosdevices maps Windows drives, not an individual game's save rules.
        dirs[:] = [name for name in dirs if not (Path(root) == prefix and name == 'dosdevices')]
        for name in dirs + files:
            path = Path(root) / name
            if not path.is_symlink():
                continue
            target = path.resolve()
            if target.is_relative_to(base):
                result.append(dict(path=path.relative_to(prefix).as_posix(), target=str(target),
                                   original=os.readlink(path), directory=not target.is_file()))
    return result


def custom_links(data):
    savedir = relative_path(data['savedir']) if data.get('savedir') else None
    if savedir is not None:
        prefix = Path(data['prefix']).resolve()
        profile = prefix / 'drive_c/users/root'
        if profile.is_symlink() and profile.resolve() == prefix / 'drive_c/users/steamuser':
            parts = savedir.parts
            if parts[:3] == ('drive_c', 'users', 'root'):
                savedir = Path('drive_c/users/steamuser', *parts[3:])
    patterns = data.get('savefiles', '').split(';')
    result = []
    for link in data.get('save_links', []):
        path = Path(link['path'])
        standard = False
        if savedir is not None and path.is_relative_to(savedir):
            relative = path.relative_to(savedir).as_posix()
            standard = (not data.get('savefiles') or any(fnmatch.fnmatchcase(relative, pattern) for pattern in patterns))
        if not standard:
            result.append(link)
    return result


def restore_legacy(prefix, manifest, restore_links=True):
    data = json.loads(manifest.read_text())
    links = custom_links(data) if restore_links == 'custom' else data.get('save_links', [])
    for link in links if restore_links else []:
        path = prefix / link['path']
        if not path.parent.resolve().is_relative_to(prefix.resolve()):
            raise ValueError('save link parent escapes the working prefix')
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            path.unlink()
        elif path.is_dir():
            path.rmdir()  # Only remove an empty placeholder, never game data.
        elif path.exists():
            raise ValueError(f'save link was replaced by game data: {path}')
        path.symlink_to(link['original'], target_is_directory=link['directory'])
    for name in data.get('test_scripts', []):
        path = prefix / name
        if path.is_file() and not path.is_symlink():
            text = path.read_text(encoding='utf-8', errors='surrogateescape')
            for original, replacement in data['script_replacements']:
                text = text.replace(replacement, original)
            path.write_text(text, encoding='utf-8', errors='surrogateescape')


def stage_legacy(manifest):
    """Merge only save locations used by this test, never copy the whole root."""
    data = json.loads(manifest.read_text())
    shared = Path(data['test_save']) / '.legacy-shared'
    base = Path(data['save_root'])
    stage = Path(data['test_save']) / '.legacy-publish'
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    entries = []
    for child in sorted(shared.iterdir()) if shared.exists() else []:
        target = base / child.name
        prepared = stage / child.name
        if target.is_symlink():
            raise ValueError('external save destination must not be a symlink')
        if child.is_dir():
            if target.exists():
                shutil.copytree(target, prepared, symlinks=False)
            shutil.copytree(child, prepared, symlinks=False, dirs_exist_ok=True)
        elif child.is_file():
            shutil.copy2(child, prepared)
        else:
            raise ValueError('unsupported external save entry')
        entries.append(dict(target=str(target), prepared=str(prepared)))
    data['legacy_publish'] = entries
    save_json(manifest, data)


def cleanup_runtime_bottles(root, archive_name):
    """Remove every cached Wine overlay for one WSquashFS without following symlinks."""
    if (not archive_name or Path(archive_name).name != archive_name or
            "/" in archive_name or "\\" in archive_name or
            not archive_name.casefold().endswith(".wsquashfs")):
        raise ValueError("expected a WSquashFS filename, not a path")
    root = Path(root)
    if root.is_symlink():
        raise ValueError("Wine bottle root must not be a symlink")
    if not root.exists():
        return []
    if not root.is_dir():
        raise ValueError("Wine bottle root is not a directory")
    root = root.resolve()
    target_name = (archive_name + ".wine").casefold()
    removed = []
    for current, directories, _ in os.walk(root, topdown=True, followlinks=False):
        for name in list(directories):
            candidate = Path(current) / name
            if name.casefold() != target_name:
                if candidate.is_symlink():
                    directories.remove(name)
                continue
            if candidate.is_symlink():
                candidate.unlink()
            elif candidate.is_dir():
                if not candidate.parent.resolve().is_relative_to(root):
                    raise ValueError("Wine bottle path escapes the configured root")
                shutil.rmtree(candidate)
            else:
                continue
            removed.append(str(candidate))
            directories.remove(name)
    return removed


def cleanup_test_saves(manifest):
    data = json.loads(manifest.read_text())
    if not data.get('committed'):
        raise ValueError('test saves must be retained until the update is committed')
    base = Path(data['save_root']).resolve()
    test = Path(data['test_save'])
    expected = '.uwt-test-' + manifest.stem if data.get('same_rom_name') else Path(data['prefix']).stem
    if test.parent.resolve() != base or test.name != expected or test.is_symlink():
        raise ValueError('invalid test-save cleanup location')
    if test.resolve() == Path(data['original_save']).resolve():
        raise ValueError('cannot remove original saves')
    if test.exists():
        shutil.rmtree(test)


def prepare(prefix, source, archive, save_root, manifest, reuse_prefix=False):
    new_archive = reuse_prefix and not archive.exists() and not archive.is_symlink()
    if not new_archive and (archive.is_symlink() or not archive.is_file()):
        raise ValueError('archive must be a regular file')
    if prefix.is_symlink() or not prefix.is_dir():
        raise ValueError('working prefix must be a real directory')
    root = prefix.resolve()
    if reuse_prefix and (prefix.suffix.casefold() != '.wine' or not (root / 'system.reg').is_file()
                         or not (root / 'autorun.cmd').is_file()):
        raise ValueError('reusing a prefix requires a .wine directory with system.reg and autorun.cmd')
    ensure_root_alias(root)
    game = game_directory(root)
    if (root / 'drive_c').is_symlink() or not game.is_dir() or game.is_symlink():
        raise ValueError('archive must contain an internal game directory')
    source = validate_source(source, root)
    text, values = directives(root)
    links = save_links(root, save_root)
    savedir = relative_path(values.get('SAVEDIR', '')) if values.get('SAVEDIR') else None
    if savedir is not None and savedir != Path('.') and not (root / savedir).parent.resolve().is_relative_to(root):
        raise ValueError('save-directory parent escapes the prefix')
    original_save = save_root / archive.stem
    same_rom_name = prefix.stem == archive.stem
    test_save = save_root / ('.uwt-test-' + manifest.stem) if same_rom_name else save_root / prefix.stem
    if test_save.exists() or test_save.is_symlink():
        raise ValueError('test-save destination already exists')
    if original_save.is_symlink():
        raise ValueError('original save directory must not be a symlink')
    if savedir is not None:
        location = root / savedir
        if location.is_symlink() and not location.resolve().is_relative_to(original_save.resolve()):
            raise ValueError('existing save link does not point to this game save directory')
    old_game = game.with_name(game.name + '.bak')
    embedded = root / '.uwt-update-embedded-save'
    leftovers = [p for p in (old_game, embedded) if p.exists() or p.is_symlink()]
    if leftovers:
        paths = ', '.join(str(p) for p in leftovers)
        raise ValueError('unfinished preparation artifacts already present: ' + paths)
    if source.stat().st_dev != game.parent.stat().st_dev:
        raise ValueError('game source and prefix must be on the same filesystem for a move without copying')
    existing_launch = launch_executable(root)
    data = {'archive': str(archive), 'archive_signature': None if new_archive else signature(archive),
            'reuse_prefix': reuse_prefix,
            'prefix': str(prefix), 'source': str(source), 'game_dir': game.relative_to(root).as_posix(), 'game_backup': str(old_game),
            'original_save': str(original_save), 'test_save': str(test_save),
            'autorun': text, 'savedir': values.get('SAVEDIR', ''),
            'savefiles': values.get('SAVEFILES', ''), 'save_root': str(save_root),
            'save_links': links, 'test_scripts': [], 'same_rom_name': same_rom_name}
    save_json(manifest, data)
    if original_save.is_dir():
        shutil.copytree(original_save, test_save, symlinks=False)
    else:
        test_save.mkdir(parents=True)
    if savedir is not None and savedir != Path('.'):
        location = root / savedir
        if location.is_relative_to(game) and location != game and location.is_dir() and not location.is_symlink():
            shutil.copytree(location, embedded, symlinks=True)
    game.rename(old_game)
    try:
        try:
            source.rename(game)
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
            print('Direct rename returned EXDEV; checking mergerfs physical branches (no copy).', flush=True)
            def record_moves(plan):
                data['physical_moves'] = plan
                save_json(manifest, data)
            try:
                rename_in_branches(source, game, record_moves)
            except (OSError, ValueError) as physical_error:
                raise OSError(errno.EXDEV, f'Cannot move without copying: {physical_error}') from exc
    except MoveRecoveryRequired:
        raise  # Partial new game must not be mixed with the old .bak.
    except Exception:
        old_game.rename(game)
        raise
    # Original start.bat scripts take precedence, even if the new game supplies
    # another start.bat. Keep each one at its original relative location.
    launchers = []
    for directory, _, files in os.walk(old_game, followlinks=False):
        for filename in files:
            old_path = Path(directory) / filename
            if filename.casefold() == 'start.bat' and not old_path.is_symlink():
                launchers.append(old_path.relative_to(old_game))
    if existing_launch:
        launch = root / existing_launch
        if launch.suffix.casefold() in ('.bat', '.cmd') and launch.is_relative_to(game):
            relative = launch.relative_to(game)
            if relative not in launchers:
                launchers.append(relative)
    for relative in launchers:
        old_path = old_game / relative
        if not old_path.is_file() or old_path.is_symlink():
            continue
        replacement = game / relative
        if not replacement.parent.resolve().is_relative_to(game.resolve()) or replacement.is_symlink():
            raise ValueError('replacement redirects an original batch launcher')
        replacement.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old_path, replacement)
    if embedded.exists():
        location = root / savedir
        if location.is_symlink() or not location.parent.resolve().is_relative_to(root):
            raise ValueError('replacement game redirects the savedir outside the prefix')
        shutil.copytree(embedded, location, symlinks=True, dirs_exist_ok=True)
    # Restore custom save links that replacing drive_c/game would otherwise lose.
    # SAVEDIR links use Batocera's per-ROM test copy; custom links use a separate
    # root view, including links that point at the shared saves/windows root.
    shared = test_save / '.legacy-shared'
    for link in links:
        target = Path(link['target'])
        path = root / link['path']
        if target == save_root.resolve():
            replacement = Path(link['original'])
        elif savedir is not None and target.is_relative_to(original_save.resolve()):
            replacement = test_save / target.relative_to(original_save.resolve())
        else:
            relative = target.relative_to(save_root.resolve())
            replacement = shared / relative
            if relative != Path('.') and target.exists() and not replacement.exists():
                replacement.parent.mkdir(parents=True, exist_ok=True)
                if target.is_dir():
                    shutil.copytree(target, replacement, symlinks=False)
                else:
                    shutil.copy2(target, replacement)
            else:
                shared.mkdir(parents=True, exist_ok=True)
        if not path.parent.resolve().is_relative_to(root):
            raise ValueError('replacement game redirects the save-link parent')
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            path.unlink()
        elif path.is_dir():
            path.rmdir()  # Restore the old link only over an empty placeholder.
        elif path.exists():
            raise ValueError(f'replacement contains data at old save-link location: {path}')
        path.symlink_to(replacement, target_is_directory=link['directory'])
    # Literal save-root references in batch launchers must use the same test view.
    # No command is executed or arbitrary batch expression evaluated here.
    if links and savedir is None and not any(Path(link['target']) == save_root.resolve() for link in links):
        shared.mkdir(parents=True, exist_ok=True)
        replacements = [(str(save_root), str(shared)),
                        (str(save_root).replace('/', '\\'), str(shared).replace('/', '\\'))]
        candidates = {archive.stem}
        for path in game.rglob('*'):
            if path.suffix.casefold() not in ('.bat', '.cmd') or path.is_symlink() or not path.is_file():
                continue
            content = path.read_text(encoding='utf-8', errors='surrogateescape')
            for base in (str(save_root), str(save_root).replace('/', '\\')):
                for match in re.finditer(re.escape(base) + r'[/\\]([^"\r\n]+)', content):
                    candidate = re.split(r'[/\\]', match.group(1))[0].strip()
                    if candidate and candidate not in ('.', '..') and not any(c in candidate for c in '%!><|&'):
                        candidates.add(candidate)
        for name in candidates:
            target = save_root / name
            destination = shared / name
            if target.is_dir() and not target.is_symlink() and not destination.exists():
                shutil.copytree(target, destination, symlinks=False)
        data['script_replacements'] = replacements
        for path in game.rglob('*'):
            if path.suffix.casefold() not in ('.bat', '.cmd') or path.is_symlink() or not path.is_file():
                continue
            content = path.read_text(encoding='utf-8', errors='surrogateescape')
            updated = content
            for original, replacement in replacements:
                updated = updated.replace(original, replacement)
            if updated != content:
                data['test_scripts'].append(path.relative_to(root).as_posix())
                path.write_text(updated, encoding='utf-8', errors='surrogateescape')
        save_json(manifest, data)
    redirect_saves(root, original_save, test_save, old_game)
    if same_rom_name and savedir is not None:
        # A stable .wine name shares Batocera's save basename with the archive.
        # Disable its automatic save redirect for this test only, and install
        # explicit links to the isolated copy (including SAVEFILES registries).
        location = root / savedir
        if not location.parent.resolve().is_relative_to(root) and savedir != Path('.'):
            raise ValueError('test save parent escapes the prefix')
        if values.get('SAVEFILES'):
            location.mkdir(parents=True, exist_ok=True)
            for pattern in values['SAVEFILES'].split(';'):
                if not pattern.strip(): continue
                relative_path(pattern)
                for entry in location.glob(pattern):
                    if not entry.is_file(): continue
                    relative = entry.relative_to(location)
                    target = test_save / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not target.exists(): shutil.copy2(entry, target)
                    if entry.resolve() != target.resolve():
                        entry.unlink(); entry.symlink_to(target)
        else:
            if location == root or game.is_relative_to(location):
                raise ValueError('SAVEDIR cannot redirect the whole prefix or game for this test')
            if location.is_symlink():
                location.unlink()
            elif location.exists():
                shutil.copytree(location, test_save, symlinks=False, dirs_exist_ok=True)
                shutil.rmtree(location)
            location.parent.mkdir(parents=True, exist_ok=True)
            location.symlink_to(test_save, target_is_directory=True)
        rewrite_save_rules(root, '', '')
    if embedded.exists():
        shutil.rmtree(embedded)


def existing_save_locations(manifest):
    """Read-only locations; a shared-root link requires choosing a child folder."""
    data = json.loads(manifest.read_text())
    base = Path(data['save_root']).resolve()
    excluded = {Path(data['test_save']).resolve(),
                base / (Path(data['prefix']).stem + '.validated')}
    candidates = [Path(data['original_save'])]
    for link in data.get('save_links', []):
        target = Path(link['target'])
        if target.resolve() == base:
            candidates.extend(base.iterdir())
        else:
            candidates.append(target if link['directory'] else target.parent)
    locations = set()
    for path in candidates:
        real = path.resolve()
        if (not path.is_symlink() and path.is_dir() and real != base
                and real.is_relative_to(base) and real not in excluded
                and not path.name.startswith('.uwt-')):
            locations.add(real)
    return sorted(locations, key=lambda path: str(path).casefold())


def prepare_retest(manifest, prepared=None):
    """Rebind a prepared prefix to test saves before another game launch."""
    from wsquashfs_builder import safe_save_dir
    data = json.loads(manifest.read_text())
    root = Path(data['prefix']).resolve()
    base = Path(data['save_root']).resolve()
    test = Path(data['test_save'])
    expected = '.uwt-test-' + manifest.stem if data.get('same_rom_name') else Path(data['prefix']).stem
    if (data.get('committed') or test.is_symlink() or test.parent.resolve() != base
            or test.name != expected or not test.is_dir()):
        raise ValueError('invalid test-save location for relaunch')
    if prepared is not None:
        if (prepared.is_symlink() or prepared.parent.resolve() != base
                or prepared.name != Path(data['prefix']).stem + '.validated'):
            raise ValueError('invalid prepared save copy')
        if prepared.is_dir():
            shutil.copytree(prepared, test, symlinks=False, dirs_exist_ok=True)
    _, rules = directives(root)
    savedir, savefiles = rules.get('SAVEDIR', ''), rules.get('SAVEFILES', '')
    if savedir:
        relative = relative_path(savedir)
        location = root / relative
        if savefiles:
            if not location.resolve().is_relative_to(root):
                raise ValueError('SAVEFILES parent escapes the prefix')
            for pattern in savefiles.split(';'):
                if not pattern.strip(): continue
                relative_path(pattern)
                for entry in location.glob(pattern):
                    if not entry.is_file(): continue
                    target = test / entry.relative_to(location)
                    if entry.resolve() != target.resolve():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(entry, target)
                        entry.unlink()
                        entry.symlink_to(target)
        else:
            safe_save_dir(root, str(relative), save_root=base)
            if location.is_symlink():
                location.unlink()
            else:
                shutil.copytree(location, test, symlinks=False, dirs_exist_ok=True)
                shutil.rmtree(location)
            location.symlink_to(test, target_is_directory=True)
        if data.get('same_rom_name'):
            rewrite_save_rules(root, '', '')
    for link in custom_links(data):
        path = root / relative_path(link['path'])
        target = Path(link['target']).resolve()
        if not target.is_relative_to(base) or not path.parent.resolve().is_relative_to(root):
            raise ValueError('invalid legacy test-save link')
        replacement = base if target == base else test / '.legacy-shared' / target.relative_to(base)
        if target != base and not replacement.exists() and target.exists():
            replacement.parent.mkdir(parents=True, exist_ok=True)
            if target.is_dir(): shutil.copytree(target, replacement, symlinks=False)
            else: shutil.copy2(target, replacement)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink(): path.unlink()
        elif path.is_dir(): path.rmdir()
        elif path.exists():
            raise ValueError('legacy save link contains unexpected data')
        path.symlink_to(replacement, target_is_directory=link['directory'])
    for name in data.get('test_scripts', []):
        path = root / relative_path(name)
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('test script escapes the working prefix')
        if path.is_file():
            text = path.read_text(encoding='utf-8', errors='surrogateescape')
            for original, replacement in data['script_replacements']:
                text = text.replace(original, replacement)
            path.write_text(text, encoding='utf-8', errors='surrogateescape')


def finish_game(manifest):
    data = json.loads(manifest.read_text())
    if data.get('game_backup_removed'):
        return
    root = Path(data['prefix']).resolve()
    game = root / relative_path(data['game_dir'])
    expected = game.with_name(game.name + '.bak')
    backup = Path(data.get('game_backup', expected))
    if backup != expected or not backup.parent.resolve().is_relative_to(root) or backup.is_symlink():
        raise ValueError('invalid old-game backup directory')
    if backup.exists():
        shutil.rmtree(backup)
    data['game_backup_removed'] = True
    save_json(manifest, data)


def rewrite_save_rules(prefix, savedir, savefiles):
    text, _ = directives(prefix)
    lines = [line for line in text.splitlines() if line.split('=', 1)[0].strip().upper() not in ('SAVEDIR', 'SAVEFILES')]
    if savedir: lines.append('SAVEDIR=' + savedir)
    if savefiles: lines.append('SAVEFILES=' + savefiles)
    tmp = prefix / 'autorun.cmd.uwt-saves'
    tmp.write_text('\n'.join(lines) + '\n', encoding='utf-8', errors='surrogateescape')
    os.replace(tmp, prefix / 'autorun.cmd')


def write_autorun(prefix, exe, savedir=None, savefiles=None):
    root = prefix.resolve()
    path = root / relative_path(exe)
    if not path.is_file() or not path.resolve().is_relative_to(root) or path.name.casefold() == 'autorun.cmd':
        raise ValueError('selected executable must be an internal game file')
    if '"' in path.name:
        raise ValueError('executable name contains a quote')
    text, values = directives(root)
    old_cmd = values.get('CMD', '')
    match = re.match(r'^"[^"]*"(.*)$', old_cmd)
    unquoted = re.match(r'^.+?\.(?:exe|bat|cmd)(\s.*)?$', old_cmd, re.I)
    suffix = match.group(1) if match else ((unquoted.group(1) or '') if unquoted else '')
    if suffix and not suffix.startswith(' '):
        suffix = ' ' + suffix
    changes = {'DIR': path.parent.relative_to(root).as_posix(), 'CMD': f'"{path.name}"' + suffix}
    if savedir is not None:
        changes.update(SAVEDIR=savedir, SAVEFILES=savefiles or '')
    # Preserve ENV, arguments, language and every unrelated directive/comment.
    lines = [line for line in text.splitlines()
             if line.split('=', 1)[0].strip().upper() not in changes]
    lines += [f'{key}={value}' for key, value in changes.items() if value]
    tmp = root / 'autorun.cmd.uwt-update'
    tmp.write_text('\n'.join(lines) + '\n', encoding='utf-8', errors='surrogateescape')
    os.replace(tmp, root / 'autorun.cmd')


def detach_saves(prefix, save):
    """Make archive paths portable; do not change the external save copy."""
    save = save.resolve()
    for root, dirs, files in os.walk(prefix, followlinks=False):
        for name in dirs + files:
            path = Path(root) / name
            if not path.is_symlink():
                continue
            target = path.resolve()
            if not target.is_relative_to(save):
                continue
            if target.is_dir():
                path.unlink()
                path.mkdir()
            elif target.is_file():
                tmp = path.with_name(path.name + '.uwt-copy')
                shutil.copy2(target, tmp)
                path.unlink()
                os.replace(tmp, path)
            else:
                raise ValueError(f'unresolved save link: {path}')


def copy_config(conf, source, dest, backup_dir=None, preserve_existing=False):
    if any(c in source + dest for c in '\n\r=#"'):
        raise ValueError('unsupported ROM name in configuration')
    if not conf.exists():
        return '__SYSTEM__'
    lines = conf.read_text(encoding='utf-8', errors='surrogateescape').splitlines(keepends=True)
    old = f'windows["{source}"].'
    new = f'windows["{dest}"].'
    selected = [line.strip()[len(old):] for line in lines if line.lstrip().startswith(old)]
    if preserve_existing and not selected:
        selected = [line.strip()[len(new):] for line in lines if line.lstrip().startswith(new)]
    if backup_dir:
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / ('batocera.conf.update-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        shutil.copy2(conf, backup)
    lines = [line for line in lines if not line.lstrip().startswith(new)]
    if lines and not lines[-1].endswith('\n'):
        lines[-1] += '\n'
    lines += [new + value + '\n' for value in selected]
    tmp = conf.with_name(conf.name + '.uwt-update')
    tmp.write_text(''.join(lines), encoding='utf-8', errors='surrogateescape')
    os.chmod(tmp, conf.stat().st_mode & 0o777)
    os.replace(tmp, conf)
    runners = [value.split('=', 1)[1] for value in selected if value.startswith('wine-runner=')]
    return runners[-1] if runners else '__SYSTEM__'


def commit(manifest, staged, prepared_save=None, keep_archive_backup=True):
    data = json.loads(manifest.read_text())
    archive = Path(data['archive'])
    new_archive = data.get('reuse_prefix') and data.get('archive_signature') is None
    if new_archive:
        if archive.exists() or archive.is_symlink():
            raise ValueError('new archive destination appeared since preparation; creation refused')
    elif archive.is_symlink() or signature(archive) != data['archive_signature']:
        raise ValueError('original archive changed since preparation; replacement refused')
    if staged.is_symlink() or not staged.is_file() or staged.parent.resolve() != archive.parent.resolve() or staged == archive:
        raise ValueError('validated replacement must be a distinct adjacent file')
    backup = None
    if keep_archive_backup and not new_archive:
        backup = archive.with_name(archive.stem + '.backup-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + archive.suffix)
        try:
            os.link(archive, backup)
        except OSError:
            shutil.copy2(archive, backup)
    original_save = Path(data['original_save'])
    changes = list(data.get('legacy_publish', []))
    if prepared_save is not None:
        if prepared_save.is_symlink() or not prepared_save.is_dir() or prepared_save.parent.resolve() != original_save.parent.resolve() or prepared_save == original_save:
            raise ValueError('prepared saves must be a distinct adjacent directory')
        changes.append(dict(target=str(original_save), prepared=str(prepared_save)))
    swapped = []
    save_backup = None
    try:
        for change in changes:
            target = Path(change['target']); prepared = Path(change['prepared'])
            if target.is_symlink() or prepared.is_symlink() or not prepared.exists():
                raise ValueError('invalid save transaction path')
            if target.parent.resolve() != Path(data.get('save_root', original_save.parent)).resolve():
                raise ValueError('save transaction escapes the save root')
            backup_path = None
            if target.exists():
                backup_path = target.with_name(target.name + '.backup-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
                target.rename(backup_path)
            swapped.append((target, prepared, backup_path))
            prepared.rename(target)
            save_backup = backup_path or save_backup
        if new_archive:
            os.link(staged, archive)  # Atomic no-clobber publication of a new archive.
        else:
            os.replace(staged, archive)
    except Exception:
        for target, prepared, backup_path in reversed(swapped):
            if target.exists():
                target.rename(prepared)
            if backup_path is not None:
                backup_path.rename(target)
        raise
    data.update(committed=True, archive_backup=str(backup or ''), save_backup=str(save_backup or ''))
    save_json(manifest, data)
    if new_archive:
        try:
            staged.unlink()
        except OSError as exc:
            print(f'New archive committed; temporary hardlink retained: {exc}', file=sys.stderr)
    return backup or ''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sp = p.add_subparsers(dest='action', required=True)
    a = sp.add_parser('listing')
    a.add_argument('directory', type=Path); a.add_argument('kind', choices=('archives', 'sources', 'bases')); a.add_argument('--preferred', default=''); a.add_argument('--exclude', default='')
    a = sp.add_parser('prepare')
    for name in ('prefix', 'source', 'archive', 'save_root', 'manifest'):
        a.add_argument(name, type=Path)
    a.add_argument('--reuse-prefix', action='store_true')
    a = sp.add_parser('autorun')
    a.add_argument('prefix', type=Path); a.add_argument('exe')
    a.add_argument('--savedir'); a.add_argument('--savefiles')
    a = sp.add_parser('detach')
    a.add_argument('prefix', type=Path); a.add_argument('save', type=Path)
    a = sp.add_parser('retest')
    a.add_argument('manifest', type=Path); a.add_argument('--prepared-save', type=Path)
    a = sp.add_parser('save-locations')
    a.add_argument('manifest', type=Path)
    a = sp.add_parser('config')
    a.add_argument('conf', type=Path); a.add_argument('source'); a.add_argument('dest')
    a.add_argument('--backup-dir', type=Path); a.add_argument('--preserve-existing', action='store_true')
    a = sp.add_parser('commit')
    a.add_argument('manifest', type=Path); a.add_argument('staged', type=Path); a.add_argument('--prepared-save', type=Path); a.add_argument('--replace', action='store_true')
    a = sp.add_parser('cleanup-bottles')
    a.add_argument('root', type=Path); a.add_argument('archive_name')
    for action in ('cleanup-test', 'profiles', 'restore-save-rules', 'finish-game', 'restore-legacy', 'restore-custom', 'restore-scripts', 'stage-legacy', 'legacy-summary', 'exe', 'game-dir'):
        a = sp.add_parser(action)
        a.add_argument('prefix' if action in ('exe', 'game-dir', 'profiles') else 'manifest', type=Path)
    a = sp.add_parser('root-link')
    a.add_argument('manifest', type=Path)
    a = sp.add_parser('seed-legacy')
    a.add_argument('manifest', type=Path); a.add_argument('source', type=Path)
    a = sp.add_parser('copy-test')
    a.add_argument('manifest', type=Path); a.add_argument('destination', type=Path)
    a = sp.add_parser('value')
    a.add_argument('manifest', type=Path); a.add_argument('key')
    a = p.parse_args()
    try:
        if a.action == 'listing':
            for path, matched in update_listing(a.directory, a.kind, a.preferred, a.exclude): print(f'{path}\t{int(matched)}')
        elif a.action == 'prepare': prepare(a.prefix, a.source, a.archive, a.save_root, a.manifest, a.reuse_prefix)
        elif a.action == 'autorun': write_autorun(a.prefix, a.exe, a.savedir, a.savefiles)
        elif a.action == 'detach': detach_saves(a.prefix, a.save)
        elif a.action == 'config': print(copy_config(a.conf, a.source, a.dest, a.backup_dir, a.preserve_existing))
        elif a.action == 'commit': print(commit(a.manifest, a.staged, a.prepared_save, not a.replace))
        elif a.action == 'game-dir': print(game_directory(a.prefix).relative_to(a.prefix).as_posix())
        elif a.action == 'cleanup-test': cleanup_test_saves(a.manifest)
        elif a.action == 'cleanup-bottles':
            removed = cleanup_runtime_bottles(a.root, a.archive_name)
            print('\n'.join(removed) if removed else f'No runtime bottle found for {a.archive_name}')
        elif a.action == 'profiles': ensure_root_alias(a.prefix)
        elif a.action == 'retest': prepare_retest(a.manifest, a.prepared_save)
        elif a.action == 'save-locations':
            for path in existing_save_locations(a.manifest):
                sys.stdout.write(str(path) + '\0')
        elif a.action == 'exe': print(launch_executable(a.prefix))
        elif a.action == 'root-link':
            data = json.loads(a.manifest.read_text())
            print(any(Path(link['target']) == Path(data['save_root']).resolve() for link in data.get('save_links', [])))
        elif a.action == 'seed-legacy':
            data = json.loads(a.manifest.read_text())
            base = Path(data['save_root']).resolve()
            source = a.source.resolve(strict=True)
            if not source.is_dir() or source.parent != base or a.source.is_symlink():
                raise ValueError('choose this game folder directly inside the saves/windows root')
            destination = Path(data['test_save']) / '.legacy-shared' / source.name
            shutil.copytree(source, destination, symlinks=False, dirs_exist_ok=True)
        elif a.action == 'copy-test':
            data = json.loads(a.manifest.read_text())
            for child in Path(data['test_save']).iterdir():
                if child.name in ('.legacy-shared', '.legacy-publish'): continue
                target = a.destination / child.name
                if child.is_dir(): shutil.copytree(child, target, symlinks=False, dirs_exist_ok=True)
                else: shutil.copy2(child, target)
        elif a.action == 'restore-save-rules':
            data = json.loads(a.manifest.read_text())
            if data.get('same_rom_name'):
                root = Path(data['prefix'])
                location = root / relative_path(data.get('savedir', '.'))
                test = Path(data['test_save'])
                for pattern in data.get('savefiles', '').split(';'):
                    if not pattern.strip(): continue
                    relative_path(pattern)
                    for entry in location.glob(pattern):
                        if not entry.is_file(): continue
                        target = test / entry.relative_to(location)
                        if entry.resolve() != target.resolve():
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(entry, target)
            rewrite_save_rules(Path(data['prefix']), data.get('savedir', ''), data.get('savefiles', ''))
        elif a.action == 'finish-game': finish_game(a.manifest)
        elif a.action == 'restore-custom':
            data = json.loads(a.manifest.read_text()); restore_legacy(Path(data['prefix']), a.manifest, 'custom')
        elif a.action == 'restore-scripts':
            data = json.loads(a.manifest.read_text()); restore_legacy(Path(data['prefix']), a.manifest, False)
        elif a.action == 'restore-legacy':
            data = json.loads(a.manifest.read_text()); restore_legacy(Path(data['prefix']), a.manifest)
        elif a.action == 'stage-legacy': stage_legacy(a.manifest)
        elif a.action == 'legacy-summary':
            data = json.loads(a.manifest.read_text())
            print('\n'.join(link['path'] + ' -> ' + link['target'] for link in data.get('save_links', [])))
        elif a.action == 'value': print(json.loads(a.manifest.read_text()).get(a.key, ''))
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
