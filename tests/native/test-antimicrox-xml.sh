#!/bin/bash
# Requires Ubuntu 24.04 qt6-base-dev, qt6-base-dev-tools, pkg-config and g++.
# AMX_QT_LIBDIR may point at the official AppImage's squashfs-root/usr/lib.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
libdir="${AMX_QT_LIBDIR:-$(pkg-config --variable=libdir Qt6Core)}"
export LD_LIBRARY_PATH="$libdir"
"$(pkg-config --variable=libexecdir Qt6Core)/moc" "$here/antimicrox-xml-queue.cpp" -o "$tmp/antimicrox-xml-queue.moc"
g++ -std=c++17 -fPIC $(pkg-config --cflags Qt6Core) -I"$tmp" \
  "$here/antimicrox-xml-queue.cpp" -L"$libdir" -l:libQt6Core.so.6 -o "$tmp/queue"
python3 "$root/toolbox/helpers/antimicrox_compat.py" "$tmp/register.so"
set +e
"$tmp/queue"
baseline=$?
set -e
[ "$baseline" -eq 2 ] || { echo "Expected unregistered argument rejection, got $baseline"; exit 1; }
LD_PRELOAD="$tmp/register.so" "$tmp/queue"
