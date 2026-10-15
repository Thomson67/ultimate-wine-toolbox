#!/bin/bash
# AntiMicroX lifecycle: one managed mapping at a time, never kill unrelated instances.
set -u
ROOT="${WT_HOME:-/userdata/system/ultimate-wine-toolbox}"
CFG="$ROOT/config/antimicrox-games.tsv"
STATE="$ROOT/state/antimicrox"
LOG="${WT_AMX_LOG:-/userdata/system/logs/ultimate-wine-toolbox/antimicrox.log}"
[ "${2:-}" = windows ] || exit 0
case "${1:-}" in gameStart|gameStop|amxStop) ;; *) exit 0 ;; esac
rom="${5:-}"
[ -n "$rom" ] || exit 0
mkdir -p "$STATE" "$(dirname "$LOG")"
log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*" >> "$LOG"; }
exec 9>"$STATE/lock"
flock -x 9 || exit 0
# A single running profile prevents conflicting mappings and joystick drift.
session="$STATE/session"
proc_start() {
  local stat
  [ -r "/proc/$1/stat" ] || return 0
  stat="$(cat "/proc/$1/stat" 2>/dev/null)" || return 0
  # comm may contain spaces/parentheses. Fields after the last ')' start at #3.
  stat="${stat##*) }"
  awk '$1 != "Z" {print $20}' <<< "$stat"
}
stop_owned() {
  [ -f "$session" ] || return 0
  local oldrom pid stamp actual cmd
  IFS=$'\t' read -r oldrom pid stamp < "$session" || true
  rm -f -- "$session"
  case "$pid" in ''|*[!0-9]*) return 0 ;; esac
  actual="$(proc_start "$pid")"
  if [ -n "$actual" ] && [ "$actual" = "$stamp" ]; then
    cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
    case "${cmd,,}" in *antimicrox*) kill "$pid" 2>/dev/null || true
      # Wait for device release and single-instance socket shutdown.
      for _ in {1..30}; do
        [ "$(proc_start "$pid")" = "$stamp" ] || break
        sleep 0.1
      done
      if [ "$(proc_start "$pid")" = "$stamp" ]; then
        kill -KILL "$pid" 2>/dev/null || true
      fi
      log "stopped $oldrom pid=$pid" ;; esac
  fi
}
if [ "$1" = amxStop ]; then
  stop_owned
  exit 0
fi
if [ "$1" = gameStop ]; then
  [ -f "$session" ] || exit 0
  IFS=$'\t' read -r oldrom _ < "$session" || true
  [ "$oldrom" = "$rom" ] && stop_owned
  exit 0
fi
stop_owned
[ -f "$CFG" ] || exit 0
profile="$(awk -F '\t' -v p="$rom" '$1==p {v=$2} END {print v}' "$CFG")"
[ -n "$profile" ] || exit 0
[ -f "$profile" ] || { log "profile missing $rom"; exit 0; }
real="$(readlink -f -- "$profile" 2>/dev/null || true)"
case "$real" in /userdata/*) ;; *) log "profile refused (outside /userdata)"; exit 0 ;; esac
binary="$ROOT/tools/antimicrox/antimicrox"
[ -x "$binary" ] || { log "AntiMicroX not installed"; exit 0; }
[ -w /dev/uinput ] || { log "uinput unavailable or not writable"; exit 0; }
# AntiMicroX uses single-instance IPC; never change another user's mapping.
if pgrep -x antimicrox >/dev/null 2>&1; then
  log "AntiMicroX already running outside this game session; launch refused"; exit 0
fi
# Never auto-load a previous game's saved mappings or auto-profile settings.
export XDG_CONFIG_HOME="$STATE/runtime-config"
rm -rf -- "$XDG_CONFIG_HOME"
mkdir -p "$XDG_CONFIG_HOME"
"$binary" --hidden --no-tray --eventgen uinput --profile "$real" >> "$LOG" 2>&1 9>&- &
pid=$!
sleep 1
kill -0 "$pid" 2>/dev/null || { log "AntiMicroX exited early"; exit 0; }
stamp="$(proc_start "$pid")"
[ -n "$stamp" ] || exit 0
printf '%s\t%s\t%s\n' "$rom" "$pid" "$stamp" > "$session"
log "started $rom pid=$pid profile=$real"
exit 0
