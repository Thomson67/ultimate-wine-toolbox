"""An owned child of Ports lets ES launch UWT without ungrouping other systems."""
import copy
import os
from pathlib import Path
import shlex
import tempfile
import xml.etree.ElementTree as ET

SYSTEM = 'uwt_return'
MARKER = 'Managed by Ultimate Wine Toolbox: ES return proxy v1'
CONFIG_NAME = 'es_systems_uwt_return.cfg'


def atomic_owned(path, content, mode=0o644, marker=MARKER):
    if path.is_symlink() or (path.exists() and marker.encode() not in path.read_bytes()):
        raise ValueError(f'foreign return-proxy file will not be replaced: {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def ports_template(config_directory, system_directory):
    primary = next((folder / 'es_systems.cfg' for folder in (config_directory, system_directory)
                    if (folder / 'es_systems.cfg').is_file()), None)
    if primary is None:
        raise ValueError('native ES system configuration is unavailable')
    root = ET.parse(primary).getroot()
    ports = next((node for node in root.findall('system') if node.findtext('name') == 'ports'), None)
    if ports is None:
        raise ValueError('native Ports system definition is unavailable')
    ports = copy.deepcopy(ports)
    # ES applies user additions and then installed additions, field by field.
    for folder in dict.fromkeys((config_directory, system_directory)):
        for path in folder.glob('es_systems_*.cfg'):
            if path.name == CONFIG_NAME:
                continue
            for node in ET.parse(path).getroot().findall('system'):
                if node.findtext('name') != 'ports':
                    continue
                for field in node:
                    if field.tag == 'name':
                        continue
                    for old in ports.findall(field.tag):
                        ports.remove(old)
                    if field.tag == 'emulators' or (field.text or '').strip():
                        ports.append(copy.deepcopy(field))
    return ports


def ensure_proxy(home, config_directory=None, system_directory=None, port=None):
    home = Path(home)
    config_directory = Path(config_directory or '/userdata/system/configs/emulationstation')
    system_directory = Path(system_directory or '/usr/share/emulationstation')
    port = Path(port or '/userdata/roms/ports/Ultimate Wine Toolbox.sh')
    runtime = home / 'runtime/es-return-proxy'
    launcher = runtime / 'Ultimate Wine Toolbox Return.sh'
    config = config_directory / CONFIG_NAME
    if runtime.is_symlink() or runtime.resolve() != runtime:
        raise ValueError('return-proxy directory must not redirect outside its owned path')
    if not port.is_file():
        raise ValueError('installed Toolbox Ports launcher is unavailable')
    keys = Path(str(port) + '.keys')
    if not keys.is_file():
        raise ValueError('Toolbox Pad2Key profile is unavailable')
    # Guard the ES addition before writing any runtime assets.
    if config.is_symlink() or (config.exists() and MARKER.encode() not in config.read_bytes()):
        raise ValueError('foreign ES return-proxy definition will not be replaced')
    system = ports_template(config_directory, system_directory)
    command = system.findtext('command', '').strip()
    if not command:
        raise ValueError('native Ports launch command is unavailable')
    for node in system.iter('command'):
        if node.text:
            node.text = node.text.replace('%SYSTEM%', 'ports')
    for tag, value in {'name': SYSTEM, 'fullname': 'Ultimate Wine Toolbox return',
                       'path': str(runtime), 'extension': '.sh', 'platform': 'ignore',
                       'theme': 'ports', 'group': 'ports'}.items():
        for old in system.findall(tag):
            system.remove(old)
        ET.SubElement(system, tag).text = value
    document = ET.Element('systemList')
    document.append(ET.Comment(MARKER))
    document.append(system)
    wrapper = ('#!/bin/bash\n# ' + MARKER + '\nexec /bin/bash ' + shlex.quote(str(port)) + '\n').encode()
    gamelist = ET.Element('gameList')
    gamelist.append(ET.Comment(MARKER))
    # Hide the group's virtual child folder as well as the technical launcher.
    for kind, path in (('folder', '.'), ('game', './' + launcher.name)):
        entry = ET.SubElement(gamelist, kind)
        ET.SubElement(entry, 'path').text = path
        ET.SubElement(entry, 'name').text = 'Ultimate Wine Toolbox return'
        ET.SubElement(entry, 'hidden').text = 'true'
    atomic_owned(launcher, wrapper, 0o755)
    # Preserve exactly the installed Pad2Key actions. A separate marker avoids
    # adding nonstandard fields to evmapy's JSON format.
    key_path = Path(str(launcher) + '.keys')
    key_marker = runtime / 'pad2key.owner'
    if key_marker.is_symlink() or key_path.is_symlink() or (key_path.exists() and
            (not key_marker.is_file() or key_marker.read_text() != MARKER)):
        raise ValueError('foreign return-proxy Pad2Key file will not be replaced')
    runtime.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=runtime, delete=False) as stream:
        stream.write(keys.read_bytes())
        temp_keys = Path(stream.name)
    temp_keys.chmod(0o644)
    os.replace(temp_keys, key_path)
    key_marker.write_text(MARKER)
    atomic_owned(runtime / 'gamelist.xml', ET.tostring(gamelist, encoding='utf-8', xml_declaration=True))
    atomic_owned(config, ET.tostring(document, encoding='utf-8', xml_declaration=True))
    return SYSTEM, str(launcher)
