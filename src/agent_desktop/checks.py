"""Scoped, read-only predicates. Unknown evidence never becomes a successful check."""

import configparser
import hashlib
import os
import stat
import time
from pathlib import Path

from . import core

READ_LIMIT = 2 * 1024 * 1024
QUERY_KEYS = {"element", "role", "text", "state", "exact", "window", "app"}


def validate(predicate):
    if not isinstance(predicate, dict):
        raise core.DesktopError("predicate must be an object")
    kind = predicate.get("kind")
    keys = {
        "file": {"kind", "path", "exists", "contains", "text", "sha256"},
        "config": {"kind", "path", "key", "value"},
        "ui": {"kind", "query", "claim", "field", "equals", "state"},
        "browser_context": {"kind", "context", "url"},
    }
    if not isinstance(kind, str) or kind not in keys or set(predicate) - keys[kind]:
        raise core.DesktopError("Unknown predicate kind or fields")
    if kind in ("file", "config"):
        path = predicate.get("path")
        if not isinstance(path, str) or not path.startswith(("~/", "/")):
            raise core.DesktopError('path starts with "~/" (session home) or "/"')
        if kind == "config":
            if not isinstance(predicate.get("key"), str) or "value" not in predicate:
                raise core.DesktopError("config needs key and value")
        else:
            if "exists" in predicate and type(predicate["exists"]) is not bool:
                raise core.DesktopError("exists must be boolean")
            for field in ("contains", "text", "sha256"):
                if field in predicate and not isinstance(predicate[field], str):
                    raise core.DesktopError(f"{field} must be text")
            if predicate.get("exists") is False and any(
                k in predicate for k in ("contains", "text", "sha256")
            ):
                raise core.DesktopError(
                    "absence cannot be combined with content checks"
                )
    elif kind == "ui":
        query = predicate.get("query", {})
        if not isinstance(query, dict) or set(query) - QUERY_KEYS:
            raise core.DesktopError("Unknown UI query fields")
        for key, value in query.items():
            if (key == "exact" and type(value) is not bool) or (
                key != "exact" and not isinstance(value, str)
            ):
                raise core.DesktopError(f"Invalid UI query field {key}")
        if query.get("state") is not None and query["state"] not in core.STATE_TESTS:
            raise core.DesktopError("Unknown UI query state")
        claim = predicate.get("claim", "exists")
        if claim not in ("exists", "absent", "unique", "value", "all"):
            raise core.DesktopError("Unknown UI claim")
        if claim == "value" and (
            predicate.get("field", "value") not in ("value", "text", "name")
            or "equals" not in predicate
        ):
            raise core.DesktopError("value needs equals and a value/text/name field")
        if claim == "all" and (
            predicate.get("state") not in core.STATE_TESTS or "state" in query
        ):
            raise core.DesktopError("all needs a known state outside the query")
        allowed = {"kind", "query", "claim"} | (
            {"field", "equals"}
            if claim == "value"
            else {"state"}
            if claim == "all"
            else set()
        )
        if set(predicate) - allowed:
            raise core.DesktopError("Fields do not apply to this UI claim")
    elif not isinstance(predicate.get("context"), str) or not predicate["context"]:
        raise core.DesktopError("browser_context needs a stable context ID")
    elif "url" in predicate and not isinstance(predicate["url"], str):
        raise core.DesktopError("url must be text")


def evaluate(session, predicate, controller=None):
    """Check one current state; never dispatch input, retry, or infer causality.

    Status is satisfied, violated, or unknown. UI scope is visible accessibility
    content, file/config scope is a bounded persisted read, browser scope is a
    currently enumerated context. Input errors raise; unavailable evidence is unknown.
    """
    validate(predicate)
    result = {
        "session": session,
        "predicate": predicate,
        "started_at": time.time(),
        "observed_at": None,
        "status": "unknown",
        "reason": "evidence unavailable",
        "evidence": {},
    }
    kind = predicate["kind"]
    result["scope"] = {
        "kind": {
            "ui": "visible_accessibility",
            "file": "persisted_file",
            "config": "persisted_config",
            "browser_context": "browser_context",
        }[kind]
    }
    if "path" in predicate:
        result["scope"]["path"] = predicate["path"]
    if "context" in predicate:
        result["scope"]["context"] = predicate["context"]
    try:
        info = core.manifest(session)
        control = core.request(session, "control", controller)
        if control.get("owner") == "human":
            result["reason"] = "human_control: observation refused"
            return result
        if kind in ("file", "config"):
            if info.get("mode") == "host":
                result["reason"] = "file checks require a private session"
                return result
            observed, reason, evidence = file_check(session, info, predicate)
        elif kind == "ui":
            query = predicate.get("query", {})
            scope = {k: query[k] for k in ("window", "app") if k in query}
            result["scope"].update(scope)
            tree = core.request(session, "ui", controller, max_nodes=2000, **scope)
            observed, reason, evidence = ui_check(tree, predicate)
        else:
            tabs = core.request(session, "browser", controller, action="tabs")["tabs"]
            matched = next(
                (t for t in tabs if t["context"] == predicate["context"]), None
            )
            observed = matched is not None and (
                "url" not in predicate or matched["url"] == predicate["url"]
            )
            reason, evidence = (
                "context and optional URL comparison",
                {"context": predicate["context"], "present": matched is not None},
            )
        result.update(
            status="unknown"
            if observed is None
            else "satisfied"
            if observed
            else "violated",
            reason=reason,
            evidence=evidence,
        )
    except (core.DesktopError, OSError, UnicodeError, ValueError) as error:
        # Do not include file contents or exception paths in evidence errors.
        result["reason"] = f"observation unavailable ({type(error).__name__})"
    finally:
        result["observed_at"] = time.time()
    return result


