"""Small, reviewed GitHub catalogue shared by the AntiMicroX and ReShade menus."""
import argparse
import configparser
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import time
import urllib.parse
import urllib.request
import unicodedata
import uuid
import xml.etree.ElementTree as ET
import zipfile

REPOSITORY = 'Thomson67/ultimate-wine-toolbox-community'
REF = 'main'
LIMIT = 2*1024*1024
ES_LIMIT = 32*1024*1024
KINDS = {'antimicrox': '.amgp', 'reshade': '.ini'}
MODES = {'keyboard', 'mousebutton', 'mousemovement', 'pause', 'hold', 'cycle', 'distance',
         'release', 'mousespeedmod', 'keypress', 'delay', 'setchange', 'textentry', 'mix'}


def atomic(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.community-')
    try:
        with os.fdopen(fd, 'wb') as stream: stream.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def dump(value):
    return (json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode()


def clean(value, maximum=500):
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('Invalid catalogue text')
    return value.strip()


def entry(value):
    if not isinstance(value, dict): raise ValueError('Invalid catalogue entry')
    result = dict(value)
    if result.get('kind') not in KINDS: raise ValueError('Invalid profile type')
    if not isinstance(result.get('id'), str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', result['id']): raise ValueError('Invalid profile id')
    for key in ('game', 'title', 'author'):
        result[key] = clean(result.get(key), 160)
        if not result[key]: raise ValueError('Missing '+key)
    for key in ('description', 'notes', 'tested_on', 'hotkey'):
        result[key] = clean(result.get(key, ''), 2000)
    requirements = result.get('requirements', [])
    if not isinstance(requirements, list) or len(requirements) > 60: raise ValueError('Invalid requirements')
    result['requirements'] = [clean(item, 160) for item in requirements]
    path = result.get('file', '')
    if (not isinstance(path, str) or '\\' in path or not re.fullmatch(r'[a-zA-Z0-9_./-]+', path)
            or '..' in PurePosixPath(path).parts or PurePosixPath(path).is_absolute()
            or len(PurePosixPath(path).parts) != 2 or PurePosixPath(path).parts[0] != result['kind']
            or not path.endswith(KINDS[result['kind']])):
        raise ValueError('Invalid catalogue file path')
    if not isinstance(result.get('sha256'), str) or not re.fullmatch(r'[a-f0-9]{64}', result['sha256']): raise ValueError('Invalid checksum')
    return result


def entry_label(item):
    # A title may equal the game name, but distinct variants must stay visible.
    normalize = lambda value: ' '.join(unicodedata.normalize('NFKC', value).casefold().split())
    parts = [item['game']]
    if normalize(item['title']) != normalize(item['game']): parts.append(item['title'])
    parts.append(item['author'])
    return ' — '.join(parts)


def catalogue(value):
    if not isinstance(value, dict) or value.get('schema') != 1 or not isinstance(value.get('entries'), list):
        raise ValueError('Unsupported catalogue format')
    if len(value['entries']) > 10000: raise ValueError('Catalogue too large')
    entries = [entry(item) for item in value['entries']]
    if len({item['id'] for item in entries}) != len(entries): raise ValueError('Duplicate catalogue id')
    return {'schema': 1, 'entries': entries}


def profile_bytes(kind, data, export=False):
    if kind not in KINDS or len(data) > LIMIT or b'\0' in data: raise ValueError('Invalid or oversized profile')
    text = data.decode('utf-8-sig')
    if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', text): raise ValueError('Profile contains control characters')
    if kind == 'antimicrox':
        if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper(): raise ValueError('XML entities are not allowed')
        root = ET.fromstring(text)
        if root.tag != 'gamecontroller': raise ValueError('Community profiles require SDL gamecontroller format')
        if sum(1 for _ in root.iter()) > 30000: raise ValueError('XML profile too complex')
        for slot in root.findall('.//slot'):
            if slot.findtext('mode', 'keyboard') not in MODES:
                raise ValueError('External commands/profile loading are not accepted in community profiles')
        if export:
            for parent in root.iter():
                for node in list(parent):
                    if node.tag.lower() in ('uniqueid', 'guid', 'serial', 'sdlname'):
                        parent.remove(node)
            ET.indent(root, space='  ')
            data = ET.tostring(root, encoding='utf-8', xml_declaration=True)+b'\n'
        elif any(node.text for node in root.iter() if node.tag.lower() in ('uniqueid', 'guid', 'serial', 'sdlname')):
            raise ValueError('Controller identity must be stripped by the sharing export')
    else:
        if not re.search(r'^\s*Techniques\s*=', text, re.M | re.I):
            raise ValueError('Select a ReShade preset, not the ReShade configuration INI')
        # A preset may contain a global preamble; use an artificial section.
        parser = configparser.ConfigParser(interpolation=None, strict=True)
        parser.optionxform = str
        parser.read_string('[UWT_PRESET]\n'+text)
        if re.search(r'^\s*(EffectSearchPaths|TextureSearchPaths|PresetPath)\s*=', text, re.M | re.I):
            raise ValueError('Export a portable preset without local ReShade search paths')
    # Refuse machine-specific paths rather than silently publishing them.
    portable = data.decode('utf-8-sig')
    if re.search(r'/userdata/|/home/|[A-Za-z]:[\\/]|\\\\[^\s\\]+\\', portable):
        raise ValueError('Profile contains local paths; remove them in a separate export before sharing')
    return data


def hotkey_name(data):
    root = ET.fromstring(data)
    indices = {node.get('index') for node in root.findall('./sets/set[@index="1"]/button')
               if node.findtext('setselectcondition') == 'while-held'}
    names = {'1': 'A Xbox / Croix PS', '2': 'B Xbox / Rond PS', '3': 'X Xbox / Carré PS',
             '4': 'Y Xbox / Triangle PS', '5': 'Select / View / Share-Create', '6': 'Guide Xbox / PS',
             '7': 'Start / Menu / Options', '8': 'L3', '9': 'R3', '10': 'L1 / LB', '11': 'R1 / RB'}
    return ', '.join(names.get(index, index or '?') for index in sorted(indices))


def game_title(value):
    """Remove UWT file suffixes, retaining real title/edition information."""
    value = clean(value, 1000)
    if value.startswith('/') or re.match(r'^[A-Za-z]:[\\/]', value):
        value = value.replace('\\', '/').rsplit('/', 1)[-1]
    value = re.sub(r'\s*\(Pad2Key\)\s*$', '', value, flags=re.I)
    value = re.sub(r'\.(amgp|ini|keys)$', '', value, flags=re.I)
    value = re.sub(r'\s*\(Pad2Key\)\s*$', '', value, flags=re.I)
    value = re.sub(r'-pad2key-[a-f0-9]{8}(?:-\d+)?$', '', value, flags=re.I)
    value = re.sub(r'-[a-f0-9]{8,10}(?:-\d+)?$', '', value, flags=re.I)
    value = re.sub(r'\.(wsquashfs|wine|pc)$', '', value, flags=re.I)
    value = re.sub(r'\[(?:L|FR|EN|MULTI\d*|GE[- ]?Proton[^\]]*|Wine[^\]]*|TKG[^\]]*|UMU[^\]]*|Proton[^\]]*)\]', '', value, flags=re.I)
    return ' '.join(value.split()).strip(' -_')[:160]


def game_key(value):
    return ''.join(char.casefold() for char in unicodedata.normalize('NFKD', game_title(value)) if char.isalnum())


def es_games():
    # Read ES's actual in-memory gamelist, not a scan of the ROM directory.
    with urllib.request.urlopen('http://127.0.0.1:1234/systems/windows/games', timeout=3) as response:
        if response.status != 200: raise ValueError('ES game list is unavailable')
        data = response.read(ES_LIMIT+1)
    if len(data) > ES_LIMIT: raise ValueError('ES game list exceeds 32 MiB')
    values = json.loads(data)
    if not isinstance(values, list): raise ValueError('Invalid ES game list')
    result = {}
    for value in values:
        if not isinstance(value, dict): continue
        path = value.get('path', '')
        if not isinstance(path, str) or any(ord(char) < 32 or ord(char) == 127 for char in path): continue
        if not path.startswith('/userdata/roms/windows/') or Path(path).suffix.lower() not in ('.wine', '.pc', '.wsquashfs'): continue
        name = game_title(value.get('name') or Path(path).name)
        if name: result[path] = name
    return sorted(result.items(), key=lambda item: item[1].casefold())


def reshade_games(home, managed_only=False):
    """Only managed ReShade games can export/receive a Toolbox preset."""
    from community_reshade import games
    result = []
    for path, state in games(Path(home), managed_only):
        if any(ord(c) < 32 or ord(c) == 127 for c in path): continue
        result.append((path, game_title(Path(path).name), state))
    return result


def preset_info(source, fr=True):
    path = Path(source)
    if path.stat().st_size > LIMIT: raise ValueError('Preset exceeds 2 MiB')
    data = profile_bytes('reshade', path.read_bytes())
    title = 'Preset ReShade' if fr else 'ReShade preset'
    return title+' : '+path.name+'\n\n'+data.decode('utf-8-sig')


def suggest_game(home, kind, source, rom=''):
    home, source = Path(home), Path(source)
    known_roms, candidate = [], ''
    if rom:
        known_roms = [rom]
    elif kind == 'antimicrox':
        associations = home/'config/antimicrox-games.tsv'
        if associations.exists():
            for line in associations.read_text().splitlines():
                fields = line.split('\t')
                if len(fields) == 2 and Path(fields[1]).resolve() == source.resolve():
                    known_roms.append(fields[0])
        known_roms = list(dict.fromkeys(known_roms))
        if len(known_roms) > 1:
            return ''  # A shared profile needs an explicit game selection.
        imports = home/'state/community/imports.json'
        if imports.exists():
            candidate = json.loads(imports.read_text()).get(str(source.resolve()), {}).get('game', '')
        registry = home/'state/antimicrox-pad2key-conversions.json'
        if not known_roms and registry.exists():
            original = json.loads(registry.read_text()).get(str(source.resolve()), {}).get('source', '')
            if original:
                path = Path(original)
                known_roms = [str(path.parent) if path.name == 'padto.keys' else str(path).removesuffix('.keys')]
        if not candidate:
            candidate = ET.parse(source).getroot().findtext('profilename', '')
    if kind == 'reshade' and not rom:
        imports = home/'state/community/imports.json'
        if imports.exists():
            candidate = json.loads(imports.read_text()).get(str(source.resolve()), {}).get('game', '')
    if known_roms:
        candidate = game_title(Path(known_roms[0]).name)
    if not candidate:
        candidate = source.stem
    candidate = game_title(candidate)
    generic = ('default', 'defaultprofile', 'profile', 'profil', 'reshadepreset', 'gamecontroller')
    if game_key(candidate) in generic:
        candidate = game_title(source.stem)
        if game_key(candidate) in generic: return ''
    try:
        games = es_games()
    except (OSError, ValueError):
        return candidate
    if known_roms:
        matched = [name for path, name in games if path == known_roms[0]]
        if matched: return matched[0]
    matched = [name for _, name in games if game_key(name) == game_key(candidate)]
    return matched[0] if len(set(matched)) == 1 else candidate


def prioritize_games(games, preferred):
    """Rank related titles first, retaining every game and stable ordering."""
    words = lambda text: set(re.findall(r'[^\W_]+', unicodedata.normalize('NFKC', text).casefold()))
    wanted = words(preferred)
    def score(row):
        found = words(row[1])
        common = wanted & found
        return (bool(wanted) and wanted <= found, len(common) / max(1, len(wanted | found)))
    return sorted(games, key=score, reverse=True)


class Community:
    def __init__(self, home, download=None):
        self.home = Path(home)
        config = self.home/'config/community-source.json'
        source = json.loads(config.read_text()) if config.exists() else {}
        self.repository, self.ref = source.get('repository', REPOSITORY), source.get('ref', REF)
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', self.repository): raise ValueError('Invalid repository')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', self.ref): raise ValueError('Invalid catalogue branch')
        self.base = f'https://raw.githubusercontent.com/{self.repository}/{self.ref}/'
        self.cache = self.home/'state/community/catalog.json'
        self.download = download or self.network

    def network(self, url):
        headers = {'User-Agent': 'Ultimate-Wine-Toolbox'}
        if url == self.base+'catalog.json':
            # Raw GitHub branch URLs can serve a pre-publication copy for five minutes.
            # A new cache key makes an explicit refresh fetch the current catalogue.
            url += '?uwt_refresh='+uuid.uuid4().hex
            headers.update({'Cache-Control': 'no-cache', 'Pragma': 'no-cache'})
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=15) as response:
            if not response.geturl().startswith(self.base): raise ValueError('Unexpected download redirect')
            data = response.read(LIMIT+1)
        if len(data) > LIMIT: raise ValueError('Download exceeds 2 MiB')
        return data

    def refresh(self):
        value = catalogue(json.loads(self.download(self.base+'catalog.json')))
        atomic(self.cache, dump({'source': self.base, 'updated': int(time.time()), 'catalog': value}))
        return value

    def load(self):
        if self.cache.exists():
            value = json.loads(self.cache.read_text())
            if value.get('source') == self.base: return catalogue(value['catalog'])
        return self.refresh()

    def find(self, kind, identifier):
        return next((item for item in self.load()['entries'] if item['kind'] == kind and item['id'] == identifier), None)

    def local_profile(self, item):
        imports = self.home/'state/community/imports.json'
        values = json.loads(imports.read_text()) if imports.exists() else {}
        for filename, saved in values.items():
            if (saved.get('id'), saved.get('kind'), saved.get('sha256')) != (item['id'], item['kind'], item['sha256']): continue
            path = Path(filename)
            try:
                if path.is_symlink() or not path.is_file() or path.stat().st_size > LIMIT: continue
                data = path.read_bytes()
                profile_bytes(item['kind'], data)
            except (OSError, ValueError, ET.ParseError, configparser.Error): continue
            return path, hashlib.sha256(data).hexdigest() != item['sha256']
        return None

    def fetch(self, kind, identifier):
        item = self.find(kind, identifier)
        if item is None: raise ValueError('Profile no longer in catalogue; refresh the catalogue')
        data = self.download(self.base+item['file'])
        if hashlib.sha256(data).hexdigest() != item['sha256']: raise ValueError('Profile checksum mismatch; refresh catalogue')
        profile_bytes(kind, data)
        directory = self.home/'config'/('antimicrox-profiles' if kind == 'antimicrox' else 'reshade-community-presets')
        directory.mkdir(parents=True, exist_ok=True)
        name = 'community-'+identifier+'-'+item['sha256'][:10]
        path = directory/(name+KINDS[kind]); count = 2
        while path.exists() or path.is_symlink():
            if not path.is_symlink() and path.read_bytes() == data: break
            path = directory/(name+f'-{count}'+KINDS[kind]); count += 1
        else:
            with path.open('xb') as stream: stream.write(data)
        imports = self.home/'state/community/imports.json'
        values = json.loads(imports.read_text()) if imports.exists() else {}
        values[str(path.resolve())] = item
        atomic(imports, dump(values))
        return path

    def share(self, kind, source, game, title, author, description='', notes='', tested_on='', requirements=()):
        source = Path(source)
        if source.stat().st_size > LIMIT: raise ValueError('Profile exceeds 2 MiB')
        data = profile_bytes(kind, source.read_bytes(), export=True)
        identifier = re.sub(r'[^a-z0-9]+', '-', title.casefold()).strip('-')[:65] or 'profile'
        identifier += '-'+uuid.uuid4().hex[:8]
        filename = kind+'/'+identifier+KINDS[kind]
        metadata = entry({'id': identifier, 'kind': kind, 'game': game, 'title': title, 'author': author,
                          'description': description, 'notes': notes, 'tested_on': tested_on,
                          'requirements': list(requirements), 'hotkey': hotkey_name(data) if kind == 'antimicrox' else '',
                          'file': filename, 'sha256': hashlib.sha256(data).hexdigest()})
        body = (f"Type: {kind}\nJeu / Game: {game}\nTitre / Title: {title}\nAuteur / Author: {author}\n\n"
                'Joindre le ZIP généré ici / Attach the generated ZIP here.\n'
                'Je confirme être autorisé à partager ce profil publiquement / '
                'I confirm I may share this profile publicly.\n')
        url = f'https://github.com/{self.repository}/issues/new?'+urllib.parse.urlencode({'title': '[Community] '+title, 'body': body})
        directory = self.home/'exports/community'/kind; directory.mkdir(parents=True, exist_ok=True)
        path = directory/(identifier+'.zip')
        with path.open('xb') as stream, zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as package:
            package.writestr('metadata.json', dump(metadata))
            package.writestr('profile'+KINDS[kind], data)
            package.writestr('submission.txt', body+'\n'+url+'\n')
        atomic(path.with_suffix('.txt'), (str(path)+'\n\n'+url+'\n').encode())
        return path, url


def approve(package, root):
    """Maintainer-only local promotion; publication still uses normal Git review."""
    root = Path(root)
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
        if len(names) != 3 or len(set(names)) != 3: raise ValueError('Invalid submission archive')
        if any(info.file_size > LIMIT for info in archive.infolist()): raise ValueError('Submission too large')
        metadata = entry(json.loads(archive.read('metadata.json')))
        filename = 'profile'+KINDS[metadata['kind']]
        if set(names) != {'metadata.json', filename, 'submission.txt'}: raise ValueError('Unexpected archive members')
        data = archive.read(filename)
    if hashlib.sha256(data).hexdigest() != metadata['sha256']: raise ValueError('Submission checksum mismatch')
    profile_bytes(metadata['kind'], data)
    catalog_file = root/'catalog.json'
    current = catalogue(json.loads(catalog_file.read_text())) if catalog_file.exists() else {'schema': 1, 'entries': []}
    if any(item['id'] == metadata['id'] for item in current['entries']): raise ValueError('Id already exists; review as an update')
    destination = root/metadata['file']
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('xb') as stream: stream.write(data)
    try:
        current['entries'].append(metadata)
        atomic(catalog_file, dump(current))
    except BaseException:
        destination.unlink(); raise
    return destination


def details(item, fr=True):
    if item is None: raise ValueError('Unknown catalogue entry')
    fields = [('Jeu' if fr else 'Game', 'game'), ('Titre' if fr else 'Title', 'title'),
              ('Auteur' if fr else 'Author', 'author'), ('Description', 'description'),
              ('Testé avec' if fr else 'Tested with', 'tested_on'), ('Hotkey', 'hotkey'), ('Notes', 'notes')]
    lines = [label+' : '+item.get(key, '') for label, key in fields if item.get(key)]
    lines += [('Prérequis : ' if fr else 'Requirements: ')+(', '.join(item['requirements']) or ('aucun indiqué' if fr else 'none specified'))]
    if item['kind'] == 'antimicrox':
        lines += ['Vérifiez la Hotkey et les réglages de souris dans l’éditeur avant activation.' if fr else
                  'Check the Hotkey and mouse settings in the editor before enabling.']
    else:
        lines += ['Installez les packs/effets indiqués pour le jeu avant d’appliquer ce preset.' if fr else
                  'Install the listed shader packs/effects for the game before applying this preset.']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', default='/userdata/system/ultimate-wine-toolbox')
    parser.add_argument('--language', default='fr')
    sub = parser.add_subparsers(dest='command', required=True)
    arg = sub.add_parser('refresh'); arg.add_argument('--kind', choices=KINDS)
    arg = sub.add_parser('games'); arg.add_argument('--query', default=''); arg.add_argument('--prefer', default='')
    arg = sub.add_parser('reshade-games'); arg.add_argument('--query', default=''); arg.add_argument('--managed-only', action='store_true')
    sub.add_parser('reshade-scan')
    arg = sub.add_parser('reshade-presets'); arg.add_argument('rom')
    arg = sub.add_parser('reshade-export'); arg.add_argument('rom'); arg.add_argument('identifier'); arg.add_argument('destination')
    arg = sub.add_parser('preset-info'); arg.add_argument('source')
    arg = sub.add_parser('preset-packs'); arg.add_argument('source')
    arg = sub.add_parser('suggest-game'); arg.add_argument('kind', choices=KINDS); arg.add_argument('source'); arg.add_argument('--rom', default='')
    for command in ('list', 'show', 'fetch', 'local'):
        arg = sub.add_parser(command); arg.add_argument('kind', choices=KINDS)
        if command == 'list': arg.add_argument('--query', default='')
        else: arg.add_argument('identifier')
    arg = sub.add_parser('share'); arg.add_argument('kind', choices=KINDS); arg.add_argument('source')
    for name in ('game', 'title', 'author'): arg.add_argument('--'+name, required=True)
    for name in ('description', 'notes', 'tested-on'): arg.add_argument('--'+name, default='')
    arg.add_argument('--requirement', action='append', default=[])
    arg = sub.add_parser('approve'); arg.add_argument('package'); arg.add_argument('--catalog-root', required=True)
    args = parser.parse_args()
    if args.command == 'approve': print(approve(args.package, args.catalog_root)); return
    if args.command == 'preset-info': print(preset_info(args.source, args.language == 'fr')); return
    if args.command == 'preset-packs':
        from reshade_preset_effects import analyze, report
        value = analyze(args.source)
        print(','.join(value['packs'])); print('review' if value['unknown'] or value['ambiguous'] else 'complete')
        print(report(value, args.language == 'fr')); return
    if args.command == 'reshade-scan':
        from reshade_manager import scan_external_games
        print(' / '.join(map(str, scan_external_games(Path(args.home), [path for path, _ in es_games()])))); return
    if args.command == 'reshade-presets':
        from community_reshade import presets
        for item in presets(args.home, args.rom, args.language == 'fr'): print(item['id']+'\t'+item['label'])
        return
    if args.command == 'reshade-export':
        from community_reshade import export
        export(args.home, args.rom, args.identifier, args.destination); return
    if args.command == 'reshade-games':
        for path, name, state in reshade_games(args.home, args.managed_only):
            if args.query.casefold() in name.casefold(): print(path+'\t'+name+'\t'+state)
        return
    if args.command == 'games':
        for path, name in prioritize_games(es_games(), args.prefer):
            if args.query.casefold() in name.casefold(): print(path+'\t'+name)
        return
    if args.command == 'suggest-game': print(suggest_game(args.home, args.kind, args.source, args.rom)); return
    community = Community(args.home)
    if args.command == 'refresh':
        values = community.refresh()['entries']
        print(sum(1 for item in values if not args.kind or item['kind'] == args.kind))
    elif args.command == 'list':
        for item in community.load()['entries']:
            if item['kind'] == args.kind and args.query.casefold() in (item['game']+' '+item['title']+' '+item['author']).casefold():
                local = community.local_profile(item)
                label = entry_label(item)
                if local:
                    label += (' [Téléchargé' if args.language == 'fr' else ' [Downloaded') + ((' — modifié' if args.language == 'fr' else ' — modified') if local[1] else '') + ']'
                print(item['id']+'\t'+label)
    elif args.command == 'show': print(details(community.find(args.kind, args.identifier), args.language == 'fr'))
    elif args.command == 'local':
        item = community.find(args.kind, args.identifier)
        local = community.local_profile(item) if item else None
        if local: print(local[0])
    elif args.command == 'fetch': print(community.fetch(args.kind, args.identifier))
    elif args.command == 'share':
        path, url = community.share(args.kind, args.source, args.game, args.title, args.author,
                                    args.description, args.notes, args.tested_on, args.requirement)
        print(str(path)+'\n'+url)


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, RuntimeError, KeyError, ET.ParseError, configparser.Error, zipfile.BadZipFile) as error:
        raise SystemExit(str(error))
