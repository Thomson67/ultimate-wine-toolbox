"""Synchronize one Toolbox entry with Batocera ES (v43 and newer)."""
import json
import os
from pathlib import Path
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


class SyncError(RuntimeError):
    pass


def es_running():
    override = os.environ.get('SCRAPER_ES_RUNNING')
    if override in ('0', '1'):
        return override == '1'
    # Linux comm names are limited to 15 characters: pgrep -x cannot reliably
    # match the full "emulationstation" name. Inspect executable paths instead.
    try:
        for process in Path('/proc').iterdir():
            if not process.name.isdigit():
                continue
            try:
                comm = (process / 'comm').read_text().strip()
                if comm not in ('emulationstatio', 'emulationstation'):
                    continue
                if (process / 'exe').readlink().name.split(' (deleted)', 1)[0] == 'emulationstation':
                    return True
            except (FileNotFoundError, ProcessLookupError):
                continue
            except PermissionError:
                return True
        return False
    except OSError:
        return True


def synchronize(gamelist, proposed, rom_name, fields, backup):
    """Return True after verified online sync, False only when ES is stopped.

    ES's /addgames endpoint imports XML into its live metadata and saves it.
    Sending a complete entry, seeded with live metadata, preserves statistics
    accumulated since the gamelist was last written. No global reload is used.
    """
    base = os.environ.get('SCRAPER_ES_URL', 'http://127.0.0.1:1234').rstrip('/')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(path, payload=None):
        req = urllib.request.Request(base + path, data=payload,
            headers={'Content-Type': 'application/xml'} if payload else {})
        with opener.open(req, timeout=3) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise SyncError('ES response exceeds limit')
            if payload is not None:
                if response.status != 200:
                    raise SyncError(f'ES import returned HTTP {response.status}')
                return raw
            return json.loads(raw)

    try:
        systems = request('/systems')
        if not isinstance(systems, list):
            raise SyncError('invalid ES system list')
    except (OSError, ValueError, SyncError) as exc:
        if es_running():
            raise SyncError(f'ES is running but its API is unavailable; XML left untouched: {exc}') from exc
        print('scraper-assets: mode=offline (ES stopped)')
        return False

    ports = Path(gamelist).parent
    target = os.path.realpath(ports / rom_name)

    def canon(value):
        return os.path.realpath(ports / value)

    def equal(key, first, second):
        if key in ('path', 'image', 'boxart', 'fanart', 'marquee', 'thumbnail'):
            return bool(first) and bool(second) and canon(first) == canon(second)
        return first == second

    candidates = [s for s in systems if isinstance(s, dict)
                  and (s.get('name') == 'ports' or s.get('group') == 'ports')
                  and str(s.get('collection', 'false')).lower() != 'true'
                  # ES can turn an existing native Ports system into a group
                  # without removing its own games or gamelist. Only a purely
                  # virtual group has gamesystem=false.
                  and str(s.get('gamesystem', 'true')).lower() != 'false']
    matches = []
    foreign_owners = set()
    for system in candidates:
        name = system.get('name')
        if not isinstance(name, str):
            continue
        games = request('/systems/' + urllib.parse.quote(name, safe='') + '/games')
        if not isinstance(games, list):
            raise SyncError('invalid ES game list')
        for game in games:
            if not isinstance(game, dict) or not isinstance(game.get('path'), str) or canon(game['path']) != target:
                continue
            # A group lists child-system games too. Never import a child entry
            # into the group's own gamelist, or count its alias as a duplicate.
            owner = game.get('systemName')
            if owner is None and str(system.get('groupsystem', 'false')).lower() != 'true':
                owner = name  # Compatibility with older non-group API responses.
            if owner == name:
                matches.append((name, game))
            else:
                foreign_owners.add(str(owner))
    print('scraper-assets: native candidate systems=' + ','.join(str(s.get('name')) for s in candidates))
    if len(matches) > 1:
        raise SyncError('multiple owning ES systems found for this launcher; XML left untouched')

    if not matches and foreign_owners:
        raise SyncError('launcher belongs to another system (' + ','.join(sorted(foreign_owners)) + '); XML left untouched')

    proposed_root = ET.fromstring(proposed)
    entries = [g for g in proposed_root.findall('game') if canon(g.findtext('path', '')) == target]
    if len(entries) != 1:
        raise SyncError('expected exactly one Toolbox entry; XML left untouched')
    entry = entries[0]
    expected = {key: entry.findtext(key, '') for key in fields}
    live = {}
    detail_url = None
    if matches:
        system_name, game = matches[0]
        print(f'scraper-assets: launcher owner={system_name}; exact path matched')
        game_id = game.get('id')
        if not isinstance(game_id, str) or not game_id:
            raise SyncError('missing ES game identifier')
        detail_url = '/systems/' + urllib.parse.quote(system_name, safe='') + '/games/' + urllib.parse.quote(game_id, safe='') + '?localpaths=true'
        live = request(detail_url)
        if not isinstance(live, dict) or canon(live.get('path', '')) != target or live.get('systemName', system_name) != system_name:
            raise SyncError('ES returned a different launcher')
        # Prefer a user-selected live value over a managed/default value.
        for key in fields:
            value = live.get(key, '')
            if not isinstance(value, str) or not value or key == 'path':
                continue
            managed_paths = {canon(fields[key])} if key in ('image', 'boxart', 'fanart', 'marquee', 'thumbnail') else set()
            if managed_paths:
                slug = Path(fields[key]).stem
                managed_paths.update(canon(p) for p in (
                    f'./media/{folder}/{slug}.png' for folder in ('images', 'box2d', 'thumbnails', 'fanarts', 'marquee')))
                managed_paths.update(canon(f'./images/{slug}-{suffix}.png') for suffix in ('box2d', 'screenshot', 'fanart', 'logo'))
            if not managed_paths or canon(value) not in managed_paths:
                expected[key] = value
        # Keep live statistics, flags, custom metadata, and paths for every other
        # known field. The list response contains HTTP media URLs, hence detail.
        for key, value in live.items():
            if key in fields or key in ('id', 'systemName'):
                continue
            key = 'id' if key == 'scraperId' else key
            if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', key):
                continue
            if isinstance(value, str):
                node = entry.find(key)
                if node is None:
                    node = ET.SubElement(entry, key)
                node.text = value
    else:
        # A native Ports system (possibly also a group) can import a fresh
        # launcher before a scan. A purely virtual group cannot.
        if not any(s.get('name') == 'ports' for s in candidates):
            raise SyncError('real Ports system unavailable; XML left untouched')
        system_name = 'ports'

    # Match ES's fileMap using the literal absolute path returned by its API.
    # A relative path is resolved against ES's configured root, which need not
    # have the same spelling as the on-disk Ports directory (symlinks/groups).
    expected['path'] = live['path'] if live else str(ports.absolute() / rom_name)
    for key in ('image', 'boxart', 'fanart', 'marquee', 'thumbnail'):
        value = expected.get(key, '')
        if value and not os.path.isabs(value) and not value.startswith('~/'):
            expected[key] = os.path.abspath(ports / value)

    for key, value in expected.items():
        node = entry.find(key)
        if node is None:
            node = ET.SubElement(entry, key)
        node.text = value

    disk = ET.parse(gamelist).getroot() if Path(gamelist).exists() else ET.Element('gameList')
    disk_entries = [g for g in disk.findall('game') if canon(g.findtext('path', '')) == target]
    disk_ok = len(disk_entries) == 1 and all(equal(k, disk_entries[0].findtext(k, ''), v) for k, v in expected.items())
    live_ok = bool(live) and all(equal(k, live.get(k, ''), v) for k, v in expected.items())
    if not disk_ok or not live_ok:
        backup()
        payload = ET.Element('gameList')
        payload.append(entry)
        xml_payload = ET.tostring(payload, encoding='utf-8', xml_declaration=True)
        print(f'scraper-assets: import path={expected["path"]}', flush=True)
        print('scraper-assets: import XML=' + xml_payload.decode('utf-8'), flush=True)
        request('/addgames/' + urllib.parse.quote(system_name, safe=''), xml_payload)
        games = request('/systems/' + urllib.parse.quote(system_name, safe='') + '/games')
        games = [g for g in games if isinstance(g, dict) and isinstance(g.get('path'), str) and canon(g['path']) == target]
        if len(games) != 1 or not isinstance(games[0].get('id'), str):
            raise SyncError('launcher not found after ES import')
        result = request('/systems/' + urllib.parse.quote(system_name, safe='') + '/games/' + urllib.parse.quote(games[0]['id'], safe='') + '?localpaths=true')
        if not isinstance(result, dict) or not all(equal(k, result.get(k, ''), v) for k, v in expected.items()):
            raise SyncError('ES memory verification failed after import')
    disk = ET.parse(gamelist).getroot()
    games = [g for g in disk.findall('game') if canon(g.findtext('path', '')) == target]
    if len(games) != 1 or not all(equal(k, games[0].findtext(k, ''), v) for k, v in expected.items()):
        raise SyncError('gamelist verification failed after ES import')
    print('scraper-assets: mode=api; memory and gamelist verified; no ES reload requested')
    return True
