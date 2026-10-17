#!/bin/bash

RUNNER_STAGE="$WT_HOME/staging/runner-manager"
RUNNER_CACHE_DIR="$WT_HOME/cache/releases"
RUNNER_CACHE_TTL=21600
KRON4EK_REPO="Kron4ek/Wine-Builds"
GE_REPO="GloriousEggroll/proton-ge-custom"

runner_normalized_name() {
    python3 "$WT_ROOT/helpers/runner_names.py" name "$1"
}

runner_offer_normalization() {
    local candidates report rc
    candidates="$(python3 "$WT_ROOT/helpers/runner_names.py" list "$BATOCERA_CUSTOM_WINE")" || return 1
    if [ -z "$candidates" ]; then
        msgbox "$(i18n runner_normalize_title)" "$(i18n runner_normalize_none)"
        return
    fi
    yesno_default_no "$(i18n runner_normalize_title)" "$(i18n runner_normalize_confirm "$candidates")" || return
    report="$(python3 "$WT_ROOT/helpers/runner_names.py" migrate "$BATOCERA_CUSTOM_WINE" \
        /userdata/system/batocera.conf /userdata/system/wine-bottles/windows \
        "$WT_HOME/state/wsquashfs-builder.json" "$WT_HOME/backups/runner-names" 2>&1)"
    rc=$?
    [ -z "$report" ] || wt_log "$report"
    if [ "$rc" -eq 0 ]; then
        msgbox "$(i18n runner_normalize_title)" "$(i18n runner_normalize_done "$report")"
    else
        msgbox "$(i18n runner_normalize_title)" "$(i18n runner_normalize_failed "$report")"
    fi
    return "$rc"
}

runner_offer_normalization_at_startup() {
    local marker="$WT_HOME/config/runner-names-offered-v1" candidates
    [ ! -e "$marker" ] || return 0
    [ "${WT_AUTO_RESUME_WSQ:-0}" != 1 ] || return 0
    candidates="$(python3 "$WT_ROOT/helpers/runner_names.py" list "$BATOCERA_CUSTOM_WINE")" || return 0
    [ -n "$candidates" ] || return 0
    runner_offer_normalization || true
    mkdir -p "$WT_HOME/config" && touch "$marker"
}

runner_api_get() {
    local url="$1"
    curl -fsSL --retry 2 --connect-timeout 10 --max-time 30         -H "Accept: application/vnd.github+json"         -H "User-Agent: Ultimate-Wine-Toolbox"         "$url"
}

runner_cache_path() {
    local repo="$1"
    printf '%s/%s.jsonl' "$RUNNER_CACHE_DIR" "$(printf '%s' "$repo" | tr '/:' '__')"
}

runner_cache_fresh() {
    local file="$1" now mtime age
    [ -s "$file" ] || return 1
    now="$(date +%s)"
    mtime="$(stat -c '%Y' "$file" 2>/dev/null || printf '0')"
    age=$((now-mtime))
    [ "$age" -ge 0 ] && [ "$age" -lt "$RUNNER_CACHE_TTL" ]
}

runner_fetch_all_releases() {
    local repo="$1" out="$2" cache tmp page=1 pagefile count
    mkdir -p "$RUNNER_CACHE_DIR"
    cache="$(runner_cache_path "$repo")"

    if runner_cache_fresh "$cache"; then
        cp -f "$cache" "$out"
        return 0
    fi

    tmp="$(mktemp "$RUNNER_CACHE_DIR/.releases.XXXXXX")" || return 1
    : > "$tmp"

    while true; do
        pagefile="$(mktemp /tmp/wt-releases-page.XXXXXX)" || { rm -f "$tmp"; return 1; }
        if ! runner_api_get "https://api.github.com/repos/$repo/releases?per_page=100&page=$page" > "$pagefile"; then
            rm -f "$pagefile" "$tmp"
            [ -s "$cache" ] && { cp -f "$cache" "$out"; return 0; }
            return 1
        fi

        count="$(python3 - "$pagefile" <<'PY'
import json, sys
try:
    data=json.load(open(sys.argv[1], encoding="utf-8"))
    print(len(data) if isinstance(data, list) else 0)
except Exception:
    print(0)
PY
)"
        if [ "$count" -le 0 ]; then
            rm -f "$pagefile"
            break
        fi

        python3 - "$pagefile" >> "$tmp" <<'PY'
import json, sys
for item in json.load(open(sys.argv[1], encoding="utf-8")):
    print(json.dumps(item, separators=(",", ":")))
PY
        rm -f "$pagefile"

        [ "$count" -lt 100 ] && break
        page=$((page+1))
    done

    if [ ! -s "$tmp" ]; then
        rm -f "$tmp"
        [ -s "$cache" ] && { cp -f "$cache" "$out"; return 0; }
        return 1
    fi

    mv -f "$tmp" "$cache"
    cp -f "$cache" "$out"
}

