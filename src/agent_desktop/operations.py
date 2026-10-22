"""Durable private-session jobs. Submission never means delivery or success.

Jobs send ordinary guarded worker requests. Status and cooperative cancellation
use local files so they remain available while the synchronous worker is busy.
There is deliberately no retry or resume API.
"""

import fcntl
import json
import math
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

from . import core
from .worker import start_time

MAX_RECORDS = 32
MAX_BYTES = 524288
MAX_ACTION_BYTES = 65536
TERMINAL = {"completed", "stopped", "cancelled", "delivery_unknown"}
STATES = TERMINAL | {"submitted", "running"}
DISPATCH = {"pending", "dispatching", "acknowledged", "observed", "failed", "uncertain"}
_children = {}


def directory(session):
    root = core.session_path(session) / "operations"
    root.mkdir(mode=0o700, exist_ok=True)
    if root.is_symlink():
        raise core.DesktopError("Invalid operation directory")
    return root


def record_path(session, operation_id):
    if not isinstance(operation_id, str) or not re.fullmatch(
        r"[a-f0-9]{32}", operation_id
    ):
        raise core.DesktopError("Invalid operation identifier")
    return directory(session) / f"{operation_id}.json"


def save(path, record):
    record["updated_at"] = time.time()
    data = json.dumps(record, allow_nan=False).encode()
    if len(data) > MAX_BYTES:
        raise core.DesktopError("Operation evidence exceeds the retention bound")
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    with open(temporary, "wb", opener=lambda p, f: os.open(p, f, 0o600)) as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def load(path, session, operation_id):
    try:
        if path.is_symlink():
            raise ValueError("symlink")
        with path.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("oversized record")
        record = json.loads(data)
        steps = record["steps"]
        valid = (
            record["schema_version"] == 1
            and record["session"] == session
            and record["operation_id"] == operation_id
            and record["state"] in STATES
            and record["kind"] in ("actions", "browser")
            and type(record["completed"]) is int
            and type(record["total"]) is int
            and 0 <= record["completed"] <= record["total"] <= 50
            and record["total"] >= 1
            and isinstance(steps, list)
            and len(steps) == record["total"]
            and isinstance(record["checks"], list)
            and len(record["checks"]) <= 50
            and type(record["created_at"]) in (int, float)
            and math.isfinite(record["created_at"])
            and type(record["updated_at"]) in (int, float)
            and math.isfinite(record["updated_at"])
            and isinstance(record["controller"], str)
            and type(record["release_lease"]) is bool
            and type(record["timeout"]) in (int, float)
            and 0 < record["timeout"] <= 600
            and (
                record["observation"] is None or isinstance(record["observation"], str)
            )
            and (
                record["current_step"] is None
                or type(record["current_step"]) is int
                and 0 <= record["current_step"] < record["total"]
            )
        )
        for index, step in enumerate(steps):
            valid = valid and (
                isinstance(step, dict)
                and step["index"] == index
                and isinstance(step["request"], dict)
                and step["dispatch_state"] in DISPATCH
                and ("result" not in step or isinstance(step["result"], dict))
                and (
                    step["dispatch_state"] not in ("acknowledged", "observed")
                    or isinstance(step.get("result"), dict)
                )
            )
            if isinstance(step.get("result"), dict):
                result = step["result"]
                valid = valid and (
                    (
                        "delivered" not in result
                        or result["delivered"] is None
                        or type(result["delivered"]) is bool
                    )
                    and ("uncertain" not in result or type(result["uncertain"]) is bool)
                )
        if record["state"] == "completed":
            valid = (
                valid
                and record["completed"] == record["total"]
                and all(
                    s["dispatch_state"] in ("acknowledged", "observed")
                    and isinstance(s.get("result"), dict)
                    and not s["result"].get("uncertain")
                    and (
                        "delivered" not in s["result"]
                        or s["result"]["delivered"] is True
                    )
                    and not s["result"].get("observation_error")
                    and (
                        s["request"].get("action") != "wait"
                        or s["result"].get("satisfied") is True
                    )
                    for s in steps
                )
            )
            valid = (
                valid
                and isinstance(record.get("result"), dict)
                and record["result"].get("stopped") is None
            )
        if record["state"] == "cancelled":
            valid = valid and all(
                s["dispatch_state"] not in ("dispatching", "uncertain") for s in steps
            )
        if not valid:
            raise ValueError("invalid evidence")
        return record
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        IndexError,
    ) as error:
        raise core.DesktopError(
            "Operation evidence unavailable or invalid; delivery is unknown. Do not resubmit blindly."
        ) from error


