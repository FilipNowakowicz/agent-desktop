"""Session creation and a local Unix socket API. No host-display fallback."""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path


class DesktopError(RuntimeError):
    pass


def state_root():
    override = os.environ.get("AGENT_DESKTOP_STATE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return (
        Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
        / "agent-desktop"
    )


def session_path(session):
    if not isinstance(session, str) or not re.fullmatch(r"[a-f0-9]{12}", session):
        raise DesktopError("Invalid session identifier")
    root = state_root() / session
    if not root.is_dir() or root.is_symlink():
        raise DesktopError(f"Unknown session: {session}")
    return root


def manifest(session):
    try:
        return json.loads((session_path(session) / "session.json").read_text())
    except (OSError, ValueError) as error:
        raise DesktopError(f"Unreadable session: {session}") from error


def request(session, operation, **arguments):
    info = manifest(session)
    endpoint = info["control_socket"]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(30)
            connection.connect(endpoint)
            connection.sendall(
                (json.dumps({"operation": operation, **arguments}) + "\n").encode()
            )
            with connection.makefile("rb") as stream:
                line = stream.readline(262145)
            if len(line) > 262144:
                raise DesktopError("Response exceeds the protocol limit")
            reply = json.loads(line)
    except (OSError, ValueError) as error:
        raise DesktopError(
            f"Session unavailable: {session}; see {session_path(session) / 'session.log'}"
        ) from error
    if not reply.get("ok"):
        raise DesktopError(reply.get("error", "Unknown session failure"))
    return reply["result"]


def create(mode="headless", tools=None):
    if mode not in ("headless", "visible"):
        raise DesktopError("Mode must be headless or visible")
    paths = {}
    for tool in ("labwc", "grim", "dbus-daemon"):
        executable = (tools or {}).get(tool) or os.environ.get(
            "AGENT_DESKTOP_" + tool.upper().replace("-", "_"), tool
        )
        paths[tool] = shutil.which(executable)
        if not paths[tool]:
            raise DesktopError(f"Missing executable: {executable}")
    parent = None
    host_runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not host_runtime:
        raise DesktopError(
            "XDG_RUNTIME_DIR must point to a writable user runtime directory"
        )
    if mode == "visible":
        display = os.environ.get("WAYLAND_DISPLAY")
        if not display:
            raise DesktopError("Visible mode requires a parent Wayland display")
        parent = str((Path(host_runtime) / display).resolve())
        if not Path(parent).is_socket():
            raise DesktopError("Parent Wayland socket does not exist")
    session = uuid.uuid4().hex[:12]
    base = state_root()
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    root = base / session
    root.mkdir(mode=0o700)
    runtime_base = Path(host_runtime) / "agent-desktop"
    runtime_base.mkdir(exist_ok=True, mode=0o700)
    if runtime_base.is_symlink() or runtime_base.stat().st_uid != os.getuid():
        raise DesktopError("Unsafe runtime directory")
    runtime = runtime_base / session
    runtime.mkdir(mode=0o700)
    endpoint = str(runtime / "control.sock")
    if len(endpoint.encode()) >= 108:
        shutil.rmtree(runtime)
        shutil.rmtree(root)
        raise DesktopError("Runtime directory is too long for a Unix socket")
    info = {
        "id": session,
        "mode": mode,
        "tools": paths,
        "runtime": str(runtime),
        "control_socket": endpoint,
        "parent_wayland": parent,
        "token": uuid.uuid4().hex,
        "status": "starting",
        "created_at": time.time(),
    }
    (root / "session.json").write_text(json.dumps(info, indent=2) + "\n")
    env = os.environ.copy()
    env["AGENT_DESKTOP_SESSION_TOKEN"] = info["token"]
    with (root / "session.log").open("ab") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "agent_desktop.worker",
                str(root),
            ],
            env=env,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    # Reap the supervisor when this client remains alive (e.g. an MCP server).
    threading.Thread(target=process.wait, daemon=True).start()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        latest = json.loads((root / "session.json").read_text())
        if latest["status"] == "ready":
            return {
                "session": session,
                "mode": mode,
                "status": "ready",
                "logs": str(root / "session.log"),
            }
        if process.poll() is not None or latest["status"] == "failed":
            detail = logs(session).get("session.log", "")[-4096:]
            raise DesktopError(
                f"Session startup failed; see {root / 'session.log'}\n{detail}"
            )
        time.sleep(0.1)
    # The process group is created exclusively for this new session.
    import signal

    os.killpg(process.pid, signal.SIGTERM)
    raise DesktopError(f"Session startup timed out; see {root / 'session.log'}")


