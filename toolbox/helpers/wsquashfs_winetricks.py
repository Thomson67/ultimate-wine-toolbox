#!/usr/bin/env python3
"""Install Winetricks in a working prefix through Batocera's runner setup."""
import argparse
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import tempfile

from winetricks_catalog import valid_verb, pending_components
from winetricks_games import configured_runner


def private_file(path, source=None):
    fd, temporary = tempfile.mkstemp(prefix='.uwt-winetricks-', dir=path.parent)
    os.close(fd)
    try:
        shutil.copy2(source or path, temporary)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def selected_runner_root(prefix):
    name = os.environ.get('UWT_COMPONENT_ROM_NAME', prefix.name)
    runner = configured_runner(Path(name), Path('/userdata/system/batocera.conf'))
    runner = {'__SYSTEM__': 'wine-tkg', 'lutris': 'wine-tkg', 'proton': 'wine-proton'}.get(runner, runner)
    if runner in ('wine-tkg', 'wine-proton'):
        return Path('/usr/wine') / runner
    if not runner or Path(runner).name != runner or runner in ('.', '..'):
        raise ValueError('Invalid selected runner name')
    return Path('/userdata/system/wine/custom') / runner


NVAPI_DLLS = {'nvapi.dll': 0x14c, 'nvapi64.dll': 0x8664, 'nvofapi64.dll': 0x8664}
DXVK_ROOTS = (Path('/userdata/system/wine/dxvk'), Path('/usr/wine/dxvk'))


def legacy_dxvk_link(path, prefix):
    """Recognize Batocera graphics links, including optional NVAPI DLLs."""
    relative = path.relative_to(prefix / 'drive_c/windows')
    dll = path.name.casefold()
    if len(relative.parts) != 2 or dll not in ('d3d8.dll', 'd3d9.dll', 'd3d10.dll', 'd3d10_1.dll', 'd3d10core.dll', 'd3d11.dll', 'd3d12.dll', 'd3d12core.dll', 'dxgi.dll', 'ddraw.dll', *NVAPI_DLLS):
        return None
    folder = relative.parts[0].casefold()
    if folder == 'syswow64':
        arch, dxvk, machine = 'i386-windows', 'x32', 0x14c
    elif folder == 'system32':
        try:
            win32 = '#arch=win32' in (prefix / 'system.reg').read_text(errors='replace').splitlines()
        except FileNotFoundError:
            win32 = False
        arch, dxvk, machine = ('i386-windows', 'x32', 0x14c) if win32 else ('x86_64-windows', 'x64', 0x8664)
    else:
        return None
    target = Path(os.readlink(path))
    if target not in (base / dxvk / path.name for base in DXVK_ROOTS):
        return None
    if dll in NVAPI_DLLS and machine != NVAPI_DLLS[dll]:
        return None
    return dll, arch, dxvk, machine


def legacy_dxvk_source(path, prefix, runner_root=None):
    """Find a same-architecture replacement for a recognized graphics link."""
    recognized = legacy_dxvk_link(path, prefix)
    if recognized is None:
        return None
    dll, arch, dxvk, machine = recognized
    runner = (runner_root or selected_runner_root(prefix)).resolve()
    candidates = [(runner / layout / arch / dll, runner)
                  for layout in ('lib/wine', 'files/lib/wine', 'dist/lib/wine')]
    if dll in NVAPI_DLLS:
        # NVAPI is an optional native component, usually outside Wine's DLL tree.
        for base in (runner, runner / 'files', runner / 'dist'):
            for lib in ('lib/wine', 'lib64/wine', 'lib32/wine', 'lib', 'lib64', 'lib32'):
                for component in ('nvapi', 'dxvk-nvapi'):
                    candidates.extend((directory / dll, runner) for directory in
                                      (base / lib / component / arch, base / lib / component))
        candidates.extend((base / dxvk / dll, base.resolve()) for base in DXVK_ROOTS)
    for candidate, allowed_root in candidates:
        resolved = candidate.resolve()
        if not resolved.is_relative_to(allowed_root) or not candidate.is_file():
            continue
        with candidate.open('rb') as stream:
            header = stream.read(64)
            if len(header) < 64 or header[:2] != b'MZ':
                continue
            offset = int.from_bytes(header[60:64], 'little')
            if offset < 64 or offset > candidate.stat().st_size - 6:
                continue
            stream.seek(offset)
            pe = stream.read(6)
        if pe[:4] == b'PE\0\0' and int.from_bytes(pe[4:6], 'little') == machine:
            return candidate
    return None


