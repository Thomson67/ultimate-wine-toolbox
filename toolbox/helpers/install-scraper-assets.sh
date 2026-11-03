#!/bin/bash
set -euo pipefail

SRC_DIR="${1:?Usage: install-scraper-assets.sh SOURCE_DIR SLUG ROM_NAME TITLE DESC_FR DESC_EN STATE_DIR BACKUP_DIR}"
SLUG="${2:?missing scraper slug}"
ROM_NAME="${3:?missing Ports launcher name}"
TITLE="${4:?missing display title}"
DESC_FR="${5:?missing French description}"
DESC_EN="${6:?missing English description}"
STATE_DIR="${7:?missing persistent state directory}"
BACKUP_DIR="${8:?missing backup directory}"
PORTS_DIR="${SCRAPER_PORTS_DIR:-/userdata/roms/ports}"
MANIFEST="$STATE_DIR/scraper-assets.sha256"

fail() { printf 'scraper-assets: %s\n' "$*" >&2; exit 1; }

if [ -n "${SCRAPER_LOG_FILE:-}" ]; then
    mkdir -p "$(dirname "$SCRAPER_LOG_FILE")"
    exec > >(tee -a "$SCRAPER_LOG_FILE") 2>&1
fi
printf '\nscraper-assets: installation started %s\n' "$(date -Iseconds)"

[ -d "$SRC_DIR" ] || fail "asset directory missing: $SRC_DIR"
for file in box2d.jpg fanart.jpg logo.png screenshot.jpg; do
    [ -s "$SRC_DIR/$file" ] || fail "required asset missing: $SRC_DIR/$file"
done

case "$(batocera-settings-get system.language 2>/dev/null || true)" in
    fr*|FR*) DESC="$DESC_FR"; GENRE="Utilitaire" ;;
    *) DESC="$DESC_EN"; GENRE="Utility" ;;
esac

mkdir -p "$PORTS_DIR" "$STATE_DIR"
old_manifest="$MANIFEST"
new_manifest="$STATE_DIR/.scraper-assets.sha256.$$"
: > "$new_manifest"
trap 'rm -f -- "$new_manifest"' EXIT

install_asset() {
    local source_file="$1" target_rel="$2"
    local source="$SRC_DIR/$source_file" target="$PORTS_DIR/$target_rel"
    local new_hash old_hash current_hash
    mkdir -p "$(dirname "$target")"
    new_hash="$(sha256sum "$source" | awk '{print $1}')"
    old_hash=""
    if [ -s "$old_manifest" ]; then
        old_hash="$(awk -v n="$target_rel" '$2 == n { print $1; exit }' "$old_manifest")"
    fi

    if [ -L "$target" ]; then
        printf 'scraper-assets: preserving linked custom media %s\n' "$target"
    elif [ -e "$target" ]; then
        current_hash="$(sha256sum "$target" | awk '{print $1}')"
        if [ "$current_hash" = "$new_hash" ] || { [ -n "$old_hash" ] && [ "$current_hash" = "$old_hash" ]; }; then
            cp -f -- "$source" "$target" || fail "could not update $target"
        else
            printf 'scraper-assets: preserving custom media %s\n' "$target"
        fi
    else
        cp -p -- "$source" "$target" || fail "could not install $target"
    fi
    printf '%s %s\n' "$new_hash" "$target_rel" >> "$new_manifest"
}

# Batocera's standard gamelist layout uses media subdirectories relative to
# the Ports folder: image is the screenshot, and thumbnail is the 2D box art.
install_asset screenshot.jpg "media/images/$SLUG.jpg"
install_asset box2d.jpg "media/box2d/$SLUG.jpg"
install_asset box2d.jpg "media/thumbnails/$SLUG.jpg"
install_asset fanart.jpg "media/fanarts/$SLUG.jpg"
install_asset logo.png "media/marquee/$SLUG.png"

python3 "$(dirname "$0")/scraper_metadata.py" \
    "$PORTS_DIR/gamelist.xml" "$BACKUP_DIR" "$ROM_NAME" "$TITLE" "$DESC" "$GENRE" "$SLUG"

# Keep old media and the old manifest if metadata synchronization failed.
# Remove only prior managed files whose recorded hash still matches. This
# cleans up the older reversed PNG paths without deleting custom replacements.
if [ -s "$old_manifest" ]; then
    while read -r old_hash old_rel; do
        [ -n "$old_rel" ] || continue
        if ! awk -v n="$old_rel" '$2 == n { found=1 } END { exit !found }' "$new_manifest"; then
            old_target="$PORTS_DIR/$old_rel"
            if [ -f "$old_target" ] && [ ! -L "$old_target" ] &&
               [ "$(sha256sum "$old_target" | awk '{print $1}')" = "$old_hash" ]; then
                rm -f -- "$old_target"
            fi
        fi
    done < "$old_manifest"
fi
mv -f -- "$new_manifest" "$MANIFEST" || fail "could not update asset manifest"