def sessions():
    results = []
    for path in sorted(state_root().glob("*/session.json")):
        try:
            info = json.loads(path.read_text())
            status = info["status"]
            if status == "ready":
                try:
                    request(info["id"], "status")
                except DesktopError:
                    status = "unavailable"
            control = info.get("control") or {}
            results.append(
                {
                    "session": info["id"],
                    "mode": info["mode"],
                    "status": status,
                    "control": control.get("owner", "agent"),
                    "human_request": (control.get("request") or {}).get("reason"),
                }
            )
        except (OSError, ValueError, KeyError):
            continue
    return results


def logs(session):
    root = session_path(session)
    files = sorted(root.glob("*.log"))
    result = {}
    for path in files:
        with path.open("rb") as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - 16384))
            result[path.name] = stream.read().decode(errors="replace")
    return result


def supervisor_alive(info):
    marker = f"AGENT_DESKTOP_SESSION_TOKEN={info['token']}".encode()
    for key in ("guardian_pid", "worker_pid"):
        try:
            environment = Path(f"/proc/{info[key]}/environ").read_bytes()
        except (KeyError, OSError):
            continue
        if marker in environment.split(b"\0"):
            return True
    return False


def recover(session, info):
    """Clean up after supervisors that no longer exist, using the session token."""
    from .worker import cleanup_processes, remove_session_files, write_manifest

    root = session_path(session)
    runtime = Path(info["runtime"])
    host_runtime = os.environ.get("XDG_RUNTIME_DIR")
    expected = Path(host_runtime or "/nonexistent") / "agent-desktop" / session
    if not host_runtime or runtime.resolve() != expected.resolve():
        raise DesktopError("Refusing to remove an unexpected runtime directory")
    try:
        # Token only: this process's own children are not session processes.
        cleanup_processes(info["token"], tree=False)
    except RuntimeError as error:
        raise DesktopError(f"Recovery failed: {error}") from error
    remove_session_files(root, runtime)
    info.update(status="stopped", recovered=True)
    write_manifest(root, info)
    return {
        "session": session,
        "status": "stopped",
        "recovered": True,
        "runtime_removed": not runtime.exists(),
    }


def wait_for_agent_control(session, timeout):
    """Wait until no person holds or has been asked to take the session."""
    deadline = time.monotonic() + max(0, min(timeout, 600))
    while True:
        state = request(session, "control")
        if state["owner"] == "agent" and not state["request"]:
            return state
        if time.monotonic() >= deadline:
            return state
        time.sleep(0.5)


def destroy(session):
    info = manifest(session)
    if info["status"] == "stopped":
        return {"session": session, "status": "stopped"}
    try:
        request(session, "destroy")
    except DesktopError:
        if supervisor_alive(info):
            raise
        return recover(session, info)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        info = manifest(session)
        # Stopped means the supervisors have exited too, not just the worker's report.
        if info["status"] == "stopped" and not supervisor_alive(info):
            return {
                "session": session,
                "status": "stopped",
                "runtime_removed": not Path(info["runtime"]).exists(),
            }
        if info["status"] == "failed":
            raise DesktopError(
                f"Session cleanup failed; see {session_path(session) / 'session.log'}"
            )
        time.sleep(0.1)
    raise DesktopError("Session cleanup timed out")
