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
        if not current_runtime(home, rom, Path(j['root'])):
            continue
        if m.directory_id(Path(j['root'])) == j.get('root_id'):
            source = m.safe_leaf(Path(j['root']), (PurePosixPath(j['exe']).parent / 'ReShadePreset.ini').as_posix())
            if source.is_file() and not source.is_symlink():
                journals.append((source.stat().st_mtime_ns, j))
    if journals:
        _, latest = max(journals, key=lambda entry: entry[0])
        m.profile_save(home, rom, Path(latest['root']), latest)
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
    targets = [(folder(home, rom) / 'ReShadePreset.ini', data)]
    for jp in (Path(home) / 'reshade/installations' / m.key(rom)).glob('*.json'):
        j = m.read_json(jp)
        if m.directory_id(Path(j['root'])) == j.get('root_id'):
            targets.append((m.safe_leaf(Path(j['root']), (PurePosixPath(j['exe']).parent / 'ReShadePreset.ini').as_posix()), data))
            config = m.safe_leaf(Path(j['root']), (PurePosixPath(j['exe']).parent / 'ReShade.ini').as_posix())
            if config.is_file() and not config.is_symlink():
                # A Toolbox selection is made while idle. The next gameStart
                # deploys the full collection and selects its native file.
                targets.append((config, legacy_config(config.read_bytes())))
    previous = [(p, p.read_bytes() if p.is_file() and not p.is_symlink() else None) for p, _ in targets]
    if any(p.is_symlink() for p, _ in targets):
        raise ValueError('managed preset must be a regular file')
    before = json.loads(json.dumps(value))
    try:
        for target, content in targets:
            m.atomic_bytes(target, content)
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


def runtime_session(home, rom):
    """A revision directory keeps removed/renamed variants out of native cycling."""
    if not (folder(home, rom) / 'presets/index.json').is_file():
        return None
    value = index(home, rom)
    current = context(home, rom)
    rows = {i: v for i, v in value['items'].items() if v.get('pack', '') == current}
    if value['active'] not in rows:
        capture(home, rom, adopt=True)
        value = index(home, rom)
        rows = {i: v for i, v in value['items'].items() if v.get('pack', '') == current}
    if not rows:
        return None
    names = {}
    for identity, item in rows.items():
        name = re.sub(r'[<>:"/\\|?*]', '_', item['name']).strip(' .')
        if name.lower().endswith('.ini'):
            name = name[:-4]
        # Prefix avoids Windows device names, even after a user rename.
        names['Preset-' + (name[:64] or 'preset') + '--' + identity + '.ini'] = identity
    token = hashlib.sha256(json.dumps([current, sorted(names.items())]).encode()).hexdigest()[:16]
    return {'directory': 'UWT-ReShadePresets/' + token, 'files': names,
            'active': value['active'], 'pack': current}


def session_path(session):
    if not session:
        return None
    name = next(name for name, identity in session['files'].items() if identity == session['active'])
    return './' + session['directory'] + '/' + name


def session_files(home, rom, root, executable_folder, session):
    if not session:
        return []
    return [(root, (executable_folder / session['directory'] / name).as_posix(),
             checked(path(home, rom, identity).read_bytes()), True)
            for name, identity in sorted(session['files'].items())]


def mark_runtime(home, rom, root, session):
    if not session:
        return
    value = index(home, rom)
    value['runtime'] = {'root': str(root), 'root_id': m.directory_id(root)}
    save(home, rom, value)


def current_runtime(home, rom, root):
    marker = index(home, rom).get('runtime')
    return (not marker or (marker['root'] == str(root) and marker['root_id'] == m.directory_id(root)))


def capture_session(home, rom, root, executable_folder, session):
    """Read only journal-owned files; never follow the INI's arbitrary paths."""
    if not session or session.get('pack', '') != context(home, rom):
        return False
    config = m.safe_leaf(root, (executable_folder / 'ReShade.ini').as_posix())
    if not config.is_file() or config.is_symlink():
        return False
    parser = ini(config.read_bytes())
    selected_path = parser.get('GENERAL', 'PresetPath', fallback='').strip().strip('"').replace('\\', '/').removeprefix('./')
    value = index(home, rom)
    selected = None
    selected_data = None
    changed = False
    for name, identity in session['files'].items():
        if identity not in value['items'] or value['items'][identity].get('pack', '') != session.get('pack', ''):
            continue
        relative = session['directory'] + '/' + name
        target = m.safe_leaf(root, (executable_folder / m.relative(relative)).as_posix())
        if not target.is_file() or target.is_symlink():
            continue
        data = checked(target.read_bytes())
        digest = hashlib.sha256(data).hexdigest()
        if value['items'][identity]['sha256'] != digest:
            m.atomic_bytes(path(home, rom, identity), data)
            value['items'][identity].update(sha256=digest, updated=datetime.now(timezone.utc).isoformat(timespec='seconds'))
            changed = True
        # ReShade saves a relative path, but tolerate a Wine drive prefix too.
        if selected_path.casefold() == relative.casefold() or selected_path.casefold().endswith('/' + relative.casefold()):
            selected, selected_data = identity, data
    if selected:
        value['active'] = selected
        m.atomic_bytes(folder(home, rom) / 'ReShadePreset.ini', selected_data)
        # Maintain the legacy working copy for export and existing tooling.
        m.atomic_bytes(m.safe_leaf(root, (executable_folder / 'ReShadePreset.ini').as_posix()), selected_data)
        changed = True
    if changed:
        save(home, rom, value)
    return bool(selected)


def legacy_config(data):
    parser = ini(data)
    if not parser.has_section('GENERAL'):
        parser.add_section('GENERAL')
    parser['GENERAL']['PresetPath'] = '.\\ReShadePreset.ini'
    from reshade_pack import encode_ini
    return encode_ini(parser)
