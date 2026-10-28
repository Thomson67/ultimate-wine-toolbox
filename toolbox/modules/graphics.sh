#!/bin/bash

MANGOHUD_CONFIG_DIR="$WT_HOME/config"
MANGOHUD_GLOBAL_FILE="$MANGOHUD_CONFIG_DIR/mangohud-global"
MANGOHUD_OVERRIDE_FILE="$MANGOHUD_CONFIG_DIR/mangohud-games.tsv"
WINDOWS_ROMS="/userdata/roms/windows"

mangohud_global_state() {
    local v="0"
    [ -s "$MANGOHUD_GLOBAL_FILE" ] && v="$(head -n1 "$MANGOHUD_GLOBAL_FILE" | tr -d '\r\n[:space:]')"
    case "$v" in
        1|on|ON|true|TRUE) printf '%s' "$(i18n enabled)" ;;
        *) printf '%s' "$(i18n disabled)" ;;
    esac
}

mangohud_set_global() {
    local value="$1"
    mkdir -p "$MANGOHUD_CONFIG_DIR"
    printf '%s\n' "$value" > "$MANGOHUD_GLOBAL_FILE"
    if [ "$value" = "1" ]; then
        msgbox "$(i18n mangohud_title)" "$(i18n mangohud_global_enabled)"
    else
        msgbox "$(i18n mangohud_title)" "$(i18n mangohud_global_disabled)"
    fi
}

mangohud_game_override() {
    local path="$1" v
    [ -s "$MANGOHUD_OVERRIDE_FILE" ] || { printf '%s' "inherit"; return; }
    v="$(awk -F '\t' -v p="$path" '$2==p {v=$1} END{print v}' "$MANGOHUD_OVERRIDE_FILE")"
    case "$v" in
        on|off) printf '%s' "$v" ;;
        *) printf '%s' "inherit" ;;
    esac
}

mangohud_override_label() {
    case "$1" in
        on) printf '%s' "$(i18n enabled)" ;;
        off) printf '%s' "$(i18n disabled)" ;;
        *) printf '%s' "$(i18n mangohud_inherit)" ;;
    esac
}

mangohud_set_game_override() {
    local path="$1" state="$2" tmp
    mkdir -p "$MANGOHUD_CONFIG_DIR"
    tmp="$(mktemp /tmp/wt-mangohud-overrides.XXXXXX)" || return 1

    if [ -s "$MANGOHUD_OVERRIDE_FILE" ]; then
        awk -F '\t' -v p="$path" '$2!=p' "$MANGOHUD_OVERRIDE_FILE" > "$tmp"
    fi

    case "$state" in
        on|off) printf '%s\t%s\n' "$state" "$path" >> "$tmp" ;;
    esac

    mv -f "$tmp" "$MANGOHUD_OVERRIDE_FILE"
}

mangohud_list_games() {
    [ -d "$WINDOWS_ROMS" ] || return 0
    find "$WINDOWS_ROMS" -mindepth 1 \
        \( -name '.*' -prune \) -o \
        \( -type d \( -iname '*.pc' -o -iname '*.wine' \) -print -prune \) -o \
        \( -type f \( -iname '*.wsquashfs' -o -iname '*.wtgz' \) -print \) \
        2>/dev/null | sort -f
}

