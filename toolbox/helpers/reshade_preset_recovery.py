#!/usr/bin/env python3
"""Copy small preset/config snapshots for recovery; never change game files."""
import argparse
import configparser
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid

LIMIT = 2 * 1024 * 1024


def snapshot(home, output):
    home, output = Path(home), Path(output)
    destination = output / (datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    (destination / 'files').mkdir(mode=0o700)
    entries, errors, configs, seen = [], [], [], set()

    def copy(source, base):
        source, base = Path(source), Path(base)
        if str(source) in seen:
            return
        seen.add(str(source))
        try:
            if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(base.resolve()):
                return
            before = source.stat()
            if before.st_size > LIMIT:
                return
            data = source.read_bytes()
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError('file changed during snapshot; retry')
            digest = hashlib.sha256(data).hexdigest()
            filename = 'files/' + digest + source.suffix.lower()
            backup = destination / filename
            if not backup.exists():
                backup.write_bytes(data)
                backup.chmod(0o600)
            entries.append({'source': str(source), 'backup': filename, 'sha256': digest, 'mtime_ns': after.st_mtime_ns})
            if source.name.lower() == 'reshade.ini':
                parser = configparser.ConfigParser(interpolation=None, strict=False)
                parser.read_string(data.decode('utf-8-sig'))
                configs.append({'source': str(source), 'AutoSavePreset': parser.get('OVERLAY', 'AutoSavePreset', fallback='default'),
                                'PresetPath': parser.get('GENERAL', 'PresetPath', fallback='')})
        except (OSError, ValueError, configparser.Error) as error:
            errors.append({'source': str(source), 'error': str(error)})

    profiles = home / 'reshade/profiles'
    for profile in profiles.iterdir() if profiles.is_dir() else []:
        if not profile.is_dir() or profile.is_symlink():
            continue
        for name in ('ReShade.ini', 'ReShadePreset.ini', 'presets/index.json', 'pack/manifest.json'):
            copy(profile / name, home)
        for subdir in ('presets', 'pack/before'):
            for source in (profile / subdir).rglob('*.ini'):
                copy(source, home)
    for journal in (home / 'reshade/installations').glob('*/*.json'):
        try:
            if journal.is_symlink() or journal.stat().st_size > LIMIT:
                continue
            data = json.loads(journal.read_text())
            copy(journal, home)
            root = Path(data['root'])
            if data.get('root_id') != [root.stat().st_dev, root.stat().st_ino]:
                continue
            for name in data.get('files', {}):
                source = Path(name)
                if (source.name in ('ReShade.ini', 'ReShadePreset.ini')
                        or ('UWT-ReShadePresets' in source.parts and source.suffix.lower() == '.ini')):
                    copy(source, root)
        except (OSError, ValueError, KeyError) as error:
            errors.append({'source': str(journal), 'error': str(error)})
    report = {'files': entries, 'configs': configs, 'errors': errors}
    (destination / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    (destination / 'report.json').chmod(0o600)
    return destination, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path('/userdata/system/ultimate-wine-toolbox'))
    parser.add_argument('--output', type=Path, default=Path('/userdata/system/backups/ultimate-wine-toolbox/reshade-presets'))
    args = parser.parse_args()
    destination, report = snapshot(args.home, args.output)
    print(f"Sauvegarde : {destination}\nFichiers conservés : {len(report['files'])}")
    for item in report['configs']:
        print(f"\n{item['source']}\nAutoSavePreset={item['AutoSavePreset']}\nPresetPath={item['PresetPath']}")
    if report['errors']:
        print(f"\nLectures à vérifier : {len(report['errors'])} (voir report.json)")


if __name__ == '__main__':
    main()
