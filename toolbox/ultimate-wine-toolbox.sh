#!/bin/bash
set -u

WT_ROOT="$(cd "$(dirname "$0")" && pwd)"
export WT_ROOT

source "$WT_ROOT/lib/common.sh"
source "$WT_ROOT/lib/github.sh"
source "$WT_ROOT/lib/download.sh"
source "$WT_ROOT/lib/checksum.sh"
source "$WT_ROOT/lib/batocera.sh"
source "$WT_ROOT/modules/update.sh"

source "$WT_ROOT/modules/umu.sh"
source "$WT_ROOT/modules/starter-pack.sh"
source "$WT_ROOT/modules/runners.sh"
source "$WT_ROOT/modules/ge-proton-legacy.sh"
source "$WT_ROOT/modules/maintenance.sh"
source "$WT_ROOT/modules/wsquashfs.sh"
source "$WT_ROOT/modules/batocera-conf.sh"
source "$WT_ROOT/modules/batocera-conf-extra.sh"
source "$WT_ROOT/modules/batocera-conf-transfer.sh"
source "$WT_ROOT/modules/graphics.sh"
source "$WT_ROOT/modules/winetricks.sh"
source "$WT_ROOT/modules/community.sh"
source "$WT_ROOT/modules/antimicrox.sh"
source "$WT_ROOT/modules/reshade.sh"
source "$WT_ROOT/modules/dxvk-manager.sh"
source "$WT_ROOT/modules/settings.sh"
source "$WT_ROOT/modules/documentation.sh"

ensure_batocera_paths
runner_offer_normalization_at_startup
[ -f "$WT_HOME/state/antimicrox-live.json" ] || startup_update_check

main_menu() {
    while true; do
        local choice
        choice="$(menu_select "$WT_TITLE v$(wt_version)" \
            "$(i18n app_subtitle)

$(i18n menu_umu): $(umu_toolbox_status)" \
            "1" "$(i18n menu_umu)" \
            "2" "$(i18n menu_starter)" \
            "3" "$(i18n menu_runners)" \
            "4" "$(i18n menu_graphics)" \
            "5" "$(i18n menu_wsquashfs)" \
            "6" "$(i18n menu_maintenance)" \
            "7" "$(i18n menu_settings)" \
            "8" "$(i18n menu_documentation)" \
            "0" "$(i18n exit)")" || exit 0

        case "$choice" in
            1) umu_menu ;;
            2) starter_pack_menu ;;
            3) runner_manager_menu ;;
            4) graphics_menu ;;
            5) wsquashfs_menu ;;
            6) maintenance_menu ;;
            7) settings_menu ;;
            8) documentation_menu ;;
            0|"") clear; exit 0 ;;
        esac
    done
}

if [ "${WT_AUTO_RESUME_AMX:-0}" = "1" ] || [ -f "$WT_HOME/state/antimicrox-live.json" ]; then
    unset WT_AUTO_RESUME_AMX
    amx_live_resume && antimicrox_menu
fi

if [ "${WT_AUTO_RESUME_WSQ:-0}" = "1" ]; then
    unset WT_AUTO_RESUME_WSQ
    wsq_resume_build
    wsq_rc=$?
    [ "$wsq_rc" -eq 20 ] && exit 0
    [ "$wsq_rc" -ne 12 ] || wsquashfs_menu
fi

if [ "${WT_AUTO_RESUME_RESH:-0}" = "1" ] || [ -f "$WT_HOME/state/reshade-diagnostic.json" ]; then
    unset WT_AUTO_RESUME_RESH
    resh_resume_diagnostic
fi

main_menu
