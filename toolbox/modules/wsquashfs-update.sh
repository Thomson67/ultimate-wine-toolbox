#!/bin/bash

source "$(dirname "${BASH_SOURCE[0]}")/../lib/operations.sh"

WSQ_UPDATE_HELPER="$WT_ROOT/helpers/wsquashfs_update.py"

wsq_update_run() {
    local title="$1" body="$2" log="$3" pid start=$SECONDS rc
    have_dialog || printf '%b\n' "$body"
    shift 3
    local UWT_OPERATION_OWNER="${UWT_SESSION_OWNER:-}"
    [ -n "$UWT_OPERATION_OWNER" ] || read -r UWT_OPERATION_OWNER _ < /proc/self/stat
    wt_operation_run "$@" >> "$log" 2>&1 &
    pid=$!
    while kill -0 "$pid" 2>/dev/null; do
        if have_dialog; then
            dialog --no-shadow --title "$title" --infobox \
                "$body\n\n$(i18n wsq_update_elapsed "$((SECONDS-start))")" 12 96
        fi
        sleep 1
    done
    wait "$pid"; rc=$?
    wt_clear_tty
    return "$rc"
}

# Keep both output streams in the operation report while forwarding progress.
# PIPESTATUS preserves unsquashfs failures rather than tee's successful exit.
wsq_update_logged_command() {
    local log="$1"
    shift
    {
        # This pipeline runs in a subshell: keep Toolbox/session limits unchanged.
        local soft hard target=65536
        soft="$(ulimit -Sn)"; hard="$(ulimit -Hn)"
        if [ "$hard" != unlimited ] && [ "$hard" -lt "$target" ]; then
            ulimit -Hn "$target" 2>/dev/null || true
            hard="$(ulimit -Hn)"
            [ "$hard" = unlimited ] || [ "$hard" -ge "$target" ] || target="$hard"
        fi
        if [ "$soft" != unlimited ] && [ "$soft" -lt "$target" ]; then
            ulimit -Sn "$target" 2>/dev/null || true
        fi
        printf 'Extraction open files: soft=%s hard=%s (previous soft=%s)\n' \
            "$(ulimit -Sn)" "$(ulimit -Hn)" "$soft"
        wt_operation_run "$@"
    } 2>&1 | tee -a "$log"
    local -a statuses=("${PIPESTATUS[@]}")
    [ "${statuses[0]}" -eq 0 ] || return "${statuses[0]}"
    return "${statuses[1]}"
}

wsq_update_extract() {
    local title="$1" body="$2" log="$3" rc=0
    shift 3
    {
        printf '\n[%s] Extraction started\n' "$(date '+%Y-%m-%d %H:%M:%S')"
        printf 'Command:'; printf ' %q' "$@"; printf '\n'
    } >> "$log" || return 1
    maintenance_run_progress "$title" "$body" wsq_update_logged_command "$log" "$@" || rc=$?
    printf '\nExtraction exit=%s\n' "$rc" >> "$log" || return 1
    return "$rc"
}

wsq_update_log_detail() {
    python3 - "$1" <<'PY'
from pathlib import Path
import re
import sys
try:
    lines = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace").splitlines()
except OSError:
    lines = []
# Focus on the last attempt: do not surface an older failure after a retry.
starts = [i for i, line in enumerate(lines)
          if line.startswith('operation_started=') or re.match(r'^\[.*\] .* started$', line)]
if starts:
    lines = lines[starts[-1]:]
lines = [line for line in lines if line.strip() and not line.strip().isdigit()]
errors = [line for line in lines if re.search(
    r'error|fatal|failed|no space|cannot|not enough|killed|interrupt|erreur|impossible|'
    r'exit(?:_code)?[=:]\s*[1-9][0-9]*', line, re.I)]
detail = "\n".join(errors[-3:] if errors else lines[-4:])[-900:]
print(detail or "No additional detail was written to the log.")
PY
}

wsq_find_unfinished_preparations() {
    [ -d "$WSQ_WINDOWS_DIR" ] || return 0
    local prefix relative game artifact
    while IFS= read -r -d '' prefix; do
        artifact="$prefix/.uwt-update-embedded-save"
        if [ -e "$artifact" ] || [ -L "$artifact" ]; then
            printf '%s\n' "$artifact"
        fi
        relative="$(python3 "$WSQ_UPDATE_HELPER" game-dir "$prefix" 2>/dev/null)" || continue
        game="$prefix/$relative"
        artifact="$game.bak"
        if [ -e "$artifact" ] || [ -L "$artifact" ]; then
            printf '%s\n' "$artifact"
        fi
    done < <(find "$WSQ_WINDOWS_DIR" -mindepth 1 -maxdepth 1 -type d -name '*.wine' -print0 2>/dev/null)
}

