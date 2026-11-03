#!/usr/bin/env python3
"""Local ReShade bundles. Never load add-ons while inspecting an archive."""
import configparser
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import zipfile

import reshade_manager as m

LIMIT = 256 * 1024 * 1024
FILE_LIMIT = 32 * 1024 * 1024
ASSETS = {'.fx', '.fxh', '.png', '.jpg', '.jpeg', '.dds', '.bmp', '.tga', '.gif', '.txt', '.md', '.h', '.hlsl'}
STAGE = 'UWT-ReShadePack'


def ini(data, preset=False):
    if len(data) > 1024 * 1024 or b'\0' in data:
        raise ValueError('invalid pack INI')
    text = data.decode('utf-8-sig')
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    parser.read_string(('[UWT_PRESET]\n' if preset else '') + text)
    if preset and not parser.has_option('UWT_PRESET', 'Techniques'):
        raise ValueError('pack preset has no Techniques entry')
    return parser


def encode_ini(parser, preset=False):
    out = io.StringIO()
    parser.write(out, space_around_delimiters=False)
    text = out.getvalue()
    if preset:
        text = text.replace('[UWT_PRESET]\n', '', 1)
    return text.encode()


def archive(path):
    """Read allowlisted payloads into memory, with bounds and Windows path checks."""
    files, seen, total = {}, set(), 0
    with zipfile.ZipFile(path) as z:
        if len(z.infolist()) > 4096:
            raise ValueError('too many pack files')
        for item in z.infolist():
            name = item.filename
            p = PurePosixPath(name)
            if (p.is_absolute() or '..' in p.parts or '\\' in name or any(c in name for c in ':*?"<>|')
                    or any(ord(c) < 32 for c in name) or len(name) > 240
                    or any(part.rstrip(' .') != part for part in p.parts)
                    or any(re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part) for part in p.parts)):
                raise ValueError('unsafe pack archive path')
            if stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError('pack links are not supported')
            if item.is_dir():
                continue
            if p.as_posix().casefold() in seen:
                raise ValueError('duplicate pack filename')
            seen.add(p.as_posix().casefold())
            total += item.file_size
            if total > LIMIT or item.file_size > FILE_LIMIT:
                raise ValueError('pack exceeds size limit')
            # No executables, runtime DLLs or scripts are imported from bundles.
            allowed = ((len(p.parts) == 1 and p.suffix.lower() in ('.ini', '.addon', '.addon32', '.addon64'))
                       or (p.parts[:1] == ('reshade-shaders',) and p.suffix.lower() in ASSETS))
            if allowed:
                files[p.as_posix()] = z.read(item)
    if 'ReShade.ini' not in files or not any(n.startswith('reshade-shaders/Shaders/') for n in files):
        raise ValueError('ZIP requires ReShade.ini and reshade-shaders/Shaders at its root')
    config = ini(files['ReShade.ini'])
    presets = []
    for name, data in files.items():
        if '/' not in name and name.lower().endswith('.ini') and name.lower() not in ('reshade.ini', 'reshade2.ini', 'reshadegui.ini'):
            try:
                ini(data, True)
            except (ValueError, configparser.Error):
                continue
            presets.append(name)
    addons = {n: m.pe_arch(d) for n, d in files.items() if PurePosixPath(n).suffix.lower() in ('.addon', '.addon32', '.addon64')}
    for name, bits in addons.items():
        extension = PurePosixPath(name).suffix
        if extension not in ('.addon', f'.addon{bits}'):
            raise ValueError('add-on extension must match its architecture and use lowercase')
    if len(set(addons.values())) > 1:
        raise ValueError('this local import requires add-ons of a single architecture')
    citra = 'citra.addon' in addons and 'reshade-shaders/Shaders/Citra.fx' in files
    preferred = config.get('GENERAL', 'PresetPath', fallback='').replace('\\', '/').removeprefix('./')
    if not presets:
        raise ValueError('no presets found in pack')
    return files, {'schema': 1, 'presets': sorted(presets), 'preferred': preferred if preferred in presets else sorted(presets)[0],
                   'addons': addons, 'required_release': '6.3.3-addons' if citra else '',
                   'citra': citra, 'files': len(files), 'bytes': total}


