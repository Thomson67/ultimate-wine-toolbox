"""Launch a live-editing game only after the Ports launcher has exited."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request
import urllib.parse

from antimicrox_live import LiveSession
from es_return_proxy import proxy_launcher

TOOLBOX = '/userdata/roms/ports/Ultimate Wine Toolbox.sh'
LOG_DIR = Path('/userdata/system/logs/ultimate-wine-toolbox')


class EsApi:
    def reload_games(self):
        # ES queues this on its UI thread; Ports must already have exited.
        with urllib.request.urlopen('http://127.0.0.1:1234/reloadgames', timeout=5) as response:
            if response.status != 200:
                raise RuntimeError(f'ES reload returned HTTP {response.status}')

    def indexed(self, rom, system=None):
        """Consult ES's in-memory list: /launch also returns 200 for unknown ROMs."""
        if system is None:
            parts = Path(rom).relative_to('/userdata/roms').parts
            if len(parts) < 2:
                raise ValueError('Invalid ROM path')
            system = parts[0]
        system = urllib.parse.quote(system, safe='')
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:1234/systems/{system}/games', timeout=5) as response:
                if response.status != 200:
                    raise RuntimeError(f'ES game list returned HTTP {response.status}')
                games = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:  # A newly populated system may not be loaded yet.
                return False
            raise
        if not isinstance(games, list) or any(not isinstance(game, dict) or
                                               not isinstance(game.get('path'), str) for game in games):
            raise ValueError('Invalid ES game list')
        return any(os.path.normpath(game['path']) == os.path.normpath(rom) for game in games)

    def system_info(self, system):
        name = urllib.parse.quote(system, safe='')
        with urllib.request.urlopen(f'http://127.0.0.1:1234/systems/{name}', timeout=5) as response:
            data = json.loads(response.read())
        if not isinstance(data, dict):
            raise ValueError('Invalid ES system information')
        return data

    def running(self):
        try:
            with urllib.request.urlopen('http://127.0.0.1:1234/runningGame', timeout=2) as response:
                if response.status in (201, 404):
                    return response.status, ''
                if response.status == 200:
                    body = json.loads(response.read())
                    return 200, body.get('path', '') if isinstance(body, dict) else ''
        except urllib.error.HTTPError as exc:
            if exc.code in (201, 404):
                return exc.code, ''
        except (OSError, ValueError):
            pass
        return None, ''

    def launch(self, rom):
        request = urllib.request.Request('http://127.0.0.1:1234/launch',
                                         data=rom.encode(), method='POST',
                                         headers={'Content-Type': 'text/plain; charset=utf-8'})
        with urllib.request.urlopen(request, timeout=5) as response:
            if response.status not in (200, 201, 202, 204):
                raise RuntimeError(f'ES launch returned HTTP {response.status}')


