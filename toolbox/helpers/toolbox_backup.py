"""Export and restore Ultimate Wine Toolbox data under /userdata/system."""
import argparse
import contextlib
import fcntl
import gzip
import hashlib
import json
import io
import os
import shutil
import stat
import sys
import tarfile
import tempfile
import time
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import batocera_conf_transfer as windows
import es_options

HOME = "ultimate-wine-toolbox"
FEATURES = Path("configs/emulationstation") / es_options.FEATURES.name
RUNNERS = Path("wine/custom")
RESHADE_RUNTIME = Path(HOME, "reshade/runtime")
BACKUP_METADATA = Path("backups/ultimate-wine-toolbox/last-export.json")
# These roots contain portable settings and assets. Live recovery journals,
# caches and Wine prefixes are deliberately outside this inventory.
COLLECTIONS = tuple(Path(HOME, name) for name in (
    "config", "config/antimicrox-profiles", "reshade/games", "reshade/profiles", "reshade/runtime",
    "reshade/existing-presets", "dxvk/bundles", "exports",
    "state/community",
))
PORTABLE_STATE = {
    Path(HOME, "state/community/imports.json"),
    Path(HOME, "state/community/es-options-initialized"),
    Path(HOME, "state/antimicrox-pad2key-conversions.json"),
}
MARKER = b"Ultimate Wine Toolbox backup v1\n"


def inventory(system, runners):
    for folder in (*COLLECTIONS, *((RUNNERS,) if runners else ())):
        directory = safe_path(system, folder)
        if directory.is_dir():
            for child in sorted(directory.iterdir()):
                unit = folder / child.name
                if portable(unit) and not child.name.startswith('.') and not child.name.endswith('.lock'):
                    yield unit
    for unit in sorted(PORTABLE_STATE - {p for p in PORTABLE_STATE if p.parent in COLLECTIONS}):
        if safe_path(system, unit).is_file():
            yield unit
    features = safe_path(system, FEATURES)
    if features.is_file() and es_options.OWNER in features.read_bytes():
        yield FEATURES


def portable(unit):
    if unit == Path(HOME, "config/antimicrox-profiles"):
        return False
    if unit == FEATURES or unit in PORTABLE_STATE:
        return True
    parent = unit.parent
    if parent == Path(HOME, "state/community"):
        return False
    return parent in COLLECTIONS or parent == RUNNERS


def safe_path(root, relative, leaf_link=False):
    path = root
    for part in relative.parts:
        path /= part
        if path.is_symlink() and not (leaf_link and path == root / relative):
            raise ValueError(f"Redirected path: {path}")
    return path


def unit_for(relative):
    for index in range(1, len(relative.parts) + 1):
        unit = Path(*relative.parts[:index])
        if portable(unit):
            return unit
    raise ValueError(f"Unexpected archive path: {relative}")


def archive_link(relative, unit, target, system=None):
    # A link may be a leaf of the staging tree, never an extraction parent.
    if relative != unit and target and "\0" not in target:
        # Wine runners can contain absolute links such as dosdevices/z:.
        if unit.parent == RUNNERS:
            return target
        if relative.is_relative_to(RESHADE_RUNTIME):
            if system is not None:
                resolved = (system / relative.parent / target).resolve()
                if resolved.is_relative_to(system):
                    destination = resolved.relative_to(system)
                else:
                    destination = resolved
            else:
                destination = Path(os.path.normpath(relative.parent / target))
            if destination.is_relative_to(RESHADE_RUNTIME):
                return os.path.relpath(destination, relative.parent)
    raise ValueError(f"Unsupported symbolic link: {relative} -> {target}")

def entries(system, runners, output=None):
    def walk(relative, unit):
        path = system / relative
        if output is not None and (path == output or path in output.parents and path == system / unit):
            raise ValueError(f"Select a backup destination outside {system / unit}")
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            archive_link(relative, unit, os.readlink(path), system)
        elif not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise ValueError(f"Unsupported file: {path}")
        yield relative, info
        if stat.S_ISDIR(info.st_mode):
            for child in sorted(path.iterdir()):
                yield from walk(relative / child.name, unit)

    for unit in inventory(system, runners):
        yield from walk(unit, unit)


