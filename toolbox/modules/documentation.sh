#!/bin/bash

documentation_show() {
    local topic="$1" language="${WT_LANGUAGE:-fr}" columns lines width height document source_file
    case "$topic" in creation|templates|update|mangohud|dxvk|reshade) ;; *) return 1 ;; esac
    case "$language" in fr|en) ;; *) language=en ;; esac
    source_file="$WT_ROOT/docs/$language/$topic.txt"
    [ -r "$source_file" ] || {
        msgbox "$(i18n menu_documentation)" "$(i18n doc_missing)"
        return 1
    }
    columns="$(tput cols 2>/dev/null || printf '104')"
    lines="$(tput lines 2>/dev/null || printf '28')"
    case "$columns" in ''|*[!0-9]*) columns=104 ;; esac
    case "$lines" in ''|*[!0-9]*) lines=28 ;; esac
    width=$((columns-4)); height=$((lines-4))
    [ "$width" -le 100 ] || width=100
    [ "$height" -le 24 ] || height=24
    [ "$width" -ge 20 ] || width=20
    [ "$height" -ge 8 ] || height=8
    document="$(mktemp /tmp/uwt-documentation.XXXXXX)" || return 1
    python3 - "$source_file" "$((width-6))" "${WSQ_TEMPLATES_DIR:-$WT_HOME/templates}" > "$document" <<'PY'
from pathlib import Path
import sys
import textwrap
text = Path(sys.argv[1]).read_text().replace('__TEMPLATES_DIR__', sys.argv[3])
for line in text.splitlines():
    print(textwrap.fill(line, width=int(sys.argv[2]), break_long_words=False,
                        break_on_hyphens=False) if line else '')
PY
    if [ "$?" -ne 0 ]; then
        rm -f -- "$document"
        return 1
    fi
    if have_dialog; then
        dialog --clear --no-shadow --exit-label "$(i18n back)" \
            --title "$(i18n "doc_$topic")" --textbox "$document" "$height" "$width"
    else
        cat -- "$document"
    fi
    rm -f -- "$document"
}

documentation_menu() {
    local choice
    while true; do
        choice="$(menu_select "$(i18n menu_documentation)" "$(i18n doc_intro)" \
            1 "$(i18n doc_creation)" 2 "$(i18n doc_templates)" \
            3 "$(i18n doc_update)" 4 "$(i18n doc_mangohud)" \
            5 "$(i18n doc_dxvk)" 6 "$(i18n doc_reshade)" 0 "$(i18n back)")" || return
        case "$choice" in
            1) documentation_show creation ;;
            2) documentation_show templates ;;
            3) documentation_show update ;;
            4) documentation_show mangohud ;;
            5) documentation_show dxvk ;;
            6) documentation_show reshade ;;
            0|'') return ;;
        esac
    done
}