wsq_pending_guard() {
    if [ ! -s "$WSQ_STATE_FILE" ]; then
        local leftovers choice
        leftovers="$(wsq_find_unfinished_preparations)"
        [ -n "$leftovers" ] || return 0
        choice="$(menu_select "$(i18n wsq_resume_title)" \
            "$(i18n wsq_pending_orphaned "$leftovers")" \
            continue "$(i18n wsq_pending_continue)" \
            back "$(i18n back)")" || return 1
        [ "$choice" = continue ] && return 0
        return 1
    fi
    local prefix snapshot mode game phase archive log metadata summary operation stage choice
    prefix="$(wsq_state_value prefix 2>/dev/null)" || prefix=""
    snapshot="$(wsq_state_value snapshot 2>/dev/null)" || snapshot=""
    mode="$(wsq_state_value mode 2>/dev/null)" || mode=""
    game="$(wsq_state_value game_name 2>/dev/null)" || game=""
    phase="$(wsq_state_value phase 2>/dev/null)" || phase=""
    archive="$(wsq_state_value archive 2>/dev/null)" || archive=""
    log="$(wsq_state_value update_log 2>/dev/null)" || log=""
    metadata="$(wsq_state_value metadata 2>/dev/null)" || metadata=""

    [ -n "$mode" ] || mode=create
    if [ -z "$phase" ] && [ -d "$prefix" ] && [ -s "$snapshot" ]; then
        phase=testing
    fi
    case "$mode" in
        update) operation="$(i18n wsq_pending_operation_update)" ;;
        create) operation="$(i18n wsq_pending_operation_create)" ;;
        *) operation="$(i18n wsq_pending_operation_unknown)" ;;
    esac
    case "$phase" in
        extracting) stage="$(i18n wsq_pending_stage_extracting)" ;;
        preparing) stage="$(i18n wsq_pending_stage_preparing)" ;;
        selecting-executable) stage="$(i18n wsq_pending_stage_executable)" ;;
        writing-autorun) stage="$(i18n wsq_pending_stage_autorun)" ;;
        configuring) stage="$(i18n wsq_pending_stage_configuring)" ;;
        snapshotting) stage="$(i18n wsq_pending_stage_snapshot)" ;;
        testing) stage="$(i18n wsq_pending_stage_testing)" ;;
        committed) stage="$(i18n wsq_pending_stage_committed)" ;;
        *) stage="$(i18n wsq_pending_stage_unknown)" ;;
    esac
    [ -n "$game" ] || game="$(i18n wsq_pending_value_unknown)"
    [ -n "$prefix" ] || prefix="$(i18n wsq_pending_value_unknown)"
    [ -n "$archive" ] || archive="$(i18n wsq_pending_value_unknown)"
    [ -n "$log" ] || log="$(i18n wsq_pending_value_unknown)"
    summary="$(i18n wsq_pending_summary "$operation" "$game" "$stage" \
        "$(wsq_display_path "$prefix")" "$(wsq_display_path "$archive")" "$(wsq_display_path "$log")")"

    # Testing and prepared updates retain the snapshot needed to resume safely.
    if { [ "$phase" = testing ] || [ "$phase" = ready ] ||
         { [ "$mode" = update ] && [ "$phase" = configuring ] &&
           [ "$(wsq_state_value save_review_ready)" = 1 ]; }; } && [ -d "$prefix" ] && [ -s "$snapshot" ] &&
        { [ "$mode" != update ] || [ -s "$metadata" ]; }; then
        choice="$(menu_select "$(i18n wsq_resume_title)" \
            "$summary\n\n$(i18n wsq_pending_what_next)" \
            resume "$(i18n wsq_pending_resume)" \
            abandon "$(i18n wsq_pending_abandon_continue)" \
            back "$(i18n back)")" || return 1
        case "$choice" in
            resume) wsq_resume_build; return 1 ;;
            abandon) wsq_abandon_pending "$prefix"; return 0 ;;
            *) return 1 ;;
        esac
    fi

    choice="$(menu_select "$(i18n wsq_resume_title)" \
        "$summary\n\n$(i18n wsq_pending_incomplete)" \
        abandon "$(i18n wsq_pending_abandon)" \
        back "$(i18n back)")" || return 1
    [ "$choice" = abandon ] || return 1
    wsq_abandon_pending "$prefix"
    return 1
}

wsq_begin_update_state() {
    local prefix="$1" game_name="$2" snapshot="$3" archive="$4" metadata="$5" log="$6" phase="$7"
    python3 - "$WSQ_STATE_FILE" "$prefix" "$game_name" "$snapshot" "$archive" "$metadata" "$log" "$phase" <<'PY'
import json, os, sys
path, prefix, game, snapshot, archive, metadata, log, phase = sys.argv[1:9]
data = {
    "mode": "update",
    "phase": phase,
    "prefix": prefix,
    "game_name": game,
    "snapshot": snapshot,
    "archive": archive,
    "metadata": metadata,
    "update_log": log,
}
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
os.replace(tmp, path)
PY
}

