"""Private runtime profiles: reserve the keyboard chord and suspend AMX output.

Saved profiles are never edited. The common AMX lock serialises profile IPC
with launcher transitions and game shutdown.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from antimicrox_live import atomic

INDICES = {'guide': 6, 'b': 1, 'a': 2, 'y': 3, 'x': 4, 'select': 5,
           'l3': 8, 'r3': 9, 'pageup': 10, 'pagedown': 11}


def active_modifiers():
    # Saved ES entries include disconnected controllers with other Hotkeys.
    # Only physical devices validated by the same watcher affect this session.
    from virtual_keyboard_runtime import controllers
    devices = controllers()
    try:
        return [INDICES[d.amx_hotkey] for d in devices if d.amx_hotkey in INDICES]
    finally:
        for device in devices:
            device.close()


def reserved_profile(source, modifiers=None):
    root = ET.parse(source).getroot()
    if root.tag != 'gamecontroller':
        raise ValueError(f'Unsupported AntiMicroX joystick profile: {source}')
    sets = root.find('sets')
    if sets is None:
        return ET.tostring(root, encoding='utf-8', xml_declaration=True)
    modifiers = modifiers if modifiers is not None else active_modifiers()
    modifiers = set(modifiers)
    populated = [s for s in sets.findall('set') if any(c.tag != 'name' for c in s)]
    if not populated:
        return ET.tostring(root, encoding='utf-8', xml_declaration=True)
    if len(modifiers) != 1 or 5 in modifiers:
        raise ValueError('AntiMicroX keyboard requires one distinct configured Hotkey button')
    modifier = next(iter(modifiers))
    by_index = {s.get('index'): s for s in sets.findall('set')}
    switches = {}
    for group in populated:
        button = group.find(f'button[@index="{modifier}"]')
        if button is not None and button.find('setselect') is not None:
            target = button.findtext('setselect')
            if button.findtext('setselectcondition') != 'while-held' or target not in by_index:
                raise ValueError('Unsupported AntiMicroX Hotkey set switch')
            switches[group.get('index')] = target
    # Reciprocal while-held pairs use the lower-numbered set as their base.
    # One-way declarations identify their held target directly.
    held = {target for source, target in switches.items()
            if switches.get(target) != source or int(source) < int(target)}
    if (root.findtext('setindex') or '1') in held:
        raise ValueError('AntiMicroX starts in a held Hotkey set')
    for group in list(populated):
        if group.get('index') in held:
            continue
        button = group.find(f'button[@index="{modifier}"]')
        target = button.findtext('setselect') if button is not None else None
        if not target:
            free = next((str(i) for i in range(1, 9)
                         if str(i) not in by_index or not any(c.tag != 'name' for c in by_index[str(i)])), None)
            if free is None:
                raise ValueError('No unused AntiMicroX set for keyboard chord')
            layer = copy.deepcopy(group)
            layer.set('index', free)
            if free in by_index:
                sets.remove(by_index[free])
            sets.append(layer); by_index[free] = layer
            for current, destination in ((group, free), (layer, group.get('index'))):
                hk = current.find(f'button[@index="{modifier}"]')
                if hk is not None:
                    current.remove(hk)
                hk = ET.SubElement(current, 'button', {'index': str(modifier)})
                ET.SubElement(hk, 'setselect').text = destination
                ET.SubElement(hk, 'setselectcondition').text = 'while-held'
            target = free
        layer = by_index[target]
        select = layer.find('button[@index="5"]')
        if select is not None:
            layer.remove(select)
        # An empty Select in the held layer reserves the chord for the OSK.
        ET.SubElement(layer, 'button', {'index': '5'})
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)+b'\n'


def runtime_profile(home, rom, source):
    from virtual_keyboard import Settings
    home = Path(home)
    if not Settings(home).enabled(rom):
        return str(source)
    try:
        raw = reserved_profile(source)
    except ValueError as exc:
        # Keep normal game controls if this unusual profile cannot be adapted.
        # The keyboard preflight reports the reason and refuses its own start.
        print(f'virtual_keyboard_profile_refused={exc}', file=sys.stderr)
        return str(source)
    state = home/'state/virtual-keyboard/profiles'
    state.mkdir(parents=True, exist_ok=True)
    path = state/(hashlib.sha256(raw).hexdigest()+'.amgp')
    if not path.exists():
        atomic(path, raw)
    atomic(state/'requested', json.dumps({'rom': str(rom), 'profile': str(path)}).encode())
    marker = state/'visible'
    if marker.exists():
        from virtual_keyboard import process_identity
        owner = json.loads(marker.read_text())
        if (owner.get('rom') == str(rom) and owner.get('token')
                and process_identity(owner.get('pid')) == owner['token']):
            return empty_profile(home)
    return str(path)


def empty_profile(home):
    path = Path(home)/'state/virtual-keyboard/profiles/empty.amgp'
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic(path, b'<?xml version="1.0"?><gamecontroller configversion="19"><sets><set index="1"/></sets></gamecontroller>\n')
    return str(path)


def priority(home, rom, visible):
    """Only command the verified AMX instance owned by this game session."""
    import fcntl
    from antimicrox_launcher import Session
    home = Path(home)
    state = home/'state/virtual-keyboard/profiles'
    state.mkdir(parents=True, exist_ok=True)
    lockpath = home/'state/antimicrox/lock'
    if not lockpath.parent.exists():
        return
    with lockpath.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        marker = state/'visible'
        if visible:
            from virtual_keyboard import process_identity
            atomic(marker, json.dumps({'rom': str(rom), 'pid': os.getpid(), 'token': process_identity(os.getpid())}).encode())
        else:
            marker.unlink(missing_ok=True)
        try:
            fields = (lockpath.parent/'session').read_text().rstrip('\n').split('\t')
            if len(fields) != 3 or fields[0] != str(rom):
                return
            session = Session(home, fields[0], int(fields[1]), fields[2])
            if not session.active():
                return
            requested = state/'requested'
            if not requested.exists():
                raise RuntimeError('AntiMicroX runtime profile not prepared; restart the game')
            data = json.loads(requested.read_text())
            if data.get('rom') != str(rom):
                raise RuntimeError('AntiMicroX runtime profile belongs to another game')
            profile = empty_profile(home) if visible else data['profile']
            subprocess.run([str(home/'tools/antimicrox/antimicrox'), '--hidden', '--no-tray', '--profile', profile],
                           check=True, timeout=5, stdin=subprocess.DEVNULL, close_fds=True,
                           env={**os.environ, 'XDG_CONFIG_HOME': str(home/'state/antimicrox/runtime-config')})
        except FileNotFoundError:
            return
