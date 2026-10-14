#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

EXCLUDED_DIRS = {
    "windows", "system32", "syswow64", "_commonredist",
    "program files", "program files (x86)", "programdata",
    "$recycle.bin", "temp", "tmp",
}
EXCLUDED_EXE_NAMES = (
    "unins", "uninstall", "setup", "install", "crash", "report",
    "bug", "config", "settings", "updater", "update",
    "redistributable", "redist", "dxsetup",
)
PRIORITY_EXE_NAMES = ("game", "start", "play", "run", "main")
PRIORITY_DIRS = ("game", "bin", "binaries", "win32", "win64")
SAVE_ROOTS = (
    "AppData/Local", "AppData/LocalLow", "AppData/Roaming",
    "Documents", "Saved Games",
)
SAVE_EXTENSIONS = {
    ".sav", ".save", ".dat", ".profile", ".slot", ".bin", ".json",
}
POSITIVE_PATH = (
    "save", "saved", "savegame", "savegames", "profile", "profiles",
    "userdata", "user data",
)
NEGATIVE_PATH = (
    "cache", "shader", "log", "logs", "crash", "temp", "tmp",
    "d3dscache", "webcache",
)


def registry_sections(prefix: Path):
    """Compare values, ignoring Wine's section timestamps and volatile headers."""
    sections = {}
    key = None
    try:
        text = (prefix / "user.reg").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return sections
    for line in text.splitlines():
        if line.startswith("[") and "]" in line:
            key = line[1:line.rindex("]")]
            sections[key] = []
        elif key is not None and line.strip() and not line.startswith(("#", ";")):
            sections[key].append(line)
    return {key: "\n".join(values) for key, values in sections.items()}


def safe_save_dir(prefix: Path, rel: str, exe: str = "", save_root: Path = Path("/userdata/saves/windows")):
    root = prefix.resolve()
    lexical = Path(os.path.abspath(root / rel))
    lexical.relative_to(root)
    path = lexical.resolve()
    if not path.is_relative_to(root):
        # Batocera may already have redirected this exact SAVEDIR to its saves.
        # Accept only a leaf link with an internal parent and a dedicated target.
        external_root = save_root.resolve()
        if (not lexical.is_symlink() or not lexical.parent.resolve().is_relative_to(root)
                or not path.is_relative_to(external_root) or path == external_root):
            raise ValueError("not an internal directory or a Batocera save-directory link")
    if not path.is_dir() or lexical == root:
        raise ValueError("not an internal save directory")
    internal = lexical.parent.resolve() / lexical.name
    parts = internal.relative_to(root).parts
    if any(x in ("windows", "dosdevices") for x in (p.casefold() for p in parts)):
        raise ValueError("system directory")
    if len(parts) == 1 and parts[0].casefold() == "drive_c":
        raise ValueError("drive root")
    if len(parts) <= 3 and tuple(p.casefold() for p in parts[:2]) == ("drive_c", "users"):
        raise ValueError("user profile root")
    if tuple(p.casefold() for p in parts[:2]) == ("drive_c", "users"):
        if len(parts) == 4 and parts[3].casefold() in ("appdata", "documents", "saved games"):
            raise ValueError("shared profile directory")
        if len(parts) == 5 and parts[3].casefold() == "appdata" and parts[4].casefold() in ("local", "locallow", "roaming"):
            raise ValueError("shared application directory")
    if exe and (root / exe).resolve().is_relative_to(path):
        raise ValueError("directory contains the game executable")
    return internal.relative_to(root).as_posix()


def cmd_directories(args):
    root = Path(args.prefix).resolve()
    current = (root / args.relative).resolve()
    if not current.is_relative_to(root):
        safe_save_dir(Path(args.prefix), args.relative, save_root=Path(args.save_root))
        return
    for child in sorted(current.iterdir(), key=lambda p: p.name.casefold()):
        try:
            if not child.is_dir():
                continue
            if not child.resolve().is_relative_to(root):
                try:
                    safe_save_dir(root, str(child), save_root=Path(args.save_root))
                except ValueError:
                    continue
            rel = child.relative_to(root).as_posix()
            if any(c in rel for c in ("\t", "\n", "\r")):
                continue
            print(rel)
        except OSError:
            continue


def cmd_validate_save(args):
    print(safe_save_dir(Path(args.prefix), args.relative, args.exe, Path(args.save_root)))


