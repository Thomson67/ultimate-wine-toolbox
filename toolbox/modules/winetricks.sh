#!/bin/bash

winetricks_game_menu() {
    local prefix runner choice selected idx path
    local WSQ_COMPONENT_MODE=standalone
    local -a games=() items=() picker_flags=()
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
        while true; do
            choice="$(menu_select "$(i18n winetricks_tools_title)" \
                "$(i18n winetricks_tools_selected "$prefix" "$runner")" \
                components "$(i18n wsq_winetricks_title)" dotnet "$(i18n dotnet_title)" \
                runner "$(i18n wsq_runner_title)" back "$(i18n back)")" || break
            case "$choice" in
                components)
                    if wsq_install_extra_winetricks standalone; then
                        msgbox "$(i18n winetricks_tools_title)" "$(i18n winetricks_tools_done)"
                    fi ;;
                dotnet) wsq_dotnet_menu ;;
                runner) selected="$(wsq_select_runner)" && runner="$selected" ;;
                back|'') break ;;
            esac
        done
    done
}
