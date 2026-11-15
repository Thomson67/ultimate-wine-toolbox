#!/bin/bash

osk_cmd() {
    python3 "$WT_ROOT/helpers/virtual_keyboard.py" --home "$WT_HOME" --feature "${virtual_feature:-keyboard}" "$@"
}

osk_label() {
    case "$1" in on) i18n enabled ;; off) i18n disabled ;; *) i18n osk_inherit ;; esac
}

osk_game_menu() {
    local mode="${1:-all}" rom selected state rows idx=1 title prompt empty_message
    title="$(i18n osk_game)"; prompt="$(i18n osk_game_help)"; empty_message="$(i18n mangohud_no_games)"
    local feature_title="$(i18n "${virtual_title:-osk_title}")"
    local error_key="${virtual_error:-osk_config_error}"
    [ "${virtual_feature:-keyboard}" != mouse ] || prompt="$(i18n mouse_game_help)"
    local -a games=() items=()
    local -A labels=([on]="$(osk_label on)" [off]="$(osk_label off)" [inherit]="$(osk_label inherit)")
    local -A WT_MENU_GAME_LABELS=()
    if [ "$mode" = configured ]; then
        title="$(i18n osk_configured)"; prompt="$(i18n osk_configured_help)"
        empty_message="$(i18n osk_no_configured)"
        if ! rows="$(osk_cmd configured-games)"; then
            msgbox "$feature_title" "$(i18n "$error_key")"; return
        fi
    else
        if have_dialog; then
            wt_clear_tty
            dialog --no-shadow --title "$title" --infobox "$(i18n osk_loading_games)" 8 80 >&2 || true
        fi
        if ! rows="$(mangohud_list_games | osk_cmd game-states)"; then
            msgbox "$feature_title" "$(i18n "$error_key")"; return
        fi
    fi
    while IFS=$'\t' read -r state rom; do
        [ -n "$rom" ] || continue
        games+=("$rom")
        WT_MENU_GAME_LABELS["$idx"]="${rom##*/}"
        items+=("$idx" "${rom##*/} — ${labels[$state]}")
        idx=$((idx+1))
    done <<< "$rows"
    if [ "${#games[@]}" -eq 0 ]; then
        msgbox "$feature_title" "$empty_message"; return
    fi
    selected="$(WT_MENU_LIST=1 menu_select "$title" "$prompt" "${items[@]}" back "$(i18n back)")" || return
    [[ "$selected" =~ ^[0-9]+$ ]] || return
    [ "$selected" -ge 1 ] && [ "$selected" -le "${#games[@]}" ] || return
    rom="${games[$((selected-1))]}"
    state="$(menu_select "${rom##*/}" "$prompt" \
        inherit "$(i18n osk_inherit)" on "$(i18n enabled)" off "$(i18n disabled)" back "$(i18n back)")" || return
    case "$state" in on|off|inherit) osk_cmd set --rom "$rom" --value "$state" || msgbox "$feature_title" "$(i18n "$error_key")" ;; esac
}

virtual_keyboard_menu() {
    local virtual_feature="${1:-keyboard}" virtual_title=osk_title virtual_error=osk_config_error intro=osk_intro
    local choice global report title
    local -a extra=(preview "$(i18n osk_preview)")
    if [ "$virtual_feature" = mouse ]; then
        virtual_title=mouse_title
        virtual_error=mouse_config_error
        intro=mouse_intro
        extra=()
    fi
    title="$(i18n "$virtual_title")"
    while true; do
        global="$(osk_cmd get)" || { msgbox "$title" "$(i18n "$virtual_error")"; return; }
        choice="$(menu_select "$title" "$(i18n "$intro")\n\n$(i18n osk_global) : $(osk_label "$global")" \
            on "$(i18n osk_global_on)" off "$(i18n osk_global_off)" \
            games "$(i18n osk_game)" configured "$(i18n osk_configured)" \
            "${extra[@]}" back "$(i18n back)")" || return
        case "$choice" in
            on|off) osk_cmd set --value "$choice" || msgbox "$title" "$(i18n "$virtual_error")" ;;
            games) osk_game_menu ;;
            configured) osk_game_menu configured ;;
            preview)
                report="$(osk_cmd preview 2>&1)" || msgbox "$(i18n osk_title)" "$report" ;;
            *) return ;;
        esac
    done
}
