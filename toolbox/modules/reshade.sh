#!/bin/bash
RESH_HELPER="$WT_ROOT/helpers/reshade_manager.py"
RESH_BACKEND="$WT_HOME/reshade/backend/reshadelinux.sh"

resh_cmd() {
    local -a flags=()
    if ! grep -Fq 'WINE_BOTTLE_DIR}/${WINE_VERSION}/${ROMGAMENAME}.wine' /usr/bin/batocera-wine 2>/dev/null; then
        flags+=(--legacy)
    fi
    python3 "$RESH_HELPER" --home "$WT_HOME" "${flags[@]}" "$@"
}

resh_backend_ready() {
    local tool missing=""
    for tool in curl python3 sha256sum tar flock; do
        command -v "$tool" >/dev/null 2>&1 || missing+="$tool "
    done
    if [ -n "$missing" ]; then
        msgbox "$(i18n resh_title)" "$(i18n resh_missing_tools "$missing")"
        return 1
    fi
    msgbox "$(i18n resh_title)" "$(i18n resh_backend_fetch)" || return 1
    WT_HOME="$WT_HOME" bash "$WT_ROOT/helpers/install-reshade-backend.sh" >> "${WT_SESSION_LOG:-/dev/null}" 2>&1 || {
        msgbox "$(i18n resh_title)" "$(i18n resh_failed "${WT_SESSION_LOG:-}")"
        return 1
    }
}

resh_prepare_tools() {
    local shim="$WT_HOME/reshade/bin"
    mkdir -p "$shim"
    # Batocera does not ship Git/libmagic on every image. These private
    # adapters cover only the calls of our pinned upstream backend.
    local compatibility_tool
    for compatibility_tool in git file; do
        if ! command -v "$compatibility_tool" >/dev/null 2>&1; then
            printf '#!/bin/bash\nexec python3 %q %q "$@"\n' \
                "$WT_ROOT/helpers/reshade_compat.py" "$compatibility_tool" > "$shim/$compatibility_tool"
            chmod +x "$shim/$compatibility_tool"
        else
            printf '#!/bin/bash\nexec %q "$@"\n' "$(command -v "$compatibility_tool")" > "$shim/$compatibility_tool"
            chmod +x "$shim/$compatibility_tool"
        fi
    done
    # Official ReShade installers contain a ZIP payload. Always use Python:
    # Batocera may provide a 7z executable with a missing archive plugin.
    printf '#!/bin/bash\nexec python3 %q "$@"\n' "$WT_ROOT/helpers/reshade_extract.py" > "$shim/7z"
    chmod +x "$shim/7z"
}

resh_model_packs() {
    case "$1" in
        standard) printf '%s' 'reshade-shaders,sweetfx-shaders' ;;
        retro) printf '%s' 'reshade-shaders,sweetfx-shaders,crt-royale,rsretroarch-shaders,scaling-shaders,reshade-bur' ;;
        thomson) printf '%s' 'reshade-shaders,sweetfx-shaders,reshade-shaders-legacy,fubax-shaders,quintfx,prod80-shaders,astrayfx-shaders,immerse-shaders' ;;
        manual) printf '' ;;
    esac
}

resh_preset_file() {
    local mode="$1" rom="$2" name="${2##*/}" chosen
    name="${name%.*}-ReShade.ini"
    if command -v yad >/dev/null 2>&1; then
        local -a flags=()
        [ "$mode" != export ] || flags+=(--save --confirm-overwrite)
        DISPLAY="${DISPLAY:-:0}" LANGUAGE="$WT_LANGUAGE" yad --file-selection "${flags[@]}" \
            --filename="/userdata/$([ "$mode" != export ] || printf '%s' "$name")" \
            --title="$(i18n "resh_${mode}_title")" --file-filter='ReShade presets | *.ini *.INI' \
            --file-filter="$(i18n resh_all_files) | *" --width=1000 --height=700
    else
        chosen="$(input_text "$(i18n "resh_${mode}_title")" "$(i18n resh_preset_prompt)" "/userdata/$([ "$mode" != export ] || printf '%s' "$name")")" || return 1
        if [ "$mode" = export ] && [ -e "$chosen" ]; then
            yesno_default_no "$(i18n resh_title)" "$(i18n resh_export_overwrite "$chosen")" || return 1
        fi
        printf '%s' "$chosen"
    fi
}

