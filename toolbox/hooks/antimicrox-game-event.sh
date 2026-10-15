#!/bin/bash
# Native AntiMicroX game-event hook (never modifies Wine prefixes).
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
# Derive file key from full ROM path, avoiding collisions between game names.
key="$(printf '%s' "$rom" | sha256sum | awk '{print $1}')"
pidfile="$STATE/$key.pid"
stop_owned() {
  [ -f "$pidfile" ] || return 0
  local pid
  pid="$(cat "$pidfile" 2>/dev/null || true)"
  rm -f -- "$pidfile"
  case "$pid" in ''|*[!0-9]*) return 0 ;; esac
  # Only stop a process launched by us, and never kill an arbitrary reused PID.
  if [ -r "/proc/$pid/cmdline" ] && tr '\0' ' ' < "/proc/$pid/cmdline" | grep -qi 'antimicrox'; then
    kill "$pid" 2>/dev/null || true
    log "stopped $rom pid=$pid"
  fi
}
if [ "$1" = gameStop ]; then stop_owned; exit 0; fi
[ -f "$CFG" ] || exit 0
profile="$(awk -F '\t' -v p="$rom" '$1==p {v=$2} END {print v}' "$CFG")"
[ -n "$profile" ] || exit 0
[ -f "$profile" ] || { log "missing profile for $rom: $profile"; exit 0; }
case "$profile" in /userdata/*) ;; *) log "refused profile outside /userdata"; exit 0 ;; esac
if command -v antimicrox >/dev/null 2>&1; then
  binary="$(command -v antimicrox)"
elif [ -x "$ROOT/tools/antimicrox/antimicrox" ]; then
  binary="$ROOT/tools/antimicrox/antimicrox"
else
  log "AntiMicroX binary missing for $rom"
  exit 0
fi
if [ ! -e /dev/uinput ]; then log "uinput unavailable, refusing Wayland start for $rom"; exit 0; fi
stop_owned
"$binary" --hidden --no-tray --eventgen uinput --profile "$profile" >> "$LOG" 2>&1 &
pid=$!
printf '%s\n' "$pid" > "$pidfile"
log "started $rom pid=$pid profile=$profile"
exit 0