def prepare(prefix, detach=True, runner_root=None):
    if prefix.is_symlink() or not prefix.is_dir() or prefix.suffix.casefold() != '.wine':
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
    obsolete_nvapi = []
    for path in files:
        if path.is_symlink() and not path.resolve().is_relative_to(root):
            if not path.is_file():
                source = legacy_dxvk_source(path, prefix, runner_root)
                if source is None:
                    recognized = legacy_dxvk_link(path, prefix)
                    if recognized is not None and recognized[0] in NVAPI_DLLS:
                        # Batocera links optional NVAPI/Optical Flow DLLs even when
                        # the installed bundle lacks them. A broken link supplies
                        # no implementation; do not block unrelated installers.
                        obsolete_nvapi.append(path)
                        continue
                    raise ValueError(f'Missing shared Windows file: {path} -> {os.readlink(path)}')
                copies.append((path, source))
            else:
                copies.append((path, None))
        elif path.is_file() and path.stat().st_nlink > 1:
            copies.append((path, None))
    if detach:
        for path in obsolete_nvapi:
            target = os.readlink(path)
            path.unlink()
            print(f'winetricks_obsolete_nvapi_link_removed={path} target={target}', flush=True)
        for path, source in copies:
            private_file(path, source)
            if source is not None:
                print(f'winetricks_legacy_dxvk_repaired={path} source={source}', flush=True)


def installer_file_limit():
    """Raise this helper's inherited soft limit, never the system/hard limit."""
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    target = 65536 if hard == resource.RLIM_INFINITY else min(65536, hard)
    if soft != resource.RLIM_INFINITY and soft < target:
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
        except (OSError, ValueError) as error:
            print(f'dotnet_nofile_raise_failed={error}', flush=True)
    current, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    print(f'dotnet_nofile_soft={current} hard={hard} previous_soft={soft}', flush=True)


