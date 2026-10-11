#!/bin/bash

WT_ROOT="${WT_ROOT:-/userdata/system/ultimate-wine-toolbox/toolbox}"
WT_HOME="${WT_ROOT%/toolbox}"
WT_VERSION_FILE="$WT_HOME/VERSION"
WT_TITLE="Ultimate Wine Toolbox"
WT_CONFIG="$WT_HOME/config"
WT_LANGUAGE_FILE="$WT_CONFIG/language"
WT_LANGUAGE=""

wt_version() {
    [ -s "$WT_VERSION_FILE" ] && tr -d '\r\n[:space:]' < "$WT_VERSION_FILE" || printf 'dev'
}

detect_language() {
    local saved=""
    [ -s "$WT_LANGUAGE_FILE" ] && saved="$(tr -d '\r\n[:space:]' < "$WT_LANGUAGE_FILE" 2>/dev/null || true)"
    case "$saved" in
        fr|en) WT_LANGUAGE="$saved"; return ;;
    esac
    case "${LC_ALL:-${LANG:-}}" in fr*|fr_*) WT_LANGUAGE="fr" ;; *) WT_LANGUAGE="en" ;; esac
}

load_i18n() {
    local catalog="$WT_ROOT/lang/$WT_LANGUAGE.sh"
    declare -gA I18N=()
    [ -r "$catalog" ] || return 1
    # shellcheck disable=SC1090
    source "$catalog"
}

i18n() {
    local key="$1" fmt
    shift || true
    fmt="${I18N[$key]-}"
    [ -n "$fmt" ] || { printf '[missing translation: %s]' "$key"; return 1; }
    printf "$fmt" "$@"
}

save_language() {
    mkdir -p "$WT_CONFIG"
    printf '%s\n' "$WT_LANGUAGE" > "$WT_LANGUAGE_FILE"
}

have_dialog() { command -v dialog >/dev/null 2>&1; }

wt_clear_tty() {
    if [ -w /dev/tty ]; then
        printf '\033[2J\033[H' > /dev/tty 2>/dev/null || true
    fi
}

wt_log() {
    [ -n "${WT_SESSION_LOG:-}" ] || return 0
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$WT_SESSION_LOG" 2>/dev/null || true
}

msgbox() {
    local title="$1" body="$2"
    if have_dialog; then
        wt_clear_tty
        dialog --clear --no-shadow --ok-label "$(i18n ok)" --title "$title" --msgbox "$body" 22 96
        local rc=$?
        wt_clear_tty
        return $rc
    else
        clear
        printf '==== %s ====\n\n%b\n\n' "$title" "$body"
        read -r -p "$(i18n press_enter)" _
    fi
} >&2 # Messages must stay visible when callers capture a selector's stdout.

yesno() {
    local title="$1" body="$2"
    if have_dialog; then
        wt_clear_tty
        dialog --clear --no-shadow --yes-label "$(i18n yes)" --no-label "$(i18n no)" --title "$title" --yesno "$body" 22 96
        local rc=$?
        wt_clear_tty
        return $rc
    fi
    clear
    printf '==== %s ====\n\n%b\n\n' "$title" "$body"
    printf '%s [y/N] ' "$(i18n choice_prompt)"
    read -r ans
    case "$ans" in y|Y|o|O|oui|OUI|yes|YES) return 0 ;; *) return 1 ;; esac
} >&2 # Confirmations stay visible inside captured selectors, like msgbox.

yesno_default_no() {
    local title="$1" body="$2"
    if have_dialog; then
        wt_clear_tty
        dialog --clear --no-shadow --defaultno \
            --yes-label "$(i18n yes)" --no-label "$(i18n no)" \
            --title "$title" --yesno "$body" 22 96
        local rc=$?
        wt_clear_tty
        return $rc
    fi

    clear
    printf '==== %s ====\n\n%b\n\n' "$title" "$body"
    printf '%s [y/N] ' "$(i18n choice_prompt)"
    read -r ans
    case "$ans" in y|Y|o|O|oui|OUI|yes|YES) return 0 ;; *) return 1 ;; esac
} >&2 # Confirmations return a status, never selector data on stdout.

