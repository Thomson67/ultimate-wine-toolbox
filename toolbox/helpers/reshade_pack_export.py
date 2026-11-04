"""Prepare portable ReShade ZIPs; never submit binary packs to the text-only API."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import uuid
import zipfile

import reshade_manager as m
import reshade_pack as pack


class ShaderFiles(dict):
    """Index installed libraries without loading unrelated shader payloads."""
    def __getitem__(self, name):
        value = super().__getitem__(name)
        if not isinstance(value, Path):
            return value
        size = value.stat().st_size
        if not value.is_file() or size > pack.FILE_LIMIT:
            raise ValueError('selected shader exceeds file limit')
        with value.open('rb') as stream:
            data = stream.read(pack.FILE_LIMIT + 1)
        if len(data) != size:
            raise ValueError('shader changed during export')
        return data


def text(value, required=False):
    if not isinstance(value, str) or len(value) > 4000 or any(ord(c) < 32 for c in value):
        raise ValueError('invalid public pack metadata')
    if required and not value.strip():
        raise ValueError('pack title, game, author and redistribution credits are required')
    return value.strip()


def game_source(home, rom):
    import reshade_presets as presets
    from reshade_preset_dependencies import shader_root, idle
    home, rom = Path(home), Path(rom)
    cfg = m.read_json(home / 'reshade/games' / (m.key(rom) + '.json'))
    if not cfg:
        raise ValueError('choose a Toolbox-managed game or a local ZIP/directory')
    idle(home, rom, cfg)
    rows = presets.listing(home, rom)
    files, names, active = ShaderFiles(), {}, ''
    for row in rows:
        if not row['compatible']:
            continue
        name = 'Preset-' + row['id'] + '.ini'
        files[name] = presets.path(home, rom, row['id']).read_bytes()
        names[name] = row['name']
        if row['active']:
            active = name
    files['ReShade.ini'] = (presets.folder(home, rom) / 'ReShade.ini').read_bytes()
    root = shader_root(home, rom, cfg)
    seen, count = set(), 0
    # Backend merged views use links inside the Toolbox cache. Flatten those
    # links into regular ZIP members, never follow a target outside that cache.
    for current, dirs, leaves in os.walk(root, followlinks=True):
        actual = Path(current).resolve()
        if not actual.is_relative_to(home.resolve()) or actual in seen:
            raise ValueError('external or circular shader directory')
        seen.add(actual)
        for name in dirs + leaves:
            count += 1
            if count > 100000:
                raise ValueError('too many shader files')
            path = Path(current) / name
            target = path.resolve()
            if not target.is_relative_to(home.resolve()):
                raise ValueError('shader link outside Toolbox cache')
            if name in dirs:
                continue
            if not target.is_file():
                raise ValueError('shader is not a regular file')
            if path.suffix.lower() in pack.ASSETS:
                files['reshade-shaders/' + path.relative_to(root).as_posix()] = target
    meta = pack.manifest(home, rom) if cfg.get('pack') else {}
    for name in meta.get('addons', {}):
        path = presets.folder(home, rom) / 'pack/assets' / m.relative(name)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > pack.FILE_LIMIT:
            raise ValueError('invalid installed add-on')
        files[name] = path.read_bytes()
    return files, {'names': names, 'preferred': active, 'release': cfg.get('release_id', ''),
                   'arch': cfg.get('arch'), 'api': cfg.get('dll', '')}


def source(home, rom=None, local=None):
    if bool(rom) == bool(local):
        raise ValueError('choose one source: managed game or local ZIP/directory')
    if rom:
        files, context = game_source(home, rom)
    else:
        files, metadata = pack.archive(Path(local))
        context = {'names': {n: n for n in metadata['presets']}, 'preferred': metadata['preferred'],
                   'release': metadata['required_release'], 'arch': next(iter(metadata['addons'].values()), None), 'api': ''}
    digest = hashlib.sha256()
    for name, data in sorted(files.items()):
        stamp = str((data.stat().st_ino, data.stat().st_size, data.stat().st_mtime_ns)).encode() if isinstance(data, Path) else hashlib.sha256(data).digest()
        digest.update(name.encode() + b'\0' + stamp)
    config = pack.ini(files['ReShade.ini'])
    disabled = {n.strip().casefold() for n in config.get('ADDON', 'DisabledAddons', fallback='').split(',')}
    addons = {n: m.pe_arch(files[n]) for n in files
              if PurePosixPath(n).suffix in ('.addon', '.addon32', '.addon64')
              and n.casefold() not in disabled and PurePosixPath(n).stem.casefold() not in disabled}
    context.update(sha256=digest.hexdigest(), addons=addons)
    return files, context


def plan(home, rom=None, local=None):
    files, context = source(home, rom, local)
    issues = {}
    for name in context['names']:
        try:
            dependencies(files, [name])
        except (ValueError, UnicodeError) as error:
            issues[name] = str(error)
    valid = [name for name in context['names'] if name not in issues]
    context['issues'] = issues
    context['default'] = context['preferred'] if context['preferred'] in valid else next(iter(valid), '')
    return context


def dependencies(files, selected):
    """Resolve active effects and literal include/texture references only."""
    effects = [n for n in files if n.startswith('reshade-shaders/Shaders/') and n.lower().endswith('.fx')]
    result = set()

    def resolve(value, parent='', texture=False):
        value = value.replace('\\', '/')
        if re.match(r'^[A-Za-z]:|^/', value):
            raise ValueError('absolute shader dependency: ' + value)
        # Relative includes may use ../ inside the shader tree.
        import posixpath
        candidates = [posixpath.normpath(str(PurePosixPath(parent).parent / value))] if parent else []
        base = 'reshade-shaders/Textures/' if texture else 'reshade-shaders/Shaders/'
        candidates += [base + value]
        for candidate in candidates:
            if not candidate.startswith('reshade-shaders/'):
                continue
            matches = [n for n in files if n.casefold() == candidate.casefold()]
            if len(matches) == 1:
                return matches[0]
        matches = [n for n in files if n.startswith(base) and (n.casefold().endswith('/' + value.casefold()) or n.casefold() == (base + value).casefold())]
        if not matches:
            raise ValueError('missing shader dependency: ' + value)
        if len(matches) > 1:
            raise ValueError('ambiguous shader dependency: ' + value + ' (' + ', '.join(sorted(matches)) + ')')
        return matches[0]

    def visit(name):
        if name in result:
            return
        result.add(name)
        if PurePosixPath(name).suffix.lower() not in ('.fx', '.fxh', '.h', '.hlsl'):
            return
        code = files[name].decode('utf-8-sig')
        code = re.sub(r'/\*.*?\*/|//[^\n]*', '', code, flags=re.S)
        for include in re.findall(r'^\s*#\s*include\s+([^\n]+)', code, re.M):
            match = re.fullmatch(r'["<]([^">]+)[">]\s*', include.strip())
            if not match:
                raise ValueError('dynamic include needs manual resolution in ' + name + ': ' + include.strip())
            visit(resolve(match[1], name))
        annotations = re.findall(r'\btexture(?:1D|2D|3D|Cube)?\s+\w+\s*<([^>]*)>', code, re.S)
        for texture in re.findall(r'\bsource\s*=\s*([^;]+);', '\n'.join(annotations)):
            match = re.fullmatch(r'"([^"\n]+)"', texture.strip())
            if not match:
                raise ValueError('dynamic texture needs manual resolution in ' + name)
            visit(resolve(match[1], texture=True))

    for name in selected:
        try:
            parser = pack.ini(files[name], True)
            for technique in parser['UWT_PRESET'].get('Techniques', '').split(','):
                technique = technique.strip()
                if not technique:
                    continue
                if '@' in technique:
                    visit(resolve(technique.split('@', 1)[1]))
                else:
                    matches = [n for n in effects if re.search(r'\btechnique\d*\s+' + re.escape(technique) + r'\b', files[n].decode('utf-8-sig'))]
                    if len(matches) != 1:
                        raise ValueError('missing or ambiguous active technique: ' + technique)
                    visit(matches[0])
        except (ValueError, UnicodeError) as error:
            raise ValueError('preset ' + name + ': ' + str(error)) from error
    if not any(n.lower().endswith('.fx') for n in result):
        raise ValueError('selected presets contain no active shader')
    return result


def export(home, *, rom=None, local=None, selected=(), addons=(), expected='', game='', title='', author='', credits='', description='', tested_on=''):
    home = Path(home)
    public = {k: text(v, k in ('game', 'title', 'author', 'credits')) for k, v in
              dict(game=game, title=title, author=author, credits=credits, description=description, tested_on=tested_on).items()}
    files, context = source(home, rom, local)
    if not expected or expected != context['sha256']:
        raise ValueError('pack changed during review; select it again')
    selected, addons = list(dict.fromkeys(selected)), list(dict.fromkeys(addons))
    if not selected or any(n not in context['names'] for n in selected):
        raise ValueError('select at least one available preset')
    if any(n not in context['addons'] for n in addons):
        raise ValueError('selected add-on is unavailable or disabled')
    # The existing Citra import recipe activates this adapter pass before all
    # visual effects. Preserve that executable add-on/shader dependency when
    # exporting an original ZIP whose presets do not yet list the adapter.
    citra = 'citra.addon' in addons and 'reshade-shaders/Shaders/Citra.fx' in files
    if citra:
        for name in selected:
            files[name] = pack.preset_bytes(files[name], {'citra': True})
    needed = dependencies(files, selected)
    if any(n.endswith('/Citra.fx') for n in needed) and 'citra.addon' in context['addons'] and 'citra.addon' not in addons:
        raise ValueError('the active Citra shader requires selecting citra.addon')
    payload = {n: files[n] for n in needed | set(addons)}
    preferred = context['preferred'] if context['preferred'] in selected else selected[0]
    output_names = {}
    for number, n in enumerate(selected, 1):
        label = context['names'][n]
        stem = re.sub(r'[\\:*?"<>|/]', '-', label).rstrip(' .')
        if stem.lower().endswith('.ini'):
            stem = stem[:-4]
        output_names[n] = f'{number:02d}-{stem or "Preset"}.ini' if rom else n
        payload[output_names[n]] = pack.preset_bytes(files[n], {'citra': False})
    preferred = output_names[preferred]
    base = ('[GENERAL]\nPresetPath=./' + preferred + '\nEffectSearchPaths=./reshade-shaders/Shaders/**\nTextureSearchPaths=./reshade-shaders/Textures/**\n').encode()
    payload['ReShade.ini'] = pack.merge_config(base, files['ReShade.ini'])
    public.update(schema=1, kind='uwt-reshade-pack', release=context['release'], api=context['api'], arch=context['arch'],
                  presets={output_names[n]: context['names'][n] for n in selected}, addons={n: context['addons'][n] for n in addons},
                  requires_full_addons=bool(addons), files={n: hashlib.sha256(d).hexdigest() for n, d in sorted(payload.items())})
    payload['uwt-pack.json'] = (json.dumps(public, ensure_ascii=False, indent=2) + '\n').encode()
    payload['README.txt'] = ('UWT ReShade pack / Pack ReShade\n' + title + '\n' + credits + '\n\n'
        'Import via ReShade > Pack local > ZIP. Install the specified ReShade version/API first.\n'
        'Public community API upload is not supported yet; share this ZIP manually.\n'
        'Add-ons were explicitly selected by the author; they are executable Windows modules.\n').encode()
    folder = home / 'exports/community/reshade-packs'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / ('reshade-pack-' + uuid.uuid4().hex[:12] + '.zip')
    fd, temporary = tempfile.mkstemp(prefix='.pack-export-', dir=folder)
    try:
        with os.fdopen(fd, 'wb') as stream, zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(payload.items()):
                archive.writestr(name, data)
        # Use the normal importer as the final portability/size/architecture check.
        pack.archive(temporary)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    m.atomic_bytes(target.with_suffix('.zip.sha256'), (hashlib.sha256(target.read_bytes()).hexdigest() + '  ' + target.name + '\n').encode())
    return target
