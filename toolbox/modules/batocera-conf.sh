#!/bin/bash

BATOCERA_CONF="/userdata/system/batocera.conf"
BATOCERA_CONF_BACKUP_DIR="/userdata/system/backups/ultimate-wine-toolbox"

batocera_conf_scan() {
    [ -r "$BATOCERA_CONF" ] || return 10
    [ -d "$WINDOWS_ROMS_DIR" ] || return 11

    local err rc
    err="$(mktemp /tmp/wt-batocera-conf-scan.XXXXXX)" || return 12

    python3 - "$BATOCERA_CONF" "$WINDOWS_ROMS_DIR" 2>"$err" <<'PY'
from pathlib import Path
import os
import re
import sys

conf = Path(sys.argv[1])
roms = Path(sys.argv[2])

game_re = re.compile(r'^\s*windows\["([^"]+)"\]')
global_re = re.compile(r'^\s*(?:windows\.|windows-renderer\.)')

existing = set()
game_dir_suffixes = (".wine", ".pc")

try:
    for current, dirs, files in os.walk(roms):
        current_path = Path(current)

        # A .wine/.pc directory is itself a game container. Record it but
        # never descend into its prefix/game contents.
        kept_dirs = []
        for name in dirs:
            p = current_path / name
            rel = p.relative_to(roms).as_posix()
            if name.casefold().endswith(game_dir_suffixes):
                existing.add(name.casefold())
                existing.add(rel.casefold())
            else:
                kept_dirs.append(name)
        dirs[:] = kept_dirs

        # Files are cheap to record and accepting all of them is deliberately
        # conservative: an unusual Windows launcher must never be flagged as
        # orphaned merely because its extension is not in a hard-coded list.
        for name in files:
            p = current_path / name
            rel = p.relative_to(roms).as_posix()
            existing.add(name.casefold())
            existing.add(rel.casefold())
except OSError:
    raise SystemExit(2)

global_lines = 0
game_lines = 0
games = {}
order = []

with open(conf, "r", encoding="utf-8", errors="surrogateescape") as fh:
    for raw in fh:
        line = raw.rstrip("\r\n")
        match = game_re.match(line)
        if match:
            game = match.group(1)
            game_lines += 1
            if game not in games:
                games[game] = 0
                order.append(game)
            games[game] += 1
        elif global_re.match(line):
            global_lines += 1

orphans = [(game, games[game]) for game in order if game.casefold() not in existing]

print("\t".join((
    "SUMMARY", str(global_lines), str(game_lines), str(len(games)),
    str(len(orphans)), str(sum(count for _, count in orphans))
)))
for game, count in orphans:
    print("\t".join(("ORPHAN", game, str(count))))
PY
    rc=$?

    if [ "$rc" -ne 0 ]; then
        wt_log "batocera.conf scan failed (python rc=$rc)"
        if [ -s "$err" ]; then
            while IFS= read -r line; do
                wt_log "batocera.conf scan: $line"
            done < "$err"
        fi
        rm -f "$err"
        return 12
    fi

    rm -f "$err"
    return 0
}

batocera_conf_backup() {
    local stamp backup

    [ -r "$BATOCERA_CONF" ] || return 1
    mkdir -p "$BATOCERA_CONF_BACKUP_DIR" || return 1

    stamp="$(date '+%Y%m%d-%H%M%S')"
    backup="$BATOCERA_CONF_BACKUP_DIR/batocera.conf-$stamp.bak"
    [ ! -e "$backup" ] || backup="$BATOCERA_CONF_BACKUP_DIR/batocera.conf-$stamp-$$.bak"

    cp -p -- "$BATOCERA_CONF" "$backup" || return 1
    printf '%s' "$backup"
}

