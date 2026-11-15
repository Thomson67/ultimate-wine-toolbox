"""Opt-in Windows options exported to EmulationStation."""
import argparse
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

from antimicrox_live import atomic

FEATURES = Path('/userdata/system/configs/emulationstation/es_features_ultimate_wine_toolbox.cfg')
CONF = Path('/userdata/system/batocera.conf')
OWNER = b'<!-- Managed by Ultimate Wine Toolbox -->'

SWITCH = {'on': ('Activé', 'Enabled'), 'off': ('Désactivé', 'Disabled')}
OPTIONS = {
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
    'antimicrox': (('antimicrox', ('AntiMicroX', 'AntiMicroX'),
                    {'on': ('Utiliser le profil associé', 'Use the assigned profile'), 'off': SWITCH['off']}),),
    'keyboard': (('keyboard', ('Clavier virtuel', 'Virtual keyboard'), SWITCH),),
    'mouse': (('mouse', ('Souris virtuelle', 'Virtual mouse'), SWITCH),),
    'reshade': (('reshade', ('ReShade configuré (par jeu)', 'Configured ReShade (per game)'), SWITCH),),
    'launcher': (('launcher', ('Réafficher le launcher (par jeu)', 'Show the launcher again (per game)'),
                   {'normal': ('Démarrage normal', 'Normal launch'),
                    'next': ('Au prochain démarrage', 'On next launch')}),),
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


def publish(groups, language, path=FEATURES):
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
            if key == 'launcher':
                feature.set('description', (
                    'Ouvrez les options du jeu. Si ES affiche encore « Au prochain démarrage » après usage, '
                    'enregistrez « Démarrage normal », puis réactivez l’option.',
                    'Use the game options. If ES still shows “On next launch” after use, '
                    'save “Normal launch”, then enable the request again.',
                )[index])
            for value, captions in choices.items():
                ET.SubElement(feature, 'choice', name=captions[index], value=value)
    ET.indent(xml)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic(path, OWNER + b'\n' + ET.tostring(xml, encoding='utf-8') + b'\n', mode=0o644)


def game_key(rom, key):
    name = Path(rom).name
    if any(character in name for character in '\r\n"'):
        return ''
    name = name.replace('=', '').replace('#', '')
    return f'windows["{name}"].uwt_{key}'


class Overrides:
    def __init__(self, rom, features=FEATURES, conf=CONF):
        self.rom = rom
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
        allowed = CHOICES[key]
        game = self.values.get(game_key(self.rom, key))
        if game in allowed:
            return game
        if toolbox_game is not None:
            return toolbox_game
        if not game_only:
            system = self.values.get(f'windows.uwt_{key}')
            if system in allowed:
                return system
        return None


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
    put = sub.add_parser('publish')
    put.add_argument('language', choices=('fr', 'en'))
    put.add_argument('groups', nargs='*')
    get = sub.add_parser('get')
    get.add_argument('key', choices=tuple(CHOICES))
    get.add_argument('rom')
    get.add_argument('--game-only', action='store_true')
    get.add_argument('--toolbox-game', choices=('on', 'off'))
    args = parser.parse_args()
    if args.action == 'list':
        enabled = exposed()
        for name, items in OPTIONS.items():
            if any(key in enabled for key, _, _ in items):
                print(name)
    elif args.action == 'remove':
        if not FEATURES.is_symlink() and OWNER in option_file():
            FEATURES.unlink()
    elif args.action == 'publish':
        if unknown := set(args.groups) - OPTIONS.keys():
            parser.error(f'unknown ES options: {", ".join(sorted(unknown))}')
        publish(args.groups, args.language)
    else:
        print(Overrides(args.rom).get(args.key, game_only=args.game_only, toolbox_game=args.toolbox_game) or '')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, ET.ParseError) as exc:
        print(f'ES options: {exc}', file=sys.stderr)
        sys.exit(1)
