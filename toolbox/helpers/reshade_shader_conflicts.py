"""Choose one FX per filename in a private per-game view; shared caches stay intact."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

import reshade_manager as m


def effect_key(name):
    path = Path(name)
    return path.name.casefold() if path.suffix.casefold() == '.fx' else ''


def contents(value):
    return value.read_bytes() if isinstance(value, Path) else value


def unique(files, *, require_unique=True):
    """Identical copies in subfolders are one effect; differing variants need review."""
    result, effects, duplicates = {}, {}, []
    for name in sorted(files, key=lambda n: (len(Path(n).parts), n.casefold(), n)):
        data = files[name]
        effect = effect_key(name)
        if effect and effect in effects:
            winner = effects[effect]
            if contents(data) != contents(result[winner]):
                if require_unique:
                    raise ValueError(f'ambiguous shader variants inside one library: {winner}, {name}')
                result[name] = data
                continue
            duplicates.append({'name': Path(name).name, 'kept': winner, 'removed': name})
            continue
        result[name] = data
        if effect:
            effects[effect] = name
    return result, duplicates


def library(home, root):
    files = {}
    paths = list(root.glob('*.fxh'))
    for part in ('Shaders', 'Textures'):
        paths.extend((root / part).rglob('*'))
    for path in paths:
        if path.is_file():
            if not path.resolve().is_relative_to(home.resolve()):
                raise ValueError('shader library outside Toolbox cache')
            files[path.relative_to(root).as_posix()] = path
    return files


def installed(home, rom, cfg):
    from reshade_preset_dependencies import shader_root
    return unique(library(home, shader_root(home, rom, cfg)))[0]


def plan(home, rom, files, cfg):
    base = installed(home, rom, cfg)
    custom, duplicates = unique({n.removeprefix('reshade-shaders/'): d for n, d in files.items()
                                  if n.startswith('reshade-shaders/')})
    base_fx = {effect_key(n): (n, d) for n, d in base.items() if effect_key(n)}
    conflicts = []
    for name, data in custom.items():
        key = effect_key(name)
        if key and key in base_fx:
            old, path = base_fx[key]
            conflicts.append({'name': Path(name).name, 'pack': name, 'installed': old,
                              'identical': hashlib.sha256(data).digest() == hashlib.sha256(path.read_bytes()).digest()})
    stamp = [(n, p.stat().st_dev, p.stat().st_ino, p.stat().st_size, p.stat().st_mtime_ns, p.stat().st_ctime_ns) for n, p in sorted(base.items())]
    stamp += [(n, hashlib.sha256(d).hexdigest()) for n, d in sorted(files.items())]
    expected = hashlib.sha256(json.dumps(stamp).encode()).hexdigest()
    return {'conflicts': conflicts, 'duplicates': duplicates, 'expected': expected}


def build(home, rom, cfg, assets, policy):
    if policy not in ('pack', 'installed'):
        raise ValueError('choose pack or installed shader priority')
    base = installed(home, rom, cfg)
    custom = unique({p.relative_to(assets).as_posix(): p for p in assets.rglob('*') if p.is_file()})[0]
    # Select the preferred source first, including its exact relative includes.
    sources = (custom, base) if policy == 'pack' else (base, custom)
    chosen, effects, paths = {}, set(), set()
    for source in sources:
        for name, path in source.items():
            key = effect_key(name)
            if name.casefold() in paths or (key and key in effects):
                continue
            chosen[name] = path
            paths.add(name.casefold())
            if key:
                effects.add(key)
    return make_view(home, rom, chosen)


def make_view(home, rom, chosen):
    parent = home / 'reshade/runtime/pack-shaders' / m.key(rom)
    if parent.resolve() != parent:
        raise ValueError('redirected shader view directory')
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='view-', dir=parent))
    try:
        for name, path in chosen.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(path.resolve())
        (root / 'Shaders').mkdir(exist_ok=True)
        (root / 'Textures').mkdir(exist_ok=True)
    except Exception:
        shutil.rmtree(root)
        raise
    return root


def remove_view(home, rom, root):
    path = Path(root)
    parent = home / 'reshade/runtime/pack-shaders' / m.key(rom)
    if path.parent != parent or parent.resolve() != parent or path.is_symlink() or not path.name.startswith('view-'):
        raise ValueError('invalid private shader view')
    if path.exists():
        shutil.rmtree(path)
