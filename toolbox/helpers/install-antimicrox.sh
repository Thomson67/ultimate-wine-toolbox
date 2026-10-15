#!/bin/bash
# Explicit opt-in installer; never changes Batocera system files.
set -euo pipefail
ROOT=/userdata/system/ultimate-wine-toolbox
DEST="$ROOT/tools/antimicrox"
TAG=3.6.1
API="https://api.github.com/repos/AntiMicroX/antimicrox/releases/tags/$TAG"
TMP="$(mktemp -d /userdata/system/.amx-install.XXXXXX)"
trap 'rm -rf -- "$TMP"' EXIT
[ "$(uname -m)" = x86_64 ] || { echo "Only x86_64 AppImage is supported"; exit 1; }
for c in curl python3 sha256sum; do command -v "$c" >/dev/null || exit 1; done
curl -fLsS --retry 3 "$API" -o "$TMP/release.json"
python3 - "$TMP/release.json" "$TMP/url" <<'PY'
import json,sys
with open(sys.argv[1]) as f: release=json.load(f)
assets=release.get("assets",[])
found=[a for a in assets if a["name"].lower().endswith(".appimage") and any(v in a["name"].lower() for v in ("x86_64","amd64"))]
# Exclude diagnostic builds; the release ships regular and debug AppImages.
found=[a for a in found if "debug" not in a["name"].lower()]
# Official releases can ship both Qt5 and Qt6 builds. Prefer Qt6 on
# Batocera 43 while rejecting genuinely ambiguous asset selections.
qt6=[a for a in found if "qt6" in a["name"].lower().replace("-", "").replace("_", "")]
qt5=[a for a in found if "qt5" in a["name"].lower().replace("-", "").replace("_", "")]
selected=qt6 if len(qt6)==1 else (qt5 if not qt6 and len(qt5)==1 else found if len(found)==1 else [])
if len(selected)!=1:
    raise SystemExit("Ambiguous x86_64 AppImage assets: "+", ".join(a["name"] for a in found))
asset=selected[0]
print("Selected official AppImage:", asset["name"])
url=asset["browser_download_url"]
if not url.startswith("https://github.com/AntiMicroX/antimicrox/releases/download/"): raise SystemExit("Unexpected download host")
open(sys.argv[2],"w").write(url)
PY
curl -fL --retry 3 "$(cat "$TMP/url")" -o "$TMP/AntiMicroX.AppImage"
[ "$(head -c 4 "$TMP/AntiMicroX.AppImage" | od -An -tx1 | tr -d ' \n')" = 7f454c46 ] || { echo "Invalid AppImage ELF header"; exit 1; }
chmod 755 "$TMP/AntiMicroX.AppImage"
mkdir -p "$DEST"
# Atomic replacement. Keep checksum for later diagnostics.
sha256sum "$TMP/AntiMicroX.AppImage" | awk '{print $1}' > "$TMP/sha256"
mv -f -- "$TMP/AntiMicroX.AppImage" "$DEST/AntiMicroX.AppImage"
mv -f -- "$TMP/sha256" "$DEST/sha256"
cat > "$DEST/antimicrox" <<'SH'
#!/bin/bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$DIR/AntiMicroX.AppImage"
# AppImage runtime can be unavailable on stock Batocera (FUSE).
# FUSE-less extraction in a persistent, user-writable directory.
if [ ! -x "$DIR/squashfs-root/AppRun" ]; then
  (cd "$DIR"; "$APP" --appimage-extract >/dev/null)
fi
exec "$DIR/squashfs-root/AppRun" "$@"
SH
chmod 755 "$DEST/antimicrox"
echo "AntiMicroX $TAG installed in $DEST"
echo "SHA256: $(cat "$DEST/sha256")"
