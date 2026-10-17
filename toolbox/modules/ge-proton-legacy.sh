#!/bin/bash

# GE-Proton compatibility policy for Batocera:
# Classic Batocera layout: flatten files/ into the runner root for all GE versions.
# Batocera v44 is recommended for GE-Proton 11.x and later.

if [ "${WT_LANGUAGE:-en}" = "fr" ]; then
    I18N[runner_ge_umu_notice]="Ce menu installe GE-Proton comme runner classique Batocera. Pour GE-Proton 11.x et suivants, Batocera v44 est conseillée. La compatibilité dépend du jeu et de la version de Batocera.

UMU reste disponible depuis UMU Runner Toolbox pour utiliser son runtime dédié."
    I18N[runner_ge_v44]="Batocera v44 conseillée"
    I18N[runner_ge_flattening]="Adaptation Batocera : déplacement du contenu de files/ à la racine du runner..."
    I18N[runner_ge_files_missing]="Impossible d'adapter %s pour Batocera : le dossier files/ attendu est absent."
else
    I18N[runner_ge_umu_notice]="This menu installs GE-Proton as a classic Batocera runner. Batocera v44 is recommended for GE-Proton 11.x and later. Compatibility depends on the game and Batocera version.

UMU remains available through UMU Runner Toolbox with its dedicated runtime."
    I18N[runner_ge_v44]="Batocera v44 recommended"
    I18N[runner_ge_flattening]="Batocera adaptation: moving the contents of files/ to the runner root..."
    I18N[runner_ge_files_missing]="Unable to adapt %s for Batocera: expected files/ directory is missing."
fi

runner_release_rows_ge() {
    local tmp
    tmp="$(mktemp /tmp/wt-ge.XXXXXX)" || return 1
    runner_fetch_all_releases "$GE_REPO" "$tmp" || {
        rm -f "$tmp"
        return 1
    }

    python3 - "$tmp" <<'PY'
import json, re, sys
try:
    releases=[json.loads(line) for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
except Exception:
    sys.exit(1)

for rel in releases:
    if rel.get("draft") or rel.get("prerelease"):
        continue

    tag=str(rel.get("tag_name") or "")
    m=re.match(r"^GE-Proton(\d+)-", tag)
    if not m:
        continue

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
    checksum_url=checks.get(name+".sha512sum") or checks.get(name.removesuffix(".tar.gz")+".sha512sum", "")
    print("\t".join([
        tag,
        name,
        chosen.get("browser_download_url") or "",
        str(chosen.get("size") or 0),
        checksum_url
    ]))
PY

    local rc=$?
    rm -f "$tmp"
    return $rc
}

runner_install_ge_archive() {
    local title="$1" name="$2" url="$3" size="$4" checksum_url="$5"
    local stage archive extract candidate target count checksum_file expected_hash actual free estimate

    mkdir -p "$RUNNER_STAGE" "$BATOCERA_CUSTOM_WINE"

    free="$(free_bytes_userdata)"
    estimate=$(( size * 4 + 536870912 ))
    if [ -n "$free" ] && [ "$free" -lt "$estimate" ]; then
        msgbox "$title" "$(i18n runner_space_low "$(human_bytes "$estimate")" "$(human_bytes "$free")")"
        return 1
    fi

    stage="$(mktemp -d "$RUNNER_STAGE/ge-install.XXXXXX")" || return 1
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

    if [ -n "$checksum_url" ]; then
        checksum_file="$stage/checksum.sha512"
        if curl -fsSL "$checksum_url" -o "$checksum_file"; then
            expected_hash="$(awk -v n="$name" '$2==n || $2=="*"n {print $1; exit}' "$checksum_file")"
            if [ -n "$expected_hash" ]; then
                echo "$(i18n runner_verifying)"
                actual="$(sha512sum "$archive" | awk '{print $1}')"
                if [ "$actual" != "$expected_hash" ]; then
                    rm -rf "$stage"
                    msgbox "$title" "$(i18n runner_checksum_failed "$name")"
                    return 1
                fi
            fi
        fi
    fi

    echo "$(i18n runner_extracting "$name")"
    if ! tar -xzf "$archive" -C "$extract"; then
        rm -rf "$stage"
        msgbox "$title" "$(i18n runner_archive_invalid "$name")"
        return 1
    fi

    count="$(find "$extract" -mindepth 1 -maxdepth 1 -type d | wc -l)"
    if [ "$count" -ne 1 ]; then
        rm -rf "$stage"
        msgbox "$title" "$(i18n runner_archive_invalid "$name")"
        return 1
    fi

    candidate="$(find "$extract" -mindepth 1 -maxdepth 1 -type d | head -n1)"

    if [ ! -d "$candidate/files" ]; then
        rm -rf "$stage"
        msgbox "$title" "$(i18n runner_ge_files_missing "$name")"
        return 1
    fi

    echo "$(i18n runner_ge_flattening)"
    if ! cp -a "$candidate/files/." "$candidate/"; then
        rm -rf "$stage"
        msgbox "$title" "$(i18n runner_install_failed "$(basename "$candidate")")"
        return 1
    fi
    rm -rf "$candidate/files"

    target="$BATOCERA_CUSTOM_WINE/$(runner_normalized_name "$(basename "$candidate")")"
    if [ -e "$target" ]; then
        rm -rf "$stage"
        msgbox "$title" "$(i18n runner_already_installed "$(basename "$target")")"
        return 1
    fi

    if ! mv "$candidate" "$target"; then
        rm -rf "$stage"
        msgbox "$title" "$(i18n runner_install_failed "$(basename "$target")")"
        return 1
    fi

    rm -rf "$stage"
    msgbox "$title" "$(i18n runner_installed_ok "$(basename "$target")")"
}

runner_install_ge() {
    local title row tag name url size checksum_url
    title="$(i18n runner_ge_proton)"

    msgbox "$title" "$(i18n runner_ge_umu_notice)"

    row="$(runner_choose_release ge-proton "$title" "$(i18n runner_ge_v44)")" || return
    IFS=$'\t' read -r tag name url size checksum_url <<< "$row"

    yesno "$title" "$(i18n runner_install_confirm "$tag" "$name" "$(human_bytes "$size")" "$BATOCERA_CUSTOM_WINE")" || return

    runner_install_ge_archive "$title" "$name" "$url" "$size" "$checksum_url"
}