def external_profiles(system):
    """Copy assigned AntiMicroX profiles stored elsewhere under /userdata."""
    config = system / HOME / "config"
    userdata = system.parent
    replacements = {}

    def portable_profile(value):
        original = Path(value)
        if not original.is_absolute() or original.suffix.casefold() != ".amgp":
            return value
        source = original.resolve()
        if source.is_relative_to(config) or not source.is_relative_to(userdata) or not source.is_file():
            return value
        digest = hashlib.sha256(os.fsencode(source)).hexdigest()
        relative = Path(HOME, "config/antimicrox-profiles", "backup-" + digest + ".amgp")
        replacements[relative] = source.read_bytes()
        return str(system / relative)

    assignments = safe_path(config, Path("antimicrox-games.tsv"))
    if assignments.is_file():
        rows = []
        for line in assignments.read_text().splitlines(keepends=True):
            game, separator, profile = line.rstrip("\r\n").partition("\t")
            rows.append(game + separator + portable_profile(profile) + line[len(line.rstrip("\r\n")):]
                        if separator else line)
        replacements[assignments.relative_to(system)] = "".join(rows).encode()
    launchers = safe_path(config, Path("antimicrox-launchers"))
    for file in launchers.glob("*.json"):
        safe_path(launchers, Path(file.name))
        data = json.loads(file.read_text())
        for key in ("launcher_profile", "game_profile"):
            if isinstance(data.get(key), str):
                data[key] = portable_profile(data[key])
        replacements[file.relative_to(system)] = (json.dumps(data, ensure_ascii=False) + "\n").encode()
    return replacements


def add_bytes(archive, name, data):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o600
    archive.addfile(info, io.BytesIO(data))


def record_export(system, output, runners):
    metadata = safe_path(system, BACKUP_METADATA)
    metadata.parent.mkdir(parents=True, exist_ok=True)
    size = output.stat().st_size
    with tempfile.TemporaryDirectory(prefix=".last-export-", dir=metadata.parent) as temporary:
        staged = Path(temporary) / metadata.name
        staged.write_text(json.dumps({
            "path": str(output), "timestamp": time.time(), "bytes": size, "runners": runners,
        }) + "\n")
        staged.replace(metadata)


def export(system, output, runners):
    output = output.resolve()
    if output == system / BACKUP_METADATA:
        raise ValueError("Select a different backup filename.")
    if output.exists():
        raise ValueError(f"Backup already exists: {output}")
    files = list(entries(system, runners, output))
    replacements = external_profiles(system)
    size = sum(info.st_size for path, info in files if stat.S_ISREG(info.st_mode) and path not in replacements)
    size += sum(map(len, replacements.values()))
    if shutil.disk_usage(output.parent).free < size:
        raise ValueError("Insufficient space for the estimated backup size.")
    with tempfile.TemporaryDirectory(prefix=".uwt-export-", dir=output.parent) as temporary:
        work = Path(temporary)
        conf = work / "windows.conf"
        windows.cmd_export(SimpleNamespace(
            conf=system / "batocera.conf", output=conf, batocera="Toolbox backup"
        ))
        pending = work / "backup.tar.gz"
        # Dereferencing hardlinks is unnecessary. Save each regular file so
        # restores never need to link to arbitrary paths supplied by the tar.
        with tarfile.open(pending, "w:gz", compresslevel=3) as archive:
            for relative, checked in files:
                if relative in replacements:
                    continue
                source = system / relative
                if source.lstat() != checked:
                    raise ValueError(f"Changed during export: {source}")
                if stat.S_ISREG(checked.st_mode):
                    archive.inodes.clear()
                if stat.S_ISLNK(checked.st_mode):
                    member = archive.gettarinfo(source, arcname=f"data/{relative}")
                    member.linkname = archive_link(relative, unit_for(relative), member.linkname, system)
                    archive.addfile(member)
                else:
                    archive.add(source, arcname=f"data/{relative}", recursive=False)
                if source.lstat() != checked:
                    raise ValueError(f"Changed during export: {source}")
            for relative, data in sorted(replacements.items()):
                add_bytes(archive, f"data/{relative}", data)
            archive.add(conf, arcname="windows.conf", recursive=False)
            add_bytes(archive, "format", MARKER)
        if output.exists():
            raise ValueError(f"Backup already exists: {output}")
        pending.rename(output)
    try:
        record_export(system, output, runners)
    except (OSError, ValueError) as error:
        print(f"Could not record successful export: {error}", file=sys.stderr)