batocera_conf_analyze() {
    local scan rc summary global_lines game_lines games orphan_games orphan_lines
    local report kind game count

    scan="$(batocera_conf_scan)"
    rc=$?
    case "$rc" in
        0) ;;
        10)
            msgbox "$(i18n batocera_conf_title)" "$(i18n batocera_conf_unreadable "$BATOCERA_CONF")"
            return
            ;;
        11)
            msgbox "$(i18n batocera_conf_title)" "$(i18n batocera_conf_roms_missing "$WINDOWS_ROMS_DIR")"
            return
            ;;
        *)
            msgbox "$(i18n batocera_conf_title)" "$(i18n batocera_conf_scan_failed)"
            return
            ;;
    esac

    summary="$(printf '%s\n' "$scan" | awk -F '\t' '$1=="SUMMARY"{print; exit}')"
    IFS=$'\t' read -r _ global_lines game_lines games orphan_games orphan_lines <<< "$summary"

    report="$(mktemp /tmp/wt-batocera-conf-report.XXXXXX)" || return
    {
        printf '%s\n\n' "$(i18n batocera_conf_report_header "$BATOCERA_CONF")"
        printf '%s\n' "$(i18n batocera_conf_report_summary \
            "$global_lines" "$games" "$game_lines" "$orphan_games" "$orphan_lines")"

        if [ "$orphan_games" -gt 0 ]; then
            printf '\n%s\n' "$(i18n batocera_conf_report_orphans)"
            while IFS=$'\t' read -r kind game count; do
                [ "$kind" = "ORPHAN" ] || continue
                printf '• %s (%s)\n' "$game" "$(i18n batocera_conf_lines_count "$count")"
            done <<< "$scan"
        else
            printf '\n%s\n' "$(i18n batocera_conf_no_orphans)"
        fi

        printf '\n%s\n' "$(i18n batocera_conf_report_note)"
    } > "$report"

    maintenance_show_report "$(i18n batocera_conf_analyze)" "$report"
    rm -f "$report"
}

batocera_conf_clean_orphans() {
    local scan rc summary orphan_games orphan_lines kind game count idx=1
    local selected id line selected_file backup removed
    local -a items=()
    local rows=""

    scan="$(batocera_conf_scan)"
    rc=$?
    case "$rc" in
        0) ;;
        10)
            msgbox "$(i18n batocera_conf_title)" "$(i18n batocera_conf_unreadable "$BATOCERA_CONF")"
            return
            ;;
        11)
            msgbox "$(i18n batocera_conf_title)" "$(i18n batocera_conf_roms_missing "$WINDOWS_ROMS_DIR")"
            return
            ;;
        *)
            msgbox "$(i18n batocera_conf_title)" "$(i18n batocera_conf_scan_failed)"
            return
            ;;
    esac

    summary="$(printf '%s\n' "$scan" | awk -F '\t' '$1=="SUMMARY"{print; exit}')"
    IFS=$'\t' read -r _ _ _ _ orphan_games orphan_lines <<< "$summary"

    [ "$orphan_games" -gt 0 ] || {
        msgbox "$(i18n batocera_conf_title)" "$(i18n batocera_conf_no_orphans)"
        return
    }

    while IFS=$'\t' read -r kind game count; do
        [ "$kind" = "ORPHAN" ] || continue
        items+=("$idx" "$game — $(i18n batocera_conf_lines_count "$count")" "off")
        rows+="$game"$'\n'
        idx=$((idx+1))
    done <<< "$scan"

    selected="$(checklist_select "$(i18n batocera_conf_clean)" \
        "$(i18n batocera_conf_clean_prompt "$orphan_games" "$orphan_lines")" \
        "${items[@]}")" || return
    [ -n "$selected" ] || return

    selected_file="$(mktemp /tmp/wt-batocera-conf-selected.XXXXXX)" || return
    : > "$selected_file"

    while IFS= read -r id; do
        [ -n "$id" ] || continue
        line="$(sed -n "${id}p" <<< "$rows")"
        [ -n "$line" ] && printf '%s\n' "$line" >> "$selected_file"
    done <<< "$selected"

    [ -s "$selected_file" ] || {
        rm -f "$selected_file"
        return
    }

    yesno_default_no "$(i18n batocera_conf_clean)" "$(i18n batocera_conf_clean_confirm)" || {
        rm -f "$selected_file"
        return
    }

    backup="$(batocera_conf_backup)" || {
        rm -f "$selected_file"
        msgbox "$(i18n batocera_conf_title)" "$(i18n batocera_conf_backup_failed)"
        return
    }

    removed="$(python3 - "$BATOCERA_CONF" "$selected_file" <<'PY'
from pathlib import Path
import os
import re
import shutil
import sys
import tempfile

conf = Path(sys.argv[1])
selected_file = Path(sys.argv[2])
selected = {
    line for line in selected_file.read_text(
        encoding="utf-8", errors="surrogateescape"
    ).splitlines() if line
}
game_re = re.compile(r'^\s*windows\["([^"]+)"\]')

with conf.open("r", encoding="utf-8", errors="surrogateescape", newline="") as fh:
    lines = fh.readlines()

kept = []
removed = 0
for raw in lines:
    match = game_re.match(raw.rstrip("\r\n"))
    if match and match.group(1) in selected:
        removed += 1
    else:
        kept.append(raw)

fd, tmp_name = tempfile.mkstemp(prefix=".batocera.conf.wt-", dir=str(conf.parent))
try:
    with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape", newline="") as out:
        out.writelines(kept)
        out.flush()
        os.fsync(out.fileno())
    shutil.copystat(conf, tmp_name)
    os.replace(tmp_name, conf)
