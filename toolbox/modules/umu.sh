#!/bin/bash

UMU_TOOLBOX_REPO="Thomson67/umu-runner-toolbox"
UMU_TOOLBOX_ROOT="/userdata/system/umu/toolbox"
UMU_TOOLBOX_MAIN="$UMU_TOOLBOX_ROOT/umu-toolbox.sh"
UMU_TOOLBOX_VERSION_FILE="$UMU_TOOLBOX_ROOT/VERSION"

umu_toolbox_installed() { [ -x "$UMU_TOOLBOX_MAIN" ]; }

umu_toolbox_version() {
    [ -s "$UMU_TOOLBOX_VERSION_FILE" ] \
        && tr -d '\r\n[:space:]' < "$UMU_TOOLBOX_VERSION_FILE" \
        || printf '%s' "$(i18n unknown)"
}

umu_toolbox_status() {
    if umu_toolbox_installed; then
        printf '%s - v%s' "$(i18n installed)" "$(umu_toolbox_version)"
    else
        printf '%s' "$(i18n not_installed)"
    fi
}

install_umu_toolbox() {
    clear
    echo "$(i18n umu_installing)"
    echo
    curl -fsSL "https://raw.githubusercontent.com/$UMU_TOOLBOX_REPO/main/install.sh" | bash
}

ensure_umu_toolbox() {
    umu_toolbox_installed && return 0
    install_umu_toolbox || {
        msgbox "$(i18n menu_umu)" "$(i18n umu_install_failed)"
        return 1
    }
    umu_toolbox_installed
}

launch_umu_toolbox() {
    if ! umu_toolbox_installed; then
        msgbox "$(i18n menu_umu)" "$(i18n umu_missing)"
        return
    fi
    # The Ports launcher creates UMU's terminal with its own saved font and
    # window preferences. Running main here would reuse Ultimate's terminal.
    local launcher="$UMU_TOOLBOX_ROOT/ports/UMU Runner Toolbox.sh"
    if [ -s "$launcher" ]; then
        bash "$launcher"
    else
        # Compatibility with older UMU installations without a bundled launcher.
        "$UMU_TOOLBOX_MAIN"
    fi
}

install_umu_runner() {
    local runner="$1"
    ensure_umu_toolbox || return 1
    echo "$(i18n umu_runner_installing "$runner")"
    if [ "${2:-}" != batch ] && [[ "$runner" != dwproton-*-UMU ]]; then
        "$UMU_TOOLBOX_MAIN" --install-runner "$runner"
        return $?
    fi
    # Use a temporary CLI-only copy to support installed UMU Toolbox versions
    # whose msg() helper still opens a dialog at the end of each install.
    local batch_script rc
    batch_script="$(mktemp "$UMU_TOOLBOX_ROOT/.starter-batch.XXXXXX")" || return 1
    if ! python3 - "$UMU_TOOLBOX_MAIN" "$batch_script" "$runner" <<'PY'
from pathlib import Path
import re
import sys
source = Path(sys.argv[1]).read_text()
replacement = """msg() {
    printf '\\n==== %s ====\\n' "$1"
    printf '%b\\n' "$2"
    return 0
"""
patched, count = re.subn(r'^msg\(\)\s*\{\s*\n', lambda _: replacement, source, count=1, flags=re.M)
if count != 1:
    raise SystemExit("UMU batch mode unavailable: msg() helper not recognized")
if sys.argv[3].startswith("dwproton-"):
    # Older UMU Toolbox releases only expose DW through the interactive menu.
    # Adapt a temporary copy; retain its installer, checksums and runtime setup.
    start = patched.find("install_dw() {")
    end = patched.find("\ninstall_runner_menu()", start)
    if start < 0 or end < 0:
        raise SystemExit("DW installer unavailable in installed UMU Toolbox")
    installer = patched[start:end]
    installer = installer.replace("install_dw() {", 'install_dw() {\n    local requested="${1:-}"', 1)
    marker = '    if command -v dialog >/dev/null 2>&1; then\n        name="$(dialog'
    if marker not in installer:
        raise SystemExit("DW selector not recognized")
    installer = installer.replace(marker, '    if [ -n "$requested" ]; then\n        name="${requested%-UMU}"\n    elif command -v dialog >/dev/null 2>&1; then\n        name="$(dialog', 1)
    confirmation = '    if ! yesno "$(i18n install_named "$name-UMU")"'
    if confirmation not in installer:
        raise SystemExit("DW confirmation not recognized")
    installer = installer.replace(confirmation, '    if [ -z "$requested" ] && ! yesno "$(i18n install_named "$name-UMU")"', 1)
    patched = patched[:start] + installer + patched[end:]
    cli = '        proton-EM-*) install_em "$base" 1 ;;'
    if cli not in patched:
        raise SystemExit("UMU CLI not recognized")
    patched = patched.replace(cli, cli + '\n        dwproton-*)\n            install_dw "$base"\n            verify_runner_manifest "$target" || return 1\n            ;;', 1)
Path(sys.argv[2]).write_text(patched)
PY
    then
        rm -f -- "$batch_script"
        return 1
    fi
    bash "$batch_script" --install-runner "$runner"
    rc=$?
    rm -f -- "$batch_script"
    return "$rc"
}

umu_menu() {
    while true; do
        local choice
        choice="$(menu_select "$(i18n menu_umu)" \
            "$(i18n umu_intro)\n\n$(i18n status): $(umu_toolbox_status)" \
            "1" "$(i18n umu_launch)" \
            "2" "$(i18n umu_install_update)" \
            "0" "$(i18n back)")" || return
        case "$choice" in
            1) launch_umu_toolbox ;;
            2) install_umu_toolbox ;;
            0|"") return ;;
        esac
    done
}
