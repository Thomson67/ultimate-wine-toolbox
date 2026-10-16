"""Convert Batocera player-one Pad2Key mappings to Linux AntiMicroX profiles."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

from antimicrox_live import atomic
from antimicrox_pad2key_state import Pad2KeyStore

BUTTONS = {'b': 1, 'a': 2, 'y': 3, 'x': 4, 'select': 5, 'start': 7,
           'l3': 8, 'r3': 9, 'pageup': 10, 'pagedown': 11}
STICK_DIRECTIONS = {'up': 1, 'right': 3, 'down': 5, 'left': 7}
DPAD = {'up': 1, 'right': 2, 'down': 4, 'left': 8}
QT_KEYS = {'KEY_ESC': 0x1000000, 'KEY_TAB': 0x1000001, 'KEY_BACKSPACE': 0x1000003,
           'KEY_ENTER': 0x1000004, 'KEY_INSERT': 0x1000006,
           'KEY_DELETE': 0x1000007, 'KEY_PAUSE': 0x1000008, 'KEY_HOME': 0x1000010,
           'KEY_END': 0x1000011, 'KEY_LEFT': 0x1000012, 'KEY_UP': 0x1000013,
           'KEY_RIGHT': 0x1000014, 'KEY_DOWN': 0x1000015, 'KEY_PAGEUP': 0x1000016,
           'KEY_PAGEDOWN': 0x1000017, 'KEY_LEFTSHIFT': 0x1000020, 'KEY_LEFTCTRL': 0x1000021,
           'KEY_LEFTALT': 0x1000023, 'KEY_CAPSLOCK': 0x1000024, 'KEY_NUMLOCK': 0x1000025,
           'KEY_SCROLLLOCK': 0x1000026, 'KEY_SPACE': 0x20}
QT_KEYS.update({f'KEY_{c}': ord(c) for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'})
QT_KEYS.update({f'KEY_F{n}': 0x100002f+n for n in range(1, 25)})
QT_KEYS.update({name: ord(char) for name, char in {
    'KEY_MINUS': '-', 'KEY_EQUAL': '=', 'KEY_LEFTBRACE': '[', 'KEY_RIGHTBRACE': ']',
    'KEY_SEMICOLON': ';', 'KEY_APOSTROPHE': "'", 'KEY_GRAVE': '`', 'KEY_BACKSLASH': '\\',
    'KEY_COMMA': ',', 'KEY_DOT': '.', 'KEY_SLASH': '/'}.items()})
# Native Linux uinput codes retain modifier side and keypad identity.
NATIVE_KEYS = {'KEY_RIGHTSHIFT': 54, 'KEY_KPENTER': 96, 'KEY_RIGHTCTRL': 97, 'KEY_RIGHTALT': 100,
               'KEY_LEFTMETA': 125, 'KEY_RIGHTMETA': 126, 'KEY_SYSRQ': 99,
               'KEY_KP0': 82, 'KEY_KP1': 79, 'KEY_KP2': 80, 'KEY_KP3': 81,
               'KEY_KP4': 75, 'KEY_KP5': 76, 'KEY_KP6': 77, 'KEY_KP7': 71,
               'KEY_KP8': 72, 'KEY_KP9': 73, 'KEY_KPDOT': 83, 'KEY_KPSLASH': 98,
               'KEY_KPASTERISK': 55, 'KEY_KPMINUS': 74, 'KEY_KPPLUS': 78, 'KEY_KPEQUAL': 117}


def target_slot(target):
    if target in ('BTN_LEFT', 'BTN_MIDDLE', 'BTN_RIGHT'):
        return 'mousebutton', {'BTN_LEFT': 1, 'BTN_MIDDLE': 2, 'BTN_RIGHT': 3}[target]
    if target in QT_KEYS:
        return 'keyboard', QT_KEYS[target]
    native = NATIVE_KEYS.get(target)
    if native is None and isinstance(target, str) and target.startswith('KEY_'):
        try:
            from evdev import ecodes
            native = ecodes.ecodes.get(target)
        except ImportError:
            pass
    if isinstance(native, int) and 0 < native < 0x2ff and target not in ('KEY_MAX', 'KEY_CNT'):
        return 'keyboard', 0x60000000+native
    raise ValueError(f'Unsupported key: {target}')


def control(trigger):
    if trigger in BUTTONS:
        return ('button', BUTTONS[trigger])
    if trigger in ('l2', 'r2'):
        return ('trigger', 5 if trigger == 'l2' else 6, 'triggerbutton', 2)
    if trigger in DPAD:
        return ('dpad', 1, 'dpadbutton', DPAD[trigger])
    for stick in (1, 2):
        for direction, index in STICK_DIRECTIONS.items():
            if trigger == f'joystick{stick}{direction}':
                return ('stick', stick, 'stickbutton', index)
    raise ValueError(f'Unsupported trigger: {trigger}')


def analyze(source):
    source = Path(source)
    if source.stat().st_size > 8*1024*1024:
        raise ValueError('Pad2Key file exceeds 8 MiB')
    raw = source.read_bytes()
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get('actions_player1'), list):
        raise ValueError('Expected a Pad2Key JSON with actions_player1')
    root = ET.Element('gamecontroller', {'configversion': '19', 'appversion': '3.6.1'})
    ET.SubElement(root, 'profilename').text = source.name.removesuffix('.keys')+' (Pad2Key)'
    group = ET.SubElement(ET.SubElement(root, 'sets'), 'set', {'index': '1'})
    bindings, descriptions, warnings, converted = {}, {}, [], 0
    actions = data['actions_player1']
    for position, action in enumerate(actions, 1):
        try:
            if not isinstance(action, dict):
                raise ValueError('Invalid action object')
            extras = set(action)-{'trigger', 'type', 'target', 'description', 'hold', 'mode'}
            if extras:
                raise ValueError('Unsupported fields: '+', '.join(sorted(extras)))
            if action.get('hold', 0) != 0:
                raise ValueError('Delayed/held trigger (hold) requires manual editing')
            if action.get('mode', 'all') not in ('all', 'any'):
                raise ValueError('Trigger sequences require manual editing')
            trigger = action.get('trigger')
            triggers = trigger if isinstance(trigger, list) else [trigger]
            if len(triggers) > 1 and action.get('mode', 'all') != 'any':
                raise ValueError('Button chords require manual editing')
            if not triggers or not all(isinstance(t, str) for t in triggers):
                raise ValueError('Invalid trigger')
            additions = []
            if action.get('type') == 'mouse':
                if (not isinstance(trigger, str) or 'target' in action
                        or ('mode' in action and action['mode'] != 'any')):
                    raise ValueError('Mouse action needs one joystick trigger, no target, and default/any mode')
                for trigger in triggers:
                    if trigger not in ('joystick1', 'joystick2'):
                        raise ValueError('Mouse action needs joystick1 or joystick2')
                    stick = int(trigger[-1])
                    for direction, mouse in [('up', 1), ('down', 2), ('left', 3), ('right', 4)]:
                        additions.append((('stick', stick, 'stickbutton', STICK_DIRECTIONS[direction]), [('mousemovement', mouse)]))
            elif action.get('type') == 'key':
                targets = action.get('target')
                targets = targets if isinstance(targets, list) else [targets]
                if not targets or not all(isinstance(t, str) for t in targets):
                    raise ValueError('Empty or invalid key targets')
                slots = [target_slot(target) for target in targets]
                additions = [(control(trigger), slots) for trigger in triggers]
            else:
                raise ValueError('Only key and mouse actions are converted; shell commands are never executed')
            for destination, slots in additions:
                result = bindings.setdefault(destination, [])
                for slot in slots:
                    if slot not in result:
                        result.append(slot)
                if isinstance(action.get('description'), str) and action['description']:
                    descriptions.setdefault(destination, []).append(action['description'])
            converted += 1
        except (ValueError, TypeError) as error:
            warnings.append(f'actions_player1 #{position}: {error}')
    for player, values in data.items():
        if player != 'actions_player1' and values:
            warnings.append(f'{player}: not converted (player-one profiles only)')
    containers = {}
    for destination, slots in bindings.items():
        if len(destination) == 2:
            button = ET.SubElement(group, destination[0], {'index': str(destination[1])})
        else:
            parent_key = destination[:2]
            if parent_key not in containers:
                containers[parent_key] = ET.SubElement(group, destination[0], {'index': str(destination[1])})
            button = ET.SubElement(containers[parent_key], destination[2], {'index': str(destination[3])})
        if destination in descriptions:
            ET.SubElement(button, 'actionname').text = ' ; '.join(dict.fromkeys(descriptions[destination]))
        slot_group = ET.SubElement(button, 'slots')
        for mode, code in slots:
            slot = ET.SubElement(slot_group, 'slot')
            ET.SubElement(slot, 'code').text = hex(code) if mode == 'keyboard' else str(code)
            ET.SubElement(slot, 'mode').text = mode
    ET.indent(root, space='  ')
    xml = ET.tostring(root, encoding='utf-8', xml_declaration=True)+b'\n'
    return {'source': str(source.resolve()), 'sha256': hashlib.sha256(raw).hexdigest(),
            'converted': converted, 'total': len(actions), 'warnings': warnings, 'xml': xml,
            'triggers': [a['trigger'] for a in actions if isinstance(a, dict) and 'trigger' in a]}


def summary(result, fr=True):
    lines = [result['source'], '', ('Actions converties' if fr else 'Converted actions')+
             f" : {result['converted']} / {result['total']}"]
    lines.append(('Actions à reprendre manuellement' if fr else 'Actions requiring manual editing')+f" : {len(result['warnings'])}")
    translations = {
        'Unsupported key:': 'Touche non reconnue :',
        'Unsupported trigger:': 'Déclencheur non reconnu :',
        'Unsupported fields:': 'Champs non pris en charge :',
        'Delayed/held trigger (hold) requires manual editing': 'Déclenchement temporisé (hold) : à reprendre manuellement',
        'Trigger sequences require manual editing': 'Séquence de boutons : à reprendre manuellement',
        'Button chords require manual editing': 'Combinaison de boutons : à reprendre manuellement',
        'Only key and mouse actions are converted; shell commands are never executed': 'Commande externe non convertie et jamais exécutée',
        'not converted (player-one profiles only)': 'non converti (seul le joueur 1 est pris en charge)',
        'Mouse action needs one joystick trigger, no target, and default/any mode': 'Action souris non standard : à reprendre manuellement',
    }
    for warning in result['warnings']:
        if fr:
            for original, translated in translations.items():
                warning = warning.replace(original, translated)
        lines.append('  - '+warning)
    lines += ['', 'La vitesse de souris et la zone morte peuvent nécessiter un ajustement dans AntiMicroX.' if fr else
              'Mouse speed and deadzone may need adjustment in AntiMicroX.',
              'Le fichier Pad2Key original reste inchangé pendant la conversion.' if fr else
              'Conversion leaves the original Pad2Key file unchanged.']
    return '\n'.join(lines)


def convert(source, home, expected=None, userdata='/userdata'):
    result = analyze(source)
    if expected and result['sha256'] != expected:
        raise ValueError('Pad2Key changed since preview. Analyze it again.')
    if not result['converted']:
        raise ValueError('No supported actions to convert')
    store = Pad2KeyStore(home, userdata)
    folder = Path(home)/'config/antimicrox-profiles'
    folder.mkdir(parents=True, exist_ok=True)
    stem = Path(source).name.removesuffix('.keys').removesuffix('.wsquashfs')
    if stem == 'padto':
        stem = Path(source).parent.stem
    stem = ''.join(c if c.isalnum() or c in ' -_[]' else '_' for c in stem)[:90] or 'Pad2Key'
    base = stem+'-pad2key-'+hashlib.sha256(result['source'].encode()).hexdigest()[:8]
    with store.locked():
        destination, suffix = folder/(base+'.amgp'), 2
        while destination.exists() or destination.is_symlink():
            destination = folder/(base+f'-{suffix}.amgp'); suffix += 1
        created = None
        try:
            with store.transaction():
                # Exclusive creation also protects against an external editor race.
                with destination.open('xb') as stream:
                    created = os.fstat(stream.fileno()).st_ino
                    stream.write(result['xml'])
                registry = store.read(store.registry)
                registry[str(destination.resolve())] = {k: result[k] for k in ('source', 'sha256', 'converted', 'total', 'warnings', 'triggers')}
                atomic(store.registry, json.dumps(registry, ensure_ascii=False, indent=2).encode())
        except BaseException:
            if created is not None and destination.exists() and destination.stat().st_ino == created and destination.read_bytes() == result['xml']:
                destination.unlink()
            raise
    return destination


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', default=os.environ.get('WT_HOME', '/userdata/system/ultimate-wine-toolbox'))
    parser.add_argument('--language', default='fr')
    sub = parser.add_subparsers(dest='action', required=True)
    for name in ('preview', 'convert'):
        command = sub.add_parser(name); command.add_argument('source')
        if name == 'convert': command.add_argument('--expected')
    assign = sub.add_parser('assign'); assign.add_argument('rom'); assign.add_argument('profile')
    sub.add_parser('restore-all')
    args = parser.parse_args()
    if args.action == 'preview':
        result = analyze(args.source)
        print(result['sha256']); print(summary(result, args.language == 'fr'))
    elif args.action == 'convert':
        print(convert(args.source, args.home, args.expected))
    elif args.action == 'assign':
        store = Pad2KeyStore(args.home)
        if args.profile and str(Path(args.profile).resolve()) in store.read(store.registry):
            if not os.access(Path(args.home)/'tools/antimicrox/antimicrox', os.X_OK) or not os.access('/dev/uinput', os.W_OK):
                raise ValueError('Install AntiMicroX and check /dev/uinput before enabling the converted profile')
        store.assign(args.rom, args.profile)
    else:
        Pad2KeyStore(args.home).restore_all()


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr); sys.exit(1)