runner_installed() {
    [ -d "$BATOCERA_CUSTOM_WINE/$1" ]
}

runner_release_rows_kron4ek() {
    local family="$1" tmp
    tmp="$(mktemp /tmp/wt-kron4ek.XXXXXX)" || return 1

    runner_fetch_all_releases "$KRON4EK_REPO" "$tmp" || {
        rm -f "$tmp"
        return 1
    }

    python3 - "$family" "$tmp" <<'PY'
import json, re, sys

family=sys.argv[1]
try:
    releases=[json.loads(line) for line in open(sys.argv[2], encoding="utf-8") if line.strip()]
except Exception:
    sys.exit(1)

for rel in releases:
    if rel.get("draft") or rel.get("prerelease"):
        continue

    tag=str(rel.get("tag_name") or "")
    body=rel.get("body") or ""
    assets=rel.get("assets") or []

    if family == "vanilla":
        preferred=[
            f"wine-{tag}-amd64-wow64.tar.xz",
            f"wine-{tag}-amd64.tar.xz",
        ]
    else:
        preferred=[
            f"wine-{tag}-staging-tkg-amd64-wow64.tar.xz",
            f"wine-{tag}-staging-tkg-amd64.tar.xz",
        ]

    chosen=None
    for wanted in preferred:
        chosen=next((a for a in assets if (a.get("name") or "") == wanted), None)
        if chosen:
            break

    if not chosen:
        continue

    name=chosen.get("name") or ""
    checksum=""
    m=re.search(r"(?im)^([0-9a-f]{64})\s+\*?"+re.escape(name)+r"\s*$", body)
    if m:
        checksum=m.group(1).lower()

    print("\t".join([
        tag,
        name,
        chosen.get("browser_download_url") or "",
        str(chosen.get("size") or 0),
        checksum
    ]))
PY

    local rc=$?
    rm -f "$tmp"
    return $rc
}

runner_release_rows_ge() {
    local tmp
    tmp="$(mktemp /tmp/wt-ge.XXXXXX)" || return 1

    runner_fetch_all_releases "$GE_REPO" "$tmp" || {
        rm -f "$tmp"
        return 1
    }

    python3 - "$tmp" <<'PY'
import json, sys
try:
    releases=[json.loads(line) for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
except Exception:
    sys.exit(1)

for rel in releases:
    if rel.get("draft") or rel.get("prerelease"):
        continue
    tag=str(rel.get("tag_name") or "")
    assets=rel.get("assets") or []
    tars=[]
    checks={}
    for a in assets:
        n=a.get("name") or ""
        u=a.get("browser_download_url") or ""
        # Legacy x86_64 builds have no architecture suffix. Never fall back
        # to another architecture when a release has only ARM archives.
        if n in (tag+".tar.gz", tag+"-x86_64.tar.gz", tag+"-amd64.tar.gz", tag+"-x64.tar.gz"):
            tars.append(a)
        elif n.endswith(".sha512sum"):
            checks[n]=u
    if not tars:
        continue
    chosen=next((a for a in tars if "x86_64" in (a.get("name") or "")), tars[0])
    name=chosen.get("name") or ""
    print("\t".join([
        tag,
        name,
        chosen.get("browser_download_url") or "",
        str(chosen.get("size") or 0),
        checks.get(name+".sha512sum") or checks.get(name.removesuffix(".tar.gz")+".sha512sum", "")
    ]))
PY

    local rc=$?
    rm -f "$tmp"
    return $rc
}

runner_choose_release() {
    local source="$1" title="$2" recommendation="${3:-}"
    local rows="" choice
    local -a items=()

    case "$source" in
        kron4ek-vanilla) rows="$(runner_release_rows_kron4ek vanilla)" || true ;;
        kron4ek-tkg) rows="$(runner_release_rows_kron4ek tkg)" || true ;;
        ge-proton) rows="$(runner_release_rows_ge)" || true ;;
        *) return 1 ;;
    esac

    if [ -z "$rows" ]; then
        msgbox "$title" "$(i18n runner_fetch_failed)"
        return 1
    fi

    # Format the entire menu in one process: large release lists must not
    # spawn a Python interpreter for every name and every size.
    mapfile -d '' -t items < <(
        python3 - "$WT_ROOT/helpers" "$BATOCERA_CUSTOM_WINE" "$(i18n installed)" "$recommendation" 3<<< "$rows" <<'PY'
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from runner_names import canonical

root = Path(sys.argv[2])
installed_label = sys.argv[3]
for index, line in enumerate(os.fdopen(3), 1):
    fields = line.rstrip("\n").split("\t")
    if len(fields) < 4 or not fields[0]:
        continue
    legacy = fields[1]
    for suffix in (".tar.xz", ".tar.gz"):
        if legacy.endswith(suffix):
            legacy = legacy[:-len(suffix)]
    name = canonical(legacy)
    size = float(fields[3])
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            readable = f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
            break
        size /= 1024
    state = f" | {installed_label}" if (root / name).is_dir() or (root / legacy).is_dir() else ""
    match = re.match(r"^GE-Proton-?(\d+)-", name)
    note = f" | {sys.argv[4]}" if sys.argv[4] and match and int(match[1]) >= 11 else ""
    sys.stdout.write(f"{index}\0{name} | {readable}{state}{note}\0")
PY
    )
    if [ "${#items[@]}" -eq 0 ]; then
        msgbox "$title" "$(i18n runner_fetch_failed)"
        return 1
    fi

    choice="$(menu_select "$title" "$(i18n runner_choose_version)" "${items[@]}" "0" "$(i18n back)")" || return 1
    [ "$choice" != "0" ] && [ -n "$choice" ] || return 1
    sed -n "${choice}p" <<< "$rows"
}

