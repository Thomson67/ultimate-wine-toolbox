"""Read AntiMicroX mappings and delete explicitly selected profile files."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import xml.etree.ElementTree as ET

from antimicrox_live import atomic
from antimicrox_pad2key_state import Pad2KeyStore


def number(text):
    try:
        return int(text, 16 if str(text).lower().startswith('0x') else 10)
    except (ValueError, TypeError):
        return None


def key_name(text, fr=False):
    value = number(text)
    specials = {0x1000000: 'Échap' if fr else 'Esc', 0x1000001: 'Tab',
        0x1000002: 'Maj+Tab' if fr else 'Shift+Tab', 0x1000003: 'Retour arrière' if fr else 'Backspace',
        0x1000004: 'Entrée' if fr else 'Return', 0x1000005: 'Entrée pavé numérique' if fr else 'Enter',
        0x1000006: 'Insert', 0x1000007: 'Suppr' if fr else 'Delete', 0x1000008: 'Pause',
        0x1000009: 'Impr. écran' if fr else 'Print', 0x1000010: 'Début' if fr else 'Home',
        0x1000011: 'Fin' if fr else 'End', 0x1000012: '←', 0x1000013: '↑',
        0x1000014: '→', 0x1000015: '↓', 0x1000016: 'Page ↑', 0x1000017: 'Page ↓',
        0x1000020: 'Maj' if fr else 'Shift', 0x1000021: 'Ctrl', 0x1000022: 'Super',
        0x1000023: 'Alt', 0x1000024: 'Verr. Maj' if fr else 'Caps Lock',
        0x1000025: 'Verr. Num' if fr else 'Num Lock', 0x1000026: 'Scroll Lock',
        0x20: 'Espace' if fr else 'Space'}
    if value in specials:
        return specials[value]
    if value is not None and 0x1000030 <= value <= 0x1000052:
        return f'F{value-0x1000030+1}'
    if value is not None and 0x21 <= value <= 0x10ffff and chr(value).isprintable():
        return chr(value)
    return ('Code touche ' if fr else 'Key code ') + str(text)


def slot_text(slot, fr):
    mode, code = slot.findtext('mode', 'keyboard'), slot.findtext('code', '?')
    if mode == 'keyboard':
        return key_name(code, fr)
    if mode == 'mix':
        return '(' + ' + '.join(slot_text(s, fr) for s in slot.findall('./slots/slot')) + ')'
    if mode == 'mousebutton':
        names = {1: ('clic gauche', 'left click'), 2: ('clic milieu', 'middle click'),
                 3: ('clic droit', 'right click'), 4: ('molette ↑', 'wheel ↑'),
                 5: ('molette ↓', 'wheel ↓'), 6: ('molette ←', 'wheel ←'), 7: ('molette →', 'wheel →')}
        return (names[number(code)][0 if fr else 1] if number(code) in names
                else ('Bouton souris ' if fr else 'Mouse button ') + code)
    if mode == 'mousemovement':
        return ('Souris ' if fr else 'Mouse ') + {1: '↑', 2: '↓', 3: '←', 4: '→'}.get(number(code), code)
    if mode in ('pause', 'hold', 'delay', 'release', 'keypress'):
        labels = {'pause': ('Pause', 'Pause'), 'hold': ('Maintien', 'Hold'),
            'delay': ('Délai', 'Delay'), 'release': ('Relâchement', 'Release'), 'keypress': ('Durée de frappe', 'Key press duration')}
        return f'{labels[mode][0 if fr else 1]} {code} ms'
    if mode == 'setchange':
        value = number(code)
        return ('Ensemble ' if fr else 'Set ') + str(value+1 if value is not None else code)
    if mode == 'loadprofile':
        return ('Charger profil : ' if fr else 'Load profile: ') + slot.findtext('profile', '?')
    if mode == 'textentry':
        return ('Texte : ' if fr else 'Text: ') + json.dumps(slot.findtext('text', ''), ensure_ascii=False)
    if mode == 'execute':
        return ('Exécuter : ' if fr else 'Execute: ') + json.dumps(slot.findtext('path', '')+' '+slot.findtext('arguments', ''), ensure_ascii=False)
    # Keep every field of unfamiliar/advanced slot types visible.
    return mode + ' [' + ', '.join(f'{e.tag}={e.text or ""}' for e in slot if e.tag != 'mode') + ']'


def controller_button(index, fr):
    # GameControllerSet indexes SDL_GameControllerButton + 1 in profile XML.
    names = {
        '1': 'A / Croix' if fr else 'A / Cross',
        '2': 'B / Rond' if fr else 'B / Circle',
        '3': 'X / Carré' if fr else 'X / Square',
        '4': 'Y / Triangle',
        '5': 'View / Share ou Create' if fr else 'View / Share or Create',
        '6': 'Xbox / PS', '7': 'Menu / Options',
        '8': 'Clic LS / L3' if fr else 'LS click / L3',
        '9': 'Clic RS / R3' if fr else 'RS click / R3',
        '10': 'LB / L1', '11': 'RB / R1',
        '12': 'D-pad ↑', '13': 'D-pad ↓', '14': 'D-pad ←', '15': 'D-pad →',
        '16': 'Share (Xbox) / Micro (PS5)' if fr else 'Share (Xbox) / Mic (PS5)',
        '21': 'Pavé tactile (clic, PS)' if fr else 'Touchpad click (PS)',
    }
    original = ('Bouton ' if fr else 'Button ')+index
    return names[index]+f' [{original.lower()}]' if index in names else original


def report(profile, language='fr'):
    path = Path(profile)
    if path.stat().st_size > 8*1024*1024:
        raise ValueError('Profile XML exceeds 8 MiB')
    root = ET.parse(path).getroot()
    if root.tag not in ('gamecontroller', 'joystick'):
        raise ValueError('Not an AntiMicroX profile')
    fr = language == 'fr'
    standard = root.tag == 'gamecontroller'
    lines = [str(path), f'{root.tag} — {len(root.findall(".//slot"))} '+('actions enregistrées' if fr else 'recorded actions'),
             ('Taille (octets) : ' if fr else 'Size (bytes): ')+str(path.stat().st_size)]
    if root.findtext('profilename'):
        lines.append(root.findtext('profilename'))
    if standard:
        lines.append('Libellés : Xbox / PlayStation ; numéros AntiMicroX entre crochets.' if fr
                     else 'Labels: Xbox / PlayStation; AntiMicroX numbers in brackets.')
    directions = {'1': '↑', '2': '→', '3': '↗', '4': '↓', '6': '↘', '8': '←', '9': '↖', '12': '↙'}
    # JoyStickDirections is a clockwise 1..8 enum, NOT SDL's D-pad bitmask.
    stick_directions = {'1': '↑', '2': '↗', '3': '→', '4': '↘', '5': '↓', '6': '↙', '7': '←', '8': '↖'}
    labels = {'button': ('Bouton', 'Button'), 'stick': ('Stick', 'Stick'),
              'axis': ('Axe', 'Axis'), 'trigger': ('Gâchette', 'Trigger'),
              'dpad': ('Croix', 'D-pad'), 'vdpad': ('Croix virtuelle', 'Virtual D-pad'),
              'sensor': ('Capteur', 'Sensor')}
    buttons = {'button', 'axisbutton', 'triggerbutton', 'stickbutton',
               'stickmodifierbutton', 'dpadbutton', 'sensorbutton'}
    for group in root.findall('./sets/set'):
        lines += ['', ('Ensemble ' if fr else 'Set ')+group.get('index', '?')+
                  (f' — {group.findtext("name")}' if group.findtext('name') else '')]
        parents = {child: parent for parent in group.iter() for child in parent}
        found = False
        for button in group.iter():
            if button.tag not in buttons:
                continue
            slots = button.findall('./slots/slot')
            settings = [f'{e.tag}={e.text}' for e in button if e.tag != 'slots' and e.text]
            if not slots and not settings:
                continue
            found = True
            index = button.get('index', '?')
            parent = parents.get(button)
            if button.tag == 'button':
                label = controller_button(index, fr) if standard else ('Bouton ' if fr else 'Button ')+index
                custom = next((e.text for e in root.findall('./names/buttonname') if e.get('index') == index), None)
                if custom:
                    label += f' ({custom})'
            else:
                kind = parent.tag if parent is not None else button.tag
                parent_index = parent.get('index', '?') if parent is not None else '?'
                label = labels.get(kind, (kind, kind))[0 if fr else 1]+' '+parent_index
                if standard and kind == 'stick' and parent_index in ('1', '2'):
                    label = ({'1': 'Stick gauche (LS)', '2': 'Stick droit (RS)'} if fr else
                             {'1': 'Left stick (LS)', '2': 'Right stick (RS)'})[parent_index]
                elif standard and kind == 'trigger' and parent_index in ('1', '2', '5', '6'):
                    label = 'LT / L2' if parent_index in ('1', '5') else 'RT / R2'
                elif standard and kind == 'dpad' and parent_index == '1':
                    label = 'Croix directionnelle' if fr else 'D-pad'
                if button.tag in ('axisbutton', 'triggerbutton'):
                    label += ' '+{'1': '−', '2': '+'}.get(index, index)
                elif button.tag == 'stickmodifierbutton':
                    label += ' '+('modificateur' if fr else 'modifier')
                elif button.tag == 'sensorbutton':
                    label += ' '+index
                else:
                    direction_names = stick_directions if button.tag == 'stickbutton' else directions
                    label += ' '+direction_names.get(index, index)
            separator = ' + ' if all(s.findtext('mode', 'keyboard') in ('keyboard', 'mousebutton', 'mousemovement', 'mix') for s in slots) else ' ; '
            lines.append(label+' : '+(separator.join(slot_text(s, fr) for s in slots) if slots else ('sans touche' if fr else 'no key')))
            if settings:
                lines.append('    '+', '.join(settings))
        if not found:
            lines.append('  '+('Aucune affectation.' if fr else 'No mappings.'))
    if root.find('./sets/set') is None:
        lines += ['', 'Aucune affectation.' if fr else 'No mappings.']
    # A scrollable text report: wrap long commands instead of horizontal scrolling.
    lines = [re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', lambda match: f'\\x{ord(match[0]):02x}', line) for line in lines]
    return '\n'.join('\n'.join(textwrap.wrap(line, 88, subsequent_indent='    ', replace_whitespace=False))
                     if line else '' for line in lines)+'\n'


class ProfileInUse(ValueError):
    """A profile must be managed through the game or bundle that uses it."""


class Profiles:
    def __init__(self, home, userdata='/userdata', active=None):
        self.home, self.userdata = Path(home), Path(userdata).resolve()
        self.cfg = self.home/'config/antimicrox-games.tsv'
        self.active = active or self.running

    def running(self):
        pattern = '^'+re.escape(str(self.home/'tools/antimicrox/squashfs-root'))+r'/(AppRun|usr/bin/antimicrox)(\s|$)'
        return any(subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
                   for command in (['pgrep', '-x', 'antimicrox'], ['pgrep', '-f', pattern]))

    def raw(self):
        return self.cfg.read_bytes() if self.cfg.exists() else b''

    def references(self, path, raw):
        keep, games = [], []
        for line in raw.decode('utf-8').splitlines(keepends=True):
            fields = line.rstrip('\r\n').split('\t')
            try:
                matched = len(fields) == 2 and Path(fields[1]).resolve() == path
            except (OSError, RuntimeError):
                matched = False
            if matched:
                games.append(fields[0])
            else:
                keep.append(line)
        return sorted(set(games)), ''.join(keep).encode('utf-8')

    def validate(self, path):
        original = Path(path)
        if any(char in str(original) for char in '\n\r\t'):
            raise ValueError('Profile paths cannot contain tabs or line breaks')
        if original.is_symlink():
            raise ValueError('Refusing to delete a symlink')
        path = original.resolve(strict=True)
        if not path.is_relative_to(self.userdata) or path.suffix.lower() != '.amgp' or not path.is_file():
            raise ValueError('Select an .amgp file under /userdata')
        return path

    def plan(self, selected, unassigned=False):
        path = self.validate(selected)
        raw = self.raw()
        games, remaining = self.references(path, raw)
        if unassigned and games:
            raise ProfileInUse("This profile is assigned to a game. Use its game configuration menu.")
        # Launcher pairs must be removed as a configuration, including secondary
        # references that are not present in the primary-association TSV.
        for config in (self.home/'config/antimicrox-launchers').glob('*.json'):
            if config.is_symlink() or config.stat().st_size > 1024*1024:
                raise ValueError('Invalid launcher configuration; use its game menu')
            value = json.loads(config.read_text())
            if not isinstance(value, dict): raise ValueError('Invalid launcher configuration')
            if any(isinstance(value.get(key), str) and value[key] and Path(value[key]).resolve() == path
                   for key in ('launcher_profile', 'game_profile')):
                raise ProfileInUse('This profile belongs to a launcher configuration. Use its game menu to remove that configuration first.')
        imported = Pad2KeyStore(self.home, self.userdata).read(self.home/'state/community/imports.json')
        for owner, metadata in imported.items():
            config = metadata.get('launcher_config') if isinstance(metadata, dict) else None
            if (isinstance(config, dict) and isinstance(config.get('game_profile'), str)
                    and config['game_profile'] and Path(config['game_profile']).resolve() == path
                    and Path(owner).resolve() != path and Path(owner).is_file()):
                raise ProfileInUse('This profile is used by another stored launcher profile. Remove its configuration or owner profile first.')
        stat = path.stat()
        sha = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(65536), b''):
                sha.update(chunk)
        token = hashlib.sha256(json.dumps([str(path), stat.st_dev, stat.st_ino,
            stat.st_mtime_ns, sha.hexdigest(), hashlib.sha256(raw).hexdigest()]).encode()).hexdigest()
        return path, games, remaining, raw, token

    def list(self):
        candidates = set((self.home/'config/antimicrox-profiles').rglob('*.amgp'))
        for line in self.raw().decode('utf-8').splitlines():
            fields = line.split('\t')
            if len(fields) == 2 and fields[1]:
                candidates.add(Path(fields[1]))
        found = set()
        for path in candidates:
            try:
                found.add(self.validate(path))
            except (OSError, ValueError, RuntimeError):
                continue
        return sorted(found)

    def list_unassigned(self):
        found = []
        for path in self.list():
            try:
                self.plan(path, unassigned=True)
            except ProfileInUse:
                continue
            found.append(path)
        return found

    def delete(self, selected, token, unassigned=False):
        self.cfg.parent.mkdir(parents=True, exist_ok=True)
        with (self.cfg.parent/'antimicrox-games.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if self.active():
                raise ValueError('Close the game and AntiMicroX before deleting a profile')
            path, games, remaining, original, actual = self.plan(selected, unassigned=unassigned)
            if actual != token:
                raise ValueError('Profile or assignments changed. Select the profile again.')
            store = Pad2KeyStore(self.home, self.userdata)
            with store.transaction(games):
                # Stage on the same filesystem; restore file and TSV if deletion fails.
                folder = Path(tempfile.mkdtemp(prefix='.uwt-amx-delete-', dir=path.parent))
                backup = folder/path.name
                try:
                    os.replace(path, backup)
                    try:
                        store.restore(games)
                        registry = store.read(store.registry)
                        if registry.pop(str(path), None) is not None:
                            atomic(store.registry, json.dumps(registry, ensure_ascii=False, indent=2).encode())
                        if remaining != original:
                            atomic(self.cfg, remaining)
                        backup.unlink()
                    except BaseException:
                        # Never automatically remove a backup if restoration fails.
                        if backup.exists():
                            os.replace(backup, path)
                        if remaining != original:
                            atomic(self.cfg, original)
                        raise
                finally:
                    try:
                        folder.rmdir()
                    except OSError:
                        pass  # Keep a recoverable staged file after a failed restore.
            return games


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', default=os.environ.get('WT_HOME', '/userdata/system/ultimate-wine-toolbox'))
    parser.add_argument('--language', default='fr')
    parser.add_argument('--unassigned', action='store_true', help='Refuse profiles used by a game')
    parser.add_argument('action', choices=('report', 'list', 'list-unassigned', 'plan', 'delete'))
    parser.add_argument('profile', nargs='?')
    parser.add_argument('token', nargs='?')
    args = parser.parse_args()
    profiles = Profiles(args.home)
    if args.action == 'report':
        print(report(args.profile, args.language), end='')
    elif args.action in ('list', 'list-unassigned'):
        for path in (profiles.list_unassigned() if args.action == 'list-unassigned' else profiles.list()):
            print(path)
    elif args.action == 'plan':
        path, games, _, _, token = profiles.plan(args.profile, unassigned=args.unassigned)
        print(token)
        print(path)
        print(('Jeux associés' if args.language == 'fr' else 'Assigned games')+f' : {len(games)}')
        for game in games:
            print('  '+game)
    elif args.action == 'delete':
        profiles.delete(args.profile, args.token, unassigned=args.unassigned)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, ET.ParseError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
