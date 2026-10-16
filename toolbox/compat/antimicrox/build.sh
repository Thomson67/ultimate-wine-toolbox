#!/bin/bash
# Ubuntu 24.04: g++ binutils qt6-base-dev pkg-config (Qt 6.4.2).
set -euo pipefail
cd "$(dirname "$0")"
tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
g++ -std=c++17 -O2 -shared -fPIC -fvisibility=hidden \
  -Wl,-z,defs -Wl,-z,relro,-z,now \
  $(pkg-config --cflags Qt6Core) register-xml-reader.cpp \
  $(pkg-config --libs Qt6Core) -o "$tmp/register-xml-reader.so"
strip --strip-unneeded "$tmp/register-xml-reader.so"
base64 "$tmp/register-xml-reader.so" > register-xml-reader-x86_64.so.b64
sha256sum "$tmp/register-xml-reader.so"
echo 'Update SHA256 in toolbox/helpers/antimicrox_compat.py after rebuilding.'