def cmd_registry(args):
    before = json.loads(Path(args.before).read_text(encoding="utf-8"))
    old = before.get("__registry__", {})
    rows = []
    for key, values in registry_sections(Path(args.prefix)).items():
        low = key.casefold().replace("\\\\", "\\")
        if not low.startswith("software\\") or low.startswith(("software\\wine", "software\\microsoft", "software\\classes")):
            continue
        if any(c in key for c in ("\t", "\n", "\r")):
            continue
        changed = "__registry__" in before and old.get(key) != values
        score = 50 if changed else 0
        if any(word in (low + " " + values.casefold()) for word in POSITIVE_PATH + ("progress", "level", "unlock", "checkpoint")):
            score += 40
        if score or values:
            rows.append((score, key))
    for score, key in sorted(rows, key=lambda row: (-row[0], row[1].casefold())):
        print(f"{score}\t{key}")


def cmd_registry_view(args):
    values = registry_sections(Path(args.prefix)).get(args.key, "")
    print(f"[{args.key}]\n{values[:6000]}")


def cmd_inspect(args):
    """Bounded read-only listing; never follow links outside the prefix."""
    root = Path(args.prefix).resolve()
    current = (root / args.relative).resolve()
    if not current.is_relative_to(root):
        relative = safe_save_dir(Path(args.prefix), args.relative, save_root=Path(args.save_root))
    else:
        relative = current.relative_to(root).as_posix()
    print(relative + "/\n")
    count = 0

    def visit(folder, depth):
        nonlocal count
        try:
            children = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold()))
        except OSError as exc:
            print(str(exc))
            return
        for child in children:
            if count >= 500:
                return
            count += 1
            try:
                info = child.lstat()
                stamp = datetime.fromtimestamp(info.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                rel = child.relative_to(current).as_posix()
                if child.is_symlink():
                    print(f"{stamp}  [LINK]  {rel} -> {os.readlink(child)}")
                elif child.is_dir():
                    print(f"{stamp}  [DIR]   {rel}/")
                    if depth < 2:
                        visit(child, depth + 1)
                else:
                    print(f"{stamp}  {info.st_size:>12} B  {rel}")
            except OSError as exc:
                print(f"{child.name}: {exc}")

    visit(current, 0)
    if count >= 500:
        print("\n[500 entries maximum]")


def clean_game_name(name: str) -> str:
    name = re.sub(r"(?i)\bbuild\b[.\s]*\d*", " ", name)
    name = re.sub(r"(?i)\bv?\d+(?:\.\d+){1,}\b", " ", name)
    name = name.replace(".", " ")
    return re.sub(r"\s+", " ", name).strip()


def find_exes(prefix: Path, game_relative="drive_c/game"):
    game_dir = prefix / game_relative
    if not game_dir.resolve().is_relative_to(prefix.resolve()):
        raise ValueError("game directory escapes the prefix")
    rows = []
    if not game_dir.is_dir():
        return rows
    for root, dirs, files in os.walk(game_dir):
        root_p = Path(root)
        dirs[:] = [
            d for d in dirs
            if d.casefold() not in EXCLUDED_DIRS
            and not d.startswith('.')
            and not (root_p / d).is_symlink()
            and not (root_p == prefix / 'drive_c' and d.casefold() == 'users')
            and not d.casefold().endswith((".wine", ".pc"))
        ]
        rel_root = root_p.relative_to(prefix)
        for filename in files:
            low = filename.casefold()
            if low == "autorun.cmd":
                continue
            if not low.endswith((".exe", ".bat", ".cmd")):
                continue
            if any(x in low for x in EXCLUDED_EXE_NAMES):
                continue
            candidate = root_p / filename
            if not candidate.is_file() or not candidate.resolve().is_relative_to(prefix.resolve()):
                continue
            rel = (rel_root / filename).as_posix()
            score = 0
            if any(x in low for x in PRIORITY_EXE_NAMES):
                score += 50
            if low.endswith((".bat", ".cmd")) and any(x in low for x in ("start", "launch", "play", "run")):
                score += 20
            rel_low = rel_root.as_posix().casefold()
            if any(x in rel_low for x in PRIORITY_DIRS):
                score += 30
            depth = len(rel_root.parts)
            score += max(0, 25 - depth * 4)
            folder_name = rel_root.name.casefold()
            if folder_name and folder_name in low:
                score += 35
            if "shipping" in low:
                score += 35
            rows.append((score, rel))
    return sorted(rows, key=lambda x: (-x[0], x[1].casefold()))


def candidate_roots(prefix: Path):
    roots = []
    users = prefix / "drive_c" / "users"
    if users.is_dir():
        for user in users.iterdir():
            if not user.is_dir() or user.is_symlink():
                continue
            for rel in SAVE_ROOTS:
                p = user / rel
                if p.is_dir():
                    roots.append(p)
    userdata = prefix / "userdata"
    if userdata.is_dir():
        roots.append(userdata)

    game = prefix / "drive_c" / "game"
    if game.is_dir():
        try:
            for child in game.iterdir():
                if child.is_dir() and any(k in child.name.casefold() for k in POSITIVE_PATH):
                    roots.append(child)
        except OSError:
            pass
    return roots


def file_state(path: Path):
    try:
        st = path.stat()
        return [st.st_mtime_ns, st.st_size]
    except OSError:
        return None


def snapshot(prefix: Path):
    out = {}
    for base in candidate_roots(prefix):
        for root, dirs, files in os.walk(base):
            dirs[:] = [
                d for d in dirs
                if not any(x in d.casefold() for x in ("cache", "shadercache", "webcache", "temp"))
            ]
            root_p = Path(root)
            for filename in files:
                p = root_p / filename
                state = file_state(p)
                if state is None:
                    continue
                try:
                    rel = p.relative_to(prefix).as_posix()
                except ValueError:
                    continue
                out[rel] = state

    game = prefix / "drive_c" / "game"
    if game.is_dir():
        try:
            for p in game.iterdir():
                if p.is_file() and p.suffix.casefold() in SAVE_EXTENSIONS:
                    state = file_state(p)
                    if state:
                        out[p.relative_to(prefix).as_posix()] = state
        except OSError:
            pass
    from wsquashfs_savefiles import inventory
    out["__game_files__"] = inventory(prefix)
    out["__registry__"] = registry_sections(prefix)
    return out


def score_save_dir(rel_dir: str, changed_files):
    low = rel_dir.casefold()
    score = 25
    reasons = []
    if any(x in low for x in POSITIVE_PATH):
        score += 45
        reasons.append("save-like path")
    if any(x in low for x in NEGATIVE_PATH):
        score -= 70
        reasons.append("cache/log-like path")

    ext_hits = sum(Path(f).suffix.casefold() in SAVE_EXTENSIONS for f in changed_files)
    if ext_hits:
        score += min(40, ext_hits * 10)
        reasons.append(f"{ext_hits} save-like file(s)")

    if "/documents/" in f"/{low}/" or "/saved games/" in f"/{low}/":
        score += 20
        reasons.append("standard user save location")
    if "/appdata/" in f"/{low}/":
        score += 10

    return score, ", ".join(reasons) or "changed during test"


def diff_snapshots(prefix: Path, before, after):
    changed = []
    for rel, state in after.items():
        if rel in ("__registry__", "__game_files__"):
            continue
        if before.get(rel) != state:
            changed.append(rel)

    grouped = {}
    for rel in changed:
        parent = str(Path(rel).parent).replace("\\", "/")
        grouped.setdefault(parent, []).append(rel)

    candidates = []
    for parent, files in grouped.items():
        score, reason = score_save_dir(parent, files)
        if score <= 0:
            continue
        candidates.append((score, parent, len(files), reason))
    return sorted(candidates, key=lambda x: (-x[0], x[1].casefold()))


def cmd_exes(args):
    for score, rel in find_exes(Path(args.prefix), args.game_dir):
        print(f"{score}\t{rel}")


def cmd_snapshot(args):
    data = snapshot(Path(args.prefix))
    Path(args.output).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def cmd_diff(args):
    before = json.loads(Path(args.before).read_text(encoding="utf-8"))
    after = snapshot(Path(args.prefix))
    for score, rel, count, reason in diff_snapshots(Path(args.prefix), before, after):
        print(f"{score}\t{count}\t{rel}\t{reason}")


def cmd_clean_name(args):
    print(clean_game_name(args.name))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("exes")
    p.add_argument("prefix")
    p.add_argument("--game-dir", default="drive_c/game")
    p.set_defaults(func=cmd_exes)

    p = sub.add_parser("snapshot")
    p.add_argument("prefix")
    p.add_argument("output")
    p.set_defaults(func=cmd_snapshot)

    p = sub.add_parser("diff")
    p.add_argument("prefix")
    p.add_argument("before")
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser("clean-name")
    p.add_argument("name")
    p.set_defaults(func=cmd_clean_name)

    p = sub.add_parser("directories")
    p.add_argument("prefix")
    p.add_argument("relative")
    p.add_argument("--save-root", default="/userdata/saves/windows")
    p.set_defaults(func=cmd_directories)

    p = sub.add_parser("validate-save")
    p.add_argument("prefix")
    p.add_argument("relative")
    p.add_argument("exe", nargs="?", default="")
    p.add_argument("--save-root", default="/userdata/saves/windows")
    p.set_defaults(func=cmd_validate_save)

    p = sub.add_parser("registry")
    p.add_argument("prefix")
    p.add_argument("before")
    p.set_defaults(func=cmd_registry)

    p = sub.add_parser("registry-view")
    p.add_argument("prefix")
    p.add_argument("key")
    p.set_defaults(func=cmd_registry_view)

    p = sub.add_parser("inspect")
    p.add_argument("prefix")
    p.add_argument("relative")
    p.add_argument("--save-root", default="/userdata/saves/windows")
    p.set_defaults(func=cmd_inspect)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
