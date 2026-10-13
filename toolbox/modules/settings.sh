#!/bin/bash

language_menu() {
    while true; do
        local choice
        choice="$(menu_select "$(i18n language_title)" "$(i18n language_title)"             "fr" "Français"             "en" "English"             "0" "$(i18n back)")" || return

        case "$choice" in
            fr|en)
                WT_LANGUAGE="$choice"
                save_language
                load_i18n
                msgbox "$(i18n language_changed)" "$(i18n language_changed_body)"
                ;;
            0|"") return ;;
        esac
    done
}

display_mode_menu() {
    local choice mode font prompt
    while true; do
        mode="$(cat "$WT_CONFIG/display-mode" 2>/dev/null || true)"
        font="$(cat "$WT_CONFIG/font-size" 2>/dev/null || true)"
        case "$mode" in fullscreen) ;; *) mode=normal ;; esac
        case "$font" in 11|13|16|18|20) ;; *) font=11 ;; esac
        if [ "$WT_LANGUAGE" = fr ]; then
            prompt="Fenêtre : $mode | Police : $font. Relancer depuis Ports pour appliquer."
            choice="$(menu_select "Affichage" "$prompt" "w" "Fenêtre : Normal / Plein écran" "f" "Taille de police : 11 / 13 / 16 / 18 / 20" "0" "Retour")" || return
        else
            prompt="Window: $mode | Font: $font. Relaunch from Ports to apply."
            choice="$(menu_select "Display" "$prompt" "w" "Window: Normal / Fullscreen" "f" "Font size: 11 / 13 / 16 / 18 / 20" "0" "Back")" || return
        fi
        case "$choice" in
            w)
                if [ "$WT_LANGUAGE" = fr ]; then
                    choice="$(menu_select "Fenêtre" "Mode de fenêtre" "normal" "Normal" "fullscreen" "Plein écran" "0" "Retour")" || continue
                else
                    choice="$(menu_select "Window" "Window mode" "normal" "Normal" "fullscreen" "Fullscreen" "0" "Back")" || continue
                fi
                case "$choice" in normal|fullscreen)
                    mkdir -p "$WT_CONFIG"
                    printf '%s\n' "$choice" > "$WT_CONFIG/display-mode" ;;
                esac ;;
            f)
                if [ "$WT_LANGUAGE" = fr ]; then
                    choice="$(menu_select "Police" "Taille de police" "11" "11" "13" "13" "16" "16" "18" "18" "20" "20" "0" "Retour")" || continue
                else
                    choice="$(menu_select "Font" "Font size" "11" "11" "13" "13" "16" "16" "18" "18" "20" "20" "0" "Back")" || continue
                fi
                case "$choice" in 11|13|16|18|20)
                    mkdir -p "$WT_CONFIG"
                    printf '%s\n' "$choice" > "$WT_CONFIG/font-size" ;;
                esac ;;
            0|"") return ;;
        esac
    done
}

settings_menu() {
    while true; do
        local choice
        choice="$(menu_select "$(i18n settings_title)" "$(i18n settings_title)"             "u" "$(i18n update_check_action)"             "l" "$(i18n settings_language)"             "d" "Affichage / Display"             "0" "$(i18n back)")" || return

        case "$choice" in
            u) manual_update_check ;;
            l) language_menu ;;
            d) display_mode_menu ;;
            0|"") return ;;
        esac
    done
}
