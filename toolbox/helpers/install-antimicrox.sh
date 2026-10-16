#!/bin/bash
# Explicit opt-in installer; never changes Batocera system files.
set -euo pipefail
ROOT="${WT_HOME:-/userdata/system/ultimate-wine-toolbox}"
HELPERS="$(cd "$(dirname "$0")" && pwd)"
DEST="$ROOT/tools/antimicrox"
TAG=3.6.1
API="https://api.github.com/repos/AntiMicroX/antimicrox/releases/tags/$TAG"
TMP="$(mktemp -d /userdata/system/.amx-install.XXXXXX)"
trap 'rm -rf -- "$TMP"' EXIT
[ "$(uname -m)" = x86_64 ] || { echo "Only x86_64 AppImage is supported"; exit 1; }
for c in curl python3 sha256sum flock pgrep; do command -v "$c" >/dev/null || exit 1; done
curl -fLsS --retry 3 "$API" -o "$TMP/release.json"
python3 - "$TMP/release.json" "$TMP/url" <<'PY'
import json,sys
with open(sys.argv[1]) as f: release=json.load(f)
assets=release.get("assets",[])
found=[a for a in assets if a["name"].lower().endswith(".appimage") and any(v in a["name"].lower() for v in ("x86_64","amd64"))]
# Exclude diagnostic builds; the release ships regular and debug AppImages.
found=[a for a in found if "debug" not in a["name"].lower()]
selected=found
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
# Extract and check the runtime before replacing the installed version.
(cd "$TMP"; ./AntiMicroX.AppImage --appimage-extract > extract.log 2>&1) || {
  cat "$TMP/extract.log"; exit 1;
}
[ -x "$TMP/squashfs-root/AppRun" ] || { echo "AppRun missing after extraction"; exit 1; }
[ -f "$TMP/squashfs-root/usr/plugins/platforms/libqxcb.so" ] || { echo "Qt xcb plugin missing"; exit 1; }
# Fail with useful loader diagnostics rather than silently accepting a download.
if command -v ldd >/dev/null 2>&1; then
  : > "$TMP/dependencies.log"
  for elf in "$TMP/squashfs-root/AppRun" "$TMP/squashfs-root/usr/plugins/platforms/libqxcb.so"; do
    env -u LD_LIBRARY_PATH -u LD_PRELOAD ldd "$elf" >> "$TMP/dependencies.log" 2>&1 || true
  done
  if grep -Eq 'not found|version .* not found' "$TMP/dependencies.log"; then
    cat "$TMP/dependencies.log"; exit 1
  fi
fi
[ -s "$HELPERS/antimicrox-launch.sh" ] || { echo "Launcher missing: reinstall the complete test Toolbox package."; exit 1; }
sha256sum "$TMP/AntiMicroX.AppImage" | awk '{print $1}' > "$TMP/sha256"
mkdir -p "$DEST"
# Serialize installation and refuse replacement while AntiMicroX is running.
exec 8>"$DEST/install.lock"
flock -x 8
if pgrep -x antimicrox >/dev/null 2>&1 ||
   pgrep -f "^$ROOT/tools/antimicrox/squashfs-root/(AppRun|usr/bin/antimicrox)([[:space:]]|$)" >/dev/null 2>&1; then
  echo "Close AntiMicroX and any mapped game before reinstalling."; exit 1
fi
rm -rf -- "$DEST/squashfs-root.previous"
if [ -d "$DEST/squashfs-root" ]; then
  mv -- "$DEST/squashfs-root" "$DEST/squashfs-root.previous"
fi
if ! mv -- "$TMP/squashfs-root" "$DEST/squashfs-root"; then
  [ ! -d "$DEST/squashfs-root.previous" ] || mv -- "$DEST/squashfs-root.previous" "$DEST/squashfs-root"
  exit 1
fi
mv -f -- "$TMP/AntiMicroX.AppImage" "$DEST/AntiMicroX.AppImage"
mv -f -- "$TMP/sha256" "$DEST/sha256"
cp -- "$HELPERS/antimicrox-launch.sh" "$DEST/antimicrox"
chmod 755 "$DEST/antimicrox"
rm -rf -- "$DEST/squashfs-root.previous"
echo "AntiMicroX $TAG extracted and installed in $DEST"
echo "SHA256: $(cat "$DEST/sha256")"
echo "GUI and controller mapping still require testing in the Batocera desktop session."
