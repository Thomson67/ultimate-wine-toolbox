#!/bin/bash

ROOT="${WT_HOME:-/userdata/system/ultimate-wine-toolbox}"
CONFIG_DIR="$ROOT/config"
GLOBAL_FILE="$CONFIG_DIR/mangohud-global"
OVERRIDE_FILE="$CONFIG_DIR/mangohud-games.tsv"
LEGACY_LAYER_DIR="/usr/share/vulkan/implicit_layer.d"
LEGACY_LAYER_FILE="$LEGACY_LAYER_DIR/MangoHud.ultimate-wine-toolbox.json"
X86_LAYER_FILE="$LEGACY_LAYER_DIR/MangoHud.ultimate-wine-toolbox.x86.json"
MANGOHUD_RUNTIME="$ROOT/runtime/mangohud"
MANGOHUD32_LIB="$MANGOHUD_RUNTIME/lib32/mangohud/libMangoHud.so"
MANGOHUD64_LIB="$MANGOHUD_RUNTIME/lib64/mangohud/libMangoHud.so"
MANGOHUD_UMU_EXTRA_RO="$MANGOHUD_RUNTIME"
MANGOHUD_PRELOAD="libMangoHud_shim.so"
MANGOHUD_LIBPATH_PREFIX="$MANGOHUD_RUNTIME/lib64/mangohud:$MANGOHUD_RUNTIME/lib32/mangohud"
LOG_DIR="${WT_MANGOHUD_LOG_DIR:-/userdata/system/logs/ultimate-wine-toolbox}"
HOOK_LOG="$LOG_DIR/mangohud-hook.log"

hook_log() {
    mkdir -p "$LOG_DIR" 2>/dev/null || true
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$HOOK_LOG" 2>/dev/null || true
}

event="${1:-}"
system="${2:-}"
emulator="${3:-}"
core="${4:-}"
rom="${5:-}"

case "$event" in
    gameStart|gameStop) ;;
    *) exit 0 ;;
esac
[ -n "$rom" ] || exit 0

batocera_major() {
    local raw=""
    if command -v batocera-version >/dev/null 2>&1; then
        raw="$(batocera-version 2>/dev/null | head -n1)"
    elif [ -r /usr/share/batocera/batocera.version ]; then
        raw="$(head -n1 /usr/share/batocera/batocera.version 2>/dev/null)"
    elif [ -r /etc/os-release ]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        raw="${PRETTY_NAME:-${VERSION_ID:-}}"
    fi
    printf '%s\n' "$raw" | grep -oE '[0-9]+' | head -n1
}

is_legacy_mangohud_batocera() {
    case "$(batocera_major)" in
        41|42) return 0 ;;
        *) return 1 ;;
    esac
}

# Keep native behavior if restoring an older package without the resolver.
# Custom systems require explicit selection and a supported actual emulator.
backend=native
saved_autorun=""
resolver=(python3 "$ROOT/toolbox/helpers/wine_systems.py" --home "$ROOT")
[ -z "${WT_ES_USER_DIR:-}" ] || resolver+=(--es-user-dir "$WT_ES_USER_DIR")
[ -z "${WT_ES_SYSTEM_FILE:-}" ] || resolver+=(--es-system-file "$WT_ES_SYSTEM_FILE")
if [ -f "$ROOT/toolbox/helpers/wine_systems.py" ]; then
    major="$(batocera_major)"
    mapfile -t launch_context < <("${resolver[@]}" context --event "$event" \
        --system "$system" --emulator "$emulator" --core "$core" --rom "$rom" \
        --major "${major:-0}")
    [ "${#launch_context[@]}" -eq 3 ] || exit 0
    system="${launch_context[0]}"
    backend="${launch_context[1]}"
    saved_autorun="${launch_context[2]}"
else
    [ "$system" = windows ] || exit 0
fi
hook_log "event=$event system=$system emulator=$emulator core=$core backend=$backend rom=$rom"
# Stock Wine uses Windows settings/bottles; DCG passes its custom system.
settings_system=windows
[ "$backend" != dcg ] || settings_system="$system"

ensure_x86_vulkan_layer() {
    [ -r "$MANGOHUD32_LIB" ] || return 0
    mkdir -p "$LEGACY_LAYER_DIR" 2>/dev/null || return 0

    cat > "$X86_LAYER_FILE" <<EOF
{
    "file_format_version": "1.0.0",
    "layer": {
        "name": "VK_LAYER_MANGOHUD_overlay_x86",
        "type": "GLOBAL",
        "api_version": "1.3.0",
        "library_path": "$MANGOHUD32_LIB",
        "implementation_version": "1",
        "description": "Vulkan Hud Overlay 32-bit (Ultimate Wine Toolbox)",
        "functions": {
            "vkGetInstanceProcAddr": "overlay_GetInstanceProcAddr",
            "vkGetDeviceProcAddr": "overlay_GetDeviceProcAddr"
        },
        "enable_environment": {
            "MANGOHUD": "1"
        },
        "disable_environment": {
            "DISABLE_MANGOHUD": "1"
        }
    }
}
EOF
}

