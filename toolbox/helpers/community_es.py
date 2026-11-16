"""Dispatch a share selected in ES after EmulationStation saves batocera.conf."""
import json
from pathlib import Path
import re
import time

from antimicrox_handoff import EsApi
from toolbox_return import resume
from community_profiles import atomic, dump, es_games, game_key as title_key
from es_options import COMMUNITY_KEYS, CONF, FEATURES, Overrides, game_key

GAME_SETTING = re.compile(r'windows\["([^"\r\n]+)"\]\.uwt_(community_(?:antimicrox|reshade))')
SHARE_ID = re.compile(r'(?:[a-z0-9][a-z0-9-]{0,79}|zip:pack-[a-f0-9]{64})')
REQUEST = 'community-es.request'
OTHER_WORKFLOWS = ('resume-wsq.request', 'launch-game.request', 'restart-es.request',
                   'reshade-diagnostic.json', 'antimicrox-live.json')


def open_selection(home, api, args):
    request = home / 'state' / REQUEST
    atomic(request, ('\n'.join(args) + '\n').encode())
    try:
        return resume(home, None, api=api, timeout=5, refresh_timeout=15,
                      confirm_timeout=45, request_name=REQUEST, max_attempts=1)
    finally:
        request.unlink(missing_ok=True)


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
        self.stamp = None
        self.dispatched = None
        self.current = None
        self.retry_at = 0
        self.failed = {}

    def poll(self):
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
        self.save_delivered(delivered)
        self.failed = {key: value for key, value in self.failed.items() if self.current.get(key) == value}
        pending = next(((key, value) for key, value in self.current.items() if key not in delivered and key not in self.failed), None)
        if pending and time.monotonic() >= self.retry_at:
            api = EsApi()
            if api.running()[0] != 201 or any((self.home / 'state' / name).exists() for name in OTHER_WORKFLOWS):
                self.retry_at = time.monotonic() + 1
                return
            key, value = pending
            option = GAME_SETTING.fullmatch(key)[2]
            kind = next(kind for kind, name in COMMUNITY_KEYS.items() if name == option)
            share = self.catalogue(self.home, kind).get(value)
            rom = resolve_game(option, key, share) if share else None
            args = [kind, rom, value] if rom else ['unavailable']
            print(f'ES community {key}: {value} ({rom or "no matching game"})', flush=True)
            try:
                if open_selection(self.home, api, args):
                    delivered[key] = value
                    self.save_delivered(delivered)
                    return
            except (OSError, RuntimeError, ValueError) as error:
                print(f'ES community launch: {error}', flush=True)
            self.failed[key] = value
            print('ES community: launch unconfirmed; save Auto before retrying this selection', flush=True)

    def save_delivered(self, delivered):
        if delivered != self.dispatched:
            atomic(self.state, dump(delivered))
            self.dispatched = delivered
