#!/usr/bin/env python3
"""Place a new archive on a writable mergerfs branch with enough free space.

Only per-file placement is changed: pool configuration and policies stay intact.
The logical temporary path remains adjacent to its destination for publication.
"""
import argparse
import errno
import os
from pathlib import Path
import stat
import sys

from mergerfs_move import is_mergerfs_mount, relative_and_mount

MARGIN = 64 * 1024 * 1024


def pool_for(parent):
    # Inspect mountinfo first: unsupported xattrs on ordinary disks are normal,
    # but missing/invalid metadata on a verified pool must not silently bypass us.
    for candidate in (parent, *parent.parents):
        if is_mergerfs_mount(candidate):
            if parent == candidate:
                return candidate, Path('.')
            relative, mount = relative_and_mount(parent)
            if mount != candidate:
                raise ValueError('mergerfs path does not match the verified mount')
            return mount, relative
    return None


def source_bound(source):
    """Conservative uncompressed payload + metadata/compression overhead allowance."""
    total = 0
    def failed(error):
        raise error
    for directory, dirs, files in os.walk(source, followlinks=False, onerror=failed):
        for name in files:
            item = (Path(directory) / name).lstat()
            if stat.S_ISREG(item.st_mode):
                total += item.st_size
    return total + total // 20 + MARGIN


def branches(mount):
    raw = os.fsdecode(os.getxattr(mount / '.mergerfs', 'user.mergerfs.branches')).rstrip('\0')
    try:
        reserve = int(os.getxattr(mount / '.mergerfs', 'user.mergerfs.minfreespace').rstrip(b'\0'))
    except OSError:
        reserve = 0  # Older mergerfs versions may not expose this optional key.
    seen = set()
    for entry in raw.split(':'):
        path, separator, options = entry.rpartition('=')
        if not separator:
            path, options = entry, 'RW'
        values = options.split(',')
        if not path.startswith('/') or values[0] not in ('RW', 'RO', 'NC'):
            raise ValueError('Unrecognized mergerfs branch configuration')
        branch = Path(path)
        if branch in seen or branch.resolve() != branch:
            raise ValueError('Duplicated or redirected mergerfs branch')
        seen.add(branch)
        minimum = int(values[1]) if len(values) == 2 else reserve
        if len(values) > 2 or minimum < 0:
            raise ValueError('Invalid mergerfs free-space reservation')
        yield branch, values[0], minimum


def prepare(source, output, replace_existing=False):
    source, output = Path(source).absolute(), Path(output).absolute()
    if (not source.is_dir() or source.is_symlink() or output.is_symlink()
            or (output.exists() and (not replace_existing or not output.is_file()))):
        raise ValueError('Expected a source directory and an unused temporary archive path')
    pool = pool_for(output.parent)
    if pool is None:
        return  # Ordinary disks keep the existing compression path and behavior.
    mount, relative = pool
    # Existing output is accepted only for an owned component-workspace retry.
    # It is discarded after a viable placement has been found, never beforehand.
    retained = None
    if output.exists():
        existing = os.getxattr(output, 'user.mergerfs.allpaths').split(b'\0')
        configured = {branch for branch, mode, reserve in branches(mount) if mode == 'RW'}
        paths = [Path(os.fsdecode(item)) for item in existing if item]
        if (len(paths) != 1 or not any(paths[0] == branch / relative / output.name for branch in configured)
                or paths[0].resolve() != paths[0] or not paths[0].is_file()):
            raise ValueError('Invalid existing physical temporary archive')
        retained = paths[0]
    required = source_bound(source)
    print(f'archive_storage_required_bytes={required} estimate=uncompressed_plus_5_percent_plus_64MiB', flush=True)
    choices = []
    for branch, mode, reserve in branches(mount):
        try:
            info = os.statvfs(branch)
            available = info.f_bavail * info.f_frsize
            reclaim = retained.stat().st_blocks * 512 if retained and retained.parent == branch / relative else 0
            physical_parent = branch / relative
            ancestor = physical_parent
            while not ancestor.exists() and ancestor != branch:
                if ancestor.is_symlink():
                    raise ValueError('Redirected physical archive directory')
                ancestor = ancestor.parent
            safe = (branch.is_dir() and branch.resolve() == branch
                    and ancestor.resolve() == ancestor and ancestor.is_dir()
                    and physical_parent.resolve() == physical_parent)
            writable = (mode == 'RW' and not info.f_flag & os.ST_RDONLY
                        and safe and os.access(ancestor, os.W_OK | os.X_OK))
            print(f'archive_storage_branch={branch} mode={mode} available_bytes={available} '
                  f'reserve_bytes={reserve} reclaimable_bytes={reclaim} eligible={int(writable)}', flush=True)
            if writable and available + reclaim >= required + reserve:
                choices.append((available + reclaim - reserve, physical_parent))
        except OSError as error:
            print(f'archive_storage_branch={branch} unavailable={error}', flush=True)
    if not choices:
        raise OSError(errno.ENOSPC, f'No writable mergerfs disk has enough space for the archive '
                      f'(conservative estimate: {required / 2**30:.2f} GiB on one disk; see per-disk capacities above)')
    _, parent = max(choices, key=lambda item: item[0])
    # Do not create branch roots: an unavailable drive must never become a
    # directory on its parent filesystem. Only the relative game directory.
    parent.mkdir(parents=True, exist_ok=True, mode=stat.S_IMODE(output.parent.stat().st_mode))
    physical = parent / output.name
    if output.exists():
        output.unlink()
    fd = os.open(physical, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    os.close(fd)
    try:
        visible = [Path(os.fsdecode(item)) for item in os.getxattr(output, 'user.mergerfs.allpaths').split(b'\0') if item]
        if visible != [physical] or output.is_symlink() or not output.is_file():
            raise ValueError('The selected physical archive is not uniquely visible through mergerfs')
    except BaseException:
        physical.unlink(missing_ok=True)
        raise
    print(f'archive_storage_selected={parent} physical_output={physical}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        prepare(args.source, args.output)
    except (OSError, ValueError) as error:
        print(f'Archive storage failed: {error}', file=sys.stderr)
        raise SystemExit(1)