ensure_legacy_vulkan_layer() {
    is_legacy_mangohud_batocera || return 0
    [ -r "$MANGOHUD64_LIB" ] || return 0

    # Batocera 41/42 ship MangoHud but omit its Vulkan implicit-layer manifest.
    # Do not add a duplicate if another manifest already exposes the same layer.
    if [ -d "$LEGACY_LAYER_DIR" ] &&        grep -Rslq '"VK_LAYER_MANGOHUD_overlay_x86_64"' "$LEGACY_LAYER_DIR" 2>/dev/null; then
        return 0
    fi

    mkdir -p "$LEGACY_LAYER_DIR" 2>/dev/null || return 0
    cat > "$LEGACY_LAYER_FILE" <<EOF
{
    "file_format_version": "1.0.0",
    "layer": {
        "name": "VK_LAYER_MANGOHUD_overlay_x86_64",
        "type": "GLOBAL",
        "api_version": "1.3.0",
        "library_path": "$MANGOHUD64_LIB",
        "implementation_version": "1",
        "description": "Vulkan Hud Overlay (Ultimate Wine Toolbox compatibility)",
        "functions": {
            "vkGetInstanceProcAddr": "overlay_GetInstanceProcAddr",
            "vkGetDeviceProcAddr": "overlay_GetDeviceProcAddr"
        },
        "enable_environment": {
            "MANGOHUD": "1"
        },
        "disable_environment": {
            "DISABLE_MANGOHUD": "1"
        }
    }
}
EOF
}

global_state="0"
[ -s "$GLOBAL_FILE" ] && global_state="$(head -n1 "$GLOBAL_FILE" | tr -d '\r\n[:space:]')"
case "$global_state" in 1|on|ON|true|TRUE) global_state=1 ;; *) global_state=0 ;; esac

override=""
if [ -s "$OVERRIDE_FILE" ]; then
    override="$(awk -F '\t' -v p="$rom" '$2==p {v=$1} END{print v}' "$OVERRIDE_FILE")"
fi

if [ "$event" = "gameStop" ]; then
    # MangoHud ENV entries are runtime-only. Always remove the entries managed
    # by Ultimate when the game exits so .wine/.pc prefixes remain clean and a
    # later WSquashFS build cannot embed MangoHud runtime settings.
    desired=0
else
    case "$override" in
        on) desired=1 ;;
        off) desired=0 ;;
        *) desired="$global_state" ;;
    esac
fi

legacy_mangohud=0
detected_major="$(batocera_major)"
hook_log "batocera_major=${detected_major:-unknown} global=$global_state override=${override:-inherit} desired=$desired event=$event"

if [ "$desired" = "1" ]; then
    ensure_x86_vulkan_layer
    if [ -s "$X86_LAYER_FILE" ]; then
        hook_log "x86_vulkan_layer=ready path=$X86_LAYER_FILE"
    else
        hook_log "x86_vulkan_layer=unavailable"
    fi
fi

if is_legacy_mangohud_batocera; then
    legacy_mangohud=1
    if [ "$desired" = "1" ]; then
        ensure_legacy_vulkan_layer
        if [ -s "$LEGACY_LAYER_FILE" ]; then
            hook_log "legacy_vulkan_layer=created path=$LEGACY_LAYER_FILE"
        elif grep -Rslq '"VK_LAYER_MANGOHUD_overlay_x86_64"' "$LEGACY_LAYER_DIR" 2>/dev/null; then
            hook_log "legacy_vulkan_layer=already_present"
        else
            hook_log "legacy_vulkan_layer=missing"
        fi
    fi
fi

hud_profile=default
[ ! -s "$CONFIG_DIR/mangohud-profile" ] || hud_profile="$(head -n1 "$CONFIG_DIR/mangohud-profile")"
case "$hud_profile" in minimal|detailed) ;; *) hud_profile=default ;; esac
hook_log "display_profile=$hud_profile"

