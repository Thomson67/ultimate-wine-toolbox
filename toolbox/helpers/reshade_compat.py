#!/usr/bin/env python3
"""Private adapters for the pinned ReShadeLinux calls on minimal Batocera.

The git adapter downloads GitHub source snapshots; it is not a Git client.
It only supports the clone/update operations used by this backend and protects
local edits before replacing a cached snapshot.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import quote


def describe(path):
    with Path(path).open('rb') as stream:
        data = stream.read(1024 * 1024)
    if data[:2] != b'MZ' or len(data) < 64:
        raise ValueError('not a Windows executable')
    offset = struct.unpack_from('<I', data, 0x3c)[0]
    if offset + 6 > len(data) or data[offset:offset + 4] != b'PE\0\0':
        raise ValueError('invalid Windows PE header')
    machine = struct.unpack_from('<H', data, offset + 4)[0]
    arch = {0x14c: 'PE32 executable Intel 80386', 0x8664: 'PE32+ executable x86-64'}.get(machine)
    if not arch:
        raise ValueError('unsupported Windows architecture')
    return f'{path}: {arch}, for MS Windows'


def tree_hashes(root):
    result = {}
    for p in root.rglob('*'):
        rel = p.relative_to(root)
        if '.git' in rel.parts:
            continue
        if p.is_symlink():
            raise ValueError('local shader symlink; snapshot update refused')
        if p.is_file():
            result[rel.as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return result


def snapshot(url, branch, destination, update=False):
    match = re.fullmatch(r'https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?', url)
    if not match or not branch or branch.startswith('-'):
        raise ValueError('unsupported shader source')
    destination = Path(destination)
    if destination.is_symlink():
        raise ValueError('shader cache must be a real directory')
    metadata = destination / '.git/uwt-archive.json'
    if update:
        old = json.loads(metadata.read_text())
        if tree_hashes(destination) != old['files']:
            raise ValueError('local shader edits; snapshot update refused')
    elif destination.exists():
        raise ValueError('shader destination already exists')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.uwt-shaders-', dir=destination.parent) as folder:
        work = Path(folder)
        archive = work / 'source.tar.gz'
        source = work / 'source'
        source.mkdir()
        endpoint = f'https://codeload.github.com/{match[1]}/{match[2]}/tar.gz/{quote(branch, safe="/")}'
        subprocess.run(['curl', '-fsSL', '--retry', '3', '--connect-timeout', '15', '--max-time', '300',
                        endpoint, '-o', str(archive)], check=True)
        unpack(archive, source)
        record = dict(url=url, branch=branch, files=tree_hashes(source))
        (source / '.git').mkdir()
        (source / '.git/uwt-archive.json').write_text(json.dumps(record))
        if update:
            destination.rename(work / 'previous')
            try:
                source.rename(destination)
            except Exception:
                (work / 'previous').rename(destination)
                raise
        else:
            source.rename(destination)


def unpack(archive, source):
    total = 0
    with tarfile.open(archive, 'r:gz') as tar:
        root = None
        for member in tar:
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or not path.parts:
                raise ValueError('unsafe shader archive path')
            root = root or path.parts[0]
            if path.parts[0] != root:
                raise ValueError('multiple shader archive roots')
            rel = PurePosixPath(*path.parts[1:])
            if not path.parts[1:]:
                if member.isdir():
                    continue
                raise ValueError('invalid shader archive root')
            if '.git' in rel.parts or not (member.isfile() or member.isdir()):
                raise ValueError('unsupported shader archive entry')
            target = source / rel
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            total += member.size
            if member.size > 128 * 1024 * 1024 or total > 1024 * 1024 * 1024:
                raise ValueError('shader archive exceeds extraction limit')
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as incoming, target.open('wb') as outgoing:
                shutil.copyfileobj(incoming, outgoing)


def git_call(args):
    args = list(args)
    directory = Path.cwd()
    while args and args[0] in ('-c', '-C'):
        flag, value = args[:2]
        args = args[2:]
        if flag == '-C':
            directory = Path(value)
    if not args:
        raise ValueError('missing snapshot operation')
    operation, args = args[0], args[1:]
    if operation == 'clone':
        branch = 'HEAD'
        while args and args[0].startswith('--'):
            flag = args.pop(0)
            if flag == '--depth':
                if args.pop(0) != '1':
                    raise ValueError('only shallow shader snapshots supported')
            elif flag == '--branch':
                branch = args.pop(0)
            elif flag != '--single-branch':
                raise ValueError('unsupported snapshot option')
        if len(args) != 2:
            raise ValueError('invalid shader snapshot arguments')
        snapshot(args[0], branch, args[1])
        return
    record = json.loads((directory / '.git/uwt-archive.json').read_text())
    if operation == 'rev-parse' and args == ['HEAD']:
        print(record['branch'] if re.fullmatch(r'[a-f0-9]{40}', record['branch']) else 'uwt-snapshot')
    elif operation == 'for-each-ref' and len(args) == 3 and args[0] == '--contains' and args[2] == 'refs/remotes':
        if tree_hashes(directory) == record['files']:
            print('uwt-snapshot')
    elif operation == 'cat-file' and len(args) == 2 and args[0] == '-e':
        if args[1] != record['branch'] + '^{commit}':
            raise ValueError('commit not in snapshot cache')
    elif operation == 'fetch' and len(args) == 4 and args[:3] == ['--depth', '1', 'origin'] and re.fullmatch(r'[a-f0-9]{40}', args[3]):
        # checkout below downloads this exact commit; fetch must not move HEAD.
        pass
    elif operation == 'checkout' and len(args) == 3 and args[:2] == ['--quiet', '--detach'] and re.fullmatch(r'[a-f0-9]{40}', args[2]):
        snapshot(record['url'], args[2], directory, update=True)
    elif operation == 'rev-parse' and args == ['@{upstream}']:
        print('uwt-snapshot')
    elif operation == 'rev-list' and args == ['--count', 'uwt-snapshot..HEAD']:
        print(0)
    elif operation == 'status' and args == ['--porcelain']:
        if tree_hashes(directory) != record['files']:
            print(' M local shader cache')
    elif operation == 'pull' and args == ['--ff-only']:
        snapshot(record['url'], record['branch'], directory, update=True)
    else:
        raise ValueError('unsupported Git operation in snapshot adapter')


def main(args):
    if args[0] == 'file' and len(args) == 2:
        print(describe(args[1]))
    elif args[0] == 'git':
        git_call(args[1:])
    else:
        raise ValueError('unsupported compatibility command')


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except (OSError, ValueError, KeyError, IndexError, tarfile.TarError, subprocess.CalledProcessError) as exc:
        print('ReShade compatibility adapter: ' + str(exc), file=sys.stderr)
        sys.exit(1)