def process_alive(pid, started):
    if type(pid) is not int or type(started) is not int:
        return False
    try:
        raw = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return raw[0] not in ("Z", "X") and start_time(pid) == started
    except (OSError, IndexError):
        return False


def reap():
    for ident, child in list(_children.items()):
        if child.poll() is not None:
            del _children[ident]


def status(session, operation_id):
    reap()
    path = record_path(session, operation_id)
    record = load(path, session, operation_id)
    if record["state"] not in TERMINAL:
        alive = process_alive(record.get("pid"), record.get("process_start"))
        # A submitter killed between spawn and the start gate cannot dispatch.
        # Keep a brief publication grace so readers do not race that handshake.
        if not alive and time.time() - record["created_at"] > 3:
            dispatched = any(s["dispatch_state"] != "pending" for s in record["steps"])
            record["state"] = "delivery_unknown" if dispatched else "stopped"
            record["reason"] = (
                "Operation process exited; reconcile its recorded delivery before retrying"
                if dispatched
                else "Operation process exited before any recorded dispatch"
            )
            for step in record["steps"]:
                if step["dispatch_state"] == "dispatching":
                    step["dispatch_state"] = "uncertain"
            save(path, record)
    record["cancel_requested"] = path.with_suffix(".cancel").exists()
    return record


def list_operations(session):
    paths = sorted(directory(session).glob("*.json"), key=lambda p: p.stat().st_mtime)
    if len(paths) > MAX_RECORDS:
        raise core.DesktopError("Operation retention exceeded; inspect session state")
    keys = (
        "operation_id",
        "session",
        "kind",
        "state",
        "completed",
        "total",
        "current_step",
        "created_at",
        "updated_at",
        "cancel_requested",
    )
    return [
        {k: r[k] for k in keys if k in r}
        for path in paths
        for r in [status(session, path.stem)]
    ]


def validate_actions(actions, kind):
    if kind not in ("actions", "browser"):
        raise core.DesktopError("kind must be actions or browser")
    limit = 30 if kind == "browser" else 50
    if not isinstance(actions, list) or not 1 <= len(actions) <= limit:
        raise core.DesktopError(f"actions must contain 1 to {limit} steps")
    allowed = (
        core.SEQUENCE_ACTIONS
        if kind == "actions"
        else (
            "start",
            "tabs",
            "open",
            "close",
            "find",
            "text",
            "wait",
            "click",
            "fill",
            "select",
        )
    )
    for index, step in enumerate(actions):
        if not isinstance(step, dict) or step.get("action") not in allowed:
            raise core.DesktopError(f"Invalid action in step {index}")
        if {"session", "controller", "deadline", "observation"} & step.keys():
            raise core.DesktopError(
                f"Step {index} cannot override session, controller, deadline or observation"
            )
        if kind == "actions" and "expect" in step:
            expect = step["expect"]
            if (
                not isinstance(expect, dict)
                or not expect
                or set(expect) - set(core.EXPECT_KEYS)
            ):
                raise core.DesktopError(f"Invalid expectation in step {index}")
    try:
        size = len(json.dumps(actions, allow_nan=False).encode())
    except (ValueError, TypeError) as error:
        raise core.DesktopError("Actions must be finite JSON data") from error
    if size > MAX_ACTION_BYTES:
        raise core.DesktopError("Operation actions exceed 64 KiB")


