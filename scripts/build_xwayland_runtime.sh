#!/bin/sh
# Build a project-local wlroots mapping repair and copy its labwc consumer.
set -eu

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 NEW_OUTPUT_DIRECTORY" >&2
    exit 2
fi
for tool in curl sha256sum tar patch meson ninja pkg-config patchelf labwc; do
    command -v "$tool" >/dev/null || { echo "Missing runtime build tool: $tool" >&2; exit 1; }
done
if [ -e "$1" ]; then
    echo "Output directory already exists: $1" >&2
    exit 1
fi
repository=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
compositor=$(command -v labwc)
case "$(patchelf --print-needed "$compositor")" in
    *libwlroots-0.20.so*)
        abi=0.20; version=0.20.2
        checksum=972c7ac44b17828f4702bfae7cd8347346a3fb5b2c1076cfa2c3fcedac5ec343 ;;
    *libwlroots-0.19.so*)
        abi=0.19; version=0.19.3
        checksum=a6ff89b64ea15e424d1b0db4a22145fccf5ec2ff2e7b8af0fa35e2ac8975986f ;;
    *) echo "Unsupported labwc library ABI" >&2; exit 1 ;;
esac
if [ "$(pkg-config --modversion "wlroots-$abi")" != "$version" ]; then
    echo "This repair requires the wlroots $version development package" >&2
    exit 1
fi
mkdir -p -- "$1"
output=$(CDPATH= cd -- "$1" && pwd)
archive="$output/wlroots-$version.tar.gz"
curl --fail --location --output "$archive" \
    "https://gitlab.freedesktop.org/wlroots/wlroots/-/archive/$version/wlroots-$version.tar.gz"
printf '%s  %s\n' "$checksum" "$archive" | sha256sum --check -
tar -xzf "$archive" -C "$output"
patch --fuzz=0 -d "$output/wlroots-$version" -p1 < "$repository/runtime/patches/wlroots-map-at-associate.patch"
meson setup "$output/build" "$output/wlroots-$version" \
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
