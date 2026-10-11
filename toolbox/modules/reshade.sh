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

resh_install_game() {
    local rom="$1" exe selected dll version packs state workspace name label
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
    dll="$(menu_select "$(i18n resh_title)" "$(i18n resh_api_prompt)" \
        dxgi "DirectX 10 / 11 / 12 (dxgi)" d3d9 "DirectX 9 (d3d9)" opengl32 "OpenGL (opengl32)")" || return 1
    case "$dll" in dxgi|d3d9|opengl32) ;; *) return 1 ;; esac
    version="$(input_text "$(i18n resh_title)" "$(i18n resh_version_prompt)" latest)" || return 1
    [[ "$version" =~ ^(latest|[0-9]+\.[0-9]+\.[0-9]+)$ ]] || {
        msgbox "$(i18n resh_title)" "$(i18n resh_version_invalid)"
        return 1
    }
    resh_backend_ready || return 1
    items=()
    while IFS=$'\t' read -r name label; do
        name="${name#  }"
        [[ "$name" =~ ^[a-z0-9_-]+$ ]] && [ -n "$label" ] || continue
        state=off
        case "$name" in reshade-shaders|sweetfx-shaders) state=on ;; esac
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

resh_game_menu() {
    local rom="$1" state choice preset profile details version arch dll exe packs prompt
    while true; do
        state="$(resh_cmd status "$rom")" || return
        prompt="$(i18n resh_game_status "$(i18n "resh_status_$state")")"
        if [ "$state" != missing ]; then
            details="$(resh_cmd details "$rom")" || return
            IFS=$'\t' read -r version arch dll exe packs <<< "$details"
            prompt+="\n\n$(i18n resh_details "$version" "$arch" "$dll" "$exe" "$packs")"
        fi
        choice="$(menu_select "$(i18n resh_title) — $(basename "$rom")" \
            "$prompt" \
            install "$(i18n resh_install)" enable "$(i18n resh_enable)" disable "$(i18n resh_disable)" \
            preset "$(i18n resh_preset)" profile "$(i18n resh_profile)" uninstall "$(i18n resh_uninstall)" \
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
            preset)
                if [ "$state" = missing ]; then
                    msgbox "$(i18n resh_title)" "$(i18n resh_install_first)"
                    continue
                fi
                preset="$(input_text "$(i18n resh_title)" "$(i18n resh_preset_prompt)" /userdata/)" || continue
                resh_cmd preset "$rom" "$preset" >> "${WT_SESSION_LOG:-/dev/null}" 2>&1 || {
                    msgbox "$(i18n resh_title)" "$(i18n resh_failed "${WT_SESSION_LOG:-}")"
                } ;;
            profile)
                profile="$(resh_cmd profile "$rom")" || continue
                msgbox "$(i18n resh_title)" "$(i18n resh_profile_path "$profile")" ;;
            back|"") return ;;
        esac
    done
}

resh_menu() {
    local rom choice path state label enabled_label disabled_label missing_label
    local -a games=() items=()
    msgbox "$(i18n resh_title)" "$(i18n resh_intro)" || return
    enabled_label="$(i18n resh_status_enabled)"
    disabled_label="$(i18n resh_status_disabled)"
    missing_label="$(i18n resh_status_missing)"
    while IFS= read -r -d '' path && IFS= read -r -d '' state; do
        games+=("$path")
        case "$state" in
            enabled) label="$enabled_label" ;;
            disabled) label="$disabled_label" ;;
            *) label="$missing_label" ;;
        esac
        items+=("${#games[@]}" "${path##*/} — $label")
    done < <(mangohud_list_games | python3 "$RESH_HELPER" --home "$WT_HOME" status-list \
        2>> "${WT_SESSION_LOG:-/dev/null}")
    [ "${#games[@]}" -gt 0 ] || { msgbox "$(i18n resh_title)" "$(i18n mangohud_no_games)"; return; }
    choice="$(menu_select "$(i18n resh_title)" "$(i18n resh_game_prompt)" "${items[@]}")" || return
    case "$choice" in ''|*[!0-9]*) return ;; esac
    [ "$choice" -ge 1 ] && [ "$choice" -le "${#games[@]}" ] || return
    rom="${games[$((choice-1))]}"
    resh_game_menu "$rom"
}
