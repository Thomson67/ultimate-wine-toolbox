#!/usr/bin/env python3
"""Opt-in Batocera 41 boot persistence, using Batocera's user service registry."""
import argparse
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import v41_savedir_patch as patch

SERVICE = 'uwt_v41_savedir'
SERVICE_MARKER = '# UWT_V41_SAVEDIR_SERVICE'
STATE = patch.HOME
SERVICE_PATH = Path('/userdata/system/services') / SERVICE
BOOT_LOG = Path('/userdata/system/logs/ultimate-wine-toolbox/v41-savedir-boot.log')


def service_text(state):
    script = str(state / 'v41_savedir_service.py')
    if any(c in script for c in '"$`\\\n\r'):
        raise ValueError('invalid persistent helper path')
    return ('#!/bin/bash\n' + SERVICE_MARKER + '\n'
            'case "$1" in\n'
            f'  start) exec /usr/bin/python3 "{script}" boot ;;\n'
            f'  status) exec /usr/bin/python3 "{script}" status ;;\n'
            '  stop) exit 0 ;;\n'
            '  *) exit 1 ;;\n'
            'esac\n')


def persistent(action, target, state, os_release, version_file, service_path, source_dir,
               services='/usr/bin/batocera-services', settings='/usr/bin/batocera-settings-get'):
    enabled = state / 'enabled'
    if action == 'status':
        patch.manage('status', target, state, os_release, source_dir / 'v41_savedir.py', version_file)
        print('boot-enabled' if enabled.is_file() else 'boot-disabled')
        return
    if action == 'boot':
        if not enabled.is_file() or not patch.version41(os_release, version_file):
            print('Batocera 41 save service: disabled or another major version; no changes')
            return
        patch.manage('install', target, state, os_release, source_dir / 'v41_savedir.py', version_file)
        print('Batocera 41 save service: patch active')
        return
    if service_path.is_symlink() or (service_path.exists() and
                                     SERVICE_MARKER not in service_path.read_text()):
        raise ValueError('another service already uses this name; no changes made')
    if action == 'disable':
        # First prevent reapplication on boot, even if restoring a changed script fails.
        subprocess.run([services, 'disable', SERVICE], check=True)
        selected = subprocess.check_output([settings, 'system.services'], text=True).split()
        if SERVICE in selected:
            raise ValueError('Batocera did not disable the user service')
        enabled.unlink(missing_ok=True)
        patch.manage('remove', target, state, os_release, source_dir / 'v41_savedir.py', version_file)
        service_path.unlink(missing_ok=True)
        print('Batocera 41 boot compatibility disabled; launcher restored when applicable')
        return
    if action == 'refresh' and not enabled.is_file():
        return
    if not patch.version41(os_release, version_file):
        raise ValueError('boot compatibility can only be enabled/refreshed on Batocera 41')
    selected_before = subprocess.check_output([settings, 'system.services'], text=True).split()
    had_patch = patch.MARKER.encode() in target.read_bytes()
    previous_service = service_path.read_bytes() if service_path.exists() else None
    patch.manage('install', target, state, os_release, source_dir / 'v41_savedir.py', version_file)
    for name in ('v41_savedir.py', 'v41_savedir_patch.py', 'v41_savedir_service.py'):
        patch.write_atomic(state / name, (source_dir / name).read_bytes(), 0o644)
    service_path.parent.mkdir(parents=True, exist_ok=True)
    patch.write_atomic(service_path, service_text(state).encode(), 0o755)
    try:
        subprocess.run([services, 'enable', SERVICE], check=True)
        selected = subprocess.check_output([settings, 'system.services'], text=True).split()
        if SERVICE not in selected:
            raise ValueError('Batocera did not enable the user service')
        patch.write_atomic(enabled, b'1\n', 0o600)
    except (OSError, ValueError, subprocess.SubprocessError):
        if SERVICE not in selected_before:
            subprocess.run([services, 'disable', SERVICE], check=False)
        if previous_service is None:
            service_path.unlink(missing_ok=True)
        else:
            patch.write_atomic(service_path, previous_service, 0o755)
        if not had_patch:
            patch.manage('remove', target, state, os_release, source_dir / 'v41_savedir.py', version_file)
        raise
    print('Batocera 41 save compatibility active now and enabled at boot')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('enable', 'disable', 'refresh', 'boot', 'status'))
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.exit(1, 'Batocera 41 boot service: root is required\n')
    STATE.mkdir(parents=True, exist_ok=True)
    log = None
    if args.action == 'boot':
        BOOT_LOG.parent.mkdir(parents=True, exist_ok=True)
        if BOOT_LOG.exists() and BOOT_LOG.stat().st_size > 1048576:
            BOOT_LOG.write_text('Previous boot log exceeded 1 MiB; rotated.\n')
        log = BOOT_LOG.open('a', buffering=1)
        sys.stdout = sys.stderr = log
    try:
        with (STATE / 'service.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            persistent(args.action, Path('/usr/bin/batocera-wine'), STATE,
                       Path('/etc/os-release'), patch.VERSION_FILE, SERVICE_PATH,
                       Path(__file__).parent)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'Batocera 41 boot service: {error}', file=sys.stderr)
        return 1
    finally:
        if log is not None:
            log.flush()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
