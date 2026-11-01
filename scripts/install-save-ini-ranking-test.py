#!/usr/bin/env python3
"""Adjust only the save-directory scoring function; preserve unrelated changes."""
import argparse
from pathlib import Path
import shutil

BEFORE = 'def score_save_dir(rel_dir: str, changed_files, directory_files=None):\n    # A savedir may have any name and contain text or extensionless saves.\n    # Reject only folders whose observed files are all clearly temporary.\n    files = list(directory_files if directory_files is not None else changed_files)\n    meaningful = [name for name in files if Path(name).suffix.casefold() not in TEMPORARY_EXTENSIONS]\n    if files and not meaningful:\n        return 0, "temporary/log files only"\n    low = rel_dir.casefold()\n    score = 25\n    reasons = []\n    if any(x in low for x in POSITIVE_PATH):\n        score += 45\n        reasons.append("save-like path")\n    # Match directory words, not substrings of game titles such as Logan or Temple.\n    words = set(re.split(r"[^a-z0-9]+", low))\n    if words.intersection(NEGATIVE_PATH):\n        score -= 15\n        reasons.append("cache/log-like path")\n\n    # Cache data can use save-like names and extensions too (usercache.dat).\n    # Do not let these files supply positive evidence for a save directory.\n    save_files = [name for name in meaningful if "cache" not in Path(name).name.casefold()]\n    if "cache" in low:\n        score -= 20\n        reasons.append("cache directory name")\n    if len(save_files) < len(meaningful):\n        score -= 20 if not save_files else 5\n        reasons.append("cache filename(s)")\n    name_hits = sum(any(hint in Path(name).name.casefold() for hint in SAVE_NAME_HINTS)\n                    for name in save_files)\n    strong_hits = sum(Path(name).suffix.casefold() in STRONG_SAVE_EXTENSIONS for name in save_files)\n    if name_hits or strong_hits:\n        score += 65 + min(15, max(name_hits, strong_hits) * 5)\n        reasons.append("save-like filename or extension")\n    ext_hits = sum(Path(name).suffix.casefold() in SAVE_EXTENSIONS for name in save_files)\n    if ext_hits:\n        score += min(30, ext_hits * 10)\n        reasons.append(f"{ext_hits} save-like file(s)")\n\n    if "/documents/" in f"/{low}/" or "/saved games/" in f"/{low}/":\n        score += 20\n        reasons.append("standard user save location")\n    if "/appdata/" in f"/{low}/":\n        score += 10\n\n    return score, ", ".join(reasons) or "changed during test"\n\n'
AFTER = 'def score_save_dir(rel_dir: str, changed_files, directory_files=None):\n    # A savedir may have any name and contain text or extensionless saves.\n    # Reject only folders whose observed files are all clearly temporary.\n    files = list(directory_files if directory_files is not None else changed_files)\n    meaningful = [name for name in files if Path(name).suffix.casefold() not in TEMPORARY_EXTENSIONS]\n    if files and not meaningful:\n        return 0, "temporary/log files only"\n    low = rel_dir.casefold()\n    score = 25\n    reasons = []\n    if any(x in low for x in POSITIVE_PATH):\n        score += 45\n        reasons.append("save-like path")\n    # Match directory words, not substrings of game titles such as Logan or Temple.\n    words = set(re.split(r"[^a-z0-9]+", low))\n    if words.intersection(NEGATIVE_PATH):\n        score -= 15\n        reasons.append("cache/log-like path")\n\n    # Cache data can use save-like names and extensions too (usercache.dat).\n    # Do not let these files supply positive evidence for a save directory.\n    save_files = [name for name in meaningful if "cache" not in Path(name).name.casefold()]\n    if "cache" in low:\n        score -= 20\n        reasons.append("cache directory name")\n    if len(save_files) < len(meaningful):\n        score -= 20 if not save_files else 5\n        reasons.append("cache filename(s)")\n    # INI files remain selectable, but names such as UserSettings.ini or\n    # save_config.ini must not masquerade as strong progression evidence.\n    evidence_files = [name for name in save_files if Path(name).suffix.casefold() != ".ini"]\n    if meaningful and all(Path(name).suffix.casefold() == ".ini" for name in meaningful):\n        score -= 10\n        reasons.append("INI configuration files only")\n    name_hits = sum(any(hint in Path(name).name.casefold() for hint in SAVE_NAME_HINTS)\n                    for name in evidence_files)\n    strong_hits = sum(Path(name).suffix.casefold() in STRONG_SAVE_EXTENSIONS for name in save_files)\n    if name_hits or strong_hits:\n        score += 65 + min(15, max(name_hits, strong_hits) * 5)\n        reasons.append("save-like filename or extension")\n    ext_hits = sum(Path(name).suffix.casefold() in SAVE_EXTENSIONS for name in save_files)\n    if ext_hits:\n        score += min(30, ext_hits * 10)\n        reasons.append(f"{ext_hits} save-like file(s)")\n\n    if "/documents/" in f"/{low}/" or "/saved games/" in f"/{low}/":\n        score += 20\n        reasons.append("standard user save location")\n    if "/appdata/" in f"/{low}/":\n        score += 10\n\n    return score, ", ".join(reasons) or "changed during test"\n\n'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', type=Path, default=Path('/userdata/system/ultimate-wine-toolbox'))
    parser.add_argument('--restore', action='store_true')
    args = parser.parse_args()
    path = args.home / 'toolbox/helpers/wsquashfs_builder.py'
    text = path.read_text()
    old, new = (AFTER, BEFORE) if args.restore else (BEFORE, AFTER)
    if new in text:
        print('Correctif déjà retiré.' if args.restore else 'Correctif déjà installé.')
        return
    if text.count(old) != 1:
        raise RuntimeError('Calcul du score différent de celui attendu : aucune modification.')
    candidate = text.replace(old, new, 1)
    compile(candidate, str(path), 'exec')
    if not args.restore:
        state = args.home / 'state/save-ini-ranking-test'
        state.mkdir(parents=True, exist_ok=True)
        backup = state / 'wsquashfs_builder.py.original'
        if not backup.exists():
            shutil.copy2(path, backup)
        dest = state / 'installer.py'
        if Path(__file__).resolve() != dest.resolve():
            shutil.copy2(__file__, dest)
    path.write_text(candidate)
    print('Correctif retiré.' if args.restore else 'Score des fichiers INI corrigé. Version de la Toolbox inchangée.')
    if not args.restore:
        print('Les dossiers INI restent proposés. Reprendre la recherche des sauvegardes pour recalculer les scores.')
        print('Restauration : python3 ' + str(state / 'installer.py') + ' --restore --home ' + str(args.home))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc))
