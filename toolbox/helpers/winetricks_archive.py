#!/usr/bin/env python3
"""Rebuild a component-edited archive, retaining the original until validation."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import stat
import subprocess
import tempfile
import uuid
from datetime import datetime

from archive_storage import prepare as prepare_archive_storage
from attached_operation import cancellation_signals, defer_cancellation
from winetricks_target import ensure_idle
from winetricks_games import valid_prefix
from wsquashfs_integrity import check


def identity(path):
    st = path.stat()
    return [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns]


class ArchiveEdit:
    def __init__(self, archive, home):
        self.archive = archive.absolute()
        self.home = home
        self.key = hashlib.sha256(os.fsencode(str(self.archive))).hexdigest()[:24]
        self.workspace = self.archive.parent / ('.uwt-components-' + self.key)
        self.prefix = self.workspace / (self.archive.stem + '.wine')
        self.state = home / 'state/component-archives' / (self.key + '.json')

    @contextmanager
    def locked(self):
        directory = self.home / 'state/component-locks'
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / (self.key + '.lock')).open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield

    def save(self, data):
        self.state.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.state-', dir=self.state.parent)
        try:
            with os.fdopen(fd, 'w') as output:
                json.dump(data, output, indent=2)
            os.replace(name, self.state)
        finally:
            Path(name).unlink(missing_ok=True)

    def load(self):
        data = json.loads(self.state.read_text())
        if (data.get('archive') != str(self.archive) or data.get('prefix') != str(self.prefix)
                or self.workspace.is_symlink() or self.prefix.is_symlink()):
            raise ValueError('Archive component workspace ownership mismatch')
        return data

    def original_unchanged(self, data):
        if self.archive.is_symlink() or identity(self.archive) != data['original']:
            raise ValueError('The original archive has changed; the working prefix is retained')

    def prepare(self):
        if self.archive.is_symlink() or not self.archive.is_file() or self.archive.suffix.casefold() != '.wsquashfs':
            raise ValueError('Select a regular .wsquashfs archive')
        if self.state.exists():
            data = self.load()
            if data['phase'] == 'committed':
                self.cleanup()
                return self.prepare()
            self.original_unchanged(data)
            if data['phase'] != 'extracting':
                if not valid_prefix(self.prefix):
                    raise ValueError('The retained working prefix is incomplete')
                print(f'components_archive_resumed={self.prefix}', flush=True)
                return
        else:
            if self.workspace.exists() or self.workspace.is_symlink():
                raise ValueError('An unowned component workspace already exists; it will not be overwritten')
            data = dict(archive=str(self.archive), prefix=str(self.prefix), original=identity(self.archive), phase='extracting')
            self.save(data)
        ensure_idle(self.archive, self.archive)
        self.workspace.mkdir(exist_ok=True)
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        target = 65536 if hard == resource.RLIM_INFINITY else min(65536, hard)
        if soft != resource.RLIM_INFINITY and soft < target:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
        print(f'components_archive_extract={self.archive}\nworking_prefix={self.prefix}', flush=True)
        subprocess.run(['unsquashfs', '-no-xattrs', '-f', '-d', str(self.prefix), str(self.archive)], check=True)
        if not valid_prefix(self.prefix):
            raise ValueError('The extracted archive does not contain a valid Wine prefix')
        self.original_unchanged(data)
        data['phase'] = 'ready'
        self.save(data)

    def build(self, log):
        data = self.load()
        self.original_unchanged(data)
        if data['phase'] == 'extracting' or not valid_prefix(self.prefix):
            raise ValueError('Complete extraction before rebuilding the archive')
        ensure_idle(self.archive, self.archive)
        ensure_idle(self.prefix, self.prefix)
        if data.get('output'):
            output = Path(data['output'])
            if (output.parent != self.archive.parent or not output.name.startswith('.uwt-components-' + self.key + '-')
                    or output.suffix != '.tmp' or output.is_symlink()):
                raise ValueError('Invalid retained archive output path')
        else:
            output = self.archive.parent / ('.uwt-components-' + self.key + '-' + uuid.uuid4().hex + '.tmp')
        prepare_archive_storage(self.prefix, output, replace_existing=bool(data.get('output')))
        data.update(phase='building', output=str(output))
        self.save(data)
        print(f'components_archive_build={output}', flush=True)
        print(f'components_phase=compression time={datetime.now().isoformat(timespec="seconds")}', flush=True)
        subprocess.run(['mksquashfs', str(self.prefix), str(output), '-noappend', '-comp', 'zstd',
                        '-processors', str(min(4, os.cpu_count() or 1))], check=True)
        cancel = self.workspace / 'integrity.cancel'
        cancel.unlink(missing_ok=True)
        print(f'components_phase=verification time={datetime.now().isoformat(timespec="seconds")}', flush=True)
        if check(output, 'full', log, cancel) != 0:
            raise ValueError('Full verification failed; original archive and working prefix are preserved')
        self.original_unchanged(data)
        ensure_idle(self.archive, self.archive)
        ensure_idle(self.prefix, self.prefix)
        os.chmod(output, stat.S_IMODE(self.archive.stat().st_mode))
        # Fail rather than copy over the destination if a union filesystem
        # cannot perform this rename atomically. The checked output is kept.
        print(f'components_phase=publication time={datetime.now().isoformat(timespec="seconds")}', flush=True)
        with defer_cancellation():
            os.replace(output, self.archive)
            data.update(phase='committed', published=identity(self.archive))
            self.save(data)
        print(f'components_archive_replaced={self.archive}', flush=True)
        print(f'components_phase=cleanup time={datetime.now().isoformat(timespec="seconds")}', flush=True)
        self.cleanup()
        print(f'components_phase=done time={datetime.now().isoformat(timespec="seconds")}', flush=True)

    def cleanup(self):
        data = self.load()
        if data['phase'] != 'committed' or identity(self.archive) != data.get('published'):
            raise ValueError('Only a committed, unchanged archive workspace can be cleaned')
        if self.workspace.exists():
            shutil.rmtree(self.workspace)
        self.state.unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--log', type=Path)
    parser.add_argument('action', choices=('path', 'prepare', 'build', 'cleanup'))
    parser.add_argument('archive', type=Path)
    args = parser.parse_args()
    edit = ArchiveEdit(args.archive, args.home)
    try:
        if args.action == 'path':
            print(edit.prefix)
            return 0
        with edit.locked(), cancellation_signals():
            if args.action == 'prepare':
                edit.prepare()
            elif args.action == 'cleanup':
                edit.cleanup()
            else:
                if args.log is None:
                    raise ValueError('A build/integrity log is required')
                edit.build(args.log)
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'Archive components: {error}\nRetained working prefix: {edit.prefix}', flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
