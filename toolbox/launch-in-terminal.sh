#!/bin/bash
set -u

ROOT="/userdata/system/ultimate-wine-toolbox/toolbox"
MAIN="$ROOT/ultimate-wine-toolbox.sh"
LOG_DIR="/userdata/system/logs/ultimate-wine-toolbox"
mkdir -p "$LOG_DIR"

# Safety net for direct launches: force a UTF-8 locale known to exist.
select_utf8_locale() {
    local syslang candidate available
    syslang="$(batocera-settings-get system.language 2>/dev/null | tr -d '\r\n[:space:]' || true)"
    syslang="${syslang%%.*}"

    available="$(locale -a 2>/dev/null || true)"
    for candidate in "$syslang.UTF-8" "$syslang.utf8" "C.UTF-8" "C.utf8" "en_US.UTF-8" "en_US.utf8"; do
        [ -n "$candidate" ] || continue
        if printf '%s\n' "$available" | grep -Fxqi "$candidate"; then
            printf '%s' "$candidate"
            return 0
        fi
    done

    # Last fallback: keep UTF-8 semantics requested by xterm even on very
    # minimal builds where locale -a is incomplete.
    printf '%s' "C.UTF-8"
}

WT_UTF8_LOCALE="$(select_utf8_locale)"
export LANG="$WT_UTF8_LOCALE"
export LC_ALL="$WT_UTF8_LOCALE"
export LANGUAGE="$WT_UTF8_LOCALE"

# Keep only the 20 most recent Toolbox session logs.
ls -1t "$LOG_DIR"/toolbox-*.log 2>/dev/null | tail -n +21 | while IFS= read -r oldlog; do
    [ -n "$oldlog" ] && rm -f -- "$oldlog"
done

STAMP="$(date '+%Y%m%d-%H%M%S')"
LOG="$LOG_DIR/toolbox-$STAMP.log"
ln -sfn "$(basename "$LOG")" "$LOG_DIR/latest.log" 2>/dev/null || true

# IMPORTANT: do not pipe stdout/stderr through tee here.
# dialog must keep a real TTY on stderr or its screen handling becomes unstable.
export WT_SESSION_LOG="$LOG"

{
    echo "===== Ultimate Wine Toolbox ====="
    echo "date=$(date '+%Y-%m-%d %H:%M:%S %z')"
    echo "user=$(id -un 2>/dev/null || true) uid=$(id -u 2>/dev/null || true)"
    echo "pwd=$(pwd)"
    echo "DISPLAY=${DISPLAY:-<unset>}"
    echo "TERM=${TERM:-<unset>}"
    echo "LANG=${LANG:-<unset>}"
    echo "LC_ALL=${LC_ALL:-<unset>}"
    echo "main=$MAIN"
} >>"$LOG" 2>&1

# BEGIN UWT RETURN FOCUS
# Activate the existing terminal only for a return, without delaying the UI.
if [ "${WT_AUTO_RESUME_WSQ:-0}" = 1 ] || \
   [ "${WT_AUTO_RESUME_AMX:-0}" = 1 ] || \
   [ "${WT_AUTO_RESUME_RESH:-0}" = 1 ]; then
    python3 "$ROOT/helpers/toolbox_focus.py" --pid "$PPID" --owner "$$" \
        >> "$LOG" 2>&1 &
fi
# END UWT RETURN FOCUS

if [ ! -s "$MAIN" ]; then
    echo "ERROR: main script missing: $MAIN" | tee -a "$LOG" >&2
    rc=70
elif ! /bin/bash -n "$MAIN" >>"$LOG" 2>&1; then
    echo "ERROR: main script syntax check failed. See $LOG" >&2
    rc=71
else
    /bin/bash "$MAIN"
    rc=$?
fi

{
    echo "toolbox_exit_code=$rc"
    echo "log=$LOG"
} >>"$LOG" 2>&1

if [ "$rc" -ne 0 ]; then
    echo
    echo "The Toolbox exited with an error (code $rc)."
    echo "Log: $LOG"
    echo "Press Enter to close this terminal."
    read -r _
fi

exit "$rc"
