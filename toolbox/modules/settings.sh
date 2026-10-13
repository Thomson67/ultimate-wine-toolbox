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
    local choice current label
    while true; do
        current="$(cat "$WT_CONFIG/display-mode" 2>/dev/null || true)"
        case "$current" in handheld) ;; *) current=normal ;; esac
        if [ "$WT_LANGUAGE" = fr ]; then
            label="Profil actuel : $current. Redémarrer la Toolbox après modification."
            choice="$(menu_select "Affichage" "$label" "normal" "Normal (police 11)" "handheld" "Console portable (police 16)" "fullscreen" "Plein écran (police 11)" "0" "Retour")" || return
        else
            label="Current profile: $current. Restart the Toolbox after changing it."
            choice="$(menu_select "Display" "$label" "normal" "Normal (font 11)" "handheld" "Handheld (font 16)" "fullscreen" "Fullscreen (font 11)" "0" "Back")" || return
        fi
        case "$choice" in
            normal|handheld|fullscreen)
                mkdir -p "$WT_CONFIG"
                printf '%s\n' "$choice" > "$WT_CONFIG/display-mode"
                if [ "$WT_LANGUAGE" = fr ]; then
                    msgbox "Affichage" "Profil enregistré. Quittez puis relancez la Toolbox depuis Ports pour appliquer la nouvelle taille."
                else
                    msgbox "Display" "Profile saved. Exit and relaunch the Toolbox from Ports to apply the new size."
                fi
                return ;;
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
