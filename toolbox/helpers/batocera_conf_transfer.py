#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

EXPORT_MARKER = "# ULTIMATE_WINE_TOOLBOX_WINDOWS_CONFIG_EXPORT=1"
USER_MARKER = "# ------------ User-generated Configurations ----------- #"
PROTECTED_HEADING = "## Enable DXVK for Wine and FPS HUD."
WINDOWS_RE = re.compile(r'^\s*(?:windows(?:-renderer)?\.|windows\["[^"]+"\](?:-renderer)?\.)')
GAME_RE = re.compile(r'^\s*windows\["([^"]+)"\](?:-renderer)?\.')
GLOBAL_RE = re.compile(r'^\s*((?:windows|windows-renderer)\..*)$')
EXPORT_GAME_RE = re.compile(r'^\s*(windows\["([^"]+)"\](?:-renderer)?\..*)$')
PROTECTED_RE = re.compile(r'^\s*windows\.dxvk(?:_hud)?=')
HEADER_RE = re.compile(r'^# ===== \[ ([A-Z0-9_.+ -]+) \] =====\s*$')


def active_export_lines(path: Path) -> tuple[list[str], dict[str, list[str]]]:
    globals_: list[str] = []
    games: dict[str, list[str]] = {}
    with path.open("r", encoding="utf-8", errors="surrogateescape") as fh:
        for raw in fh:
            line = raw.rstrip("\r\n")
            if not line or line.lstrip().startswith("#") or PROTECTED_RE.match(line):
                continue
            match = EXPORT_GAME_RE.match(line)
            if match:
                games.setdefault(match.group(2), []).append(match.group(1))
                continue
            match = GLOBAL_RE.match(line)
            if match:
                globals_.append(match.group(1))
    return globals_, games


def cmd_export(args: argparse.Namespace) -> int:
    conf = Path(args.conf)
    output = Path(args.output)
    globals_, games = active_export_lines(conf)
    lines = [
        "# Ultimate Wine Toolbox - Windows configuration export",
        EXPORT_MARKER,
        f"# SOURCE_BATOCERA={args.batocera}",
        "# Protected stock settings windows.dxvk/windows.dxvk_hud are intentionally excluded.",
        "",
    ]
    lines.extend(globals_)
    if globals_ and games:
        lines.append("")
    for game in sorted(games, key=str.casefold):
        lines.extend(games[game])
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(globals_)}\t{len(games)}\t{sum(len(v) for v in games.values())}")
    return 0


def read_export(path: Path) -> tuple[list[str], int, int, int]:
    lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    if EXPORT_MARKER not in lines[:8]:
        raise ValueError("bad-format")
    entries: list[str] = []
    games: set[str] = set()
    global_count = 0
    game_lines = 0
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if PROTECTED_RE.match(line):
            raise ValueError("protected")
        if not WINDOWS_RE.match(line) or "=" not in line:
            raise ValueError("unsafe")
        entries.append(line)
        match = GAME_RE.match(line)
        if match:
            games.add(match.group(1))
            game_lines += 1
        else:
            global_count += 1
    return entries, global_count, len(games), game_lines


def key_of(line: str) -> str:
    return line.split("=", 1)[0].strip().casefold()


def existing_windows_keys(conf: Path) -> set[str]:
    keys: set[str] = set()
    with conf.open("r", encoding="utf-8", errors="surrogateescape") as fh:
        for raw in fh:
            line = raw.rstrip("\r\n")
            if not line or line.lstrip().startswith("#") or PROTECTED_RE.match(line):
                continue
            if WINDOWS_RE.match(line) and "=" in line:
                keys.add(key_of(line))
    return keys