resh_diagnostic() {
    local rom="$1"
    yesno_default_no "$(i18n resh_title)" "$(i18n resh_diag_confirm)" || return 1
    python3 "$WT_ROOT/helpers/reshade_diagnostic.py" --home "$WT_HOME" request "$rom" >> "${WT_SESSION_LOG:-/dev/null}" 2>&1 || {
        msgbox "$(i18n resh_title)" "$(i18n resh_diag_pending)"; return 1;
    }
    return 0
}

resh_resume_diagnostic() {
    local rom detected candidates evidence result
    rom="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["rom"])' "$WT_HOME/state/reshade-diagnostic.json" 2>/dev/null)" || return
    if [ "$(cat "$WT_HOME/state/launch-game.request" 2>/dev/null)" = "$rom" ]; then
        rm -f -- "$WT_HOME/state/launch-game.request"
    fi
    if python3 "$WT_ROOT/helpers/reshade_diagnostic.py" --home "$WT_HOME" active "$rom"; then
        msgbox "$(i18n resh_title)" "$(i18n resh_diag_active)"
        return
    fi
    rm -f -- "$WT_HOME/state/reshade-diagnostic.json" "$WT_HOME/state/reshade-diagnostic.stop"
    detected="$(python3 "$WT_ROOT/helpers/reshade_diagnostic.py" --home "$WT_HOME" result "$rom")"
    candidates="${detected%%$'\t'*}"; evidence="${detected##*$'\t'}"
    result="$(cat "$WT_HOME/state/wsq-launch-result" 2>/dev/null)"
    msgbox "$(i18n resh_title)" "$(i18n resh_diag_result "${candidates:-?}" "${evidence:-?}" "${result:-?}")"
    resh_game_menu "$rom"
}

resh_api_select() {
    local rom="$1" exe="$2" detected candidates kind evidence prompt choice api label query titles title idx selected
    local -a rows=() names=()
    detected="$(resh_cmd api "$rom" "$exe" 2>> "${WT_SESSION_LOG:-/dev/null}")" || detected=""
    IFS=$'\t' read -r candidates kind evidence <<< "$detected"
    # read treats tabs as whitespace; retain empty candidate fields explicitly.
    candidates="${detected%%$'\t'*}"
    local observed
    observed="$(python3 "$WT_ROOT/helpers/reshade_diagnostic.py" --home "$WT_HOME" result "$rom" 2>> "${WT_SESSION_LOG:-/dev/null}")"
    if [ -n "${observed%%$'\t'*}" ]; then
        candidates="${observed%%$'\t'*}"; evidence="${observed##*$'\t'}"
    fi
    prompt="$(i18n resh_api_prompt)\n\n$(i18n resh_api_detection "${evidence:-?}")"
    while true; do
        rows=()
        for api in d3d9 dxgi opengl32; do
            case "$api" in d3d9) label='DirectX 9 (d3d9)' ;; dxgi) label='DirectX 10 / 11 / 12 (dxgi)' ;; opengl32) label='OpenGL (opengl32)' ;; esac
            if [[ ",$candidates," == *",$api,"* ]]; then
                rows+=("$api" "$label — $(i18n resh_api_suggested)")
            fi
        done
        for api in dxgi d3d9 opengl32; do
            [[ ",$candidates," != *",$api,"* ]] || continue
            case "$api" in d3d9) label='DirectX 9 (d3d9)' ;; dxgi) label='DirectX 10 / 11 / 12 (dxgi)' ;; opengl32) label='OpenGL (opengl32)' ;; esac
            rows+=("$api" "$label")
        done
        if [[ ",$candidates," == *',vulkan,'* || ",$candidates," == *',legacy,'* ]]; then
            prompt+="\n$(i18n resh_api_unsupported)"
        fi
        choice="$(menu_select "$(i18n resh_title)" "$prompt" "${rows[@]}" diagnostic "$(i18n resh_diag_title)" wiki "$(i18n resh_api_wiki)")" || return 1
        case "$choice" in
            dxgi|d3d9|opengl32) printf '%s' "$choice"; return 0 ;;
            diagnostic) resh_diagnostic "$rom" && return 2; continue ;;
            wiki)
                query="$(resh_cmd wiki-title "$rom")"
                query="$(input_text "$(i18n resh_api_wiki)" "$(i18n resh_wiki_query)" "$query")" || continue
                titles="$(resh_cmd wiki-search "$query" 2>> "${WT_SESSION_LOG:-/dev/null}")" || {
                    msgbox "$(i18n resh_title)" "$(i18n resh_wiki_unavailable)"; continue;
                }
                names=(); rows=(); idx=0
                while IFS= read -r title; do
                    [ -n "$title" ] || continue
                    names+=("$title"); idx=$((idx+1)); if [ "$idx" -eq 1 ]; then rows+=("$idx" "$title — $(i18n resh_wiki_first)"); else rows+=("$idx" "$title"); fi
                done <<< "$titles"
                [ "$idx" -gt 0 ] || { msgbox "$(i18n resh_title)" "$(i18n resh_no_match)"; continue; }
                selected="$(menu_select "$(i18n resh_api_wiki)" "$(i18n resh_wiki_choose)" "${rows[@]}")" || continue
                case "$selected" in ''|*[!0-9]*) continue ;; esac
                [ "$selected" -ge 1 ] && [ "$selected" -le "$idx" ] || continue
                title="${names[$((selected-1))]}"
                detected="$(resh_cmd wiki-page "$title" 2>> "${WT_SESSION_LOG:-/dev/null}")" || {
                    msgbox "$(i18n resh_title)" "$(i18n resh_wiki_unavailable)"; continue;
                }
                candidates="${detected%%$'\t'*}"; evidence="${detected#*$'\t'}"
                prompt="$(i18n resh_api_prompt)\n\nPCGamingWiki : $title\n${evidence:-?}\n$(i18n resh_wiki_hint)"
                ;;
            *) return 1 ;;
        esac
    done
}

