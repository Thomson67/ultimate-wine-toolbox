#!/bin/bash

wsq_dotnet_command() {
    local action="$1"
    shift
    if [ "${WSQ_COMPONENT_MODE:-}" = standalone ]; then
        python3 "$WT_ROOT/helpers/winetricks_target.py" --home "$WT_HOME" \
            --runner "$runner" --settings-rom-name "${WSQ_COMPONENT_SETTINGS_ROM:-}" "$prefix" dotnet "$action" "$@"
    else
        python3 "$WT_ROOT/helpers/wsquashfs_dotnet.py" "$action" "$prefix" "$@"
    fi
}

wsq_dotnet_report() {
    local data runner_root
    runner_root="$(wsq_runner_root "$runner")" || return 1
    data="$(wsq_dotnet_command inspect \
        --runner-root "$runner_root")" || {
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
if data.get('mono_support_residue'):
    print('Ancienne entrée Mono Support conservée ; fichiers du CLR Microsoft vérifiés.' if fr else 'Old Mono Support entry retained; Microsoft CLR files verified.')
if data['dotnet48_marker']:
    print('Winetricks : dotnet48')
print('\n' + ('Mono partagé Batocera (disponible, pas forcément utilisé) :' if fr else 'Batocera shared Mono (available, not necessarily used):'))
print('\n'.join(data['shared']) or ('Non trouvé dans les emplacements standards' if fr else 'Not found in standard locations'))
PY
}

wsq_dotnet_run() {
    local title="$1" body="$2" log="$3" restore_fullscreen=0 rc
    shift 3
    # A fullscreen xterm can cover setup dialogs under XWayland. Only change
    # this terminal's actual window state, then restore it; keep user settings.
    if [[ "${WINDOWID:-}" =~ ^(0x[0-9a-fA-F]+|[0-9]+)$ ]] \
        && command -v xprop >/dev/null 2>&1 && command -v wmctrl >/dev/null 2>&1; then
        if xprop -id "$WINDOWID" _NET_WM_STATE 2>/dev/null | grep -q '_NET_WM_STATE_FULLSCREEN'; then
            wmctrl -i -r "$WINDOWID" -b remove,fullscreen >/dev/null 2>&1 && restore_fullscreen=1
        fi
    fi
    # Foreground execution preserves stdin for Winetricks confirmations, and
    # tee keeps both console output and the diagnostic log. No silent counter.
    wt_clear_tty
    printf '%s\n\n%b\n\n' "$title" "$body"
    "$@" 2>&1 | tee -a "$log"
    rc=${PIPESTATUS[0]}
    if [ "$restore_fullscreen" -eq 1 ]; then
        wmctrl -i -r "$WINDOWID" -b add,fullscreen >/dev/null 2>&1 || true
    fi
    return "$rc"
}

wsq_dotnet_apply() {
    local action="$1" log="$WSQ_STATE_DIR/wsquashfs-dotnet.log"
    yesno_default_no "$(i18n dotnet_title)" \
        "$(i18n dotnet_confirm "$(i18n "dotnet_$action")" "$runner" "$WT_HOME/backups/dotnet")" || return 1
    wsq_set_runner_config "${WSQ_COMPONENT_SETTINGS_ROM:-$(basename "$prefix")}" "$runner" || return 1
    mkdir -p "$WSQ_STATE_DIR"
    printf '\n===== .NET %s | %s | runner=%s | %s =====\n' \
        "$(date -Is)" "$action" "$runner" "$prefix" >> "$log"
    if ! wsq_dotnet_run "$(i18n dotnet_title)" "$(i18n dotnet_wait)" "$log" \
        wsq_dotnet_command "$action" \
        --backups "$WT_HOME/backups/dotnet" --cache "$WT_HOME/cache/wine-mono"; then
        msgbox "$(i18n dotnet_title)" "$(i18n dotnet_failed "$log" "$(wsq_update_log_detail "$log")")"
        return 1
    fi
    msgbox "$(i18n dotnet_title)" "$(i18n dotnet_done "$log")"
}

wsq_dotnet_restore_menu() {
    local choice name rows log="$WSQ_STATE_DIR/wsquashfs-dotnet.log"
    local -a items=()
    rows="$(wsq_dotnet_command backups \
        --backups "$WT_HOME/backups/dotnet")" || return 1
    while IFS= read -r name; do
        [ -n "$name" ] || continue
        items+=("$name" "$name ($(date -r "$WT_HOME/backups/dotnet/$name/backup.json" '+%d/%m %H:%M' 2>/dev/null))")
    done <<< "$rows"
    [ "${#items[@]}" -gt 0 ] || {
        msgbox "$(i18n dotnet_title)" "$(i18n dotnet_no_backup)"
        return 1
    }
    choice="$(menu_select "$(i18n dotnet_restore)" "$(i18n dotnet_restore_choose)" "${items[@]}" back "$(i18n back)")" || return 1
    case "$choice" in back|'') return 1 ;; esac
    yesno_default_no "$(i18n dotnet_restore)" "$(i18n dotnet_restore_confirm "$choice")" || return 1
    mkdir -p "$WSQ_STATE_DIR"
    if ! wsq_update_run "$(i18n dotnet_restore)" "$(i18n dotnet_wait)" "$log" \
        wsq_dotnet_command restore \
        --backups "$WT_HOME/backups/dotnet" --snapshot "$WT_HOME/backups/dotnet/$choice"; then
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
            restore "$(i18n dotnet_restore)" \
            doc "$(i18n doc_dotnet)" back "$(i18n back)")" || return 1
        case "$choice" in
            mono|microsoft) wsq_dotnet_apply "$choice" ;;
            restore) wsq_dotnet_restore_menu ;;
            doc) documentation_show dotnet ;;
            back|'') return 0 ;;
        esac
    done
}