def cmd_preview(args: argparse.Namespace) -> int:
    try:
        entries, global_count, game_count, game_lines = read_export(Path(args.source))
    except UnicodeError:
        print("invalid", file=sys.stderr)
        return 13
    except ValueError as exc:
        code = {"bad-format": 10, "protected": 11, "unsafe": 12}.get(str(exc), 13)
        return code

    existing = existing_windows_keys(Path(args.conf))
    seen: set[str] = set()
    add_count = 0
    skip_count = 0
    for line in entries:
        key = key_of(line)
        if key in existing or key in seen:
            skip_count += 1
        else:
            add_count += 1
            seen.add(key)

    print(f"{global_count}\t{game_count}\t{game_lines}\t{add_count}\t{skip_count}")
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    conf = Path(args.conf)
    source = Path(args.source)
    try:
        imported, _, _, _ = read_export(source)
    except (UnicodeError, ValueError):
        return 21

    with conf.open("r", encoding="utf-8", errors="surrogateescape", newline="") as fh:
        lines = fh.readlines()

    marker_indexes = [i for i, raw in enumerate(lines) if raw.rstrip("\r\n") == USER_MARKER]
    if not marker_indexes:
        return 20
    marker_index = marker_indexes[0]
    newline = "\r\n" if any(raw.endswith("\r\n") for raw in lines) else "\n"

    protected_indexes: set[int] = set()
    for i in range(marker_index):
        if lines[i].rstrip("\r\n") != PROTECTED_HEADING:
            continue
        pos = i
        while pos < marker_index:
            protected_indexes.add(pos)
            if pos > i and lines[pos].rstrip("\r\n") == "":
                break
            pos += 1
        break

    existing_lines: list[str] = []
    existing_keys: set[str] = set()
    for i, raw in enumerate(lines):
        text = raw.rstrip("\r\n")
        if i in protected_indexes or PROTECTED_RE.match(text):
            continue
        if WINDOWS_RE.match(text):
            existing_lines.append(raw)
            if "=" in text:
                existing_keys.add(key_of(text))

    added: list[str] = []
    skipped = 0
    seen_import: set[str] = set()
    for line in imported:
        key = key_of(line)
        if key in existing_keys or key in seen_import:
            skipped += 1
            continue
        seen_import.add(key)
        added.append(line + newline)

    merged = existing_lines + added

    before: list[str] = []
    for i, raw in enumerate(lines[:marker_index]):
        text = raw.rstrip("\r\n")
        if i in protected_indexes or PROTECTED_RE.match(text):
            before.append(raw)
        elif WINDOWS_RE.match(text):
            continue
        else:
            before.append(raw)

    after: list[str] = []
    inside_windows_header = False
    for raw in lines[marker_index + 1:]:
        text = raw.rstrip("\r\n")
        if PROTECTED_RE.match(text):
            after.append(raw)
            inside_windows_header = False
            continue
        header = HEADER_RE.match(text)
        if header:
            inside_windows_header = header.group(1).casefold() == "windows"
            if inside_windows_header:
                continue
            after.append(raw)
            continue
        if WINDOWS_RE.match(text):
            continue
        if inside_windows_header and not text:
            continue
        inside_windows_header = False
        after.append(raw)

    while after and after[-1].strip() == "":
        after.pop()

    insert_at = len(after)
    for i, raw in enumerate(after):
        match = HEADER_RE.match(raw.rstrip("\r\n"))
        if match and match.group(1).casefold() > "windows":
            insert_at = i
            break

    globals_: list[str] = []
    games: dict[str, list[str]] = {}
    for raw in merged:
        match = GAME_RE.match(raw.rstrip("\r\n"))
        if match:
            games.setdefault(match.group(1), []).append(raw)
        else:
            globals_.append(raw)

    windows_block: list[str] = []
    if globals_ or games:
        windows_block.extend([f"# ===== [ WINDOWS ] ====={newline}", newline])
        windows_block.extend(globals_)
        if globals_ and games:
            windows_block.append(newline)
        for game in sorted(games, key=str.casefold):
            windows_block.extend(games[game])
        if insert_at < len(after):
            windows_block.append(newline)

    new_after = after[:insert_at] + windows_block + after[insert_at:]
    output = list(before)
    output.append(lines[marker_index])
    if new_after:
        if output[-1].strip() and new_after[0].strip():
            output.append(newline)
        output.extend(new_after)

    fd, tmp_name = tempfile.mkstemp(prefix=".batocera.conf.wt-import-", dir=str(conf.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape", newline="") as out:
            out.writelines(output)
            out.flush()
            os.fsync(out.fileno())
        shutil.copystat(conf, tmp_name)
        os.replace(tmp_name, conf)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)

    print(f"{len(added)}\t{skipped}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    p_export = sub.add_parser("export")
    p_export.add_argument("--conf", required=True)
    p_export.add_argument("--output", required=True)
    p_export.add_argument("--batocera", required=True)
    p_export.set_defaults(func=cmd_export)

    p_preview = sub.add_parser("preview-import")
    p_preview.add_argument("--conf", required=True)
    p_preview.add_argument("--source", required=True)
    p_preview.set_defaults(func=cmd_preview)

    p_merge = sub.add_parser("merge-import")
    p_merge.add_argument("--conf", required=True)
    p_merge.add_argument("--source", required=True)
    p_merge.set_defaults(func=cmd_merge)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
