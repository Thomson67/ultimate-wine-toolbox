#!/bin/bash
set -euo pipefail

DEST="/userdata/system/ultimate-wine-toolbox"
PORT="/userdata/roms/ports/Ultimate Wine Toolbox.sh"
KEYS="$PORT.keys"
MANGOHUD_HOOK="/userdata/system/scripts/ultimate-wine-toolbox-mangohud.sh"
DXVK_HOOK="/userdata/system/scripts/ultimate-wine-toolbox-dxvk.sh"
RESHADE_HOOK="/userdata/system/scripts/ultimate-wine-toolbox-reshade.sh"
DXVK_PATH="/userdata/system/wine/dxvk"
DXVK_BUNDLES="$DEST/dxvk/bundles"
MANGOHUD_LEGACY_LAYER="/usr/share/vulkan/implicit_layer.d/MangoHud.ultimate-wine-toolbox.json"
MANGOHUD_X86_LAYER="/usr/share/vulkan/implicit_layer.d/MangoHud.ultimate-wine-toolbox.x86.json"

# Legacy development-name artifacts are removed as well.
OLD_DEST="/userdata/system/thomsonito-wine-toolbox"
OLD_PORT="/userdata/roms/ports/Thomsonito Batocera Wine Toolbox.sh"
OLD_MANGOHUD_HOOK="/userdata/system/scripts/thomsonito-wine-toolbox-mangohud.sh"
OLD_DXVK_HOOK="/userdata/system/scripts/thomsonito-wine-toolbox-dxvk.sh"

case "${LC_ALL:-${LANG:-}}" in fr*|fr_*) L=fr ;; *) L=en ;; esac
say() {
    if [ "$L" = "fr" ]; then printf '%s\n' "$1"; else printf '%s\n' "$2"; fi
}

[ "$(id -u)" -eq 0 ] || {
    say "ERREUR : lancez ce désinstalleur en root." "ERROR: run this uninstaller as root."
    exit 1
}

if [ -f "$DEST/v41-savedir/state.json" ] || [ -f "$DEST/v41-savedir/enabled" ] || \
   [ -f /userdata/system/services/uwt_v41_savedir ]; then
    python3 "$DEST/toolbox/helpers/v41_savedir_service.py" disable || {
        say "ERREUR : restauration du lanceur v41 refusée. Toolbox et sauvegarde du script conservées." \
            "ERROR: v41 launcher restoration refused. Toolbox and script backup preserved."
        exit 1
    }
fi

if [ -L "$DXVK_PATH" ]; then
    target="$(readlink -f "$DXVK_PATH" 2>/dev/null || true)"
    case "$target" in
        "$DXVK_BUNDLES"/*|"$OLD_DEST"/dxvk/bundles/*) rm -f "$DXVK_PATH" ;;
    esac
fi

if [ -d "$DEST/reshade" ]; then
    python3 "$DEST/toolbox/helpers/reshade_manager.py" --home "$DEST" disable-all || {
        say "ERREUR : restauration ReShade incomplète. Installation et sauvegardes conservées." \
            "ERROR: incomplete ReShade restoration. Installation and backups preserved."
        exit 1
    }
fi

rm -rf "$DEST" "$OLD_DEST"
rm -f "$PORT" "$KEYS" "$MANGOHUD_HOOK" "$DXVK_HOOK" "$RESHADE_HOOK"
rm -f "$MANGOHUD_LEGACY_LAYER" "$MANGOHUD_X86_LAYER"
rm -f "$OLD_PORT" "$OLD_PORT.keys" "$OLD_MANGOHUD_HOOK" "$OLD_DXVK_HOOK"

say "Ultimate Wine Toolbox supprimée. Les runners Wine/UMU installés ont été conservés." \
    "Ultimate Wine Toolbox removed. Installed Wine/UMU runners were left untouched."
