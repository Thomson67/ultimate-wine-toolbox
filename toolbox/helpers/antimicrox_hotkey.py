"""Resolve the Batocera hotkey to a logical SDL game-controller button."""
from pathlib import Path
import xml.etree.ElementTree as ET

BUTTONS = {'b', 'a', 'x', 'y', 'select', 'l3', 'r3', 'pageup', 'pagedown'}


def choices(paths=None):
    paths = paths or ['/userdata/system/configs/emulationstation/es_input.cfg',
                      '/usr/share/emulationstation/es_input.cfg']
    seen, found = set(), {}
    for path in paths:
        if not Path(path).exists():
            continue
        root = ET.parse(path).getroot()
        for config in root.findall('inputConfig'):
            if config.get('type') != 'joystick':
                continue
            identity = (config.get('deviceGUID'), config.get('deviceName'))
            if identity in seen:
                continue
            seen.add(identity)
            inputs = config.findall('input')
            hotkey = next((item for item in inputs if item.get('name') == 'hotkey'), None)
            if hotkey is None or hotkey.get('type') != 'button' or hotkey.get('id') is None:
                continue
            aliases = [item.get('name') for item in inputs if item is not hotkey
                       and item.get('type') == 'button' and item.get('id') == hotkey.get('id')]
            # Batocera exports a standalone Hotkey as SDL Guide; duplicates use
            # their existing SDL button. Ambiguous aliases need manual editing.
            if not aliases:
                button = 'guide'
            elif len(aliases) == 1 and aliases[0] in BUTTONS:
                button = aliases[0]
            else:
                continue
            name = ' '.join((config.get('deviceName') or 'Controller').split())
            found.setdefault(button, []).append(name)
    return [(button, ' / '.join(dict.fromkeys(names))) for button, names in found.items()]
