#!/bin/sh
# Build a project-local wlroots 0.20.2 repair and copy its labwc consumer.
set -eu

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 NEW_OUTPUT_DIRECTORY" >&2
    exit 2
fi
for tool in curl sha256sum tar patch meson ninja pkg-config patchelf labwc; do
    command -v "$tool" >/dev/null || { echo "Missing runtime build tool: $tool" >&2; exit 1; }
done
if [ "$(pkg-config --modversion wlroots-0.20)" != "0.20.2" ]; then
    echo "This repair requires the wlroots 0.20.2 development package" >&2
    exit 1
fi
if [ -e "$1" ]; then
    echo "Output directory already exists: $1" >&2
    exit 1
fi
repository=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
compositor=$(command -v labwc)
mkdir -p -- "$1"
output=$(CDPATH= cd -- "$1" && pwd)
archive="$output/wlroots-0.20.2.tar.gz"
curl --fail --location --output "$archive" \
    https://gitlab.freedesktop.org/wlroots/wlroots/-/archive/0.20.2/wlroots-0.20.2.tar.gz
printf '%s  %s\n' 972c7ac44b17828f4702bfae7cd8347346a3fb5b2c1076cfa2c3fcedac5ec343 "$archive" | sha256sum --check -
tar -xzf "$archive" -C "$output"
patch -d "$output/wlroots-0.20.2" -p1 < "$repository/runtime/patches/wlroots-map-at-associate.patch"
meson setup "$output/build" "$output/wlroots-0.20.2" \
    --prefix="$output/install" --libdir=lib --buildtype=release \
    -Dexamples=false -Dxwayland=enabled
meson compile -C "$output/build"
meson install -C "$output/build"
mkdir "$output/install/bin"
cp -- "$compositor" "$output/install/bin/labwc"
# Limit the repaired library to this copied compositor; do not change the host loader.
old_rpath=$(patchelf --print-rpath "$output/install/bin/labwc")
patchelf --set-rpath "\$ORIGIN/../lib${old_rpath:+:$old_rpath}" "$output/install/bin/labwc"
printf 'Private runtime: %s/install/bin/labwc\n' "$output"