wsq_update_state() {
    python3 - "$WSQ_STATE_FILE" "$@" <<'PY'
import json, os, sys
path = sys.argv[1]
with open(path, encoding='utf-8') as f:
    data = json.load(f)
for i in range(2, len(sys.argv), 2):
    data[sys.argv[i]] = sys.argv[i + 1]
tmp = path + '.tmp'
with open(tmp, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
os.replace(tmp, path)
PY
}

wsq_update_select_executable() {
    local prefix="$1" existing choice
    existing="$(python3 "$WSQ_UPDATE_HELPER" exe "$prefix")" || return 1
    if [ -n "$existing" ]; then
        choice="$(menu_select "$(i18n wsq_executable_title)" \
            "$(i18n wsq_update_exe_prompt "$(wsq_display_path "$existing")")" \
            keep "$(i18n wsq_update_exe_keep)" other "$(i18n wsq_update_exe_other)")" || return 1
        case "$choice" in
            keep) printf '%s\n' "$existing"; return 0 ;;
            other) ;;
            *) return 1 ;;
        esac
    else
        msgbox "$(i18n wsq_executable_title)" "$(i18n wsq_update_exe_missing)"
    fi
    local game_dir
    game_dir="$(python3 "$WSQ_UPDATE_HELPER" game-dir "$prefix")" || return 1
    wsq_select_executable "$prefix" "$game_dir"
}

wsq_update_select_source() {
    local path base choice selected game_dir matched preferred="${1:-}" excluded="${2:-}" idx=1
    local -a folders=() items=()
    local -A WT_MENU_GAME_LABELS=()
    while IFS=$'\t' read -r path matched; do
        [ -d "$path" ] && [ ! -L "$path" ] || continue
        base="$(basename "$path")"
        wsq_source_folder_visible "$base" || continue
        folders+=("$path")
        [ "$matched" != 1 ] || WT_MENU_GAME_LABELS["$idx"]="$base"
        [ "$matched" != 1 ] || base="$base — $(i18n wsq_update_name_match)"
        items+=("$idx" "$base")
        idx=$((idx+1))
    done < <(python3 "$WSQ_UPDATE_HELPER" listing "$WSQ_WINDOWS_DIR" sources --preferred "$preferred" --exclude "$excluded")
    items+=(browse "$(i18n wsq_update_source_browse)")
    choice="$(WT_MENU_LIST=1 menu_select "$(i18n wsq_update_source_title)" "$(i18n wsq_update_source_list_prompt)" "${items[@]}")" || return 1
    case "$choice" in
        browse)
    if command -v yad >/dev/null 2>&1; then
        selected="$(DISPLAY="${DISPLAY:-:0}" LANGUAGE="$WT_LANGUAGE" yad --file --directory \
            --filename="$WSQ_WINDOWS_DIR/" --title="$(i18n wsq_update_source_title)" --width=1000 --height=700)" || return
    else
        selected="$(input_text "$(i18n wsq_update_source_title)" "$(i18n wsq_update_source_prompt)" "$WSQ_WINDOWS_DIR/")" || return
    fi
            ;;
        ''|*[!0-9]*) return 1 ;;
        *)
            [ "$choice" -ge 1 ] && [ "$choice" -lt "$idx" ] || return 1
            selected="${folders[$((choice-1))]}"
            ;;
    esac
    # A listed Wine prefix supplies its game content, rather than another prefix.
    if [ -d "$selected/drive_c" ] && [ -f "$selected/system.reg" ]; then
        game_dir="$(python3 "$WSQ_UPDATE_HELPER" game-dir "$selected")" || {
            msgbox "$(i18n wsq_update_title)" "$(i18n wsq_source_invalid "$selected")"
            return 1
        }
        selected="$selected/$game_dir"
    fi
    printf '%s\n' "$selected"
}

wsq_update_prefix_target() {
    local archive="$1" source="$2" target="${1%.*}.wine" choice name source_real target_real
    while [ -e "$target" ] || [ -L "$target" ]; do
        choice="$(menu_select "$(i18n wsq_update_prefix_conflict_title)" \
            "$(i18n wsq_update_prefix_conflict "$target")" \
            replace "$(i18n wsq_update_prefix_replace)" \
            rename "$(i18n wsq_update_prefix_rename)" \
            cancel "$(i18n cancel)")" || return 1
        case "$choice" in
            replace)
                source_real="$(readlink -f -- "$source")" || return 1
                target_real="$(readlink -f -- "$target")" || return 1
                case "$source_real" in
                    "$target_real"|"$target_real"/*)
                        msgbox "$(i18n wsq_update_title)" "$(i18n wsq_update_prefix_source_overlap)"; continue ;;
                esac
                [ -d "$target" ] && [ ! -L "$target" ] || {
                    msgbox "$(i18n wsq_update_title)" "$(i18n wsq_source_invalid "$target")"; continue
                }
                break ;;
            rename)
                name="$(input_text "$(i18n wsq_update_prefix_conflict_title)" "$(i18n wsq_update_prefix_name_prompt)" "$(basename "${archive%.*}")-update.wine")" || continue
                case "$name" in ''|.|..|*/*|*$'\n'*|*$'\r'*|*$'\t'*) continue ;; esac
                [ "${name: -5}" = .wine ] || name="$name.wine"
                target="$(dirname "$archive")/$name" ;;
            *) return 1 ;;
        esac
    done
    printf '%s\n' "$target"
}

