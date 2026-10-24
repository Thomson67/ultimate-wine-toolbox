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
LIVE_HELPER="$ROOT/toolbox/helpers/antimicrox_live.py"
live=0
profile=""
if [ -f "$ROOT/state/antimicrox-live.json" ] && [ -f "$LIVE_HELPER" ]; then
  profile="$(python3 "$LIVE_HELPER" --home "$ROOT" profile "$rom" 2>> "$LOG")"
  if [ -n "$profile" ]; then
    live=1
  else
    python3 "$LIVE_HELPER" --home "$ROOT" finish --result interrupted >> "$LOG" 2>&1 || true
  fi
fi
if [ "$live" -eq 0 ]; then
  [ -f "$CFG" ] || exit 0
  profile="$(awk -F '\t' -v p="$rom" '$1==p {v=$2} END {print v}' "$CFG")"
fi
live_error() {
  log "$*"
  [ "$live" -eq 0 ] || python3 "$LIVE_HELPER" --home "$ROOT" mark "$rom" --error "$*" >> "$LOG" 2>&1 || true
}
[ -n "$profile" ] || exit 0
[ -f "$profile" ] || { live_error "profile missing $rom"; exit 0; }
real="$(readlink -f -- "$profile" 2>/dev/null || true)"
case "$real" in /userdata/*) ;; *) log "profile refused (outside /userdata)"; exit 0 ;; esac
binary="$ROOT/tools/antimicrox/antimicrox"
[ -x "$binary" ] || { live_error "AntiMicroX not installed"; exit 0; }
[ -w /dev/uinput ] || { live_error "uinput unavailable or not writable"; exit 0; }
# AntiMicroX uses single-instance IPC; never change another user's mapping.
if pgrep -x antimicrox >/dev/null 2>&1 ||
   pgrep -f "^$ROOT/tools/antimicrox/squashfs-root/(AppRun|usr/bin/antimicrox)([[:space:]]|$)" >/dev/null 2>&1; then
  live_error "AntiMicroX already running outside this game session; launch refused"; exit 0
fi
if [ "$live" -eq 1 ]; then
  # One visible editing instance for this game, with an isolated settings home.
  export XDG_CONFIG_HOME="$STATE/live-config"
  rm -rf -- "$XDG_CONFIG_HOME"
  mkdir -p "$XDG_CONFIG_HOME"
  python3 "$ROOT/toolbox/helpers/antimicrox_editor.py" "$XDG_CONFIG_HOME" >> "$LOG" 2>&1 || true
  args=(--show --eventgen uinput --log-level info --profile "$real")
else
  # Never auto-load a previous game's saved mappings or auto-profile settings.
  export XDG_CONFIG_HOME="$STATE/runtime-config"
  rm -rf -- "$XDG_CONFIG_HOME"
  mkdir -p "$XDG_CONFIG_HOME"
  args=(--hidden --no-tray --eventgen uinput --log-level info --profile "$real")
fi
# Batocera 44 waits for captured hook pipes to reach EOF. A parent wrapper
# can retain duplicates beyond stdout/stderr; a shell background launch keeps
# those open for the editor's lifetime. Close every inherited nonstandard FD
# and give AMX its own session, stdin and log before returning to configgen.
if ! pid="$(python3 - "$binary" "$LOG" "${args[@]}" 9>&- <<'PY'
import subprocess
import sys

with open(sys.argv[2], 'ab', buffering=0) as log:
    process = subprocess.Popen([sys.argv[1], *sys.argv[3:]],
                               stdin=subprocess.DEVNULL, stdout=log,
                               stderr=subprocess.STDOUT, close_fds=True,
                               start_new_session=True)
print(process.pid)
PY
)"; then
  live_error "Failed to detach AntiMicroX"; exit 0
fi
sleep 1
kill -0 "$pid" 2>/dev/null || { live_error "AntiMicroX exited early"; exit 0; }
stamp="$(proc_start "$pid")"
[ -n "$stamp" ] || exit 0
printf '%s\t%s\t%s\n' "$rom" "$pid" "$stamp" > "$session"
if [ "$live" -eq 1 ]; then
  python3 "$LIVE_HELPER" --home "$ROOT" mark "$rom" --phase running >> "$LOG" 2>&1 || true
  if [ -f "$ROOT/toolbox/helpers/antimicrox_focus.py" ] && command -v batocera-flash-screen >/dev/null 2>&1; then
    python3 "$ROOT/toolbox/helpers/antimicrox_focus.py" spawn "$rom" "$pid" "$stamp" --home "$ROOT" >> "$LOG" 2>&1 9>&- || true
  fi
fi
log "started $rom pid=$pid profile=$real live=$live"
exit 0