runner_install_archive() {
    local title="$1" name="$2" url="$3" size="$4" verify_kind="$5" verify_value="$6"
    local stage archive extract candidate target count expected_hash checksum_file actual free estimate

    mkdir -p "$RUNNER_STAGE" "$BATOCERA_CUSTOM_WINE"
    free="$(free_bytes_userdata)"
    estimate=$(( size * 4 + 536870912 ))

    if [ -n "$free" ] && [ "$free" -lt "$estimate" ]; then
        msgbox "$title" "$(i18n runner_space_low "$(human_bytes "$estimate")" "$(human_bytes "$free")")"
        return 1
    fi

    stage="$(mktemp -d "$RUNNER_STAGE/install.XXXXXX")" || return 1
    archive="$stage/$name"
    extract="$stage/extracted"
    mkdir -p "$extract"

    echo
    echo "$(i18n runner_downloading "$name")"
    if ! download_file "$url" "$archive"; then
        rm -rf "$stage"
        msgbox "$title" "$(i18n runner_download_failed "$name")"
        return 1
    fi

    case "$verify_kind" in
        sha256)
            if [ -n "$verify_value" ]; then
                echo "$(i18n runner_verifying)"
                if ! verify_sha256 "$archive" "$verify_value"; then
                    rm -rf "$stage"
                    msgbox "$title" "$(i18n runner_checksum_failed "$name")"
                    return 1
                fi
            fi
            ;;
        sha512-url)
            if [ -n "$verify_value" ]; then
                checksum_file="$stage/checksum.sha512"
                if curl -fsSL "$verify_value" -o "$checksum_file"; then
                    expected_hash="$(awk -v n="$name" '$2==n || $2=="*"n {print $1; exit}' "$checksum_file")"
                    if [ -n "$expected_hash" ]; then
                        actual="$(sha512sum "$archive" | awk '{print $1}')"
                        if [ "$actual" != "$expected_hash" ]; then
                            rm -rf "$stage"
                            msgbox "$title" "$(i18n runner_checksum_failed "$name")"
                            return 1
                        fi
                    fi
                fi
            fi
            ;;
    esac

    echo "$(i18n runner_extracting "$name")"
    case "$name" in
        *.tar.xz) tar -xJf "$archive" -C "$extract" ;;
        *.tar.gz) tar -xzf "$archive" -C "$extract" ;;
        *)
            rm -rf "$stage"
            msgbox "$title" "$(i18n runner_archive_invalid "$name")"
            return 1
            ;;
    esac || {
        rm -rf "$stage"
        msgbox "$title" "$(i18n runner_archive_invalid "$name")"
        return 1
    }

    count="$(find "$extract" -mindepth 1 -maxdepth 1 -type d | wc -l)"
    if [ "$count" -ne 1 ]; then
        rm -rf "$stage"
        msgbox "$title" "$(i18n runner_archive_invalid "$name")"
        return 1
    fi

    candidate="$(find "$extract" -mindepth 1 -maxdepth 1 -type d | head -n1)"
    target="$BATOCERA_CUSTOM_WINE/$(runner_normalized_name "$(basename "$candidate")")"

    if [ -e "$target" ]; then
        rm -rf "$stage"
        msgbox "$title" "$(i18n runner_already_installed "$(basename "$target")")"
        return 1
    fi

    mv "$candidate" "$target" || {
        rm -rf "$stage"
        msgbox "$title" "$(i18n runner_install_failed "$(basename "$target")")"
        return 1
    }

    rm -rf "$stage"
    msgbox "$title" "$(i18n runner_installed_ok "$(basename "$target")")"
}

