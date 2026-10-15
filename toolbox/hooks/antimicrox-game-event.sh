#!/bin/bash
# AntiMicroX lifecycle: one managed mapping at a time, never kill unrelated instances.
set -u
ROOT=/userdata/system/ultimate-wine-toolbox
CFG="$ROOT/config/antimicrox-games.tsv"
STATE="$ROOT/state/antimicrox"
LOG=/userdata/system/logs/ultimate-wine-toolbox/antimicrox.log
[ "${2:-}" = windows ] || exit 0
case "${1:-}" in gameStart|gameStop) ;; *) exit 0 ;; esac
rom="${5:-}"
[ -n "$rom" ] || exit 0
mkdir -p "$STATE" "$(dirname "$LOG")"
log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*" >> "$LOG"; }
exec 9>"$STATE/lock"
flock -x 9 || exit 0
# A single running profile prevents conflicting mappings and joystick drift.
session="$STATE/session"
proc_start() { [ -r "/proc/$1/stat" ] && awk '{print $22}' "/proc/$1/stat" || true; }
stop_owned() {
  [ -f "$session" ] || return 0
  local oldrom pid stamp actual cmd
  IFS=$'\t' read -r oldrom pid stamp < "$session" || true
  rm -f -- "$session"
  case "$pid" in ''|*[!0-9]*) return 0 ;; esac
  actual="$(proc_start "$pid")"
  if [ -n "$actual" ] && [ "$actual" = "$stamp" ]; then
    cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
    case "${cmd,,}" in *antimicrox*) kill "$pid" 2>/dev/null || true; log "stopped $oldrom pid=$pid" ;; esac
  fi
}
if [ "$1" = gameStop ]; then
  [ -f "$session" ] || exit 0
  IFS=$'\t' read -r oldrom _ < "$session" || true
  [ "$oldrom" = "$rom" ] && stop_owned
  exit 0
fi
[ -f "$CFG" ] || exit 0
profile="$(awk -F '\t' -v p="$rom" '$1==p {v=$2} END {print v}' "$CFG")"
[ -n "$profile" ] || exit 0
[ -f "$profile" ] || { log "profile missing $rom"; exit 0; }
real="$(readlink -f -- "$profile" 2>/dev/null || true)"
case "$real" in /userdata/*) ;; *) log "profile refused (outside /userdata)"; exit 0 ;; esac
binary="$ROOT/tools/antimicrox/antimicrox"
[ -x "$binary" ] || { log "AntiMicroX not installed"; exit 0; }
[ -w /dev/uinput ] || { log "uinput unavailable or not writable"; exit 0; }
stop_owned
"$binary" --hidden --no-tray --eventgen uinput --profile "$real" >> "$LOG" 2>&1 &
pid=$!
sleep 0.2
kill -0 "$pid" 2>/dev/null || { log "AntiMicroX exited early"; exit 0; }
stamp="$(proc_start "$pid")"
[ -n "$stamp" ] || exit 0
printf '%s\t%s\t%s\n' "$rom" "$pid" "$stamp" > "$session"
log "started $rom pid=$pid profile=$real"
exit 0
