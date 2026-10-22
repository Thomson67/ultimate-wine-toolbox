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
    local profile=default
    [ ! -s "$MANGOHUD_CONFIG_DIR/mangohud-profile" ] || profile="$(head -n1 "$MANGOHUD_CONFIG_DIR/mangohud-profile")"
    case "$profile" in minimal|detailed) ;; *) profile=default ;; esac
    printf '%s' "$profile"
}

mangohud_profile_menu() {
    local choice current profile tmp
    local -a items=()
    current="$(mangohud_profile_state)"
    items+=("$current" "$(i18n "mangohud_profile_$current")")
    for profile in default minimal detailed; do
        [ "$profile" = "$current" ] || items+=("$profile" "$(i18n "mangohud_profile_$profile")")
    done
    choice="$(menu_select "$(i18n mangohud_profile_title)" "$(i18n mangohud_profile_prompt)" \
        "${items[@]}" 0 "$(i18n back)")" || return
    case "$choice" in default|minimal|detailed) ;; *) return ;; esac
    mkdir -p "$MANGOHUD_CONFIG_DIR" || return
    tmp="$(mktemp "$MANGOHUD_CONFIG_DIR/.mangohud-profile.XXXXXX")" || return
    printf '%s\n' "$choice" > "$tmp"
    mv -f -- "$tmp" "$MANGOHUD_CONFIG_DIR/mangohud-profile" || { rm -f -- "$tmp"; return; }
    msgbox "$(i18n mangohud_profile_title)" "$(i18n mangohud_profile_applied "$(i18n "mangohud_profile_$choice")")"
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
            "0" "$(i18n back)")" || return

        case "$choice" in
            1) mangohud_set_global 1 ;;
            2) mangohud_set_global 0 ;;
            3) mangohud_game_menu ;;
            4) mangohud_disable_individual_menu ;;
            5) mangohud_profile_menu ;;
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
