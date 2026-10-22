"""Session creation and a local Unix socket API. No host-display fallback."""

import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path


class DesktopError(RuntimeError):
    pass


class DeliveryUnknown(DesktopError):
    """Execution may have acted, but no reliable delivery result is available."""


FILE_READ_LIMIT = 2 * 1024 * 1024


RENDERERS = ("pixman", "gles2", "vulkan")


def render_nodes():
    """Accessible GPU render nodes and their kernel drivers, e.g. i915 or nvidia."""
    nodes = {}
    for node in sorted(Path("/dev/dri").glob("renderD*")):
        if os.access(node, os.R_OK | os.W_OK):
            driver = Path("/sys/class/drm", node.name, "device/driver")
            nodes[str(node)] = driver.resolve().name if driver.exists() else None
    return nodes


def compositor_renderer():
    """The compositor's renderer and render node: software unless configured.

    A GPU renderer without a device lets wlroots choose the node, which on a
    machine with two GPUs can be one it cannot initialize.
    """
    renderer = os.environ.get("AGENT_DESKTOP_RENDERER") or "pixman"
    device = os.environ.get("AGENT_DESKTOP_RENDER_DEVICE") or None
    if renderer not in RENDERERS:
        raise DesktopError(
            f"AGENT_DESKTOP_RENDERER must be one of {', '.join(RENDERERS)}"
        )
    if device and renderer == "pixman":
        raise DesktopError("AGENT_DESKTOP_RENDER_DEVICE needs a GPU renderer")
    if device and device not in render_nodes():
        raise DesktopError(f"Not an accessible render node: {device}")
    return {"name": renderer, "device": device}


def host_runtime_dir(shared=Path("/tmp")):
    """Where session runtimes go: XDG_RUNTIME_DIR, or without a login session
    (containers, cron, CI) a private /tmp/agent-desktop-<uid>.

    /tmp is shared, so the fallback must be a real directory owned by this
    user and closed to others; anything else is refused, not repaired.
    """
    configured = os.environ.get("XDG_RUNTIME_DIR")
    if configured:
        return Path(configured)
    path = shared / f"agent-desktop-{os.getuid()}"
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    found = path.lstat()
    if (
        not stat.S_ISDIR(found.st_mode)
        or found.st_uid != os.getuid()
        or found.st_mode & 0o077
    ):
        raise DesktopError(
            f"XDG_RUNTIME_DIR is unset and {path} is not a private directory "
            "of this user; export XDG_RUNTIME_DIR as a private 0700 directory"
        )
    return path


def state_root():
    override = os.environ.get("AGENT_DESKTOP_STATE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return (
        Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
        / "agent-desktop"
    )


def runtime_prefix():
    """The selected desktop runtime prefix, if any.

    AGENT_DESKTOP_RUNTIME names it; otherwise a runtime installed (or linked,
    e.g. by `nix build --out-link`) at $XDG_DATA_HOME/agent-desktop/runtime is
    used. Without either, tools come from PATH.
    """
    override = os.environ.get("AGENT_DESKTOP_RUNTIME")
    if override:
        return Path(override).expanduser()
    default = (
        Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
        / "agent-desktop/runtime"
    )
    return default if (default / "bin").is_dir() else None


def use_runtime():
    """Put the selected runtime first on PATH for this process and its sessions."""
    prefix = runtime_prefix()
    if prefix is None:
        return None
    bin_dir = str(prefix / "bin")
    entries = os.environ.get("PATH", "").split(os.pathsep)
    if entries[:1] != [bin_dir]:
        os.environ["PATH"] = os.pathsep.join([bin_dir, *entries])
    return prefix


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


def profile_lock(path):
    """Lock file beside (not inside) a profile, so deletion cannot remove it.

    It is never deleted: unlinking a lock others may hold would let two
    processes believe they own the profile.
    """
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path.parent / f".{path.name}.lock"


def profile_in_use(path):
    import fcntl

    try:
        with profile_lock(path).open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    return False


def profile_last_session(path):
    """The session that most recently started on a profile, or None."""
    try:
        session = json.loads((path / "last-session.json").read_text())["session"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(session, str) or not re.fullmatch(r"[a-f0-9]{12}", session):
        return None
    return session


def profile_state(path):
    """How the profile's last session ended, or None if it has never been used.

    "abandoned" means neither supervisor is alive but nothing marked the session
    stopped or failed (both were killed): its applications may still be running.
    "pruned" means the session's state has since been removed.
    """
    session = profile_last_session(path)
    if session is None:
        return None
    try:
        info = manifest(session)
    except DesktopError:
        return {"session": session, "status": "pruned"}
    status = info.get("status")
    if status not in ("stopped", "failed") and not supervisor_alive(info):
        status = "abandoned"
    state = {"session": session, "status": status}
    if info.get("recovered"):
        state["recovered"] = True
    if info.get("error"):
        state["error"] = info["error"]
    return state


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
                "last_session": profile_state(profile),
                "bytes": size,
                "path": str(path),
            }
        )
    return results


