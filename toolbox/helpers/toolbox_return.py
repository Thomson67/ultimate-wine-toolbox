"""Return through ES after the old Ports launcher has released its session."""
import argparse
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import time

from antimicrox_handoff import EsApi, TOOLBOX, LOG_DIR

HOME = Path('/userdata/system/ultimate-wine-toolbox')


def parent_alive(pid):
    try:
        # A zombie has finished; waiting for its reaper could block the handoff.
        stat = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return stat[0] != 'Z'
    except (OSError, IndexError):
        return False


def resume(home, parent_pid, api=None, clock=time.monotonic, sleep=time.sleep,
           alive=parent_alive, timeout=30, refresh_timeout=60, confirm_timeout=10):
    api = api or EsApi()
    request = Path(home) / 'state/resume-wsq.request'

    def log(message):
        print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] Toolbox return: {message}', flush=True)

    deadline = clock() + timeout
    while alive(parent_pid):
        if clock() >= deadline:
            log('old Ports launcher still active; request retained')
            return False
        sleep(.25)
    log('old Ports launcher released')
    deadline = clock() + timeout
    idle = 0
    while idle < 3:
        if not request.exists():
            return True  # Manually reopened during recovery.
        code, _ = api.running()
        idle = idle + 1 if code == 201 else 0
        if clock() >= deadline:
            log('ES not idle; request retained')
            return False
        sleep(.25)

    if not api.indexed(TOOLBOX):
        log('Toolbox missing from ES index; refreshing game list once')
        api.reload_games()
        deadline = clock() + refresh_timeout
        while not api.indexed(TOOLBOX):
            if not request.exists():
                return True
            code, _ = api.running()
            if code != 201 or clock() >= deadline:
                log('Toolbox indexing unconfirmed or ES busy; request retained')
                return False
            sleep(.25)
        sleep(.5)

    for attempt in range(1, 4):
        if not request.exists():
            return True
        code, _ = api.running()
        if code != 201:
            log('ES busy/unavailable before launch; request retained')
            return False
        log(f'launching through ES, attempt={attempt}')
        try:
            api.launch(TOOLBOX)
        except (OSError, RuntimeError) as exc:
            log(f'launch request failed: {exc}')
        deadline = clock() + confirm_timeout
        while clock() < deadline:
            if not request.exists():
                log('new Ports launcher consumed resume request; confirmed')
                return True
            sleep(.25)
    log('return unconfirmed; reopen Toolbox from Ports; no direct terminal fallback')
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('spawn', 'run'))
    parser.add_argument('--parent-pid', type=int, required=True)
    parser.add_argument('--home', type=Path, default=HOME)
    args = parser.parse_args()
    if args.command == 'spawn':
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with (LOG_DIR / 'port-launch.log').open('ab', buffering=0) as log:
            process = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), 'run',
                 '--parent-pid', str(args.parent_pid), '--home', str(args.home)],
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True, close_fds=True)
        print(f'Toolbox return detached pid={process.pid}', flush=True)
        return
    state = args.home / 'state'
    state.mkdir(parents=True, exist_ok=True)
    with (state / 'toolbox-return.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Toolbox return already running')
        if not resume(args.home, args.parent_pid):
            raise SystemExit(1)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(f'Toolbox return failed; request retained: {exc}')
