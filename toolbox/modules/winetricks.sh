#!/bin/bash

winetricks_game_menu() {
    local prefix runner choice selected idx path archive_mode original_archive archive_log
    local WSQ_COMPONENT_MODE=standalone
    local WSQ_COMPONENT_SETTINGS_ROM=''
    local -a games=() items=() picker_flags=() archive_options=()
    while true; do
        games=(); items=(); idx=1
        while IFS= read -r path; do
            [ -n "$path" ] || continue
            games+=("$path")
            items+=("$idx" "$(basename "$path")")
            idx=$((idx+1))
        done < <(python3 "$WT_ROOT/helpers/winetricks_games.py" list "$WSQ_WINDOWS_DIR")
        choice="$(menu_select "$(i18n winetricks_tools_title)" "$(i18n winetricks_tools_intro)" \
            "${items[@]}" browse "$(i18n wsq_update_source_browse)" \
            archive "$(i18n winetricks_tools_archive)" back "$(i18n back)")" || return 0
        case "$choice" in
            back|'') return 0 ;;
            browse|archive)
                if command -v yad >/dev/null 2>&1; then
                    picker_flags=()
                    [ "$choice" = archive ] || picker_flags=(--directory)
                    selected="$(DISPLAY="${DISPLAY:-:0}" LANGUAGE="$WT_LANGUAGE" yad --file "${picker_flags[@]}" \
                        --filename="$WSQ_WINDOWS_DIR/" --title="$(i18n winetricks_tools_title)" \
                        --width=1000 --height=700)" || continue
                else
                    selected="$(input_text "$(i18n winetricks_tools_title)" \
                        "$(i18n winetricks_tools_prefix)" "$WSQ_WINDOWS_DIR/")" || continue
                fi
                prefix="${selected%/}" ;;
            *[!0-9]*) continue ;;
            *)
                [ "$choice" -ge 1 ] && [ "$choice" -lt "$idx" ] || continue
                prefix="${games[$((choice-1))]}" ;;
        esac
        if ! python3 "$WT_ROOT/helpers/winetricks_games.py" validate "$prefix"; then
            msgbox "$(i18n winetricks_tools_title)" "$(i18n winetricks_tools_invalid)"
            continue
        fi
        runner="$(python3 "$WT_ROOT/helpers/winetricks_games.py" runner "$prefix" --conf "$WSQ_CONF")" || continue
        archive_mode=0
        WSQ_COMPONENT_SETTINGS_ROM=''
        archive_options=()
        if [[ "${prefix,,}" = *.wsquashfs ]]; then
            choice="$(menu_select "$(i18n winetricks_tools_title)" "$(i18n winetricks_archive_mode_prompt)" \
                bottle "$(i18n winetricks_archive_bottle)" archive "$(i18n winetricks_archive_embed)" \
                back "$(i18n back)")" || continue
            case "$choice" in
                bottle) ;;
                archive)
                    original_archive="$prefix"
                    mkdir -p "$WT_LOG_DIR" || return 1
                    archive_log="$(mktemp "$WT_LOG_DIR/components-archive-XXXXXX.log")" || return 1
                    if ! wsq_update_run "$(i18n winetricks_tools_title)" "$(i18n winetricks_archive_extract)" "$archive_log" \
                        python3 "$WT_ROOT/helpers/winetricks_archive.py" --home "$WT_HOME" prepare "$original_archive"; then
                        msgbox "$(i18n winetricks_tools_title)" "$(i18n winetricks_archive_failed "$archive_log")"
                        continue
                    fi
                    prefix="$(python3 "$WT_ROOT/helpers/winetricks_archive.py" --home "$WT_HOME" path "$original_archive")" || continue
                    WSQ_COMPONENT_SETTINGS_ROM="$(basename "$original_archive")"
                    archive_mode=1
                    archive_options=(rebuild "$(i18n winetricks_archive_finish)") ;;
                *) continue ;;
            esac
        fi
        while true; do
            choice="$(menu_select "$(i18n winetricks_tools_title)" \
                "$(i18n winetricks_tools_selected "$prefix" "$runner")" \
                components "$(i18n wsq_winetricks_title)" dotnet "$(i18n dotnet_title)" \
                "${archive_options[@]}" \
                runner "$(i18n wsq_runner_title)" back "$(i18n back)")" || break
            case "$choice" in
                components)
                    if wsq_install_extra_winetricks standalone; then
                        if [ "$archive_mode" = 1 ]; then
                            msgbox "$(i18n winetricks_tools_title)" "$(i18n winetricks_archive_installed)"
                        else
                            msgbox "$(i18n winetricks_tools_title)" "$(i18n winetricks_tools_done)"
                        fi
                    fi ;;
                dotnet) wsq_dotnet_menu ;;
                runner) selected="$(wsq_select_runner)" && runner="$selected" ;;
                rebuild)
                    yesno_default_no "$(i18n winetricks_tools_title)" \
                        "$(i18n winetricks_archive_confirm "$original_archive")" || continue
                    if wsq_update_run "$(i18n winetricks_tools_title)" "$(i18n winetricks_archive_building)" "$archive_log" \
                        python3 "$WT_ROOT/helpers/winetricks_archive.py" --home "$WT_HOME" --log "$archive_log" build "$original_archive"; then
                        msgbox "$(i18n winetricks_tools_title)" "$(i18n winetricks_archive_done)"
                        break
                    fi
                    msgbox "$(i18n winetricks_tools_title)" "$(i18n winetricks_archive_failed "$archive_log")" ;;
                back|'')
                    if [ "$archive_mode" = 1 ]; then
                        msgbox "$(i18n winetricks_tools_title)" "$(i18n winetricks_archive_pending "$prefix")"
                    fi
                    break ;;
            esac
        done
    done
}