def delete_profile(name):
    path = profile_path(name)
    if not (path / "home").is_dir() or path.is_symlink():
        raise DesktopError(f"Unknown profile: {name}")
    import fcntl

    # Hold the lock for the whole deletion: a session starting meanwhile waits
    # for nothing and fails instead of using a half-deleted profile.
    with profile_lock(path).open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DesktopError(f"Profile {name} is in use by a session") from None
        shutil.rmtree(path)
    return {"profile": name, "deleted": True}


def manifest(session):
    try:
        return json.loads((session_path(session) / "session.json").read_text())
    except (OSError, ValueError) as error:
        raise DesktopError(f"Unreadable session: {session}") from error


def controller_id(controller=None):
    """The controller a request is made for: the argument, else
    AGENT_DESKTOP_CONTROLLER, else None (anonymous)."""
    return controller or os.environ.get("AGENT_DESKTOP_CONTROLLER") or None


def request_budget(operation, arguments):
    """Worker budget in seconds; transport allows another five seconds to reply.

    Browser batches get the sum of their step budgets rather than the default
    socket timeout. These are execution budgets, not evidence of task success.
    """
    if operation == "type":
        text = arguments.get("text")
        return 30 + (len(text) * 0.03 if isinstance(text, str) else 0)
    if operation == "browser":
        if arguments.get("action") == "steps":
            steps = arguments.get("steps")
            if isinstance(steps, list) and 1 <= len(steps) <= 30:
                return sum(
                    request_budget("browser", step)
                    if isinstance(step, dict) and step.get("action") != "steps"
                    else 30
                    for step in steps
                )
        if arguments.get("action") == "wait":
            timeout, seconds = arguments.get("timeout", 10), arguments.get("seconds", 0)
            if (
                isinstance(timeout, (int, float))
                and 0 <= timeout <= 60
                and isinstance(seconds, (int, float))
                and 0 <= seconds <= 30
            ):
                # Target discovery and the last condition read can each wait
                # for a command reply beyond the requested polling interval.
                return 90 + timeout + seconds
        return 180  # target discovery, input/navigation, then page/element reads
    return 30


def request(session, operation, controller=None, **arguments):
    """Send one operation to a session's supervisor and return its result.

    Controller lease: each session has at most one controller. A mutating
    operation (input, launch, focus, ui_action, request_human) from a named
    controller takes the lease when none is held; any request from the holder
    renews it; it expires after AGENT_DESKTOP_LEASE_SECONDS (default 60) without
    requests or is released with the "lease" operation. While it is held,
    mutating requests from other or anonymous controllers are refused with
    LeaseHeld and nothing is sent. Anonymous requests run without a lease when
    none is held. Reads, destroy, take and release are never refused by a lease.

    Raises DeliveryUnknown when a sent request has no reliable reply or fails
    after mutation starts. It may have partly run; never repeat it blindly.
    """
    info = manifest(session)
    endpoint = info["control_socket"]
    budget = request_budget(operation, arguments)
    message = {
        "operation": operation,
        **arguments,
        "deadline": time.monotonic() + budget,
    }
    controller = controller_id(controller)
    if controller is not None:
        message["controller"] = controller
    sent = False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(budget + 5)
            connection.connect(endpoint)
            payload = (json.dumps(message) + "\n").encode()
            # A failed send can have transmitted enough for execution. Once
            # sending starts, only a reply can establish the delivery result.
            sent = True
            connection.sendall(payload)
            with connection.makefile("rb") as stream:
                line = stream.readline(262145)
            if len(line) > 262144:
                raise ValueError("Response exceeds the protocol limit")
            reply = json.loads(line)
            if (
                not isinstance(reply, dict)
                or type(reply.get("ok")) is not bool
                or (reply["ok"] and "result" not in reply)
                or (not reply["ok"] and not isinstance(reply.get("error"), str))
            ):
                raise ValueError("Malformed session reply")
    except (OSError, ValueError) as error:
        if sent:
            raise DeliveryUnknown(
                f"No reply from session {session} after sending {operation}; it "
                "may or may not have run. Check the desktop before acting again."
            ) from error
        raise DesktopError(
            f"Session unavailable: {session}; see {session_path(session) / 'session.log'}"
        ) from error
    if not reply.get("ok"):
        if reply.get("uncertain"):
            raise DeliveryUnknown(reply["error"])
        raise DesktopError(reply.get("error", "Unknown session failure"))
    return reply["result"]