wsq_update_new() {
    wsq_pending_guard || return
    local archive source prefix game_name exe_rel runner snapshot metadata log choice idx=1 rows="" path stamp matched label base reuse_prefix=0 phase
    local source_links
    local -a prepare_args=()
    local WT_MENU_CANCEL_LABEL="$(i18n back)"
    local -a items=()
    local -A WT_MENU_GAME_LABELS=()
    command -v unsquashfs >/dev/null 2>&1 && command -v mksquashfs >/dev/null 2>&1 || {
        msgbox "$(i18n wsq_update_title)" "$(i18n squash_tools_missing)"; return
    }
    while IFS=$'\t' read -r path matched; do
        [ -n "$path" ] || continue
        label="${path##*/}"
        if [ -d "$path" ]; then
            label="$label — $(i18n wsq_update_reuse_label)"
        fi
        [ "$matched" != 1 ] || label="$label — $(i18n wsq_update_name_match)"
        [ "$label" = "${path##*/}" ] || WT_MENU_GAME_LABELS["$idx"]="${path##*/}"
        items+=("$idx" "$label")
        rows+="$path"$'\n'
        idx=$((idx+1))
    done < <(python3 "$WSQ_UPDATE_HELPER" listing "$WSQ_WINDOWS_DIR" bases)
    [ "${#items[@]}" -gt 0 ] || {
        msgbox "$(i18n wsq_update_title)" "$(i18n wsq_update_no_base)"; return
    }
    while true; do
        choice="$(WT_MENU_LIST=1 menu_select "$(i18n wsq_update_title)" "$(i18n wsq_update_intro)\n\n$(i18n wsq_version_warning)" "${items[@]}")" || return
        case "$choice" in ''|*[!0-9]*) return ;; esac
        [ "$choice" -ge 1 ] && [ "$choice" -lt "$idx" ] || return
        base="$(sed -n "${choice}p" <<< "$rows")"
        reuse_prefix=0; prepare_args=()
        if [ -d "$base" ] && [ ! -L "$base" ]; then
            reuse_prefix=1
            prefix="$base"
            archive="${base%.*}.wsquashfs"
            prepare_args+=(--reuse-prefix)
            python3 "$WSQ_UPDATE_HELPER" game-dir "$prefix" >/dev/null 2>&1 || {
                msgbox "$(i18n wsq_update_title)" "$(i18n wsq_update_prefix_required)"; continue
            }
        else
            archive="$base"
        fi
        while true; do
            source="$(wsq_update_select_source "${archive##*/}" "$base")" || break
            [ -d "$source" ] || { msgbox "$(i18n wsq_update_title)" "$(i18n wsq_source_invalid "$source")"; return; }
            if [ "$reuse_prefix" -eq 0 ]; then
                [ "$(maintenance_detect_wsquashfs_type "$archive")" = wine ] || {
                    msgbox "$(i18n wsq_update_title)" "$(i18n wsq_update_prefix_required)"; return
                }
            fi
            game_name="$(basename "$archive")"; game_name="${game_name%.*}"
            stamp="$(date '+%Y%m%d-%H%M%S')-$$"
            if [ "$reuse_prefix" -eq 1 ]; then
                yesno_default_no "$(i18n wsq_update_title)" \
                    "$(i18n wsq_update_reuse_confirm "$(wsq_display_path "$prefix")" "$(wsq_display_path "$source")" "$(wsq_display_path "$archive")")" || continue
            else
                prefix="$(wsq_update_prefix_target "$archive" "$source")" || continue
                yesno_default_no "$(i18n wsq_update_title)" \
                    "$(i18n wsq_update_confirm "$(wsq_display_path "$archive")" "$(wsq_display_path "$source")" "$(wsq_display_path "$prefix")")" || continue
            fi
            break 2
        done
    done
    if [ "$reuse_prefix" -eq 0 ] && [ -e "$prefix" ]; then
        maintenance_delete_wine_dir_symlink_safe "$prefix" || {
            msgbox "$(i18n wsq_update_title)" "$(i18n wsq_source_invalid "$prefix")"; return
        }
    fi
    mkdir -p "$WSQ_STATE_DIR" "$WT_LOG_DIR" || return
    metadata="$WSQ_STATE_DIR/wsquashfs-update-$stamp.json"
    snapshot="$WSQ_STATE_DIR/wsquashfs-before-$stamp.json"
    log="$WT_LOG_DIR/wsquashfs-integrity-update-$stamp.log"
    : > "$log"
    wsq_integrity_rotate_logs "$log" || true
    phase=extracting
    [ "$reuse_prefix" -eq 0 ] || phase=preparing
    wsq_begin_update_state "$prefix" "$game_name" "$snapshot" "$archive" "$metadata" "$log" "$phase" || {
        msgbox "$(i18n wsq_update_title)" "$(i18n wsq_update_failed "$prefix" "$log" "$(wsq_update_log_detail "$log")")"; return
    }
    if [ "$reuse_prefix" -eq 0 ]; then
    if ! wsq_update_extract "$(i18n wsq_update_title)" "$(i18n wsq_update_extract)" "$log" \
        unsquashfs -no-xattrs -percentage -d "$prefix" "$archive"; then
        msgbox "$(i18n wsq_update_title)" \
            "$(i18n wsq_update_extract_failed "$(wsq_update_log_detail "$log")" "$prefix" "$log")"
        return
    fi
    else
        printf 'Reusing existing Wine prefix without extraction: %s\n' "$prefix" >> "$log"
    fi
    wsq_update_state phase preparing || return
    if ! source_links="$(python3 "$WSQ_UPDATE_HELPER" source-save-links "$prefix" "$source" "$WSQ_SAVE_ROOT" 2>> "$log")"; then
        msgbox "$(i18n wsq_update_title)" \
            "$(i18n wsq_update_prepare_failed "$(wsq_update_log_detail "$log")" "$prefix" "$log")"
        return
    fi
    if [ -n "$source_links" ]; then
        yesno "$(i18n wsq_update_title)" \
            "$(i18n wsq_update_replace_source_links "$(wsq_display_path "$source_links")")" || return
        prepare_args+=(--replace-source-save-links)
    fi
    if ! wsq_update_run "$(i18n wsq_update_title)" "$(i18n wsq_update_copy)" "$log" \
        python3 "$WSQ_UPDATE_HELPER" prepare "$prefix" "$source" "$archive" "$WSQ_SAVE_ROOT" "$metadata" "${prepare_args[@]}"; then
        msgbox "$(i18n wsq_update_title)" \
            "$(i18n wsq_update_prepare_failed "$(wsq_update_log_detail "$log")" "$prefix" "$log")"
        return
    fi
    # Keep the autorun executable selected in the archive; review or change it after testing.
    exe_rel="$(python3 "$WSQ_UPDATE_HELPER" exe "$prefix")" || {
        msgbox "$(i18n wsq_update_title)" "$(i18n wsq_update_failed "$prefix" "$log" "$(wsq_update_log_detail "$log")")"; return
    }
    wsq_update_state phase configuring || return
    runner="$(python3 "$WSQ_UPDATE_HELPER" config "$WSQ_CONF" "$(basename "$archive")" "$(basename "$prefix")" \
        --backup-dir "$WSQ_STATE_DIR/config-backups" --preserve-existing 2>> "$log")" || {
        msgbox "$(i18n wsq_update_title)" "$(i18n wsq_update_failed "$prefix" "$log" "$(wsq_update_log_detail "$log")")"; return
    }
    wsq_update_state phase snapshotting || return
    python3 "$WSQ_HELPER" snapshot "$prefix" "$snapshot" >> "$log" 2>&1 || {
        msgbox "$(i18n wsq_update_title)" "$(i18n wsq_update_failed "$prefix" "$log" "$(wsq_update_log_detail "$log")")"; return
    }
    wsq_save_state "$prefix" "$game_name" "$snapshot" "$exe_rel" "$runner" || return
    wsq_update_state mode update archive "$archive" metadata "$metadata" phase testing update_log "$log" || return
    msgbox "$(i18n wsq_update_title)" "$(i18n wsq_update_test "$prefix")"
    wsq_request_game_launch "$prefix" || return
    wsq_restart_emulationstation_deferred || return
    exit 0
}

