#!/usr/bin/env python3
"""Install only the AntiMicroX launcher test on an unmodified UWT v0.7.2."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.request

BASE_HASHES = {
    'toolbox/modules/antimicrox.sh': '866cb6530ddd52efa0bee287988a5f758954cedf4fc13ac8324988c64cbe7c1f',
    'toolbox/hooks/antimicrox-game-event.sh': 'cdc747d6d44f2fc8c264e32521da948c895c59de40e77e710f434f9520a6d252',
}
HELPER = 'toolbox/helpers/antimicrox_launcher.py'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def replace(path, data, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.uwt-launcher-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def idle():
    if subprocess.run(['pgrep', '-x', 'antimicrox'], stdout=subprocess.DEVNULL).returncode == 0:
        raise ValueError('Fermez le jeu, AntiMicroX et la Toolbox avant installation/restauration.')


def install(home, hook, ref, source=None):
    idle()
    if (home/'VERSION').read_text().strip() != '0.7.2':
        raise ValueError('Ce test nécessite la Toolbox v0.7.2.')
    targets = [(home/path, path) for path in BASE_HASHES]
    targets += [(home/HELPER, HELPER), (hook, 'toolbox/hooks/antimicrox-game-event.sh')]
    for target, source_path in targets:
        if target.is_symlink():
            raise ValueError('Chemin symbolique inattendu : '+str(target))
        if source_path == HELPER:
            if target.exists():
                raise ValueError('Le module de test existe déjà. Restaurer avant réinstallation.')
        elif sha(target.read_bytes()) != BASE_HASHES[source_path]:
            raise ValueError('Fichier modifié ou version différente : '+str(target)+'. Aucun fichier modifié.')
    payloads = {}
    for source_path in [*BASE_HASHES, HELPER]:
        if source:
            data = (source/source_path).read_bytes()
        else:
            url = 'https://raw.githubusercontent.com/Thomson67/ultimate-wine-toolbox/'+ref+'/'+source_path
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read(1024*1024+1)
        if len(data) > 1024*1024:
            raise ValueError('Fichier de test trop volumineux')
        if source_path.endswith('.py'):
            compile(data, source_path, 'exec')
        else:
            subprocess.run(['/bin/bash', '-n'], input=data, check=True)
        payloads[source_path] = data
    # No installed file has been modified before all downloads and checks pass.
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup = home/'state/backups'/('antimicrox-launchers-'+stamp)
    backup.mkdir(parents=True)
    entries = []
    for index, (target, source_path) in enumerate(targets):
        old = target.read_bytes() if target.exists() else None
        name = f'{index:02d}.original'
        mode = target.stat().st_mode & 0o777 if old is not None else 0o644
        if old is not None:
            (backup/name).write_bytes(old)
        entries.append({'path': str(target), 'original': name if old is not None else None,
                        'mode': mode, 'installed_sha256': sha(payloads[source_path])})
    manifest = {'version': 1, 'ref': ref, 'files': entries}
    (backup/'manifest.json').write_text(json.dumps(manifest, indent=2))
    shutil.copy2(__file__, backup/'installer.py')
    done = []
    try:
        for entry, (_, source_path) in zip(entries, targets):
            replace(Path(entry['path']), payloads[source_path], entry['mode'])
            done.append(entry)
    except BaseException:
        for entry in reversed(done):
            target = Path(entry['path'])
            if entry['original'] is None:
                target.unlink(missing_ok=True)
            else:
                replace(target, (backup/entry['original']).read_bytes(), entry['mode'])
        raise
    print('Test launchers installé. Ouvrez la Toolbox > AntiMicroX > 10.')
    print('Vos archives, profils et réglages Sunshine restent inchangés.')
    print('Pour retirer le test (fermer le jeu et la Toolbox) :')
    import shlex
    print(shlex.join(['python3', str(backup/'installer.py'), '--restore', str(backup)]))
    return backup


def restore(backup):
    idle()
    manifest = json.loads((backup/'manifest.json').read_text())
    if manifest.get('version') != 1:
        raise ValueError('Sauvegarde inconnue')
    for entry in manifest['files']:
        path = Path(entry['path'])
        if path.is_symlink() or sha(path.read_bytes()) != entry['installed_sha256']:
            raise ValueError('Fichier changé depuis le test : '+str(path)+'. Restauration automatique refusée.')
    for entry in manifest['files']:
        path = Path(entry['path'])
        if entry['original'] is None:
            path.unlink()
        else:
            replace(path, (backup/entry['original']).read_bytes(), entry['mode'])
    print('Code v0.7.2 restauré. Les profils créés pendant le test sont conservés.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path('/userdata/system/ultimate-wine-toolbox'))
    parser.add_argument('--hook', type=Path, default=Path('/userdata/system/scripts/ultimate-wine-toolbox-antimicrox.sh'))
    parser.add_argument('--ref', help='Commit SHA to install')
    parser.add_argument('--source', type=Path, help='Local source tree (developer tests)')
    parser.add_argument('--restore', type=Path)
    args = parser.parse_args()
    if args.restore:
        restore(args.restore)
    else:
        if not args.source and (not args.ref or not re.fullmatch('[0-9a-f]{40}', args.ref)):
            parser.error('--ref doit être le SHA complet du commit de test')
        install(args.home.resolve(), args.hook.absolute(), args.ref or 'local', args.source)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, SyntaxError, subprocess.SubprocessError) as exc:
        raise SystemExit('Installation/restauration interrompue : '+str(exc))
