"""Activate only the returning Toolbox terminal, during a bounded startup window."""
import argparse
from pathlib import Path
import time

from antimicrox_focus import XWindows, process_start


def is_es(pid):
    try:
        return Path(f'/proc/{pid}/comm').read_text().strip().startswith('emulationstat')
    except OSError:
        return False


def activate_return(pid, owner, windows, identity=process_start, es=is_es,
                    clock=time.monotonic, sleep=time.sleep, timeout=8, log=print):
    stamp, owner_stamp = identity(pid), identity(owner)
    if not stamp or not owner_stamp:
        return False
    deadline = clock() + timeout
    stable_since = None
    attempts = 0
    next_attempt = 0
    while clock() < deadline:
        if identity(pid) != stamp or identity(owner) != owner_stamp:
            log('Toolbox focus: session ended; stopping')
            return False
        target = windows.editor_window(pid)
        active = windows.cardinal(windows.root, '_NET_ACTIVE_WINDOW')
        if target and active == target:
            if stable_since is None:
                stable_since = clock()
            if clock() - stable_since >= .75:
                log(f'Toolbox focus: confirmed window={target} attempts={attempts}')
                return True
        else:
            stable_since = None
            active_pid = windows.cardinal(active, '_NET_WM_PID') if active else 0
            if active and active_pid and not es(active_pid):
                log('Toolbox focus: another application is active; stopping')
                return False
            if target and clock() >= next_attempt and attempts < 3:
                # Recheck identity immediately before requesting activation.
                if identity(pid) != stamp or identity(owner) != owner_stamp:
                    return False
                windows.activate(target)
                attempts += 1
                next_attempt = clock() + 1
                log(f'Toolbox focus: activation requested window={target} attempt={attempts}')
        sleep(.1)
    log('Toolbox focus: startup activation unconfirmed; stopping')
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--owner', type=int, required=True)
    args = parser.parse_args()
    activate_return(args.pid, args.owner, XWindows(),
                    log=lambda text: print(text, flush=True))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'Toolbox focus: unavailable: {exc}', flush=True)