def create(
    mode="headless", tools=None, profile=None, guard_host=False, _host_minutes=None
):
    if mode == "host":
        # Only approve_host/request_host may attach to the person's own screen.
        if _host_minutes is None:
            raise DesktopError(
                "Host sessions need the person's approval: use request_host"
            )
        if profile is not None or guard_host:
            raise DesktopError("Host sessions take no profile or host guard")
    elif mode not in ("headless", "visible"):
        raise DesktopError("Mode must be headless or visible")
    renderer = compositor_renderer() if mode != "host" else None
    home = None
    if profile is not None:
        home = profile_path(profile) / "home"
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        if home.parent.is_symlink() or home.is_symlink():
            raise DesktopError("Unsafe profile directory")
        if profile_in_use(home.parent):
            raise DesktopError(f"Profile {profile} is in use by another session")
        previous = profile_state(home.parent)
        if previous and previous["status"] == "abandoned":
            # Both supervisors died, releasing the lock while the old session's
            # applications may still write to the profile: stop them first.
            recover(previous["session"], manifest(previous["session"]))
            previous = profile_state(home.parent)
    paths = {}
    required = ("grim",) if mode == "host" else ("labwc", "grim", "dbus-daemon")
    for tool in required:
        executable = (tools or {}).get(tool) or os.environ.get(
            "AGENT_DESKTOP_" + tool.upper().replace("-", "_"), tool
        )
        paths[tool] = shutil.which(executable)
        if not paths[tool]:
            raise DesktopError(f"Missing executable: {executable}")
    parent = None
    host_runtime = host_runtime_dir()
    if mode in ("visible", "host"):
        display = os.environ.get("WAYLAND_DISPLAY")
        if not display:
            raise DesktopError(f"{mode.title()} mode requires a Wayland desktop")
        parent = str((Path(host_runtime) / display).resolve())
        if not Path(parent).is_socket():
            raise DesktopError("Parent Wayland socket does not exist")
    if mode == "host" and active_host_session():
        raise DesktopError(
            f"A host session is already running: {active_host_session()}"
        )
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
        "renderer": renderer,
        "home": str(home) if home else None,
        "profile_lock": str(profile_lock(home.parent)) if home else None,
        "token": uuid.uuid4().hex,
        "status": "starting",
        "created_at": time.time(),
    }
    if mode == "host":
        info["parent_wayland"] = None
        info["host_wayland"] = parent
        info["expires_at"] = time.time() + _host_minutes * 60
    from .worker import write_private

    write_private(root / "session.json", json.dumps(info, indent=2) + "\n")
    if home:
        (home.parent / "last-session.json").write_text(
            json.dumps({"session": session}) + "\n"
        )
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
            stdin=subprocess.DEVNULL,
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
            result = {
                "session": session,
                "mode": mode,
                "profile": profile,
                "status": "ready",
                "logs": str(root / "session.log"),
            }
            if home:
                # Applications may offer to restore after a failed or recovered end.
                result["previous_session"] = previous
            return result
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


def directory_bytes(path):
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
        except OSError:
            pass
    return total


def usage():
    """Disk used by session state and named profiles."""
    root = state_root()
    counts, total, screenshots = {}, 0, 0
    for path in root.glob("*/session.json"):
        try:
            status = json.loads(path.read_text())["status"]
        except (OSError, ValueError, KeyError):
            status = "unreadable"
        counts[status] = counts.get(status, 0) + 1
        total += directory_bytes(path.parent)
        screenshots += directory_bytes(path.parent / "screenshots")
    profile_bytes = sum(p["bytes"] for p in profiles())
    return {
        "sessions": counts,
        "session_bytes": total,
        "screenshot_bytes": screenshots,
        "profile_bytes": profile_bytes,
        "state_root": str(root),
    }


def prune(older_than_days=0, dry_run=False):
    """Remove stopped or failed sessions' state; never live sessions or profiles."""
    cutoff = time.time() - older_than_days * 86400
    removed, kept, freed = [], [], 0
    for path in sorted(state_root().glob("*/session.json")):
        root = path.parent
        try:
            info = json.loads(path.read_text())
        except (OSError, ValueError):
            kept.append({"session": root.name, "reason": "unreadable manifest"})
            continue
        if info.get("status") not in ("stopped", "failed") or supervisor_alive(info):
            kept.append(
                {"session": root.name, "reason": f"status {info.get('status')}"}
            )
            continue
        if path.stat().st_mtime > cutoff:
            kept.append({"session": root.name, "reason": "newer than the cutoff"})
            continue
        freed += directory_bytes(root)
        removed.append(root.name)
        if not dry_run:
            shutil.rmtree(root)
    return {"removed": removed, "kept": kept, "bytes_freed": freed, "dry_run": dry_run}


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


