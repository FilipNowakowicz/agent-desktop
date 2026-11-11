"""Events for desktop shells and notifiers (docs/project/EVENT_CONTRACT.md).

Everything is derived from state the runtime already writes: each session's
session.json, the host request file, operation records and action traces. No
content leaves: no typed or page text, titles, URLs or arguments. The only free
text is an agent's reason, which is written for the person, and an error's
first line.
"""

import json
import sys
import time
from pathlib import Path

from . import core, printed

TERMINAL = {"completed", "stopped", "cancelled", "delivery_unknown"}
SESSION_EVENTS = {
    "starting": "session_started",
    "ready": "session_ready",
    "stopped": "session_stopped",
    "failed": "session_failed",
}


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def first_line(text):
    return str(text).strip().splitlines()[0][:300] if text else None


def state(session=None, offsets=None):
    """The persisted state events are derived from, plus new trace outcomes.

    `offsets` maps trace paths to the byte offset already read; it is updated.
    """
    root = core.state_root()
    paths = (
        [root / session / "session.json"]
        if session
        else sorted(root.glob("*/session.json"))
    )
    sessions, operations, outcomes = {}, {}, []
    for path in paths:
        info = read_json(path)
        if not isinstance(info, dict) or not isinstance(info.get("id"), str):
            continue
        control = info.get("control") or {}
        sessions[info["id"]] = {
            "status": info.get("status"),
            "mode": info.get("mode"),
            "profile": info.get("profile"),
            "error": first_line(info.get("error")),
            "owner": control.get("owner", "agent"),
            "request": control.get("request"),
            "last": control.get("last"),
        }
        for record_path in sorted((path.parent / "operations").glob("*.json")):
            record = read_json(record_path)
            if isinstance(record, dict) and isinstance(record.get("operation_id"), str):
                operations[(info["id"], record["operation_id"])] = {
                    "state": record.get("state"),
                    "completed": record.get("completed"),
                    "total": record.get("total"),
                }
        if offsets is not None:
            outcomes += trace_outcomes(info["id"], path.parent / "trace.jsonl", offsets)
    host = read_json(root / core.HOST_REQUEST)
    return {
        "sessions": sessions,
        "operations": operations,
        "host": host if isinstance(host, dict) else None,
        "outcomes": outcomes,
    }


def trace_outcomes(session, path, offsets):
    """Uncertain steps and stopped batches recorded since the last read."""
    try:
        size = path.stat().st_size
    except OSError:
        return []
    start = offsets.get(str(path))
    if start is None or start > size:  # first look, or the trace was trimmed
        offsets[str(path)] = size
        return []
    with path.open("rb") as stream:
        stream.seek(start)
        data = stream.read()
    complete = data.rfind(b"\n") + 1
    offsets[str(path)] = start + complete
    events = []
    for line in data[:complete].splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        outcome = record.get("outcome") or {}
        base = {
            "at": record.get("at"),
            "session": session,
            "operation": record.get("operation"),
        }
        if isinstance(outcome.get("stopped"), str):
            events.append(
                {**base, "event": "batch_stopped", "reason": outcome["stopped"]}
            )
        elif outcome.get("uncertain") or (
            "delivered" in outcome and outcome["delivered"] is None
        ):
            events.append({**base, "event": "step_uncertain"})
    return events


def human_commands(session):
    return {
        "take_command": printed.command("take", session),
        "paste_command": printed.command("take", "--paste", session),
    }


def changes(before, after):
    """Events that turn `before` into `after` (`before` may be empty)."""
    now = round(time.time(), 3)
    events = []

    def emit(event, **fields):
        events.append({"at": now, "event": event, **fields})

    old_sessions = before.get("sessions", {})
    for ident, current in after["sessions"].items():
        old = old_sessions.get(ident, {})
        if (
            current["status"] != old.get("status")
            and current["status"] in SESSION_EVENTS
        ):
            fields = {"mode": current["mode"], "profile": current["profile"]}
            if current["status"] == "failed":
                fields["error"] = current["error"]
            emit(SESSION_EVENTS[current["status"]], session=ident, **fields)
        request, old_request = current["request"], old.get("request")
        if request and request != old_request:
            emit(
                "human_requested",
                session=ident,
                reason=request.get("reason"),
                login=bool(request.get("login")),
                **human_commands(ident),
            )
        if old_request and not request and current["owner"] == "agent":
            if old.get("owner") != "human":
                emit("human_withdrawn", session=ident)
        if current["owner"] == "human" and old.get("owner") != "human":
            emit("control_taken", session=ident)
        if current["owner"] == "agent" and old.get("owner") == "human":
            last = current.get("last") or {}
            emit(
                "control_returned",
                session=ident,
                how=last.get("how"),
                **({"browser": last["browser"]} if last.get("browser") else {}),
            )
    old_operations = before.get("operations", {})
    for (ident, operation), current in after["operations"].items():
        old_state = (old_operations.get((ident, operation)) or {}).get("state")
        if current["state"] in TERMINAL and current["state"] != old_state:
            emit(
                "operation_finished",
                session=ident,
                operation=operation,
                state=current["state"],
                completed=current["completed"],
                total=current["total"],
            )
    host, old_host = after["host"], before.get("host")
    if host and isinstance(host.get("id"), str):
        same = old_host and old_host.get("id") == host["id"]
        expired = not host.get("answer") and time.time() > host.get("expires", 0)
        if not same and not host.get("answer") and not expired:
            emit(
                "host_requested",
                request=host["id"],
                reason=host.get("reason"),
                minutes=host.get("minutes"),
                approve_command=printed.command("host", "approve"),
                deny_command=printed.command("host", "deny"),
            )
        if host.get("answer") and (not same or not old_host.get("answer")):
            emit("host_answered", request=host["id"], answer=host["answer"])
        was_expired = (
            same and not old_host.get("answer") and old_host.get("_expired", False)
        )
        if expired and not was_expired:
            emit("host_expired", request=host["id"])
        host["_expired"] = expired
    events += after.get("outcomes", [])
    return events


def follow(session=None, interval=0.5, out=sys.stdout, until=None):
    """Print the current state as events, then changes as they happen."""
    offsets = {}
    previous = {}
    while True:
        current = state(session, offsets)
        for event in changes(previous, current):
            out.write(json.dumps(event) + "\n")
        out.flush()
        previous = current
        if until is not None and until():
            return
        time.sleep(interval)


def snapshot(session=None):
    """The current state as events, once."""
    return changes({}, state(session))
