#!/bin/bash

LOG_DIR="/userdata/system/logs/ultimate-wine-toolbox"
BOOT_LOG="$LOG_DIR/port-launch.log"
LAUNCHER="/userdata/system/ultimate-wine-toolbox/toolbox/launch-in-terminal.sh"
TOOLBOX_PORT="/userdata/roms/ports/Ultimate Wine Toolbox.sh"
STATE_DIR="/userdata/system/ultimate-wine-toolbox/state"
RESTART_REQUEST="$STATE_DIR/restart-es.request"
LAUNCH_REQUEST="$STATE_DIR/launch-game.request"
RESUME_REQUEST="$STATE_DIR/resume-wsq.request"
RESULT_FILE="$STATE_DIR/wsq-launch-result"
DIAG_REQUEST="$STATE_DIR/reshade-diagnostic.json"
RESUME_ENV=WT_AUTO_RESUME_WSQ

mkdir -p "$LOG_DIR" "$STATE_DIR"
export DISPLAY="${DISPLAY:-:0}"

# xterm decides its character encoding when the terminal process starts.
# EmulationStation/Ports may launch us without the UTF-8 locale later selected
# by launch-in-terminal.sh, so initialize a known UTF-8 locale before xterm.
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

    printf '%s' "C.UTF-8"
}

WT_UTF8_LOCALE="$(select_utf8_locale)"
export LANG="$WT_UTF8_LOCALE"
export LC_ALL="$WT_UTF8_LOCALE"
export LANGUAGE="$WT_UTF8_LOCALE"

{
    echo
    echo "===== $(date '+%Y-%m-%d %H:%M:%S %z') ====="
    echo "port_launcher=$0"
    echo "uid=$(id -u 2>/dev/null || true)"
    echo "DISPLAY=$DISPLAY"
    echo "TERM=${TERM:-<unset>}"
    echo "LANG=${LANG:-<unset>}"
    echo "LC_ALL=${LC_ALL:-<unset>}"
    echo "xterm=$(command -v xterm 2>/dev/null || true)"
    echo "launcher=$LAUNCHER"
} >>"$BOOT_LOG" 2>&1

# Configurable terminal profile. Changes apply on the next Ports launch.
WT_DISPLAY_MODE_FILE="/userdata/system/ultimate-wine-toolbox/config/display-mode"
WT_FONT_SIZE_FILE="/userdata/system/ultimate-wine-toolbox/config/font-size"
WT_FONT_SIZE=11
WT_GEOMETRY="120x36"
WT_FULLSCREEN=0
case "$(head -n 1 "$WT_DISPLAY_MODE_FILE" 2>/dev/null)" in
    handheld) WT_FONT_SIZE=16; WT_GEOMETRY="88x28" ;; # Legacy preset
    fullscreen) WT_FULLSCREEN=1 ;;
esac
# Independent font preference overrides legacy handheld setting.
case "$(head -n 1 "$WT_FONT_SIZE_FILE" 2>/dev/null)" in
    11|13|16|18|20) WT_FONT_SIZE="$(head -n 1 "$WT_FONT_SIZE_FILE")" ;;
esac
WT_XTERM_DISPLAY_ARGS=(-geometry "$WT_GEOMETRY")
if [ "$WT_FULLSCREEN" -eq 1 ]; then
    WT_XTERM_DISPLAY_ARGS=(-fullscreen)
fi

if [ ! -x /usr/bin/xterm ]; then
    echo "ERROR: /usr/bin/xterm missing or not executable." >>"$BOOT_LOG"
    exit 1
fi

if [ ! -s "$LAUNCHER" ]; then
    echo "ERROR: terminal launcher missing: $LAUNCHER" >>"$BOOT_LOG"
    exit 1
fi

resume_requested=0
if [ -f "$RESUME_REQUEST" ]; then
    [ "$(cat "$RESUME_REQUEST")" != reshade ] || RESUME_ENV=WT_AUTO_RESUME_RESH
    rm -f -- "$RESUME_REQUEST"
    resume_requested=1
    echo "wsq_resume_request_consumed=1" >>"$BOOT_LOG"
fi

if [ "${WT_SKIP_INITIAL_TOOLBOX:-0}" = "1" ]; then
    unset WT_SKIP_INITIAL_TOOLBOX
    rc=0
    echo "initial_toolbox_skipped=1" >>"$BOOT_LOG"