HOST_REQUEST = "host-request.json"
HOST_REQUEST_SECONDS = 120


def active_host_session():
    """The running host session's id, if any."""
    for entry in sessions():
        if entry.get("mode") == "host" and entry.get("status") in ("starting", "ready"):
            return entry["session"]
    return None


def host_status():
    """The running host session with its expiry, or {"session": None}."""
    session = active_host_session()
    if not session:
        return {"session": None}
    expires = manifest(session).get("expires_at")
    return {
        "session": session,
        "expires_at": expires,
        "seconds_left": max(0, round(expires - time.time())) if expires else None,
    }


def host_minutes(minutes):
    if (
        not isinstance(minutes, (int, float))
        or isinstance(minutes, bool)
        or not 0 < minutes <= 240
    ):
        raise DesktopError("Minutes must be between 0 and 240")
    return minutes


def person_browser():
    """Whether desktop_browser can use the person's Firefox, known before approval."""
    from .worker import person_firefox_bridge

    if person_firefox_bridge(os.environ):
        return {"dom": True}
    return {
        "dom": False,
        "detail": "The person's Firefox has no WebDriver BiDi port, so "
        "desktop_browser cannot use it; screenshots and input still work. Only "
        "they can restart it with --remote-debugging-port=0.",
    }


def request_host(reason, minutes=15, wait=50):
    """Ask the person to let the agent use their own screen.

    A notification shows the reason: clicking it allows, dismissing it declines
    (`agent-desktop host approve` / `deny` answers from a terminal). Waits up to
    `wait` seconds and returns {"status": "pending"} if there is no answer yet;
    call again with the same reason to keep waiting. The request lapses after
    two minutes. Returns the host session on approval.
    """
    if not isinstance(reason, str) or not 0 < len(reason.strip()) <= 300:
        raise DesktopError("Reason must be a nonempty string of at most 300 characters")
    minutes = host_minutes(minutes)
    if not 0 <= wait <= 60:
        raise DesktopError("Wait must be between 0 and 60 seconds")
    running = active_host_session()
    if running:
        return {
            "session": running,
            "status": "ready",
            "approved": "already running",
            "browser": person_browser(),
        }
    base = state_root()
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = base / HOST_REQUEST
    try:
        pending = json.loads(path.read_text())
    except (OSError, ValueError):
        pending = None
    if pending and time.time() > pending.get("expires", 0):
        path.unlink(missing_ok=True)
        if not pending.get("answer"):
            pending = None
    if not pending or pending.get("reason") != reason.strip():
        pending = {
            "id": uuid.uuid4().hex[:12],
            "reason": reason.strip(),
            "minutes": minutes,
            "expires": time.time() + HOST_REQUEST_SECONDS,
        }
        path.write_text(json.dumps(pending))
        if (
            shutil.which("notify-send")
            and os.environ.get("AGENT_DESKTOP_HOST_NOTIFY") != "0"
        ):
            # A separate process owns the notification, so this call can return.
            subprocess.Popen(
                [sys.executable, "-m", "agent_desktop.hostprompt", str(path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
    deadline = time.monotonic() + wait
    while True:
        try:
            current = json.loads(path.read_text())
        except (OSError, ValueError):
            current = {}
        answer = current.get("answer") if current.get("id") == pending["id"] else None
        if answer or time.monotonic() >= deadline:
            break
        if time.time() > pending["expires"]:
            answer = "expired"
            break
        time.sleep(0.2)
    if not answer:
        return {
            "status": "pending",
            "detail": "No answer yet; call desktop_request_host again with the same "
            "reason to keep waiting.",
            "browser": person_browser(),
        }
    path.unlink(missing_ok=True)
    if answer == "expired":
        raise DesktopError("No answer from the person; the screen was not shared")
    if answer != "approved":
        raise DesktopError("The person declined; do not use their screen")
    return {
        **create("host", _host_minutes=pending["minutes"]),
        "approved": True,
        "browser": person_browser(),
    }


def answer_host(approve, minutes=None):
    """Answer a pending request; approving with none pending starts a session."""
    path = state_root() / HOST_REQUEST
    try:
        pending = json.loads(path.read_text())
    except (OSError, ValueError):
        pending = None
    if pending:
        pending["answer"] = "approved" if approve else "declined"
        path.write_text(json.dumps(pending))
        return {"request": pending["id"], "answer": pending["answer"]}
    if not approve:
        return {"request": None, "answer": "nothing pending"}
    return create("host", _host_minutes=host_minutes(minutes or 15))


def stop_host():
    """End the host session (and decline any pending request)."""
    answer_host(False)
    running = active_host_session()
    if not running:
        return {"stopped": None}
    return {"stopped": running, **destroy(running)}


def trace(session, limit=50):
    """The newest action-trace records (oldest first); readable after a crash."""
    path = session_path(session) / "trace.jsonl"
    if not 0 < limit <= 1000:
        raise DesktopError("Limit must be between 1 and 1000")
    if not path.exists():
        return {"session": session, "records": []}
    lines = path.read_text(errors="replace").splitlines()[-limit:]
    records = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return {"session": session, "records": records}


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
    expected = host_runtime_dir() / "agent-desktop" / session
    if runtime.resolve() != expected.resolve():
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

# wait(state=...): a listed state, or the absence of its opposite.
STATE_TESTS = {
    "checked": ("checked", True),
    "unchecked": ("checked", False),
    "enabled": ("disabled", False),
    "disabled": ("disabled", True),
    "focused": ("focused", True),
    "selected": ("selected", True),
    "expanded": ("expanded", True),
    "collapsed": ("expanded", False),
    "editable": ("editable", True),
    "pressed": ("pressed", True),
    "busy": ("busy", True),
    "idle": ("busy", False),
}


def node_matches(node, element=None, role=None, text=None, state=None, exact=False):
    """Whether a UI node has this name (substring, or whole with `exact`),
    exact role, text or value substring and state."""
    content = str(node.get("text") or "") + str(node.get("value") or "")
    if state is not None:
        listed, present = STATE_TESTS[state]
        if (listed in node.get("states", ())) != present:
            return False
    return (
        (
            element is None
            or (element == node["name"] if exact else element in node["name"])
        )
        and (role is None or node["role"] == role)
        and (text is None or text in content)
    )


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
    controller=None,
    state=None,
    exact=False,
    file=None,
    contains=None,
    key=None,
    value=None,
):
    """Wait until every condition holds at the same time.

    Conditions: a window (title substring and/or exact app_id), a UI element
    (accessible name substring, or the whole name with `exact`; exact role;
    text or value substring; a `state` such as checked, unchecked, enabled,
    disabled, focused, selected, expanded or collapsed; searched within the
    matched windows when a title or app_id is given) and a settled
    screen. `gone` applies to the window condition, or to the element condition
    when no window condition is given; an incomplete tree never counts as gone.
    `seconds` pauses first; `timeout` counts from the end of the pause.

    Changes covering at most QUIET_AREA square pixels, such as a blinking caret,
    count as settled.

    Effect conditions read the session's files directly: `file` ("~/..." in
    the session home, or absolute) exists, contains `contains`, and in an
    INI-style file (GSettings keyfile, .conf, .ini) `key` ("section/key")
    equals `value`. They need no screenshot or UI tree.
    """
    if not isinstance(timeout, (int, float)) or not 0 <= timeout <= 120:
        raise DesktopError("Timeout must be between 0 and 120 seconds")
    if not isinstance(stable_ms, int) or not 0 <= stable_ms <= 30000:
        raise DesktopError("stable_ms must be an integer from 0 to 30000")
    if not isinstance(seconds, (int, float)) or not 0 <= seconds <= 30:
        raise DesktopError("seconds must be between 0 and 30")
    if state is not None and state not in STATE_TESTS:
        raise DesktopError(f"state must be one of {', '.join(STATE_TESTS)}")
    # Every wait addresses an existing, controllable session, even a plain pause.
    # Its requests renew the caller's lease, so a long wait keeps control.
    request(session, "control", controller)
    started = time.monotonic()
    # A plain pause first, for changes no condition can describe.
    time.sleep(seconds)
    deadline = time.monotonic() + timeout
    wants_window = title is not None or app_id is not None
    if (contains is not None or key is not None) and file is None:
        raise DesktopError("contains and key need a file")
    if (key is None) != (value is None):
        raise DesktopError("key and value go together")
    target = None
    if file is not None:
        if not isinstance(file, str) or not file.startswith(("~/", "/")):
            raise DesktopError('file starts with "~/" (the session home) or "/"')
        target = (
            session_path(session) / "home" / file[2:]
            if file.startswith("~/")
            else Path(file)
        )
    wants_element = any(v is not None for v in (element, role, text, state))
    element_gone = gone and not wants_window

    def element_matches(node):
        return node_matches(node, element, role, text, state, exact)

    def check():
        """(satisfied, reason, windows, elements) from one round of checks
        (separate requests, so not an atomic snapshot)."""
        windows, elements = [], []
        if target is not None:
            reason = file_condition(target, contains, key, value)
            if reason:
                return False, reason, windows, elements
        if wants_window:
            windows = [
                w
                for w in request(session, "windows", controller)["windows"]
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
            # The element must belong to a matched window, not any application.
            if gone:
                scopes = [None]
            elif title is not None:
                scopes = [title]
            elif app_id is not None:
                scopes = list(dict.fromkeys(w["title"] for w in windows))
            else:
                scopes = [None]
            truncated = unreadable = False
            for scope in scopes:
                tree = request(
                    session,
                    "ui",
                    controller,
                    max_nodes=2000,
                    **({"window": scope} if scope is not None else {}),
                )
                elements += [n for n in tree["nodes"] if element_matches(n)]
                truncated = truncated or tree["truncated"]
                unreadable = unreadable or bool(tree.get("unreadable"))
            if element_gone and elements:
                return False, "element still present", windows, elements
            if element_gone and truncated:
                return False, "element unknown: tree truncated", windows, elements
            if element_gone and unreadable:
                return (
                    False,
                    "element unknown: part of the UI could not be read",
                    windows,
                    elements,
                )
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
            frame = request(session, "frame", controller)["frame"]
            while time.monotonic() - quiet_since < stable_ms / 1000:
                if time.monotonic() >= deadline:
                    return result(False, "screen still changing", windows, elements)
                time.sleep(0.05)
                latest = request(session, "frame", controller, since=frame)
                frame, box = latest["frame"], latest["changed"]
                if box == "unknown" or (box and box[2] * box[3] > QUIET_AREA):
                    quiet_since = time.monotonic()
            # The conditions must still hold once the screen has settled.
            satisfied, reason, windows, elements = check()
        if satisfied:
            return result(True, "ok", windows, elements)
        if time.monotonic() >= deadline:
            failed = result(False, reason, windows, elements)
            if reason == "no window":
                # Distinguish a wrong title or app_id from a window not yet open.
                failed["open_windows"] = [
                    {"title": w["title"], "app_id": w["app_id"]}
                    for w in request(session, "windows", controller)["windows"]
                ]
            return failed
        time.sleep(0.2 if wants_element else 0.05)


# A ui_action step's own "text" is what set_text writes, so targets have no text.
TARGET_KEYS = ("element", "role", "state", "exact", "window", "app")
EXPECT_KEYS = (
    "title",
    "app_id",
    "gone",
    "element",
    "role",
    "text",
    "state",
    "exact",
    "timeout",
    "stable_ms",
    "file",
    "contains",
    "key",
    "value",
)


def ui_complete(tree):
    """Only explicit, well-formed coverage establishes a complete visible read."""
    return (
        tree.get("truncated") is False
        and type(tree.get("unreadable")) is int
        and tree["unreadable"] == 0
    )


def resolve_element(
    session,
    controller,
    element=None,
    role=None,
    text=None,
    state=None,
    exact=False,
    window=None,
    app=None,
):
    """The id of the one visible UI node that matches, looked up now.

    A name matches as a substring unless `exact`; when several nodes match but
    exactly one has the whole name, that one is chosen. No match, several
    matches or an incomplete listing raise DesktopError (nothing is acted on).
    """
    if element is None and role is None and text is None:
        raise DesktopError("A target needs element, role or text")
    if state is not None and state not in STATE_TESTS:
        raise DesktopError(f"state must be one of {', '.join(STATE_TESTS)}")
    scope = {k: v for k, v in (("window", window), ("app", app)) if v is not None}
    tree = request(session, "ui", controller, max_nodes=2000, **scope)
    if not ui_complete(tree):
        raise DesktopError(
            "The UI listing was incomplete; uniqueness is unknown. "
            "Filter by app or window and read again before acting."
        )
    found = [
        n for n in tree["nodes"] if node_matches(n, element, role, text, state, exact)
    ]
    if len(found) > 1 and element is not None and not exact:
        whole = [n for n in found if n["name"] == element]
        if len(whole) == 1:
            found = whole
    described = f"{element!r}" if element is not None else "the target"
    if not found:
        raise DesktopError(f"No visible element matches {described}")
    if len(found) > 1:
        sample = "; ".join(f"{n['role']} {n['name']!r}" for n in found[:4])
        raise DesktopError(
            f"{len(found)} elements match {described} ({sample}); add role, "
            "window or exact to pick one"
        )
    return found[0]["id"]


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


def run_actions(session, actions, observation=None, controller=None, timeout=None):
    """Run up to 50 actions, stopping at the first surprise.

    Each input action is sent only if windows, focus and output are as they were
    right after the previous action (or as in `observation` for the first). A
    `wait` or `focus` step expects a change and takes a new baseline.

    Any step can carry `expect`, wait conditions (title, app_id, gone, element,
    role, text, state, exact, timeout default 5 s, stable_ms, file, contains,
    key, value) that must hold after it; otherwise the run stops there, reporting the step as done and the
    expectation as unmet. A `ui_action` step can name its target by element,
    role, state, exact, window or app instead of a node id; it is looked
    up when the step runs and must match exactly one element. `timeout` bounds
    the whole run: no step starts after it.

    The sequence holds the session's controller lease throughout, so another
    client cannot interleave input: the caller's lease when a controller is
    given (kept afterwards), otherwise a temporary one released at the end.
    Steps are never retried. A step whose request got no reply is reported
    with "uncertain": true; it may or may not have been delivered.
    """
    if not isinstance(actions, list) or not 1 <= len(actions) <= 50:
        raise DesktopError("Actions must be a list of 1 to 50 steps")
    for index, step in enumerate(actions):
        if not isinstance(step, dict) or step.get("action") not in SEQUENCE_ACTIONS:
            raise DesktopError(
                f"Step {index} needs an action: {', '.join(SEQUENCE_ACTIONS)}"
            )
        if {"observation", "session", "controller"} & step.keys():
            raise DesktopError(
                f"Step {index} must not set observation, session or controller"
            )
        expect = step.get("expect")
        if expect is not None and (
            not isinstance(expect, dict) or not expect or set(expect) - set(EXPECT_KEYS)
        ):
            raise DesktopError(f"Step {index}: expect takes {', '.join(EXPECT_KEYS)}")
    if timeout is not None and (
        not isinstance(timeout, (int, float)) or not 0 < timeout <= 600
    ):
        raise DesktopError("timeout must be between 0 and 600 seconds")
    controller = controller_id(controller)
    temporary = controller is None
    if temporary:
        controller = f"sequence-{uuid.uuid4().hex[:12]}"
    try:
        request(session, "lease", controller)
    except DesktopError as error:
        return stopped(0, len(actions), str(error))
    first = []  # effect_id of the first step, when the ledger is on
    try:
        result = run_steps(session, actions, observation, controller, first, timeout)
        if first:
            # Everything the sequence changed, including writes after its last
            # step's reply (experimental effect ledger).
            try:
                result["effects"] = request(
                    session, "effects", controller, effect_id=first[0]
                )
            except DesktopError as error:
                result["effects_error"] = str(error)
        return result
    finally:
        if temporary:
            try:
                request(session, "lease", controller, action="release")
            except DesktopError:
                pass  # e.g. the session was destroyed; the lease went with it


def run_steps(
    session,
    actions,
    observation,
    controller,
    first=None,
    timeout=None,
    progress=None,
    cancelled=None,
):
    def report(index, state, result=None):
        if progress is not None:
            progress(index, state, result)

    def cancellation(index):
        if cancelled is not None and cancelled():
            result = stopped(
                index, len(actions), "Cancellation requested before dispatch"
            )
            result["stopped"]["cancelled"] = True
            return result
        return None

    started = time.monotonic()
    baseline = observation or request(session, "observe", controller)["observation"]
    # Keep a cropped or scaled screenshot's coordinate mapping for every step.
    mapping = "@" + observation.partition("@")[2] if "@" in (observation or "") else ""
    for index, step in enumerate(actions):
        if result := cancellation(index):
            return result
        if timeout is not None and time.monotonic() - started > timeout:
            return stopped(index, len(actions), f"run timeout ({timeout} s) reached")
        arguments = {k: v for k, v in step.items() if k not in ("action", "expect")}
        action = step["action"]
        if action == "ui_action" and "name" in arguments:
            # "action" names the step, so a UI action's own name travels as "name".
            arguments["action"] = arguments.pop("name")
        try:
            if action == "ui_action" and "node" not in arguments:
                target = {k: arguments.pop(k) for k in TARGET_KEYS if k in arguments}
                arguments["node"] = resolve_element(session, controller, **target)
            if result := cancellation(index):
                return result
            report(index, "dispatching")
            if action == "wait":
                waited = wait(session, **arguments, controller=controller)
                report(index, "acknowledged", waited)
                if not waited["satisfied"]:
                    return stopped(index, len(actions), f"wait: {waited['reason']}")
            elif action == "focus":
                reply = request(session, "focus", controller, **arguments)
            else:
                reply = request(
                    session, action, controller, observation=baseline, **arguments
                )
            if action != "wait":
                report(index, "acknowledged", reply)
            if (
                first is not None
                and not first
                and action != "wait"
                and isinstance(reply, dict)
                and "effects" in reply
            ):
                first.append(reply["effects"]["effect_id"])
        except DeliveryUnknown as error:
            # Never retried: input such as typing or submitting may not be
            # idempotent. Report the step so the caller can check the desktop.
            result = stopped(index, len(actions), str(error))
            result["stopped"]["uncertain"] = True
            report(index, "uncertain", {"reason": str(error)})
            return result
        except DesktopError as error:
            report(index, "failed", {"reason": str(error)})
            return stopped(index, len(actions), str(error))
        except TypeError as error:
            report(index, "failed", {"reason": str(error)})
            hint = (
                "; wait accepts title, app_id, gone, stable_ms, timeout, element, "
                "role, text, state, exact, seconds, file, contains, key and value"
                if action == "wait"
                else ""
            )
            return stopped(index, len(actions), f"{error}{hint}")
        if step.get("expect"):
            try:
                expected = wait(
                    session, **{"timeout": 5, **step["expect"]}, controller=controller
                )
            except (DesktopError, TypeError) as error:
                expected = {"satisfied": False, "reason": str(error)}
            if not expected["satisfied"]:
                result = stopped(
                    index + 1,
                    len(actions),
                    f"step {index} ran, but its expectation was not met: "
                    f"{expected['reason']}",
                )
                result["stopped"]["step"] = index
                result["stopped"]["expectation"] = True
                return result
        try:
            baseline = request(session, "observe", controller)["observation"] + mapping
            report(index, "observed", {"observation": baseline})
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
        reason = tree.get("truncated_by") or "limit reached"
        lines.append(
            f"… truncated ({reason}): filter by app or window, or raise max_nodes"
        )
    if tree.get("unreadable"):
        lines.append(
            f"… incomplete: {tree['unreadable']} unreadable UI subtree(s); "
            "absence and uniqueness are unknown"
        )
    return "\n".join(lines) or "(no accessible elements)"


def setting(raw):
    """A keyfile value without GVariant type prefixes or string quotes."""
    raw = str(raw).strip()
    for prefix in ("uint32 ", "int32 ", "uint64 ", "int64 ", "byte ", "double "):
        raw = raw.removeprefix(prefix)
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        raw = raw[1:-1]
    return raw


def file_condition(path, contains, key, value):
    """None when the file condition holds, else the reason it does not."""
    from .effects import ini_values

    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                return f"{path.name} is not a regular file"
            data = stream.read(FILE_READ_LIMIT + 1)
            after = os.fstat(stream.fileno())
        if len(data) > FILE_READ_LIMIT:
            return f"{path.name} exceeds the {FILE_READ_LIMIT}-byte file read limit"

        def version(info):
            return (
                info.st_dev,
                info.st_ino,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
            )

        if version(before) != version(after) or version(after) != version(path.stat()):
            return f"{path.name} changed during the file read"
        text = data.decode("utf-8")
    except FileNotFoundError:
        return f"no file {path.name}"
    except UnicodeDecodeError:
        return f"{path.name} is not valid UTF-8; content condition unavailable"
    except OSError:
        return f"{path.name} could not be read; content condition unavailable"
    if contains is not None and str(contains) not in text:
        return f"{path.name} does not contain {str(contains)[:60]!r}"
    if key is not None:
        values = ini_values(text) or {}
        if key not in values:
            return f"{path.name} has no key {key}"
        if setting(values[key]) != setting(value):
            return f"{path.name} {key} is {values[key]}, not {value}"
    return None


def wait_effect(session, effect_id, path, timeout=10, controller=None):
    """Wait until a file matching `path` ("~/..." glob) has been written since
    the action `effect_id` and has gone quiet; return that action's effects.

    Experimental (AGENT_DESKTOP_EFFECTS=1). Returns satisfied=false at the
    timeout with the effects observed so far.
    """
    if not isinstance(timeout, (int, float)) or not 0 <= timeout <= 120:
        raise DesktopError("Timeout must be between 0 and 120 seconds")
    deadline = time.monotonic() + timeout
    while True:
        found = request(
            session, "effects", controller, effect_id=effect_id, match=path
        )["matched"]
        if found or time.monotonic() >= deadline:
            effects = request(session, "effects", controller, effect_id=effect_id)
            return {"satisfied": found, "effects": effects}
        time.sleep(0.1)


def wait_for_agent_control(session, timeout, controller=None):
    """Wait until no person holds or has been asked to take the session."""
    deadline = time.monotonic() + max(0, min(timeout, 600))
    while True:
        state = request(session, "control", controller)
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
