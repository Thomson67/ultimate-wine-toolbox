"""Local installer staging and reversible publication, excluding game data."""
import ctypes
import errno
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def filesystem(path):
    try:
        result = subprocess.run(['findmnt', '-n', '-o', 'FSTYPE', '-T', str(path)],
                                capture_output=True, text=True, check=False)
        return result.stdout.strip() or 'unknown'
    except OSError:
        return 'unknown'


def exchange_probe(parent):
    """Exercise the file/directory exchange used by TKG reparse creation."""
    with tempfile.TemporaryDirectory(prefix='.uwt-dotnet-probe-', dir=parent) as folder:
        file = Path(folder) / 'file'
        directory = Path(folder) / 'directory'
        file.touch()
        directory.mkdir()
        libc = ctypes.CDLL(None, use_errno=True)
        try:
            call = libc.renameat2
        except AttributeError:
            return errno.ENOSYS
        call.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        call.restype = ctypes.c_int
        rc = call(-100, os.fsencode(file), -100, os.fsencode(directory), 2)
        return ctypes.get_errno() if rc else 0


def relocate_links(root, old, new):
    """Move Linux prefix links, including TKG's literal ${WINEPREFIX} anchors."""
    old = old.resolve()
    new = new.resolve()
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            link = Path(directory) / name
            if not link.is_symlink():
                continue
            target = Path(os.readlink(link))
            replacement = None
            if name == '${WINEPREFIX}' and '.REPARSE_POINT' in link.relative_to(root).parts:
                replacement = str(new)
            elif target.is_absolute() and target.is_relative_to(old):
                replacement = str(new / target.relative_to(old))
            if replacement is not None:
                link.unlink()
                link.symlink_to(replacement)


def stage(prefix, game, work_root):
    work_root.mkdir(parents=True, exist_ok=True)
    if work_root.resolve().is_relative_to(prefix.resolve()):
        raise ValueError('Local installer staging must be outside the prefix')
    kind = filesystem(work_root)
    probe = exchange_probe(work_root)
    print(f'dotnet_local_filesystem={kind} exchange_errno={probe}', flush=True)
    if kind.startswith('fuse') or probe:
        raise ValueError('Installer staging needs a local filesystem supporting rename exchange; '
                         'set UWT_DOTNET_WORK_ROOT to an ext4/Btrfs directory')
    container = Path(tempfile.mkdtemp(prefix='install-', dir=work_root))
    target = container / prefix.name  # Preserve per-game Batocera runner selection.
    try:
        shutil.copytree(prefix, target, symlinks=True,
                        ignore=lambda folder, names: [game.name] if Path(folder) == game.parent else [])
        relocate_links(target, prefix, target)
    except BaseException:
        shutil.rmtree(container)
        raise
    print(f'dotnet_staged_prefix={target}', flush=True)
    return target


def publish(source, prefix, game):
    """Prepare every copy before replacing entries; rollback on promotion errors."""
    # A bind/OverlayFS prefix is a separate filesystem from its parent. Keep
    # the reversible rename transaction inside that mount to avoid EXDEV.
    mounted = os.environ.get('UWT_COMPONENT_MOUNTED_PREFIX') == str(prefix)
    transaction = Path(tempfile.mkdtemp(prefix='.uwt-dotnet-commit-', dir=prefix if mounted else prefix.parent))
    incoming = transaction / 'incoming'
    previous = transaction / 'previous'
    operations = []
    rolled_back = True
    try:
        shutil.copytree(source, incoming, symlinks=True)
        relocate_links(incoming, source, prefix)
        previous.mkdir()
        paths = {Path(p.name) for p in prefix.iterdir() if p.name != 'drive_c' and p != transaction}
        paths.update(Path(p.name) for p in incoming.iterdir() if p.name != 'drive_c')
        paths.update(Path('drive_c') / p.name for p in (prefix / 'drive_c').iterdir() if p != game)
        paths.update(Path('drive_c') / p.name for p in (incoming / 'drive_c').iterdir())
        if game.relative_to(prefix) in paths:
            raise ValueError('Staged installation unexpectedly contains game data')
        for relative in sorted(paths):
            destination = prefix / relative
            fresh = incoming / relative
            old = previous / relative
            old.parent.mkdir(parents=True, exist_ok=True)
            operation = [destination, fresh, old, False, False]
            operations.append(operation)
            if destination.exists() or destination.is_symlink():
                os.replace(destination, old)
                operation[3] = True
            if fresh.exists() or fresh.is_symlink():
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(fresh, destination)
                operation[4] = True
    except BaseException as error:
        for destination, fresh, old, old_moved, fresh_moved in reversed(operations):
            try:
                if fresh_moved:
                    fresh.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(destination, fresh)
                if old_moved:
                    os.replace(old, destination)
            except OSError:
                rolled_back = False
        if not rolled_back:
            raise ValueError(f'Publication interrupted; recovery files retained in {transaction}') from error
        raise
    finally:
        if rolled_back:
            shutil.rmtree(transaction)
