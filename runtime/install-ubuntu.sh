#!/bin/sh
# Install the desktop runtime on Ubuntu 24.04 from the Ubuntu archive.
# Python dependencies are separate: `uv sync` in the repository.
set -eu

. /etc/os-release
if [ "${ID:-}" != ubuntu ] || [ "${VERSION_ID:-}" != 24.04 ]; then
    echo "This recipe is tested on Ubuntu 24.04; found ${PRETTY_NAME:-unknown}." >&2
    echo "Set AGENT_DESKTOP_INSTALL_ANYWAY=1 to try it." >&2
    [ "${AGENT_DESKTOP_INSTALL_ANYWAY:-}" = 1 ] || exit 1
fi

# Required: compositor, capture, private bus, X11 applications.
required="labwc grim dbus-daemon xwayland"
# Optional: viewer and human takeover, clipboard, semantic UI, a terminal.
optional="wayvnc tigervnc-viewer wl-clipboard at-spi2-core foot"

sudo apt-get update
# shellcheck disable=SC2086
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends $required $optional
dpkg-query -W $required $optional