def install(prefix, verbs, launcher=Path('/usr/bin/batocera-wine'), wine_command=False, native_runner=False, unattended=True, mono_cleanup=False):
    if not verbs or (not wine_command and any(not valid_verb(v) for v in verbs)):
        raise ValueError('Use Winetricks component names, without options or shell commands')
    if not wine_command and not mono_cleanup:
        verbs = pending_components(prefix, verbs, os.environ.get('UWT_WINETRICKS_CATALOG'))
        if not verbs:
            print('winetricks_all_selected_components_already_installed=1', flush=True)
            return 0
    source = launcher.read_text()
    if os.environ.get('UWT_COMPONENT_ROM_NAME'):
        source, count = re.subn(r'^ROMGAMENAME=.*$',
                               'ROMGAMENAME="${UWT_COMPONENT_ROM_NAME}"', source,
                               count=1, flags=re.MULTILINE)
        if count != 1:
            raise ValueError('Unsupported Batocera game settings selection')
    if mono_cleanup:
        if wine_command or not native_runner or verbs != ['remove_mono', 'dotnet48']:
            raise ValueError('Mono cleanup is restricted to the Microsoft .NET workflow')
        invocation = '    WINEPREFIX=${WINEPOINT} ${CMD_PREFIX} "${WINETRICKS}" "${TRICK[@]}"'
        if source.count(invocation) != 1:
            raise ValueError('Unsupported Batocera Winetricks invocation for Mono cleanup')
        source = source.replace(invocation,
            '    python3 "$UWT_MONO_PATCHER" "$WINETRICKS" "$UWT_MONO_TRICKS" || return 1\n'
            '    WINEPREFIX=${WINEPOINT} ${CMD_PREFIX} "$UWT_MONO_TRICKS" "${TRICK[@]}"', 1)
    call = '            trick_wine "${l_PREFIX}" "$@"'
    if source.count(call) != 1:
        raise ValueError('This Batocera Winetricks launcher is not supported')
    # The stock CLI unsets l_PREFIX after Winetricks, losing its exit code.
    # Keep Batocera's setup and cleanup in a temporary copy and return the
    # actual installer result. Never change /usr/bin/batocera-wine.
    action = ('            WINEPOINT="${l_PREFIX}"\n'
              '            WINEPREFIX="${l_PREFIX}" ${CMD_PREFIX:-} "${WINE}" "$@"'
              if wine_command else call)
    # A .NET setup EXE is an installer, not an UMU game. Winetricks must use
    # one Wine engine/prefix for regedit, winecfg, setup EXEs and wineserver.
    # Windows DLL links have already been detached by prepare() below.
    native_setup = '''
            UWT_NATIVE_ROOT="$(dirname "$(dirname "$WINE")")"
            if [ -f "$UWT_NATIVE_ROOT/umu-batocera/umu-root-runner.py" ]; then
                if [ ! -x "$UWT_NATIVE_ROOT/files/bin/wine" ] || [ ! -x "$UWT_NATIVE_ROOT/files/bin/wineserver" ]; then
                    echo "UWT: selected UMU runner has no usable native Wine engine" >&2
                    exit 1
                fi
                export WINE="$UWT_NATIVE_ROOT/files/bin/wine"
                export WINESERVER="$UWT_NATIVE_ROOT/files/bin/wineserver"
                export WINE64="$WINE"
                [ ! -x "$UWT_NATIVE_ROOT/files/bin/wine64" ] || export WINE64="$UWT_NATIVE_ROOT/files/bin/wine64"
                export WINELOADER="$WINE"
                export PATH="$UWT_NATIVE_ROOT/files/bin:$PATH"
                echo "dotnet_runner_mode=native wine=$WINE wine64=$WINE64 wineserver=$WINESERVER"
            fi
''' if native_runner else ''
    source = source.replace(call,
        '            if [ -x "${DIR}/${WINE_VERSION}/bin/wine" ]; then\n'
        '                export WINE="${DIR}/${WINE_VERSION}/bin/wine"\n'
        '                export WINESERVER="${DIR}/${WINE_VERSION}/bin/wineserver"\n'
        '            fi\n' + native_setup + action + '\n'
        '            UWT_TRICKS_RC=$?\n'
        '            waitWineServer 0\n'
        '            cleanAndExit "$UWT_TRICKS_RC"\n'
        '            exit "$UWT_TRICKS_RC"', 1)
    prepare(prefix)
    if native_runner:
        installer_file_limit()
    with tempfile.TemporaryDirectory(prefix='uwt-winetricks-') as tmp:
        wrapper = Path(tmp) / 'batocera-wine'
        wrapper.write_text(source)
        env = dict(os.environ, WINE='wine', WINESERVER='wineserver')
        if mono_cleanup:
            env.update(UWT_MONO_PATCHER=str(Path(__file__).with_name('wsquashfs_mono_cleanup.py').resolve()),
                       UWT_MONO_TRICKS=str(Path(tmp) / 'winetricks'))
        if not unattended:
            env.pop('W_OPT_UNATTENDED', None)
        # Exported Wine variables retain their export flag when init_wine()
        # replaces them with the selected runner's executable paths.
        args = verbs if wine_command or not unattended else ['-q', *verbs]
        if not unattended and not wine_command:
            for gui in ('zenity', 'kdialog'):
                if shutil.which(gui):
                    args = [f'--gui={gui}', *args]
                    break
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
