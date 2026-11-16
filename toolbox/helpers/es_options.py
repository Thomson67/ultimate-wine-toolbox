"""Opt-in Windows options exported to EmulationStation."""
import argparse
from contextlib import contextmanager
import fcntl
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

from antimicrox_live import atomic

FEATURES = Path('/userdata/system/configs/emulationstation/es_features_ultimate_wine_toolbox.cfg')
CONF = Path('/userdata/system/batocera.conf')
BUNDLES = Path(__file__).resolve().parents[2]/'dxvk/bundles'
HOME = Path('/userdata/system/ultimate-wine-toolbox')
OWNER = b'<!-- Managed by Ultimate Wine Toolbox -->'

SWITCH = {'on': ('Activé', 'Enabled'), 'off': ('Désactivé', 'Disabled')}
# Retain the stored values used by the original launcher option.
LAUNCHER_TITLE = ('Afficher le launcher (par jeu)', 'Show launcher (per game)')
LAUNCHER_CHOICES = {'normal': ('Non', 'No'), 'next': ('Oui', 'Yes')}
LAUNCHER_DESCRIPTION = (
    'Avec Oui, affiche le launcher à chaque démarrage de ce jeu.',
    'With Yes, show the launcher every time this game starts.',
)
RESHADE_TITLE = ('ReShade (par jeu)', 'ReShade (per game)')
RESHADE_PRESET_KEY = 'reshade_preset'
RESHADE_PRESET_TITLES = ('Preset ReShade installé (par jeu)', 'Installed ReShade preset (per game)')
DXVK_TITLE = ('Bundle DXVK / VKD3D', 'DXVK / VKD3D bundle')
DXVK_NATIVE = ('Versions natives de Batocera', 'Batocera defaults')
COMMUNITY_KEYS = {'reshade': 'community_reshade', 'antimicrox': 'community_antimicrox'}
COMMUNITY_NAMES = {
    'community_reshade': ('Presets ReShade communautaires (par jeu)', 'Community ReShade presets (per game)'),
    'community_antimicrox': ('Profils AntiMicroX communautaires (par jeu)', 'Community AntiMicroX profiles (per game)'),
}
OPTIONS = {
    **{key: ((key, names, {}),) for key, names in COMMUNITY_NAMES.items()},
    'mangohud': (
        ('mangohud', ('MangoHud', 'MangoHud'), SWITCH),
        ('mangohud_display', ('Profil MangoHud', 'MangoHud profile'),
         {'default': ('Standard', 'Standard'), 'minimal': ('Minimal', 'Minimal'),
          'detailed': ('Détaillé', 'Detailed'), 'hidden': ('Masqué', 'Hidden')}),
        ('mangohud_fps', ('Limite FPS MangoHud', 'MangoHud FPS limit'),
         {'0': ('Illimitée', 'Unlimited'), **{str(fps): (str(fps), str(fps)) for fps in (30, 40, 45, 50, 60, 72, 90, 120, 144, 165, 240)}}),
        ('mangohud_vulkan', ('Présentation Vulkan (MangoHud)', 'Vulkan presentation (MangoHud)'),
         {'off': ('Immédiat', 'Immediate'), 'mailbox': ('Mailbox', 'Mailbox'),
          'on': ('VSync', 'VSync'), 'adaptive': ('Adaptatif', 'Adaptive')}),
    ),
    'dxvk': (('dxvk', DXVK_TITLE, {'batocera': DXVK_NATIVE}),),
    'antimicrox': (('antimicrox', ('AntiMicroX', 'AntiMicroX'),
                    {'on': ('Utiliser le profil associé', 'Use the assigned profile'), 'off': SWITCH['off']}),),
    'keyboard': (('keyboard', ('Clavier virtuel', 'Virtual keyboard'), SWITCH),),
    'mouse': (('mouse', ('Souris virtuelle', 'Virtual mouse'), SWITCH),),
    'reshade': (('reshade', RESHADE_TITLE, SWITCH),),
    'launcher': (('launcher', LAUNCHER_TITLE, LAUNCHER_CHOICES),),
}
CHOICES = {key: choices for group in OPTIONS.values() for key, _, choices in group}


def option_file(path=FEATURES):
    if path.is_symlink():
        raise ValueError(f'Refusing a symlink at {path}')
    return path.read_bytes() if path.exists() else b''