def check_release(cfg, metadata):
    from reshade_versions import selection
    if metadata['required_release'] and cfg.get('release_id') != metadata['required_release']:
        raise ValueError('this Citra pack requires ReShade 6.3.3 with full add-on support (6.3.3-addons)')
    if metadata['addons']:
        if selection(cfg.get('release_id', '')).get('addon_support') != 'full':
            raise ValueError('install a ReShade build with verified full add-on support first')
        if any(bits != cfg['arch'] for bits in metadata['addons'].values()):
            raise ValueError('pack add-on architecture differs from the selected executable')


def merge_config(base, supplied):
    result, source = ini(base), ini(supplied)
    allowed = {'ADDON': {'DisabledAddons'},
               'DEPTH': {'DepthCopyAtClearIndex', 'DepthCopyBeforeClears', 'UseAspectRatioHeuristics'},
               'GENERAL': {'PreprocessorDefinitions'}}
    for section, keys in allowed.items():
        for key in keys:
            if source.has_option(section, key):
                if not result.has_section(section):
                    result.add_section(section)
                value = source[section][key]
                if re.search(r'[A-Za-z]:[\\/]|/userdata/|/home/|[\r\n]', value):
                    raise ValueError('machine-specific pack configuration')
                result[section][key] = value
    if not result.has_section('GENERAL'):
        result.add_section('GENERAL')
    # Keep uniforms editable during the first in-game depth/layout setup.
    result['GENERAL']['PerformanceMode'] = '0'
    return encode_ini(result)


def preset_bytes(data, metadata):
    result = ini(data, True)
    for section in result.sections():
        for name in list(result[section]):
            if name.lower() in ('effectsearchpaths', 'texturesearchpaths', 'presetpath'):
                del result[section][name]
            elif re.search(r'[A-Za-z]:[\\/]|/userdata/|/home/|\\\\', result[section][name]):
                raise ValueError('machine-specific preset path')
    if metadata['citra']:
        # The supplied README requires this pass before the other effects.
        technique = 'Citra@Citra.fx'
        for key in ('Techniques', 'TechniqueSorting'):
            values = result['UWT_PRESET'].get(key, '').split(',')
            result['UWT_PRESET'][key] = ','.join([technique] + [v for v in values if v and v != technique])
    return encode_ini(result, True)


def profile(home, rom):
    return home / 'reshade/profiles' / m.key(rom)


def manifest(home, rom):
    return m.read_json(profile(home, rom) / 'pack/manifest.json')