resh_install_game() {
    local rom="$1" exe selected dll version packs state workspace name label model defaults current
    local -a exes=() items=() shaders=()
    local listing
    listing="$(resh_cmd exes "$rom" 2>> "${WT_SESSION_LOG:-/dev/null}")" || {
        msgbox "$(i18n resh_title)" "$(i18n resh_failed "${WT_SESSION_LOG:-}")"
        return 1
    }
    while IFS= read -r exe; do
        [ -n "$exe" ] || continue
        exes+=("$exe")
        items+=("${#exes[@]}" "$exe")
    done <<< "$listing"
    [ "${#exes[@]}" -gt 0 ] || { msgbox "$(i18n resh_title)" "$(i18n resh_no_exe)"; return 1; }
    selected="$(menu_select "$(i18n resh_title)" "$(i18n resh_exe_prompt)" "${items[@]}")" || return 1
    case "$selected" in ''|*[!0-9]*) return 1 ;; esac
    [ "$selected" -ge 1 ] && [ "$selected" -le "${#exes[@]}" ] || return 1
    exe="${exes[$((selected-1))]}"
    dll="$(resh_api_select "$rom" "$exe")" || {
        [ ! -f "$WT_HOME/state/reshade-diagnostic.json" ] || exit 0
        return 1
    }
    case "$dll" in dxgi|d3d9|opengl32) ;; *) return 1 ;; esac
    version="$(input_text "$(i18n resh_title)" "$(i18n resh_version_prompt)" latest)" || return 1
    [[ "$version" =~ ^(latest|[0-9]+\.[0-9]+\.[0-9]+)$ ]] || {
        msgbox "$(i18n resh_title)" "$(i18n resh_version_invalid)"
        return 1
    }
    resh_backend_ready || return 1
    items=(standard "$(i18n resh_model_standard)" retro "$(i18n resh_model_retro)" thomson "$(i18n resh_model_thomson)" manual "$(i18n resh_model_manual)")
    current="$(resh_cmd details "$rom")"
    [ -z "$current" ] || items+=(current "$(i18n resh_model_current)")
    model="$(menu_select "$(i18n resh_title)" "$(i18n resh_model_prompt)" "${items[@]}")" || return 1
    case "$model" in
        standard|retro|thomson|manual) defaults="$(resh_model_packs "$model")" ;;
        current) defaults="${current##*$'\t'}" ;;
        *) return 1 ;;
    esac
    if [ "$model" = manual ]; then
        items=()
        while IFS=$'\t' read -r name label; do
            name="${name#  }"
            [[ "$name" =~ ^[a-z0-9_-]+$ ]] && [ -n "$label" ] || continue
            state=off
            [[ ",$defaults," != *",$name,"* ]] || state=on
            items+=("$name" "$label" "$state")
        done < <(MAIN_PATH="$WT_HOME/reshade/runtime" UI_BACKEND=cli NO_COLOR=1 \
            bash "$RESH_BACKEND" --cli --list-shader-repos 2>> "${WT_SESSION_LOG:-/dev/null}")
        [ "${#items[@]}" -gt 0 ] || return 1
        selected="$(checklist_select "$(i18n resh_title)" "$(i18n resh_shaders_prompt)" "${items[@]}")" || return 1
        while IFS= read -r name; do
            [ -z "$name" ] || shaders+=("$name")
        done <<< "$selected"
        packs="$(IFS=','; printf '%s' "${shaders[*]}")"
        packs="${packs:-none}"
    else
        packs="$defaults"
    fi
    yesno_default_no "$(i18n resh_title)" "$(i18n resh_install_confirm "$(basename "$rom")" "$exe" "$dll" "$version" "$packs")" || return 1
    # Reconfiguration starts from restored originals; the saved preset survives.
    state="$(resh_cmd status "$rom")"
    if [ "$state" != missing ]; then
        resh_cmd disable "$rom" >> "${WT_SESSION_LOG:-/dev/null}" 2>&1 || {
            msgbox "$(i18n resh_title)" "$(i18n resh_failed "${WT_SESSION_LOG:-}")"
            return 1
        }
    fi
    workspace="$(resh_cmd prepare "$rom" "$exe" "$dll" "$version" "$packs" 2>> "${WT_SESSION_LOG:-/dev/null}")" || {
        msgbox "$(i18n resh_title)" "$(i18n resh_failed "${WT_SESSION_LOG:-}")"
        return 1
    }
    local log="${WT_LOG_DIR:-/userdata/system/logs/ultimate-wine-toolbox}/reshade-install-$(date +%Y%m%d-%H%M%S)-$$.log"
    mkdir -p "$(dirname "$log")"
    ls -1t "$(dirname "$log")"/reshade-install-*.log 2>/dev/null | tail -n +20 | while IFS= read -r oldlog; do
        [ -z "$oldlog" ] || rm -f -- "$oldlog"
    done
    msgbox "$(i18n resh_title)" "$(i18n resh_download_wait "$log")" || return 1
    local shim="$WT_HOME/reshade/bin"
    resh_prepare_tools || return 1
    (
        exec 9> "$WT_HOME/reshade/runtime.lock"
        flock 9
        MAIN_PATH="$WT_HOME/reshade/runtime" WINEPREFIX="" UI_BACKEND=cli \
            RESHADE_VERSION="$version" RESHADE_ADDON_SUPPORT=0 NO_COLOR=1 PROGRESS_UI=0 \
            PATH="$shim:$PATH" bash "$RESH_BACKEND" --cli --game-path="$workspace" \
            --dll-override="$dll" --shader-repos="$packs" <<< i
    ) >> "$log" 2>&1 && resh_cmd finish "$rom" >> "$log" 2>&1 || {
        msgbox "$(i18n resh_title)" "$(i18n resh_failed "$log")"
        return 1
    }
    if ! resh_cmd enable "$rom" >> "$log" 2>&1; then
        msgbox "$(i18n resh_title)" "$(i18n resh_failed "$log")"
        return 1
    fi
    msgbox "$(i18n resh_title)" "$(i18n resh_installed "$log")"
}

