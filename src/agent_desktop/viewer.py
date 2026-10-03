"""Optional observer for a headless session over a private Unix VNC socket."""

import os
import shutil
import signal
import subprocess
import tempfile

from .core import DesktopError, request


def view(session, wayvnc=None, viewer=None):
    executable = shutil.which(
        viewer or os.environ.get("AGENT_DESKTOP_VIEWER", "vncviewer")
    )
    if not executable:
        raise DesktopError("Missing optional viewer dependency: vncviewer")
    server = request(
        session,
        "viewer_start",
        wayvnc=wayvnc or os.environ.get("AGENT_DESKTOP_WAYVNC", "wayvnc"),
    )
    with tempfile.TemporaryDirectory(prefix="desktop-viewer-") as home:
        env = os.environ.copy()
        env.update(HOME=home, XDG_CONFIG_HOME=home, XDG_CACHE_HOME=home)
        process = subprocess.Popen(
            [
                executable,
                "-ViewOnly",
                "-Shared",
                "-RemoteResize=0",
                "-AcceptClipboard=0",
                "-SendClipboard=0",
                "-SendPrimary=0",
                "-SetPrimary=0",
                "-AlertOnFatalError=0",
                "-ReconnectOnError=0",
                server["socket"],
            ],
            env=env,
            start_new_session=True,
        )
        try:
            code = process.wait()
        except KeyboardInterrupt:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
            code = 0
        if code:
            raise DesktopError(
                f"Viewer exited with code {code}; the desktop session is still independent"
            )
    try:
        running = request(session, "status")["status"] == "ready"
    except DesktopError:
        running = False
    return {"session": session, "viewer_closed": True, "desktop_running": running}
