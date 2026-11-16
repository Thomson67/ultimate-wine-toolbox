"""Read the environment summary without walking game or prefix trees."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import stat
from xml.etree.ElementTree import ParseError

import es_options
from toolbox_backup import BACKUP_METADATA

ROM_SUFFIXES = {".pc", ".exe", ".wine", ".wsquashfs", ".wtgz"}
HOOKS = ("mangohud", "dxvk", "reshade", "antimicrox", "virtual-keyboard", "es-launcher")
WINDOWS_OPTION = re.compile(r'^windows(?:\["[^"\r\n]+"\])?\.(core|wine-runner|uwt_dxvk)$')
SETTINGS_DEFAULTS = {"", "auto", "default", "batocera", "none"}


def directories(path, suffix=''):
    try:
        return sorted((item for item in path.iterdir() if item.name.endswith(suffix) and item.is_dir()), key=lambda item: item.name.lower())
    except OSError:
        return []


def bottle_inventory(root):
    """Use Batocera's legacy and per-runner layout without measuring sizes."""
    modern, legacy = [], []
    defaults = {"default-prefix", "default-settings"}
    for folder in directories(root):
        if folder.name in defaults:
            continue
        prefixes = directories(folder, ".wine")
        if prefixes or (folder / "default-prefix").is_dir() or (folder / "default-settings").exists():
            modern.extend(("v43", folder.name, item.name, str(item)) for item in prefixes)
        else:
            legacy.append(("legacy", "-", folder.name, str(folder)))
    return modern + legacy


def session_type():
    if os.environ.get("XDG_SESSION_TYPE") == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
        return "Wayland"
    if os.environ.get("XDG_SESSION_TYPE") == "x11" or os.environ.get("DISPLAY"):
        return "Xorg"
    return ""


def catalogue_running(home):
    try:
        pid = int((home / "state/community/catalog-sync.lock").read_text().strip())
        if pid <= 0:
            return False
        command = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        helper = home / "toolbox/helpers/community_catalog.py"
        return b"--serve" in command and os.fsencode(helper.resolve()) in command
    except (OSError, ValueError):
        return False


def integration_versions(runners):
    versions = set()
    for runner in runners:
        try:
            info = (runner / "umu-batocera/runner-info").read_text(errors="replace")
        except OSError:
            continue
        match = re.search(r"^UMU_INTEGRATION=([\d.]+)$", info, re.MULTILINE)
        if match:
            versions.add(match[1])
    return ", ".join(sorted(versions))


def missing_assignments(system, home, runners, native_runners):
    installed = {runner.name for runner in runners + directories(native_runners)}
    bundles = es_options.dxvk_choices(home / "dxvk/bundles")
    configured_runners, configured_bundles = set(), set()

    def lines(path):
        try:
            return path.read_text(errors="replace").splitlines()
        except OSError:
            return []

    for line in lines(system / "batocera.conf"):
        name, equals, value = line.strip().partition("=")
        match = WINDOWS_OPTION.fullmatch(name.strip())
        if equals and match:
            (configured_bundles if match[1] == "uwt_dxvk" else configured_runners).add(value.strip())

    for line in lines(home / "config/dxvk-games.tsv"):
        bundle, sep, _ = line.partition("\t")
        if sep:
            configured_bundles.add(bundle)
    configured_bundles.update(lines(home / "config/dxvk-global")[:1])
    return (sorted(configured_runners - installed - SETTINGS_DEFAULTS - {"wine"}),
            sorted(configured_bundles - bundles.keys() - SETTINGS_DEFAULTS))


def backup_details(system, fr):
    try:
        data = json.loads((system / BACKUP_METADATA).read_text())
        archive = Path(data["path"])
        date = datetime.fromtimestamp(data["timestamp"]).strftime("%Y-%m-%d %H:%M")
        size = data["bytes"]
        runners = data["runners"]
        if not isinstance(size, int) or size < 0 or not isinstance(runners, bool):
            raise ValueError("Invalid backup metadata")
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        return "Aucun export enregistré" if fr else "No recorded export"

    try:
        available = stat.S_ISREG(archive.stat().st_mode) and os.access(archive, os.R_OK)
    except OSError:
        available = False
    if fr:
        mode = "avec runners" if runners else "sans runners"
        state = "accessible" if available else "indisponible"
    else:
        mode = "with runners" if runners else "without runners"
        state = "available" if available else "unavailable"
    unit = 1024**3 if size >= 1024**3 else 1024**2
    suffix = ("Gio" if fr else "GiB") if unit == 1024**3 else ("Mio" if fr else "MiB")
    return f"{date} • {size / unit:.2f} {suffix} • {mode} • {state}\n  {archive}"


def report(system, home, roms, custom, native, language):
    fr = language == "fr"
    none = "aucun" if fr else "none"
    unknown = "inconnue" if fr else "unknown"
    runners = directories(custom)
    umu = [runner for runner in runners if runner.name.endswith("-UMU")]
    try:
        # Count directory entries by name; no per-game stat or recursive scan.
        with os.scandir(roms) as entries:
            games = sum(Path(entry.name).suffix.lower() in ROM_SUFFIXES for entry in entries)
    except OSError:
        games = "indisponible" if fr else "unavailable"
    bottles = len(bottle_inventory(system / "wine-bottles/windows"))
    try:
        enabled = es_options.exposed(system / es_options.FEATURES.relative_to("/userdata/system"))
        labels = [items[0][1][not fr] for items in es_options.OPTIONS.values()
                  if any(key in enabled for key, _, _ in items)]
        if es_options.RESHADE_PRESET_KEY in enabled:
            labels.append("Presets ReShade installés" if fr else "Installed ReShade presets")
        sections = ", ".join(labels) or none
    except (OSError, ValueError, ParseError):
        sections = "illisibles" if fr else "unreadable"

    missing_hooks = [hook for hook in HOOKS
                     if not os.access(system / f"scripts/ultimate-wine-toolbox-{hook}.sh", os.X_OK)]
    running = catalogue_running(home)
    missing_runners, missing_bundles = missing_assignments(system, home, runners, native)

    def line(fr_label, en_label, value):
        print(f"{fr_label if fr else en_label} : {value}")

    line("Rubriques EmulationStation", "EmulationStation sections", sections)
    line("Catalogue communautaire", "Community catalogue",
         ("actif" if running else "arrêté") if fr else ("running" if running else "stopped"))
    line("Hooks manquants", "Missing hooks", ", ".join(missing_hooks) or none)
    print()
    line("Dernière sauvegarde Toolbox", "Latest Toolbox backup", backup_details(system, fr))
    print()
    line("Session graphique", "Display session", session_type() or unknown)
    line("Runners Wine classiques / UMU", "Classic Wine / UMU runners", f"{len(runners) - len(umu)} / {len(umu)}")
    line("Intégration UMU installée", "Installed UMU integration", integration_versions(umu) or unknown)
    line("Jeux Windows", "Windows games", games)
    line("Préfixes Wine", "Wine bottles", bottles)
    if missing_runners:
        line("Runners référencés absents", "Missing runner references", ", ".join(missing_runners))
    if missing_bundles:
        line("Bundles DXVK/VKD3D référencés absents", "Missing DXVK/VKD3D bundle references", ", ".join(missing_bundles))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("system", "home", "roms", "custom", "native"):
        parser.add_argument(name, type=Path)
    parser.add_argument("language", choices=("fr", "en"))
    report(**vars(parser.parse_args()))