runner_install_kron4ek() {
    local family="$1" title row tag name url size checksum

    if [ "$family" = "vanilla" ]; then
        title="$(i18n runner_kron4ek_vanilla)"
        row="$(runner_choose_release kron4ek-vanilla "$title")" || return
    else
        title="$(i18n runner_kron4ek_tkg)"
        row="$(runner_choose_release kron4ek-tkg "$title")" || return
    fi

    IFS=$'\t' read -r tag name url size checksum <<< "$row"
    yesno "$title" "$(i18n runner_install_confirm "$tag" "$name" "$(human_bytes "$size")" "$BATOCERA_CUSTOM_WINE")" || return
    runner_install_archive "$title" "$name" "$url" "$size" "sha256" "$checksum"
}

runner_install_ge() {
    local title row tag name url size checksum_url
    title="$(i18n runner_ge_proton)"
    row="$(runner_choose_release ge-proton "$title")" || return
    IFS=$'\t' read -r tag name url size checksum_url <<< "$row"
    yesno "$title" "$(i18n runner_install_confirm "$tag" "$name" "$(human_bytes "$size")" "$BATOCERA_CUSTOM_WINE")" || return
    runner_install_archive "$title" "$name" "$url" "$size" "sha512-url" "$checksum_url"
}

runner_family_label() {
    local name="$1"
    case "$name" in
        *-UMU) printf '%s' "UMU" ;;
        GE-Proton*) printf '%s' "GE-Proton" ;;
        TKG-*|wine-*-staging-tkg-amd64-wow64|wine-*-staging-tkg-amd64|wine-tkg-*) printf '%s' "Kron4ek TKG" ;;
        Vanilla-Proton-*|wine-proton-*-amd64-wow64|wine-proton-*-amd64) printf '%s' "Kron4ek Proton" ;;
        Vanilla-*|wine-*-amd64-wow64|wine-*-amd64) printf '%s' "Kron4ek Vanilla" ;;
        *) printf '%s' "$(i18n runner_other_family)" ;;
    esac
}

runner_uninstall_menu() {
    local -a items=()
    local name path family selected="" pretty=""
    local count=0 failures=0

    mkdir -p "$BATOCERA_CUSTOM_WINE"

    while IFS= read -r path; do
        [ -n "$path" ] || continue
        name="$(basename "$path")"
        case "$name" in "."|"..") continue ;; esac
        family="$(runner_family_label "$name")"
        items+=("$name" "$family | $name" "off")
        count=$((count+1))
    done < <(find "$BATOCERA_CUSTOM_WINE" -mindepth 1 -maxdepth 1 \( -type d -o -type l \) -print | sort)

    if [ "$count" -eq 0 ]; then
        msgbox "$(i18n runner_uninstall)" "$(i18n runner_none_installed)"
        return
    fi

    selected="$(checklist_select "$(i18n runner_uninstall)" "$(i18n runner_uninstall_prompt)" "${items[@]}")" || return

    if [ -z "$selected" ]; then
        msgbox "$(i18n runner_uninstall)" "$(i18n runner_select_none)"
        return
    fi

    while IFS= read -r name; do
        [ -n "$name" ] || continue
        pretty+="- $name"$'\n'
    done <<< "$selected"

    yesno "$(i18n runner_uninstall)" "$(i18n runner_uninstall_confirm "$pretty")" || return

    while IFS= read -r name; do
        [ -n "$name" ] || continue
        case "$name" in */*|.|..) failures=$((failures+1)); continue ;; esac
        path="$BATOCERA_CUSTOM_WINE/$name"

        case "$path" in
            "$BATOCERA_CUSTOM_WINE"/*)
                if [ -e "$path" ] || [ -L "$path" ]; then
                    rm -rf -- "$path" || failures=$((failures+1))
                fi
                ;;
            *) failures=$((failures+1)) ;;
        esac
    done <<< "$selected"

    if [ "$failures" -eq 0 ]; then
        msgbox "$(i18n runner_uninstall)" "$(i18n runner_uninstall_done)"
    else
        msgbox "$(i18n runner_uninstall)" "$(i18n runner_uninstall_partial)"
    fi
}

runner_manager_menu() {
    while true; do
        local choice
        choice="$(menu_select "$(i18n runner_manager_title)" "$(i18n runner_manager_intro)"             "1" "$(i18n runner_kron4ek_vanilla)"             "2" "$(i18n runner_kron4ek_tkg)"             "3" "$(i18n runner_ge_proton)"             "4" "$(i18n runner_uninstall)"             "0" "$(i18n back)")" || return

        case "$choice" in
            1) runner_install_kron4ek vanilla ;;
            2) runner_install_kron4ek tkg ;;
            3) runner_install_ge ;;
            4) runner_uninstall_menu ;;
            0|"") return ;;
        esac
    done
}
