"""Temporarily enable per-game Wine diagnostics, collect logs, restore autorun."""
import argparse
import base64
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import zipfile

from antimicrox_live import LiveSession, atomic

DEBUG = '+timestamp,+pid,+event,+x11drv,+dinput'
LOGDIR = Path('/userdata/system/logs/ultimate-wine-toolbox')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def rewrite(raw):
    text = raw.decode('utf-8', errors='surrogateescape')
    tokens = [token for line in text.splitlines() if line.startswith('ENV=')
              for token in shlex.split(line[4:]) if not token.startswith('WINEDEBUG=')]
    tokens.append('WINEDEBUG='+DEBUG)
    lines = [line for line in text.splitlines() if not line.startswith('ENV=')]
    return ('\n'.join(lines+['ENV='+shlex.join(tokens)])+'\n').encode('utf-8', errors='surrogateescape')


class WineTrace:
    def __init__(self, home):
        self.home = Path(home)
        self.backup = self.home/'state/antimicrox-wine-trace.json'

    def prepare(self, rom):
        if self.backup.exists():
            raise ValueError('Restore the preceding Wine trace before preparing another one')
        session = LiveSession(self.home).read() or {}
        if session.get('phase') in ('prepared', 'running'):
            raise ValueError('Close the active live-editing game before preparing Wine diagnostics')
        rom = Path(rom).absolute()
        if (not rom.is_relative_to('/userdata/roms/windows') or '..' in rom.parts
                or rom.suffix.lower() not in ('.wine', '.pc') or not rom.is_dir()):
            raise ValueError('Select an existing Windows .wine or .pc game directory')
        return self._prepare(rom)

    def _prepare(self, rom):
        path = rom/'autorun.cmd'
        if path.is_symlink() or not path.is_file():
            raise ValueError('A regular autorun.cmd is required')
        raw = path.read_bytes()
        injected = rewrite(raw)
        data = {'rom': str(rom), 'autorun': str(path), 'original': base64.b64encode(raw).decode(),
                'mode': stat.S_IMODE(path.stat().st_mode), 'injected_sha256': sha(injected),
                'debug': DEBUG, 'prepared_at': datetime.now().timestamp()}
        atomic(self.backup, json.dumps(data, ensure_ascii=False).encode(), 0o600)
        try:
            atomic(path, injected, data['mode'])
        except BaseException:
            # atomic() never replaces the old file until its content is ready.
            self.backup.unlink(missing_ok=True)
            raise
        return data

    def restore(self):
        if not self.backup.exists():
            return
        data = json.loads(self.backup.read_text())
        path = Path(data['autorun'])
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Autorun path changed; original retained in {self.backup}')
        raw = base64.b64decode(data['original'])
        current = path.read_bytes()
        if current != raw and sha(current) != data['injected_sha256']:
            raise ValueError(f'Autorun was edited during diagnostics; original retained in {self.backup}')
        if current != raw:
            atomic(path, raw, data['mode'])
        self.backup.unlink()

    def metadata(self, data):
        from antimicrox_focus import XWindows
        from antimicrox_handoff import EsApi
        os.environ.setdefault('DISPLAY', ':0')
        os.environ.setdefault('XAUTHORITY', '/var/lib/.Xauthority')
        metadata = {'rom': data['rom'], 'requested_winedebug': data['debug'],
                    'es_running': EsApi().running(), 'wine_processes': []}
        session = LiveSession(self.home).read() or {}
        if session.get('rom') != data['rom'] or session.get('phase') != 'running':
            raise ValueError('Collect while the same live-editing game is still running')
        windows = XWindows()
        try:
            for window in windows.client_windows():
                pid = windows.cardinal(window, '_NET_WM_PID')
                if windows.kind(window, -1) != 'game':
                    continue
                proc = Path('/proc')/str(pid)
                try:
                    env = [item.decode(errors='replace') for item in (proc/'environ').read_bytes().split(b'\0')
                           if item.startswith((b'WINEDEBUG=', b'WINEPREFIX=', b'PROTONPATH=', b'WINELOADER=', b'WINESERVER='))]
                    paths = [line.split(maxsplit=5)[-1] for line in (proc/'maps').read_text().splitlines()
                             if 'winex11.drv' in line]
                    metadata['wine_processes'].append({'pid': pid, 'window': hex(window),
                        'exe': os.readlink(proc/'exe'), 'environment': env, 'winex11_paths': sorted(set(paths))})
                except OSError as exc:
                    metadata['wine_processes'].append({'pid': pid, 'error': str(exc)})
        finally:
            windows.close()
        return metadata

    def collect(self, logdir=LOGDIR, metadata=None, system_logdir=Path('/userdata/system/logs')):
        data = json.loads(self.backup.read_text())
        details = self.metadata(data) if metadata is None else metadata
        logdir.mkdir(parents=True, exist_ok=True)
        path = logdir/f'antimicrox-wine-trace-{datetime.now():%Y%m%d-%H%M%S}-{os.getpid()}.zip'
        candidates = [system_logdir/'es_launch_stderr.log', system_logdir/'es_launch_stdout.log']
        # UMU may redirect Wine stderr to its own launch log instead.
        umu = system_logdir/'umu-runner'
        for candidate in sorted(umu.glob('runner-20*.log'), key=lambda p: p.stat().st_mtime, reverse=True):
            if candidate.stat().st_mtime < data['prepared_at']:
                continue
            with candidate.open('rb') as stream:
                header = stream.read(131072)
            if data['rom'].encode() in header:
                candidates.append(candidate)
                break
        with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('metadata.json', json.dumps(details, ensure_ascii=False, indent=2))
            captures = []
            for candidate in candidates:
                if candidate.is_file():
                    size = candidate.stat().st_size
                    offset = max(0, size-64*1024*1024)
                    name = candidate.parent.name+'/'+candidate.name
                    captures.append({'file': name, 'size_at_capture': size, 'start_offset': offset})
                    # Logs are still growing. Copy a bounded snapshot rather
                    # than reading until a moving EOF or filling the disk.
                    with candidate.open('rb') as source, archive.open(name, 'w') as target:
                        source.seek(offset)
                        remaining = size-offset
                        while remaining:
                            chunk = source.read(min(131072, remaining))
                            if not chunk:
                                break
                            target.write(chunk)
                            remaining -= len(chunk)
            archive.writestr('capture.json', json.dumps(captures, indent=2))
        os.chmod(path, 0o600)
        # Copy stderr before returning to the Toolbox can overwrite ES's logs.
        # Restore autorun now; this does not change the running process's env.
        self.restore()
        return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path('/userdata/system/ultimate-wine-toolbox'))
    sub = parser.add_subparsers(dest='action', required=True)
    prepare = sub.add_parser('prepare'); prepare.add_argument('rom', type=Path)
    sub.add_parser('collect'); sub.add_parser('restore')
    args = parser.parse_args()
    tool = WineTrace(args.home)
    if args.action == 'prepare':
        data = tool.prepare(args.rom)
        print('Traces Wine activées pour : '+data['rom'])
        print('Relancer en configuration AntiMicroX, reproduire le blocage, attendre 2 s, appuyer sur E puis tester les déplacements.')
        print('Laisser le jeu ouvert, puis lancer la commande collect. Elle restaurera aussi autorun.cmd.')
    elif args.action == 'collect':
        print('Archive à joindre : '+str(tool.collect()))
        print('autorun.cmd restauré. Quitter le jeu pour arrêter les traces Wine.')
    else:
        tool.restore()
        print('autorun.cmd restauré.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc))
