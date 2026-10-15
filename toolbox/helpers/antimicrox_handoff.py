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

from antimicrox_live import LiveSession, atomic

TOOLBOX = '/userdata/roms/ports/Ultimate Wine Toolbox.sh'
LOG_DIR = Path('/userdata/system/logs/ultimate-wine-toolbox')


class EsApi:
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
                 idle_timeout=30, start_timeout=300):
        self.session, self.rom = session, rom
        self.api = api or EsApi()
        self.clock, self.sleep = clock, sleep
        self.idle_timeout, self.start_timeout = idle_timeout, start_timeout
        self.session_id = (session.read() or {}).get('session_id')

    def owns_session(self):
        data = self.session.read()
        return bool(data and data['rom'] == self.rom and data.get('session_id') == self.session_id)

    def require_active_session(self):
        if not self.owns_session() or self.session.read()['phase'] not in ('prepared', 'running'):
            raise RuntimeError('Live session was recovered or cancelled elsewhere')

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
            if code == 200 and path and path != TOOLBOX:
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
            if code == 200 and path and path not in (TOOLBOX, self.rom):
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
                atomic(self.session.home/'state/resume-wsq.request', b'antimicrox\n')
                self.api.launch(TOOLBOX)
                self.log('Requested return to AntiMicroX menu')
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
