#!/usr/bin/env python3
"""Observe one game's Wine DLL mappings without modifying launch configuration."""
import argparse
from functools import lru_cache
import os
from pathlib import Path
import re
import time

from reshade_api import DLL_APIS
from reshade_manager import atomic_bytes, key, read_json, save_json, valid_rom

IGNORED = {'wineserver', 'wineboot.exe', 'services.exe', 'explorer.exe', 'rundll32.exe', 'winedevice.exe', 'plugplay.exe', 'rpcss.exe', 'conhost.exe', 'svchost.exe', 'xalia.exe', 'tabtip.exe'}


@lru_cache(maxsize=512)
def posix_cksum(data):
    """UMU's adapter identity uses POSIX cksum, not zlib's reflected CRC32."""
    crc = 0
    length = len(data)
    suffix = bytearray()
    while length:
        suffix.append(length & 255)
        length >>= 8
    for byte in data + suffix:
        crc ^= byte << 24
        for _ in range(8):
            crc = ((crc << 1) ^ (0x04c11db7 if crc & 0x80000000 else 0)) & 0xffffffff
    return crc ^ 0xffffffff


def prefix_matches(value, candidates):
    if not value:
        return False
    path = Path(value)
    for candidate in candidates:
        if path == candidate:
            return True
        try:
            if os.path.samefile(path, candidate):
                return True
        except OSError:
            pass
    return False


def scan(proc, candidates):
    evidence = set()
    processes = set()
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            with (entry / 'environ').open('rb') as stream:
                env = dict(v.split(b'=', 1) for v in stream.read(65536).split(b'\0') if b'=' in v)
            prefix = os.fsdecode(env.get(b'WINEPREFIX', b''))
            compat = os.fsdecode(env.get(b'STEAM_COMPAT_DATA_PATH', b''))
            if not (prefix_matches(prefix, candidates) or
                    (compat and prefix_matches(str(Path(compat)/'pfx'), candidates))):
                continue
            comm = (entry / 'comm').read_text().strip()
            if comm.casefold() in IGNORED:
                continue
            with (entry / 'maps').open('rb') as stream:
                # Vulkan's Linux library is deliberately ignored: it may be DXVK/VKD3D.
                maps = stream.read(4*1024*1024).decode(errors='replace')
            dlls = set(re.findall(r'(?i)(?<![\w.-])(d3d9\.dll|d3d10(?:_1)?\.dll|d3d11\.dll|d3d12\.dll|dxgi\.dll|opengl32\.dll|vulkan-1\.dll|d3d8\.dll|ddraw\.dll)(?:\.so)?(?=[\s/]|$)', maps))
            if dlls:
                evidence.update(d.lower() for d in dlls)
                processes.add(comm)
        except (OSError, ValueError):
            continue
    return evidence, processes


def targets(rom, bottles=Path('/userdata/system/wine-bottles/windows'),
            runners=Path('/userdata/system/wine/custom'),
            compatdata=Path('/userdata/system/umu/compatdata')):
    candidates = [rom, Path('/var/run/wine') / rom.name, Path('/run/wine') / rom.name,
                  bottles / rom.name]
    # Include all runner-specific bottles: the effective runner is selected by ES.
    if bottles.is_dir():
        candidates += [folder / (rom.name + '.wine') for folder in bottles.iterdir() if folder.is_dir()]
    # toolbox/overlay/bin/wine in umu-runner-toolbox binds/materializes the
    # Batocera prefix as compatdata/<safe anchor>-<cksum>/pfx. Materialized
    # prefixes have a different inode: samefile alone cannot identify them.
    # Reproduce its exact identity for installed runners. Never match prefixes
    # by a game-name substring: another game/runner could be mistaken for ours.
    if runners.is_dir():
        anchors = {rom.name, rom.name + '.wine'}
        for runner in runners.iterdir():
            if not runner.is_dir():
                continue
            for anchor in anchors:
                stem = anchor[:-5] if anchor.endswith('.wine') else anchor
                safe = re.sub(rb'[^A-Za-z0-9._-]', b'_', os.fsencode(stem)).decode('ascii')
                for mode in ('embedded', 'compressed'):
                    ident = os.fsencode(f'{mode}|{anchor}|{runner.name}')
                    adapter = compatdata / f'{safe}-{posix_cksum(ident)}'
                    candidates.extend((adapter, adapter/'pfx'))
    return candidates


def observe(rom, report, stop, proc=Path('/proc'), interval=0.5, limit=3600):
    started = time.monotonic()
    evidence, processes = set(), set()
    while not stop.exists() and time.monotonic() - started < limit:
        found, names = scan(proc, targets(rom))
        evidence.update(found)
        processes.update(names)
        save_json(report, {'rom': str(rom), 'candidates': sorted({DLL_APIS[d] for d in evidence}),
                          'evidence': sorted(evidence), 'processes': sorted(processes),
                          'timestamp': time.time(), 'finished': False})
        time.sleep(interval)
    data = read_json(report, {'rom': str(rom), 'candidates': [], 'evidence': [], 'processes': []})
    data.update(finished=True, timed_out=not stop.exists(), timestamp=time.time())
    save_json(report, data)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--home', type=Path, required=True)
    p.add_argument('action', choices=['request', 'observe', 'result', 'active'])
    p.add_argument('rom', type=Path)
    args = p.parse_args()
    rom = Path(os.path.abspath(args.rom))
    state = args.home / 'state'
    request = state / 'reshade-diagnostic.json'
    report = args.home / 'reshade/diagnostics' / (key(rom)+'.json')
    stop = state / 'reshade-diagnostic.stop'
    if args.action == 'request':
        valid_rom(rom)
        state.mkdir(parents=True, exist_ok=True)
        if request.exists() or (state / 'launch-game.request').exists() or (state / 'restart-es.request').exists():
            raise ValueError('another game launch/diagnostic is pending; reopen the toolbox to review it')
        if scan(Path('/proc'), targets(rom))[0]:
            raise ValueError('close this game before starting a diagnostic')
        (state / 'wsq-launch-result').unlink(missing_ok=True)
        stop.unlink(missing_ok=True)
        report.unlink(missing_ok=True)
        save_json(request, {'rom': str(rom)})
        atomic_bytes(state / 'launch-game.request', (str(rom)+'\n').encode())
        # ES still considers this Ports launcher a running game until it exits.
        # Use the proven WSquashFS restart handoff before posting the new launch;
        # otherwise runningGame may report the toolbox and wait forever for it.
        atomic_bytes(state / 'restart-es.request', b'')
    elif args.action == 'active':
        data = read_json(request)
        pid = data.get('observer_pid', 0)
        try:
            command = (Path('/proc') / str(pid) / 'cmdline').read_bytes().split(b'\0')
            active = os.fsencode(str(Path(__file__).resolve())) in command and b'observe' in command
        except OSError:
            active = False
        raise SystemExit(0 if active else 1)
    elif args.action == 'observe':
        data = read_json(request)
        if data.get('rom') != str(rom):
            raise ValueError('diagnostic request no longer matches this launch')
        data['observer_pid'] = os.getpid()
        save_json(request, data)
        observe(rom, report, stop)
    else:
        data = read_json(report)
        if data.get('rom') != str(rom):
            print('\tunknown\t?')
        else:
            print(','.join(data.get('candidates', []))+'\truntime\t'+', '.join(data.get('evidence', [])))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc))
