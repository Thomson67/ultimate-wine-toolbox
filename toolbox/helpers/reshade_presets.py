"""Per-game preset collection; one working INI remains staged beside the game."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import uuid

import reshade_manager as m
from reshade_pack import ini


def folder(home, rom):
    return Path(home) / 'reshade/profiles' / m.key(rom)


def index(home, rom):
    value = m.read_json(folder(home, rom) / 'presets/index.json', {'schema': 1, 'active': '', 'items': {}})
    if value.get('schema') != 1:
        raise ValueError('unsupported preset collection')
    return value


def save(home, rom, value):
    m.save_json(folder(home, rom) / 'presets/index.json', value)


def path(home, rom, identity):
    if not re.fullmatch(r'[a-f0-9]{24}', identity):
        raise ValueError('invalid preset identifier')
    return folder(home, rom) / 'presets' / (identity + '.ini')


def context(home, rom):
    cfg = m.read_json(Path(home) / 'reshade/games' / (m.key(rom) + '.json'))
    if not cfg:
        raise ValueError('install ReShade for this game first')
    if cfg.get('pack'):
        meta = m.read_json(folder(home, rom) / 'pack/manifest.json')
        return meta['archive_sha256']
    return ''


def checked(data):
    ini(data, True)
    return data


def title(value):
    value = value.strip()
    if not value or len(value) > 120 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('preset name must contain 1 to 120 printable characters')
    return value


def add(home, rom, data, name, origin='local', pack=None):
    checked(data)
    source_name = name
    if any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ValueError('invalid preset filename')
    name = title(name[:120])
    pack = context(home, rom) if pack is None else pack
    value = index(home, rom)
    digest = hashlib.sha256(data).hexdigest()
    # Reimporting an unchanged named preset must not create endless duplicates.
    for identity, item in value['items'].items():
        if item['name'] == name and item.get('pack', '') == pack and item['sha256'] == digest:
            return identity
    identity = uuid.uuid4().hex[:24]
    m.atomic_bytes(path(home, rom, identity), data)
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    value['items'][identity] = {'name': name, 'source_name': source_name, 'origin': origin, 'pack': pack, 'sha256': digest,
                                'created': now, 'updated': now}
    save(home, rom, value)
    return identity


def capture(home, rom, adopt=False):
    """Persist live edits of the active preset; adopt is used after pack changes."""
    current = folder(home, rom) / 'ReShadePreset.ini'
    if not current.is_file():
        return
    data = checked(current.read_bytes())
    value = index(home, rom)
    pack = context(home, rom)
    identity = value.get('active', '')
    item = value['items'].get(identity)
    if adopt or not item or item.get('pack', '') != pack:
        digest = hashlib.sha256(data).hexdigest()
        identity = next((i for i, v in value['items'].items()
                         if v['sha256'] == digest and v.get('pack', '') == pack), '')
        if not identity:
            name = 'ReShadePreset.ini'
            if pack:
                name = m.read_json(folder(home, rom) / 'pack/manifest.json').get('selected', name)
            identity = add(home, rom, data, name, 'current', pack)
        value = index(home, rom)
        value['active'] = identity
        save(home, rom, value)
        return
    digest = hashlib.sha256(data).hexdigest()
    if item['sha256'] != digest:
        m.atomic_bytes(path(home, rom, identity), data)
        item.update(sha256=digest, updated=datetime.now(timezone.utc).isoformat(timespec='seconds'))
        save(home, rom, value)


def sync(home, rom):
    journals = []
    for jp in (Path(home) / 'reshade/installations' / m.key(rom)).glob('*.json'):
        j = m.read_json(jp)
        m.ensure_idle(rom, Path(j['root']), Path(j['prefix']))
        if m.directory_id(Path(j['root'])) == j.get('root_id'):
            source = m.safe_leaf(Path(j['root']), (PurePosixPath(j['exe']).parent / 'ReShadePreset.ini').as_posix())
            if source.is_file() and not source.is_symlink():
                journals.append((source.stat().st_mtime_ns, j))
    if journals:
        _, latest = max(journals, key=lambda entry: entry[0])
        m.profile_save(home, rom, Path(latest['root']), {'exe': latest['exe']})
    capture(home, rom)


def listing(home, rom):
    sync(home, rom)
    value = index(home, rom)
    pack = context(home, rom)
    return [dict(v, id=i, active=i == value['active'], compatible=v.get('pack', '') == pack)
            for i, v in sorted(value['items'].items(), key=lambda pair: (pair[0] != value['active'], pair[1]['name'].casefold()))]


def activate(home, rom, identity):
    value = index(home, rom)
    if identity not in value['items']:
        raise ValueError('preset no longer exists')
    if value['items'][identity].get('pack', '') != context(home, rom):
        raise ValueError('preset requires its original shader pack; install/remove the local pack first')
    data = checked(path(home, rom, identity).read_bytes())
    sync(home, rom)
    value = index(home, rom)
    if value['active'] == identity:
        return
    # Read after sync, which may have saved edits of this preset from the game.
    data = checked(path(home, rom, identity).read_bytes())
    targets = [folder(home, rom) / 'ReShadePreset.ini']
    for jp in (Path(home) / 'reshade/installations' / m.key(rom)).glob('*.json'):
        j = m.read_json(jp)
        if m.directory_id(Path(j['root'])) == j.get('root_id'):
            targets.append(m.safe_leaf(Path(j['root']), (PurePosixPath(j['exe']).parent / 'ReShadePreset.ini').as_posix()))
    previous = [(p, p.read_bytes() if p.is_file() and not p.is_symlink() else None) for p in targets]
    if any(p.is_symlink() for p in targets):
        raise ValueError('managed preset must be a regular file')
    before = json.loads(json.dumps(value))
    try:
        for target in targets:
            m.atomic_bytes(target, data)
        value['active'] = identity
        save(home, rom, value)
    except Exception:
        for target, old in previous:
            if old is None:
                target.unlink(missing_ok=True)
            else:
                m.atomic_bytes(target, old)
        save(home, rom, before)
        raise


def import_file(home, rom, source):
    source = Path(source)
    data = checked(source.read_bytes())
    sync(home, rom)
    identity = add(home, rom, data, source.name)
    activate(home, rom, identity)
    return identity


def pack_presets(home, rom, files, metadata, selected=None):
    """Keep all variants, adjusted with the same preprocessing as the chosen one."""
    from reshade_pack import preset_bytes
    sync(home, rom)
    current = context(home, rom)
    if not current or current != metadata['archive_sha256']:
        raise ValueError('install this local shader pack before adding its presets')
    chosen = None
    for name in metadata['presets']:
        identity = add(home, rom, preset_bytes(files[name], metadata), name, 'pack', current)
        if name == selected:
            chosen = identity
    if chosen:
        value = index(home, rom)
        value['active'] = chosen
        save(home, rom, value)
    return len(metadata['presets'])


def rename(home, rom, identity, name):
    value = index(home, rom)
    value['items'][identity]['name'] = title(name)
    save(home, rom, value)


def remove(home, rom, identity):
    sync(home, rom)
    value = index(home, rom)
    if identity == value['active']:
        raise ValueError('activate another preset before deleting the active one')
    del value['items'][identity]
    save(home, rom, value)
    path(home, rom, identity).unlink(missing_ok=True)


def details(home, rom, identity, fr=True, full=False):
    value = index(home, rom)
    item = value['items'][identity]
    source = path(home, rom, identity)
    parser = ini(source.read_bytes(), True)
    if full:
        return source.read_text(encoding='utf-8-sig')
    text = lambda a, b: a if fr else b
    active = identity == value['active']
    effects = [v.strip() for v in parser['UWT_PRESET'].get('Techniques', '').split(',') if v.strip()]
    lines = [item['name'], text('Actif : ', 'Active: ') + text('oui' if active else 'non', 'yes' if active else 'no'),
             text('Origine : ', 'Origin: ') + {'current': text('preset existant', 'existing preset'),
                                              'local': text('fichier importé', 'imported file'),
                                              'pack': text('pack local', 'local bundle')}.get(item['origin'], item['origin']),
             text('Nom à l’import : ', 'Original name: ') + item.get('source_name', item['name']),
             text('Contexte shaders : ', 'Shader context: ') + (text('pack local', 'local bundle') if item.get('pack') else text('packs du jeu', 'game shader packs')),
             text('Même contexte de shaders : ', 'Same shader context: ') + text('oui' if item.get('pack', '') == context(home, rom) else 'non', 'yes' if item.get('pack', '') == context(home, rom) else 'no'),
             text('Dernière sauvegarde (UTC) : ', 'Last saved (UTC): ') + item['updated'],
             text('Effets actifs : ', 'Active effects: ') + str(len(effects))]
    lines += effects or [text('Aucun effet activé.', 'No enabled effects.')]
    lines += ['', text('Sections de paramètres : ', 'Parameter sections: ') + str(len(parser.sections()) - 1),
              text('Fichier : ', 'File: ') + str(source)]
    return '\n'.join(lines)
