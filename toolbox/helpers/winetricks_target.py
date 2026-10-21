#!/usr/bin/env python3
"""Edit game components in Batocera's persistent prefix, without running a game."""
import argparse
from contextlib import contextmanager
import ctypes
import errno
import fcntl
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from winetricks_games import valid_game
from reshade_diagnostic import prefix_matches, targets
from reshade_manager import runner_for
import wsquashfs_winetricks as tricks


def enter_private_namespace():
    """Keep component mounts private without requiring the unshare executable."""
    libc = ctypes.CDLL(None, use_errno=True)
    libc.unshare.argtypes = [ctypes.c_int]
    libc.unshare.restype = ctypes.c_int
    if libc.unshare(0x00020000) != 0:  # CLONE_NEWNS
        error = ctypes.get_errno()
        raise OSError(error, 'Cannot create a private mount namespace: ' + os.strerror(error))
    libc.mount.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
                           ctypes.c_ulong, ctypes.c_void_p]
    libc.mount.restype = ctypes.c_int
    if libc.mount(None, b'/', None, 0x4000 | 0x40000, None) != 0:  # MS_REC | MS_PRIVATE
        error = ctypes.get_errno()
        raise OSError(error, 'Cannot make mount propagation private: ' + os.strerror(error))


def bottle_for(rom, runner, launcher, bottles):
    selected = runner_for(rom, '' if runner == '__SYSTEM__' else runner)
    if 'WINE_BOTTLE_DIR}/${WINE_VERSION}/${ROMGAMENAME}.wine' in launcher.read_text():
        return bottles / selected / (rom.name + '.wine')
    return bottles / rom.name


def ensure_idle(rom, bottle, proc=Path('/proc')):
    candidates = [bottle, *targets(rom)]
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            fields = dict(field.split(b'=', 1) for field in (entry / 'environ').read_bytes().split(b'\0') if b'=' in field)
            prefix = os.fsdecode(fields.get(b'WINEPREFIX', b''))
            compat = os.fsdecode(fields.get(b'STEAM_COMPAT_DATA_PATH', b''))
            if prefix_matches(prefix, candidates) or (compat and prefix_matches(str(Path(compat) / 'pfx'), candidates)):
                raise ValueError('Game/prefix is active; close the game and its Wine processes first')
            # Never mount the same upper directory twice, including an ES/UMU
            # overlay left in another mount namespace after an interrupted run.
            info = (entry / 'mountinfo').read_text()
            for upper in re.findall(r'(?:^|[, ])upperdir=([^,\n ]+)', info):
                upper = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), upper)
                if Path(upper).resolve() == bottle.resolve():
                    raise ValueError('Game overlay is already mounted; close the game before installing components')
        except OSError as error:
            if error.errno not in (errno.ENOENT, errno.ESRCH):
                raise ValueError(f'Cannot establish whether the game is idle: {entry}') from error