menu_select() {
    local title="$1" prompt="$2"
    shift 2
    if have_dialog; then
        wt_clear_tty
        local result rc
        result="$(dialog --stdout --clear --no-shadow --cr-wrap --ok-label "$(i18n ok)" --cancel-label "$(i18n cancel)" \
            --title "$title" --menu "$prompt" 24 100 16 "$@")"
        rc=$?
        wt_clear_tty
        [ "$rc" -eq 0 ] && printf '%s' "$result"
        return "$rc"
    else
        clear
        printf '==== %s ====\n\n%b\n\n' "$title" "$prompt"
        while [ "$#" -gt 0 ]; do
            printf '%s) %s\n' "$1" "$2"
            shift 2
        done
        printf '\n%s' "$(i18n choice_prompt)"
        read -r REPLY
        printf '%s' "$REPLY"
    fi
}

directory_select() {
    local title="$1" prompt="$2" initial="${3:-/userdata/roms/windows/}"

    if have_dialog; then
        wt_clear_tty
        local result rc
        result="$(dialog --stdout --clear --no-shadow             --ok-label "$(i18n ok)" --cancel-label "$(i18n cancel)"             --title "$title" --dselect "$initial" 22 100)"
        rc=$?
        wt_clear_tty
        [ "$rc" -eq 0 ] && printf '%s' "${result%/}"
        return "$rc"
    fi

    input_text "$title" "$prompt" "${initial%/}"
}

input_text() {
    local title="$1" prompt="$2" initial="${3:-}"

    if have_dialog; then
        wt_clear_tty
        local result rc
        result="$(dialog --stdout --clear --no-shadow --cr-wrap \
            --ok-label "$(i18n ok)" --cancel-label "$(i18n cancel)" \
            --title "$title" --inputbox "$prompt" 12 96 "$initial")"
        rc=$?
        wt_clear_tty
        [ "$rc" -eq 0 ] && printf '%s' "$result"
        return "$rc"
    fi

    clear
    printf '==== %s ====\n\n%b\n\n' "$title" "$prompt"
    printf '[%s] : ' "$initial"
    read -r REPLY
    [ -n "$REPLY" ] && printf '%s' "$REPLY" || printf '%s' "$initial"
}

checklist_select() {
    local title="$1" prompt="$2"
    shift 2
    if have_dialog; then
        wt_clear_tty
        local result rc
        result="$(dialog --stdout --separate-output --clear --no-shadow \
            --ok-label "$(i18n ok)" --cancel-label "$(i18n cancel)" \
            --title "$title" --checklist "$prompt" 26 110 18 "$@")"
        rc=$?
        wt_clear_tty
        [ "$rc" -eq 0 ] && printf '%s\n' "$result"
        return "$rc"
    fi

    clear
    printf '==== %s ====\n\n%b\n\n' "$title" "$prompt"
    local -a tags=()
    local index=1 tag label state
    while [ "$#" -gt 0 ]; do
        tag="$1"; label="$2"; state="$3"
        tags+=("$tag")
        printf '%d) %s\n' "$index" "$label"
        index=$((index+1))
        shift 3
    done
    printf '\n%s' "$(i18n checklist_prompt)"
    read -r REPLY
    [ -n "$REPLY" ] || return 1
    local n
    for n in ${REPLY//,/ }; do
        case "$n" in
            ''|*[!0-9]*) continue ;;
        esac
        [ "$n" -ge 1 ] 2>/dev/null && [ "$n" -le "${#tags[@]}" ] 2>/dev/null || continue
        printf '%s\n' "${tags[$((n-1))]}"
    done
}

human_bytes() {
    python3 - "$1" <<'PY'
import sys
n=float(sys.argv[1])
units=["B","KiB","MiB","GiB","TiB"]
for u in units:
    if n < 1024 or u == units[-1]:
        print(f"{n:.1f} {u}" if u!="B" else f"{int(n)} B")
        break
    n /= 1024
PY
}

detect_language
load_i18n
