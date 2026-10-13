#!/bin/bash

wsq_dotnet_report() {
    local data
    data="$(python3 "$WT_ROOT/helpers/wsquashfs_dotnet.py" inspect "$prefix" \
        --runner-root "${BATOCERA_CUSTOM_WINE:-/userdata/system/wine/custom}/$runner")" || {
        msgbox "$(i18n dotnet_title)" "$data"
        return 1
    }
    python3 - "$data" "${WT_LANGUAGE:-fr}" <<'PY'
import json, sys
data = json.loads(sys.argv[1])
fr = sys.argv[2] == 'fr'
states = {
    'mono': ('Wine Mono détecté', 'Wine Mono detected'),
    'microsoft': ('.NET Framework Microsoft détecté', 'Microsoft .NET Framework detected'),
    'mixed': ('État mixte : vérifier avant modification', 'Mixed state: inspect before changing'),
    'uncertain': ('Traces .NET non identifiées : vérifier avant modification', 'Unidentified .NET traces: inspect before changing'),
    'absent': ('Aucun composant .NET identifié dans le préfixe', 'No .NET component identified inside the prefix'),
}
print(states[data['status']][0 if fr else 1])
for entry in data['mono'] + data['microsoft']:
    print(entry['DisplayName'] + ' ' + entry.get('DisplayVersion', ''))
if data['dotnet48_marker']:
    print('Winetricks : dotnet48')
print('\n' + ('Mono partagé Batocera (disponible, pas forcément utilisé) :' if fr else 'Batocera shared Mono (available, not necessarily used):'))
print('\n'.join(data['shared']) or ('Non trouvé dans les emplacements standards' if fr else 'Not found in standard locations'))
PY
}

wsq_dotnet_apply() {
    local action="$1" log="$WSQ_STATE_DIR/wsquashfs-dotnet.log"
    yesno_default_no "$(i18n dotnet_title)" \
        "$(i18n dotnet_confirm "$(i18n "dotnet_$action")" "$runner" "$WT_HOME/backups/dotnet")" || return 1
    wsq_set_runner_config "$(basename "$prefix")" "$runner" || return 1
    mkdir -p "$WSQ_STATE_DIR"
    if ! wsq_update_run "$(i18n dotnet_title)" "$(i18n dotnet_wait)" "$log" \
        python3 "$WT_ROOT/helpers/wsquashfs_dotnet.py" "$action" "$prefix" \
        --backups "$WT_HOME/backups/dotnet" --cache "$WT_HOME/cache/wine-mono"; then
        msgbox "$(i18n dotnet_title)" "$(i18n dotnet_failed "$log" "$(wsq_update_log_detail "$log")")"
        return 1
    fi
    msgbox "$(i18n dotnet_title)" "$(i18n dotnet_done "$log")"
}

wsq_dotnet_menu() {
    local choice report
    while true; do
        report="$(wsq_dotnet_report)" || return 1
        choice="$(menu_select "$(i18n dotnet_title)" "$report\n\n$(i18n dotnet_intro)" \
            mono "$(i18n dotnet_mono)" microsoft "$(i18n dotnet_microsoft)" \
            doc "$(i18n doc_dotnet)" back "$(i18n back)")" || return 1
        case "$choice" in
            mono|microsoft) wsq_dotnet_apply "$choice" ;;
            doc) documentation_show dotnet ;;
            back|'') return 0 ;;
        esac
    done
}
