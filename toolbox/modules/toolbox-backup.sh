#!/bin/bash

maintenance_backup_label() {
    if [ "$WT_LANGUAGE" = fr ]; then
        printf 'Sauvegarder ou restaurer la Toolbox'
    else
        printf 'Back up or restore the Toolbox'
    fi
}

maintenance_backup_error() {
    local title="$1" message="$2" details="$3" report
    report="$(mktemp /tmp/wt-backup-error.XXXXXX)" || {
        msgbox "$title" "$message\n\n$details"
        return
    }
    printf '%s\n\n%s\n' "$message" "$details" | fold -s -w 90 > "$report"
    maintenance_show_report "$title" "$report"
    rm -f -- "$report"
}

maintenance_backup_menu() {
    local title export_label restore_label runner_prompt restore_runners replace_prompt confirm_export
    local confirm_restore source_prompt output_prompt done_export done_restore failed estimate
    local path default_dir choice output size free summary
    local -a options=()
    title="$(maintenance_backup_label)"
    if [ "$WT_LANGUAGE" = fr ]; then
        export_label="Créer une sauvegarde"
        restore_label="Restaurer une sauvegarde"
        runner_prompt="Inclure les runners Wine et UMU ? Ils peuvent prendre plusieurs Gio et rallonger l’opération."
        restore_runners="Restaurer aussi les runners présents dans l’archive ?"
        replace_prompt="Remplacer les réglages et fichiers en conflit par ceux de la sauvegarde ? Non conserve ceux de cette machine."
        confirm_export="Créer cette archive ? Volume avant compression / espace libre"
        confirm_restore="Restaurer cette archive ? Fermez les jeux et les menus de réglages d’EmulationStation avant de continuer."
        source_prompt="Chemin complet de l’archive .tar.gz à restaurer"
        output_prompt="Chemin complet de la nouvelle archive .tar.gz (le dossier doit exister)"
        done_export="Sauvegarde créée"
        done_restore="Restauration terminée. Redémarrez la Toolbox et EmulationStation. Vérifiez les associations des jeux renommés ou déplacés."
        failed="Opération interrompue"
    else
        export_label="Create a backup"
        restore_label="Restore a backup"
        runner_prompt="Include Wine and UMU runners? They can use several GiB and add time to the operation."
        restore_runners="Also restore any runners included in the archive?"
        replace_prompt="Replace conflicting settings and files with the backup versions? No keeps this machine’s copies."
        confirm_export="Create this archive? Uncompressed size / free space"
        confirm_restore="Restore this archive? Close games and EmulationStation settings menus before proceeding."
        source_prompt="Full path of the .tar.gz archive to restore"
        output_prompt="Full path for the new .tar.gz archive (the directory must exist)"
        done_export="Backup created"
        done_restore="Restore complete. Restart the Toolbox and EmulationStation. Check associations for renamed or moved games."
        failed="Operation failed"
    fi
    local -a helper=(python3 "$WT_ROOT/helpers/toolbox_backup.py")
    default_dir="/userdata/system/backups/ultimate-wine-toolbox"
    choice="$(menu_select "$title" "$title" "1" "$export_label" "2" "$restore_label" "0" "$(i18n back)")" || return
    case "$choice" in
        1)
            mkdir -p -- "$default_dir" || { msgbox "$title" "$failed"; return; }
            path="$(input_text "$title" "$output_prompt" "$default_dir/UWT-$(date +%Y%m%d-%H%M%S).tar.gz")" || return
            [ -n "$path" ] || return
            if yesno_default_no "$title" "$runner_prompt"; then options+=(--runners); fi
            if ! estimate="$("${helper[@]}" estimate "$path" "${options[@]}" 2>&1)"; then
                maintenance_backup_error "$title" "$failed" "$estimate"
                return
            fi
            IFS=$'\t' read -r size free <<< "$estimate"
            summary="$(awk -v size="$size" -v free="$free" 'BEGIN {printf "%.2f / %.2f GiB", size/1073741824, free/1073741824}')"
            yesno_default_no "$title" "$confirm_export\n\n$summary\n\n$path" || return
            if output="$("${helper[@]}" export "$path" "${options[@]}" 2>&1)"; then
                msgbox "$title" "$done_export\n\n$path"
            else
                maintenance_backup_error "$title" "$failed" "$output"
            fi
            ;;
        2)
            path="$(input_text "$title" "$source_prompt" "$default_dir/")" || return
            [ -f "$path" ] || { msgbox "$title" "$failed\n\n$path"; return; }
            if ! summary="$("${helper[@]}" inspect "$path" 2>&1)"; then
                maintenance_backup_error "$title" "$failed" "$summary"
                return
            fi
            yesno_default_no "$title" "$confirm_restore\n\n$summary" || return
            if yesno_default_no "$title" "$restore_runners"; then options+=(--runners); fi
            if yesno_default_no "$title" "$replace_prompt"; then options+=(--replace); fi
            if output="$("${helper[@]}" restore "$path" "${options[@]}" 2>&1)"; then
                python3 "$WT_ROOT/helpers/es_options.py" refresh >> "${WT_SESSION_LOG:-/dev/null}" 2>&1 || true
                printf '%s\n' "$output" >> "${WT_SESSION_LOG:-/dev/null}"
                msgbox "$title" "$done_restore"
            else
                maintenance_backup_error "$title" "$failed" "$output"
            fi
            ;;
    esac
}
