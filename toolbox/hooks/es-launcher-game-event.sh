#!/bin/bash
[ "${2:-}" = windows ] && [ -n "${5:-}" ] || exit 0
case "${1:-}" in gameStart|gameStop) ;; *) exit 0 ;; esac
ROOT=/userdata/system/ultimate-wine-toolbox
[ -s /userdata/system/configs/emulationstation/es_features_ultimate_wine_toolbox.cfg ] ||
    [ -d "$ROOT/state/es-launcher" ] || exit 0
mkdir -p /userdata/system/logs/ultimate-wine-toolbox
python3 "$ROOT/toolbox/helpers/es_launcher.py" "$1" "$ROOT" "$5" \
    >> /userdata/system/logs/ultimate-wine-toolbox/es-launcher.log 2>&1 || true
