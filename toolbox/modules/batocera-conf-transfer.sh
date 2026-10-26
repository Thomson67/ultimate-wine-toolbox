#!/bin/bash

BATOCERA_WINDOWS_EXPORT_DIR="$WT_HOME/exports/windows-config"
BATOCERA_WINDOWS_TRANSFER_HELPER="$WT_ROOT/helpers/batocera_conf_transfer.py"

batocera_conf_export_windows() {
    local stamp output result rc global_count game_count game_lines

    [ -r "$BATOCERA_CONF" ] || {
        msgbox "$(i18n batocera_conf_title)" "$(i18n batocera_conf_unreadable "$BATOCERA_CONF")"
        return
    }

    mkdir -p "$BATOCERA_WINDOWS_EXPORT_DIR" || {
        msgbox "$(i18n batocera_conf_export_title)" "$(i18n batocera_conf_export_dir_failed "$BATOCERA_WINDOWS_EXPORT_DIR")"
        return
    }

    stamp="$(date '+%Y%m%d-%H%M%S')"
    output="$BATOCERA_WINDOWS_EXPORT_DIR/windows-config-$stamp.conf"

    result="$(python3 "$BATOCERA_WINDOWS_TRANSFER_HELPER" export \
        --conf "$BATOCERA_CONF" \
        --output "$output" \
        --batocera "$(batocera_version)")"
    rc=$?

    if [ "$rc" -ne 0 ] || [ ! -s "$output" ]; then
        rm -f -- "$output"
        msgbox "$(i18n batocera_conf_export_title)" "$(i18n batocera_conf_export_failed)"
        return
    fi

    IFS="$(printf '\t')" read -r global_count game_count game_lines <<< "$result"
    msgbox "$(i18n batocera_conf_export_title)" \
        "$(i18n batocera_conf_export_done "$global_count" "$game_count" "$game_lines" "$output")"
}

batocera_conf_import_windows_file() {
    local source="$1" backup result rc
    local global_count game_count game_lines add_count skip_count

    [ -f "$source" ] || {
        msgbox "$(i18n batocera_conf_import_title)" "$(i18n batocera_conf_import_invalid)"
        return
    }

    [ -r "$BATOCERA_CONF" ] || {
        msgbox "$(i18n batocera_conf_title)" "$(i18n batocera_conf_unreadable "$BATOCERA_CONF")"
        return
    }

    result="$(python3 "$BATOCERA_WINDOWS_TRANSFER_HELPER" preview-import \
        --conf "$BATOCERA_CONF" \
        --source "$source")"
    rc=$?

    case "$rc" in
        0) ;;
        10)
            msgbox "$(i18n batocera_conf_import_title)" "$(i18n batocera_conf_import_bad_format)"
            return
            ;;
        11|12)
            msgbox "$(i18n batocera_conf_import_title)" "$(i18n batocera_conf_import_unsafe)"
            return
            ;;
        *)
            msgbox "$(i18n batocera_conf_import_title)" "$(i18n batocera_conf_import_invalid)"
            return
            ;;
    esac

    IFS="$(printf '\t')" read -r global_count game_count game_lines add_count skip_count <<< "$result"

    yesno_default_no "$(i18n batocera_conf_import_title)" \
        "$(i18n batocera_conf_import_confirm "$(basename "$source")" "$global_count" "$game_count" "$game_lines" "$add_count" "$skip_count")" || return

    backup="$(batocera_conf_backup)" || {
        msgbox "$(i18n batocera_conf_import_title)" "$(i18n batocera_conf_backup_failed)"
        return
    }

    result="$(python3 "$BATOCERA_WINDOWS_TRANSFER_HELPER" merge-import \
        --conf "$BATOCERA_CONF" \
        --source "$source")"
    rc=$?

    if [ "$rc" -eq 0 ]; then
        IFS="$(printf '\t')" read -r add_count skip_count <<< "$result"
        msgbox "$(i18n batocera_conf_import_title)" \
            "$(i18n batocera_conf_import_done "$add_count" "$skip_count" "$backup")"
    else
        msgbox "$(i18n batocera_conf_import_title)" \
            "$(i18n batocera_conf_import_failed "$backup")"
    fi
}

batocera_conf_import_windows() {
    local -a items=()
    local rows="" path idx=1 count=0 choice selected mode manual

    mkdir -p "$BATOCERA_WINDOWS_EXPORT_DIR" || {
        msgbox "$(i18n batocera_conf_import_title)" "$(i18n batocera_conf_export_dir_failed "$BATOCERA_WINDOWS_EXPORT_DIR")"
        return
    }

    mode="$(menu_select "$(i18n batocera_conf_import_title)" \
        "$(i18n batocera_conf_import_source_prompt "$BATOCERA_WINDOWS_EXPORT_DIR")" \
        "1" "$(i18n batocera_conf_import_from_folder)" \
        "2" "$(i18n batocera_conf_import_manual)" \
        "0" "$(i18n back)")" || return

    case "$mode" in
        1)
            while IFS= read -r path; do
                [ -f "$path" ] || continue
                items+=("$idx" "$(basename "$path")")
                rows+="$path"$'\n'
                idx=$((idx+1))
                count=$((count+1))
            done < <(find "$BATOCERA_WINDOWS_EXPORT_DIR" -mindepth 1 -maxdepth 1 \
                -type f -name 'windows-config-*.conf' -print 2>/dev/null | sort -r)

            [ "$count" -gt 0 ] || {
                msgbox "$(i18n batocera_conf_import_title)" \
                    "$(i18n batocera_conf_import_none "$BATOCERA_WINDOWS_EXPORT_DIR")"
                return
            }

            choice="$(WT_MENU_LIST=1 menu_select "$(i18n batocera_conf_import_title)" \
                "$(i18n batocera_conf_import_choose "$count")" \
                "${items[@]}")" || return
            [ -n "$choice" ] || return
            selected="$(sed -n "${choice}p" <<< "$rows")"
            ;;
        2)
            manual="$(input_text "$(i18n batocera_conf_import_title)" \
                "$(i18n batocera_conf_import_manual_prompt)" \
                "$BATOCERA_WINDOWS_EXPORT_DIR/")" || return
            selected="$manual"
            ;;
        *)
            return
            ;;
    esac

    batocera_conf_import_windows_file "$selected"
}

batocera_conf_menu() {
    while true; do
        local choice
        choice="$(menu_select "$(i18n batocera_conf_title)" "$(i18n batocera_conf_intro)" \
            "1" "$(i18n batocera_conf_analyze)" \
            "2" "$(i18n batocera_conf_clean)" \
            "3" "$(i18n batocera_conf_clean_all)" \
            "4" "$(i18n batocera_conf_organize)" \
            "5" "$(i18n batocera_conf_export_title)" \
            "6" "$(i18n batocera_conf_import_title)" \
            "7" "$(i18n batocera_conf_restore)" \
            "0" "$(i18n back)")" || return

        case "$choice" in
            1) batocera_conf_analyze ;;
            2) batocera_conf_clean_orphans ;;
            3) batocera_conf_clean_all_orphans ;;
            4) batocera_conf_organize ;;
            5) batocera_conf_export_windows ;;
            6) batocera_conf_import_windows ;;
            7) batocera_conf_restore ;;
            0|"") return ;;
        esac
    done
}
