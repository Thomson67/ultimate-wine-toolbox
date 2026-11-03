#!/bin/bash
# ReShadeLinux v1.4.1 (GPL-2.0-or-later), unmodified and checksum-pinned.
set -euo pipefail
ROOT="${WT_HOME:-/userdata/system/ultimate-wine-toolbox}"
BACKEND="$ROOT/reshade/backend"
COMMIT=1a58739f7868d385b2b99870efbf7ba48d916859
HASH=4c47eadb3e95e0f0379e23a7b5c41fd26d16fba2d6f1b9dda833915f18d5def6
mkdir -p "$ROOT/reshade"
exec 9> "$ROOT/reshade/backend.lock"
flock 9
if [ -f "$BACKEND/commit" ] && [ "$(cat "$BACKEND/commit")" = "$COMMIT" ] && [ -s "$BACKEND/reshadelinux.sh" ]; then
    exit 0
fi
STAGING="$(mktemp -d "$ROOT/reshade/.backend.XXXXXX")"
trap 'rm -rf -- "$STAGING"' EXIT
curl -fsSL --retry 3 --connect-timeout 15 --max-time 180 \
    "https://github.com/asafelobotomy/reshadelinux/archive/$COMMIT.tar.gz" -o "$STAGING/source.tar.gz"
printf '%s  %s\n' "$HASH" "$STAGING/source.tar.gz" | sha256sum -c -
mkdir "$STAGING/source"
# Pinned GitHub archive; never run the upstream installer during toolbox setup.
tar -xzf "$STAGING/source.tar.gz" --strip-components=1 -C "$STAGING/source"
test -s "$STAGING/source/reshadelinux.sh"
test -s "$STAGING/source/LICENSE"
printf '%s\n' "$COMMIT" > "$STAGING/source/commit"
rm -rf -- "$BACKEND"
mv -- "$STAGING/source" "$BACKEND"
