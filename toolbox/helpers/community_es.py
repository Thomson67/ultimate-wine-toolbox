"""Dispatch a share selected in ES after EmulationStation saves batocera.conf."""
import json
import os
from pathlib import Path
import re
import subprocess

from community_profiles import atomic, dump, es_games, game_key as title_key
from es_options import COMMUNITY_KEYS, CONF, FEATURES, Overrides, game_key

GAME_SETTING = re.compile(r'windows\["([^"\r\n]+)"\]\.uwt_(community_(?:antimicrox|reshade))')
SHARE_ID = re.compile(r'(?:[a-z0-9][a-z0-9-]{0,79}|zip:pack-[a-f0-9]{64})')
PORT = Path('/userdata/roms/ports/Ultimate Wine Toolbox.sh')
DISPLAY_VARS = {'DISPLAY', 'XAUTHORITY', 'WAYLAND_DISPLAY', 'XDG_RUNTIME_DIR',
                'DBUS_SESSION_BUS_ADDRESS', 'HOME', 'SDL_VIDEODRIVER'}


def es_environment():
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            # Linux truncates comm to 15 characters. Check the executable too.
            if (process / 'comm').read_text().strip() != 'emulationstatio':
                continue
            executable = Path(os.readlink(process / 'exe')).name
            if executable != 'emulationstation':
                continue
            environment = {}
            for field in (process / 'environ').read_bytes().split(b'\0'):
                key, _, value = os.fsdecode(field).partition('=')
                if key in DISPLAY_VARS and value:
                    environment[key] = value
            environment.setdefault('DISPLAY', ':0')
            if Path('/var/lib/.Xauthority').is_file():
                environment.setdefault('XAUTHORITY', '/var/lib/.Xauthority')
            return dict(os.environ, **environment)
        except OSError:
            continue
    return None


def resolve_game(option, setting, share):
    matches = [(rom, title) for rom, title in es_games()
               if game_key(rom, option) == setting and Path(rom).exists()]
    if len(matches) == 1:
        rom, title = matches[0]
        if title_key(share['game']) in ({title_key(rom), title_key(title)} - {''}):
            return rom
    return None


class Selections:
    def __init__(self, home, catalogue, features=FEATURES, conf=CONF):
        self.home = home
        self.catalogue = catalogue
        self.features = features
        self.conf = conf
        self.state = home / 'state/community/es-selections.json'
        self.process = None
        self.stamp = None
        self.dispatched = None
        self.current = None

    def poll(self):
        if self.process is not None and self.process.poll() is None:
            return
        stat = self.conf.stat()
        features_stat = self.features.stat() if self.features.is_file() else None
        stamp = (stat.st_ino, stat.st_mtime_ns, stat.st_size,
                 features_stat.st_mtime_ns if features_stat else None)
        if stamp != self.stamp:
            self.stamp = stamp
            self.current = None
            return  # ES copies over batocera.conf. Read only after it settles.
        if self.current is None:
            overrides = Overrides('', features=self.features, conf=self.conf)
            current = {}
            for key, value in overrides.values.items():
                match = GAME_SETTING.fullmatch(key)
                if (match and match[2] in overrides.keys and value not in {'auto', 'catalogue-unavailable'}
                        and SHARE_ID.fullmatch(value)):
                    current[key] = value
            self.current = current
        if self.dispatched is None:
            try:
                saved = json.loads(self.state.read_text())
                self.dispatched = saved if isinstance(saved, dict) else {}
            except (FileNotFoundError, ValueError):
                self.dispatched = {}
        delivered = {key: value for key, value in self.dispatched.items() if self.current.get(key) == value}
        pending = next(((key, value) for key, value in self.current.items() if key not in delivered), None)
        if pending and (environment := es_environment()):
            key, value = pending
            option = GAME_SETTING.fullmatch(key)[2]
            kind = next(kind for kind, name in COMMUNITY_KEYS.items() if name == option)
            share = self.catalogue(self.home, kind).get(value)
            rom = resolve_game(option, key, share) if share else None
            args = [kind, rom, value] if rom else ['unavailable']
            print(f'ES community {key}: {value} ({rom or "no matching game"})', flush=True)
            self.process = subprocess.Popen(
                ['/bin/bash', str(PORT), '--community-selection', *args],
                env=environment, stdin=subprocess.DEVNULL, start_new_session=True,
            )
            delivered[key] = value
        if delivered != self.dispatched:
            atomic(self.state, dump(delivered))
            self.dispatched = delivered