def checked(args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise ValueError(f'{args[0]} failed: {result.stderr.strip() or result.stdout.strip()}')


@contextmanager
def mounted_prefix(rom, bottle, runtime):
    """Called only inside a private mount namespace; never unmount ES mounts."""
    if any(c in str(bottle) + str(runtime) for c in ',:\\'):
        raise ValueError('Overlay paths containing commas, colons or backslashes are unsupported')
    runtime.mkdir(parents=True, exist_ok=True)
    if runtime.is_symlink():
        raise ValueError('Component runtime must not be a symbolic link')
    prefix = runtime / 'prefix.wine'
    lower = runtime / 'lower'
    for path in (prefix, lower):
        if path.is_symlink():
            raise ValueError('Component mount point must not be a symbolic link')
        path.mkdir(exist_ok=True)
    work = None
    mounts = []
    try:
        if rom.suffix.casefold() == '.wsquashfs':
            bottle.mkdir(parents=True, exist_ok=True)
            work = Path(tempfile.mkdtemp(prefix='.uwt-components-work-', dir=bottle.parent))
            checked(['mount', '-o', 'loop,ro,nosuid,nodev', str(rom), str(lower)])
            mounts.append(lower)
            checked(['mount', '-t', 'overlay', '-o',
                     f'rw,lowerdir={lower},upperdir={bottle},workdir={work},redirect_dir=on',
                     'overlay', str(prefix)])
        else:
            if not (bottle / 'system.reg').is_file() or not (bottle / 'drive_c/windows').is_dir():
                raise ValueError('Launch this .pc game once with the selected runner before installing components')
            checked(['mount', '--bind', str(bottle), str(prefix)])
        mounts.append(prefix)
        yield prefix
    finally:
        # No lazy/forced unmount and no recursive deletion of a mount point.
        # A failed unmount keeps the work directory for diagnosis/recovery.
        released = True
        for path in reversed(mounts):
            try:
                checked(['umount', str(path)])
            except ValueError as error:
                released = False
                print(f'Components: {error}; retained work directory: {work}', file=sys.stderr)
        if work is not None and released:
            shutil.rmtree(work)


def invoke(prefix, mode, arguments, rom, launcher, settings_rom_name=''):
    # Preserve the original ROM's per-game settings through staging and bind
    # mounts. Settings still come from Batocera; no system launcher is edited.
    previous = {key: os.environ.get(key) for key in (
        'UWT_COMPONENT_ROM_NAME', 'UWT_COMPONENT_PC_BOTTLE', 'UWT_COMPONENT_MOUNTED_PREFIX')}
    os.environ['UWT_COMPONENT_ROM_NAME'] = settings_rom_name or rom.name
    if rom.suffix.casefold() == '.pc':
        os.environ['UWT_COMPONENT_PC_BOTTLE'] = '1'
    else:
        os.environ.pop('UWT_COMPONENT_PC_BOTTLE', None)
    if rom.suffix.casefold() != '.wine':
        os.environ['UWT_COMPONENT_MOUNTED_PREFIX'] = str(prefix)
    else:
        os.environ.pop('UWT_COMPONENT_MOUNTED_PREFIX', None)
    try:
        if mode == 'tricks':
            return tricks.install(prefix, arguments, launcher=launcher, native_runner=True)
        if not arguments:
            raise ValueError('A .NET action is required')
        return subprocess.run([sys.executable, str(Path(__file__).with_name('wsquashfs_dotnet.py')),
                               arguments[0], str(prefix), *arguments[1:]]).returncode
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--runner', default='__SYSTEM__')
    parser.add_argument('--settings-rom-name', default='')
    parser.add_argument('rom', type=Path)
    parser.add_argument('mode', choices=('tricks', 'dotnet'))
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        if not valid_game(args.rom):
            raise ValueError('Select a .wine, .pc or .wsquashfs game')
        rom = args.rom.absolute()
        launcher = Path('/usr/bin/batocera-wine')
        bottle = rom if rom.suffix.casefold() == '.wine' else bottle_for(
            rom, args.runner, launcher, Path('/userdata/system/wine-bottles/windows'))
        if bottle.is_symlink() or bottle.parent.is_symlink():
            raise ValueError('The persistent bottle must not be a symbolic link')
        if rom.suffix.casefold() != '.wine':
            # Mounts are isolated from EmulationStation and cleaned up by the
            # kernel even if this helper is killed. The upper bottle persists.
            enter_private_namespace()
        ident = hashlib.sha256(os.fsencode(str(rom))).hexdigest()[:24]
        lockdir = args.home / 'state/component-locks'
        lockdir.mkdir(parents=True, exist_ok=True)
        with (lockdir / (ident + '.lock')).open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('Another component operation is already using this game')
            ensure_idle(rom, bottle)
            if rom.suffix.casefold() == '.wine':
                return invoke(rom, args.mode, args.arguments, rom, launcher, args.settings_rom_name)
            bottle_id = hashlib.sha256(os.fsencode(str(bottle))).hexdigest()[:24]
            with mounted_prefix(rom, bottle, args.home / 'runtime/component-mounts' / bottle_id) as prefix:
                return invoke(prefix, args.mode, args.arguments, rom, launcher)
    except (OSError, ValueError) as error:
        print(f'Components: {error}', flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