else
    if [ "$resume_requested" -eq 1 ]; then
        env "$RESUME_ENV=1" /usr/bin/xterm \
            +lc \
            -u8 \
            -fa "DejaVu Sans Mono" \
            -fs "$WT_FONT_SIZE" \
            -title "Ultimate Wine Toolbox" \
            "${WT_XTERM_DISPLAY_ARGS[@]}" \
            -e /bin/bash "$LAUNCHER" \
            >>"$BOOT_LOG" 2>&1
    else
        /usr/bin/xterm \
            +lc \
            -u8 \
            -fa "DejaVu Sans Mono" \
            -fs "$WT_FONT_SIZE" \
            -title "Ultimate Wine Toolbox" \
            "${WT_XTERM_DISPLAY_ARGS[@]}" \
            -e /bin/bash "$LAUNCHER" \
            >>"$BOOT_LOG" 2>&1
    fi

    rc=$?
    echo "xterm_exit_code=$rc" >>"$BOOT_LOG"
fi

wait_for_es_api() {
    local attempt=0
    while [ "$attempt" -lt 40 ]; do
        attempt=$((attempt + 1))
        if command -v curl >/dev/null 2>&1; then
            if curl -sS --max-time 1 -o /dev/null http://127.0.0.1:1234/ >/dev/null 2>&1; then
                echo "es_api_ready_after_attempt=$attempt" >>"$BOOT_LOG"
                return 0
            fi
        elif command -v wget >/dev/null 2>&1; then
            if wget -q -T 1 -O /dev/null http://127.0.0.1:1234/ >/dev/null 2>&1; then
                echo "es_api_ready_after_attempt=$attempt" >>"$BOOT_LOG"
                return 0
            fi
        else
            echo "ERROR: curl/wget unavailable; cannot probe ES API." >>"$BOOT_LOG"
            return 1
        fi
        sleep 0.25
    done

    echo "ERROR: ES API not ready after timeout." >>"$BOOT_LOG"
    return 1
}

wait_for_es_restart() {
    local old_pid="$1" attempt=0 new_pid=""
    while [ "$attempt" -lt 80 ]; do
        attempt=$((attempt + 1))
        new_pid="$(pidof emulationstation 2>/dev/null | awk '{print $1}')"
        if [ -n "$new_pid" ] && { [ -z "$old_pid" ] || [ "$new_pid" != "$old_pid" ]; }; then
            echo "es_new_pid=$new_pid" >>"$BOOT_LOG"
            echo "es_pid_changed_after_attempt=$attempt" >>"$BOOT_LOG"
            return 0
        fi
        sleep 0.25
    done

    echo "ERROR: EmulationStation PID did not change after restart timeout." >>"$BOOT_LOG"
    return 1
}

launch_game_via_es() {
    local rom="$1"
    [ -n "$rom" ] || return 1

    echo "es_launch_rom=$rom" >>"$BOOT_LOG"

    if command -v curl >/dev/null 2>&1; then
        curl -fsS --max-time 5 -X POST --data-binary "$rom"             http://127.0.0.1:1234/launch >>"$BOOT_LOG" 2>&1
        return $?
    fi

    if command -v wget >/dev/null 2>&1; then
        wget -q -T 5 --post-data="$rom" -O -             http://127.0.0.1:1234/launch >>"$BOOT_LOG" 2>&1
        return $?
    fi

    return 1
}

get_running_game_http_code() {
    if command -v curl >/dev/null 2>&1; then
        curl -sS --max-time 2 -o /dev/null -w '%{http_code}' \
            http://127.0.0.1:1234/runningGame 2>/dev/null || true
        return 0
    fi

    if command -v wget >/dev/null 2>&1; then
        local body
        body="$(wget -q -T 2 -O - http://127.0.0.1:1234/runningGame 2>/dev/null || true)"
        if printf '%s' "$body" | grep -q 'NO GAME RUNNING'; then
            printf '201'
        elif [ -n "$body" ]; then
            printf '200'
        fi
        return 0
    fi

    return 1
}

wait_for_game_start() {
    local deadline=$((SECONDS + 300)) code=""
    while [ "$SECONDS" -lt "$deadline" ]; do
        code="$(get_running_game_http_code)"
        if [ "$code" = "200" ]; then
            GAME_STARTED_AT=$SECONDS
            echo "game_started_at=$GAME_STARTED_AT" >>"$BOOT_LOG"
            return 0
        fi
        sleep 0.25
    done
    echo "ERROR: game launch not confirmed within 300 seconds." >>"$BOOT_LOG"
    return 1
}

wait_for_game_stop() {
    local code=""
    while true; do
        code="$(get_running_game_http_code)"
        if [ "$code" = "201" ]; then
            echo "game_stopped_time=$(date '+%Y-%m-%d %H:%M:%S %z')" >>"$BOOT_LOG"
            return 0
        fi
        sleep 0.5
    done
}