def install(home, rom, source, preset, runner='', bottles=Path('/userdata/system/wine-bottles/windows'), legacy=False):
    files, meta = archive(source)
    config_path = home / 'reshade/games' / (m.key(rom) + '.json')
    cfg = m.read_json(config_path)
    if not cfg:
        raise ValueError('install ReShade for this game first')
    check_release(cfg, meta)
    if preset not in meta['presets']:
        raise ValueError('select a preset from the pack')
    p = profile(home, rom)
    if cfg.get('pack') or (p / 'pack').exists():
        raise ValueError('remove the current pack before importing another one')
    # Validate all output before touching the game, profile or enabled state.
    chosen = preset_bytes(files[preset], meta)
    # Validate every variant before modifying an existing installation.
    for name in meta['presets']:
        preset_bytes(files[name], meta)
    merged = merge_config((p / 'ReShade.ini').read_bytes(), files['ReShade.ini'])
    payload = {n: data for n, data in files.items() if n.startswith('reshade-shaders/') or n in meta['addons']}
    meta.update(selected=preset, archive_sha256=hashlib.sha256(Path(source).read_bytes()).hexdigest(),
                hashes={n: hashlib.sha256(d).hexdigest() for n, d in payload.items()})
    was_enabled = cfg.get('enabled', False)
    from reshade_presets import sync
    sync(home, rom)
    # Disable captures current in-game edits before taking the profile snapshot.
    m.set_enabled(home, rom, False)
    merged = merge_config((p / 'ReShade.ini').read_bytes(), files['ReShade.ini'])
    old = {n: (p / n).read_bytes() for n in ('ReShade.ini', 'ReShadePreset.ini')}
    try:
        with tempfile.TemporaryDirectory(prefix='.pack-', dir=p) as temp:
            stage = Path(temp)
            for n, data in payload.items():
                m.atomic_bytes(stage / 'assets' / n, data)
            for n, data in old.items():
                m.atomic_bytes(stage / 'before' / n, data)
            m.save_json(stage / 'manifest.json', meta)
            stage.rename(p / 'pack')
        m.atomic_bytes(p / 'ReShade.ini', merged)
        m.atomic_bytes(p / 'ReShadePreset.ini', chosen)
        cfg.update(pack=True, enabled=False)
        m.save_json(config_path, cfg)
        m.set_enabled(home, rom, was_enabled)
        if was_enabled:
            m.event(home, rom, 'gameStart', runner, bottles, legacy)
        from reshade_presets import pack_presets
        pack_presets(home, rom, files, meta, preset)
    except Exception:
        m.set_enabled(home, rom, False)
        for n, data in old.items():
            m.atomic_bytes(p / n, data)
        cfg.pop('pack', None)
        cfg['enabled'] = False
        m.save_json(config_path, cfg)
        shutil.rmtree(p / 'pack', ignore_errors=True)
        m.set_enabled(home, rom, was_enabled)
        if was_enabled:
            m.event(home, rom, 'gameStart', runner, bottles, legacy)
        raise
    return meta


def remove(home, rom, runner='', bottles=Path('/userdata/system/wine-bottles/windows'), legacy=False):
    config_path = home / 'reshade/games' / (m.key(rom) + '.json')
    cfg = m.read_json(config_path)
    if not cfg.get('pack'):
        raise ValueError('no local ReShade pack installed')
    p = profile(home, rom)
    old = {n: (p / 'pack/before' / n).read_bytes() for n in ('ReShade.ini', 'ReShadePreset.ini')}
    was_enabled = cfg.get('enabled', False)
    m.set_enabled(home, rom, False)
    active = {n: (p / n).read_bytes() for n in old}
    # Keep the snapshot/assets until the restored configuration is installed.
    try:
        for n, data in old.items():
            m.atomic_bytes(p / n, data)
        cfg.pop('pack')
        cfg['enabled'] = False
        m.save_json(config_path, cfg)
        if was_enabled:
            m.set_enabled(home, rom, True)
            m.event(home, rom, 'gameStart', runner, bottles, legacy)
    except Exception:
        m.set_enabled(home, rom, False)
        for n, data in active.items():
            m.atomic_bytes(p / n, data)
        cfg.update(pack=True, enabled=False)
        m.save_json(config_path, cfg)
        raise
    shutil.rmtree(p / 'pack')
    from reshade_presets import capture
    capture(home, rom, adopt=True)


def stage_files(home, rom, root, folder, cfg):
    if not cfg.get('pack'):
        return []
    meta = manifest(home, rom)
    check_release(cfg, meta)
    files = []
    for name, expected in meta['hashes'].items():
        name = m.relative(name)
        path = m.safe_leaf(profile(home, rom) / 'pack/assets', name)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('local ReShade pack asset changed; remove and import the pack again')
        target = name if name in meta['addons'] else STAGE + '/' + name
        files.append((root, (folder / target).as_posix(), data, False))
    return files