resh_external_menu() {
    local rom="$1" details="$2" state="${2%%$'\n'*}" choice label
    while true; do
        case "$state" in
            external-enabled) label="$(i18n resh_external_enabled)" ;;
            external-disabled) label="$(i18n resh_external_disabled)" ;;
            *) label="$(i18n resh_external_unknown)" ;;
        esac
        choice="$(menu_select "$(i18n resh_title) — ${rom##*/}" "$(i18n resh_external_info "$label"$'\n'"${details#*$'\n'}")" \
            enable "$(i18n resh_enable)" disable "$(i18n resh_disable)" \
            release "$(i18n resh_external_release)" diagnostic "$(i18n resh_diag_title)" back "$(i18n back)")" || return
        case "$choice" in
            enable|disable)
                if [ "$state" = external-unsupported ]; then
                    msgbox "$(i18n resh_title)" "$(i18n resh_external_unsupported)"; continue
                fi
                resh_cmd "external-$choice" "$rom" >> "${WT_SESSION_LOG:-/dev/null}" 2>&1 && {
                    msgbox "$(i18n resh_title)" "$(i18n resh_external_done)"
                } || msgbox "$(i18n resh_title)" "$(i18n resh_failed "${WT_SESSION_LOG:-}")" ;;
            release)
                resh_cmd external-release "$rom" >> "${WT_SESSION_LOG:-/dev/null}" 2>&1 || {
                    msgbox "$(i18n resh_title)" "$(i18n resh_failed "${WT_SESSION_LOG:-}")"; continue;
                }
                return ;;
            diagnostic) resh_diagnostic "$rom" && exit 0 ;;
            *) return ;;
        esac
        details="$(resh_cmd external-info "$rom")"; state="${details%%$'\n'*}"
    done
}

