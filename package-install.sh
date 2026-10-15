#!/bin/bash
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="/userdata/system/ultimate-wine-toolbox"
OLD_DEST="/userdata/system/thomsonito-wine-toolbox"

PORTS="/userdata/roms/ports"
PORT_NAME="Ultimate Wine Toolbox.sh"
PORT="$PORTS/$PORT_NAME"
KEYS="$PORTS/$PORT_NAME.keys"
OLD_PORT="$PORTS/Thomsonito Batocera Wine Toolbox.sh"

SCRIPTS="/userdata/system/scripts"
MANGOHUD_HOOK="$SCRIPTS/ultimate-wine-toolbox-mangohud.sh"
DXVK_HOOK="$SCRIPTS/ultimate-wine-toolbox-dxvk.sh"
RESHADE_HOOK="$SCRIPTS/ultimate-wine-toolbox-reshade.sh"
ANTIMICROX_HOOK="$SCRIPTS/ultimate-wine-toolbox-antimicrox.sh"
OLD_MANGOHUD_HOOK="$SCRIPTS/thomsonito-wine-toolbox-mangohud.sh"
OLD_DXVK_HOOK="$SCRIPTS/thomsonito-wine-toolbox-dxvk.sh"

LOG_DIR="/userdata/system/logs/ultimate-wine-toolbox"
OLD_LOG_DIR="/userdata/system/logs/thomsonito-wine-toolbox"
BACKUP_DIR="/userdata/system/backups/ultimate-wine-toolbox"
OLD_BACKUP_DIR="/userdata/system/backups/thomsonito-wine-toolbox"

DXVK_PATH="/userdata/system/wine/dxvk"
OLD_DXVK_BUNDLE=""

case "${LC_ALL:-${LANG:-}}" in fr*|fr_*) L=fr ;; *) L=en ;; esac

say() {
    if [ "$L" = "fr" ]; then printf '%s\n' "$1"; else printf '%s\n' "$2"; fi
}

[ "$(id -u)" -eq 0 ] || {
    say "ERREUR : lancez cet installateur en root." "ERROR: run this installer as root."
    exit 1
}

migration_fail() {
    say         "ERREUR : la migration de l'ancienne installation a échoué. L'ancienne installation a été conservée."         "ERROR: migration of the previous installation failed. The previous installation was preserved."
    exit 1
}

