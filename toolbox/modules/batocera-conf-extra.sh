#!/bin/bash

batocera_conf_clean_all_orphans() {
    local scan rc summary orphan_games orphan_lines kind game count selected_file backup removed

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

    yesno_default_no "$(i18n batocera_conf_clean_all)" \
        "$(i18n batocera_conf_clean_all_confirm "$orphan_games" "$orphan_lines")" || return

    selected_file="$(mktemp /tmp/wt-batocera-conf-all-orphans.XXXXXX)" || return
    : > "$selected_file"
    while IFS=$'\t' read -r kind game count; do
        [ "$kind" = "ORPHAN" ] || continue
        [ -n "$game" ] && printf '%s\n' "$game" >> "$selected_file"
    done <<< "$scan"

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
selected = {line for line in selected_file.read_text(encoding="utf-8", errors="surrogateescape").splitlines() if line}
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
        msgbox "$(i18n batocera_conf_clean_all)" "$(i18n batocera_conf_clean_all_done "$removed" "$backup")"
    else
        msgbox "$(i18n batocera_conf_clean_all)" "$(i18n batocera_conf_modify_failed "$backup")"
    fi
}

batocera_conf_restore() {
    local -a items=()
    local rows="" path idx=1 count=0 choice selected backup_current tmp rc=0

    [ -d "$BATOCERA_CONF_BACKUP_DIR" ] || {
        msgbox "$(i18n batocera_conf_restore)" "$(i18n batocera_conf_restore_none "$BATOCERA_CONF_BACKUP_DIR")"
        return
    }

    while IFS= read -r path; do
        [ -f "$path" ] || continue
        case "$(basename "$path")" in
            batocera.conf-*.bak) ;;
            *) continue ;;
        esac
        items+=("$idx" "$(basename "$path")")
        rows+="$path"$'\n'
        idx=$((idx+1))
        count=$((count+1))
    done < <(find "$BATOCERA_CONF_BACKUP_DIR" -mindepth 1 -maxdepth 1 -type f -name 'batocera.conf-*.bak' -print 2>/dev/null | sort -r)

    [ "$count" -gt 0 ] || {
        msgbox "$(i18n batocera_conf_restore)" "$(i18n batocera_conf_restore_none "$BATOCERA_CONF_BACKUP_DIR")"
        return
    }

    choice="$(WT_MENU_LIST=1 menu_select "$(i18n batocera_conf_restore)" "$(i18n batocera_conf_restore_prompt "$count")" "${items[@]}")" || return
    [ -n "$choice" ] || return

    selected="$(sed -n "${choice}p" <<< "$rows")"
    [ -f "$selected" ] || {
        msgbox "$(i18n batocera_conf_restore)" "$(i18n batocera_conf_restore_invalid)"
        return
    }

    case "$selected" in
        "$BATOCERA_CONF_BACKUP_DIR"/batocera.conf-*.bak) ;;
        *)
            msgbox "$(i18n batocera_conf_restore)" "$(i18n batocera_conf_restore_invalid)"
            return
            ;;
    esac

    yesno_default_no "$(i18n batocera_conf_restore)" "$(i18n batocera_conf_restore_confirm "$(basename "$selected")")" || return

    backup_current="$(batocera_conf_backup)" || {
        msgbox "$(i18n batocera_conf_restore)" "$(i18n batocera_conf_backup_failed)"
        return
    }

    tmp="$(mktemp /userdata/system/.batocera.conf.restore.XXXXXX)" || rc=1
    if [ "$rc" -eq 0 ]; then
        cp -p -- "$selected" "$tmp" || rc=1
    fi
    if [ "$rc" -eq 0 ]; then
        mv -f -- "$tmp" "$BATOCERA_CONF" || rc=1
    fi
    [ -n "${tmp:-}" ] && [ -e "$tmp" ] && rm -f -- "$tmp"

    if [ "$rc" -eq 0 ]; then
        msgbox "$(i18n batocera_conf_restore)" "$(i18n batocera_conf_restore_done "$(basename "$selected")" "$backup_current")"
    else
        msgbox "$(i18n batocera_conf_restore)" "$(i18n batocera_conf_restore_failed "$backup_current")"
    fi
}