class Handoff:
    def __init__(self, session, rom, api=None, clock=time.monotonic, sleep=time.sleep,
                 idle_timeout=30, start_timeout=300, refresh_timeout=60):
        self.session, self.rom = session, rom
        self.api = api or EsApi()
        self.clock, self.sleep = clock, sleep
        self.idle_timeout, self.start_timeout = idle_timeout, start_timeout
        self.refresh_timeout = refresh_timeout
        self.session_id = (session.read() or {}).get('session_id')

    def owns_session(self):
        data = self.session.read()
        return bool(data and data['rom'] == self.rom and data.get('session_id') == self.session_id)

    def is_toolbox(self, path):
        return path in (TOOLBOX, str(proxy_launcher(self.session.home)))

    def require_active_session(self):
        if not self.owns_session() or self.session.read()['phase'] not in ('prepared', 'running'):
            raise RuntimeError('Live session was recovered or cancelled elsewhere')

    def ensure_indexed(self):
        self.require_active_session()
        if self.api.indexed(self.rom):
            return
        self.log('Game absent from ES list; requesting one automatic game-list refresh')
        # Recheck ES ownership immediately before queuing the refresh.
        code, path = self.api.running()
        if code not in (201, 404):
            raise RuntimeError(f'ES is no longer idle; game-list refresh cancelled: {path}')
        self.api.reload_games()
        deadline = self.clock()+self.refresh_timeout
        while self.clock() < deadline:
            self.require_active_session()
            code, path = self.api.running()
            if code == 200 and path:
                raise RuntimeError(f'A game started during game-list refresh: {path}')
            try:
                if code in (201, 404) and self.api.indexed(self.rom):
                    self.log('Game found in ES after automatic refresh')
                    return
            except (OSError, ValueError, RuntimeError):
                pass  # ES may be temporarily unavailable while reloading.
            self.sleep(.5)
        raise RuntimeError('Jeu toujours absent ou ES indisponible après actualisation automatique ; '
                           'vérifiez le jeu et la liste dans ES (game-list refresh timed out)')

    def log(self, message):
        print(f'[{time.strftime("%F %T")}] {message}', flush=True)

    def wait_for_slot(self):
        deadline = self.clock()+self.idle_timeout
        while self.clock() < deadline:
            self.require_active_session()
            code, path = self.api.running()
            if code in (201, 404):
                self.log('Toolbox port released; ES is idle')
                return 'launch'
            if code == 200 and path == self.rom:
                self.log('Requested game already active; attach without a second launch')
                return 'attach'
            if code == 200 and path and not self.is_toolbox(path):
                raise RuntimeError(f'Another game is running: {path}')
            self.sleep(.25)
        raise RuntimeError('Toolbox port was not released within the timeout')

    def wait_for_target(self):
        deadline = self.clock()+self.start_timeout
        while self.clock() < deadline:
            self.require_active_session()
            code, path = self.api.running()
            if code == 200 and path == self.rom:
                self.log(f'Confirmed requested game: {path}')
                return
            if code == 200 and path and path != self.rom and not self.is_toolbox(path):
                raise RuntimeError(f'A different game started: {path}')
            self.sleep(.25)
        raise RuntimeError('Requested game launch was not confirmed')

    def wait_for_stop(self):
        while True:
            self.require_active_session()
            code, path = self.api.running()
            if code in (201, 404) or (code == 200 and path and path != self.rom):
                return
            self.sleep(.5)

    def stop_mapping(self):
        hook = self.session.home/'toolbox/hooks/antimicrox-game-event.sh'
        # Only stop this ROM's mapping, never an intervening game's session.
        subprocess.run(['/bin/bash', str(hook), 'gameStop', 'windows', '', '', self.rom],
                       check=False, timeout=10)

    def resume(self):
        deadline = self.clock()+self.idle_timeout
        while self.clock() < deadline:
            code, path = self.api.running()
            if code in (201, 404):
                if not self.session.request_return(self.rom, self.session_id):
                    self.log('Return already presented, session changed, or another workflow owns recovery; no relaunch')
                    return
                # Import at handoff time: the shared return helper uses EsApi.
                from toolbox_return import resume
                try:
                    confirmed = resume(self.session.home, None, api=self.api,
                                       clock=self.clock, sleep=self.sleep,
                                       timeout=self.idle_timeout, refresh_timeout=self.refresh_timeout)
                except (OSError, ValueError, RuntimeError) as exc:
                    self.log(f'Automatic Toolbox return failed; request retained: {exc}')
                    return
                self.log('Confirmed return to AntiMicroX menu' if confirmed else
                         'Return unconfirmed; reopen the Toolbox to recover AntiMicroX')
                return
            if code == 200 and path:
                self.log('Another Ports/game session is active; defer recovery to next Toolbox opening')
                return
            self.sleep(.25)
        self.log('ES unavailable for automatic return; reopen the Toolbox to recover')

    def run(self):
        data = self.session.read()
        if not data or data['rom'] != self.rom or data['phase'] not in ('prepared', 'running'):
            raise RuntimeError('No matching live session to launch')
        result = 'launch_failed'
        try:
            if self.wait_for_slot() == 'launch':
                self.ensure_indexed()
                self.require_active_session()
                self.log(f'Requesting game after Ports exit: {self.rom}')
                self.api.launch(self.rom)
                self.wait_for_target()
            started = self.clock()
            self.wait_for_stop()
            result = 'short' if self.clock()-started < 30 else 'normal'
        except (OSError, RuntimeError, ValueError) as exc:
            self.log(f'ERROR: {exc}')
            if self.owns_session():
                self.session.mark(self.rom, error=str(exc))
        finally:
            if self.owns_session():
                try:
                    self.stop_mapping()
                except (OSError, subprocess.TimeoutExpired) as exc:
                    self.log(f'WARNING: mapping stop failed: {exc}')
                self.session.finish(result, self.rom)
        if self.owns_session():
            self.resume()
        return result


def spawn(home, rom):
    session = LiveSession(home)
    data = session.read()
    if not data or data['rom'] != rom or data['phase'] not in ('prepared', 'running'):
        raise ValueError('No matching prepared AntiMicroX session')
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR/'antimicrox-handoff.log').open('ab', buffering=0) as log:
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--home', str(home), 'run', rom],
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True, close_fds=True)
    print(f'AntiMicroX detached handoff started pid={process.pid}', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', default='/userdata/system/ultimate-wine-toolbox')
    parser.add_argument('command', choices=('spawn', 'run'))
    parser.add_argument('rom')
    args = parser.parse_args()
    if args.command == 'spawn':
        spawn(args.home, args.rom)
        return
    session = LiveSession(args.home)
    session.state.parent.mkdir(parents=True, exist_ok=True)
    with (session.state.parent/'antimicrox-handoff.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('An AntiMicroX handoff is already running')
        Handoff(session, args.rom).run()


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc))