rewrite_autorun() {
    local file="$1" state="$2" legacy="$3"
    [ -f "$file" ] || return 1

    python3 - "$file" "$state" "$legacy" "$MANGOHUD_PRELOAD" "$MANGOHUD_LIBPATH_PREFIX" "$MANGOHUD_UMU_EXTRA_RO" "$hud_profile" <<'PY'
import re, sys
from pathlib import Path

path=Path(sys.argv[1])
enabled=sys.argv[2] == "1"
legacy=sys.argv[3] == "1"
managed_preload=sys.argv[4]
managed_libpath_prefix=sys.argv[5]
managed_umu_extra_ro=sys.argv[6]
profile_configs = {
    "minimal": "fps_only=1,frametime=0,frame_timing=0",
    "detailed": "fps,cpu_stats,gpu_stats,cpu_temp,gpu_temp,ram,vram,frametime,frame_timing",
}
profile_config = profile_configs.get(sys.argv[7], "")

try:
    text=path.read_text(encoding="utf-8", errors="replace")
except Exception:
    raise SystemExit(1)

lines=text.replace("\r\n","\n").replace("\r","\n").split("\n")
out=[]
found=False

def clean_payload(payload):
    for config in profile_configs.values():
        payload = re.sub(r"(^|\s)MANGOHUD_CONFIG=" + re.escape(config) + r"(?=\s|$)", " ", payload)
    payload=re.sub(r'(^|\s)MANGOHUD=[^\s]+', ' ', payload)
    payload=re.sub(r'(^|\s)MANGOHUD_DLSYM=[^\s]+', ' ', payload)

    # Remove every LD_PRELOAD form previously managed by the Toolbox.
    managed_preloads = [
        managed_preload,
        "/usr/$LIB/mangohud/libMangoHud_opengl.so",
        "/usr/lib/mangohud/libMangoHud_opengl.so:/userdata/system/ultimate-wine-toolbox/runtime/mangohud/lib32/mangohud/libMangoHud_opengl.so",
        "/usr/lib/mangohud/libMangoHud_dlsym.so:/usr/lib/mangohud/libMangoHud_opengl.so:/userdata/system/ultimate-wine-toolbox/runtime/mangohud/lib32/mangohud/libMangoHud_dlsym.so:/userdata/system/ultimate-wine-toolbox/runtime/mangohud/lib32/mangohud/libMangoHud_opengl.so",
        "/userdata/system/ultimate-wine-toolbox/runtime/mangohud/$LIB/mangohud/libMangoHud_dlsym.so:/userdata/system/ultimate-wine-toolbox/runtime/mangohud/$LIB/mangohud/libMangoHud_opengl.so",
    ]
    for value in managed_preloads:
        payload=re.sub(
            r'(^|\s)LD_PRELOAD=(?:[\'"])?' + re.escape(value) + r'(?:[\'"])?(?=\s|$)',
            ' ',
            payload
        )

    # Remove only an LD_LIBRARY_PATH token that contains Ultimate's
    # managed MangoHud prefix. Keep unrelated user-defined LD_LIBRARY_PATH
    # assignments untouched.
    payload=re.sub(
        r'(^|\s)LD_LIBRARY_PATH=[^\s]*' + re.escape(managed_libpath_prefix) + r'[^\s]*(?=\s|$)',
        ' ',
        payload
    )
    # Remove the legacy Ultimate-managed pressure-vessel form during migration.
    payload=re.sub(r'(^|\s)PRESSURE_VESSEL_FILESYSTEMS_RO=[^\s]+', ' ', payload)
    payload=re.sub(r'(^|\s)UMU_BATOCERA_EXTRA_RO=[^\s]*' + re.escape(managed_umu_extra_ro) + r'[^\s]*(?=\s|$)', ' ', payload)
    return re.sub(r'\s+', ' ', payload).strip()

for line in lines:
    if line.startswith("ENV=") and not found:
        payload=clean_payload(line[4:])
        if enabled:
            payload=(payload + " " if payload else "") + "MANGOHUD=1"
            if profile_config:
                payload += " MANGOHUD_CONFIG=" + profile_config
            # Match MangoHud's official wrapper: preload plain filenames and
            # let the dynamic linker select the matching 32/64-bit library.
            if not re.search(r'(^|\s)LD_LIBRARY_PATH=', payload):
                payload += " LD_LIBRARY_PATH=\'" + managed_libpath_prefix + "\':\"${LD_LIBRARY_PATH:-}\""
            # Keep independent ReShade/custom mounts regardless of hook order.
            payload += " UMU_BATOCERA_EXTRA_RO=\'" + managed_umu_extra_ro + "\':\"${UMU_BATOCERA_EXTRA_RO:-}\""
            if not re.search(r'(^|\s)LD_PRELOAD=', payload):
                payload += " LD_PRELOAD='" + managed_preload + "'"
        if payload:
            out.append("ENV="+payload)
        found=True
    else:
        out.append(line)

if enabled and not found:
    payload="MANGOHUD=1"
    if profile_config:
        payload += " MANGOHUD_CONFIG=" + profile_config
    payload += " LD_LIBRARY_PATH=\'" + managed_libpath_prefix + "\':\"${LD_LIBRARY_PATH:-}\""
    payload += " UMU_BATOCERA_EXTRA_RO=\'" + managed_umu_extra_ro + "\':\"${UMU_BATOCERA_EXTRA_RO:-}\""
    payload += " LD_PRELOAD='" + managed_preload + "'"
    insert_at=0
    for i,line in enumerate(out):
        if line.startswith(("DIR=","CMD=","LANG=","SAVEDIR=","SAVEFILES=")):
            insert_at=i
            break
    out.insert(insert_at, "ENV="+payload)

while out and out[-1] == "":
    out.pop()
path.write_text("\n".join(out)+"\n", encoding="utf-8")
PY
}

