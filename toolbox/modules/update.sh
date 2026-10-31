#!/bin/bash

WT_UPDATE_REPO="Thomson67/ultimate-wine-toolbox"
WT_UPDATE_BACKUP_DIR="/userdata/system/backups/ultimate-wine-toolbox/updates"

wt_release_asset_name() {
    local tag="$1"
    printf 'Ultimate-Wine-Toolbox-%s.zip' "$tag"
}

wt_version_is_newer() {
    local latest="$1" current="$2"
    python3 - "$latest" "$current" <<'PY'
import re, sys
def parse(v):
    v=v.strip().lstrip("v")
    m=re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", v)
    return tuple(map(int, m.groups())) if m else None
latest=parse(sys.argv[1]); current=parse(sys.argv[2])
raise SystemExit(0 if latest and current and latest > current else 1)
PY
}

wt_update_available_tag() {
    local current latest
    current="$(wt_version)"
    case "$current" in *-dev*|*-[Tt][Ee][Ss][Tt]*) return 1 ;; esac
    latest="$(github_latest_release_tag "$WT_UPDATE_REPO" 2>/dev/null)" || return 2
    case "$latest" in v[0-9]*.[0-9]*.[0-9]*) ;; *) return 2 ;; esac
    wt_version_is_newer "$latest" "$current" || return 1
    printf '%s' "$latest"
}

wt_update_backup_current() {
    local current="$1" backup
    mkdir -p "$WT_UPDATE_BACKUP_DIR" || return 1
    backup="$WT_UPDATE_BACKUP_DIR/${current}-$(date '+%Y%m%d-%H%M%S')"
    mkdir -p "$backup" || return 1
    cp -a "$WT_HOME/toolbox" "$backup/toolbox" || return 1
    cp -a "$WT_HOME/VERSION" "$backup/VERSION" || return 1
    [ -f "$WT_HOME/uninstall.sh" ] && cp -a "$WT_HOME/uninstall.sh" "$backup/uninstall.sh" || true
    printf '%s' "$backup"
}

wt_update_restore_backup() {
    local backup="$1"
    [ -d "$backup/toolbox" ] || return 1
    if [ -f "$WT_HOME/toolbox/helpers/virtual_keyboard.py" ]; then
        python3 "$WT_HOME/toolbox/helpers/virtual_keyboard.py" --home "$WT_HOME" stop || return 1
    fi
    rm -rf "$WT_HOME/toolbox"
    cp -a "$backup/toolbox" "$WT_HOME/toolbox" || return 1
    cp -a "$backup/VERSION" "$WT_HOME/VERSION" || return 1
    [ -f "$backup/uninstall.sh" ] && cp -a "$backup/uninstall.sh" "$WT_HOME/uninstall.sh" || true

    cp -f "$WT_HOME/toolbox/ports/Ultimate Wine Toolbox.sh" "/userdata/roms/ports/Ultimate Wine Toolbox.sh" 2>/dev/null || true
    cp -f "$WT_HOME/toolbox/ports/Ultimate Wine Toolbox.sh.keys" "/userdata/roms/ports/Ultimate Wine Toolbox.sh.keys" 2>/dev/null || true
    cp -f "$WT_HOME/toolbox/hooks/mangohud-game-event.sh" "/userdata/system/scripts/ultimate-wine-toolbox-mangohud.sh" 2>/dev/null || true
    cp -f "$WT_HOME/toolbox/hooks/dxvk-game-event.sh" "/userdata/system/scripts/ultimate-wine-toolbox-dxvk.sh" 2>/dev/null || true
    if [ -f "$WT_HOME/toolbox/hooks/virtual-keyboard-game-event.sh" ]; then
        cp -f "$WT_HOME/toolbox/hooks/virtual-keyboard-game-event.sh" "/userdata/system/scripts/ultimate-wine-toolbox-virtual-keyboard.sh" || return 1
    else
        rm -f "/userdata/system/scripts/ultimate-wine-toolbox-virtual-keyboard.sh"
    fi
    chmod +x "/userdata/roms/ports/Ultimate Wine Toolbox.sh" "/userdata/system/scripts/ultimate-wine-toolbox-"*.sh 2>/dev/null || true
}

