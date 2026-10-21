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