batocera_conf_organize() {
    local backup result rc systems_count lines_count

    [ -r "$BATOCERA_CONF" ] || {
        msgbox "$(i18n batocera_conf_title)" "$(i18n batocera_conf_unreadable "$BATOCERA_CONF")"
        return
    }
    [ -d "/userdata/roms" ] || {
        msgbox "$(i18n batocera_conf_title)" "$(i18n batocera_conf_systems_missing)"
        return
    }

    yesno_default_no "$(i18n batocera_conf_organize)" \
        "$(i18n batocera_conf_organize_confirm_all)" || return

    backup="$(batocera_conf_backup)" || {
        msgbox "$(i18n batocera_conf_title)" "$(i18n batocera_conf_backup_failed)"
        return
    }

    result="$(python3 - "$BATOCERA_CONF" "/userdata/roms" <<'PY'
from pathlib import Path
import os
import re
import shutil
import sys
import tempfile

conf = Path(sys.argv[1])
roms = Path(sys.argv[2])
marker = "# ------------ User-generated Configurations ----------- #"
protected_heading = "## Enable DXVK for Wine and FPS HUD."
generated_header_re = re.compile(r'^# ===== \[ [A-Z0-9_.+ -]+ \] =====\s*$')
per_game_re = re.compile(r'^\s*([A-Za-z0-9_-]+)\["([^"]+)"\](?:-renderer)?\.')
global_re = re.compile(r'^\s*([A-Za-z0-9_-]+)(?:-renderer)?\.')
protected_key_re = re.compile(r'^\s*windows\.dxvk(?:_hud)?=')

with conf.open("r", encoding="utf-8", errors="surrogateescape", newline="") as fh:
    lines = fh.readlines()

marker_indexes = [i for i, raw in enumerate(lines) if raw.rstrip("\r\n") == marker]
if not marker_indexes:
    print("ERROR:MARKER")
    raise SystemExit(20)
marker_index = marker_indexes[0]

newline = "\r\n" if any(raw.endswith("\r\n") for raw in lines) else "\n"

systems = set()
try:
    for p in roms.iterdir():
        if p.is_dir():
            systems.add(p.name.casefold())
except OSError:
    raise SystemExit(21)
systems.add("windows")

def classify(raw):
    line = raw.rstrip("\r\n")
    if not line or line.lstrip().startswith("#"):
        return None

    match = per_game_re.match(line)
    if match:
        prefix = match.group(1).casefold()
        base = "windows" if prefix == "windows-renderer" else prefix
        if base in systems:
            return ("game", base, match.group(2))
        return None

    match = global_re.match(line)
    if match:
        prefix = match.group(1).casefold()
        base = prefix
        if prefix.endswith("-renderer") and prefix[:-9] in systems:
            base = prefix[:-9]
        if base in systems:
            return ("global", base, None)

    return None

protected = set()
protected_heading_index = None
for i in range(marker_index):
    if lines[i].rstrip("\r\n") != protected_heading:
        continue

    protected_heading_index = i
    protected.add(i)
    pos = i + 1
    while pos < marker_index:
        protected.add(pos)
        if lines[pos].rstrip("\r\n") == "":
            break
        pos += 1
    break

# Keep the two active stock DXVK settings in Batocera's original DXVK block.
# This also repairs files organized by an earlier Toolbox build that moved
# these lines below the user-generated marker.
stock_dxvk_lines = []
if protected_heading_index is not None:
    for raw in lines:
        if protected_key_re.match(raw.rstrip("\r\n")):
            stock_dxvk_lines.append(raw)

collected = {}

def add_entry(kind, system, game, raw):
    bucket = collected.setdefault(system, {"global": [], "games": {}})
    if kind == "global":
        bucket["global"].append(raw)
    else:
        bucket["games"].setdefault(game, []).append(raw)

before = []
for i, raw in enumerate(lines[:marker_index]):
    text = raw.rstrip("\r\n")

    if i == protected_heading_index:
        before.append(raw)
        before.extend(stock_dxvk_lines)
        continue

    if protected_heading_index is not None and protected_key_re.match(text):
        continue

    if i in protected:
        before.append(raw)
        continue

    item = classify(raw)
    if item:
        add_entry(*item, raw)
    else:
        before.append(raw)

marker_line = lines[marker_index]

user_other = []
for raw in lines[marker_index + 1:]:
    text = raw.rstrip("\r\n")
    if generated_header_re.match(text):
        continue
    if protected_heading_index is not None and protected_key_re.match(text):
        continue

    item = classify(raw)
    if item:
        add_entry(*item, raw)
    else:
        user_other.append(raw)

while user_other and user_other[-1].strip() == "":
    user_other.pop()

output = list(before)
output.append(marker_line)

if user_other:
    output.extend(user_other)
    output.append(newline)

system_names = sorted(collected, key=str.casefold)

for system_index, system in enumerate(system_names):
    if output and output[-1].strip():
        output.append(newline)

    output.append(f"# ===== [ {system.upper()} ] ====={newline}")
    output.append(newline)

    bucket = collected[system]
    output.extend(bucket["global"])

    game_names = sorted(bucket["games"], key=str.casefold)
    if bucket["global"] and game_names:
        output.append(newline)

    for game in game_names:
        output.extend(bucket["games"][game])

    if system_index != len(system_names) - 1:
        output.append(newline)

fd, tmp_name = tempfile.mkstemp(prefix=".batocera.conf.wt-", dir=str(conf.parent))
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

line_count = sum(
    len(bucket["global"])
    + sum(len(game_lines) for game_lines in bucket["games"].values())
    for bucket in collected.values()
)
print(f"OK:{len(system_names)}:{line_count}")
PY
)"
    rc=$?

    if [ "$rc" -eq 20 ] || [ "$result" = "ERROR:MARKER" ]; then
        msgbox "$(i18n batocera_conf_organize)" \
            "$(i18n batocera_conf_marker_missing "$backup")"
        return
    fi

    if [ "$rc" -ne 0 ]; then
        msgbox "$(i18n batocera_conf_organize)" \
            "$(i18n batocera_conf_modify_failed "$backup")"
        return
    fi

    systems_count="$(printf '%s' "$result" | awk -F: '{print $2}')"
    lines_count="$(printf '%s' "$result" | awk -F: '{print $3}')"

    msgbox "$(i18n batocera_conf_organize)" \
        "$(i18n batocera_conf_organize_done_all \
            "${systems_count:-0}" "${lines_count:-0}" "$backup")"
}

# Override the submenu defined by batocera-conf.sh with the extended one.
batocera_conf_menu() {
    while true; do
        local choice
        choice="$(menu_select "$(i18n batocera_conf_title)" "$(i18n batocera_conf_intro)" \
            "1" "$(i18n batocera_conf_analyze)" \
            "2" "$(i18n batocera_conf_clean)" \
            "3" "$(i18n batocera_conf_clean_all)" \
            "4" "$(i18n batocera_conf_organize)" \
            "5" "$(i18n batocera_conf_restore)" \
            "0" "$(i18n back)")" || return

        case "$choice" in
            1) batocera_conf_analyze ;;
            2) batocera_conf_clean_orphans ;;
            3) batocera_conf_clean_all_orphans ;;
            4) batocera_conf_organize ;;
            5) batocera_conf_restore ;;
            0|"") return ;;
        esac
    done
}
