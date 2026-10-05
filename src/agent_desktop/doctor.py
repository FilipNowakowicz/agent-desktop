"""Preflight checks for the private desktop runtime.

Each check reports ok, warn or fail with a hint. `smoke` additionally creates a
session, captures it and destroys it. Nothing here changes the host.
"""

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import core
from .worker import find_registryd

# Stock wlroots versions with the reproduced Xwayland mapping race.
AFFECTED_WLROOTS = ("0.19.3", "0.20.2")
REPAIR_MARKER = "agent-desktop-xwayland-repair"


def run(argv, timeout=5):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as error:
        return None, str(error)
    return result.returncode, (result.stdout + result.stderr).strip()


def tool(name, required, hint):
    variable = "AGENT_DESKTOP_" + name.upper().replace("-", "_")
    executable = shutil.which(os.environ.get(variable, name))
    if executable:
        return {"check": name, "status": "ok", "path": executable}
    return {
        "check": name,
        "status": "fail" if required else "warn",
        "detail": "not found on PATH" + (f" or in {variable}" if required else ""),
        "hint": hint,
    }


def wlroots(labwc):
    """Which wlroots this labwc loads, and whether it is the project's repair."""
    _, output = run([labwc, "--version"])
    version = re.search(r"wlroots-([0-9.]+)", output or "")
    version = version.group(1) if version else None
    _, libraries = run(["ldd", labwc])
    library = re.search(r"libwlroots[^\s]* => (\S+)", libraries or "")
    library = Path(library.group(1)).resolve() if library else None
    if version is None and library:
        # Older labwc releases omit wlroots from --version; use the library name.
        named = re.search(r"libwlroots-([0-9]+\.[0-9]+)", library.name)
        version = named.group(1) if named else None
    repaired = bool(library and (library.parent / REPAIR_MARKER).exists())
    result = {"check": "wlroots", "version": version, "library": str(library)}
    if repaired:
        marker = (library.parent / REPAIR_MARKER).read_text().strip()
        return {**result, "status": "ok", "detail": f"repaired runtime ({marker})"}
    if version and any(v.startswith(version + ".") for v in AFFECTED_WLROOTS):
        return {
            **result,
            "status": "warn",
            "detail": f"wlroots {version}.x: the patch level is unknown, and "
            f"{', '.join(AFFECTED_WLROOTS)} can leave X11 windows unmapped",
            "hint": "native Wayland apps are unaffected; for X11 apps build the "
            "repair (scripts/build_xwayland_runtime.sh, runtime/README.md)",
        }
    if version in AFFECTED_WLROOTS:
        return {
            **result,
            "status": "warn",
            "detail": f"stock wlroots {version} can leave X11 windows unmapped",
            "hint": "native Wayland apps are unaffected; for X11 apps build the "
            "repair (scripts/build_xwayland_runtime.sh, runtime/README.md)",
        }
    if version:
        return {**result, "status": "ok"}
    return {
        **result,
        "status": "warn",
        "detail": "could not determine the wlroots version labwc uses",
    }


def runtime_directory():
    host = os.environ.get("XDG_RUNTIME_DIR")
    if not host or not Path(host).is_dir() or not os.access(host, os.W_OK):
        return {
            "check": "XDG_RUNTIME_DIR",
            "status": "fail",
            "detail": f"unset or not writable: {host!r}",
            "hint": "run from a normal login session or export a private 0700 directory",
        }
    # The longest socket a session creates must fit in sockaddr_un (108 bytes).
    longest = Path(host) / "agent-desktop" / ("0" * 12) / "takeover-control.sock"
    if len(str(longest).encode()) >= 108:
        return {
            "check": "XDG_RUNTIME_DIR",
            "status": "fail",
            "detail": f"path too long for session sockets: {host}",
        }
    return {"check": "XDG_RUNTIME_DIR", "status": "ok", "path": host}


def accessibility():
    registryd = find_registryd()
    if registryd:
        return {"check": "at-spi2-registryd", "status": "ok", "path": registryd}
    return {
        "check": "at-spi2-registryd",
        "status": "warn",
        "detail": "not found; semantic UI tools are unavailable",
        "hint": "install at-spi2-core or set AGENT_DESKTOP_AT_SPI_REGISTRYD",
    }


def smoke():
    started = time.monotonic()
    try:
        session = core.create()["session"]
    except core.DesktopError as error:
        return {"check": "smoke", "status": "fail", "detail": str(error)[:500]}
    try:
        capture = core.request(session, "screenshot")
        detail = f"{capture['width']}x{capture['height']} capture"
    except core.DesktopError as error:
        detail = None
        failure = str(error)[:500]
    finally:
        cleanup = core.destroy(session)
    elapsed = round(time.monotonic() - started, 2)
    if detail is None:
        return {"check": "smoke", "status": "fail", "detail": failure}
    if cleanup.get("status") != "stopped":
        return {"check": "smoke", "status": "fail", "detail": f"cleanup: {cleanup}"}
    return {"check": "smoke", "status": "ok", "detail": f"{detail} in {elapsed} s"}


def doctor(with_smoke=False):
    checks = [
        tool("labwc", True, "install labwc (the private compositor)"),
        tool("grim", True, "install grim (screenshots)"),
        tool("dbus-daemon", True, "install dbus (the session's private bus)"),
        tool("Xwayland", False, "install Xwayland for X11 applications"),
        tool("wayvnc", False, "install wayvnc for `view` and `take`"),
        tool("vncviewer", False, "install TigerVNC's vncviewer for `view` and `take`"),
        runtime_directory(),
        accessibility(),
    ]
    labwc = checks[0].get("path")
    if labwc:
        checks.append(wlroots(labwc))
    if with_smoke and all(c["status"] != "fail" for c in checks):
        checks.append(smoke())
    statuses = {c["status"] for c in checks}
    overall = "fail" if "fail" in statuses else "warn" if "warn" in statuses else "ok"
    return {"status": overall, "checks": checks}