mangohud_game_menu() {
    local -a items=()
    local rows="" path state selected="" id count=0 failures=0 idx=1

    while IFS= read -r path; do
        [ -n "$path" ] || continue
        state="$(mangohud_game_override "$path")"

        if [ "$state" = "on" ]; then
            items+=("$idx" "$(basename "$path")" "on")
        else
            items+=("$idx" "$(basename "$path")" "off")
        fi

        rows+="$path"$'\n'
        idx=$((idx+1))
        count=$((count+1))
    done < <(mangohud_list_games)

    if [ "$count" -eq 0 ]; then
        msgbox "$(i18n mangohud_per_game)" "$(i18n mangohud_no_games)"
        return
    fi

    selected="$(checklist_select "$(i18n mangohud_per_game)" \
        "$(i18n mangohud_enable_multi_prompt)" \
        "${items[@]}")" || return

    if [ -z "$selected" ]; then
        msgbox "$(i18n mangohud_per_game)" "$(i18n mangohud_select_none)"
        return
    fi

    while IFS= read -r id; do
        [ -n "$id" ] || continue
        path="$(sed -n "${id}p" <<< "$rows")"
        [ -n "$path" ] || { failures=$((failures+1)); continue; }
        mangohud_set_game_override "$path" on || failures=$((failures+1))
    done <<< "$selected"

    if [ "$failures" -eq 0 ]; then
        msgbox "$(i18n mangohud_per_game)" "$(i18n mangohud_enable_multi_done)"
    else
        msgbox "$(i18n mangohud_per_game)" "$(i18n mangohud_enable_multi_partial)"
    fi
}
mangohud_disable_individual_menu() {
    local -a items=()
    local rows="" state path selected="" id count=0 failures=0 idx=1

    if [ ! -s "$MANGOHUD_OVERRIDE_FILE" ]; then
        msgbox "$(i18n mangohud_disable_individual)" "$(i18n mangohud_no_individual_enabled)"
        return
    fi

    while IFS=$'\t' read -r state path; do
        [ "$state" = "on" ] || continue
        [ -n "$path" ] || continue

        items+=("$idx" "$(basename "$path")" "off")
        rows+="$path"$'\n'
        idx=$((idx+1))
        count=$((count+1))
    done < "$MANGOHUD_OVERRIDE_FILE"

    if [ "$count" -eq 0 ]; then
        msgbox "$(i18n mangohud_disable_individual)" "$(i18n mangohud_no_individual_enabled)"
        return
    fi

    selected="$(checklist_select "$(i18n mangohud_disable_individual)" \
        "$(i18n mangohud_disable_individual_prompt)" \
        "${items[@]}")" || return

    if [ -z "$selected" ]; then
        msgbox "$(i18n mangohud_disable_individual)" "$(i18n mangohud_select_none)"
        return
    fi

    while IFS= read -r id; do
        [ -n "$id" ] || continue
        path="$(sed -n "${id}p" <<< "$rows")"
        [ -n "$path" ] || { failures=$((failures+1)); continue; }
        mangohud_set_game_override "$path" inherit || failures=$((failures+1))
    done <<< "$selected"

    if [ "$failures" -eq 0 ]; then
        msgbox "$(i18n mangohud_disable_individual)" "$(i18n mangohud_disable_individual_done)"
    else
        msgbox "$(i18n mangohud_disable_individual)" "$(i18n mangohud_disable_individual_partial)"
    fi
}
mangohud_profile_state() {
    mangohud_setting_get display "" --effective
}

mangohud_profile_menu() {
    local choice current profile
    local -a items=()
    current="$(mangohud_profile_state)"
    items+=("$current" "$(i18n "mangohud_profile_$current")")
    for profile in default minimal detailed hidden; do
        [ "$profile" = "$current" ] || items+=("$profile" "$(i18n "mangohud_profile_$profile")")
    done
    choice="$(menu_select "$(i18n mangohud_profile_title)" "$(i18n mangohud_profile_prompt)" \
        "${items[@]}" 0 "$(i18n back)")" || return
    case "$choice" in default|minimal|detailed|hidden) ;; *) return ;; esac
    mangohud_setting_set display "$choice" "" || return
    msgbox "$(i18n mangohud_profile_title)" "$(i18n mangohud_profile_applied "$(i18n "mangohud_profile_$choice")")"
}

mangohud_setting_get() {
    local key="$1" game="${2:-}"
    shift 2
    python3 "$WT_ROOT/helpers/mangohud_settings.py" get "$MANGOHUD_CONFIG_DIR" "$key" --game "$game" "$@"
}

mangohud_setting_set() {
    python3 "$WT_ROOT/helpers/mangohud_settings.py" set "$MANGOHUD_CONFIG_DIR" "$1" "$2" --game "${3:-}" || {
        msgbox "$(i18n mangohud_controls)" "$(i18n mangohud_settings_error)"
        return 1
    }
}

mangohud_setting_label() {
    local key="$1" value="$2" game="${3:-}"
    case "$value" in
        inherit)
            if [ -n "$game" ]; then
                printf '%s (%s)' "$(i18n mangohud_inherit)" \
                    "$(mangohud_setting_label "$key" "$(mangohud_setting_get "$key" "$game" --effective)" "")"
            else
                i18n mangohud_application
            fi ;;
        *)
            if [ "$key" = display ]; then
                i18n "mangohud_profile_$value"
            elif [ "$key" = fps ]; then
                if [ "$value" = 0 ]; then i18n mangohud_unlimited; else printf '%s FPS' "$value"; fi
            else
                i18n "mangohud_value_$value"
            fi ;;
    esac
}