resh_game_menu() {
    local rom="$1" state choice preset profile details version arch dll exe packs prompt
    while true; do
        state="$(resh_cmd status "$rom")" || return
        if [ "$state" = missing ]; then
            details="$(resh_cmd external-info "$rom" 2>> "${WT_SESSION_LOG:-/dev/null}")" || {
                msgbox "$(i18n resh_title)" "$(i18n resh_failed "${WT_SESSION_LOG:-}")"; return;
            }
            case "${details%%$'\n'*}" in
                external-*) resh_external_menu "$rom" "$details"; return ;;
            esac
        fi
        prompt="$(i18n resh_game_status "$(i18n "resh_status_$state")")"
        if [ "$state" != missing ]; then
            details="$(resh_cmd details "$rom")" || return
            IFS=$'\t' read -r version arch dll exe packs <<< "$details"
            prompt+="\n\n$(i18n resh_details "$version" "$arch" "$dll" "$exe" "$packs")"
        fi
        choice="$(menu_select "$(i18n resh_title) — $(basename "$rom")" \
            "$prompt" \
            install "$(i18n resh_install)" enable "$(i18n resh_enable)" disable "$(i18n resh_disable)" \
            preset "$(i18n resh_preset)" export "$(i18n resh_export_title)" profile "$(i18n resh_profile)" uninstall "$(i18n resh_uninstall)" \
            back "$(i18n back)")" || return
        case "$choice" in
            install) resh_install_game "$rom" ;;
            enable|disable)
                resh_cmd "$choice" "$rom" >> "${WT_SESSION_LOG:-/dev/null}" 2>&1 || {
                    msgbox "$(i18n resh_title)" "$(i18n resh_failed "${WT_SESSION_LOG:-}")"
                } ;;
            uninstall)
                yesno_default_no "$(i18n resh_title)" "$(i18n resh_uninstall_confirm)" || continue
                resh_cmd uninstall "$rom" >> "${WT_SESSION_LOG:-/dev/null}" 2>&1 || {
                    msgbox "$(i18n resh_title)" "$(i18n resh_failed "${WT_SESSION_LOG:-}")"
                } ;;
            preset|export)
                if [ "$state" = missing ]; then
                    msgbox "$(i18n resh_title)" "$(i18n resh_install_first)"
                    continue
                fi
                if [ "$choice" = preset ]; then
                    preset="$(resh_preset_file import "$rom")" || continue
                    resh_cmd preset "$rom" "$preset" >> "${WT_SESSION_LOG:-/dev/null}" 2>&1 || {
                        msgbox "$(i18n resh_title)" "$(i18n resh_failed "${WT_SESSION_LOG:-}")"
                    }
                else
                    preset="$(resh_preset_file export "$rom")" || continue
                    resh_cmd export "$rom" "$preset" overwrite >> "${WT_SESSION_LOG:-/dev/null}" 2>&1 && {
                        msgbox "$(i18n resh_title)" "$(i18n resh_export_done "$preset")"
                    } || msgbox "$(i18n resh_title)" "$(i18n resh_failed "${WT_SESSION_LOG:-}")"
                fi ;;
            profile)
                profile="$(resh_cmd profile "$rom")" || continue
                msgbox "$(i18n resh_title)" "$(i18n resh_profile_path "$profile")" ;;
            back|"") return ;;
        esac
    done
}

