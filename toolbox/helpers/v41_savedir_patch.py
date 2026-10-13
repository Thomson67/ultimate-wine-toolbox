#!/usr/bin/env python3
"""Install/remove a session-only SAVEDIR shim on supported Batocera 41 scripts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

MARKER = '# UWT_V41_SAVEDIR'
HOME = Path('/userdata/system/ultimate-wine-toolbox/v41-savedir')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def version41(os_release):
    text = os_release.read_text()
    return bool(re.search(r'^PRETTY_NAME=["\']?Batocera(?:\.linux)? 41(?:[.\s"\']|$)', text, re.M))


def patched(text, helper):
    if MARKER in text or 'saveFilesToUserdata' in text:
        raise ValueError('script already contains save redirection; refusing to combine patches')
    if any(c in str(helper) for c in '"$`\\\n\r'):
        raise ValueError('invalid helper path')
    anchor = '    WINE_ENV=$(getWine_var "${WINEPOINT}" "ENV" "")\n'
    for name in ('play_wine', 'play_squashfs'):
        matches = list(re.finditer(r'^' + name + r'\(\) \{\n.*?^\}', text, re.M | re.S))
        if len(matches) != 1:
            raise ValueError(f'unrecognized Batocera 41 function: {name}')
        match = matches[0]; body = match.group()
        if body.count(anchor) != 1:
            raise ValueError(f'unrecognized launch sequence: {name}')
        call = ('    ' + MARKER + '\n'
                '    if [[ "${SYSTEM}" = windows ]]; then\n'
                f'        /usr/bin/python3 "{helper}" "${{WINEPOINT}}" "${{ROMGAMENAME}}" || return 1\n'
                '    fi\n')
        text = text[:match.start()] + body.replace(anchor, anchor + call) + text[match.end():]
    return text


def write_atomic(path, data, mode):
    fd, tmp = tempfile.mkstemp(prefix='.uwt-v41-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def manage(action, target, state, os_release, source):
    if target.is_symlink() or not target.is_file():
        raise ValueError('batocera-wine must be a regular file')
    data = target.read_bytes()
    record = state / 'state.json'
    previous = json.loads(record.read_text()) if record.exists() else None
    if action == 'status':
        print('active' if previous and digest(data) == previous['patched_sha256'] else
              'inactive' if MARKER.encode() not in data else 'changed')
        return
    if action == 'remove':
        if not previous:
            if MARKER.encode() in data:
                raise ValueError('patched script has no restore record')
            return
        original = (state / 'original.sh').read_bytes()
        if digest(original) != previous['original_sha256']:
            raise ValueError('original backup was changed')
        if digest(data) == previous['patched_sha256']:
            write_atomic(target, original, previous['mode'])
        elif digest(data) != previous['original_sha256']:
            raise ValueError('batocera-wine changed since installation; automatic restore refused')
        record.unlink()
        return
    if not version41(os_release):
        raise ValueError('this experimental patch is limited to Batocera 41')
    if state.is_symlink():
        raise ValueError('patch state must be a real directory')
    state.mkdir(parents=True, exist_ok=True)
    helper = state / 'v41_savedir.py'
    if previous and digest(data) == previous['patched_sha256']:
        write_atomic(helper, source.read_bytes(), 0o644)
        return
    if previous and digest(data) != previous['original_sha256']:
        raise ValueError('batocera-wine changed; remove/review the previous patch first')
    text = patched(data.decode(), helper)
    with tempfile.TemporaryDirectory() as folder:
        test = Path(folder) / 'patched.sh'; test.write_text(text)
        subprocess.run(['bash', '-n', str(test)], check=True)
    mode = target.stat().st_mode & 0o777
    write_atomic(helper, source.read_bytes(), 0o644)
    write_atomic(state / 'original.sh', data, mode)
    metadata = dict(original_sha256=digest(data), patched_sha256=digest(text.encode()), mode=mode)
    write_atomic(record, json.dumps(metadata).encode(), 0o600)
    write_atomic(target, text.encode(), mode)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('install', 'remove', 'status'))
    parser.add_argument('--target', type=Path, default=Path('/usr/bin/batocera-wine'))
    parser.add_argument('--state', type=Path, default=HOME)
    parser.add_argument('--os-release', type=Path, default=Path('/etc/os-release'))
    args = parser.parse_args()
    try:
        manage(args.action, args.target, args.state, args.os_release, Path(__file__).with_name('v41_savedir.py'))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f'Batocera 41 patch: {error}\n')