def start(
    session, actions, kind="actions", observation=None, controller=None, timeout=600
):
    validate_actions(actions, kind)
    if (
        type(timeout) not in (int, float)
        or not math.isfinite(timeout)
        or not 0 < timeout <= 600
    ):
        raise core.DesktopError("timeout must be between 0 and 600 seconds")
    if observation is not None and (
        not isinstance(observation, str) or len(observation) > 512
    ):
        raise core.DesktopError("Invalid observation token")
    info = core.manifest(session)
    if info.get("mode") not in ("headless", "visible") or info.get("status") != "ready":
        raise core.DesktopError(
            "Operations require a ready private session; host sessions are unsupported"
        )
    controller = core.controller_id(controller)
    if controller is not None and (
        not isinstance(controller, str)
        or not re.fullmatch(r"[A-Za-z0-9._:@-]{1,64}", controller)
    ):
        raise core.DesktopError("Invalid controller identifier")
    operation_id = uuid.uuid4().hex
    root = directory(session)
    with (root / "submit.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        records = list_operations(session)
        if any(r["state"] not in TERMINAL for r in records):
            raise core.DesktopError(
                "A session operation is already active; inspect or cancel it"
            )
        while len(records) >= MAX_RECORDS:
            old = records.pop(0)
            old_path = record_path(session, old["operation_id"])
            for suffix in (".json", ".cancel", ".ready"):
                old_path.with_suffix(suffix).unlink(missing_ok=True)
        path = record_path(session, operation_id)
        record = {
            "schema_version": 1,
            "operation_id": operation_id,
            "session": session,
            "kind": kind,
            "state": "submitted",
            "created_at": time.time(),
            "completed": 0,
            "total": len(actions),
            "current_step": None,
            "steps": [
                {"index": i, "request": step, "dispatch_state": "pending"}
                for i, step in enumerate(actions)
            ],
            "checks": [],
            "observation": observation,
            "timeout": timeout,
            "controller": controller or f"op-{operation_id}",
            "release_lease": controller is None,
            "recovery": "Inspect status and observed application state before repeating input; no automatic retry or resume.",
        }
        save(path, record)
        env = {**os.environ, "AGENT_DESKTOP_SESSION_TOKEN": info["token"]}
        try:
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "agent_desktop.operations",
                    str(core.session_path(session)),
                    operation_id,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                start_new_session=True,
            )
            _children[operation_id] = child
            record.update(pid=child.pid, process_start=start_time(child.pid))
            save(path, record)
            path.with_suffix(".ready").touch(mode=0o600)
        except (OSError, core.DesktopError) as error:
            record.update(state="stopped", reason=f"Could not start operation: {error}")
            save(path, record)
        return record


def cancel(session, operation_id):
    record = status(session, operation_id)
    if record["state"] not in TERMINAL:
        record_path(session, operation_id).with_suffix(".cancel").touch(mode=0o600)
        record["cancel_requested"] = True
    return record


def operate(
    session,
    action="status",
    operation_id=None,
    actions=None,
    kind="actions",
    observation=None,
    controller=None,
    timeout=600,
):
    if action == "start":
        return start(session, actions, kind, observation, controller, timeout)
    if action == "status":
        return (
            status(session, operation_id)
            if operation_id is not None
            else {"operations": list_operations(session)}
        )
    if action == "cancel":
        return cancel(session, operation_id)
    raise core.DesktopError("operation action must be start, status or cancel")


def bounded_result(result):
    if not isinstance(result, dict):
        raise core.DeliveryUnknown("Worker returned malformed step evidence")
    data = json.dumps(result, allow_nan=False)
    if len(data.encode()) <= 4096:
        return result
    # Keep delivery fields and a bounded provenance marker, never imply full coverage.
    return {
        **{
            k: result[k]
            for k in ("delivered", "uncertain", "observation", "context", "satisfied")
            if k in result
        },
        **{
            k: str(result[k])[:512]
            for k in ("error", "observation_error", "effects_error")
            if k in result
        },
        "evidence_truncated": True,
        "reason": "Step evidence exceeded 4096 bytes; inspect the application for full state",
    }