wt_update_install_tag() {
    local tag="$1" current asset checksum base tmp root package_version backup

    current="$(wt_version)"
    asset="$(wt_release_asset_name "$tag")"
    checksum="${asset}.sha256"
    base="https://github.com/${WT_UPDATE_REPO}/releases/download/${tag}"

    for cmd in curl unzip sha256sum python3; do
        command -v "$cmd" >/dev/null 2>&1 || {
            msgbox "$(i18n update_title)" "$(i18n update_missing_tool "$cmd")"
            return 1
        }
    done

    tmp="$(mktemp -d /tmp/ultimate-wine-toolbox-update.XXXXXX)" || return 1

    curl -fL --retry 3 --connect-timeout 15 -o "$tmp/$asset" "$base/$asset" || {
        rm -rf "$tmp"; msgbox "$(i18n update_title)" "$(i18n update_download_failed "$tag")"; return 1;
    }
    curl -fL --retry 3 --connect-timeout 15 -o "$tmp/$checksum" "$base/$checksum" || {
        rm -rf "$tmp"; msgbox "$(i18n update_title)" "$(i18n update_checksum_missing "$tag")"; return 1;
    }
    (cd "$tmp" && sha256sum -c "$checksum" >/dev/null 2>&1) || {
        rm -rf "$tmp"; msgbox "$(i18n update_title)" "$(i18n update_checksum_failed)"; return 1;
    }
    unzip -q "$tmp/$asset" -d "$tmp/extracted" || {
        rm -rf "$tmp"; msgbox "$(i18n update_title)" "$(i18n update_extract_failed)"; return 1;
    }

    root="$tmp/extracted/Ultimate-Wine-Toolbox-$tag"
    [ -s "$root/VERSION" ] && [ -s "$root/package-install.sh" ] || {
        rm -rf "$tmp"; msgbox "$(i18n update_title)" "$(i18n update_package_invalid)"; return 1;
    }

    package_version="$(tr -d '\r\n[:space:]' < "$root/VERSION")"
    [ "v$package_version" = "$tag" ] || {
        rm -rf "$tmp"; msgbox "$(i18n update_title)" "$(i18n update_package_invalid)"; return 1;
    }

    while IFS= read -r script; do
        /bin/bash -n "$script" || {
            rm -rf "$tmp"; msgbox "$(i18n update_title)" "$(i18n update_package_invalid)"; return 1;
        }
    done < <(find "$root" -type f -name '*.sh' -print)

    if ! python3 - "$root/toolbox" <<'PYTHON'
from pathlib import Path
import sys
for path in Path(sys.argv[1]).rglob("*.py"):
    compile(path.read_bytes(), str(path), "exec")
PYTHON
    then
        rm -rf "$tmp"; msgbox "$(i18n update_title)" "$(i18n update_package_invalid)"; return 1;
    fi

    backup="$(wt_update_backup_current "$current")" || {
        rm -rf "$tmp"; msgbox "$(i18n update_title)" "$(i18n update_backup_failed)"; return 1;
    }

    chmod +x "$root/package-install.sh"
    wt_log "update: installing $tag; backup=$backup"
    if ! "$root/package-install.sh"; then
        wt_log "update: installation failed, restoring backup"
        wt_update_restore_backup "$backup" || true
        rm -rf "$tmp"
        msgbox "$(i18n update_title)" "$(i18n update_install_failed "$backup")"
        return 1
    fi

    rm -rf "$tmp"
    msgbox "$(i18n update_title)" "$(i18n update_success "$tag")"
    export WT_SKIP_STARTUP_UPDATE=1
    exec /bin/bash "$WT_HOME/toolbox/ultimate-wine-toolbox.sh"
}

startup_update_check() {
    local latest rc
    [ "${WT_SKIP_STARTUP_UPDATE:-0}" = "1" ] && return 0
    case "$(wt_version)" in *-dev*|*-[Tt][Ee][Ss][Tt]*) return 0 ;; esac

    latest="$(wt_update_available_tag)"; rc=$?
    case "$rc" in
        0)
            wt_log "update available: $latest"
            yesno "$(i18n update_title)" "$(i18n update_available "$(wt_version)" "$latest")" || return 0
            wt_update_install_tag "$latest"
            ;;
        1) wt_log "update: already current" ;;
        *) wt_log "update: check unavailable" ;;
    esac
}

manual_update_check() {
    local latest rc current
    current="$(wt_version)"
    case "$current" in
        *-dev*|*-[Tt][Ee][Ss][Tt]*)
            msgbox "$(i18n update_title)" "$(i18n update_dev_build "$current")"
            return
            ;;
    esac

    latest="$(wt_update_available_tag)"; rc=$?
    case "$rc" in
        0)
            yesno "$(i18n update_title)" "$(i18n update_available "$current" "$latest")" || return
            wt_update_install_tag "$latest"
            ;;
        1) msgbox "$(i18n update_title)" "$(i18n update_none "$current")" ;;
        *) msgbox "$(i18n update_title)" "$(i18n update_check_failed)" ;;
    esac
}