finally:
    if os.path.exists(tmp_name):
        os.unlink(tmp_name)

print(removed)
PY
)"
    rc=$?
    rm -f "$selected_file"

    if [ "$rc" -eq 0 ]; then
        msgbox "$(i18n batocera_conf_clean)" \
            "$(i18n batocera_conf_clean_done "$removed" "$backup")"
    else
        msgbox "$(i18n batocera_conf_clean)" "$(i18n batocera_conf_modify_failed "$backup")"
    fi
}

batocera_conf_organize() {
    local scan rc summary global_lines game_lines backup result

    scan="$(batocera_conf_scan)"
    rc=$?
    case "$rc" in
        0) ;;
        10)
            msgbox "$(i18n batocera_conf_title)" "$(i18n batocera_conf_unreadable "$BATOCERA_CONF")"
            return
            ;;
        11)
            msgbox "$(i18n batocera_conf_title)" "$(i18n batocera_conf_roms_missing "$WINDOWS_ROMS_DIR")"
            return
            ;;
        *)
            msgbox "$(i18n batocera_conf_title)" "$(i18n batocera_conf_scan_failed)"
            return
            ;;
    esac

    summary="$(printf '%s\n' "$scan" | awk -F '\t' '$1=="SUMMARY"{print; exit}')"
    IFS=$'\t' read -r _ global_lines game_lines _ _ _ <<< "$summary"

    [ $((global_lines + game_lines)) -gt 0 ] || {
        msgbox "$(i18n batocera_conf_title)" "$(i18n batocera_conf_no_windows)"
        return
    }

    yesno_default_no "$(i18n batocera_conf_organize)" \
        "$(i18n batocera_conf_organize_confirm "$global_lines" "$game_lines")" || return

    backup="$(batocera_conf_backup)" || {
        msgbox "$(i18n batocera_conf_title)" "$(i18n batocera_conf_backup_failed)"
        return
    }

    result="$(python3 - "$BATOCERA_CONF" <<'PY'
from pathlib import Path
import os
import re
import shutil
import sys
import tempfile

conf = Path(sys.argv[1])
game_re = re.compile(r'^\s*windows\["([^"]+)"\]')
global_re = re.compile(r'^\s*(?:windows\.|windows-renderer\.)')

with conf.open("r", encoding="utf-8", errors="surrogateescape", newline="") as fh:
    lines = fh.readlines()

globals_ = []
games = {}
game_order = []
remaining = []
first_index = None

for raw in lines:
    line = raw.rstrip("\r\n")
    game_match = game_re.match(line)
    is_global = bool(global_re.match(line))

    if game_match or is_global:
        if first_index is None:
            first_index = len(remaining)
        if game_match:
            game = game_match.group(1)
            if game not in games:
                games[game] = []
                game_order.append(game)
            games[game].append(raw)
        else:
            globals_.append(raw)
        continue

    remaining.append(raw)

if first_index is None:
    print(0)
    raise SystemExit

newline = "\r\n" if any(raw.endswith("\r\n") for raw in lines) else "\n"

group = list(globals_)
if globals_ and games:
    group.append(newline)
for game in game_order:
    group.extend(games[game])

new_lines = remaining[:first_index] + group + remaining[first_index:]

fd, tmp_name = tempfile.mkstemp(prefix=".batocera.conf.wt-", dir=str(conf.parent))
try:
    with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape", newline="") as out:
        out.writelines(new_lines)
        out.flush()
        os.fsync(out.fileno())
    shutil.copystat(conf, tmp_name)
    os.replace(tmp_name, conf)
finally:
    if os.path.exists(tmp_name):
        os.unlink(tmp_name)

print(len(globals_) + sum(len(v) for v in games.values()))
PY
)"
    rc=$?

    if [ "$rc" -eq 0 ]; then
        msgbox "$(i18n batocera_conf_organize)" \
            "$(i18n batocera_conf_organize_done "$result" "$backup")"
    else
        msgbox "$(i18n batocera_conf_organize)" "$(i18n batocera_conf_modify_failed "$backup")"
    fi
}

batocera_conf_menu() {
    while true; do
        local choice
        choice="$(menu_select "$(i18n batocera_conf_title)" "$(i18n batocera_conf_intro)" \
            "1" "$(i18n batocera_conf_analyze)" \
            "2" "$(i18n batocera_conf_clean)" \
            "3" "$(i18n batocera_conf_organize)" \
            "0" "$(i18n back)")" || return

        case "$choice" in
            1) batocera_conf_analyze ;;
            2) batocera_conf_clean_orphans ;;
            3) batocera_conf_organize ;;
            0|"") return ;;
        esac
    done
}