wsq_update_inspect_existing_save() {
    local metadata="$1" path choice idx=1
    local -a paths=() items=()
    while IFS= read -r -d '' path; do
        paths+=("$path")
        items+=("$idx" "$(wsq_path_label "$path")")
        idx=$((idx+1))
    done < <(python3 "$WSQ_UPDATE_HELPER" save-locations "$metadata")
    if [ "${#paths[@]}" -eq 0 ]; then
        msgbox "$(i18n wsq_inspect_title)" "$(i18n wsq_inspect_existing_empty)"
        return 0
    fi
    if [ "${#paths[@]}" -eq 1 ]; then
        wsq_inspect_save_destination "${paths[0]}"
        return $?
    fi
    while true; do
        choice="$(menu_select "$(i18n wsq_inspect_existing_save)" \
            "$(i18n wsq_inspect_existing_select)" "${items[@]}" back "$(i18n back)")" || return 0
        case "$choice" in ''|back|*[!0-9]*) return 0 ;; esac
        [ "$choice" -ge 1 ] && [ "$choice" -lt "$idx" ] || continue
        wsq_inspect_save_destination "${paths[$((choice-1))]}" || true
    done
}

wsq_update_review_save() {
    local metadata="$1" savedir savefiles choice legacy
    savedir="$(python3 "$WSQ_UPDATE_HELPER" value "$metadata" savedir)" || return 1
    savefiles="$(python3 "$WSQ_UPDATE_HELPER" value "$metadata" savefiles)" || return 1
    legacy="$(python3 "$WSQ_UPDATE_HELPER" legacy-summary "$metadata")" || return 1
    if [ -z "$savedir$savefiles" ] && [ -n "$legacy" ]; then
        while true; do
            choice="$(menu_select "$(i18n wsq_update_save_title)" \
                "$(i18n wsq_update_links_prompt "$(wsq_display_path "$legacy")")" \
                keep "$(i18n wsq_update_links_keep)" \
                inspect-existing "$(i18n wsq_inspect_existing_save)" \
                detect "$(i18n wsq_update_save_detect)" \
                browse "$(i18n wsq_browser_title)" \
                retry "$(i18n wsq_no_save_retry)" \
                cancel "$(i18n wsq_launch_cancel)")" || return 12
            case "$choice" in
                keep)
                    WSQ_SAVE_KIND=legacy; WSQ_SELECTED_SAVE=""; return 0 ;;
                inspect-existing) wsq_update_inspect_existing_save "$metadata" || true ;;
                detect)
                wsq_select_save_candidate "$prefix" "$snapshot" && return 0
                [ -s "$WSQ_STATE_FILE" ] || return 1 ;;
                browse) wsq_browse_save && return 0 ;;
                retry) wsq_retry_pending; return 1 ;;
                cancel) wsq_cancel_pending; return 1 ;;
            esac
        done
    fi
    if [ -z "$savedir$savefiles" ]; then
        wsq_select_save_candidate "$prefix" "$snapshot"
        return $?
    fi
    while true; do
        choice="$(menu_select "$(i18n wsq_update_save_title)" \
            "$(i18n wsq_update_save_prompt "$(wsq_display_path "SAVEDIR=$savedir  SAVEFILES=$savefiles")")" \
            keep "$(i18n wsq_update_save_keep)" \
            inspect-existing "$(i18n wsq_inspect_existing_save)" \
            inspect "$(i18n wsq_inspect_title)" \
            detect "$(i18n wsq_update_save_detect)" \
            browse "$(i18n wsq_browser_title)" \
            retry "$(i18n wsq_no_save_retry)" \
            cancel "$(i18n wsq_launch_cancel)")" || return 12
        case "$choice" in
            keep)
                WSQ_SAVE_KIND=existing; WSQ_SELECTED_SAVE="$savedir"; return 0 ;;
            inspect-existing) wsq_update_inspect_existing_save "$metadata" || true ;;
            inspect)
                local normalized
                normalized="$(python3 - "$savedir" <<'PYCODE'
