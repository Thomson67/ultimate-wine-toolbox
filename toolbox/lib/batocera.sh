#!/bin/bash
BATOCERA_CUSTOM_WINE="/userdata/system/wine/custom"
BATOCERA_SYSTEM_WINE="/usr/wine"
BATOCERA_PORTS="/userdata/roms/ports"

batocera_version() {
    if [ -r /etc/os-release ]; then
        . /etc/os-release
        printf '%s' "${PRETTY_NAME:-Batocera}"
    else
        printf 'Batocera'
    fi
}

ensure_batocera_paths() {
    mkdir -p "$BATOCERA_CUSTOM_WINE" "$BATOCERA_PORTS"
}

free_bytes_path() {
    local path="$1"
    df -PB1 -- "$path" 2>/dev/null | awk 'NR==2 {print $4}'
}

free_bytes_userdata() {
    free_bytes_path /userdata
}

free_bytes_roms() {
    free_bytes_path /userdata/roms
}
