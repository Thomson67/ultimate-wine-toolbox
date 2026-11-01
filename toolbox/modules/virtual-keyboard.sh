#!/bin/bash

osk_cmd() {
    python3 "$WT_ROOT/helpers/virtual_keyboard.py" --home "$WT_HOME" "$@"
}

osk_label() {
    case "$1" in on) i18n enabled ;; off) i18n disabled ;; *) i18n osk_inherit ;; esac
}

osk_game_menu() {
    local rom selected state rows idx=1
    local -a games=() items=()
    local -A labels=([on]="$(osk_label on)" [off]="$(osk_label off)" [inherit]="$(osk_label inherit)")
    local -A WT_MENU_GAME_LABELS=()
    if have_dialog; then
        wt_clear_tty
        dialog --no-shadow --title "$(i18n osk_game)" --infobox "$(i18n osk_loading_games)" 8 80 >&2 || true
    fi
    if ! rows="$(mangohud_list_games | osk_cmd game-states)"; then
        msgbox "$(i18n osk_title)" "$(i18n osk_config_error)"; return
    fi
    while IFS=$'\t' read -r state rom; do
        [ -n "$rom" ] || continue
        games+=("$rom")
        WT_MENU_GAME_LABELS["$idx"]="${rom##*/}"
        items+=("$idx" "${rom##*/} — ${labels[$state]}")
        idx=$((idx+1))
    done <<< "$rows"
    if [ "${#games[@]}" -eq 0 ]; then
        msgbox "$(i18n osk_title)" "$(i18n mangohud_no_games)"; return
    fi
    selected="$(WT_MENU_LIST=1 menu_select "$(i18n osk_game)" "$(i18n osk_game_help)" "${items[@]}" back "$(i18n back)")" || return
    [[ "$selected" =~ ^[0-9]+$ ]] || return
    [ "$selected" -ge 1 ] && [ "$selected" -le "${#games[@]}" ] || return
    rom="${games[$((selected-1))]}"
    state="$(menu_select "$(basename "$rom")" "$(i18n osk_game_help)" \
        inherit "$(i18n osk_inherit)" on "$(i18n enabled)" off "$(i18n disabled)" back "$(i18n back)")" || return
    case "$state" in on|off|inherit) osk_cmd set --rom "$rom" --value "$state" || msgbox "$(i18n osk_title)" "$(i18n osk_config_error)" ;; esac
}

virtual_keyboard_menu() {
    local choice global report
    while true; do
        global="$(osk_cmd get)" || { msgbox "$(i18n osk_title)" "$(i18n osk_config_error)"; return; }
        choice="$(menu_select "$(i18n osk_title)" "$(i18n osk_intro)\n\n$(i18n osk_global) : $(osk_label "$global")" \
            on "$(i18n osk_global_on)" off "$(i18n osk_global_off)" \
            games "$(i18n osk_game)" \
            preview "$(i18n osk_preview)" back "$(i18n back)")" || return
        case "$choice" in
            on|off) osk_cmd set --value "$choice" || msgbox "$(i18n osk_title)" "$(i18n osk_config_error)" ;;
            games) osk_game_menu ;;
            preview)
                report="$(osk_cmd preview 2>&1)" || msgbox "$(i18n osk_title)" "$report" ;;
            *) return ;;
        esac
    done
}