def run_job(session, operation_id):
    path = record_path(session, operation_id)
    deadline = time.monotonic() + 2
    while not path.with_suffix(".ready").exists():
        if time.monotonic() >= deadline:
            return
        time.sleep(0.02)
    record = load(path, session, operation_id)
    if record["state"] in TERMINAL:
        return
    record["state"] = "running"
    save(path, record)

    def cancelled():
        return path.with_suffix(".cancel").exists()

    def progress(index, phase, result=None):
        record["current_step"] = index
        step = record["steps"][index]
        if phase == "failed" and step["dispatch_state"] == "dispatching":
            # A generic worker error is not a transaction rollback: input may
            # have partially run before the error reply. Pre-dispatch target
            # resolution failures still have a pending state and remain known.
            phase = "uncertain"
        step["dispatch_state"] = phase
        if result is not None:
            if phase == "observed":
                step["observation"] = result.get("observation")
            else:
                step["result"] = bounded_result(result)
        if phase in ("acknowledged", "observed"):
            record["completed"] = max(record["completed"], index + 1)
        save(path, record)

    controller = record["controller"]
    acquired = False
    lease_seconds = None
    try:
        if cancelled():
            record.update(state="cancelled", reason="Cancelled before any dispatch")
            return
        # The helper never holds the submission API open while waiting on worker
        # serialization. A failed lease sends no action.
        lease_reply = core.request(session, "lease", controller)
        acquired = True
        lease_seconds = lease_reply.get("lease", {}).get("seconds", 60)
        # A wait can exceed the ordinary inactivity lease. Keep exclusive
        # ownership through the bounded job, then restore the named caller's
        # duration (anonymous jobs release their temporary lease).
        core.request(session, "lease", controller, seconds=3600)
        actions = [s["request"] for s in record["steps"]]
        if record["kind"] == "actions":
            result = core.run_steps(
                session,
                actions,
                record["observation"],
                controller,
                timeout=record["timeout"],
                progress=progress,
                cancelled=cancelled,
            )
        else:
            result = run_browser(
                session, actions, controller, record["timeout"], progress, cancelled
            )
        record["result"] = {k: v for k, v in result.items() if k != "results"}
        record["completed"] = result["completed"]
        stopped = result.get("stopped")
        record["state"] = (
            "completed"
            if stopped is None
            else "delivery_unknown"
            if stopped.get("uncertain")
            or any(s["dispatch_state"] == "uncertain" for s in record["steps"])
            else "cancelled"
            if stopped.get("cancelled")
            else "stopped"
        )
    except core.DeliveryUnknown as error:
        record.update(state="delivery_unknown", reason=str(error))
    except core.DesktopError as error:
        in_flight = any(s["dispatch_state"] == "dispatching" for s in record["steps"])
        record.update(
            state="delivery_unknown" if in_flight else "stopped", reason=str(error)
        )
    except Exception as error:
        record.update(
            state="delivery_unknown",
            reason=f"Operation failed: {type(error).__name__}: {error}"[:1000],
        )
    finally:
        # Retain running status while releasing/restoring the lease, so a new
        # operation cannot race cleanup of its predecessor's temporary lease.
        record["cancel_requested"] = cancelled()
        if record["state"] == "delivery_unknown":
            for step in record["steps"]:
                if step["dispatch_state"] == "dispatching":
                    step["dispatch_state"] = "uncertain"
        if acquired:
            try:
                if record["release_lease"]:
                    core.request(session, "lease", controller, action="release")
                else:
                    core.request(session, "lease", controller, seconds=lease_seconds)
                record["lease_cleanup"] = "complete"
            except core.DesktopError as error:
                record["lease_cleanup"] = "unknown"
                record["lease_error"] = str(error)[:1000]
        save(path, record)


def run_browser(session, actions, controller, timeout, progress, cancelled):
    deadline = time.monotonic() + timeout
    for index, step in enumerate(actions):
        if cancelled():
            result = core.stopped(
                index, len(actions), "Cancellation requested before dispatch"
            )
            result["stopped"]["cancelled"] = True
            return result
        if time.monotonic() >= deadline:
            return core.stopped(
                index, len(actions), "Operation deadline reached before dispatch"
            )
        progress(index, "dispatching")
        try:
            reply = core.request(session, "browser", controller, **step)
        except core.DeliveryUnknown as error:
            progress(index, "uncertain", {"reason": str(error)})
            result = core.stopped(index, len(actions), str(error))
            result["stopped"]["uncertain"] = True
            return result
        except core.DesktopError as error:
            progress(index, "uncertain", {"reason": str(error)})
            result = core.stopped(index, len(actions), str(error))
            result["stopped"]["uncertain"] = True
            return result
        if reply.get("uncertain"):
            progress(index, "uncertain", reply)
            result = core.stopped(
                index, len(actions), reply.get("error", "Browser delivery unknown")
            )
            result["stopped"]["uncertain"] = True
            return result
        progress(index, "acknowledged", reply)
        if reply.get("observation_error") or (
            step["action"] == "wait" and not reply.get("satisfied")
        ):
            return core.stopped(
                index + 1,
                len(actions),
                reply.get("observation_error", "Browser wait not satisfied"),
            )
    return {"completed": len(actions), "total": len(actions), "stopped": None}


if __name__ == "__main__":
    session_root = Path(sys.argv[1]).resolve()
    os.environ["AGENT_DESKTOP_STATE_DIR"] = str(session_root.parent)
    run_job(session_root.name, sys.argv[2])
