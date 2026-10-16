#!/bin/bash
# The official 3.6.1 AppImage bundles Qt6/xcb, not a Wayland Qt plugin.
set -euo pipefail
ROOT="${WT_HOME:-/userdata/system/ultimate-wine-toolbox}"
DIR="$ROOT/tools/antimicrox"
APP="$DIR/squashfs-root/AppRun"
if [ ! -x "$APP" ] && [ -x "$DIR/AntiMicroX.AppImage" ]; then
  # Migrate an AppImage downloaded by the first experimental installer.
  (
    exec 8>"$DIR/install.lock"
    flock -x 8
    [ ! -x "$APP" ] || exit 0
    tmp="$(mktemp -d "$DIR/.extract.XXXXXX")"
    trap 'rm -rf -- "$tmp"' EXIT
    (cd "$tmp"; "$DIR/AntiMicroX.AppImage" --appimage-extract >/dev/null)
    [ -x "$tmp/squashfs-root/AppRun" ] || exit 1
    # Discard only an incomplete extraction after a failed earlier attempt.
    rm -rf -- "$DIR/squashfs-root"
    mv -- "$tmp/squashfs-root" "$DIR/squashfs-root"
  )
fi
[ -x "$APP" ] || { echo 'AntiMicroX runtime missing. Reinstall AntiMicroX from its menu.' >&2; exit 1; }
# Batocera's Qt/plugin/loader overrides belong to its own applications.
unset QT_PLUGIN_PATH QT_QPA_PLATFORM_PLUGIN_PATH QT_QPA_PLATFORMTHEME QT_STYLE_OVERRIDE
unset LD_LIBRARY_PATH LD_PRELOAD
export QT_QPA_PLATFORM=xcb
export QT_PLUGIN_PATH="$DIR/squashfs-root/usr/plugins"
export QT_QPA_PLATFORM_PLUGIN_PATH="$QT_PLUGIN_PATH/platforms"
export DISPLAY="${DISPLAY:-:0}"
export SDL_VIDEODRIVER=x11
# Upstream 3.6.1 never registers QXmlStreamReader*, so queued profile loads
# silently time out. Register that one type before main(), using bundled Qt6.
if [ -f "$DIR/squashfs-root/usr/lib/libQt6Core.so.6" ]; then
  compat="$DIR/register-xml-reader.so"
  python3 "$ROOT/toolbox/helpers/antimicrox_compat.py" "$compat"
  echo 'Qt6 XML profile reader compatibility enabled' >&2
  # Resolve AppRun's symlink before exec: its RUNPATH is relative to usr/bin.
  exec env LD_PRELOAD="$compat" "$(readlink -f -- "$APP")" "$@"
fi
exec "$APP" "$@"
