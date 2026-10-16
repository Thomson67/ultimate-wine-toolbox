"""Enlarge only the editor's Qt settings, preserving profiles and other keys."""
import os
from pathlib import Path
import re
import subprocess
import sys


def display_bounds(text):
    outputs = []
    for line in text.splitlines():
        if re.search(r'\bconnected\b', line):
            match = re.search(r'(\d+)x(\d+)([+-]\d+)([+-]\d+)', line)
            if match:
                bounds = tuple(map(int, match.groups()))
                if ' primary ' in line:
                    return bounds
                outputs.append(bounds)
    if outputs:
        return outputs[0]
    match = re.search(r'current\s+(\d+)\s+x\s+(\d+)', text)
    if not match:
        match = re.search(r'dimensions:\s+(\d+)x(\d+)', text)
    return (*map(int, match.groups()), 0, 0) if match else None


def screen_bounds():
    for command in (['xrandr', '--current'], ['xdpyinfo']):
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=3,
                                    env=dict(os.environ, DISPLAY=os.environ.get('DISPLAY') or ':0'))
            bounds = display_bounds(result.stdout)
            if result.returncode == 0 and bounds:
                return bounds
        except (OSError, subprocess.TimeoutExpired):
            pass
    return 1366, 768, 0, 0


def prepare(config_home, bounds):
    path = Path(config_home)/'antimicrox/antimicrox_settings.ini'
    text = path.read_text() if path.exists() else ''
    lines = text.splitlines()
    # QSettings stores ungrouped keys under [General]; never edit profile groups.
    start = next((i for i, line in enumerate(lines) if line.strip() == '[General]'), None)
    if start is None:
        lines = ['[General]'] + lines
        start = 0
    end = next((i for i in range(start+1, len(lines)) if lines[i].startswith('[')), len(lines))
    old = re.search(r'^WindowSize=@Size\((\d+) (\d+)\)$', '\n'.join(lines[start+1:end]), re.M)
    old_width, old_height = map(int, old.groups()) if old else (0, 0)
    width, height, x, y = bounds
    width = min(max(1600, old_width), max(1, width-64))
    height = min(max(900, old_height), max(1, height-64))
    position = (x+(bounds[0]-width)//2, y+(bounds[1]-height)//2)
    general = [line for line in lines[start+1:end]
               if not re.match(r'^Window(?:Size|Position)\s*=', line)]
    general += [f'WindowSize=@Size({width} {height})',
                f'WindowPosition=@Point({position[0]} {position[1]})']
    lines[start+1:end] = general
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text('\n'.join(lines)+'\n')
    temporary.replace(path)
    return width, height


if __name__ == '__main__':
    width, height = prepare(sys.argv[1], screen_bounds())
    print(f'Editor window requested: {width}x{height}')