def file_check(session, info, predicate):
    name = predicate["path"]
    path = (
        (Path(info.get("home") or core.session_path(session) / "home") / name[2:])
        if name.startswith("~/")
        else Path(name)
    )
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        return predicate.get("exists") is False, "path absent", {"exists": False}
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            return None, "not a regular file", {}
        if predicate.get("exists") is False:
            return False, "path present", {"exists": True}
        if predicate["kind"] == "file" and not any(
            k in predicate for k in ("contains", "text", "sha256")
        ):
            return True, "path present", {"exists": True}
        data = stream.read(READ_LIMIT + 1)
        after = os.fstat(stream.fileno())

    def version(value):
        return (value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)

    if version(before) != version(after) or version(after) != version(path.stat()):
        return None, "file changed during read", {}
    if len(data) > READ_LIMIT:
        return None, "file read limit exceeded", {"limit_bytes": READ_LIMIT}
    digest = hashlib.sha256(data).hexdigest()
    evidence = {
        "exists": True,
        "bytes": len(data),
        "sha256": digest,
        "mtime_ns": after.st_mtime_ns,
    }
    if predicate["kind"] == "config":
        parser = configparser.ConfigParser(interpolation=None, delimiters=("=",))
        parser.optionxform = str
        try:
            parser.read_string(data.decode("utf-8"))
        except configparser.Error:
            return None, "unsupported or unreadable config format", evidence
        if not parser.sections() or parser.defaults():
            return None, "unsupported or unreadable config format", evidence
        values = {
            f"{section}/{key}": value
            for section in parser.sections()
            for key, value in parser[section].items()
        }
        key = predicate["key"]
        return (
            key in values
            and core.setting(values[key]) == core.setting(predicate["value"]),
            "config key comparison",
            evidence,
        )
    matched = "sha256" not in predicate or digest == predicate["sha256"]
    if "contains" in predicate or "text" in predicate:
        text = data.decode("utf-8")
        matched = (
            matched
            and ("contains" not in predicate or predicate["contains"] in text)
            and ("text" not in predicate or text == predicate["text"])
        )
    return matched, "persisted file comparison", evidence


def ui_check(tree, predicate):
    query = {
        k: v
        for k, v in predicate.get("query", {}).items()
        if k not in ("window", "app")
    }
    nodes = [n for n in tree["nodes"] if core.node_matches(n, **query)]
    coverage = {k: tree.get(k) for k in ("truncated", "truncated_by", "unreadable")}
    evidence = {
        "coverage": coverage,
        "matched": len(nodes),
        "witness_ids": [n["id"] for n in nodes[:5]],
    }
    partial = not core.ui_complete(tree)
    claim = predicate.get("claim", "exists")
    if claim == "exists" and nodes:
        return True, "visible witness found", evidence
    if claim == "absent" and nodes:
        return False, "visible counterexample found", evidence
    if claim in ("unique", "value") and len(nodes) > 1:
        return False, "multiple visible matches refute uniqueness", evidence
    if claim == "all":
        readable = [n for n in nodes if isinstance(n.get("states"), list)]
        if any(not core.node_matches(n, state=predicate["state"]) for n in readable):
            return False, "visible counterexample found", evidence
        if len(readable) != len(nodes):
            partial = True
    if partial:
        return None, "source UI coverage incomplete", evidence
    if claim == "exists":
        return False, "no visible witness", evidence
    if claim == "absent":
        return True, "no match in complete visible scope", evidence
    if claim == "all":
        return (
            bool(nodes),
            "all visible matches satisfy state" if nodes else "empty visible domain",
            evidence,
        )
    if len(nodes) != 1:
        return False, "expected exactly one visible match", evidence
    if claim == "unique":
        return True, "one match in complete visible scope", evidence
    field = predicate.get("field", "value")
    if field not in nodes[0]:
        return None, "element field unavailable", evidence
    return (
        nodes[0][field] == predicate["equals"],
        "visible element field comparison",
        evidence,
    )