def read_archive(source, staging=None, include_runners=True):
    seen, units = set(), set()
    windows_data = None
    size = 0
    found_marker = False
    with gzip.open(source, "rb") as compressed, tarfile.open(fileobj=compressed, mode="r|") as archive:
        for member in archive:
            name = member.name
            if found_marker or name in seen:
                raise ValueError(f"Invalid archive entry: {name}")
            seen.add(name)
            if name == "format":
                if not member.isfile() or member.size != len(MARKER) or archive.extractfile(member).read() != MARKER:
                    raise ValueError("Unsupported backup format.")
                found_marker = True
                continue
            if name == "windows.conf":
                if not member.isfile() or member.size > 32 * 1024 * 1024:
                    raise ValueError("Invalid Windows settings export.")
                windows_data = archive.extractfile(member).read()
                continue
            path = PurePosixPath(name)
            if name != path.as_posix() or path.parts[:1] != ("data",) or ".." in path.parts:
                raise ValueError(f"Invalid archive entry: {name}")
            relative = Path(*path.parts[1:])
            unit = unit_for(relative)
            units.add(unit)
            if member.issym():
                link_target = archive_link(relative, unit, member.linkname)
            elif not (member.isfile() or member.isdir()):
                raise ValueError(f"Unsupported archive entry: {name}")
            if unit == FEATURES and (relative != unit or not member.isfile()):
                raise ValueError("Invalid EmulationStation settings.")
            if unit.parent == RUNNERS and not include_runners:
                continue
            size += member.size
            if staging is None:
                continue
            target = safe_path(staging, relative)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                if member.issym():
                    target.symlink_to(link_target)
                else:
                    with archive.extractfile(member) as stream, target.open("xb") as out:
                        shutil.copyfileobj(stream, out)
                    target.chmod(member.mode & 0o777)
        # Consume the gzip footer to verify the stored data CRC.
        while compressed.read(1024 * 1024):
            pass
    if not found_marker or windows_data is None:
        raise ValueError("Incomplete Toolbox backup.")
    return units, size, windows_data


def prepare_conf(system, staging, data, replace):
    staged_export = staging / "windows.conf"
    staged_export.write_bytes(data)
    imported, _, _, _ = windows.read_export(staged_export)
    conf = system / "batocera.conf"
    original = conf.read_bytes()
    staged_conf = staging / "batocera.conf"
    proposed = original
    if replace:
        keys = {windows.key_of(line) for line in imported}
        lines = original.decode("utf-8", errors="surrogateescape").splitlines(keepends=True)
        proposed = "".join(line for line in lines if not (
            windows.WINDOWS_RE.match(line) and windows.key_of(line) in keys
        )).encode("utf-8", errors="surrogateescape")
    staged_conf.write_bytes(proposed)
    shutil.copystat(conf, staged_conf)
    if windows.cmd_merge(SimpleNamespace(conf=staged_conf, source=staged_export)):
        raise ValueError("Could not merge Windows settings.")
    return original, staged_conf