resh_game_rows() {
    case "${1:-all}" in
        enabled|installed) python3 "$RESH_HELPER" --home "$WT_HOME" configured-list "$1" ;;
        *) mangohud_list_games | python3 "$RESH_HELPER" --home "$WT_HOME" status-list ;;
    esac
}

resh_pick_game() {
    local filter="${1:-all}" query="${2:-}" rom choice path name state label enabled_label disabled_label missing_label external_enabled external_disabled external_unsupported
    local -a games=() items=()
    enabled_label="$(i18n resh_status_enabled)"
    disabled_label="$(i18n resh_status_disabled)"
    missing_label="$(i18n resh_status_missing)"
    external_enabled="$(i18n resh_external_enabled)"
    external_disabled="$(i18n resh_external_disabled)"
    external_unsupported="$(i18n resh_external_unknown)"
    while IFS= read -r -d '' path && IFS= read -r -d '' state; do
        name="${path##*/}"
        [[ -z "$query" || "${name,,}" == *"${query,,}"* ]] || continue
        games+=("$path")
        case "$state" in
            enabled) label="$enabled_label" ;;
            disabled) label="$disabled_label" ;;
            external-enabled) label="$external_enabled" ;;
            external-disabled) label="$external_disabled" ;;
            external-unsupported) label="$external_unsupported" ;;
            *) label="$missing_label" ;;
        esac
        items+=("${#games[@]}" "$name — $label")
    done < <(resh_game_rows "$filter" 2>> "${WT_SESSION_LOG:-/dev/null}")
    [ "${#games[@]}" -gt 0 ] || { msgbox "$(i18n resh_title)" "$(i18n resh_no_match)"; return; }
    choice="$(menu_select "$(i18n resh_title)" "$(i18n resh_game_prompt)" "${items[@]}")" || return
    case "$choice" in ''|*[!0-9]*) return ;; esac
    [ "$choice" -ge 1 ] && [ "$choice" -le "${#games[@]}" ] || return
    rom="${games[$((choice-1))]}"
    resh_game_menu "$rom"
}

resh_menu() {
    local choice query
    msgbox "$(i18n resh_title)" "$(i18n resh_intro)" || return
    while true; do
        choice="$(menu_select "$(i18n resh_title)" "$(i18n resh_list_prompt)" \
            all "$(i18n resh_list_all)" installed "$(i18n resh_list_installed)" \
            scan "$(i18n resh_external_scan)" search "$(i18n resh_list_search)" back "$(i18n back)")" || return
        case "$choice" in
            installed|all) resh_pick_game "$choice" ;;
            scan)
                msgbox "$(i18n resh_title)" "$(i18n resh_external_scan_wait)" || continue
                local scan_log="${WT_LOG_DIR:-/userdata/system/logs/ultimate-wine-toolbox}/reshade-discovery.log"
                mkdir -p "${scan_log%/*}"
                : > "$scan_log"
                if have_dialog; then
                    dialog --no-shadow --title "$(i18n resh_title)" --infobox "$(i18n resh_external_scan_wait)" 14 90 || true
                fi
                local summary total completed failures
                if summary="$(mangohud_list_games | resh_cmd external-scan 2>> "$scan_log")"; then
                    IFS=$'\t' read -r total completed failures <<< "$summary"
                    if [ "${failures:-0}" -gt 0 ]; then
                        msgbox "$(i18n resh_title)" "$(i18n resh_external_scan_partial "$completed" "$total" "$failures" "$scan_log")"
                    else
                        msgbox "$(i18n resh_title)" "$(i18n resh_external_scan_done)"
                    fi
                else
                    msgbox "$(i18n resh_title)" "$(i18n resh_failed "$scan_log")"
                fi
                resh_pick_game installed ;;

            search)
                query="$(input_text "$(i18n resh_title)" "$(i18n resh_search_prompt)" "")" || continue
                [ -z "$query" ] || resh_pick_game all "$query" ;;
            *) return ;;
        esac
    done
}
