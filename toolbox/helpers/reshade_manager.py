#!/usr/bin/env python3
"""Batocera adapter: stage ReShadeLinux installs and journal reversible game files."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile

HOOKS = {'dxgi', 'd3d9', 'opengl32'}
COMPILER_HASH = {32: '2ad0d4987fc4624566b190e747c9d95038443956ed816abfd1e2d389b5ec0851',
                 64: '4432bbd1a390874f3f0a503d45cc48d346abc3a8c0213c289f4b615bf0ee84f3'}


def key(rom):
    return hashlib.sha256(os.fsencode(os.path.abspath(rom))).hexdigest()[:24]


def read_json(path, default=None):
    return json.loads(path.read_text()) if path.is_file() else (default if default is not None else {})


def atomic_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.uwt-reshade-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(data)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def save_json(path, data):
    atomic_bytes(path, (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode())


def relative(value):
    value = value.replace('\\', '/')
    p = PurePosixPath(value)
    if (p.is_absolute() or '..' in p.parts or not p.parts
            or any(c in value for c in '\n\r\t\x00')):
        raise ValueError('invalid relative game path')
    return p.as_posix()


def safe_leaf(root, rel):
    root = Path(os.path.abspath(root))
    path = root / relative(rel)
    if not path.parent.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'directory link escapes game/bottle: {path.parent}')
    if path.is_dir():
        raise ValueError(f'file path is a directory: {path}')
    return path


def fingerprint(path):
    if path.is_symlink():
        return {'link': os.readlink(path)}
    if path.is_file():
        return {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    if path.exists():
        raise ValueError(f'unsupported file: {path}')
    return None


def archive_bytes(rom, rel):
    return subprocess.run(['unsquashfs', '-cat', str(rom), relative(rel)], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def source_bytes(rom, rel):
    if rom.suffix.casefold() == '.wsquashfs':
        return archive_bytes(rom, rel)
    path = safe_leaf(rom, rel)
    if not path.resolve().is_relative_to(rom.resolve()):
        raise ValueError('source executable/autorun escapes the game')
    return path.read_bytes()


def source_header(rom, rel, limit=1024*1024):
    if rom.suffix.casefold() != '.wsquashfs':
        path = safe_leaf(rom, rel)
        if not path.resolve().is_relative_to(rom.resolve()):
            raise ValueError('source executable escapes the game')
        with path.open('rb') as stream:
            return stream.read(limit)
    with subprocess.Popen(['unsquashfs', '-cat', str(rom), relative(rel)],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proc:
        data = proc.stdout.read(limit)
        proc.stdout.close()
        proc.terminate()
        proc.wait()
    if not data:
        raise ValueError('configured executable is missing from the archive')
    return data


def autorun_source(rom):
    try:
        return source_bytes(rom, 'autorun.cmd').decode('utf-8', 'surrogateescape')
    except (FileNotFoundError, subprocess.CalledProcessError):
        raise ValueError('autorun.cmd is missing or unreadable')


def launch_path(text):
    vals = dict(line.split('=', 1) for line in text.splitlines() if '=' in line)
    cmd = vals.get('CMD', '').strip()
    match = re.match(r'^"([^"]+\.exe)"|^(.+?\.exe)(?:\s|$)', cmd, re.I)
    if not match:
        return ''
    exe = (match[1] or match[2]).replace('\\', '/')
    if exe.lower().startswith('c:/'):
        return relative('drive_c/' + exe[3:])
    directory = vals.get('DIR', '').strip().strip('"').replace('\\', '/').rstrip('/')
    return relative((directory + '/' if directory else '') + exe)


def executable_list(rom):
    if rom.suffix.casefold() == '.wsquashfs':
        output = subprocess.run(['unsquashfs', '-ls', str(rom)], check=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout
        paths = [line.split('squashfs-root/', 1)[1] for line in output.splitlines()
                 if line.startswith('squashfs-root/') and line.casefold().endswith('.exe')]
    else:
        paths = []
        for folder, dirs, files in os.walk(rom, followlinks=False):
            dirs[:] = [d for d in dirs if not (Path(folder) / d).is_symlink()]
            paths.extend((Path(folder) / name).relative_to(rom).as_posix()
                         for name in files if name.casefold().endswith('.exe'))
    out = []
    for p in paths:
        try:
            p = relative(p)
        except ValueError:
            continue
        if any(x.casefold() in ('windows', 'users', 'dosdevices', '_commonredist') for x in PurePosixPath(p).parts):
            continue
        if any(c in p for c in '\t\n\r'):
            continue
        out.append(p)
    primary = launch_path(autorun_source(rom))
    return sorted(set(out), key=lambda p: (p != primary, p.casefold()))


def pe_arch(data):
    if len(data) < 64 or data[:2] != b'MZ':
        raise ValueError('not a Windows PE executable')
    pos = struct.unpack_from('<I', data, 0x3c)[0]
    if pos + 6 > len(data) or data[pos:pos+4] != b'PE\0\0':
        raise ValueError('invalid Windows PE header')
    machine = struct.unpack_from('<H', data, pos+4)[0]
    if machine not in (0x14c, 0x8664):
        raise ValueError('only x86 and x86_64 Windows games are supported')
    return 64 if machine == 0x8664 else 32


def valid_rom(rom):
    if rom.suffix.casefold() not in ('.wine', '.pc', '.wsquashfs'):
        raise ValueError('supported game formats: .wine, .pc, .wsquashfs')
    if not rom.exists() or rom.is_symlink() or any(c in str(rom) for c in '\n\r\t'):
        raise ValueError('game path is missing or unsupported')


def prepare(home, rom, exe, dll, version, repos):
    valid_rom(rom)
    if dll not in HOOKS or not re.fullmatch(r'latest|[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('invalid ReShade hook/version')
    if not re.fullmatch(r'[a-z0-9_-]+(?:,[a-z0-9_-]+)*|none', repos):
        raise ValueError('invalid shader selection')
    exe = relative(exe)
    if exe not in executable_list(rom):
        raise ValueError('select an actual game executable')
    data = source_header(rom, exe)
    arch = pe_arch(data)
    workspace = home / 'reshade/workspaces' / key(rom)
    workspace.mkdir(parents=True, exist_ok=True)
    # ReShadeLinux operates only on this private staging directory.
    atomic_bytes(workspace / 'Game.exe', data)
    cache = home / 'reshade/runtime'
    state_key = 'path-' + hashlib.sha256(os.fsencode(str(workspace.resolve()))).hexdigest()[:16]
    state_file = cache / 'game-state' / (state_key + '.state')
    old = state_file.read_text() if state_file.is_file() else ''
    previous = re.search(r'^selected_repos=(.*)$', old, re.M)
    atomic_bytes(state_file, (f'dll={dll}\narch={arch}\ngamePath={workspace.resolve()}\n'
                             f'selected_repos={previous[1] if previous else ""}\napp_id=\n').encode())
    save_json(workspace / 'pending.json', {'rom': str(rom), 'exe': exe, 'dll': dll, 'arch': arch,
                                          'version': version, 'repos': repos, 'state_key': state_key})
    return workspace


def finish(home, rom):
    workspace = home / 'reshade/workspaces' / key(rom)
    pending = read_json(workspace / 'pending.json')
    cache = home / 'reshade/runtime'
    dll = (workspace / (pending['dll'] + '.dll')).resolve(strict=True)
    compiler = (workspace / 'd3dcompiler_47.dll').resolve(strict=True)
    shaders = (workspace / 'ReShade_shaders').resolve(strict=True)
    for path in (dll, compiler, shaders):
        if not path.is_relative_to(cache.resolve()):
            raise ValueError('backend payload escapes its cache')
    if pe_arch(dll.read_bytes()) != pending['arch'] or pe_arch(compiler.read_bytes()) != pending['arch']:
        raise ValueError('backend installed the wrong DLL architecture')
    if hashlib.sha256(compiler.read_bytes()).hexdigest() != COMPILER_HASH[pending['arch']]:
        raise ValueError('d3dcompiler_47 integrity check failed')
    backend_state = (cache / 'game-state' / (pending['state_key'] + '.state')).read_text()
    installed = re.search(r'^selected_repos=(.*)$', backend_state, re.M)
    requested = set(pending['repos'].split(',')) if pending['repos'] != 'none' else set()
    if not installed or set(filter(None, installed[1].split(','))) != requested:
        raise ValueError('not all requested shader packs were installed; check the log')
    config = home / 'reshade/games' / (key(rom) + '.json')
    old = read_json(config)
    pending.update(enabled=old.get('enabled', False), runtime=str(dll), compiler=str(compiler),
                   shaders=str(shaders), runtime_hash=fingerprint(dll)['sha256'],
                   compiler_hash=fingerprint(compiler)['sha256'])
    save_json(config, pending)
    profile = home / 'reshade/profiles' / key(rom)
    profile.mkdir(parents=True, exist_ok=True)
    if not (profile / 'ReShadePreset.ini').exists():
        atomic_bytes(profile / 'ReShadePreset.ini', b'Techniques=\nTechniqueSorting=\n')
    if not (profile / 'ReShade.ini').exists():
        atomic_bytes(profile / 'ReShade.ini', b'[GENERAL]\nPerformanceMode=0\n[INPUT]\nKeyOverlay=36,0,0,0\n')
    return pending


def shell_words(text):
    # Retain original quoting/expansions of unrelated ENV assignments.
    return re.findall(r'''(?:[^\s'"\\]|\\.|'[^']*'|"(?:\\.|[^"\\])*")+''', text)


def rewrite_env(text, old_words, new_words):
    lines = text.replace('\r\n', '\n').splitlines()
    env = [i for i, l in enumerate(lines) if l.startswith('ENV=')]
    if len(env) > 1:
        raise ValueError('multiple ENV directives; resolve them before enabling ReShade')
    words = shell_words(lines[env[0]][4:]) if env else []
    words = [w for w in words if w not in old_words]
    words.extend(new_words)
    if env:
        if words:
            lines[env[0]] = 'ENV=' + ' '.join(words)
        else:
            lines.pop(env[0])
    elif words:
        lines.insert(0, 'ENV=' + ' '.join(words))
    return '\n'.join(lines) + '\n'


def profile_ini(base, cfg):
    # Preserve UI settings, but keep shader and preset paths under Toolbox control.
    lines = base.replace('\r\n', '\n').splitlines()
    lines = [l for l in lines if not re.match(r'^(EffectSearchPaths|TextureSearchPaths|PresetPath)=', l)]
    index = next((i+1 for i, l in enumerate(lines) if l == '[GENERAL]'), None)
    if index is None:
        lines[:0] = ['[GENERAL]']
        index = 1
    shader_root = 'Z:' + cfg['shaders'].replace('/', '\\')
    lines[index:index] = [f'EffectSearchPaths={shader_root}\\Merged\\Shaders\\**',
                           f'TextureSearchPaths={shader_root}\\Merged\\Textures\\**',
                           'PresetPath=.\\ReShadePreset.ini']
    return '\n'.join(lines) + '\n'


def runner_for(rom, runner=''):
    if not runner:
        for setting in ('wine-runner', 'core'):
            result = subprocess.run(['batocera-settings-get', f'windows["{rom.name}"].{setting}',
                                     f'windows.{setting}', f'global.{setting}'], capture_output=True, text=True)
            runner = result.stdout.strip()
            if runner:
                break
    runner = {'lutris': 'wine-tkg', 'proton': 'wine-proton', '': 'wine-tkg'}.get(runner, runner)
    if not re.fullmatch(r'[A-Za-z0-9_.+-]+', runner):
        raise ValueError('unsupported runner folder name')
    return runner


def locations(rom, runner='', bottles=Path('/userdata/system/wine-bottles/windows'), legacy=False):
    if rom.suffix.casefold() == '.wine':
        return rom, rom
    runner = runner_for(rom, runner)
    prefix = bottles / rom.name if legacy else bottles / runner / (rom.name + '.wine')
    if rom.suffix.casefold() == '.pc':
        if not (prefix / 'user.reg').is_file():
            raise ValueError('launch this .pc game once with this runner before enabling ReShade')
        return rom, prefix
    return prefix, prefix


def journal_path(home, rom, root, prefix):
    ident = hashlib.sha256(os.fsencode(str(root) + '|' + str(prefix))).hexdigest()[:24]
    return home / 'reshade/installations' / key(rom) / (ident + '.json')


def directory_id(path):
    if not path.is_dir():
        return None
    stat = path.stat()
    return [stat.st_dev, stat.st_ino]



def profile_save(home, rom, root, cfg):
    profile = home / 'reshade/profiles' / key(rom)
    folder = PurePosixPath(cfg['exe']).parent
    for name in ('ReShade.ini', 'ReShadePreset.ini'):
        source = safe_leaf(root, (folder / name).as_posix())
        if source.is_file() and not source.is_symlink():
            atomic_bytes(profile / name, source.read_bytes())


def ensure_idle(rom, root, prefix):
    candidates = [root, prefix, Path('/var/run/wine') / rom.name]
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            environ = (entry / 'environ').read_bytes().split(b'\0')
            value = next((v[len(b'WINEPREFIX='):].decode(errors='surrogateescape')
                          for v in environ if v.startswith(b'WINEPREFIX=')), '')
            if not value:
                continue
            wineprefix = Path(value)
            for candidate in candidates:
                if wineprefix == candidate or (candidate.exists() and wineprefix.exists()
                                               and os.path.samefile(wineprefix, candidate)):
                    raise ValueError('game/prefix is active; close the game before changing ReShade')
        except (OSError, StopIteration):
            continue


def install_files(home, rom, root, prefix, cfg):
    ensure_idle(rom, root, prefix)
    if root.is_symlink() or prefix.is_symlink():
        raise ValueError("game/bottle root must be a real directory")
    for name, field in [('runtime', 'runtime_hash'), ('compiler', 'compiler_hash')]:
        p = Path(cfg[name])
        if (not p.resolve().is_relative_to((home / 'reshade/runtime').resolve())
                or fingerprint(p.resolve()) != {'sha256': cfg[field]}):
            raise ValueError('ReShade runtime missing or changed; reinstall from the menu')
    jp = journal_path(home, rom, root, prefix)
    journal = read_json(jp)
    if journal and journal['exe'] != cfg['exe']:
        raise ValueError('disable ReShade before changing its executable')
    folder = PurePosixPath(cfg['exe']).parent
    profile = home / 'reshade/profiles' / key(rom)
    ini = profile_ini((profile / 'ReShade.ini').read_text(), cfg).encode()
    files = [(root, (folder / (cfg['dll'] + '.dll')).as_posix(), Path(cfg['runtime']).read_bytes(), False),
             (root, (folder / 'd3dcompiler_47.dll').as_posix(), Path(cfg['compiler']).read_bytes(), False),
             (root, (folder / 'ReShade.ini').as_posix(), ini, True),
             (root, (folder / 'ReShadePreset.ini').as_posix(), (profile / 'ReShadePreset.ini').read_bytes(), True)]
    # ReShade >=6.5 needs the compiler in system32/syswow64 too.
    win32 = False
    try:
        win32 = '#arch=win32' in (prefix / 'user.reg').read_text()
    except OSError:
        if rom.suffix.casefold() == '.wsquashfs':
            try:
                win32 = b'#arch=win32' in archive_bytes(rom, 'user.reg')
            except subprocess.CalledProcessError:
                pass
    sysdir = 'syswow64' if cfg['arch'] == 32 and not win32 else 'system32'
    files.append((prefix, f'drive_c/windows/{sysdir}/d3dcompiler_47.dll', Path(cfg['compiler']).read_bytes(), False))
    # Do not write through a shared Windows directory link into a runner.
    targets = [(safe_leaf(base, rel), data, mutable) for base, rel, data, mutable in files]
    root.mkdir(parents=True, exist_ok=True)
    prefix.mkdir(parents=True, exist_ok=True)
    if journal and journal.get('root_id') != directory_id(root):
        # A recreated bottle must get a fresh baseline from its current archive.
        jp.unlink(missing_ok=True)
        journal = {}
    elif journal and journal.get('prefix_id') != directory_id(prefix):
        # A .pc game directory survives recreation of its separate Wine bottle.
        # Restore the surviving game files, but never restore the old compiler
        # over the new bottle's baseline.
        restore_install(home, jp)
        journal = {}
        files[2] = (root, (folder / 'ReShade.ini').as_posix(),
                    profile_ini((profile / 'ReShade.ini').read_text(), cfg).encode(), True)
        files[3] = (root, (folder / 'ReShadePreset.ini').as_posix(),
                    (profile / 'ReShadePreset.ini').read_bytes(), True)
        targets = [(safe_leaf(base, rel), data, mutable) for base, rel, data, mutable in files]
    if journal:
        profile_save(home, rom, root, {'exe': journal['exe']})
        ini = profile_ini((profile / 'ReShade.ini').read_text(), cfg).encode()
        files[2] = (root, (folder / 'ReShade.ini').as_posix(), ini, True)
        files[3] = (root, (folder / 'ReShadePreset.ini').as_posix(), (profile / 'ReShadePreset.ini').read_bytes(), True)
        targets = [(safe_leaf(base, rel), data, mutable) for base, rel, data, mutable in files]
    old_records = journal.get('files', {})
    for target, data, mutable in targets:
        rec = old_records.get(str(target))
        if rec and not mutable and fingerprint(target) not in (None, rec['installed']):
            raise ValueError(f'managed DLL was changed by another tool: {target}')
    if not journal:
        journal = {'rom': str(rom), 'root': str(root), 'prefix': str(prefix), 'exe': cfg['exe'],
                   'files': {}, 'env_words': [], 'root_id': directory_id(root), 'prefix_id': directory_id(prefix)}
    backups = jp.parent / (jp.stem + '-backups')
    backups.mkdir(parents=True, exist_ok=True)
    for target, data, mutable in targets:
        if str(target) not in journal['files']:
            original = fingerprint(target)
            backup = ''
            if original and 'sha256' in original:
                bp = backups / hashlib.sha256(os.fsencode(str(target))).hexdigest()
                atomic_bytes(bp, target.read_bytes())
                backup = str(bp)
            journal['files'][str(target)] = {'original': original, 'backup': backup, 'mutable': mutable,
                                           'installed': {'sha256': hashlib.sha256(data).hexdigest()}}
    autorun = safe_leaf(root, 'autorun.cmd')
    if autorun.is_symlink():
        raise ValueError('autorun.cmd must be a regular file')
    if not autorun.exists():
        atomic_bytes(autorun, autorun_source(rom).encode('utf-8', 'surrogateescape'))
    words = ['WINEDLLOVERRIDES="${WINEDLLOVERRIDES:-};' + cfg['dll'] + '=n,b;d3dcompiler_47=n,b"',
             'UMU_BATOCERA_EXTRA_RO=' + shlex.quote(str(home / 'reshade/runtime')) + ':"${UMU_BATOCERA_EXTRA_RO:-}"']
    text = rewrite_env(autorun.read_text(encoding='utf-8', errors='surrogateescape'), journal.get('env_words', []), words)
    for target, data, mutable in targets:
        rec = journal['files'][str(target)]
        rec['previous_installed'] = fingerprint(target)
        rec['installed'] = {'sha256': hashlib.sha256(data).hexdigest()}
    journal['env_words'] = words
    # Recovery journal precedes ALL DLL/config/ENV changes.
    save_json(jp, journal)
    for target, data, mutable in targets:
        atomic_bytes(target, data)
        journal['files'][str(target)]['installed'] = fingerprint(target)
    atomic_bytes(autorun, text.encode('utf-8', 'surrogateescape'))
    journal['env_words'] = words
    save_json(jp, journal)


def restore_install(home, path):
    journal = read_json(path)
    if not journal:
        return
    root = Path(journal['root'])
    prefix = Path(journal['prefix'])
    ensure_idle(Path(journal['rom']), root, prefix)
    root_current = directory_id(root) == journal.get('root_id')
    prefix_current = directory_id(prefix) == journal.get('prefix_id')
    if root_current:
        profile_save(home, Path(journal['rom']), root, {'exe': journal['exe']})
    targets = []
    for value, rec in journal['files'].items():
        target = Path(value)
        base = prefix if target.is_relative_to(prefix) else root
        if not (prefix_current if base == prefix else root_current):
            continue
        safe_leaf(base, target.relative_to(base).as_posix())
        current = fingerprint(target)
        if not rec['mutable'] and current not in (None, rec['installed'], rec['original'], rec.get('previous_installed')):
            raise ValueError(f'refusing to overwrite a changed DLL: {target}; backup retained in {path.parent}')
        original = rec['original']
        if original and 'sha256' in original and fingerprint(Path(rec['backup'])) != original:
            raise ValueError(f'original backup missing/changed: {rec["backup"]}')
        targets.append((target, rec))
    for target, rec in targets:
        original = rec['original']
        if not original:
            target.unlink(missing_ok=True)
        elif 'link' in original:
            target.unlink(missing_ok=True)
            target.symlink_to(original['link'])
        else:
            atomic_bytes(target, Path(rec['backup']).read_bytes())
    autorun = safe_leaf(root, 'autorun.cmd')
    if root_current and autorun.is_file() and not autorun.is_symlink():
        text = rewrite_env(autorun.read_text(encoding='utf-8', errors='surrogateescape'), journal.get('env_words', []), [])
        atomic_bytes(autorun, text.encode('utf-8', 'surrogateescape'))
    path.unlink()
    shutil.rmtree(path.parent / (path.stem + '-backups'), ignore_errors=True)


def set_enabled(home, rom, enabled):
    config = home / 'reshade/games' / (key(rom) + '.json')
    cfg = read_json(config)
    if not cfg:
        raise ValueError('install ReShade for this game first')
    if not enabled:
        for jp in (home / 'reshade/installations' / key(rom)).glob('*.json'):
            j = read_json(jp)
            ensure_idle(rom, Path(j['root']), Path(j['prefix']))
        cfg['enabled'] = False
        save_json(config, cfg)
        for jp in (home / 'reshade/installations' / key(rom)).glob('*.json'):
            restore_install(home, jp)
    else:
        cfg['enabled'] = True
        save_json(config, cfg)


def event(home, rom, action, runner='', bottles=Path('/userdata/system/wine-bottles/windows'), legacy=False):
    cfg = read_json(home / 'reshade/games' / (key(rom) + '.json'))
    if not cfg:
        if action == 'gameStart':
            import reshade_external
            reshade_external.apply(home, rom, runner, bottles, legacy)
        return
    if action == 'gameStop':
        for jp in (home / 'reshade/installations' / key(rom)).glob('*.json'):
            j = read_json(jp)
            if Path(j['root']).exists():
                profile_save(home, rom, Path(j['root']), {'exe': j['exe']})
        return
    if action != 'gameStart':
        return
    if not cfg['enabled']:
        for jp in (home / 'reshade/installations' / key(rom)).glob('*.json'):
            restore_install(home, jp)
        return
    valid_rom(rom)
    root, prefix = locations(rom, runner, bottles, legacy)
    if rom.suffix.casefold() == '.wsquashfs':
        # Check the archive still contains the configured executable after updates.
        if pe_arch(source_header(rom, cfg['exe'])) != cfg['arch']:
            raise ValueError('executable architecture changed; reconfigure ReShade')
    elif not safe_leaf(rom, cfg['exe']).is_file():
        raise ValueError('configured executable is missing; reconfigure ReShade')
    for old_path in (home / 'reshade/installations' / key(rom)).glob('*.json'):
        j = read_json(old_path)
        if j['root'] == str(root) and j['prefix'] != str(prefix):
            restore_install(home, old_path)
    try:
        install_files(home, rom, root, prefix, cfg)
    except Exception:
        jp = journal_path(home, rom, root, prefix)
        if jp.exists():
            restore_install(home, jp)
        raise


@contextlib.contextmanager
def locked(home):
    home.mkdir(parents=True, exist_ok=True)
    with (home / 'reshade-manager.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def list_statuses(home, paths):
    """Read the small local configuration directory once, never open game archives."""
    games = [p for p in paths if Path(p).suffix.casefold() in ('.wine', '.pc', '.wsquashfs')]
    wanted = {key(p) for p in games}
    states = {}
    for config in (home / 'reshade/games').glob('*.json'):
        if config.stem in wanted:
            cfg = read_json(config)
            states[config.stem] = 'enabled' if cfg.get('enabled') else 'disabled' if cfg else 'missing'
    import reshade_external
    for config in (home / 'reshade/external').glob('*.json'):
        if config.stem in wanted and config.stem not in states:
            states[config.stem] = reshade_external.state(read_json(config))
    return [(p, states.get(key(p), 'missing')) for p in games]


def configured_games(home, enabled_only=False):
    games = []
    for config in (home / 'reshade/games').glob('*.json'):
        cfg = read_json(config)
        if not cfg or (enabled_only and not cfg.get('enabled')):
            continue
        path = Path(cfg['rom'])
        if path.suffix.casefold() in ('.wine', '.pc', '.wsquashfs') and path.exists():
            games.append((str(path), 'enabled' if cfg.get('enabled') else 'disabled'))
    import reshade_external
    known = {p for p, _ in games}
    for config in (home / 'reshade/external').glob('*.json'):
        cfg = read_json(config)
        if not cfg.get('files') or cfg['rom'] in known or not Path(cfg['rom']).exists():
            continue
        status = reshade_external.state(cfg)
        if not enabled_only or status == 'external-enabled':
            games.append((cfg['rom'], status))
    return sorted(games, key=lambda item: item[0].casefold())


def export_preset(home, rom, destination, overwrite=False):
    cfg = read_json(home / 'reshade/games' / (key(rom) + '.json'))
    if not cfg:
        raise ValueError('install ReShade for this game first')
    destination = Path(destination)
    source = home / 'reshade/profiles' / key(rom) / 'ReShadePreset.ini'
    if destination.suffix.casefold() != '.ini' or destination.is_symlink() or destination.resolve() == source.resolve():
        raise ValueError('choose a separate regular .ini export file')
    if destination.exists() and not overwrite:
        raise ValueError('export destination exists; confirm overwrite')
    journals = list((home / 'reshade/installations' / key(rom)).glob('*.json'))
    for jp in journals:
        j = read_json(jp)
        ensure_idle(rom, Path(j['root']), Path(j['prefix']))
    for jp in journals:
        j = read_json(jp)
        if directory_id(Path(j['root'])) == j.get('root_id'):
            profile_save(home, rom, Path(j['root']), {'exe': j['exe']})
    atomic_bytes(destination, source.read_bytes())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', type=Path, default=Path('/userdata/system/ultimate-wine-toolbox'))
    parser.add_argument('--bottles', type=Path, default=Path('/userdata/system/wine-bottles/windows'))
    parser.add_argument('--runner', default='')
    parser.add_argument('--legacy', action='store_true')
    parser.add_argument('command', choices=['exes', 'prepare', 'finish', 'status', 'status-list', 'configured-list', 'export', 'api', 'external-scan', 'external-info', 'external-enable', 'external-disable', 'external-release', 'wiki-title', 'wiki-search', 'wiki-page', 'enable', 'disable', 'uninstall',
                                           'gameStart', 'gameStop', 'disable-all', 'preset', 'profile', 'details'])
    parser.add_argument('rom', nargs='?', type=Path)
    parser.add_argument('args', nargs='*')
    args = parser.parse_args()
    home = args.home.resolve()
    if any(c in str(home) for c in ':;\n\r\t'):
        raise ValueError('unsupported toolbox path')
    rom = Path(os.path.abspath(args.rom)) if args.rom else None
    with locked(home):
        if args.command == 'exes':
            valid_rom(rom)
            for exe in executable_list(rom):
                print(exe)
        elif args.command == 'prepare':
            print(prepare(home, rom, *args.args))
        elif args.command == 'finish':
            print(json.dumps(finish(home, rom)))
        elif args.command == 'status-list':
            paths = sys.stdin.read().splitlines()
            for path, state in list_statuses(home, paths):
                sys.stdout.buffer.write(os.fsencode(path) + b'\0' + state.encode() + b'\0')
        elif args.command == 'configured-list':
            for path, state in configured_games(home, str(args.rom) == 'enabled'):
                sys.stdout.buffer.write(os.fsencode(path) + b'\0' + state.encode() + b'\0')
        elif args.command == 'export':
            export_preset(home, rom, args.args[0], args.args[1:] == ['overwrite'])
        elif args.command == 'wiki-title':
            import reshade_api
            print(reshade_api.game_title(str(args.rom)))
        elif args.command.startswith('external-'):
            import reshade_external
            if args.command == 'external-scan':
                paths = sys.stdin.read().splitlines()
                failures = 0
                for number, path in enumerate(paths, 1):
                    try:
                        if not read_json(home / 'reshade/games' / (key(path)+'.json')):
                            reshade_external.scan_game(home, Path(path))
                    except (ValueError, OSError):
                        failures += 1
                        print('Unable to inspect: '+path, file=sys.stderr)
                    print(f'{number}/{len(paths)} {path}', file=sys.stderr, flush=True)
                if failures:
                    raise ValueError(f'{failures} games could not be inspected; index of other games retained')
            elif args.command == 'external-info':
                cfg = reshade_external.scan_game(home, rom)
                print(reshade_external.state(cfg))
                for file in cfg.get('files', []):
                    print(file['path'])
            elif args.command == 'external-release':
                reshade_external.release(home, rom)
            else:
                reshade_external.toggle(home, rom, args.command == 'external-enable', args.runner, args.bottles, args.legacy)
        elif args.command == 'api':
            import reshade_api
            exe = relative(args.args[0])
            header = source_header(rom, exe, 16*1024*1024)
            candidates, kind, evidence = reshade_api.detect(header)
            imports = reshade_api.imported_dlls(header)
            if 'unityplayer.dll' in imports:
                try:
                    c, k, e = reshade_api.detect(source_header(rom, (PurePosixPath(exe).parent / 'UnityPlayer.dll').as_posix(), 16*1024*1024))
                    candidates = sorted(set(candidates+c))
                    evidence += ['UnityPlayer: '+v for v in e]
                except (OSError, ValueError):
                    pass
            print(','.join(candidates) + '\t' + kind + '\t' + ', '.join(evidence))
        elif args.command in ('wiki-search', 'wiki-page'):
            import reshade_api
            # Query text is the positional argument, not a filesystem path.
            title = str(args.rom)
            if args.command == 'wiki-search':
                for name in reshade_api.wiki_search(title):
                    print(name.replace('\n', ' ').replace('\t', ' '))
            else:
                candidates, evidence = reshade_api.wiki_page(title)
                print(','.join(candidates) + '\t' + ', '.join(evidence))
        elif args.command == 'status':
            cfg = read_json(home / 'reshade/games' / (key(rom) + '.json'))
            print('enabled' if cfg.get('enabled') else 'disabled' if cfg else 'missing')
        elif args.command in ('enable', 'disable', 'uninstall'):
            set_enabled(home, rom, args.command == 'enable')
            if args.command == 'enable':
                try:
                    event(home, rom, 'gameStart', args.runner, args.bottles, args.legacy)
                except Exception:
                    set_enabled(home, rom, False)
                    raise
            elif args.command == 'uninstall':
                (home / 'reshade/games' / (key(rom) + '.json')).unlink()
        elif args.command in ('gameStart', 'gameStop'):
            event(home, rom, args.command, args.runner, args.bottles, args.legacy)
        elif args.command == 'disable-all':
            import reshade_external
            for config in (home / 'reshade/external').glob('*.json'):
                cfg = read_json(config)
                if cfg.get('controlled'):
                    reshade_external.release(home, Path(cfg['rom']))
            for config in (home / 'reshade/games').glob('*.json'):
                cfg = read_json(config)
                set_enabled(home, Path(cfg['rom']), False)
        elif args.command == 'details':
            cfg = read_json(home / 'reshade/games' / (key(rom) + '.json'))
            if cfg:
                print('\t'.join(map(str, [Path(cfg['runtime']).parent.name, cfg['arch'], cfg['dll'], cfg['exe'], cfg['repos']])))
        elif args.command == 'profile':
            print(home / 'reshade/profiles' / key(rom))
        elif args.command == 'preset':
            data = Path(args.args[0]).read_bytes()
            if b'\0' in data or len(data) > 1024*1024:
                raise ValueError('invalid preset INI')
            data.decode('utf-8-sig')
            cfg = read_json(home / 'reshade/games' / (key(rom) + '.json'))
            for jp in (home / 'reshade/installations' / key(rom)).glob('*.json'):
                j = read_json(jp)
                ensure_idle(rom, Path(j['root']), Path(j['prefix']))
                if directory_id(Path(j['root'])) == j.get('root_id'):
                    target = safe_leaf(Path(j['root']), (PurePosixPath(j['exe']).parent / 'ReShadePreset.ini').as_posix())
                    atomic_bytes(target, data)
            atomic_bytes(home / 'reshade/profiles' / key(rom) / 'ReShadePreset.ini', data)
            cfg = read_json(home / 'reshade/games' / (key(rom) + '.json'))
            if cfg.get('enabled'):
                event(home, rom, 'gameStart', args.runner, args.bottles, args.legacy)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