import sys
print(sys.argv[1].strip().strip('"').replace('\\', '/').rstrip('/') or '.')
PYCODE
)" || continue
                wsq_inspect_folder "$normalized" || true ;;
            detect)
                wsq_select_save_candidate "$prefix" "$snapshot" && return 0
                [ -s "$WSQ_STATE_FILE" ] || return 1 ;;
            browse) wsq_browse_save && return 0 ;;
            retry) wsq_retry_pending; return 1 ;;
            cancel) wsq_cancel_pending; return 1 ;;
        esac
    done
}

wsq_update_final_choice() {
    local archive="$1" new_archive="$2" choice
    if [ "$new_archive" -eq 1 ] || { [ ! -e "$archive" ] && [ ! -L "$archive" ]; }; then
        yesno_default_no "$(i18n wsq_update_title)" \
            "$(i18n wsq_update_new_archive "$(wsq_display_path "$archive")")" || return 10
        printf replace
        return 0
    fi
    choice="$(menu_select "$(i18n wsq_update_title)" \
        "$(i18n wsq_update_final_prompt "$(wsq_display_path "$archive")")" \
        backup "$(i18n wsq_update_final_backup)" \
        replace "$(i18n wsq_update_final_replace)" \
        back "$(i18n back)")" || return 10
    case "$choice" in
        backup|replace) printf '%s' "$choice" ;;
        *) return 10 ;;
    esac
}

wsq_update_manage_save_backups() {
    local metadata="$1" log="$2" paths decision old_backup
    decision="$(python3 "$WSQ_UPDATE_HELPER" value "$metadata" save_backup_choice)" || return 1
    case "$decision" in keep|deleted) return 0 ;; esac
    if ! paths="$(python3 "$WSQ_UPDATE_HELPER" save-backups "$metadata" 2>> "$log")"; then
        msgbox "$(i18n wsq_update_title)" "$(i18n wsq_update_save_cleanup_failed "$log")"
        python3 "$WSQ_UPDATE_HELPER" keep-save-backups "$metadata" >> "$log" 2>&1
        return $?
    fi
    if [ -z "$paths" ]; then
        # Old pending manifests do not identify every backup: do not infer paths.
        old_backup="$(python3 "$WSQ_UPDATE_HELPER" value "$metadata" save_backup)"
        [ -z "$old_backup" ] || msgbox "$(i18n wsq_save_title)" "$(i18n wsq_save_backup_done "$old_backup")"
        return 0
    fi
    if yesno_default_no "$(i18n wsq_update_save_cleanup_title)" "$(i18n wsq_update_save_cleanup_body "$paths")"; then
        if ! wsq_update_run "$(i18n wsq_update_save_cleanup_title)" "$(i18n wsq_update_save_cleanup_progress)" "$log" \
            python3 "$WSQ_UPDATE_HELPER" cleanup-save-backups "$metadata"; then
            msgbox "$(i18n wsq_update_title)" "$(i18n wsq_update_save_cleanup_failed "$log")"
            python3 "$WSQ_UPDATE_HELPER" keep-save-backups "$metadata" >> "$log" 2>&1 || return 1
        fi
    else
        python3 "$WSQ_UPDATE_HELPER" keep-save-backups "$metadata" >> "$log" 2>&1 || return 1
    fi
}

