#!/bin/bash

WSQ_WINDOWS_DIR="/userdata/roms/windows"
WSQ_TEMPLATES_DIR="$WT_HOME/templates"
WSQ_STATE_DIR="$WT_HOME/state"
WSQ_STATE_FILE="$WSQ_STATE_DIR/wsquashfs-builder.json"
WSQ_HELPER="$WT_ROOT/helpers/wsquashfs_builder.py"
WSQ_SAVE_ROOT="/userdata/saves/windows"
WSQ_CONF="/userdata/system/batocera.conf"
source "$WT_ROOT/modules/wsquashfs-update.sh"
source "$WT_ROOT/modules/wsquashfs-dotnet.sh"

wsq_list_templates() {
    [ -d "$WSQ_TEMPLATES_DIR" ] || return 0
    find "$WSQ_TEMPLATES_DIR" -maxdepth 1 -type f \
        \( -iname '*.prefix' -o -iname '*.wsquashfs' \) -print 2>/dev/null | sort -f
}

wsq_source_folder_visible() {
    local name="$1"
    case "$name" in .*) return 1 ;; esac
    # Exact folder names, ignoring case: do not hide games such as
    # "Video Game.wine" merely because their name contains a media keyword.
    case "${name,,}" in
        media|medias|médias|image|images|video|videos|vidéos|manual|manuals|\
        music|musiques|marquee|marquees|thumbnail|thumbnails|\
        screenshot|screenshots|fanart|fanarts|boxart|boxarts|\
        boxback|boxbacks|wheel|wheels|mix|mixes|titleshot|titleshots|\
        cover|covers|snap|snaps|downloaded_images|downloaded_videos)
            return 1 ;;
    esac
    return 0
}

wsq_select_source_game() {
    local -a items=()
    local rows="" path base idx=1 choice

    [ -d "$WSQ_WINDOWS_DIR" ] || {
        msgbox "$(i18n wsq_create_title)" "$(i18n wsq_windows_missing "$WSQ_WINDOWS_DIR")"
        return 1
    }

    while IFS= read -r path; do
        [ -d "$path" ] || continue
        [ -L "$path" ] && continue
        base="$(basename "$path")"
        wsq_source_folder_visible "$base" || continue

        items+=("$idx" "$base")
        rows+="$path"$'\n'
        idx=$((idx+1))
    done < <(find "$WSQ_WINDOWS_DIR" -mindepth 1 -maxdepth 1 -type d -print 2>/dev/null | sort -f)

    if [ "${#items[@]}" -eq 0 ]; then
        msgbox "$(i18n wsq_create_title)" "$(i18n wsq_no_source_games "$WSQ_WINDOWS_DIR")"
        return 1
    fi

    choice="$(menu_select "$(i18n wsq_create_title)" "$(i18n wsq_credit)\n\n$(i18n wsq_create_purpose)\n\n$(i18n wsq_version_warning)\n\n$(i18n wsq_source_prompt)" "${items[@]}")" || return 1
    sed -n "${choice}p" <<< "$rows"
}

WSQ_PREFIX_CATALOG_URL="https://raw.githubusercontent.com/Thomson67/batocera-wine-runners/main/prefixes.json"
WSQ_SELECTED_TEMPLATE=""

wsq_default_template_metadata() {
    local catalog_tmp
    catalog_tmp="$(mktemp /tmp/uwt-prefix-catalog.XXXXXX)" || return 1

    if ! download_file "$WSQ_PREFIX_CATALOG_URL" "$catalog_tmp" >/dev/null 2>&1; then
        rm -f -- "$catalog_tmp"
        return 2
    fi

    python3 - "$catalog_tmp" <<'PY'
import json
import os
import sys

path=sys.argv[1]
try:
    with open(path, encoding="utf-8") as f:
        data=json.load(f)
except Exception:
    raise SystemExit(2)

entries=[x for x in data.get("prefixes", []) if x.get("default") is True]
if len(entries) != 1:
    raise SystemExit(3)

x=entries[0]
required=("name","version","file","size_bytes","download_url","sha256")
if any(k not in x for k in required):
    raise SystemExit(4)

filename=str(x["file"])
if not filename or filename != os.path.basename(filename):
    raise SystemExit(5)

sha=str(x["sha256"]).lower()
if len(sha) != 64:
    raise SystemExit(6)
try:
    int(sha, 16)
except ValueError:
    raise SystemExit(6)

try:
    size=int(x["size_bytes"])
except Exception:
    raise SystemExit(7)
if size <= 0:
    raise SystemExit(7)

for value in (x["name"], x["version"], filename, size, x["download_url"], sha):
    print(value)
PY
    local rc=$?
    rm -f -- "$catalog_tmp"
    return "$rc"
}

wsq_template_terminal_notice() {
    local body="$1"

    # wsq_select_template is called inside command substitution:
    #   template="$(wsq_select_template)"
    # Never write interactive UI to stdout here, otherwise it is captured as
    # part of the selected template path and the terminal appears blank.
    if [ -r /dev/tty ] && [ -w /dev/tty ]; then
        wt_clear_tty
        {
            printf '==== %s ====\n\n' "$(i18n wsq_templates_download_title)"
            printf '%b\n\n' "$body"
            printf '%s' "$(i18n press_enter)"
        } > /dev/tty
        read -r _ < /dev/tty
        wt_clear_tty
    else
        printf '==== %s ====\n\n%b\n\n%s' \
            "$(i18n wsq_templates_download_title)" "$body" "$(i18n press_enter)" >&2
        read -r _
    fi
}

wsq_install_default_template() {
    local -a meta=()
    local name version filename size url sha size_human free_bytes free_human dest tmp actual_size actual_sha

    while IFS= read -r line; do
        meta+=("$line")
    done < <(wsq_default_template_metadata)

    [ "${#meta[@]}" -eq 6 ] || {
        wsq_template_terminal_notice "$(i18n wsq_template_catalog_failed)"
        return 1
    }

    name="${meta[0]}"
    version="${meta[1]}"
    filename="${meta[2]}"
    size="${meta[3]}"
    url="${meta[4]}"
    sha="${meta[5]}"
    size_human="$(human_bytes "$size")"

    free_bytes="$(df -Pk "$WT_HOME" 2>/dev/null | awk 'NR==2 {print $4 * 1024}' | cut -d. -f1)"
    case "$free_bytes" in ''|*[!0-9]*) free_bytes=0 ;; esac
    free_human="$(human_bytes "$free_bytes")"

    local download_choice
    download_choice="$(menu_select "$(i18n wsq_templates_download_title)" \
        "$(i18n wsq_templates_download_prompt "$name" "$version" "$size_human" "$WSQ_TEMPLATES_DIR" "$free_human")" \
        "1" "$(i18n yes)" \
        "0" "$(i18n no)")" || return 1
    [ "$download_choice" = "1" ] || return 1

    if [ "$free_bytes" -gt 0 ] && [ "$free_bytes" -lt "$size" ]; then
        wsq_template_terminal_notice "$(i18n wsq_template_no_space "$size_human" "$free_human")"
        return 1
    fi

    mkdir -p "$WSQ_TEMPLATES_DIR" || {
        wsq_template_terminal_notice "$(i18n wsq_template_dir_failed "$WSQ_TEMPLATES_DIR")"
        return 1
    }

    dest="$WSQ_TEMPLATES_DIR/$filename"
    tmp="$dest.download-$$"
    rm -f -- "$tmp"

    if [ -w /dev/tty ]; then
        wt_clear_tty
        {
            printf '==== %s ====\n\n' "$(i18n wsq_templates_download_title)"
            printf '%b\n\n' "$(i18n wsq_template_downloading "$name" "$size_human")"
        } > /dev/tty
    fi

    if ! download_file "$url" "$tmp" 2>/dev/tty; then
        rm -f -- "$tmp"
        wsq_template_terminal_notice "$(i18n wsq_template_download_failed)"
        return 1
    fi

    actual_size="$(wc -c < "$tmp" 2>/dev/null | tr -d '[:space:]')"
    if [ "$actual_size" != "$size" ]; then
        rm -f -- "$tmp"
        wsq_template_terminal_notice "$(i18n wsq_template_size_failed "$size" "$actual_size")"
        return 1
    fi

    actual_sha="$(sha256sum "$tmp" 2>/dev/null | awk '{print $1}')"
    if [ "$actual_sha" != "$sha" ]; then
        rm -f -- "$tmp"
        wsq_template_terminal_notice "$(i18n wsq_template_checksum_failed)"
        return 1
    fi

    if ! mv -f -- "$tmp" "$dest"; then
        rm -f -- "$tmp"
        wsq_template_terminal_notice "$(i18n wsq_template_install_failed)"
        return 1
    fi

    wt_log "WSquashFS: default prefix template installed: $dest ($size_human, version $version)"
    return 0
}

wsq_select_template() {
    local -a items=()
    local rows="" path idx=1 choice

    WSQ_SELECTED_TEMPLATE=""

    while IFS= read -r path; do
        [ -n "$path" ] || continue
        items+=("$idx" "$(basename "$path")")
        rows+="$path"$'\n'
        idx=$((idx+1))
    done < <(wsq_list_templates)

    if [ "${#items[@]}" -eq 0 ]; then
        wsq_install_default_template || return 1

        items=()
        rows=""
        idx=1
        while IFS= read -r path; do
            [ -n "$path" ] || continue
            items+=("$idx" "$(basename "$path")")
            rows+="$path"$'\n'
            idx=$((idx+1))
        done < <(wsq_list_templates)

        [ "${#items[@]}" -gt 0 ] || {
            wsq_template_terminal_notice "$(i18n wsq_templates_none "$WSQ_TEMPLATES_DIR")"
            return 1
        }
    fi

    choice="$(menu_select "$(i18n wsq_templates_title)" "$(i18n wsq_templates_prompt)" "${items[@]}")" || return 1
    WSQ_SELECTED_TEMPLATE="$(sed -n "${choice}p" <<< "$rows")"
    [ -n "$WSQ_SELECTED_TEMPLATE" ]
}