mangohud_control_edit() {
    local key="$1" game="${2:-}" current choice value
    local -a values=() items=()
    current="$(mangohud_setting_get "$key" "$game")" || return
    if [ "$key" = fps ]; then
        items+=("$current" "$(mangohud_setting_label fps "$current" "$game")")
        for value in inherit 0 30 40 60 90 120 144 165 240; do
            [ "$value" = "$current" ] || items+=("$value" "$(mangohud_setting_label fps "$value" "$game")")
        done
        choice="$(menu_select "$(i18n mangohud_fps)" "$(i18n mangohud_fps_help)" \
            "${items[@]}" custom "$(i18n mangohud_custom)" back "$(i18n back)")" || return
        case "$choice" in
            custom)
                [ "$current" != inherit ] || current=60
                choice="$(input_text "$(i18n mangohud_fps)" "$(i18n mangohud_fps_input)" "$current")" || return ;;
            inherit) ;;
            *) [[ "$choice" =~ ^[0-9]+$ ]] || return ;;
        esac
        mangohud_setting_set "$key" "$choice" "$game"
        return
    fi
    case "$key" in
        display) values=(default minimal detailed hidden) ;;
        vulkan) values=(off mailbox on adaptive) ;;
        opengl) values=(off on) ;;
        method) values=(early late) ;;
        *) return ;;
    esac
    # Put the current selection first; menu_select has no default-item API.
    items+=("$current" "$(mangohud_setting_label "$key" "$current" "$game")")
    for value in inherit "${values[@]}"; do
        [ "$value" = "$current" ] || items+=("$value" "$(mangohud_setting_label "$key" "$value" "$game")")
    done
    choice="$(menu_select "$(i18n "mangohud_$key")" "$(i18n "mangohud_${key}_help")" \
        "${items[@]}" back "$(i18n back)")" || return
    [ "$choice" != back ] && [ -n "$choice" ] || return
    mangohud_setting_set "$key" "$choice" "$game"
}

mangohud_controls_menu() {
    local game="${1:-}" choice key value target
    local -a items=()
    target="$(i18n mangohud_global_controls)"
    [ -z "$game" ] || target="$(basename "$game")"
    while true; do
        items=()
        for key in display vulkan opengl fps method; do
            value="$(mangohud_setting_get "$key" "$game")" || return
            if [ -z "$game" ] && [ "$key" = display ]; then
                value="$(mangohud_setting_get display "" --effective)" || return
            fi
            items+=("$key" "$(i18n "mangohud_$key") : $(mangohud_setting_label "$key" "$value" "$game")")
        done
        choice="$(menu_select "$target" "$(i18n mangohud_controls_help)" \
            "${items[@]}" reset "$(i18n mangohud_controls_reset)" back "$(i18n back)")" || return
        case "$choice" in
            display|vulkan|opengl|fps|method) mangohud_control_edit "$choice" "$game" ;;
            reset)
                for key in display vulkan opengl fps method; do
                    mangohud_setting_set "$key" inherit "$game" || return
                done ;;
            *) return ;;
        esac
    done
}

mangohud_game_controls_menu() {
    local path selected idx=1
    local -a paths=() items=()
    while IFS= read -r path; do
        paths+=("$path")
        items+=("$idx" "$(basename "$path")")
        idx=$((idx+1))
    done < <(mangohud_list_games)
    if [ "${#paths[@]}" -eq 0 ]; then
        msgbox "$(i18n mangohud_controls)" "$(i18n mangohud_no_games)"
        return
    fi
    selected="$(menu_select "$(i18n mangohud_game_controls)" "$(i18n mangohud_controls_help)" \
        "${items[@]}" back "$(i18n back)")" || return
    [[ "$selected" =~ ^[0-9]+$ ]] || return
    [ "$selected" -ge 1 ] && [ "$selected" -le "${#paths[@]}" ] || return
    mangohud_controls_menu "${paths[$((selected-1))]}"
}

mangohud_menu() {
    while true; do
        local choice
        choice="$(menu_select "$(i18n mangohud_title)" \
            "$(i18n mangohud_intro)\n\n$(i18n mangohud_global_status "$(mangohud_global_state)")" \
            "1" "$(i18n mangohud_enable_global)" \
            "2" "$(i18n mangohud_disable_global)" \
            "3" "$(i18n mangohud_per_game)" \
            "4" "$(i18n mangohud_disable_individual)" \
            "5" "$(i18n mangohud_profile_title)" \
            "6" "$(i18n mangohud_global_controls)" \
            "7" "$(i18n mangohud_game_controls)" \
            "0" "$(i18n back)")" || return

        case "$choice" in
            1) mangohud_set_global 1 ;;
            2) mangohud_set_global 0 ;;
            3) mangohud_game_menu ;;
            4) mangohud_disable_individual_menu ;;
            5) mangohud_profile_menu ;;
            6) mangohud_controls_menu ;;
            7) mangohud_game_controls_menu ;;
            0|"") return ;;
        esac
    done
}

graphics_menu() {
    while true; do
        local choice
        choice="$(menu_select "$(i18n graphics_title)" \
            "$(i18n graphics_intro)" \
            "1" "$(i18n mangohud_title)" \
            "2" "$(i18n dxvk_manager)" \
            "3" "$(i18n resh_title)" \
            "4" "AntiMicroX" \
            "5" "$(i18n winetricks_tools_title)" \
            "0" "$(i18n back)")" || return

        case "$choice" in
            1) mangohud_menu ;;
            2) dxvk_manager_menu ;;
            3) resh_menu ;;
            4) antimicrox_menu ;;
            5) winetricks_game_menu ;;
            0|"") return ;;
        esac
    done
}