get_runner() {
    local romname="$1" runner
    runner="$(batocera-settings-get "$settings_system[\"$romname\"].wine-runner" "$settings_system.wine-runner" "global.wine-runner" 2>/dev/null || true)"
    if [ -z "$runner" ]; then
        runner="$(batocera-settings-get "$settings_system[\"$romname\"].core" "$settings_system.core" "global.core" 2>/dev/null || true)"
    fi
    if [ -z "$runner" ] && [ "$backend" = dcg ]; then
        runner="$(batocera-settings-get windows.wine-runner 2>/dev/null || true)"
    fi
    case "$runner" in
        lutris) runner="wine-tkg" ;;
        proton) runner="wine-proton" ;;
        "") runner="wine-tkg" ;;
    esac
    # Mirror DCG's fallback when a configured custom runner is unavailable.
    if [ "$backend" = dcg ]; then
        case "$runner" in
            wine-tkg|wine-proton) ;;
            *) [ -e "/userdata/system/wine/custom/$runner" ] || runner=wine-tkg ;;
        esac
    fi
    case "$runner" in */*|*\\*|*$'\n'*|*$'\r'*|*$'\t'*|.|..) return 1 ;; esac
    printf '%s' "$runner"
}

apply_autorun() {
    local target="$1"
    if rewrite_autorun "$target" "$desired" "$legacy_mangohud"; then
        hook_log "autorun=$target backend=$backend rewritten=1 desired=$desired"
        if [ "$system" != windows ]; then
            if [ "$event" = gameStart ] && [ "$desired" = 1 ]; then
                "${resolver[@]}" remember "$system" "$backend" "$rom" "$target" || true
            elif [ "$event" = gameStop ]; then
                "${resolver[@]}" forget "$rom" || true
            fi
        fi
    else
        hook_log "autorun=$target backend=$backend rewritten=0"
    fi
}

# Cleanup uses the precise target from gameStart, even after deselection,
# XML removal, a missing ROM or a changed runner setting.
if [ "$event" = gameStop ] && [ -n "$saved_autorun" ]; then
    apply_autorun "$saved_autorun"
    exit 0
fi

BOTTLES_ROOT="${WT_WINE_BOTTLES_ROOT:-/userdata/system/wine-bottles}"
case "${rom,,}" in
    *.pc|*.wine)
        [ -d "$rom" ] || exit 0
        apply_autorun "$rom/autorun.cmd"
        ;;
    *.wsquashfs)
        [ -f "$rom" ] || exit 0
        romname="$(basename "$rom")"

        if [ "$legacy_mangohud" = "1" ] && [ "$backend" = native ]; then
            # Batocera 41/42 use the game basename directly as the OverlayFS
            # upperdir, with no runner subdirectory and no .wine suffix.
            upper="$BOTTLES_ROOT/$settings_system/$romname"
        else
            runner="$(get_runner "$romname")" || exit 0
            upper="$BOTTLES_ROOT/$settings_system/$runner/$romname.wine"
        fi

        autorun="$upper/autorun.cmd"
        if [ ! -f "$autorun" ]; then
            tmp="$(mktemp /tmp/wt-mangohud-autorun.XXXXXX)" || exit 0
            if unsquashfs -cat "$rom" autorun.cmd > "$tmp" 2>/dev/null && [ -s "$tmp" ]; then
                mkdir -p "$upper"
                cp -f "$tmp" "$autorun"
            fi
            rm -f "$tmp"
        fi

        if [ -f "$autorun" ]; then
            apply_autorun "$autorun"
            hook_log "autorun_env=$(grep -m1 '^ENV=' "$autorun" 2>/dev/null || true)"
        else
            hook_log "autorun=$autorun legacy=$legacy_mangohud rewritten=0"
        fi
        ;;
    *.wtgz)
        romname="$(basename "$rom")"
        runner="$(get_runner "$romname")" || exit 0
        prefix="$BOTTLES_ROOT/$settings_system/$runner/$romname.wine"
        [ -f "$prefix/autorun.cmd" ] && apply_autorun "$prefix/autorun.cmd"
        ;;
esac

exit 0
