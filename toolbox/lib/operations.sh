#!/bin/bash

wt_operation_run() {
    local owner="${UWT_SESSION_OWNER:-${UWT_OPERATION_OWNER:-}}"
    [ -n "$owner" ] || read -r owner _ < /proc/self/stat
    # Shell callbacks are synchronous and keep their existing local state.
    # External workers get a session guardian, including when output is piped.
    if [ "$(type -t "$1")" = function ]; then
        "$@"
    else
        python3 "$WT_ROOT/helpers/attached_operation.py" \
            --owner "$owner" -- "$@"
    fi
}

# Preserve the worker status as well as failures while writing the report.
# stdout remains available to dialog's progress gauge.
wt_operation_logged_command() {
    local log="$1"
    shift
    wt_operation_run "$@" 2>&1 | tee -a "$log"
    local -a statuses=("${PIPESTATUS[@]}")
    [ "${statuses[0]}" -eq 0 ] || return "${statuses[0]}"
    return "${statuses[1]}"
}