def exposed(path=FEATURES):
    raw = option_file(path)
    if not raw or OWNER not in raw:
        return set()
    xml = ET.fromstring(raw)
    return {feature.get('value', '').removeprefix('uwt_')
            for feature in xml.findall('./emulator/system/feature')}


def write_features(path, xml):
    ET.indent(xml)
    atomic(path, OWNER + b'\n' + ET.tostring(xml, encoding='utf-8') + b'\n', mode=0o644)


def launcher_choices(feature, index):
    feature.set('name', LAUNCHER_TITLE[index])
    feature.set('description', LAUNCHER_DESCRIPTION[index])
    for choice in feature.findall('choice'):
        feature.remove(choice)
    for value, captions in LAUNCHER_CHOICES.items():
        ET.SubElement(feature, 'choice', name=captions[index], value=value)


def dxvk_choices(bundles):
    choices = {'batocera': DXVK_NATIVE}
    if bundles.is_dir():
        for path in sorted(bundles.iterdir(), key=lambda item: item.name.casefold()):
            if (re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]*', path.name) and path.name != 'batocera'
                    and not path.is_symlink() and (path/'x32').is_dir() and (path/'x64').is_dir()
                    and not (path/'x32').is_symlink() and not (path/'x64').is_symlink()):
                choices[path.name] = (path.name, path.name)
    return choices


