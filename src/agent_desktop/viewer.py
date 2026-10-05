"""Optional observer and human takeover over private Unix VNC sockets."""

import json
import os
import shutil
import signal
import subprocess
import tempfile

from .core import DesktopError, request

READ_ONLY = [
    "-ViewOnly",
    "-AcceptClipboard=0",
    "-SendClipboard=0",
    "-SendPrimary=0",
    "-SetPrimary=0",
]


# Takeover never copies the private clipboard to the host. With paste, the
# host clipboard (not the primary selection) is sent in, e.g. from a password
# manager; the session clipboard is cleared when control returns.
def interactive_flags(paste=False):
    return [
        "-AcceptClipboard=0",
        f"-SendClipboard={int(paste)}",
        "-SendPrimary=0",
        "-SetPrimary=0",
    ]


def run_viewer(executable, endpoint, flags):
    with tempfile.TemporaryDirectory(prefix="desktop-viewer-") as home:
        env = os.environ.copy()
        env.update(HOME=home, XDG_CONFIG_HOME=home, XDG_CACHE_HOME=home)
        process = subprocess.Popen(
            [
                executable,
                *flags,
                "-Shared",
                "-RemoteResize=0",
                "-AlertOnFatalError=0",
                "-ReconnectOnError=0",
                endpoint,
            ],
            env=env,
            start_new_session=True,
        )
        try:
            return process.wait()
        except KeyboardInterrupt:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
            return 0


def viewer_executable(viewer):
    executable = shutil.which(
        viewer or os.environ.get("AGENT_DESKTOP_VIEWER", "vncviewer")
    )
    if not executable:
        raise DesktopError("Missing optional viewer dependency: vncviewer")
    return executable


def desktop_running(session):
    try:
        return request(session, "status")["status"] == "ready"
    except DesktopError:
        return False


def view(session, wayvnc=None, viewer=None):
    executable = viewer_executable(viewer)
    server = request(
        session,
        "viewer_start",
        wayvnc=wayvnc or os.environ.get("AGENT_DESKTOP_WAYVNC", "wayvnc"),
    )
    code = run_viewer(executable, server["socket"], READ_ONLY)
    if code:
        raise DesktopError(
            f"Viewer exited with code {code}; the desktop session is still independent"
        )
    return {
        "session": session,
        "viewer_closed": True,
        "desktop_running": desktop_running(session),
    }


def first(value):
    """The first entry of a comma-separated layout list, if any."""
    value = (value or "").split(",")[0].strip()
    return value or None


def host_keyboard():
    """The person's keyboard layout as wayvnc's <layout>[-<variant>], or None.

    TigerVNC sends key positions, which wayvnc translates with its own layout,
    so takeover must use the host's layout (e.g. us-dvorak types QWERTY
    otherwise). Order: AGENT_DESKTOP_KEYBOARD, Hyprland, XKB_DEFAULT_*,
    localectl.
    """
    configured = os.environ.get("AGENT_DESKTOP_KEYBOARD")
    if configured:
        return configured
    layout = variant = None
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") and shutil.which("hyprctl"):
        values = []
        for option in ("input:kb_layout", "input:kb_variant"):
            try:
                result = subprocess.run(
                    ["hyprctl", "getoption", option, "-j"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                values.append(first(json.loads(result.stdout).get("str")))
            except (OSError, ValueError, subprocess.SubprocessError):
                values.append(None)
        layout, variant = values
    if not layout:
        layout = first(os.environ.get("XKB_DEFAULT_LAYOUT"))
        variant = first(os.environ.get("XKB_DEFAULT_VARIANT"))
    if not layout and shutil.which("localectl"):
        try:
            status = subprocess.run(
                ["localectl", "status"], capture_output=True, text=True, timeout=3
            ).stdout
        except (OSError, subprocess.SubprocessError):
            status = ""
        for line in status.splitlines():
            key, _, value = line.strip().partition(":")
            if key == "X11 Layout":
                layout = first(value)
            elif key == "X11 Variant":
                variant = first(value)
    if not layout:
        return None
    return f"{layout}-{variant}" if variant else layout


def take(session, wayvnc=None, viewer=None, paste=False, keyboard=None):
    """Hold control of a session in an interactive viewer; closing it hands back."""
    executable = viewer_executable(viewer)
    server = request(
        session,
        "take",
        wayvnc=wayvnc or os.environ.get("AGENT_DESKTOP_WAYVNC", "wayvnc"),
        keyboard=keyboard or host_keyboard(),
    )
    try:
        code = run_viewer(executable, server["socket"], interactive_flags(paste))
    finally:
        release_error = None
        try:
            state = request(session, "release")
        except DesktopError as error:
            state, release_error = None, str(error)
    if code:
        raise DesktopError(
            f"Viewer exited with code {code}; control returned to the agent"
        )
    return {
        "session": session,
        "viewer_closed": True,
        "keyboard": server.get("keyboard"),
        "control": state["owner"] if state else "human",
        "release_error": release_error,
        "desktop_running": desktop_running(session),
    }
