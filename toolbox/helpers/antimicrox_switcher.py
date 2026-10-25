"""Temporarily exclude EmulationStation from labwc Alt+Tab during live editing."""
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET

from antimicrox_live import atomic


class SwitcherScope:
    def __init__(self, home, config=Path('/userdata/system/.config/labwc/rc.xml'), reload=None):
        self.state = Path(home)/'state/antimicrox-labwc-switcher.json'
        self.config = Path(config)
        self.reload = reload or self.reconfigure

    @staticmethod
    def reconfigure():
        subprocess.run(['labwc', '--reconfigure'], check=True, timeout=3,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE)

    def hide(self, session_id):
        if not os.environ.get('WAYLAND_DISPLAY') or not self.config.exists():
            return False
        if not re.fullmatch(r'[A-Za-z0-9_-]+', session_id):
            raise ValueError('Invalid live-session identifier')
        if self.state.exists():
            previous = json.loads(self.state.read_text())
            if previous['session_id'] == session_id:
                return True
            self.restore()
        path = self.config.resolve(strict=True)
        raw = path.read_bytes()
        root = ET.fromstring(raw)
        if root.tag.startswith('{'):
            raise ValueError('Namespaced labwc configuration is unsupported; preserved')
        groups = root.findall('windowRules')
        if len(groups) > 1:
            raise ValueError('Multiple labwc windowRules sections; configuration preserved')
        block = (f'\n<!-- UWT AntiMicroX switcher {session_id} begin -->\n'
                 '<windowRule identifier="emulationstation" skipWindowSwitcher="yes" />\n'
                 f'<!-- UWT AntiMicroX switcher {session_id} end -->\n').encode()
        before = after = None
        if groups and re.search(rb'</windowRules\s*>', raw):
            match = list(re.finditer(rb'</windowRules\s*>', raw))[-1]
            injected = raw[:match.start()]+block+raw[match.start():]
        elif groups:
            match = re.search(rb'<windowRules\s*/>', raw)
            if not match:
                raise ValueError('Unsupported labwc windowRules layout; preserved')
            before = match.group().decode()
            after = '<windowRules>'+block.decode()+'</windowRules>'
            injected = raw[:match.start()]+after.encode()+raw[match.end():]
        else:
            match = re.search(rb'</'+re.escape(root.tag.encode())+rb'\s*>\s*$', raw)
            if not match:
                raise ValueError('Cannot locate labwc configuration root; preserved')
            before = ''
            after = '<windowRules>'+block.decode()+'</windowRules>\n'
            injected = raw[:match.start()]+after.encode()+raw[match.start():]
        ET.fromstring(injected)
        mode = stat.S_IMODE(path.stat().st_mode)
        data = {'session_id': session_id, 'path': str(path), 'block': block.decode(),
                'container_before': before, 'container_after': after}
        # Persist recovery information before modifying the compositor config.
        atomic(self.state, json.dumps(data).encode(), 0o600)
        atomic(path, injected, mode)
        try:
            self.reload()
        except (OSError, subprocess.SubprocessError):
            self.restore(session_id)
            raise
        print('AntiMicroX live Alt+Tab: EmulationStation temporarily excluded', file=sys.stderr, flush=True)
        return True

    def restore(self, session_id=None):
        if not self.state.exists():
            return False
        data = json.loads(self.state.read_text())
        if session_id is not None and data['session_id'] != session_id:
            return False
        path = Path(data['path'])
        raw = path.read_bytes()
        block = data['block'].encode()
        after = data.get('container_after')
        if after and after.encode() in raw:
            restored = raw.replace(after.encode(), data['container_before'].encode(), 1)
        elif block in raw:
            restored = raw.replace(block, b'', 1)
        else:
            # A manual removal is fine; an edited owned block needs recovery.
            marker = f'UWT AntiMicroX switcher {data["session_id"]}'.encode()
            if marker in raw:
                raise ValueError('Temporary labwc rule was edited; recovery record retained')
            restored = raw
        ET.fromstring(restored)
        if restored != raw:
            atomic(path, restored, stat.S_IMODE(path.stat().st_mode))
        # Retain recovery information if the compositor did not accept reload.
        self.reload()
        self.state.unlink()
        print('AntiMicroX live Alt+Tab: EmulationStation exclusion removed', file=sys.stderr, flush=True)
        return True


def update_scope(home, action, session_id=None):
    """Compositor customization must never prevent game launch or key recovery."""
    try:
        scope = SwitcherScope(home)
        return scope.hide(session_id) if action == 'hide' else scope.restore(session_id)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'AntiMicroX live Alt+Tab scope unavailable: {exc}', file=sys.stderr, flush=True)
        return False
