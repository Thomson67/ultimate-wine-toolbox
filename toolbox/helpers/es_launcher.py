"""Force the configured launcher without modifying the game's Wine prefix."""
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys

from antimicrox_live import atomic
from es_options import Overrides

SAVES = Path('/userdata/saves/windows')
MAX_SCRIPT = 256 * 1024
FLAGS = re.IGNORECASE | re.MULTILINE
CREATE = re.compile(r'^\s*@?copy\s+/y\s+nul\s+"([^"\r\n]+)"\s*(?:>\s*nul)?\s*$', FLAGS)
CHECK = re.compile(r'^\s*@?if\s+exist\s+"([^"\r\n]+)"\s+goto\s+[^&|<>\r\n]+$', FLAGS)


def marker_spec(batch):
    batch = '\n'.join(batch.splitlines())
    def paths(pattern):
        return {value.replace('\\', '/').casefold(): value.replace('\\', '/')
                for value in pattern.findall(batch) if value.replace('\\', '/').split('/')[-1].casefold() == 'conf-ok.txt'}
    writes, checks = paths(CREATE), paths(CHECK)
    if len(writes) != 1 or writes.keys() != checks.keys():
        raise ValueError('Ambiguous conf-ok.txt creation or IF EXIST path')
    path = next(iter(writes.values()))
    prefix = 'z:/userdata/saves/windows/'
    if not path.casefold().startswith(prefix) or any(c in path for c in '%!<>|&^\r\n'):
        raise ValueError('Launcher marker must be a literal Z: path under /userdata/saves/windows')
    return path[len(prefix):]


def safe_marker(relative, saves):
    relative = Path(relative)
    if (relative.is_absolute() or not relative.parts or '..' in relative.parts
            or relative.name.casefold() != 'conf-ok.txt'):
        raise ValueError('Invalid launcher marker path')
    root = saves.resolve()
    marker = root / relative
    if marker.is_symlink() or not marker.resolve().is_relative_to(root):
        raise ValueError('Launcher marker escapes the save directory or is a symlink')
    return marker


def script(rom, relative):
    if rom.suffix.casefold() == '.wsquashfs':
        with subprocess.Popen(['unsquashfs', '-cat', '-no-wildcards', str(rom), str(relative)],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as child:
            data = child.stdout.read(MAX_SCRIPT+1)
            if len(data) > MAX_SCRIPT:
                child.kill()
                raise ValueError('Launcher script exceeds size limit')
            if child.wait() != 0:
                raise ValueError(f'Cannot read {relative} from archive')
    else:
        path = rom / relative
        if not path.resolve().is_relative_to(rom.resolve()) or not path.is_file():
            raise ValueError(f'Invalid launcher script: {relative}')
        with path.open('rb') as stream:
            data = stream.read(MAX_SCRIPT+1)
    if len(data) > MAX_SCRIPT:
        raise ValueError('Launcher script exceeds size limit')
    # Batocera paths containing accents are normally UTF-8. Accept Windows
    # single-byte batch files as well, with their literal paths kept intact.
    try:
        return data.decode('utf-8-sig')
    except UnicodeDecodeError:
        return data.decode('cp1252')


def batch_path(autorun):
    directives = dict((key.strip().upper(), value.strip()) for line in autorun.splitlines()
                      if '=' in line for key, value in (line.split('=', 1),))
    cmd = directives.get('CMD', '')
    match = re.match(r'^"([^"]+\.(?:bat|cmd))"|^(.+?\.(?:bat|cmd))(?:\s|$)', cmd, re.I)
    if not match:
        raise ValueError('autorun.cmd does not directly select a batch file')
    target = (match[1] or match[2]).replace('\\', '/')
    directory = directives.get('DIR', '').strip('"').replace('\\', '/')
    if target.lower().startswith('c:/'):
        path = 'drive_c/' + target[3:]
    else:
        if directory.lower().startswith('c:/'):
            directory = 'drive_c/' + directory[3:]
        path = f'{directory}/{target}' if directory else target
    rel = PurePosixPath(path)
    if (rel.is_absolute() or '..' in rel.parts or rel.as_posix().casefold() == 'autorun.cmd'
            or any(c in path for c in ':!*?%[]<>|&^"')):
        raise ValueError('Batch path is not a literal path inside the game')
    return rel


def regular_file(path):
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except FileNotFoundError:
        return False


def restore(journal, saves):
    if not journal.is_file():
        return
    marker = safe_marker(json.loads(journal.read_text())['marker'], saves)
    backup = marker.with_name(f'.{marker.name}.uwt-{journal.stem}')
    if os.path.lexists(backup):
        if not regular_file(backup):
            raise ValueError('Invalid launcher marker backup')
        if regular_file(marker):
            backup.unlink()  # The batch created a fresh marker after running the launcher.
        elif os.path.lexists(marker):
            raise ValueError('Cannot restore the launcher marker over an existing special file')
        else:
            backup.rename(marker)
    journal.unlink()


def event(home, rom, action, saves=SAVES):
    if rom.suffix.casefold() not in ('.wsquashfs', '.wine', '.pc'):
        return
    state = home/'state/es-launcher'
    journal = state/(hashlib.sha256(os.fsencode(rom)).hexdigest()+'.json')
    requested = action == 'gameStart' and Overrides(rom).get('launcher', game_only=True) == 'next'
    if not requested and not journal.is_file():
        return
    state.mkdir(parents=True, exist_ok=True)
    with (state/'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        restore(journal, saves)
        if not requested or Overrides(rom).get('launcher', game_only=True) != 'next':
            return
        batch = script(rom, batch_path(script(rom, 'autorun.cmd')))
        relative = marker_spec(batch)
        marker = safe_marker(relative, saves)
        if os.path.lexists(marker):
            if not regular_file(marker):
                raise ValueError('Launcher marker is not a regular file')
            backup = marker.with_name(f'.{marker.name}.uwt-{journal.stem}')
            if os.path.lexists(backup):
                raise ValueError('Launcher marker backup already exists')
            atomic(journal, json.dumps({'marker': relative}).encode())
            marker.rename(backup)
        print(f'Launcher enabled for {rom.name}: {marker}')


if __name__ == '__main__':
    try:
        action, home, *args = sys.argv[1:]
        if action == 'restore-all':
            state = Path(home)/'state/es-launcher'
            if state.is_dir():
                with (state/'lock').open('a') as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX)
                    for journal in state.glob('*.json'):
                        restore(journal, SAVES)
        else:
            event(Path(home), Path(args[0]), action)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'ES launcher: {exc}', file=sys.stderr)
        sys.exit(1)
