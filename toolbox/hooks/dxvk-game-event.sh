#!/bin/bash

ROOT="/userdata/system/ultimate-wine-toolbox"
CONFIG_DIR="$ROOT/config"
BUNDLE_DIR="$ROOT/dxvk/bundles"
GLOBAL_FILE="$CONFIG_DIR/dxvk-global"
GAME_FILE="$CONFIG_DIR/dxvk-games.tsv"
DXVK_PATH="/userdata/system/wine/dxvk"
LOG_DIR="/userdata/system/logs/ultimate-wine-toolbox"
LOG_FILE="$LOG_DIR/dxvk-game-event.log"

mkdir -p "$LOG_DIR"

rotate_dxvk_log() {
    local size archive
    [ -f "$LOG_FILE" ] || return 0
    size="$(stat -c %s "$LOG_FILE" 2>/dev/null || echo 0)"
    [ "$size" -ge 1048576 ] 2>/dev/null || return 0

    archive="$LOG_DIR/dxvk-game-event-$(date '+%Y%m%d-%H%M%S')-$.log"
    mv -f "$LOG_FILE" "$archive" 2>/dev/null || return 0

    # 19 archives + the current log = at most 20 DXVK logs.
    ls -1t "$LOG_DIR"/dxvk-game-event-*.log 2>/dev/null | tail -n +20 | while IFS= read -r oldlog; do
        [ -n "$oldlog" ] && rm -f -- "$oldlog"
    done
}

rotate_dxvk_log

log() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_FILE" 2>/dev/null || true
}

event="${1:-}"
system="${2:-}"
rom="${5:-}"

[ "$system" = "windows" ] || exit 0

log "event=$event system=$system rom=$rom"

managed_target() {
    local target
    [ -L "$DXVK_PATH" ] || return 1
    target="$(readlink -f "$DXVK_PATH" 2>/dev/null || true)"
    case "$target" in
        "$BUNDLE_DIR"/*) return 0 ;;
        *) return 1 ;;
    esac
}

apply_state() {
    local state="$1" target before after

    before="$(readlink -f "$DXVK_PATH" 2>/dev/null || printf '<none>')"
    log "apply_state requested=$state before=$before"

    if [ "$state" = "batocera" ] || [ -z "$state" ]; then
        if managed_target; then
            rm -f "$DXVK_PATH"
        fi
        after="$(readlink -f "$DXVK_PATH" 2>/dev/null || printf '<none>')"
        log "apply_state batocera after=$after"
        return 0
    fi

    target="$BUNDLE_DIR/$state"
    if [ ! -d "$target/x64" ] || [ ! -d "$target/x32" ]; then
        log "bundle_invalid target=$target"
        return 0
    fi

    if [ -e "$DXVK_PATH" ] && [ ! -L "$DXVK_PATH" ]; then
        log "skip_external_directory path=$DXVK_PATH"
        return 0
    fi

    if [ -L "$DXVK_PATH" ] && ! managed_target; then
        log "skip_external_symlink path=$DXVK_PATH target=$(readlink -f "$DXVK_PATH" 2>/dev/null || true)"
        return 0
    fi

    rm -f "$DXVK_PATH" 2>/dev/null || true
    if ln -s "$target" "$DXVK_PATH" 2>/dev/null; then
        after="$(readlink -f "$DXVK_PATH" 2>/dev/null || printf '<none>')"
        log "apply_state success requested=$state after=$after"
    else
        log "apply_state failed requested=$state target=$target"
    fi
}

global_state=""
if [ -s "$GLOBAL_FILE" ]; then
    global_state="$(head -n1 "$GLOBAL_FILE" | tr -d '\r\n')"
fi

log "global_state_initial=$global_state"

if [ -z "$global_state" ]; then
    if managed_target; then
        target="$(readlink -f "$DXVK_PATH" 2>/dev/null || true)"
        global_state="$(basename "$target")"
    elif [ ! -e "$DXVK_PATH" ] && [ ! -L "$DXVK_PATH" ]; then
        global_state="batocera"
    else
        exit 0
    fi
fi

case "$event" in
    gameStart)
        [ -n "$rom" ] || exit 0
        for test in "$ROOT/state"/wsq-dxvk-test.*; do
            [ -f "$test" ] || continue
            test_pid="${test##*.}"
            [[ "$test_pid" =~ ^[1-9][0-9]*$ ]] || continue
            if ! kill -0 "$test_pid" 2>/dev/null; then
                rm -f -- "$test"
                continue
            fi
            {
                IFS= read -r test_rom && IFS= read -r test_bundle
            } < "$test" || continue
            [ "$test_rom" = "$rom" ] || continue
            if [ "$test_bundle" = __GLOBAL__ ]; then
                log "gameStart selected=test-global:$global_state"
                apply_state "$global_state"
            elif [[ -n "$test_bundle" && "$test_bundle" != */* ]] &&
                 [ -d "$BUNDLE_DIR/$test_bundle/x32" ] && [ -d "$BUNDLE_DIR/$test_bundle/x64" ]; then
                log "gameStart selected=test:$test_bundle"
                apply_state "$test_bundle"
            else
                log "gameStart test_bundle_invalid=$test_bundle selected=global:$global_state"
                apply_state "$global_state"
            fi
            exit 0
        done
        override=""
        if [ -s "$GAME_FILE" ]; then
            override="$(DXVK_ROM="$rom" awk -F '\t' '$2==ENVIRON["DXVK_ROM"] {v=$1} END{print v}' "$GAME_FILE")"
        fi

        log "gameStart override=$override global=$global_state"
        if [ -n "$override" ] && [ -d "$BUNDLE_DIR/$override" ]; then
            log "gameStart selected=override:$override"
            apply_state "$override"
        else
            log "gameStart selected=global:$global_state"
            apply_state "$global_state"
        fi
        ;;
    gameStop)
        log "gameStop restore=$global_state"
        apply_state "$global_state"
        ;;
esac

exit 0
