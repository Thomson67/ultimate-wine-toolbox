#!/usr/bin/env python3
"""Keep archive operations attached to the Toolbox session that started them."""
import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def process_identity(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return fields[19] if fields[0] not in ('Z', 'X') else None
    except (OSError, IndexError):
        return None


@contextmanager
def cancellation_signals():
    """Let Python transactions roll back and reap their detached readers."""
    signals = (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)
    previous = {sig: signal.getsignal(sig) for sig in signals}

    def interrupted(signum, frame):
        # A second terminal signal must not interrupt rollback/reaping.
        for sig in signals:
            signal.signal(sig, signal.SIG_IGN)
        raise InterruptedError(f'Toolbox operation interrupted by signal {signum}')

    try:
        for sig in signals:
            signal.signal(sig, interrupted)
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


@contextmanager
def defer_cancellation():
    """Finish a short publication/journal transaction before handling closure."""
    signals = (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)
    previous = {sig: signal.getsignal(sig) for sig in signals}
    pending = []

    def defer(signum, frame):
        pending.append(signum)

    try:
        for sig in signals:
            signal.signal(sig, defer)
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    if pending:
        raise InterruptedError('Toolbox closed during archive publication; transaction completed')


def stop_group(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def run(command, owner):
    identity = process_identity(owner)
    if identity is None:
        print('operation_interrupted=Toolbox session already closed', file=sys.stderr, flush=True)
        return 130
    cancelled = False

    def cancel(signum, frame):
        nonlocal cancelled
        cancelled = True

    signals = (signal.SIGHUP, signal.SIGINT, signal.SIGTERM)
    previous = {sig: signal.getsignal(sig) for sig in signals}
    process = None
    started = time.monotonic()
    print(f'operation_started={Path(command[0]).name} time={time.strftime("%Y-%m-%d %H:%M:%S")}',
          file=sys.stderr, flush=True)
    try:
        for sig in signals:
            signal.signal(sig, cancel)
        process = subprocess.Popen(command, start_new_session=True)
        while True:
            if cancelled or process_identity(owner) != identity:
                print('operation_interrupted=Toolbox session closed; stopping owned workers',
                      file=sys.stderr, flush=True)
                stop_group(process)
                return 130
            result = process.poll()
            if result is not None:
                return result if result >= 0 else 128 - result
            time.sleep(0.05)
    finally:
        if process is not None and process.poll() is None:
            stop_group(process)
        print(f'operation_elapsed_seconds={time.monotonic() - started:.2f}', file=sys.stderr, flush=True)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner', type=int, required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if args.owner <= 1 or not command:
        parser.error('A live session owner and a command are required')
    try:
        return run(command, args.owner)
    except OSError as error:
        print(f'Archive operation: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
