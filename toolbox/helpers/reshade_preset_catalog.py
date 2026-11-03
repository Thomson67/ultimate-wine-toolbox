"""Global preset management, including missing games and detached collections."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import uuid
import zipfile

import reshade_manager as m
import reshade_presets as p


def profile(home, identity):
    if not re.fullmatch(r'[a-f0-9]{24}', identity):
        raise ValueError('invalid preset collection identifier')
    result = Path(home) / 'reshade/profiles' / identity
    if result.is_symlink() or not result.is_dir():
        raise ValueError('preset collection no longer exists')
    return result


def association(home, identity):
    root = profile(home, identity)
    cfgfile = Path(home) / 'reshade/games' / (identity + '.json')
    cfg = m.read_json(cfgfile)
    index = m.read_json(root / 'presets/index.json')
    candidates = [cfg, index, m.read_json(Path(home) / 'reshade/workspaces' / identity / 'pending.json')]
    candidates.extend(m.read_json(j) for j in (Path(home) / 'reshade/installations' / identity).glob('*.json'))
    rom = next((Path(v['rom']) for v in candidates if v.get('rom') and m.key(v['rom']) == identity), None)
    present = bool(rom and rom.exists() and not rom.is_symlink())
    status = 'unknown' if not rom else 'missing' if not present else 'uninstalled' if not cfg else 'present'
    return {'id': identity, 'rom': str(rom) if rom else '', 'name': rom.name if rom else identity,
            'status': status, 'installed': bool(cfg), 'present': present,
            'orphan': not present or not cfg}


def collections(home):
    result = []
    for root in (Path(home) / 'reshade/profiles').glob('*'):
        if not re.fullmatch(r'[a-f0-9]{24}', root.name) or root.is_symlink() or not root.is_dir():
            continue
        data = m.read_json(root / 'presets/index.json')
        count = len(data.get('items', {}))
        if not data and not (root / 'ReShadePreset.ini').is_file():
            continue
        item = association(home, root.name)
        item.update(count=count if data else 1)
        result.append(item)
    return sorted(result, key=lambda row: (not row['orphan'], row['name'].casefold()))


def load(home, identity):
    root = profile(home, identity)
    item = association(home, identity)
    cfg = m.read_json(Path(home) / 'reshade/games' / (identity + '.json'))
    if item['rom'] and item['installed'] and (not item['orphan'] or cfg.get('enabled')):
        # This also captures edits in a surviving wsquashfs bottle. No archive
        # or game-directory existence is required by the local preset sync.
        p.sync(home, Path(item['rom']))
    data = m.read_json(root / 'presets/index.json')
    if not data:
        source = root / 'ReShadePreset.ini'
        payload = p.checked(source.read_bytes())
        key = uuid.uuid4().hex[:24]
        now = datetime.now(timezone.utc).isoformat(timespec='seconds')
        m.atomic_bytes(root / 'presets' / (key + '.ini'), payload)
        data = {'schema': 1, 'active': key, 'rom': item['rom'], 'items': {
            key: {'name': 'ReShadePreset.ini', 'source_name': 'ReShadePreset.ini', 'origin': 'current',
                  'pack': '', 'sha256': hashlib.sha256(payload).hexdigest(), 'created': now, 'updated': now}}}
        m.save_json(root / 'presets/index.json', data)
    if data.get('schema') != 1:
        raise ValueError('unsupported preset collection')
    if item['rom'] and data.get('rom') != item['rom']:
        data['rom'] = item['rom']
        m.save_json(root / 'presets/index.json', data)
    return root, item, data


def items(home, identity):
    _, info, data = load(home, identity)
    return dict(info, items=[dict(value, id=key, active=key == data.get('active'))
                            for key, value in sorted(data['items'].items(), key=lambda row: row[1]['name'].casefold())])


def preset_path(root, key):
    if not re.fullmatch(r'[a-f0-9]{24}', key):
        raise ValueError('invalid preset identifier')
    path = root / 'presets' / (key + '.ini')
    if path.is_symlink():
        raise ValueError('preset must be a regular file')
    return path


def rename(home, identity, key, name):
    root, _, data = load(home, identity)
    data['items'][key]['name'] = p.title(name)
    m.save_json(root / 'presets/index.json', data)


def duplicate(home, identity, key, name):
    root, _, data = load(home, identity)
    item = dict(data['items'][key])
    payload = p.checked(preset_path(root, key).read_bytes())
    name = p.title(name)
    new = uuid.uuid4().hex[:24]
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    item.update(name=name, created=now, updated=now)
    m.atomic_bytes(preset_path(root, new), payload)
    data['items'][new] = item
    m.save_json(root / 'presets/index.json', data)
    return new


def export(home, identity, key, destination, overwrite=False):
    root, _, data = load(home, identity)
    if key not in data['items']:
        raise ValueError('preset no longer exists')
    source = preset_path(root, key)
    destination = Path(destination)
    if (destination.suffix.lower() != '.ini' or destination.is_symlink()
            or destination.resolve().is_relative_to((Path(home) / 'reshade').resolve())):
        raise ValueError('choose a separate .ini export outside managed ReShade data')
    if destination.exists() and not overwrite:
        raise ValueError('export destination exists; confirm overwrite')
    m.atomic_bytes(destination, p.checked(source.read_bytes()))


def details(home, identity, key, fr=True, full=False):
    root, _, data = load(home, identity)
    entry = data['items'][key]
    source = preset_path(root, key)
    payload = source.read_bytes()
    parsed = p.ini(payload, True)
    if full:
        return payload.decode('utf-8-sig')
    effects = [v for v in parsed['UWT_PRESET'].get('Techniques', '').split(',') if v]
    return '\n'.join([entry['name'], ('Origine : ' if fr else 'Origin: ') + entry['origin'],
                      ('Dernière sauvegarde (UTC) : ' if fr else 'Last saved (UTC): ') + entry['updated'],
                      ('Effets actifs : ' if fr else 'Enabled effects: ') + str(len(effects)),
                      *effects, '', str(source)])


def backup(home, identity, root):
    destination = Path(home) / 'reshade/deleted-presets' / (identity + '-' + uuid.uuid4().hex[:12] + '.zip')
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Preserve presets/metadata, not the large, reproducible shader/runtime cache.
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in root.rglob('*'):
            if path.is_symlink() or not path.is_file() or path.suffix.lower() not in ('.ini', '.json'):
                continue
            if not path.resolve().is_relative_to(root.resolve()):
                continue
            archive.write(path, path.relative_to(root).as_posix())
    destination.chmod(0o600)
    return destination


def idle(home, identity):
    for path in (Path(home) / 'reshade/installations' / identity).glob('*.json'):
        j = m.read_json(path)
        m.ensure_idle(Path(j['rom']), Path(j['root']), Path(j['prefix']))


def remove(home, identity, key):
    root, info, data = load(home, identity)
    idle(home, identity)
    if info['present'] and info['installed']:
        # Keep the same active-preset protection as the per-game menu.
        p.remove(home, Path(info['rom']), key)
        return ''
    if key not in data['items']:
        raise ValueError('preset no longer exists')
    source = preset_path(root, key)
    saved = backup(home, identity, root)
    if info['installed']:
        m.set_enabled(Path(home), Path(info['rom']), False)
        data = m.read_json(root / 'presets/index.json')
    del data['items'][key]
    if key == data.get('active'):
        data['active'] = ''
        # No stale working mirror may resurrect the removed preset if the game
        # is later reinstalled. Remaining variants stay available in the manager.
        m.atomic_bytes(root / 'ReShadePreset.ini', b'Techniques=\n')
    data.pop('runtime', None)
    data.pop('legacy_selection', None)
    m.save_json(root / 'presets/index.json', data)
    source.unlink(missing_ok=True)
    return str(saved)


def forget(home, identity):
    root, info, _ = load(home, identity)
    if not info['orphan']:
        raise ValueError('game is still installed; delete individual inactive presets instead')
    idle(home, identity)
    saved = backup(home, identity, root)
    if info['installed']:
        m.set_enabled(Path(home), Path(info['rom']), False)
    elif list((Path(home) / 'reshade/installations' / identity).glob('*.json')):
        raise ValueError('an unfinished ReShade installation still owns game files; restore it before forgetting this collection')
    shutil.rmtree(root)
    (Path(home) / 'reshade/games' / (identity + '.json')).unlink(missing_ok=True)
    return str(saved)