wsq_clean_name() {
    local name="$1"
    python3 "$WSQ_HELPER" clean-name "$name"
}

wsq_prepare_prefix() {
    local source="$1" template="$2" game_name="$3" target="$4"
    local tmp parent
    parent="$(dirname "$target")"
    tmp="$parent/.uwt-prefix-$$"

    [ ! -e "$target" ] || return 2
    rm -rf -- "$tmp"

    if ! unsquashfs -f -q -no-xattrs -d "$tmp" "$template"; then
        rm -rf -- "$tmp"
        return 3
    fi

    [ -d "$tmp/drive_c" ] || {
        rm -rf -- "$tmp"
        return 4
    }

    if ! mv -- "$tmp" "$target"; then
        rm -rf -- "$tmp"
        return 5
    fi

    mkdir -p "$target/drive_c/game" "$target/drive_c/users/steamuser"

    local item base
    shopt -s dotglob nullglob
    for item in "$source"/*; do
        base="$(basename "$item")"
        [ "$item" = "$target" ] && continue
        if ! mv -- "$item" "$target/drive_c/game/"; then
            # All game items already moved came from this source directory and
            # drive_c/game was created empty above. Roll them back using
            # same-filesystem renames so a partial preparation does not split
            # a very large game between two locations.
            local rollback
            for rollback in "$target/drive_c/game"/*; do
                mv -- "$rollback" "$source/" 2>/dev/null || true
            done
            shopt -u dotglob nullglob
            rm -rf -- "$target"
            return 6
        fi
    done
    shopt -u dotglob nullglob

    rmdir "$source" 2>/dev/null || true

    if [ -e "$target/drive_c/users/root" ] || [ -L "$target/drive_c/users/root" ]; then
        if [ -L "$target/drive_c/users/root" ]; then
            rm -f -- "$target/drive_c/users/root"
        elif [ -d "$target/drive_c/users/root" ]; then
            rm -rf -- "$target/drive_c/users/root"
        else
            rm -f -- "$target/drive_c/users/root"
        fi
    fi
    ln -s steamuser "$target/drive_c/users/root"
}

wsq_select_executable() {
    local prefix="$1" game_dir="${2:-drive_c}"
    local -a items=()
    local rows="" line score rel idx=1 choice
    while IFS=$'\t' read -r score rel; do
        [ -n "$rel" ] || continue
        items+=("$idx" "[$score] $rel")
        rows+="$rel"$'\n'
        idx=$((idx+1))
    done < <(python3 "$WSQ_HELPER" exes "$prefix" --game-dir "$game_dir")

    if [ "${#items[@]}" -eq 0 ]; then
        msgbox "$(i18n wsq_create_title)" "$(i18n wsq_no_executable "$game_dir")"
        return 1
    fi

    choice="$(menu_select "$(i18n wsq_executable_title)" "$(i18n wsq_executable_prompt)" "${items[@]}")" || return 1
    sed -n "${choice}p" <<< "$rows"
}

wsq_write_autorun() {
    local prefix="$1" exe_rel="$2" savedir="${3:-}" savefiles="${4:-}"
    local exe_dir exe_name tmp
    exe_dir="$(dirname "$exe_rel")"
    exe_name="$(basename "$exe_rel")"
    [ "$exe_dir" = "." ] && exe_dir=""

    tmp="$prefix/autorun.cmd.uwt-tmp"
    {
        [ -n "$savedir" ] && printf 'SAVEDIR=%s/\n' "${savedir%/}"
        [ -n "$savefiles" ] && printf 'SAVEFILES=%s\n' "$savefiles"
        printf 'DIR=%s\n' "$exe_dir"
        printf 'CMD="%s"\n' "$exe_name"
    } > "$tmp"
    # Preserve ENV settings when final save configuration rewrites autorun.
    if [ -f "$prefix/autorun.cmd" ]; then
        python3 "$WT_ROOT/helpers/autorun_env.py" copy "$prefix/autorun.cmd" "$tmp" || { rm -f -- "$tmp"; return 1; }
    fi
    mv -f -- "$tmp" "$prefix/autorun.cmd"
}

wsq_runner_candidates() {
    local path name
    printf 'system\t__SYSTEM__\n'
    if [ -d "/userdata/system/wine/custom" ]; then
        while IFS= read -r path; do
            [ -d "$path" ] || continue
            name="$(basename "$path")"
            case "$name" in
                *-UMU|*-umu) printf 'umu\t%s\n' "$name" ;;
            esac
        done < <(find /userdata/system/wine/custom -mindepth 1 -maxdepth 1 -type d -print 2>/dev/null | sort -f)
    fi
    if [ -d "/userdata/system/wine/custom" ]; then
        while IFS= read -r path; do
            [ -d "$path" ] || continue
            name="$(basename "$path")"
            case "$name" in
                *-UMU|*-umu) continue ;;
            esac
            printf 'custom\t%s\n' "$name"
        done < <(find /userdata/system/wine/custom -mindepth 1 -maxdepth 1 -type d -print 2>/dev/null | sort -f)
    fi
}

wsq_select_runner() {
    local -a items=()
    local rows="" kind name idx=1 choice label
    while IFS=$'\t' read -r kind name; do
        [ -n "$name" ] || continue
        if [ "$name" = "__SYSTEM__" ]; then
            label="$(i18n wsq_runner_system)"
        elif [ "$kind" = "umu" ]; then
            label="$name  [UMU]"
        else
            label="$name"
        fi
        items+=("$idx" "$label")
        rows+="$name"$'\n'
        idx=$((idx+1))
    done < <(wsq_runner_candidates)

    choice="$(menu_select "$(i18n wsq_runner_title)" "$(i18n wsq_runner_prompt)" "${items[@]}")" || return 1
    sed -n "${choice}p" <<< "$rows"
}

wsq_set_runner_config() {
    local rom_name="$1" runner="$2"
    python3 - "$WSQ_CONF" "$rom_name" "$runner" <<'PY'
import os
import sys

conf, rom_name, runner = sys.argv[1:4]
os.makedirs(os.path.dirname(conf), exist_ok=True)
if not os.path.exists(conf):
    open(conf, "a", encoding="utf-8").close()

safe_name=rom_name.replace("=", "").replace("#", "")
canonical_prefix = f'windows["{safe_name}"].wine-runner='

with open(conf, "r", encoding="utf-8", errors="surrogateescape") as f:
    lines=f.readlines()

def keep_line(line):
    stripped=line.lstrip()
    return not stripped.startswith(canonical_prefix)

lines=[line for line in lines if keep_line(line)]

if runner != "__SYSTEM__":
    if lines and not lines[-1].endswith("\n"):
        lines[-1]+="\n"
    if lines and lines[-1].strip():
        lines.append("\n")
    lines.append(canonical_prefix + runner + "\n")

tmp=conf+".uwt-wsq"
with open(tmp, "w", encoding="utf-8", errors="surrogateescape") as f:
    f.writelines(lines)
os.replace(tmp, conf)
PY
}

wsq_finalize_runner_config() {
    local game_name="$1" runner="$2"
    local final_rom="${game_name}.wsquashfs"
    wsq_set_runner_config "$final_rom" "$runner" || return 1
    if [ -n "${3:-}" ]; then
        python3 "$WT_ROOT/helpers/wsquashfs_options.py" copy "$WSQ_CONF" "$(basename "$3")" "$final_rom"
    fi
}

wsq_save_state() {
    local prefix="$1" game_name="$2" snapshot="$3" exe_rel="$4" runner="$5"
    mkdir -p "$WSQ_STATE_DIR"
    python3 - "$WSQ_STATE_FILE" "$prefix" "$game_name" "$snapshot" "$exe_rel" "$runner" <<'PY'
import json, sys
path, prefix, game, snapshot, exe, runner = sys.argv[1:7]
data = {}
try:
    with open(path, encoding="utf-8") as f:
        old = json.load(f)
    if old.get("prefix") == prefix and old.get("mode") == "update":
        data = old
except (OSError, ValueError):
    pass
data.update({
        "mode": data.get("mode", "create"),
        "phase": data.get("phase", "testing"),
        "prefix": prefix,
        "game_name": game,
        "snapshot": snapshot,
        "exe_rel": exe,
        "runner": runner,
    })
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
PY
}

wsq_state_value() {
    local key="$1"
    python3 - "$WSQ_STATE_FILE" "$key" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    data=json.load(f)
print(data.get(sys.argv[2], ""))
PY
}

wsq_refresh_emulationstation_games() {
    local url="http://127.0.0.1:1234/reloadgames"

    if command -v curl >/dev/null 2>&1; then
        curl -fsS --max-time 5 "$url" >/dev/null 2>&1 && return 0
    elif command -v wget >/dev/null 2>&1; then
        wget -q -T 5 -O /dev/null "$url" >/dev/null 2>&1 && return 0
    fi

    wt_log "WSquashFS: unable to request EmulationStation gamelist reload via $url"
    return 1
}

wsq_restart_emulationstation_deferred() {
    mkdir -p "$WSQ_STATE_DIR"
    : > "$WSQ_STATE_DIR/restart-es.request"
    return 0
}

wsq_request_game_launch() {
    local rom="$1"
    python3 "$WSQ_UPDATE_HELPER" profiles "$rom" >> "${WT_SESSION_LOG:-/dev/null}" 2>&1 || return 1
    mkdir -p "$WSQ_STATE_DIR"
    rm -f -- "$WSQ_STATE_DIR/wsq-launch-result"
    printf '%s\n' "$rom" > "$WSQ_STATE_DIR/launch-game.request"
    return 0
}

wsq_create_new() {
    wsq_pending_guard || return
    local source template raw_name game_name target exe_rel runner snapshot rom_name
    command -v unsquashfs >/dev/null 2>&1 || {
        msgbox "$(i18n wsq_create_title)" "$(i18n squash_tools_missing)"
        return
    }

    source="$(wsq_select_source_game)" || return
    [ -d "$source" ] || {
        msgbox "$(i18n wsq_create_title)" "$(i18n wsq_source_invalid "$source")"
        return
    }

    source="$(readlink -f -- "$source" 2>/dev/null || printf '%s' "$source")"
    local windows_root
    windows_root="$(readlink -f -- "$WSQ_WINDOWS_DIR" 2>/dev/null || printf '%s' "$WSQ_WINDOWS_DIR")"

    if [ "$source" = "$windows_root" ]; then
        msgbox "$(i18n wsq_create_title)" "$(i18n wsq_source_root_forbidden "$source")"
        return
    fi

    if [[ "$(basename "$source")" == *.wine ]]; then
        target="$source"
        raw_name="$(basename "$source")"
        raw_name="${raw_name%.wine}"
        game_name="$(wsq_clean_name "$raw_name")"
        [ -n "$game_name" ] || game_name="$raw_name"

        [ -d "$target/drive_c" ] || {
            msgbox "$(i18n wsq_create_title)" "$(i18n wsq_wine_invalid "$target")"
            return
        }
    else
        if find "$source" -mindepth 1 -maxdepth 1 \
            \( -type d \( -iname '*.wine' -o -iname '*.pc' \) -o -type f -iname '*.wsquashfs' \) \
            -print -quit 2>/dev/null | grep -q .; then
            msgbox "$(i18n wsq_create_title)" "$(i18n wsq_source_contains_games "$source")"
            return
        fi

        wsq_select_template || return
        template="$WSQ_SELECTED_TEMPLATE"
        raw_name="$(basename "$source")"
        raw_name="${raw_name%.pc}"
        game_name="$(wsq_clean_name "$raw_name")"
        [ -n "$game_name" ] || game_name="$raw_name"
        target="$(dirname "$source")/$game_name.wine"

        [ ! -e "$target" ] || {
            msgbox "$(i18n wsq_create_title)" "$(i18n wsq_target_exists "$target")"
            return
        }

        yesno_default_no "$(i18n wsq_create_title)" \
            "$(i18n wsq_move_confirm "$source" "$template" "$target")" || return

        if ! wsq_prepare_prefix "$source" "$template" "$game_name" "$target"; then
            msgbox "$(i18n wsq_create_title)" "$(i18n wsq_prepare_failed "$target")"
            return
        fi
    fi

    exe_rel="$(wsq_select_executable "$target")" || {
        msgbox "$(i18n wsq_create_title)" "$(i18n wsq_prefix_kept "$target")"
        return
    }
    wsq_write_autorun "$target" "$exe_rel"

    runner="$(wsq_select_runner)" || {
        msgbox "$(i18n wsq_create_title)" "$(i18n wsq_prefix_kept "$target")"
        return
    }

    rom_name="$(basename "$target")"
    wsq_set_runner_config "$rom_name" "$runner" || {
        msgbox "$(i18n wsq_create_title)" "$(i18n wsq_runner_config_failed)"
        return
    }

    mkdir -p "$WSQ_STATE_DIR"
    snapshot="$WSQ_STATE_DIR/wsquashfs-before-$$.json"
    if ! python3 "$WSQ_HELPER" snapshot "$target" "$snapshot"; then
        msgbox "$(i18n wsq_create_title)" "$(i18n wsq_snapshot_failed)"
        return
    fi

    wsq_save_state "$target" "$game_name" "$snapshot" "$exe_rel" "$runner"

    msgbox "$(i18n wsq_create_title)" \
        "$(i18n wsq_test_ready "$target" "$rom_name")"

    wsq_request_game_launch "$target" || true
    wsq_restart_emulationstation_deferred || true
    exit 0
}

wsq_recover_invalid_pending() {
    local choice
    choice="$(menu_select "$(i18n wsq_resume_title)" "$(i18n wsq_pending_invalid)" \
        cancel "$(i18n cancel)" back "$(i18n back)")" || return 1
    [ "$choice" = cancel ] || return 1
    # Discard only toolbox state, never the archive, saves or working files.
    rm -f -- "$WSQ_STATE_FILE" "$WSQ_STATE_DIR/wsq-launch-result" \
        "$WSQ_STATE_DIR/launch-game.request" "$WSQ_STATE_DIR/resume-wsq.request" \
        "$WSQ_STATE_DIR/restart-es.request"
}

wsq_abandon_pending() {
    local prefix="$1"
    rm -f -- "$WSQ_STATE_FILE" "$WSQ_STATE_DIR/wsq-launch-result" \
        "$WSQ_STATE_DIR/launch-game.request" "$WSQ_STATE_DIR/resume-wsq.request" \
        "$WSQ_STATE_DIR/restart-es.request"
    msgbox "$(i18n wsq_resume_title)" "$(i18n wsq_pending_abandoned "$prefix")"
}

wsq_cancel_pending() {
    rm -f -- "$snapshot" "$WSQ_STATE_FILE" "$WSQ_STATE_DIR/wsq-launch-result"
    msgbox "$(i18n wsq_resume_title)" "$(i18n wsq_prefix_kept "$prefix")"
}

wsq_retry_pending() {
    wsq_request_game_launch "$prefix" || return 1
    wsq_restart_emulationstation_deferred || return 1
    exit 0
}

wsq_display_path() {
    # Presentation only: the real path is never modified.
    python3 - "$1" <<'PY'
import sys, textwrap
print(textwrap.fill(sys.argv[1], width=72, break_long_words=True,
                    break_on_hyphens=False, replace_whitespace=False))
PY
}

wsq_path_label() {
    # dialog menu rows cannot wrap; keep a readable suffix, then show the full
    # wrapped path in the candidate review and save confirmation prompts.
    python3 - "$1" <<'PY'
import sys
path = sys.argv[1]
print(path if len(path) <= 58 else "…/" + path[-55:])
PY
}

wsq_inspect_folder() {
    local folder="$1" listing rc
    listing="$(mktemp /tmp/uwt-save-inspect.XXXXXX)" || return 1
    printf '%b\n\n' "$(i18n wsq_inspect_header)" > "$listing"
    if ! python3 "$WSQ_HELPER" inspect "$prefix" "$folder" --save-root "$WSQ_SAVE_ROOT" >> "$listing" 2>&1; then
        rm -f -- "$listing"
        msgbox "$(i18n wsq_inspect_title)" "$(i18n wsq_browser_invalid)"
        return 1
    fi
    if have_dialog; then
        wt_clear_tty
        dialog --clear --no-shadow --exit-label "$(i18n back)"             --title "$(i18n wsq_inspect_title)" --textbox "$listing" 24 100
        rc=$?
        wt_clear_tty
    else
        cat "$listing"
        read -r -p "$(i18n press_enter)" _
        rc=$?
    fi
    rm -f -- "$listing"
    return "$rc"
}

wsq_review_save_candidate() {
    local candidate="$1" choice
    while true; do
        choice="$(menu_select "$(i18n wsq_save_title)" \
            "$(i18n wsq_candidate_prompt "$(wsq_display_path "$prefix/$candidate")")" \
            "select" "$(i18n wsq_browser_select)" \
            "inspect" "$(i18n wsq_inspect_title)" \
            "browse" "$(i18n wsq_browser_title)" \
            "terminal" "$(i18n wsq_browser_terminal)" \
            "back" "$(i18n back)")" || return 1
        case "$choice" in
            select)
                WSQ_SELECTED_SAVE="$candidate"
                WSQ_SAVE_KIND="directory"
                return 0 ;;
            inspect) wsq_inspect_folder "$candidate" || true ;;
            browse) wsq_browse_save && return 0 ;;
            terminal) wsq_browse_save terminal && return 0 ;;
            back) return 1 ;;
        esac
    done
}

wsq_browse_save() {
    if [ "${1:-}" = terminal ] || ! command -v yad >/dev/null 2>&1; then
        wsq_browse_save_terminal
        return $?
    fi
    local selected validated rc screen_width="" screen_height="" resolution
    local browser_width=1000 browser_height=700
    # Prefer the active Wayland output; fall back to X11 screen geometry.
    if command -v wlr-randr >/dev/null 2>&1; then
        resolution="$(wlr-randr 2>/dev/null | awk '/current/ && match($0, /[0-9]+x[0-9]+/) { print substr($0, RSTART, RLENGTH); exit }')"
    fi
    if [ -z "${resolution:-}" ] && command -v xdpyinfo >/dev/null 2>&1; then
        resolution="$(xdpyinfo 2>/dev/null | awk '/dimensions:/ {print $2; exit}')"
    fi
    if [[ "${resolution:-}" =~ ^([0-9]+)x([0-9]+)$ ]]; then
        screen_width="${BASH_REMATCH[1]}"
        screen_height="${BASH_REMATCH[2]}"
        ((screen_width > 100)) && ((browser_width > screen_width - 80)) && browser_width=$((screen_width - 80))
        ((screen_height > 100)) && ((browser_height > screen_height - 80)) && browser_height=$((screen_height - 80))
    fi
    while true; do
        selected="$(DISPLAY="${DISPLAY:-:0}" LANGUAGE="$WT_LANGUAGE" yad \
            --file-selection --directory --filename="$prefix/" \
            --title="$(i18n wsq_browser_title)" --width="$browser_width" --height="$browser_height")"
        rc=$?
        case "$rc" in
            0) ;;
            1|252) return 1 ;;
            *)
                wt_log "WSquashFS: YAD folder selection failed (rc=$rc); using terminal browser"
                msgbox "$(i18n wsq_browser_title)" "$(i18n wsq_browser_graphical_failed)"
                wsq_browse_save_terminal
                return $? ;;
        esac
        validated="$(python3 "$WSQ_HELPER" validate-save "$prefix" "$selected" "$exe_rel" --save-root "$WSQ_SAVE_ROOT" 2>/dev/null)" || {
            msgbox "$(i18n wsq_browser_title)" "$(i18n wsq_browser_invalid)"
            continue
        }
        WSQ_SELECTED_SAVE="$validated"
        WSQ_SAVE_KIND=directory
        return 0
    done
}

wsq_browse_save_terminal() {
    local current="." path choice validated
    local -a dirs=() items=()
    while true; do
        dirs=()
        items=("select" "$(i18n wsq_browser_select)"
               "inspect" "$(i18n wsq_inspect_title)")
        [ "$current" = "." ] || items+=("up" "$(i18n wsq_browser_up)")
        while IFS= read -r path; do
            dirs+=("$path")
            items+=("${#dirs[@]}" "$(basename "$path")/")
        done < <(python3 "$WSQ_HELPER" directories "$prefix" "$current" --save-root "$WSQ_SAVE_ROOT" 2>/dev/null)
        choice="$(menu_select "$(i18n wsq_browser_title)" \
            "$(i18n wsq_browser_prompt "$(wsq_display_path "$current")")" "${items[@]}")" || return 1
        case "$choice" in
            inspect) wsq_inspect_folder "$current" || true ;;
            select)
                validated="$(python3 "$WSQ_HELPER" validate-save "$prefix" "$current" "$exe_rel" --save-root "$WSQ_SAVE_ROOT" 2>/dev/null)" || {
                    msgbox "$(i18n wsq_browser_title)" "$(i18n wsq_browser_invalid)"
                    continue
                }
                WSQ_SELECTED_SAVE="$validated"
                WSQ_SAVE_KIND="directory"
                return 0 ;;
            up)
                current="$(dirname "$current")" ;;
            *)
                case "$choice" in ''|*[!0-9]*) continue ;; esac
                [ "$choice" -ge 1 ] && [ "$choice" -le "${#dirs[@]}" ] || continue
                current="${dirs[$((choice-1))]}" ;;
        esac
    done
}

wsq_registry_save() {
    local key score choice preview
    local -a items=() keys=()
    while IFS=$'\t' read -r score key; do
        [ -n "$key" ] || continue
        keys+=("$key")
        items+=("${#keys[@]}" "[$score] $key")
    done < <(python3 "$WSQ_HELPER" registry "$prefix" "$snapshot" 2>/dev/null)
    if [ "${#keys[@]}" -eq 0 ]; then
        msgbox "$(i18n wsq_registry_title)" "$(i18n wsq_registry_none)"
        return 1
    fi
    choice="$(menu_select "$(i18n wsq_registry_title)" \
        "$(i18n wsq_registry_prompt)" "${items[@]}")" || return 1
    case "$choice" in ''|*[!0-9]*) return 1 ;; esac
    [ "$choice" -ge 1 ] && [ "$choice" -le "${#keys[@]}" ] || return 1
    preview="$(python3 "$WSQ_HELPER" registry-view "$prefix" "${keys[$((choice-1))]}" 2>/dev/null)" || return 1
    msgbox "$(i18n wsq_registry_title)" "$preview" || return 1
    yesno_default_no "$(i18n wsq_registry_title)" \
        "$(i18n wsq_registry_confirm "${keys[$((choice-1))]}")" || return 1
    WSQ_SAVE_KIND="registry"
    WSQ_SELECTED_SAVE="."
}

wsq_select_savefiles() {
    local rel size changed folder choice selected n name mode existing found
    local -a folders=() items=() names=() chosen=()
    choice="$(menu_select "$(i18n wsq_files_title)" "$(i18n wsq_files_intro)" \
        changed "$(i18n wsq_files_changed)" all "$(i18n wsq_files_all)")" || return 1
    case "$choice" in changed|all) mode="$choice" ;; *) return 1 ;; esac
    while IFS=$'\t' read -r rel size changed; do
        [ -n "$rel" ] || continue
        [ "$mode" = all ] || [ "$changed" = 1 ] || continue
        folder="$(dirname "$rel")"
        found=0
        for existing in "${folders[@]}"; do
            [ "$existing" != "$folder" ] || found=1
        done
        [ "$found" -eq 0 ] || continue
        folders+=("$folder")
        items+=("${#folders[@]}" "$(wsq_display_path "$folder")")
    done < <(python3 "$WT_ROOT/helpers/wsquashfs_savefiles.py" list "$prefix" "$snapshot")
    if [ "${#folders[@]}" -eq 0 ]; then
        msgbox "$(i18n wsq_files_title)" "$(i18n wsq_files_none)"
        return 1
    fi
    choice="$(menu_select "$(i18n wsq_files_title)" "$(i18n wsq_files_folder)" "${items[@]}")" || return 1
    case "$choice" in ''|*[!0-9]*) return 1 ;; esac
    [ "$choice" -ge 1 ] && [ "$choice" -le "${#folders[@]}" ] || return 1
    folder="${folders[$((choice-1))]}"
    items=()
    while IFS=$'\t' read -r rel size changed; do
        [ "$(dirname "$rel")" = "$folder" ] || continue
        [ "$mode" = all ] || [ "$changed" = 1 ] || continue
        name="$(basename "$rel")"
        names+=("$name")
        items+=("${#names[@]}" "$name ($size B)" off)
    done < <(python3 "$WT_ROOT/helpers/wsquashfs_savefiles.py" list "$prefix" "$snapshot")
    [ "${#names[@]}" -gt 0 ] || return 1
    selected="$(checklist_select "$(i18n wsq_files_title)" "$(i18n wsq_files_select)" "${items[@]}")" || return 1
    while IFS= read -r n; do
        case "$n" in ''|*[!0-9]*) continue ;; esac
        [ "$n" -ge 1 ] && [ "$n" -le "${#names[@]}" ] || return 1
        chosen+=("${names[$((n-1))]}")
    done <<< "$selected"
    [ "${#chosen[@]}" -gt 0 ] || return 1
    WSQ_SELECTED_SAVE="$folder"
    WSQ_SELECTED_SAVEFILES="$(IFS=';'; printf '%s' "${chosen[*]}")"
    WSQ_SAVE_KIND=files
}

wsq_copy_savefiles() {
    local staging rc
    local -a names=()
    IFS=';' read -r -a names <<< "$WSQ_SELECTED_SAVEFILES"
    staging="$(mktemp -d "$WSQ_STATE_DIR/savefiles.XXXXXX")" || return 1
    python3 "$WT_ROOT/helpers/wsquashfs_savefiles.py" stage "$prefix" "$snapshot" \
        --folder "$save_rel" --save-root "$WSQ_SAVE_ROOT" --staged "$staging" "${names[@]}" >> "${WT_SESSION_LOG:-/dev/null}" 2>&1
    rc=$?
    if [ "$rc" -eq 0 ]; then
        WSQ_LAST_SAVE_BACKUP=""
        wsq_save_destination_prepare "$WSQ_SAVE_ROOT/$game_name"
        rc=$?
        if [ "$rc" -eq 0 ]; then
            cp -a -- "$staging/." "$WSQ_SAVE_ROOT/$game_name/"
            rc=$?
            if [ "$rc" -eq 0 ]; then
                python3 "$WT_ROOT/helpers/wsquashfs_savefiles.py" remove "$prefix" "$snapshot" \
                    --folder "$save_rel" --save-root "$WSQ_SAVE_ROOT" "${names[@]}" >> "${WT_SESSION_LOG:-/dev/null}" 2>&1
                rc=$?
            fi
        fi
    fi
    rm -rf -- "$staging"
    return "$rc"
}

wsq_select_save_candidate() {
    local prefix="$1" snapshot="$2"
    WSQ_SELECTED_SAVE=""
    WSQ_SELECTED_SAVEFILES=""
    WSQ_SAVE_KIND="directory"
    local -a items=()
    local rows="" score count rel reason idx=1 choice validated
    while IFS=$'\t' read -r score count rel reason; do
        [ -n "$rel" ] || continue
        validated="$(python3 "$WSQ_HELPER" validate-save "$prefix" "$rel" "$exe_rel" --save-root "$WSQ_SAVE_ROOT" 2>/dev/null)" || continue
        items+=("$idx" "[$score] $(wsq_path_label "$validated")  ($count)")
        rows+="$validated"$'\n'
        idx=$((idx+1))
    done < <(python3 "$WSQ_HELPER" diff "$prefix" "$snapshot")

    if [ "${#items[@]}" -gt 0 ]; then
        items+=("files" "$(i18n wsq_files_title)"
                "browse" "$(i18n wsq_browser_title)"
                "terminal" "$(i18n wsq_browser_terminal)"
                "retry" "$(i18n wsq_no_save_retry)"
                "registry" "$(i18n wsq_registry_title)"
                "cancel" "$(i18n wsq_launch_cancel)")
        while true; do
            choice="$(menu_select "$(i18n wsq_save_title)" "$(i18n wsq_detected_choices)" "${items[@]}")" || return 1
            case "$choice" in
                browse) wsq_browse_save && return 0 ;;
                terminal) wsq_browse_save terminal && return 0 ;;
                retry) wsq_retry_pending; return 1 ;;
                files) wsq_select_savefiles && return 0 ;;
                registry) wsq_registry_save && return 0 ;;
                cancel) wsq_cancel_pending; return 1 ;;
                *)
                    case "$choice" in ''|*[!0-9]*) continue ;; esac
                    [ "$choice" -ge 1 ] && [ "$choice" -lt "$idx" ] || continue
                    rel="$(sed -n "${choice}p" <<< "$rows")"
                    wsq_review_save_candidate "$rel" && return 0 ;;
            esac
        done
    fi

    while true; do
        choice="$(menu_select "$(i18n wsq_save_title)" "$(i18n wsq_no_save_choices)" \
            "retry" "$(i18n wsq_no_save_retry)" \
            "registry" "$(i18n wsq_registry_title)" \
            "files" "$(i18n wsq_files_title)" \
            "browse" "$(i18n wsq_browser_title)" \
            "terminal" "$(i18n wsq_browser_terminal)" \
            "cancel" "$(i18n wsq_launch_cancel)")" || return 1
        case "$choice" in
            retry) wsq_retry_pending; return 1 ;;
            files) wsq_select_savefiles && return 0 ;;
            registry) wsq_registry_save && return 0 ;;
            browse) wsq_browse_save && return 0 ;;
            terminal) wsq_browse_save terminal && return 0 ;;
            cancel) wsq_cancel_pending; return 1 ;;
        esac
    done
}

wsq_copy_registry_save() {
    local dest="$WSQ_SAVE_ROOT/$game_name"
    # Read before touching the destination: user.reg may already point there.
    local tmp
    tmp="$(mktemp "$WSQ_STATE_DIR/user-reg.XXXXXX")" || return 1
    if ! cp -L -- "$prefix/user.reg" "$tmp"; then
        rm -f -- "$tmp"
        return 1
    fi
    wsq_save_destination_prepare "$dest"
    local rc=$?
    if [ "$rc" -ne 0 ]; then
        rm -f -- "$tmp"
        return "$rc"
    fi
    if ! cp -- "$tmp" "$dest/user.reg"; then
        rm -f -- "$tmp"
        return 1
    fi
    # The archive needs a working registry, never a symlink to this machine.
    if [ -L "$prefix/user.reg" ]; then
        cp -- "$tmp" "$prefix/.uwt-user.reg-$$" &&
            mv -f -- "$prefix/.uwt-user.reg-$$" "$prefix/user.reg" || {
                rm -f -- "$tmp" "$prefix/.uwt-user.reg-$$"
                return 1
            }
    fi
    rm -f -- "$tmp"
    return 0
}

wsq_save_destination_prepare() {
    local dest="$1"
    local choice backup stamp

    if [ ! -e "$dest" ]; then
        mkdir -p "$dest"
        return $?
    fi

    [ -d "$dest" ] && [ ! -L "$dest" ] || return 4

    choice="$(menu_select "$(i18n wsq_save_conflict_title)" \
        "$(i18n wsq_save_conflict_body "$dest")" \
        "1" "$(i18n wsq_save_conflict_backup)" \
        "2" "$(i18n wsq_save_conflict_replace)" \
        "0" "$(i18n cancel)")" || return 10

    case "$choice" in
        1)
            stamp="$(date '+%Y%m%d-%H%M%S')"
            backup="${dest}.backup-${stamp}"
            while [ -e "$backup" ]; do
                sleep 1
                stamp="$(date '+%Y%m%d-%H%M%S')"
                backup="${dest}.backup-${stamp}"
            done
            if ! mv -- "$dest" "$backup"; then
                return 5
            fi
            mkdir -p "$dest" || {
                mv -- "$backup" "$dest" 2>/dev/null || true
                return 6
            }
            WSQ_LAST_SAVE_BACKUP="$backup"
            return 0
            ;;
        2)
            yesno_default_no "$(i18n wsq_save_conflict_title)" \
                "$(i18n wsq_save_replace_confirm "$dest")" || return 10
            rm -rf -- "$dest" || return 7
            mkdir -p "$dest" || return 8
            WSQ_LAST_SAVE_BACKUP=""
            return 0
            ;;
        0|"")
            return 10
            ;;
    esac

    return 10
}

wsq_move_save_data() {
    local prefix="$1" save_rel="$2" game_name="$3"
    local save_abs dest item
    save_abs="$prefix/$save_rel"
    dest="$WSQ_SAVE_ROOT/$game_name"
    WSQ_LAST_SAVE_BACKUP=""

    [ -d "$save_abs" ] || return 2

    local source_real dest_real prefix_real
    source_real="$(readlink -f -- "$save_abs")" || return 2
    dest_real="$(readlink -m -- "$dest")" || return 2
    prefix_real="$(readlink -f -- "$prefix")" || return 2
    if [ "$source_real" = "$dest_real" ]; then
        wt_log "WSquashFS: save data already at destination: $dest"
        return 0
    fi
    case "$source_real" in
        "$dest_real"/*) return 9 ;;
    esac
    case "$dest_real" in
        "$source_real"/*) return 9 ;;
    esac

    wsq_save_destination_prepare "$dest"
    local prepare_rc=$?
    [ "$prepare_rc" -eq 0 ] || return "$prepare_rc"

    shopt -s dotglob nullglob
    for item in "$save_abs"/*; do
        if [[ "$source_real" != "$prefix_real/"* ]]; then
            # A pre-existing Batocera save link must not empty its external target.
            if ! cp -a -- "$item" "$dest/"; then
                shopt -u dotglob nullglob
                return 9
            fi
        elif ! mv -- "$item" "$dest/"; then
            shopt -u dotglob nullglob
            return 9
        fi
    done
    shopt -u dotglob nullglob
}

wsq_cleanup_internal_savedir() {
    local prefix="$1" save_rel="$2"
    local save_abs prefix_real save_real parent_real

    save_rel="${save_rel%/}"
    [ -n "$save_rel" ] || return 1

    prefix_real="$(readlink -f -- "$prefix" 2>/dev/null || true)"
    [ -n "$prefix_real" ] || return 1

    save_abs="$prefix/$save_rel"

    # SAVEDIR must remain an internal path of this prefix. Never follow or
    # remove anything outside the prefix.
    parent_real="$(readlink -f -- "$(dirname "$save_abs")" 2>/dev/null || true)"
    case "$parent_real" in
        "$prefix_real"|"$prefix_real"/*) ;;
        *) return 1 ;;
    esac

    # A symlink is never allowed in the final archive. Replace it with a real,
    # empty directory so an extracted .pc/.wine remains directly runnable.
    if [ -L "$save_abs" ]; then
        rm -f -- "$save_abs" || return 1
        mkdir -p -- "$save_abs" || return 1
        return 0
    fi

    # If the path disappeared after moving the save data, recreate it as a
    # real empty directory for portability after extraction.
    if [ ! -e "$save_abs" ]; then
        mkdir -p -- "$save_abs" || return 1
        return 0
    fi

    [ -d "$save_abs" ] || return 1
    save_real="$(readlink -f -- "$save_abs" 2>/dev/null || true)"
    case "$save_real" in
        "$prefix_real"/*) ;;
        *) return 1 ;;
    esac

    # Never hide unexpected data inside the final archive. The save contents
    # must already have been moved to /userdata/saves/windows/<game>.
    if find "$save_abs" -mindepth 1 -print -quit 2>/dev/null | grep -q .; then
        return 2
    fi

    # Keep the real empty directory in the prefix. This makes an extracted
    # archive usable as .pc/.wine without requiring Batocera to recreate it.
    return 0
}

wsq_prepare_existing_archive() {
    local archive="$1"
    local choice stamp backup

    WSQ_LAST_ARCHIVE_BACKUP=""
    WSQ_ARCHIVE_TARGET="$archive"
    WSQ_ARCHIVE_ACTION=created

    if [ ! -e "$archive" ] && [ ! -L "$archive" ]; then
        if [ "${2:-}" = choose ]; then
            choice="$(menu_select "$(i18n squash_rename_title)" "$(i18n wsq_archive_name_prompt "$archive")" \
                1 "$(i18n wsq_archive_name_keep)" 3 "$(i18n squash_create_renamed)" 0 "$(i18n cancel)")" || return 10
            case "$choice" in
                1) return 0 ;;
                3)
                    maintenance_choose_renamed_wsquashfs "$archive" || return 10
                    WSQ_ARCHIVE_TARGET="$MAINTENANCE_SELECTED_ARCHIVE"
                    WSQ_ARCHIVE_ACTION=rename
                    return 0 ;;
                *) return 10 ;;
            esac
        fi
        return 0
    fi
    [ -f "$archive" ] && [ ! -L "$archive" ] || return 4

    choice="$(menu_select "$(i18n wsq_archive_conflict_title)" \
        "$(i18n wsq_archive_conflict_body "$archive")" \
        "1" "$(i18n wsq_archive_conflict_backup)" \
        "2" "$(i18n wsq_archive_conflict_replace)" \
        "3" "$(i18n squash_create_renamed)" \
        "0" "$(i18n cancel)")" || return 10

    case "$choice" in
        1)
            stamp="$(date '+%Y%m%d-%H%M%S')"
            case "$archive" in
                *.wsquashfs) backup="${archive%.wsquashfs}.backup-${stamp}.wsquashfs" ;;
                *) backup="${archive}.backup-${stamp}" ;;
            esac
            while [ -e "$backup" ]; do
                sleep 1
                stamp="$(date '+%Y%m%d-%H%M%S')"
                case "$archive" in
                    *.wsquashfs) backup="${archive%.wsquashfs}.backup-${stamp}.wsquashfs" ;;
                    *) backup="${archive}.backup-${stamp}" ;;
                esac
            done
            mv -- "$archive" "$backup" || return 5
            WSQ_ARCHIVE_ACTION=backup
            WSQ_LAST_ARCHIVE_BACKUP="$backup"
            wt_log "WSquashFS: existing archive backed up: $archive -> $backup"
            return 0
            ;;
        2)
            WSQ_ARCHIVE_ACTION=replace
            # Keep the current archive in place while mksquashfs builds and
            # validates a temporary file. maintenance_squash_wine() replaces
            # the destination only after the new archive has passed validation.
            wt_log "WSquashFS: existing archive will be atomically replaced after validation: $archive"
            return 0
            ;;
        3)
            maintenance_choose_renamed_wsquashfs "$archive" || return 10
            WSQ_ARCHIVE_TARGET="$MAINTENANCE_SELECTED_ARCHIVE"
            WSQ_ARCHIVE_ACTION=rename
            return 0
            ;;
        0|"")
            return 10
            ;;
    esac

    return 10
}

wsq_post_build_menu() {
    local choice
    choice="$(menu_select "$(i18n wsq_post_title)" "$(i18n wsq_post_prompt)" \
        "1" "$(i18n wsq_post_new)" \
        "2" "$(i18n wsq_post_toolbox)" \
        "3" "$(i18n wsq_post_es)")" || return 20

    case "$choice" in
        1)
            wsq_create_new
            return 0
            ;;
        2)
            return 0
            ;;
        3|"")
            return 20
            ;;
    esac
}

wsq_game_option() {
    python3 "$WT_ROOT/helpers/wsquashfs_options.py" "$1" "$WSQ_CONF" \
        "$(basename "$prefix")" "$2" "${@:3}"
}

wsq_game_options_menu() {
    local key value label choice
    local -a items=()
    while true; do
        items=()
        for key in enable_hidraw dxvk fps_limit force_large_adress virtual_desktop; do
            value="$(wsq_game_option get "$key")" || return 1
            case "$value" in
                1) label="$(i18n enabled)" ;;
                0) label="$(i18n disabled)" ;;
                *) label="$(i18n wsq_option_inherit)" ;;
            esac
            items+=("$key" "$(i18n "wsq_option_$key") : $label")
        done
        value="$(python3 "$WT_ROOT/helpers/autorun_env.py" get "$prefix/autorun.cmd")" || return 1
        if [ "$value" = 1 ]; then label="$(i18n enabled)"; else label="$(i18n disabled)"; fi
        items+=("umu_direct_game" "$(i18n wsq_umu_direct_title) : $label")
        value="$(python3 "$WT_ROOT/helpers/autorun_env.py" get "$prefix/autorun.cmd" --key PROTON_SONY_HIDRAW_XINPUT)" || return 1
        case "$value" in
            1) label="$(i18n enabled)" ;;
            0) label="$(i18n disabled)" ;;
            *) label="$(i18n wsq_option_inherit)" ;;
        esac
        items+=("sony_xinput" "$(i18n wsq_sony_xinput_title) : $label")
        items+=("relaunch" "$(i18n wsq_options_relaunch)" "back" "$(i18n back)")
        choice="$(menu_select "$(i18n wsq_options_title)" "$(i18n wsq_options_prompt)" "${items[@]}")" || return 1
        case "$choice" in
            umu_direct_game)
                value="$(menu_select "$(i18n wsq_umu_direct_title)" "$(i18n wsq_umu_direct_body)" "1" "$(i18n enabled)" "0" "$(i18n disabled)")" || continue
                case "$value" in 0|1) ;; *) continue ;; esac
                python3 "$WT_ROOT/helpers/autorun_env.py" set "$prefix/autorun.cmd" "$value" || return 1
                ;;
            sony_xinput)
                value="$(menu_select "$(i18n wsq_sony_xinput_title)" "$(i18n wsq_sony_xinput_body)" "1" "$(i18n enabled)" "0" "$(i18n disabled)" "inherit" "$(i18n wsq_option_inherit)")" || continue
                case "$value" in 0|1|inherit) ;; *) continue ;; esac
                python3 "$WT_ROOT/helpers/autorun_env.py" set "$prefix/autorun.cmd" "$value" --key PROTON_SONY_HIDRAW_XINPUT || return 1
                ;;
            relaunch) wsq_retry_pending; return 1 ;;
            back) return 0 ;;
            enable_hidraw|dxvk|fps_limit|force_large_adress|virtual_desktop)
                value="$(menu_select "$(i18n "wsq_option_$choice")" "$(i18n wsq_option_prompt)"                     "1" "$(i18n enabled)" "0" "$(i18n disabled)"                     "inherit" "$(i18n wsq_option_inherit)")" || continue
                case "$value" in 0|1|inherit) ;; *) continue ;; esac
                wsq_game_option set "$choice" "$value" || {
                    msgbox "$(i18n wsq_options_title)" "$(i18n wsq_runner_config_failed)"
                    return 1
                } ;;
        esac
    done
}

wsq_apply_executable_selection() {
    local selected="$1" log="${WT_SESSION_LOG:-/dev/null}" mode update_log
    [ -n "$selected" ] || return 1
    mode="$(wsq_state_value mode 2>/dev/null)" || mode=""
    if [ "$mode" = update ]; then
        update_log="$(wsq_state_value update_log 2>/dev/null)" || update_log=""
        [ -z "$update_log" ] || log="$update_log"
    fi
    python3 "$WSQ_UPDATE_HELPER" autorun "$prefix" "$selected" >> "$log" 2>&1 || {
        msgbox "$(i18n wsq_launch_title)" "$(i18n wsq_executable_apply_failed "$selected")"
        return 1
    }
    exe_rel="$selected"
    wsq_update_state exe_rel "$selected" || return 1
}

wsq_install_extra_winetricks() {
    local choice selected verb log pretty runner_label
    local -a verbs=() items=()
    [ -d "$prefix/drive_c/windows" ] || return 1
    command -v batocera-wine >/dev/null 2>&1 || {
        msgbox "$(i18n wsq_winetricks_title)" "$(i18n wsq_winetricks_unavailable)"
        return 1
    }
    if [ "$runner" != __SYSTEM__ ] && [ ! -x "$BATOCERA_CUSTOM_WINE/$runner/bin/wine" ]; then
        msgbox "$(i18n wsq_winetricks_title)" "$(i18n wsq_winetricks_runner_missing "$runner")"
        return 1
    fi
    choice="$(menu_select "$(i18n wsq_winetricks_title)" "$(i18n wsq_winetricks_intro)" \
        common "$(i18n wsq_winetricks_common)" manual "$(i18n wsq_winetricks_manual)" \
        dotnet "$(i18n dotnet_title)" \
        back "$(i18n back)")" || return 1
    case "$choice" in
        common)
            for verb in vcrun2022 vcrun2019 vcrun2015 vcrun2013 vcrun2012 vcrun2010 \
                vcrun2008 vcrun2005 d3dcompiler_47 d3dcompiler_43 d3dx9 xact corefonts; do
                items+=("$verb" "$(i18n "wsq_winetricks_$verb")" off)
            done
            selected="$(checklist_select "$(i18n wsq_winetricks_title)" \
                "$(i18n wsq_winetricks_select)" "${items[@]}")" || return 1
            while IFS= read -r verb; do
                [ -z "$verb" ] || verbs+=("$verb")
            done <<< "$selected" ;;
        dotnet) wsq_dotnet_menu; return $? ;;
        manual)
            selected="$(input_text "$(i18n wsq_winetricks_title)" \
                "$(i18n wsq_winetricks_manual_prompt)" "")" || return 1
            read -r -a verbs <<< "$selected" ;;
        *) return 1 ;;
    esac
    [ "${#verbs[@]}" -gt 0 ] || return 1
    for verb in "${verbs[@]}"; do
        [[ "$verb" =~ ^[a-z][a-z0-9_]*$ ]] || {
            msgbox "$(i18n wsq_winetricks_title)" "$(i18n wsq_winetricks_invalid)"
            return 1
        }
    done
    pretty="${verbs[*]}"
    # Keep .NET replacement on the diagnosed, backed-up path even when typed
    # manually. Other manual Winetricks components retain their usual handling.
    for verb in "${verbs[@]}"; do
        if [ "$verb" = dotnet48 ]; then
            msgbox "$(i18n dotnet_title)" "$(i18n dotnet_manual)"
            return 1
        fi
    done
    runner_label="$runner"
    [ "$runner" != __SYSTEM__ ] || runner_label="$(i18n wsq_runner_system)"
    yesno_default_no "$(i18n wsq_winetricks_title)" \
        "$(i18n wsq_winetricks_confirm "$pretty" "$(wsq_display_path "$prefix")" "$runner_label")" || return 1
    wsq_set_runner_config "$(basename "$prefix")" "$runner" || return 1
    mkdir -p "$WSQ_STATE_DIR"
    log="${WT_SESSION_LOG:-$WSQ_STATE_DIR/wsquashfs-winetricks.log}"
    wt_log "WSquashFS: Winetricks prefix=$prefix runner=$runner components=$pretty"
    if ! wsq_update_run "$(i18n wsq_winetricks_title)" "$(i18n wsq_winetricks_installing "$pretty")" \
        "$log" python3 "$WT_ROOT/helpers/wsquashfs_winetricks.py" "$prefix" "${verbs[@]}"; then
        msgbox "$(i18n wsq_winetricks_title)" \
            "$(i18n wsq_winetricks_failed "$log" "$(wsq_update_log_detail "$log")")"
        return 1
    fi
    return 0
}

wsq_launch_failure_menu() {
    local choice new_runner new_exe
    local -a extra=()
    if [ "$(wsq_state_value mode)" = create ]; then
        extra=(winetricks "$(i18n wsq_winetricks_title)")
    fi
    while true; do
        choice="$(menu_select "$(i18n wsq_launch_title)" "$1" \
            "runner" "$(i18n wsq_launch_runner)" \
            "executable" "$(i18n wsq_launch_executable_review)" \
            "${extra[@]}" \
            "dotnet" "$(i18n dotnet_title)" \
            "retry" "$(i18n wsq_launch_retry)" \
            "options" "$(i18n wsq_options_title)" \
            "cancel" "$(i18n wsq_launch_cancel)")" || return 1
        case "$choice" in
            winetricks)
                wsq_install_extra_winetricks || continue
                if yesno "$(i18n wsq_winetricks_title)" "$(i18n wsq_winetricks_retest)"; then
                    wsq_retry_pending
                    return 1
                fi ;;
            dotnet) wsq_dotnet_menu ;;
            runner)
                new_runner="$(wsq_select_runner)" || continue
                wsq_set_runner_config "$(basename "$prefix")" "$new_runner" || {
                    msgbox "$(i18n wsq_launch_title)" "$(i18n wsq_runner_config_failed)"
                    return 1
                }
                runner="$new_runner"
                wsq_save_state "$prefix" "$game_name" "$snapshot" "$exe_rel" "$runner" || return 1
                wsq_retry_pending
                return 1 ;;
            executable)
                new_exe="$(wsq_update_select_executable "$prefix")" || continue
                [ "$new_exe" != "$exe_rel" ] || continue
                wsq_apply_executable_selection "$new_exe" || continue
                wsq_retry_pending
                return 1 ;;
            retry) wsq_retry_pending; return 1 ;;
            options) wsq_game_options_menu || return 1 ;;
            cancel) wsq_cancel_pending; return 1 ;;
        esac
    done
}

wsq_review_launch() {
    local result="" choice body new_exe
    if [ -f "$WSQ_STATE_DIR/wsq-launch-result" ]; then
        IFS= read -r result < "$WSQ_STATE_DIR/wsq-launch-result" || true
    fi
    case "$result" in
        launch_failed|start_unconfirmed|es_unavailable)
            wsq_launch_failure_menu "$(i18n "wsq_launch_$result")"
            return 1 ;;
        ""|normal|short) ;;
        *) return 1 ;;
    esac

    body="$(i18n wsq_game_worked "$runner")"
    [ "$result" != short ] || body="$(i18n wsq_launch_short)"$'\n\n'"$body"
    while true; do
        choice="$(menu_select "$(i18n wsq_launch_title)" "$body" \
            "yes" "$(i18n wsq_game_yes)" \
            "no" "$(i18n wsq_game_no)" \
            "executable" "$(i18n wsq_launch_executable_review)" \
            "hidraw" "$(i18n wsq_hidraw_retry)" \
            "options" "$(i18n wsq_options_title)" \
            "cancel" "$(i18n wsq_launch_cancel)")" || return 1
        case "$choice" in
            yes)
                rm -f -- "$WSQ_STATE_DIR/wsq-launch-result"
                return 0 ;;
            no) wsq_launch_failure_menu "$(i18n wsq_game_failed)"; return 1 ;;
            executable)
                new_exe="$(wsq_update_select_executable "$prefix")" || continue
                [ "$new_exe" != "$exe_rel" ] || continue
                wsq_apply_executable_selection "$new_exe" || continue
                wsq_retry_pending
                return 1 ;;
            hidraw)
                wsq_game_option set enable_hidraw 1 || {
                    msgbox "$(i18n wsq_launch_title)" "$(i18n wsq_runner_config_failed)"
                    return 1
                }
                wsq_retry_pending
                return 1 ;;
            options) wsq_game_options_menu || return 1 ;;
            cancel) wsq_cancel_pending; return 1 ;;
        esac
    done
}

wsq_resume_build() {
    local prefix game_name snapshot exe_rel runner save_rel dest archive save_kind
    [ -s "$WSQ_STATE_FILE" ] || {
        msgbox "$(i18n wsq_resume_title)" "$(i18n wsq_no_pending)"
        return
    }

    prefix="$(wsq_state_value prefix)"
    game_name="$(wsq_state_value game_name)"
    snapshot="$(wsq_state_value snapshot)"
    exe_rel="$(wsq_state_value exe_rel)"
    runner="$(wsq_state_value runner)"

    [ -d "$prefix" ] && [ -s "$snapshot" ] || {
        wsq_recover_invalid_pending
        return
    }

    if [ "$(wsq_state_value mode)" = update ]; then
        if [ "$(wsq_state_value phase)" = testing ]; then
            wsq_review_launch || return
        fi
        wsq_resume_update
        return $?
    fi

    wsq_review_launch || return

    wsq_select_save_candidate "$prefix" "$snapshot" || return
    save_rel="$WSQ_SELECTED_SAVE"
    save_kind="$WSQ_SAVE_KIND"

    if [ "$save_kind" = registry ]; then
        WSQ_LAST_SAVE_BACKUP=""
        wsq_copy_registry_save
    elif [ "$save_kind" = files ]; then
        yesno_default_no "$(i18n wsq_files_title)" "$(i18n wsq_files_confirm "$save_rel" "$WSQ_SELECTED_SAVEFILES")" || return
        wsq_copy_savefiles
    else
        yesno_default_no "$(i18n wsq_save_title)" \
            "$(i18n wsq_save_confirm "$(wsq_display_path "$save_rel")" "$(wsq_display_path "$WSQ_SAVE_ROOT/$game_name")")" || return
        wsq_move_save_data "$prefix" "$save_rel" "$game_name"
    fi
    local move_rc=$?
    if [ "$move_rc" -ne 0 ]; then
        if [ "$move_rc" -eq 10 ]; then
            return
        fi
        msgbox "$(i18n wsq_save_title)" "$(i18n wsq_save_move_failed "$WSQ_SAVE_ROOT/$game_name")"
        return
    fi

    if [ "$save_kind" = directory ]; then
        wsq_cleanup_internal_savedir "$prefix" "$save_rel" || {
            msgbox "$(i18n wsq_create_title)" "$(i18n wsq_savedir_cleanup_failed "$prefix/$save_rel")"
            return
        }
    fi

    if [ "$save_kind" = registry ]; then
        wsq_write_autorun "$prefix" "$exe_rel" "." "user.reg"
    elif [ "$save_kind" = files ]; then
        wsq_write_autorun "$prefix" "$exe_rel" "$save_rel" "$WSQ_SELECTED_SAVEFILES"
    else
        wsq_write_autorun "$prefix" "$exe_rel" "$save_rel"
    fi

    if [ -n "${WSQ_LAST_SAVE_BACKUP:-}" ]; then
        msgbox "$(i18n wsq_save_title)" "$(i18n wsq_save_backup_done "$WSQ_LAST_SAVE_BACKUP")"
    fi

    rm -f -- "$snapshot" "$WSQ_STATE_FILE"

    local build_prompt
    if [ "$save_kind" = registry ]; then
        build_prompt="$(i18n wsq_registry_build_now)"
    elif [ "$save_kind" = files ]; then
        build_prompt="$(i18n wsq_files_build_now)"
    else
        build_prompt="$(i18n wsq_build_now)"
    fi
    if yesno "$(i18n wsq_create_title)" "$build_prompt"; then
        archive="${prefix%.wine}.wsquashfs"
        wsq_prepare_existing_archive "$archive" choose
        local archive_rc=$?
        if [ "$archive_rc" -ne 0 ]; then
            case "$archive_rc" in
                10)
                    return
                    ;;
                4)
                    msgbox "$(i18n wsq_archive_conflict_title)" "$(i18n wsq_archive_conflict_invalid "$archive")"
                    ;;
                5)
                    msgbox "$(i18n wsq_archive_conflict_title)" "$(i18n wsq_archive_backup_failed "$archive")"
                    ;;
                *)
                    msgbox "$(i18n wsq_archive_conflict_title)" "$(i18n wsq_archive_conflict_failed "$archive")"
                    ;;
            esac
            return
        fi
        archive="$WSQ_ARCHIVE_TARGET"
        local final_game_name
        final_game_name="$(basename "$archive" .wsquashfs)"
        if [ "$final_game_name" != "$game_name" ]; then
            dest="$WSQ_SAVE_ROOT/$final_game_name"
            wsq_save_destination_prepare "$dest"
            local save_rc=$?
            if [ "$save_rc" -ne 0 ]; then
                [ "$save_rc" -eq 10 ] || msgbox "$(i18n wsq_save_title)" "$(i18n wsq_save_move_failed "$dest")"
                return
            fi
            cp -a -- "$WSQ_SAVE_ROOT/$game_name/." "$dest/" || {
                msgbox "$(i18n wsq_save_title)" "$(i18n wsq_save_move_failed "$dest")"
                return
            }
            if [ -n "${WSQ_LAST_SAVE_BACKUP:-}" ]; then
                msgbox "$(i18n wsq_save_title)" "$(i18n wsq_save_backup_done "$WSQ_LAST_SAVE_BACKUP")"
            fi
        fi
        local cleanup_rc=0
        if [ "$save_kind" = directory ]; then
            wsq_cleanup_internal_savedir "$prefix" "$save_rel"
            cleanup_rc=$?
        fi
        if [ "$cleanup_rc" -ne 0 ]; then
            if [ "$cleanup_rc" -eq 2 ]; then
                msgbox "$(i18n wsq_create_title)" "$(i18n wsq_savedir_not_empty "$prefix/$save_rel")"
            else
                msgbox "$(i18n wsq_create_title)" "$(i18n wsq_savedir_cleanup_failed "$prefix/$save_rel")"
            fi
            return
        fi

        if maintenance_squash_wine "$prefix" "$archive" ask-quick; then
            wsq_finalize_runner_config "$final_game_name" "$runner" "$prefix" || {
                msgbox "$(i18n wsq_create_title)" "$(i18n wsq_runner_finalize_failed "$archive")"
                return
            }

            if [ -n "${WSQ_LAST_ARCHIVE_BACKUP:-}" ]; then
                msgbox "$(i18n wsq_archive_conflict_title)" \
                    "$(i18n wsq_archive_backup_done "$WSQ_LAST_ARCHIVE_BACKUP")"
            fi

            if yesno_default_no "$(i18n squash_delete_source_title)" \
                "$(i18n squash_delete_source_confirm "$(basename "$prefix")")"; then
                maintenance_delete_wine_dir_symlink_safe "$prefix" || true
            fi
            msgbox "$(i18n wsq_create_title)" "$(i18n wsq_build_done "$archive" "$WSQ_SAVE_ROOT/$final_game_name")"
            wsq_restart_emulationstation_deferred || true
            wsq_post_build_menu
            return $?
        else
            msgbox "$(i18n wsq_create_title)" "$(i18n wsq_build_failed)"
        fi
    else
        msgbox "$(i18n wsq_create_title)" "$(i18n wsq_ready_to_squash "$prefix")"
    fi
}

wsq_final_archive_check() {
    local archive="$1" mode="$2" log="${3:-}" choice label cancel
    case "$mode" in
        quick) label="$(i18n wsq_integrity_quick)" ;;
        full) label="$(i18n wsq_integrity_full)" ;;
        *) return 1 ;;
    esac
    choice="$(menu_select "$(i18n wsq_integrity_title)" "$(i18n wsq_final_check_prompt)" \
        check "$label" skip "$(i18n wsq_final_check_skip)" cancel "$(i18n cancel)")" || return 1
    case "$choice" in
        skip)
            [ -z "$log" ] || printf '\nFinal archive integrity check skipped by user.\n' >> "$log"
            return 0 ;;
        check) ;;
        *) return 1 ;;
    esac
    mkdir -p "$WT_LOG_DIR" "$WSQ_STATE_DIR" || return 1
    if [ -z "$log" ]; then
        log="$(mktemp "$WT_LOG_DIR/wsquashfs-integrity-build-$(date +%Y%m%d-%H%M%S)-XXXXXX.log")" || return 1
        wsq_integrity_rotate_logs "$log" || true
    fi
    if [ "$mode" = quick ]; then
        wsq_update_run "$(i18n wsq_integrity_title)" "$label" "$log" unsquashfs -s "$archive"
    else
        cancel="$(mktemp "$WSQ_STATE_DIR/final-check-cancel-XXXXXX")" || return 1
        rm -f -- "$cancel"
        wsq_update_run "$(i18n wsq_integrity_title)" "$(i18n wsq_update_validate)" "$log" \
            python3 "$WT_ROOT/helpers/wsquashfs_integrity.py" full "$archive" "$log" "$cancel"
        local rc=$?
        rm -f -- "$cancel"
        return "$rc"
    fi
}

wsq_integrity_rotate_logs() {
    python3 - "$WT_LOG_DIR" "$1" <<'PY'
from pathlib import Path
import sys

directory = Path(sys.argv[1])
current = Path(sys.argv[2])
logs = []
for path in directory.glob("wsquashfs-integrity-*.log"):
    try:
        if path.is_file() and not path.is_symlink() and path != current:
            logs.append((path.stat().st_mtime_ns, path.name, path))
    except FileNotFoundError:
        pass
logs.sort(reverse=True)
# Reserve one of the 20 slots for the report currently being written.
for _, _, path in logs[19:]:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
PY
}

wsq_integrity_check() {
    local mode selected rows="" path id idx=1 log work cancel pid rc start elapsed choice result=""
    local -a items=()
    command -v unsquashfs >/dev/null 2>&1 || {
        msgbox "$(i18n wsq_integrity_title)" "$(i18n squash_tools_missing)"
        return
    }
    while IFS= read -r path; do
        [ -n "$path" ] || continue
        items+=("$idx" "$(basename "$path")" off)
        rows+="$path"$'\n'
        idx=$((idx+1))
    done < <(find "$WSQ_WINDOWS_DIR" -mindepth 1 -maxdepth 1 -type f -iname '*.wsquashfs' -print 2>/dev/null | sort -f)
    [ "${#items[@]}" -gt 0 ] || {
        msgbox "$(i18n wsq_integrity_title)" "$(i18n squash_no_wsquashfs)"
        return
    }
    selected="$(checklist_select "$(i18n wsq_integrity_title)" "$(i18n wsq_integrity_select)" "${items[@]}")" || return
    [ -n "$selected" ] || return
    mode="$(menu_select "$(i18n wsq_integrity_title)" "$(i18n wsq_integrity_modes)" \
        full "$(i18n wsq_integrity_full)" quick "$(i18n wsq_integrity_quick)" 0 "$(i18n cancel)")" || return
    case "$mode" in full|quick) ;; *) return ;; esac
    mkdir -p "$WT_LOG_DIR" || return
    work="$(mktemp -d /tmp/uwt-integrity.XXXXXX)" || return
    cancel="$work/cancel"
    log="$(mktemp "$WT_LOG_DIR/wsquashfs-integrity-$(date +%Y%m%d-%H%M%S)-XXXXXX.log")" || { rm -rf -- "$work"; return; }
    wsq_integrity_rotate_logs "$log" || wt_log "WSquashFS: integrity log rotation failed"
    idx=0
    while IFS= read -r id; do
        case "$id" in ''|*[!0-9]*) continue ;; esac
        path="$(sed -n "${id}p" <<< "$rows")"
        [ -n "$path" ] || continue
        idx=$((idx+1))
        start=$SECONDS
        python3 "$WT_ROOT/helpers/wsquashfs_integrity.py" "$mode" "$path" "$log" "$cancel" &
        pid=$!
        while kill -0 "$pid" 2>/dev/null; do
            elapsed=$((SECONDS-start))
            if have_dialog; then
                DIALOG_TIMEOUT=42 dialog --clear --no-shadow --timeout 1 --ok-label "$(i18n cancel)" \
                    --title "$(i18n wsq_integrity_title)" \
                    --msgbox "$(i18n wsq_integrity_running "$idx" "$(basename "$path")" "$elapsed")" 14 96
                rc=$?
                if [ "$rc" -ne 42 ]; then
                    touch "$cancel"
                    break
                fi
            else
                printf '%s\n' "$(i18n wsq_integrity_running "$idx" "$(basename "$path")" "$elapsed")"
                sleep 1
            fi
        done
        wait "$pid"
        rc=$?
        if [ -e "$cancel" ]; then
            result+="$(basename "$path") : $(i18n wsq_integrity_cancelled)"$'\n'
            break
        fi
        case "$rc" in
            0) choice="$(i18n wsq_integrity_ok)" ;;
            3) choice="$(i18n wsq_integrity_unsupported)" ;;
            *) choice="$(i18n wsq_integrity_error)" ;;
        esac
        result+="$(basename "$path") : $choice"$'\n'
    done <<< "$selected"
    rm -rf -- "$work"
    printf '\n%s\n' "$result" >> "$log"
    msgbox "$(i18n wsq_integrity_title)" "$(i18n wsq_integrity_result "$result" "$log")"
    if yesno "$(i18n wsq_integrity_title)" "$(i18n wsq_integrity_view_log)"; then
        if have_dialog; then
            dialog --clear --no-shadow --exit-label "$(i18n back)" --title "$(i18n wsq_integrity_title)" --textbox "$log" 24 100
        else
            cat -- "$log"
        fi
    fi
}

wsq_v41_savedir_menu() {
    local helper="$WT_ROOT/helpers/v41_savedir_service.py" choice status log
    status="$(python3 "$helper" status 2>/dev/null)" || status=changed
    choice="$(menu_select "$(i18n wsq_v41_title)" "$(i18n wsq_v41_intro "$status")" \
        enable "$(i18n wsq_v41_install)" disable "$(i18n wsq_v41_remove)" cancel "$(i18n back)")" || return
    case "$choice" in enable|disable) ;; *) return ;; esac
    yesno_default_no "$(i18n wsq_v41_title)" "$(i18n wsq_v41_confirm)" || return
    mkdir -p "$WT_LOG_DIR" || return
    log="$(mktemp "$WT_LOG_DIR/v41-savedir-XXXXXX.log")" || return
    if python3 "$helper" "$choice" > "$log" 2>&1; then
        msgbox "$(i18n wsq_v41_title)" "$(i18n wsq_v41_done)"
    else
        msgbox "$(i18n wsq_v41_title)" "$(i18n wsq_v41_failed "$(cat "$log")" "$log")"
    fi
}

wsquashfs_menu() {
    while true; do
        local choice pending=""
        [ -s "$WSQ_STATE_FILE" ] && pending="$(i18n wsq_pending_marker)"
        choice="$(menu_select "$(i18n wsq_title)" "$(i18n wsq_intro)" \
            "1" "$(i18n wsq_create_action)" \
            "2" "$(i18n wsq_update_title)" \
            "3" "$(i18n wsq_resume_action) $pending" \
            "4" "$(i18n squash_wine)" \
            "5" "$(i18n unsquash_wine)" \
            "6" "$(i18n wsq_integrity_title)" \
            "7" "$(i18n wsq_v41_title)" \
            "0" "$(i18n back)")" || return
        case "$choice" in
            1) wsq_create_new ;;
            2) wsq_update_new ;;
            3) wsq_resume_build ;;
            4) maintenance_select_and_squash ;;
            5) maintenance_select_and_unsquash ;;
            6) wsq_integrity_check ;;
            7) wsq_v41_savedir_menu ;;
            0|"") return ;;
        esac
    done
}
