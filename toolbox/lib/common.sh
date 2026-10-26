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


# Fit Dialog windows to the current terminal while preserving desktop sizes.
# Only defined when the real Dialog executable is available.
if type -P dialog >/dev/null 2>&1; then
dialog() {
    local -a args=("$@")
    local cols lines index widget h w limit max_h max_w list_h theme rc
    cols="$(tput cols 2>/dev/null || true)"
    lines="$(tput lines 2>/dev/null || true)"
    if [[ ! "$cols" =~ ^[0-9]+$ || ! "$lines" =~ ^[0-9]+$ ]]; then
        command dialog "$@"
        return $?
    fi
    max_w=$((cols - 4))
    max_h=$((lines - 2))
    # Too small even for Dialog: let it report its own error.
    if ((max_w < 24 || max_h < 8)); then
        command dialog "$@"
        return $?
    fi
    for ((index=0; index<${#args[@]}; index++)); do
        widget="${args[index]}"
        case "$widget" in
            --msgbox|--yesno|--inputbox|--passwordbox|--menu|--checklist|--radiolist|--textbox|--tailbox|--dselect|--fselect|--infobox|--gauge)
                # Dialog widget syntax: option, text/path, height, width.
                ((index+3 < ${#args[@]})) || break
                h="${args[index+2]}"
                w="${args[index+3]}"
                [[ "$h" =~ ^[0-9]+$ && "$w" =~ ^[0-9]+$ ]] || break
                ((h > max_h)) && args[index+2]="$max_h"
                ((w > max_w)) && args[index+3]="$max_w"
                case "$widget" in
                    --menu|--checklist|--radiolist)
                        list_h="${args[index+4]:-}"
                        if [[ "$list_h" =~ ^[0-9]+$ ]]; then
                            limit=$((${args[index+2]} - 7))
                            ((limit < 1)) && limit=1
                            ((list_h > limit)) && args[index+4]="$limit"
                        fi
                        ;;
                esac
                break
                ;;
        esac
    done
    # Regular black menu entries, with the original bold title and selection.
    # With --no-tags, Dialog uses tag_color to draw the entire item label.
    # Adjust a temporary theme copy; never rewrite the user's configuration.
    if [[ "${widget:-}" = --menu || "${widget:-}" = --checklist || "${widget:-}" = --radiolist ]]; then
        theme="$(mktemp /tmp/uwt-menu-theme.XXXXXX)" || theme=""
        if [ -n "$theme" ] && command dialog --create-rc "$theme" 2>/dev/null &&
           sed -i -E -e '/^[[:space:]]*title_color[[:space:]]*=/b' \
               -e 's/(=[[:space:]]*\([^,]*,[^,]*,)[[:space:]]*ON/\1OFF/' \
               -e 's/^(item_color|tag_color)[[:space:]]*=.*/\1 = dialog_color/' "$theme"; then
            if [[ "${WT_MENU_LIST:-0}" = 1 || "$widget" != --menu ]]; then
                # Data rows retain keyboard navigation without a red initial.
                sed -i -E -e 's/^tag_key_color[[:space:]]*=.*/tag_key_color = tag_color/' \
                    -e 's/^tag_key_selected_color[[:space:]]*=.*/tag_key_selected_color = tag_selected_color/' "$theme"
            fi
            if [ "${WT_MENU_GAME_COLUMNS:-0}" = 1 ]; then
                # Native tag/item columns allow bold game names with plain details.
                sed -i -E -e 's/^tag_color[[:space:]]*=.*/tag_color = (BLACK,WHITE,ON)/' \
                    -e 's/^tag_selected_color[[:space:]]*=.*/tag_selected_color = (YELLOW,BLUE,ON)/' "$theme"
            fi
            DIALOGRC="$theme" command dialog "${args[@]}"
            rc=$?
            rm -f -- "$theme"
            return "$rc"
        fi
        [ -z "$theme" ] || rm -f -- "$theme"
    fi
    command dialog "${args[@]}"
}
fi

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

# A scrollable, wrapped copy of an entry, without activating its action.
wt_menu_item_details() (
    local title="$1" text="$2" width="$3" report
    report="$(mktemp /tmp/uwt-menu-details.XXXXXX)" || return 1
    trap 'rm -f -- "$report"' EXIT
    printf '%s\n' "$text" | python3 -c 'import sys,textwrap
width=max(12,int(sys.argv[1])-8)
for line in sys.stdin.read().splitlines():
    print(textwrap.fill(line, width, replace_whitespace=False, break_on_hyphens=False) if line else "")' "$width" > "$report" || return 1
    wt_clear_tty
    dialog --clear --no-shadow --scrollbar --exit-label "$(i18n back)" \
        --title "$title" --textbox "$report" 24 "$width"
    wt_clear_tty
) >&2

menu_select() {
    local title="$1" prompt="$2"
    shift 2
    if have_dialog; then
        local result rc cols width=100 detail_label key text found game prefix suffix tag visible extra count max_name
        local WT_MENU_GAME_COLUMNS=0
        local -a options=("$@") display_options=("$@") display_tags=() default_item=() tag_style=(--no-tags)
        local -A seen_tags=()
        cols="$(tput cols 2>/dev/null || true)"
        if [[ "$cols" =~ ^[0-9]+$ ]] && ((cols >= 28)); then width=$((cols - 4)); fi
        # Use native columns only for game rows with trailing information.
        # The original tags/labels remain the action values and full-text source.
        if [ "${WT_MENU_LIST:-0}" = 1 ] && [[ "$(declare -p WT_MENU_GAME_LABELS 2>/dev/null)" = 'declare -A '* ]]; then
            for ((key=0; key<${#options[@]}; key+=2)); do
                tag="${options[key]}"
                game="${WT_MENU_GAME_LABELS["$tag"]-}"
                text="${options[key+1]}"
                if [ -n "$game" ] && [[ "$text" = *"$game"* ]] && [ "$text" != "$game" ]; then
                    WT_MENU_GAME_COLUMNS=1
                    break
                fi
            done
        fi
        if [ "$WT_MENU_GAME_COLUMNS" -eq 1 ]; then
            display_options=(); tag_style=()
            max_name=$(((width - 12) / 2))
            ((max_name >= 12)) || max_name=12
            for ((key=0; key<${#options[@]}; key+=2)); do
                tag="${options[key]}"
                game="${WT_MENU_GAME_LABELS["$tag"]-}"
                text="${options[key+1]}"
                visible="$text"; suffix=""
                if [ -n "$game" ] && [[ "$text" = *"$game"* ]]; then
                    prefix="${text%%"$game"*}"
                    suffix="${text#*"$game"}"
                    visible="$prefix$game"
                    suffix="${suffix# — }"
                fi
                prefix="$visible"
                if ((${#prefix} > max_name)); then prefix="${prefix:0:max_name-1}…"; fi
                visible="$prefix"; count=1
                while [ -n "${seen_tags["$visible"]-}" ]; do
                    count=$((count+1)); extra=" ($count)"
                    visible="${prefix:0:max_name-${#extra}}$extra"
                done
                seen_tags["$visible"]=1
                display_tags+=("$visible")
                display_options+=("$visible" "$suffix")
            done
        fi
        if [ "${WT_LANGUAGE:-fr}" = fr ]; then detail_label='Texte complet'; else detail_label='Full text'; fi
        ((width >= 50)) || detail_label=Info
        while true; do
            wt_clear_tty
            result="$(dialog --stdout --clear --no-shadow --cr-wrap "${tag_style[@]}" \
                --help-button --help-tags --help-label "$detail_label" \
                --ok-label "$(i18n ok)" --cancel-label "${WT_MENU_CANCEL_LABEL:-$(i18n cancel)}" \
                "${default_item[@]}" --title "$title" --menu "$prompt" 24 "$width" 16 "${display_options[@]}")"
            rc=$?
            wt_clear_tty
            if [ "$rc" -eq 2 ]; then
                found=0
                for ((key=0; key<${#options[@]}; key+=2)); do
                    visible="${options[key]}"
                    [ "$WT_MENU_GAME_COLUMNS" -ne 1 ] || visible="${display_tags[key/2]}"
                    if [ "$result" = "HELP $visible" ] || [ "$result" = "HELP \"$visible\"" ]; then
                        text="${options[key+1]}"
                        default_item=(--default-item "$visible")
                        found=1
                        wt_menu_item_details "$title" "$text" "$width"
                        break
                    fi
                done
                [ "$found" -eq 1 ] && continue
            fi
            if [ "$rc" -eq 0 ] && [ "$WT_MENU_GAME_COLUMNS" -eq 1 ]; then
                for ((key=0; key<${#display_tags[@]}; key++)); do
                    if [ "$result" = "${display_tags[key]}" ]; then result="${options[key*2]}"; break; fi
                done
            fi
            [ "$rc" -eq 0 ] && printf '%s' "$result"
            return "$rc"
        done
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
        result="$(dialog --stdout --clear --no-shadow             --ok-label "$(i18n ok)" --cancel-label "${WT_MENU_CANCEL_LABEL:-$(i18n cancel)}"             --title "$title" --dselect "$initial" 22 100)"
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
            --ok-label "$(i18n ok)" --cancel-label "${WT_MENU_CANCEL_LABEL:-$(i18n cancel)}" \
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
            --ok-label "$(i18n ok)" --cancel-label "${WT_MENU_CANCEL_LABEL:-$(i18n cancel)}" \
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