def restore(system, source, replace, include_runners):
    checked = source.stat()
    _, size, _ = read_archive(source, include_runners=include_runners)
    backup_root = safe_path(system, Path("backups/ultimate-wine-toolbox"))
    backup_root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(backup_root).free < size:
        raise ValueError("Insufficient free space to unpack this backup.")
    with tempfile.TemporaryDirectory(prefix=".restore-", dir=backup_root) as temporary:
        staging = Path(temporary)
        if source.stat() != checked:
            raise ValueError("The archive changed during restore.")
        units, _, windows_data = read_archive(source, staging, include_runners)
        if source.stat() != checked:
            raise ValueError("The archive changed during restore.")
        if FEATURES in units:
            staged_features = staging / FEATURES
            if es_options.OWNER not in staged_features.read_bytes():
                raise ValueError("Unexpected EmulationStation settings fragment.")
            es_options.exposed(staged_features)
            current = safe_path(system, FEATURES)
            if current.exists() and es_options.OWNER not in current.read_bytes():
                raise ValueError("A different EmulationStation settings fragment already exists.")
        original, config = prepare_conf(system, staging, windows_data, replace)
        units = sorted(unit for unit in units if include_runners or unit.parent != RUNNERS)
        destinations = []
        for unit in units:
            destination = safe_path(system, unit)
            if destination.exists() and not replace:
                print(f"Kept / Conservé: {destination}")
                continue
            destinations.append((staging / unit, destination, unit))
        conf = (system / "batocera.conf").resolve()
        if config.read_bytes() != original:
            destinations.append((config, conf, Path("batocera.conf")))
        default_bundle = next((src for src, _, key in destinations
                               if key == Path(HOME, "config/dxvk-global")), None)
        if default_bundle is not None:
            link = safe_path(system, Path("wine/dxvk"), leaf_link=True)
            bundle_root = system / HOME / "dxvk/bundles"
            owned = link.is_symlink() and link.resolve().parent == bundle_root
            if owned or not (link.exists() or link.is_symlink()):
                name = default_bundle.read_text().strip()
                if name == "batocera" and owned:
                    destinations.append((None, link, Path("wine/dxvk")))
                elif name and Path(name).name == name and name not in {".", "..", "batocera"}:
                    bundle = bundle_root / name
                    candidate = staging / bundle.relative_to(system)
                    if any((path / "x32").is_dir() and (path / "x64").is_dir() for path in (candidate, bundle)):
                        staged_link = staging / ".dxvk-link"
                        staged_link.symlink_to(bundle)
                        destinations.append((staged_link, link, Path("wine/dxvk")))
            else:
                print("Existing custom DXVK link or directory preserved / DXVK personnalisé conservé.")
        if conf.read_bytes() != original:
            raise ValueError("batocera.conf changed during restore.")
        if not destinations:
            return
        saved = Path(tempfile.mkdtemp(prefix="before-restore-", dir=backup_root))
        applied = []
        try:
            for src, dst, relative in destinations:
                dst.parent.mkdir(parents=True, exist_ok=True)
                previous = None
                if dst.exists() or dst.is_symlink():
                    previous = saved / relative
                    previous.parent.mkdir(parents=True, exist_ok=True)
                    dst.replace(previous)
                applied.append((src, dst, previous))
                if src is not None:
                    src.replace(dst)
        except BaseException:
            for src, dst, previous in reversed(applied):
                if src is not None and (dst.exists() or dst.is_symlink()):
                    dst.replace(src)
                if previous is not None:
                    previous.replace(dst)
            raise
        print(f"Previous files / Fichiers précédents: {saved}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system", type=Path, default=Path("/userdata/system"))
    parser.add_argument("action", choices=("estimate", "export", "inspect", "restore"))
    parser.add_argument("archive", type=Path)
    parser.add_argument("--runners", action="store_true")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    system = args.system.resolve()
    if args.action == "estimate":
        replacements = external_profiles(system)
        size = sum(info.st_size for path, info in entries(system, args.runners, args.archive.resolve())
                   if stat.S_ISREG(info.st_mode) and path not in replacements)
        size += sum(map(len, replacements.values()))
        print(f"{size}\t{shutil.disk_usage(args.archive.resolve().parent).free}")
    elif args.action == "inspect":
        units, size, windows_data = read_archive(args.archive)
        windows_count = sum(bool(windows.WINDOWS_RE.match(line))
                            for line in windows_data.decode().splitlines())
        print(f"{size / 1024**3:.2f} GiB • {sum(p.parent == RUNNERS for p in units)} runner(s) • {windows_count} Windows setting(s) / réglage(s)")
        for unit in sorted(units):
            if (system / unit).exists():
                print(f"Exists / Existe: {unit}")
    else:
        lock_root = safe_path(system, Path("backups/ultimate-wine-toolbox"))
        lock_root.mkdir(parents=True, exist_ok=True)
        lock = safe_path(lock_root, Path(".lock"))
        with lock.open("a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.action == "export":
                export(system, args.archive, args.runners)
            else:
                restore(system, args.archive, args.replace, args.runners)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, tarfile.TarError, EOFError, RuntimeError, AttributeError) as error:
        sys.exit(str(error))