monitor_wsq_launch() {
    local result diagnostic_pid=""
    if [ -f "$DIAG_REQUEST" ]; then
        python3 /userdata/system/ultimate-wine-toolbox/toolbox/helpers/reshade_diagnostic.py \
            --home /userdata/system/ultimate-wine-toolbox observe "$launch_rom" >> "$BOOT_LOG" 2>&1 &
        diagnostic_pid=$!
    fi
    if ! launch_game_via_es "$launch_rom"; then
        result="launch_failed"
    elif ! wait_for_game_start; then
        result="start_unconfirmed"
    else
        wait_for_game_stop
        if [ "$((SECONDS - GAME_STARTED_AT))" -lt 30 ]; then
            result="short"
        else
            result="normal"
        fi
    fi
    if [ -n "$diagnostic_pid" ]; then
        : > "$STATE_DIR/reshade-diagnostic.stop"
        wait "$diagnostic_pid" || true
    fi
    printf '%s\n' "$result" > "$RESULT_FILE.tmp"
    mv -f -- "$RESULT_FILE.tmp" "$RESULT_FILE"
    echo "wsq_launch_result=$result" >>"$BOOT_LOG"
    resume_wsquashfs_toolbox || true
}

resume_wsq_unavailable() {
    printf '%s\n' "es_unavailable" > "$RESULT_FILE"
    resume_wsquashfs_toolbox || true
}

resume_wsquashfs_toolbox() {
    echo "wsq_auto_resume=1" >>"$BOOT_LOG"

    # Relaunch the Toolbox through EmulationStation rather than spawning a
    # naked xterm. This restores Batocera's normal Ports lifecycle, including
    # evmapy/Pad2Key and Wayland compositor focus handling.
    if [ -f "$DIAG_REQUEST" ]; then
        RESUME_ENV=WT_AUTO_RESUME_RESH
        printf '%s\n' reshade > "$RESUME_REQUEST"
    else
        : > "$RESUME_REQUEST"
    fi

    if wait_for_es_api && launch_game_via_es "$TOOLBOX_PORT"; then
        echo "wsq_resume_via_es=1" >>"$BOOT_LOG"
        return 0
    fi

    echo "ERROR: WSquashFS resume via EmulationStation failed; using direct xterm fallback." >>"$BOOT_LOG"
    rm -f -- "$RESUME_REQUEST"

    env "$RESUME_ENV=1" /usr/bin/xterm \
        +lc \
        -u8 \
        -fa "DejaVu Sans Mono" \
        -fs "$WT_FONT_SIZE" \
        -title "Ultimate Wine Toolbox" \
        "${WT_XTERM_DISPLAY_ARGS[@]}" \
        -e /bin/bash "$LAUNCHER" \
        >>"$BOOT_LOG" 2>&1

    local resume_rc=$?
    echo "wsq_auto_resume_exit_code=$resume_rc" >>"$BOOT_LOG"

    if [ -f "$RESTART_REQUEST" ] || [ -f "$LAUNCH_REQUEST" ]; then
        echo "wsq_chained_request=1" >>"$BOOT_LOG"
        WT_SKIP_INITIAL_TOOLBOX=1 exec /bin/bash "$0"
    fi

    return "$resume_rc"
}

launch_rom=""
if [ -f "$LAUNCH_REQUEST" ]; then
    IFS= read -r launch_rom < "$LAUNCH_REQUEST" || true
    rm -f -- "$LAUNCH_REQUEST"
    echo "es_launch_requested=1" >>"$BOOT_LOG"
fi

if [ -f "$RESTART_REQUEST" ]; then
    rm -f -- "$RESTART_REQUEST"
    {
        echo "es_restart_requested=1"
        echo "es_restart_time=$(date '+%Y-%m-%d %H:%M:%S %z')"
    } >>"$BOOT_LOG"

    if command -v batocera-es-swissknife >/dev/null 2>&1; then
        old_es_pid="$(pidof emulationstation 2>/dev/null | awk '{print $1}')"
        echo "es_old_pid=${old_es_pid:-<none>}" >>"$BOOT_LOG"

        batocera-es-swissknife --restart >>"$BOOT_LOG" 2>&1
        restart_rc=$?
        echo "es_restart_exit_code=$restart_rc" >>"$BOOT_LOG"

        if [ "$restart_rc" -eq 0 ] && [ -n "$launch_rom" ]; then
            if wait_for_es_restart "$old_es_pid" && wait_for_es_api; then
                monitor_wsq_launch
            else
                echo "ERROR: automatic game launch skipped because restarted ES is unavailable." >>"$BOOT_LOG"
                resume_wsq_unavailable
            fi
        elif [ -n "$launch_rom" ]; then
            resume_wsq_unavailable
        fi
    else
        echo "ERROR: batocera-es-swissknife not found; ES restart skipped." >>"$BOOT_LOG"
        [ -z "$launch_rom" ] || resume_wsq_unavailable
    fi
elif [ -n "$launch_rom" ]; then
    if wait_for_es_api; then
        monitor_wsq_launch
    else
        resume_wsq_unavailable
    fi
fi

exit "$rc"