# Migration from the development name. User state is copied first and the old
# data is removed only after every copy has succeeded.
if [ -L "$DXVK_PATH" ]; then
    old_target="$(readlink -f "$DXVK_PATH" 2>/dev/null || true)"
    case "$old_target" in
        "$OLD_DEST"/dxvk/bundles/*) OLD_DXVK_BUNDLE="$(basename "$old_target")" ;;
    esac
fi

if [ -d "$OLD_DEST" ]; then
    mkdir -p "$DEST" || migration_fail
    for item in config dxvk exports; do
        if [ -d "$OLD_DEST/$item" ]; then
            mkdir -p "$DEST/$item" || migration_fail
            cp -a "$OLD_DEST/$item/." "$DEST/$item/" || migration_fail
        fi
    done
fi

if [ -d "$OLD_LOG_DIR" ]; then
    mkdir -p "$LOG_DIR" || migration_fail
    cp -a "$OLD_LOG_DIR/." "$LOG_DIR/" || migration_fail
fi

if [ -d "$OLD_BACKUP_DIR" ]; then
    mkdir -p "$BACKUP_DIR" || migration_fail
    cp -a "$OLD_BACKUP_DIR/." "$BACKUP_DIR/" || migration_fail
fi

# Remove legacy directories only after every migration copy above succeeded.
rm -rf -- "$OLD_DEST" "$OLD_LOG_DIR" "$OLD_BACKUP_DIR"

rm -f -- "$OLD_PORT" "$OLD_PORT.keys" "$OLD_MANGOHUD_HOOK" "$OLD_DXVK_HOOK"

mkdir -p "$DEST" "$DEST/templates" "$PORTS" "$SCRIPTS" "$LOG_DIR" "$BACKUP_DIR"
rm -rf "$DEST/toolbox"
cp -a "$SRC/toolbox" "$DEST/toolbox"
if [ -f "$DEST/v41-savedir/enabled" ]; then
    if ! python3 "$DEST/toolbox/helpers/v41_savedir_service.py" refresh; then
        say "Compatibilité SAVEDIR v41 non actualisée : consultez son menu dans la Toolbox." \
            "SAVEDIR v41 compatibility was not refreshed: check its Toolbox menu."
    fi
fi
cp -a "$SRC/VERSION" "$DEST/VERSION"
cp -a "$SRC/uninstall.sh" "$DEST/uninstall.sh"

chmod +x "$DEST/uninstall.sh"
chmod +x "$DEST/toolbox/ultimate-wine-toolbox.sh"
chmod +x "$DEST/toolbox/launch-in-terminal.sh"
chmod +x "$DEST/toolbox/modules/"*.sh "$DEST/toolbox/lib/"*.sh "$DEST/toolbox/hooks/"*.sh "$DEST/toolbox/helpers/"*.sh 2>/dev/null || true

# Refresh the AntiMicroX launcher without re-downloading its opt-in AppImage.
if [ -f "$DEST/tools/antimicrox/AntiMicroX.AppImage" ]; then
    cp -f "$DEST/toolbox/helpers/antimicrox-launch.sh" "$DEST/tools/antimicrox/antimicrox"
    chmod +x "$DEST/tools/antimicrox/antimicrox"
fi

# Install the official MangoHud runtime bundled by the Toolbox for both
# 32-bit and 64-bit Wine/Proton/UMU games. Failure is non-fatal so the
# Toolbox itself remains usable even if GitHub is temporarily unavailable.
if [ -x "$DEST/toolbox/helpers/install-mangohud-runtime.sh" ]; then
    if ! "$DEST/toolbox/helpers/install-mangohud-runtime.sh"; then
        say "AVERTISSEMENT : le runtime MangoHud n'a pas pu être installé. Les fonctions MangoHud de la Toolbox peuvent être indisponibles." \
            "WARNING: the MangoHud runtime could not be installed. Toolbox MangoHud features may be unavailable."
    fi
fi

if [ ! -s "$DEST/toolbox/ports/$PORT_NAME" ]; then
    say "ERREUR : lanceur Ports absent du package." "ERROR: Ports launcher missing from package."
    exit 1
fi
cp -f "$DEST/toolbox/ports/$PORT_NAME" "$PORT"
chmod +x "$PORT"

if [ ! -s "$DEST/toolbox/ports/$PORT_NAME.keys" ]; then
    say "ERREUR : mapping Pad2Key absent du package." "ERROR: Pad2Key mapping missing from package."
    exit 1
fi
cp -f "$DEST/toolbox/ports/$PORT_NAME.keys" "$KEYS"

if [ -s "$DEST/toolbox/hooks/mangohud-game-event.sh" ]; then
    cp -f "$DEST/toolbox/hooks/mangohud-game-event.sh" "$MANGOHUD_HOOK"
    chmod +x "$MANGOHUD_HOOK"
fi

if [ -s "$DEST/toolbox/hooks/dxvk-game-event.sh" ]; then
    cp -f "$DEST/toolbox/hooks/dxvk-game-event.sh" "$DXVK_HOOK"
    chmod +x "$DXVK_HOOK"
fi

if [ -s "$DEST/toolbox/hooks/reshade-game-event.sh" ]; then
    cp -f "$DEST/toolbox/hooks/reshade-game-event.sh" "$RESHADE_HOOK"
    chmod +x "$RESHADE_HOOK"
fi

if [ -s "$DEST/toolbox/hooks/antimicrox-game-event.sh" ]; then
    cp -f "$DEST/toolbox/hooks/antimicrox-game-event.sh" "$ANTIMICROX_HOOK"
    chmod +x "$ANTIMICROX_HOOK"
fi

if [ -n "$OLD_DXVK_BUNDLE" ] && [ -d "$DEST/dxvk/bundles/$OLD_DXVK_BUNDLE" ]; then
    rm -f -- "$DXVK_PATH"
    ln -s "$DEST/dxvk/bundles/$OLD_DXVK_BUNDLE" "$DXVK_PATH"
fi

if ! "$DEST/toolbox/helpers/install-scraper-assets.sh" "$DEST/toolbox/scraper-assets" \
    "ultimate-wine-toolbox" "Ultimate Wine Toolbox.sh" "Ultimate Wine Toolbox" \
    "Boîte à outils pour gérer Wine, Proton et UMU sous Batocera : runners, réglages graphiques, préfixes et archives WSquashFS." \
    "Manage Wine, Proton and UMU on Batocera with tools for runners, graphics settings, prefixes and WSquashFS archives." \
    "/userdata/system/ultimate-wine-toolbox/state" \
    "/userdata/system/backups/ultimate-wine-toolbox/scraper"; then
    say "AVERTISSEMENT : l’intégration du scrap Batocera n’a pas pu être terminée." \
        "WARNING: Batocera scraper integration could not be completed."
fi

command -v batocera-es-swissknife >/dev/null 2>&1 && batocera-es-swissknife --update-gamelists >/dev/null 2>&1 || true

echo
say "Ultimate Wine Toolbox installée." "Ultimate Wine Toolbox installed."
say "Pad2Key natif Batocera installé." "Native Batocera Pad2Key installed."
say "Lancement : Ports -> Ultimate Wine Toolbox" "Launch: Ports -> Ultimate Wine Toolbox"
