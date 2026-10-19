"""Rename game directories within each mergerfs branch without copying data."""
import os
from pathlib import Path
import re


class MoveRecoveryRequired(RuntimeError):
    """Some physical moves could not be rolled back; retain the old game backup."""


def is_mergerfs_mount(mount):
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        fields, filesystem = line.split(' - ', 1)
        path = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), fields.split()[4])
        if Path(path) == mount and filesystem.split()[0] == 'fuse.mergerfs':
            return True
    return False


def relative_and_mount(path):
    raw = os.fsdecode(os.getxattr(path, 'user.mergerfs.relpath')).rstrip('\0')
    relative = Path(raw.lstrip('/'))
    if not relative.parts or '..' in relative.parts:
        raise ValueError('invalid mergerfs relative path')
    mount = path
    for _ in relative.parts:
        mount = mount.parent
    if mount / relative != path:
        raise ValueError('mergerfs relative path does not match the logical path')
    return relative, mount


def move_plan(source, destination):
    source_rel, mount = relative_and_mount(source)
    parent_rel, target_mount = relative_and_mount(destination.parent)
    if mount != target_mount or not is_mergerfs_mount(mount):
        raise ValueError('physical rename requires the same verified mergerfs pool')
    raw_branches = os.fsdecode(os.getxattr(mount / '.mergerfs', 'user.mergerfs.branches'))
    branches = {}
    for entry in raw_branches.rstrip('\0').split(':'):
        path, separator, mode = entry.rpartition('=')
        if not separator or mode not in ('RW', 'RO', 'NC'):
            path, mode = entry, 'RW'
        branches[Path(path).resolve()] = mode
    raw = os.getxattr(source, 'user.mergerfs.allpaths')
    sources = [Path(os.fsdecode(path)) for path in raw.split(b'\0') if path]
    if not sources or len(set(sources)) != len(sources):
        raise ValueError('missing or duplicated physical source paths')
    plan = []
    for physical in sources:
        branch = physical
        for _ in source_rel.parts:
            branch = branch.parent
        branch = branch.resolve()
        if branch not in branches or branches[branch] != 'RW':
            raise ValueError('source is not in a writable branch of this mergerfs pool')
        expected = branch / source_rel
        target = branch / parent_rel / destination.name
        if (physical != expected or not physical.is_dir() or physical.is_symlink()
                or physical.resolve() != expected or target.parent.resolve() != target.parent):
            raise ValueError('physical rename path contains an unexpected redirect')
        if target.exists() or target.is_symlink():
            raise ValueError(f'physical destination already exists: {target}')
        if target.is_relative_to(physical) or physical.is_relative_to(target):
            raise ValueError('physical rename paths overlap')
        plan.append((physical, target))
    if len({target for _, target in plan}) != len(plan):
        raise ValueError('duplicated physical destinations')
    return plan


def rename_in_branches(source, destination, record=lambda plan: None):
    """Preflight every branch; journal moves and roll back on ordinary failures."""
    plan = move_plan(source, destination)
    journal = [{'source': str(src), 'destination': str(dst), 'moved': False}
               for src, dst in plan]
    record(journal)
    moved, created = [], []
    try:
        for index, (src, dst) in enumerate(plan):
            missing = []
            parent = dst.parent
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for parent in reversed(missing):
                parent.mkdir()
                created.append(parent)
            print(f'mergerfs physical rename: {src} -> {dst}', flush=True)
            src.rename(dst)
            moved.append((index, src, dst))
            journal[index]['moved'] = True
            record(journal)
    except Exception as exc:
        failures = []
        for index, src, dst in reversed(moved):
            try:
                dst.rename(src)
                journal[index]['moved'] = False
            except OSError as rollback:
                failures.append(f'{dst} -> {src}: {rollback}')
        for parent in reversed(created):
            try:
                parent.rmdir()  # Only remove empty directories we created.
            except OSError:
                pass
        try:
            record(journal)
        except Exception:
            pass
        if failures:
            raise MoveRecoveryRequired('physical rollback incomplete; retain .bak and journal: '
                                       + '; '.join(failures)) from exc
        raise
