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


PROFILE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")


def profile_path(name):
    """A persistent home that survives sessions, e.g. to keep a browser login."""
    if not isinstance(name, str) or not PROFILE_NAME.fullmatch(name):
        raise DesktopError(
            "Profile names use 1-32 lowercase letters, digits, '-' or '_'"
        )
    return state_root() / "profiles" / name


def profile_in_use(path):
    import fcntl

    try:
        with (path / "lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    except FileNotFoundError:
        return False
    return False


def profiles():
    root = state_root() / "profiles"
    results = []
    for path in sorted(root.glob("*/home")):
        profile = path.parent
        size = sum(
            f.stat().st_size
            for f in path.rglob("*")
            if f.is_file() and not f.is_symlink()
        )
        results.append(
            {
                "profile": profile.name,
                "in_use": profile_in_use(profile),
                "bytes": size,
                "path": str(path),
            }
        )
    return results


def delete_profile(name):
    path = profile_path(name)
    if not (path / "home").is_dir() or path.is_symlink():
        raise DesktopError(f"Unknown profile: {name}")
    if profile_in_use(path):
        raise DesktopError(f"Profile {name} is in use by a session")
    shutil.rmtree(path)
    return {"profile": name, "deleted": True}


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


def create(mode="headless", tools=None, profile=None, guard_host=False):
    if mode not in ("headless", "visible"):
        raise DesktopError("Mode must be headless or visible")
    home = None
    if profile is not None:
        home = profile_path(profile) / "home"
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        if home.parent.is_symlink() or home.is_symlink():
            raise DesktopError("Unsafe profile directory")
        if profile_in_use(home.parent):
            raise DesktopError(f"Profile {profile} is in use by another session")
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
        "profile": profile,
        "guard_host": bool(guard_host),
        "home": str(home) if home else None,
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
                "profile": profile,
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


# A blinking text caret changes a thin box; a loading spinner is larger.
QUIET_AREA = 400


def wait(
    session,
    title=None,
    app_id=None,
    gone=False,
    stable_ms=0,
    timeout=10,
    element=None,
    role=None,
    text=None,
    seconds=0,
):
    """Wait until every condition holds at the same time.

    Conditions: a window (title substring and/or exact app_id), a UI element
    (accessible name substring, exact role and/or text or value substring,
    searched within the matched window when a title is given) and a settled
    screen. `gone` applies to the window condition, or to the element condition
    when no window condition is given; an incomplete tree never counts as gone.
    `seconds` pauses first; `timeout` counts from the end of the pause.

    Changes covering at most QUIET_AREA square pixels, such as a blinking caret,
    count as settled.
    """
    if not isinstance(timeout, (int, float)) or not 0 <= timeout <= 120:
        raise DesktopError("Timeout must be between 0 and 120 seconds")
    if not isinstance(stable_ms, int) or not 0 <= stable_ms <= 30000:
        raise DesktopError("stable_ms must be an integer from 0 to 30000")
    if not isinstance(seconds, (int, float)) or not 0 <= seconds <= 30:
        raise DesktopError("seconds must be between 0 and 30")
    # Every wait addresses an existing, controllable session, even a plain pause.
    request(session, "control")
    started = time.monotonic()
    # A plain pause first, for changes no condition can describe.
    time.sleep(seconds)
    deadline = time.monotonic() + timeout
    wants_window = title is not None or app_id is not None
    wants_element = element is not None or role is not None or text is not None
    element_gone = gone and not wants_window

    def element_matches(node):
        content = str(node.get("text") or "") + str(node.get("value") or "")
        return (
            (element is None or element in node["name"])
            and (role is None or node["role"] == role)
            and (text is None or text in content)
        )

    def check():
        """(satisfied, reason, windows, elements) for one consistent look."""
        windows, elements = [], []
        if wants_window:
            windows = [
                w
                for w in request(session, "windows")["windows"]
                if (title is None or title in w["title"])
                and (app_id is None or w["app_id"] == app_id)
            ]
            if bool(windows) == gone:
                return (
                    False,
                    ("window still present" if gone else "no window"),
                    windows,
                    [],
                )
        if wants_element:
            scope = {"window": title} if title is not None and not gone else {}
            tree = request(session, "ui", max_nodes=2000, **scope)
            elements = [n for n in tree["nodes"] if element_matches(n)]
            if element_gone and elements:
                return False, "element still present", windows, elements
            if element_gone and tree["truncated"]:
                return False, "element unknown: tree truncated", windows, elements
            if not element_gone and not elements:
                return False, "no element", windows, elements
        return True, "ok", windows, elements

    def result(satisfied, reason, windows, elements):
        return {
            "satisfied": satisfied,
            "reason": reason,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "windows": windows,
            "elements": elements[:5],
        }

    while True:
        satisfied, reason, windows, elements = check()
        if satisfied and stable_ms:
            quiet_since = time.monotonic()
            frame = request(session, "frame")["frame"]
            while time.monotonic() - quiet_since < stable_ms / 1000:
                if time.monotonic() >= deadline:
                    return result(False, "screen still changing", windows, elements)
                time.sleep(0.05)
                latest = request(session, "frame", since=frame)
                frame, box = latest["frame"], latest["changed"]
                if box == "unknown" or (box and box[2] * box[3] > QUIET_AREA):
                    quiet_since = time.monotonic()
            # The conditions must still hold once the screen has settled.
            satisfied, reason, windows, elements = check()
        if satisfied:
            return result(True, "ok", windows, elements)
        if time.monotonic() >= deadline:
            return result(False, reason, windows, elements)
        time.sleep(0.2 if wants_element else 0.05)


SEQUENCE_ACTIONS = (
    "click",
    "move",
    "drag",
    "scroll",
    "type",
    "key",
    "ui_action",
    "focus",
    "wait",
)


def run_actions(session, actions, observation=None):
    """Run up to 50 actions, stopping at the first surprise.

    Each input action is sent only if windows, focus and output are as they were
    right after the previous action (or as in `observation` for the first). A
    `wait` or `focus` step expects a change and takes a new baseline. Popups and
    in-window changes are not detected; take a screenshot afterwards.
    """
    if not isinstance(actions, list) or not 1 <= len(actions) <= 50:
        raise DesktopError("Actions must be a list of 1 to 50 steps")
    for index, step in enumerate(actions):
        if not isinstance(step, dict) or step.get("action") not in SEQUENCE_ACTIONS:
            raise DesktopError(
                f"Step {index} needs an action: {', '.join(SEQUENCE_ACTIONS)}"
            )
        if "observation" in step or "session" in step:
            raise DesktopError(f"Step {index} must not set observation or session")
    baseline = observation or request(session, "observe")["observation"]
    # Keep a cropped or scaled screenshot's coordinate mapping for every step.
    mapping = "@" + observation.partition("@")[2] if "@" in (observation or "") else ""
    for index, step in enumerate(actions):
        arguments = {k: v for k, v in step.items() if k != "action"}
        action = step["action"]
        try:
            if action == "wait":
                waited = wait(session, **arguments)
                if not waited["satisfied"]:
                    return stopped(index, len(actions), f"wait: {waited['reason']}")
            elif action == "focus":
                request(session, "focus", **arguments)
            else:
                request(session, action, observation=baseline, **arguments)
        except DesktopError as error:
            return stopped(index, len(actions), str(error))
        except TypeError as error:
            hint = (
                "; wait accepts title, app_id, gone, stable_ms, timeout, element, "
                "role, text and seconds"
                if action == "wait"
                else ""
            )
            return stopped(index, len(actions), f"{error}{hint}")
        try:
            baseline = request(session, "observe")["observation"] + mapping
        except DesktopError as error:
            # The step was delivered; report it rather than an unqualified error.
            return stopped(
                index + 1,
                len(actions),
                f"step {index} was delivered, then observation failed: {error}",
            )
    return {"completed": len(actions), "total": len(actions), "stopped": None}


def stopped(index, total, reason):
    return {
        "completed": index,
        "total": total,
        "stopped": {"step": index, "reason": reason},
    }


def render_tree(tree):
    """Compact text for agents: one indented line per UI element."""
    lines = []
    for node in tree["nodes"]:
        line = "  " * node["depth"] + f"{node['id']} {node['role']}"
        if node["name"]:
            line += f" {node['name']!r}"
        if node["states"]:
            line += f" [{','.join(node['states'])}]"
        if node.get("text") is not None:
            text = node["text"]
            line += f" text={text[:200]!r}" + ("…" if len(text) > 200 else "")
        if "value" in node:
            line += f" value={node['value']:g}"
        # Chromium offers doDefault everywhere; "press" still falls back to it.
        actions = [a for a in node.get("actions", ()) if a != "doDefault"]
        if actions:
            line += f" actions={','.join(actions)}"
        lines.append(line)
    if tree["truncated"]:
        lines.append("… truncated: filter by app or window, or raise max_nodes")
    return "\n".join(lines) or "(no accessible elements)"


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
