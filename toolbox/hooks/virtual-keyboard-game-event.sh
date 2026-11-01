#!/bin/bash
# Optional Windows-only watcher. No synchronous GUI or inherited hook pipes.
set -u
ROOT="${WT_HOME:-/userdata/system/ultimate-wine-toolbox}"
[ "${2:-}" = windows ] || exit 0
case "${1:-}" in gameStart|gameStop) ;; *) exit 0 ;; esac
rom="${5:-}"
[ -n "$rom" ] || exit 0
helper="$ROOT/toolbox/helpers/virtual_keyboard.py"
[ -f "$helper" ] || exit 0
log="/userdata/system/logs/ultimate-wine-toolbox/virtual-keyboard.log"
mkdir -p "$(dirname "$log")"
case "$1" in gameStart) action=start ;; gameStop) action=stop ;; esac
# start closes all nonstandard FDs and detaches its owner before returning.
python3 "$helper" --home "$ROOT" "$action" --rom "$rom" >> "$log" 2>&1 || true
exit 0