wsq_resume_update() {
    # prefix/game_name/snapshot/exe_rel/runner are local to wsq_resume_build.
    local game_name="$game_name"
    local metadata phase save_rel save_kind test_save archive staged backup log original_name prepared_save final_mode="" new_archive=0
    local ready_review ready_kind skip_save_prepare=0
    local -a commit_args=()
    metadata="$(wsq_state_value metadata)"; phase="$(wsq_state_value phase)"; log="$(wsq_state_value update_log)"
    ready_review="$(wsq_state_value save_review_ready)"; ready_kind="$(wsq_state_value save_ready_kind)"
    [ -s "$metadata" ] || { msgbox "$(i18n wsq_update_title)" "$(i18n wsq_pending_invalid)"; return; }
    archive="$(python3 "$WSQ_UPDATE_HELPER" value "$metadata" archive)" || return
    [ "$(python3 "$WSQ_UPDATE_HELPER" value "$metadata" archive_signature)" != None ] || new_archive=1
    if [ ! -e "$archive" ] && [ ! -L "$archive" ]; then new_archive=1; fi
    test_save="$(python3 "$WSQ_UPDATE_HELPER" value "$metadata" test_save)" || return
    original_name="$game_name"
    game_name="$(basename "$prefix" .wine).validated"
    prepared_save="$WSQ_SAVE_ROOT/$game_name"
    if [ "$(python3 "$WSQ_UPDATE_HELPER" value "$metadata" committed)" = True ]; then
        phase=committed
        wsq_update_state phase committed archive_backup "$(python3 "$WSQ_UPDATE_HELPER" value "$metadata" archive_backup)" || return
    fi
    if [ "$phase" != ready ] && [ "$phase" != committed ]; then
        # wsq_resume_build has already validated the game launch at this point.
        if ! wsq_update_run "$(i18n wsq_update_title)" "$(i18n wsq_update_remove_old)" "$log" \
            python3 "$WSQ_UPDATE_HELPER" finish-game "$metadata"; then
            msgbox "$(i18n wsq_update_title)" "$(i18n wsq_update_failed "$prefix" "$log" "$(wsq_update_log_detail "$log")")"; return
        fi
        while true; do
            wsq_update_review_save "$metadata" || return $?
            save_kind="$WSQ_SAVE_KIND"; save_rel="$WSQ_SELECTED_SAVE"
            # Choose the archive action before save transfers or detachment:
            # Back can then revisit save review without replaying mutations.
            final_mode="$(wsq_update_final_choice "$archive" "$new_archive")" || continue
            if [ "$ready_review" = 1 ] && [ "$save_kind" = "$ready_kind" ] &&
               { [ "$save_kind" = existing ] || [ "$save_kind" = legacy ]; }; then
                skip_save_prepare=1
                break
            fi
            case "$save_kind" in
                legacy)
                    python3 "$WSQ_UPDATE_HELPER" stage-legacy "$metadata" >> "$log" 2>&1 || return
                    python3 "$WSQ_UPDATE_HELPER" restore-legacy "$metadata" >> "$log" 2>&1 || return
                    ;;
                existing)
                    python3 "$WSQ_UPDATE_HELPER" restore-save-rules "$metadata" >> "$log" 2>&1 || return
                    python3 "$WSQ_UPDATE_HELPER" stage-legacy "$metadata" >> "$log" 2>&1 || return
                    # A test uses its own copy; never empty existing saves because
                    # the new version failed to produce any data.
                    if [ -d "$test_save" ] && find "$test_save" -mindepth 1 -print -quit | grep -q .; then
                        wsq_save_destination_prepare "$WSQ_SAVE_ROOT/$game_name"
                        local destination_rc=$?
                        [ "$destination_rc" -ne 10 ] || continue
                        [ "$destination_rc" -eq 0 ] || return "$destination_rc"
                        python3 "$WSQ_UPDATE_HELPER" copy-test "$metadata" "$WSQ_SAVE_ROOT/$game_name" >> "$log" 2>&1 || return
                    fi ;;
                registry)
                    wsq_copy_registry_save
                    local registry_rc=$?
                    [ "$registry_rc" -ne 10 ] || continue
                    [ "$registry_rc" -eq 0 ] || return "$registry_rc"
                    python3 "$WSQ_UPDATE_HELPER" autorun "$prefix" "$exe_rel" --savedir . --savefiles user.reg >> "$log" 2>&1 || return ;;
                directory)
                    yesno_default_no "$(i18n wsq_update_save_title)" \
                        "$(i18n wsq_save_confirm "$(wsq_display_path "$save_rel")" "$(wsq_display_path "$WSQ_SAVE_ROOT/$game_name")")" || continue
                    wsq_move_save_data "$prefix" "$save_rel" "$game_name"
                    local save_rc=$?
                    [ "$save_rc" -ne 10 ] || continue
                    [ "$save_rc" -eq 0 ] || return "$save_rc"
                    wsq_cleanup_internal_savedir "$prefix" "$save_rel" || return
                    python3 "$WSQ_UPDATE_HELPER" autorun "$prefix" "$exe_rel" --savedir "${save_rel%/}/" >> "$log" 2>&1 || return ;;
                *) return ;;
            esac
            break
        done
        if [ "$skip_save_prepare" -eq 0 ] && [ "$save_kind" != legacy ]; then
        python3 "$WSQ_UPDATE_HELPER" restore-scripts "$metadata" >> "$log" 2>&1 || return
        python3 "$WSQ_UPDATE_HELPER" detach "$prefix" "$test_save" >> "$log" 2>&1 || {
            msgbox "$(i18n wsq_update_title)" "$(i18n wsq_update_failed "$prefix" "$log" "$(wsq_update_log_detail "$log")")"; return
        }
        if [ "$save_kind" = existing ]; then
            python3 "$WSQ_UPDATE_HELPER" restore-custom "$metadata" >> "$log" 2>&1 || return
        fi
        fi
        if [ -n "${WSQ_LAST_SAVE_BACKUP:-}" ]; then
            msgbox "$(i18n wsq_save_title)" "$(i18n wsq_save_backup_done "$WSQ_LAST_SAVE_BACKUP")"
        fi
        wsq_update_state phase ready save_ready_kind "$save_kind" save_review_ready 0 || return
    fi
    if [ "$phase" != committed ]; then
    if [ -z "$final_mode" ]; then
        final_mode="$(wsq_update_final_choice "$archive" "$new_archive")" || {
            # Keep the prepared copy. Re-selecting the same existing rules does
            # not repeat transfers; selecting a new location uses normal review.
            wsq_update_state phase configuring save_review_ready 1 || return
            game_name="$original_name"
            return 13
        }
    fi
    [ "$final_mode" != replace ] || commit_args+=(--replace)
    staged="$archive.update-tmp-$$"
    if ! maintenance_squash_wine "$prefix" "$staged" ask-full "$log"; then
        msgbox "$(i18n wsq_update_title)" "$(i18n wsq_update_failed "$prefix" "$log" "$(wsq_update_log_detail "$log")")"; return
    fi
    [ ! -d "$prepared_save" ] || commit_args+=(--prepared-save "$prepared_save")
    if ! wsq_update_run "$(i18n wsq_update_title)" "$(i18n wsq_update_finalizing)" "$log" \
        python3 "$WSQ_UPDATE_HELPER" commit "$metadata" "$staged" "${commit_args[@]}"; then
        msgbox "$(i18n wsq_update_title)" "$(i18n wsq_update_failed "$prefix" "$log" "$(wsq_update_log_detail "$log")")"; return
    fi
    backup="$(python3 "$WSQ_UPDATE_HELPER" value "$metadata" archive_backup)" || return
    wsq_update_state phase committed archive_backup "$backup" || return
    else
        backup="$(wsq_state_value archive_backup)"
    fi
    python3 "$WSQ_UPDATE_HELPER" config "$WSQ_CONF" "$(basename "$prefix")" "$(basename "$archive")" \
        --backup-dir "$WSQ_STATE_DIR/config-backups" >> "$log" 2>&1 || {
        msgbox "$(i18n wsq_update_title)" "$(i18n wsq_runner_finalize_failed "$archive")"; return
    }
    python3 "$WSQ_UPDATE_HELPER" cleanup-test "$metadata" >> "$log" 2>&1 || {
        msgbox "$(i18n wsq_update_title)" "$(i18n wsq_update_failed "$prefix" "$log" "$(wsq_update_log_detail "$log")")"; return
    }
    python3 "$WSQ_UPDATE_HELPER" cleanup-bottles \
        "/userdata/system/wine-bottles/windows" "$(basename "$archive")" >> "$log" 2>&1 || {
        msgbox "$(i18n wsq_update_title)" "$(i18n wsq_update_bottles_cleanup_failed "$log")"
        return
    }
    wsq_update_manage_save_backups "$metadata" "$log" || return 1
    maintenance_offer_source_deletion "$prefix" "$log" 0 || return 1
    rm -f -- "$snapshot" "$WSQ_STATE_FILE" "$metadata" "$WSQ_STATE_DIR/wsq-launch-result"
    local completed_prefix="$prefix"
    [ -d "$prefix" ] || completed_prefix="$(i18n squash_delete_source_done "$(basename "$prefix")")"
    if [ "$new_archive" -eq 1 ]; then
        msgbox "$(i18n wsq_update_title)" "$(i18n wsq_update_done_new "$archive" "$completed_prefix")"
    elif [ -n "$backup" ]; then
        msgbox "$(i18n wsq_update_title)" "$(i18n wsq_update_done "$archive" "$backup" "$completed_prefix")"
    else
        msgbox "$(i18n wsq_update_title)" "$(i18n wsq_update_done_replace "$archive" "$completed_prefix")"
    fi
    wsq_restart_emulationstation_deferred || true
    game_name="$original_name"
    wsq_post_build_menu update
}
