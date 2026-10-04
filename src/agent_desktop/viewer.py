"""Optional observer and human takeover over private Unix VNC sockets."""

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
# Takeover still keeps the host and private clipboards apart.
INTERACTIVE = [
    "-AcceptClipboard=0",
    "-SendClipboard=0",
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


def take(session, wayvnc=None, viewer=None):
    """Hold control of a session in an interactive viewer; closing it hands back."""
    executable = viewer_executable(viewer)
    server = request(
        session,
        "take",
        wayvnc=wayvnc or os.environ.get("AGENT_DESKTOP_WAYVNC", "wayvnc"),
    )
    try:
        code = run_viewer(executable, server["socket"], INTERACTIVE)
    finally:
        try:
            state = request(session, "release")
        except DesktopError:
            state = None
    if code:
        raise DesktopError(
            f"Viewer exited with code {code}; control returned to the agent"
        )
    return {
        "session": session,
        "viewer_closed": True,
        "control": state["owner"] if state else None,
        "desktop_running": desktop_running(session),
    }
