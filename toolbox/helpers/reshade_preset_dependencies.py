"""Inspect preset FX files and add shaders through isolated, transactional views."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import uuid

import reshade_manager as m
import reshade_presets as p
from reshade_preset_effects import INDEX


def config_path(home, rom):
    return home / 'reshade/games' / (m.key(rom) + '.json')


def configuration(home, rom):
    cfg = m.read_json(config_path(home, rom))
    if not cfg:
        raise ValueError('configure ReShade with the Toolbox before installing missing shaders')
    return cfg


def overlay(home, rom, cfg):
    view = cfg.get('preset_shaders')
    if not view or view.get('context') != p.context(home, rom) or view.get('base') != cfg.get('shaders'):
        return None
    root = Path(view['root'])
    if root.is_symlink() or not root.resolve().is_relative_to((home / 'reshade/runtime').resolve()):
        raise ValueError('invalid per-game shader view')
    if not (root / 'Shaders').is_dir():
        raise ValueError('per-game shaders missing; reinstall the required shader packs')
    return view


def shader_root(home, rom, cfg):
    view = overlay(home, rom, cfg)
    if view:
        return Path(view['root'])
    if cfg.get('pack'):
        return p.folder(home, rom) / 'pack/assets/reshade-shaders'
    root = Path(cfg['shaders']).resolve()
    if not root.is_relative_to((home / 'reshade/runtime').resolve()):
        raise ValueError('shader cache is outside the Toolbox runtime cache')
    return root / 'Merged'


def available(root):
    effects = {}
    for path in (root / 'Shaders').rglob('*'):
        if path.is_file() and path.suffix.lower() == '.fx':
            effects.setdefault(path.name.casefold(), []).append(path)
    return effects


def analyze(home, rom, source, index=INDEX, cfg=None, root=None):
    cfg = cfg or configuration(home, rom)
    data = Path(source).read_bytes()
    parser = p.ini(data, True)
    catalog = json.loads(Path(index).read_text())['packs']
    names = {}
    for pack, files in catalog.items():
        for name in files:
            names.setdefault(name.casefold(), set()).add(pack)
    root = Path(root) if root is not None else shader_root(home, rom, cfg)
    existing = available(root)
    refs, aliases = set(), set()
    for technique in parser['UWT_PRESET'].get('Techniques', '').split(','):
        technique = technique.strip()
        if not technique:
            continue
        if '@' in technique:
            name = PurePosixPath(technique.split('@', 1)[1].replace('\\', '/')).name
            if name.lower().endswith('.fx'):
                refs.add(name)
            else:
                aliases.add(technique)
        else:
            name = technique + '.fx'
            if name.casefold() in existing or name.casefold() in names:
                refs.add(name)
            else:
                aliases.add(technique)
    if aliases:
        defined = set()
        for paths in existing.values():
            for path in paths:
                if path.stat().st_size <= 2 * 1024 * 1024:
                    defined.update(re.findall(r'\btechnique\d*\s+(\w+)', path.read_text(errors='replace')))
        aliases.difference_update(defined)
    missing = sorted((name for name in refs if name.casefold() not in existing), key=str.casefold)
    packs, ambiguous, unknown = set(), {}, sorted(aliases)
    installed = set(cfg.get('repos', '').split(',')) | set(cfg.get('preset_shaders', {}).get('packs', []))
    for name in missing:
        options = names.get(name.casefold(), set())
        preferred = options & installed
        if len(options) == 1:
            packs.update(options)
        elif len(preferred) == 1:
            packs.update(preferred)
        elif options:
            ambiguous[name] = sorted(options)
        else:
            unknown.append(name)
    for name, options in list(ambiguous.items()):
        covered = set(options) & packs
        if len(covered) == 1:
            del ambiguous[name]
    return {'files': sorted(refs), 'missing': missing, 'packs': sorted(packs),
            'ambiguous': ambiguous, 'unknown': unknown, 'sha256': hashlib.sha256(data).hexdigest()}


def idle(home, rom, cfg, runner='', bottles=Path('/userdata/system/wine-bottles/windows'), legacy=False):
    root, prefix = m.locations(rom, runner, bottles, legacy)
    m.ensure_idle(rom, root, prefix)
    for path in (home / 'reshade/installations' / m.key(rom)).glob('*.json'):
        value = m.read_json(path)
        m.ensure_idle(rom, Path(value['root']), Path(value['prefix']))


def prepare(home, rom, source, packs, expected, runner='', bottles=Path('/userdata/system/wine-bottles/windows'), legacy=False):
    cfg = configuration(home, rom)
    idle(home, rom, cfg, runner, bottles, legacy)
    report = analyze(home, rom, source)
    if report['sha256'] != expected:
        raise ValueError('preset changed during review; select it again')
    selected = set(packs.split(','))
    catalog = json.loads(INDEX.read_text())['packs']
    if not selected or not selected.issubset(catalog):
        raise ValueError('invalid shader pack selection')
    if not set(report['packs']).issubset(selected) or any(not selected.intersection(options) for options in report['ambiguous'].values()):
        raise ValueError('not all recognized missing effects are covered')
    job = home / 'reshade/runtime/preset-effects' / m.key(rom) / uuid.uuid4().hex
    job.mkdir(parents=True)
    m.save_json(job / 'pending.json', {'rom': str(rom), 'source': str(Path(source).absolute()), 'sha256': expected,
                                      'config_hash': hashlib.sha256(config_path(home, rom).read_bytes()).hexdigest(),
                                      'packs': sorted(selected), 'missing': [n for n in report['missing'] if n not in report['unknown']]})
    return job


def merge(base, extra, destination):
    """Preserve the existing files, including custom versions supplied by packs."""
    for part in ('Shaders', 'Textures'):
        (destination / part).mkdir(parents=True, exist_ok=True)
    seen, effects = set(), set()
    for number, root in enumerate((base, extra)):
        groups = [sorted((root / part).rglob('*')) for part in ('Shaders', 'Textures')]
        groups.append(sorted(root.glob('*.fxh')))
        for sources in groups:
            for source in sources:
                if not source.is_file():
                    continue
                rel = source.relative_to(root)
                name = rel.as_posix().casefold()
                effect = source.name.casefold() if source.suffix.lower() == '.fx' else ''
                if name in seen or (number and effect and effect in effects):
                    continue
                target = destination / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                seen.add(name)
                if effect:
                    effects.add(effect)


def finish(home, rom, job, runner='', bottles=Path('/userdata/system/wine-bottles/windows'), legacy=False):
    job = Path(job)
    if job.is_symlink() or not job.resolve().is_relative_to((home / 'reshade/runtime/preset-effects' / m.key(rom)).resolve()):
        raise ValueError('invalid shader installation workspace')
    pending = m.read_json(job / 'pending.json')
    cfg = configuration(home, rom)
    idle(home, rom, cfg, runner, bottles, legacy)
    if pending.get('rom') != str(rom) or hashlib.sha256(config_path(home, rom).read_bytes()).hexdigest() != pending['config_hash']:
        raise ValueError('ReShade configuration changed during download; retry the import')
    if hashlib.sha256(Path(pending['source']).read_bytes()).hexdigest() != pending['sha256']:
        raise ValueError('preset changed during shader installation; retry the import')
    extra = job / 'cache/game-shaders/preset/Merged'
    if not (extra / 'Shaders').is_dir():
        raise ValueError('shader download did not produce the expected files')
    from reshade_extra_shaders import PACK, install as install_extra_shaders
    if PACK in pending['packs']:
        install_extra_shaders(home, extra.parent)
    combined = job / 'Combined'
    if combined.exists():
        raise ValueError('shader workspace was already finalized; retry the import')
    merge(shader_root(home, rom, cfg), extra, combined)
    report = analyze(home, rom, pending['source'], cfg=cfg, root=combined)
    if any(n in report['missing'] for n in pending['missing']):
        raise ValueError('a required effect is still missing after download; current presets were retained')
    old = overlay(home, rom, cfg)
    cfg['preset_shaders'] = {'root': str(combined), 'context': p.context(home, rom), 'base': cfg['shaders'],
                             'packs': sorted(set(pending['packs']) | set(old.get('packs', []) if old else []))}
    m.save_json(config_path(home, rom), cfg)
    return report
