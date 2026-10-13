#!/usr/bin/env python3
"""Install Winetricks in a working prefix through Batocera's runner setup."""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def private_file(path):
    fd, temporary = tempfile.mkstemp(prefix='.uwt-winetricks-', dir=path.parent)
    os.close(fd)
    try:
        shutil.copy2(path, temporary)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def prepare(prefix, detach=True):
    if prefix.is_symlink() or not prefix.is_dir() or prefix.suffix != '.wine':
        raise ValueError('Expected the working .wine prefix')
    root = prefix.resolve()
    drive = prefix / 'drive_c'
    windows = drive / 'windows'
    if drive.is_symlink() or windows.is_symlink() or not windows.is_dir():
        raise ValueError('drive_c/windows must be an internal directory')
    # Do not install while this prefix is still used by a game or wineserver.
    for envfile in Path('/proc').glob('[0-9]*/environ'):
        try:
            fields = envfile.read_bytes().split(b'\0')
        except OSError:
            continue
        for field in fields:
            if field.startswith(b'WINEPREFIX='):
                running = Path(os.fsdecode(field.split(b'=', 1)[1])).resolve()
                if running == root or running.is_relative_to(root):
                    raise ValueError('The working prefix is still in use; close the game first')
    files = []
    for directory, dirs, names in os.walk(windows, followlinks=False):
        # Some TKG builds encode Windows links in .REPARSE_POINT trees.
        # Their ${WINEPREFIX} link is bookkeeping, not a shared DLL directory.
        # Preserve metadata opaquely: never traverse or dereference it.
        def reparse(path):
            if not path.is_symlink():
                return False
            target = os.readlink(path)
            return (target.startswith(f'.REPARSE_POINT/{path.name}/')
                    and not (path.parent / '.REPARSE_POINT').is_symlink()
                    and (path.parent / '.REPARSE_POINT').is_dir())
        for name in dirs:
            path = Path(directory) / name
            if path.is_symlink() and not reparse(path):
                raise ValueError(f'Windows directory alias must be detached first: {path}')
        dirs[:] = [name for name in dirs if name != '.REPARSE_POINT' and not reparse(Path(directory) / name)]
        files.extend(Path(directory) / name for name in names if not reparse(Path(directory) / name))
    files.extend(prefix / name for name in ('system.reg', 'user.reg', 'userdef.reg'))
    # Detach shared files atomically before an installer can overwrite them.
    # User profiles and save links are deliberately outside this traversal.
    copies = []
    for path in files:
        if path.is_symlink() and not path.resolve().is_relative_to(root):
            if not path.is_file():
                raise ValueError(f'Missing shared Windows file: {path}')
            copies.append(path)
        elif path.is_file() and path.stat().st_nlink > 1:
            copies.append(path)
    if detach:
        for path in copies:
            private_file(path)


def install(prefix, verbs, launcher=Path('/usr/bin/batocera-wine'), wine_command=False):
    if not verbs or (not wine_command and any(not re.fullmatch(r'[a-z][a-z0-9_]*', v) for v in verbs)):
        raise ValueError('Use Winetricks component names, without options or shell commands')
    source = launcher.read_text()
    call = '            trick_wine "${l_PREFIX}" "$@"'
    if source.count(call) != 1:
        raise ValueError('This Batocera Winetricks launcher is not supported')
    # The stock CLI unsets l_PREFIX after Winetricks, losing its exit code.
    # Keep Batocera's setup and cleanup in a temporary copy and return the
    # actual installer result. Never change /usr/bin/batocera-wine.
    action = ('            WINEPOINT="${l_PREFIX}"\n'
              '            WINEPREFIX="${l_PREFIX}" ${CMD_PREFIX:-} "${WINE}" "$@"'
              if wine_command else call)
    source = source.replace(call,
        '            if [ -x "${DIR}/${WINE_VERSION}/bin/wine" ]; then\n'
        '                export WINE="${DIR}/${WINE_VERSION}/bin/wine"\n'
        '                export WINESERVER="${DIR}/${WINE_VERSION}/bin/wineserver"\n'
        '            fi\n' + action + '\n'
        '            UWT_TRICKS_RC=$?\n'
        '            waitWineServer 0\n'
        '            cleanAndExit "$UWT_TRICKS_RC"\n'
        '            exit "$UWT_TRICKS_RC"', 1)
    prepare(prefix)
    with tempfile.TemporaryDirectory(prefix='uwt-winetricks-') as tmp:
        wrapper = Path(tmp) / 'batocera-wine'
        wrapper.write_text(source)
        env = dict(os.environ, WINE='wine', WINESERVER='wineserver')
        # Exported Wine variables retain their export flag when init_wine()
        # replaces them with the selected runner's executable paths.
        args = verbs if wine_command else ['-q', *verbs]
        return subprocess.run(['bash', str(wrapper), 'windows', 'tricks',
                               str(prefix), *args], env=env).returncode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('prefix', type=Path)
    parser.add_argument('verbs', nargs='+')
    args = parser.parse_args()
    try:
        return install(args.prefix, args.verbs)
    except (OSError, ValueError) as error:
        print(f'Winetricks: {error}', flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