@contextmanager
def features_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with (path.parent / '.uwt-features.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def community_choices(home, key, name):
    from community_catalog import es_choices

    french = name == COMMUNITY_NAMES[key][0]
    kind = next(kind for kind, option in COMMUNITY_KEYS.items() if option == key)
    rows = es_choices(home, kind)
    if rows:
        return rows
    return [('catalogue-unavailable', 'Catalogue en attente' if french else 'Waiting for catalogue')]


def update_choices(feature, expected):
    current = [(choice.get('value'), choice.get('name')) for choice in feature.findall('choice')]
    if current == expected:
        return False
    for choice in feature.findall('choice'):
        feature.remove(choice)
    for value, label in expected:
        ET.SubElement(feature, 'choice', name=label, value=value)
    return True


def order_community_features(system):
    original = list(system)
    features = {feature.get('value'): feature for feature in original}
    near = {key: kind for kind, key in COMMUNITY_KEYS.items()}
    near[RESHADE_PRESET_KEY] = ('community_reshade' if 'uwt_community_reshade' in features else 'reshade')
    ordered = [feature for feature in original
               if feature.get('value', '').removeprefix('uwt_') not in near]
    for key, kind in near.items():
        feature = features.get(f'uwt_{key}')
        if feature is None:
            continue
        adjacent = features.get(f'uwt_{kind}')
        if adjacent is None:
            ordered.append(feature)
        else:
            ordered.insert(ordered.index(adjacent) + 1, feature)
    if ordered == original:
        return False
    system[:] = ordered
    return True


def update_reshade_presets(system, home):
    features = {feature.get('value'): feature for feature in system.findall('feature')}
    anchor = features.get('uwt_community_reshade')
    if anchor is None:
        anchor = features.get('uwt_reshade')
    if anchor is None:
        return False
    from reshade_presets import es_choices

    french = anchor.get('name') in (COMMUNITY_NAMES['community_reshade'][0], RESHADE_TITLE[0])
    value = f'uwt_{RESHADE_PRESET_KEY}'
    feature = features.get(value)
    name = RESHADE_PRESET_TITLES[0 if french else 1]
    changed = feature is None
    if changed:
        feature = ET.Element('feature', name=name, value=value,
                             submenu='Ultimate Wine Toolbox')
        system.insert(list(system).index(anchor) + 1, feature)
    description = ('Choisissez un preset du jeu. Il s’applique au prochain lancement.' if french else
                   'Choose a preset for this game. It applies on the next launch.')
    for attribute, text in (('name', name), ('description', description)):
        if feature.get(attribute) != text:
            feature.set(attribute, text)
            changed = True
    rows = es_choices(home)
    if not rows:
        rows = [('unavailable', 'Aucun preset installé' if french else 'No installed presets')]
    changed |= update_choices(feature, rows)
    return changed


def refresh_reshade_presets(path=FEATURES, home=HOME):
    if not path.is_file() or path.is_symlink():
        return
    with features_lock(path):
        raw = option_file(path)
        if OWNER not in raw:
            return
        xml = ET.fromstring(raw)
        system = xml.find('./emulator/system')
        if system is not None and update_reshade_presets(system, home):
            write_features(path, xml)


def refresh(path=FEATURES, bundles=BUNDLES, home=HOME):
    with features_lock(path):
        refresh_features(path, bundles, home)


def community_description(key, french):
    if key == 'community_reshade':
        return ('Choisissez un preset ou un pack pour ce jeu, puis quittez avec Retour.' if french else
                'Choose a preset or bundle for this game, then leave the menu with Back.')
    return ('Choisissez un profil pour ce jeu, puis quittez avec Retour.' if french else
            'Choose a profile for this game, then leave the menu with Back.')


def refresh_features(path, bundles, home):
    if path.is_symlink():
        return
    raw = option_file(path)
    if OWNER not in raw:
        return
    xml = ET.fromstring(raw)
    launcher = xml.find('./emulator/system/feature[@value="uwt_launcher"]')
    reshade = xml.find('./emulator/system/feature[@value="uwt_reshade"]')
    old_launcher = ('Réafficher le launcher (par jeu)', 'Show the launcher again (per game)')
    old_reshade = ('ReShade configuré (par jeu)', 'Configured ReShade (per game)')
    changes = False
    if launcher is not None and launcher.get('name') in old_launcher:
        launcher_choices(launcher, old_launcher.index(launcher.get('name')))
        changes = True
    if reshade is not None and reshade.get('name') in old_reshade:
        reshade.set('name', RESHADE_TITLE[old_reshade.index(reshade.get('name'))])
        changes = True
    dxvk = xml.find('./emulator/system/feature[@value="uwt_dxvk"]')
    if dxvk is not None:
        index = int(dxvk.get('name') != DXVK_TITLE[0])
        expected = [(value, names[index]) for value, names in dxvk_choices(bundles).items()]
        changes |= update_choices(dxvk, expected)
    for key in COMMUNITY_NAMES:
        feature = xml.find(f'./emulator/system/feature[@value="uwt_{key}"]')
        if feature is not None:
            french = feature.get('name') == COMMUNITY_NAMES[key][0]
            description = community_description(key, french)
            if feature.get('description') != description:
                feature.set('description', description)
                changes = True
            changes |= update_choices(feature, community_choices(home, key, feature.get('name')))
    system = xml.find('./emulator/system')
    if system is not None:
        changes |= update_reshade_presets(system, home)
        changes |= order_community_features(system)
    if changes:
        write_features(path, xml)


def publish(groups, language, path=FEATURES, bundles=BUNDLES, home=HOME):
    with features_lock(path):
        publish_features(groups, language, path, bundles, home)


def publish_features(groups, language, path, bundles, home):
    groups = set(groups)
    if 'community' in groups:
        groups.update(COMMUNITY_NAMES)
    raw = option_file(path)
    if path.exists() and OWNER not in raw:
        raise ValueError(f'{path} is not owned by Ultimate Wine Toolbox')
    if not groups:
        path.unlink(missing_ok=True)
        return
    index = int(language != 'fr')
    xml = ET.Element('features')
    emulator = ET.SubElement(xml, 'emulator', name='wine')
    system = ET.SubElement(emulator, 'system', name='windows')
    for group in OPTIONS:
        if group not in groups:
            continue
        for key, names, choices in OPTIONS[group]:
            feature = ET.SubElement(system, 'feature', name=names[index], value=f'uwt_{key}',
                                    submenu='Ultimate Wine Toolbox')
            if key in COMMUNITY_NAMES:
                feature.set('description', community_description(key, index == 0))
                update_choices(feature, community_choices(home, key, names[index]))
            elif key == 'launcher':
                launcher_choices(feature, index)
            else:
                if key == 'dxvk':
                    choices = dxvk_choices(bundles)
                for value, captions in choices.items():
                    ET.SubElement(feature, 'choice', name=captions[index], value=value)
    update_reshade_presets(system, home)
    order_community_features(system)
    write_features(path, xml)


def enable_community(language, path=FEATURES, bundles=BUNDLES, home=HOME):
    marker = home / 'state/community/es-options-initialized'
    with features_lock(path):
        if marker.is_file():
            return
        keys = exposed(path)
        groups = {group for group, items in OPTIONS.items() if any(key in keys for key, _, _ in items)}
        publish_features(groups | COMMUNITY_NAMES.keys(), language, path, bundles, home)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()


def game_key(rom, key):
    name = Path(rom).name
    if any(character in name for character in '\r\n"'):
        return ''
    name = name.replace('=', '').replace('#', '')
    return f'windows["{name}"].uwt_{key}'


class Overrides:
    def __init__(self, rom, features=FEATURES, conf=CONF, bundles=BUNDLES):
        self.rom = rom
        self.bundles = bundles
        self.keys = set()
        self.values = {}
        try:
            self.keys = exposed(features)
            if not self.keys or not conf.is_file():
                return
            with conf.open(encoding='utf-8', errors='surrogateescape') as stream:
                for line in stream:
                    name, _, value = line.partition('=')
                    if 'uwt_' in name and not name.lstrip().startswith(('#', ';')):
                        self.values[name.strip()] = value.strip()
        except (OSError, ValueError, ET.ParseError) as exc:
            print(f'ES options: {exc}', file=sys.stderr)

    def get(self, key, game_only=False, toolbox_game=None):
        if key not in self.keys:
            return toolbox_game
        allowed = dxvk_choices(self.bundles) if key == 'dxvk' else CHOICES[key]
        game = self.values.get(game_key(self.rom, key))
        if game in allowed:
            return game
        if toolbox_game is not None and (key != 'dxvk' or toolbox_game in allowed):
            return toolbox_game
        if not game_only:
            system = self.values.get(f'windows.uwt_{key}')
            if system in allowed:
                return system
        return None

    def assigned_dxvk_bundles(self):
        if 'dxvk' in self.keys:
            return {value for key, value in self.values.items() if key == 'windows.uwt_dxvk'
                    or (key.startswith('windows["') and key.endswith('"].uwt_dxvk'))}
        return set()


def mangohud_settings(directory, rom):
    from mangohud_settings import settings
    effective = settings(directory, rom)
    overrides = Overrides(rom)
    if not overrides.keys.intersection(('mangohud_display', 'mangohud_fps', 'mangohud_vulkan')):
        return effective
    per_game = settings(directory, rom, effective=False)
    for key in ('display', 'fps', 'vulkan'):
        value = overrides.get('mangohud_'+key, toolbox_game=per_game.get(key))
        if value is not None:
            effective[key] = value
    return effective


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('list')
    sub.add_parser('remove')
    sub.add_parser('refresh')
    sub.add_parser('dxvk-assigned')
    enable = sub.add_parser('enable-community')
    enable.add_argument('language', choices=('fr', 'en'))
    put = sub.add_parser('publish')
    put.add_argument('language', choices=('fr', 'en'))
    put.add_argument('groups', nargs='*')
    get = sub.add_parser('get')
    get.add_argument('key', choices=tuple(key for key in CHOICES if key not in COMMUNITY_NAMES))
    get.add_argument('rom')
    get.add_argument('--game-only', action='store_true')
    get.add_argument('--toolbox-game')
    args = parser.parse_args()
    if args.action == 'list':
        enabled = exposed()
        for name, items in OPTIONS.items():
            if any(key in enabled for key, _, _ in items):
                print(name)
    elif args.action == 'remove':
        if not FEATURES.is_symlink() and OWNER in option_file():
            FEATURES.unlink()
    elif args.action == 'refresh':
        refresh()
    elif args.action == 'enable-community':
        enable_community(args.language)
    elif args.action == 'dxvk-assigned':
        print('\n'.join(sorted(Overrides('').assigned_dxvk_bundles())))
    elif args.action == 'publish':
        if unknown := set(args.groups) - OPTIONS.keys() - {'community'}:
            parser.error(f'unknown ES options: {", ".join(sorted(unknown))}')
        publish(args.groups, args.language)
    else:
        if args.key != 'dxvk' and args.toolbox_game not in (None, 'on', 'off'):
            parser.error('--toolbox-game requires on or off for this option')
        overrides = Overrides(args.rom)
        if args.key != 'dxvk' or 'dxvk' in overrides.keys:
            print(overrides.get(args.key, game_only=args.game_only, toolbox_game=args.toolbox_game) or '')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, ET.ParseError) as exc:
        print(f'ES options: {exc}', file=sys.stderr)
        sys.exit(1)
