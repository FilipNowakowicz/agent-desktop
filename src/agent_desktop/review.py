"""Experimental offline evidence review. Rendering evidence never verifies it."""

import html
import itertools
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .core import DesktopError

MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_STEPS = 100
MAX_CHECKS = 200
SENSITIVE = re.compile(
    r"password|passwd|secret|token|credential|cookie|authorization|api[_-]?key", re.I
)
PRIVATE_FIELDS = {
    "text",
    "value",
    "contains",
    "stdout",
    "stderr",
    "body",
    "content",
    "headers",
    "html",
    "inner_html",
    "code",
    "clipboard",
    "typed_text",
    "equals",
    "argv",
    "args",
    "command",
    "path",
    "file",
    "cwd",
    "home",
}
URL = re.compile(r"https?://[^\s<>\"']+", re.I)
FILE_URL = re.compile(r"file://[^\s<>\"']+", re.I)
INLINE_SECRET = re.compile(
    r"\b(?:bearer\s+\S+|(?:password|token|secret|api[_-]?key)\s*[:=]\s*[^\s,;]+)", re.I
)

CSS = """
:root { color-scheme:light; font-family:Cantarell,'DejaVu Sans',sans-serif;
 color:#213b61; background:#f8fafc; font-size:16px; line-height:1.55; }
* { box-sizing:border-box; } body { margin:0; } main { max-width:1100px;
 margin:auto; padding:48px 32px 64px; } h1 { font-size:2rem; line-height:1.2;
 margin:0 0 12px; font-weight:650; letter-spacing:-.025em; }
h2 { font-size:1.25rem; margin:32px 0 16px; } h3 { overflow-wrap:anywhere; font-size:1.12rem;
 margin:0 0 10px; } p { overflow-wrap:anywhere; max-width:75ch; margin:10px 0; } .intro { color:#52647c; }
.notice { border-left:5px solid #815100; padding:16px 20px; background:#fff6e5;
 margin:24px 0; } .notice h2 { margin:0 0 8px; } .notice p { margin:0; }
.meta { overflow-wrap:anywhere; display:flex; flex-wrap:wrap; gap:8px 24px; color:#52647c; font-size:.9rem; }
.timeline { padding:0; margin:0; list-style:none; counter-reset:step; }
.step { counter-increment:step; position:relative; margin-left:16px;
 padding:0 0 30px 36px; border-left:2px solid #c4d1e0; }
.step::before { content:counter(step); position:absolute; left:-17px; top:0;
 width:32px; height:32px; display:grid; place-items:center; border-radius:50%;
 color:#fff; background:#213b61; font-weight:600; font-size:.9rem; }
.step:last-child { padding-bottom:0; border-left-color:transparent; }
.delivery { border-bottom:1px solid #d7e0eb; padding:0 0 12px; margin:0 0 14px; }
.label { color:#52647c; margin-right:8px; } .acknowledged,.observed { color:#2c60a7; }
.unknown,.uncertain,.pending,.dispatching { color:#815100; }
.violated,.failed { color:#8f3434; } .satisfied { color:#176254; }
.checks { margin:0; padding:0; list-style:none; } .check { margin:14px 0; }
.check strong { display:block; } .check p { margin:4px 0; }
.scope { font-size:.9rem; color:#52647c; } details { margin-top:12px; }
summary { cursor:pointer; color:#2c60a7; width:fit-content; }
summary:focus-visible { outline:3px solid #2c60a7; outline-offset:4px; }
pre { white-space:pre-wrap; overflow-wrap:anywhere; background:#edf2f7;
 color:#213b61; padding:16px; margin:10px 0 0; font-size:.82rem; max-height:26rem;
 overflow:auto; } .recovery { margin-top:32px; border-top:2px solid #213b61;
 padding-top:16px; } .recovery h2 { margin:0 0 8px; }
footer { margin-top:40px; color:#52647c; font-size:.85rem; }
@media(max-width:600px) { main { padding:28px 20px 40px; } h1 { font-size:1.65rem; }
 .step { padding-left:28px; } .meta { display:block; } .meta span { display:block; } }
@media print { main { max-width:none; padding:0; } pre { max-height:none; }
 details { break-inside:avoid; } }
"""


def escaped(value):
    return html.escape(str(value), quote=True)


def redact_url(match):
    try:
        parsed = urlsplit(match.group())
        host = parsed.hostname or "redacted"
        if ":" in host:
            host = f"[{host}]"
        if parsed.port:
            host += f":{parsed.port}"
        safe = urlunsplit((parsed.scheme, host, parsed.path, "", ""))
        return safe + (
            " [query or fragment redacted]" if parsed.query or parsed.fragment else ""
        )
    except ValueError:
        return "[redacted URL]"


class Redactor:
    def __init__(self):
        self.remaining = 5000
        self.truncated = False

    def apply(self, value, key="", depth=0):
        self.remaining -= 1
        if self.remaining < 0 or depth > 10:
            self.truncated = True
            return "[evidence truncated]"
        if (
            SENSITIVE.search(key)
            or key.casefold() in PRIVATE_FIELDS
            or re.search(r"(?:^|[_-])(?:text|value)(?:$|[_-])", key, re.I)
            or re.search(
                r"(?:^|[_-])(?:path|paths|filename|directory)(?:$|[_-])", key, re.I
            )
        ):
            return "[redacted]"
        if isinstance(value, dict):
            pairs = itertools.islice(value.items(), 200)
            if len(value) > 200:
                self.truncated = True
            return {
                self.clean_string(str(k))[:100]: self.apply(v, str(k), depth + 1)
                for k, v in pairs
            }
        if isinstance(value, list):
            if len(value) > 200:
                self.truncated = True
            return [self.apply(v, key, depth + 1) for v in value[:200]]
        if isinstance(value, str):
            return self.clean_string(value)
        return value

    def clean_string(self, value):
        if len(value) > 2000:
            self.truncated = True
            value = value[:2000] + " [truncated]"
        value = FILE_URL.sub("[redacted file URL]", value)
        return INLINE_SECRET.sub("[redacted]", URL.sub(redact_url, value))


def checks_from(value):
    if not isinstance(value, dict):
        return []
    items = value.get("checks", [])
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        items = [None]
    return [
        item
        if isinstance(item, dict)
        else {
            "status": "unknown",
            "reason": "Saved check evidence is malformed.",
            "scope": "Recorded check only",
        }
        for item in items
    ]


def check_status(check):
    state = check.get("status")
    return state if state in ("satisfied", "violated", "unknown") else "unknown"


def predicate_label(predicate):
    labels = {
        "file": "Output file",
        "config": "Configuration",
        "ui": "Visible UI",
        "browser_context": "Browser context",
    }
    return labels.get(predicate, predicate) if isinstance(predicate, str) else predicate


def action_label(request):
    if not isinstance(request, dict):
        return "Action"
    action = (
        request.get("action")
        or request.get("operation")
        or request.get("kind")
        or request.get("type")
    )
    if not isinstance(action, str):
        return "Action"
    labels = {
        "open": "Open page",
        "type": "Type text",
        "key": "Send key",
        "click": "Click",
        "fill": "Fill field",
        "press": "Press",
        "wait": "Wait",
        "select": "Select",
        "screenshot": "Capture screen",
        "launch": "Launch application",
    }
    label = labels.get(action, action)
    if action == "key" and isinstance(request.get("key"), str):
        label += ": " + request["key"]
    elif action in ("click", "press") and isinstance(request.get("element"), str):
        label += " " + request["element"]
    return label


def check_html(check):
    state = check_status(check)
    predicate = check.get("predicate") or check.get("name") or "Outcome check"
    if isinstance(predicate, dict):
        predicate = predicate.get("kind") or predicate.get("type") or "Scoped predicate"
    predicate = predicate_label(predicate)
    reason = (
        check.get("reason")
        or "No reason was recorded. Inspect the evidence before continuing."
    )
    scope = check.get("scope") or "Scope was not recorded."
    if isinstance(scope, (dict, list)):
        scope = json.dumps(scope, ensure_ascii=False)
    return (
        f'<li class="check"><strong class="{state}">{state.title()}: {escaped(predicate)}</strong>'
        f'<p>{escaped(reason)}</p><p class="scope">Scope: {escaped(scope)}</p>'
        + evidence_html(check, "Check evidence")
        + "</li>"
    )


def evidence_html(value, label="Recorded evidence"):
    return (
        f"<details><summary>{label}</summary><pre>"
        + escaped(json.dumps(value, indent=2, ensure_ascii=False))
        + "</pre></details>"
    )


def observation_error(step):
    if not isinstance(step, dict):
        return None
    if step.get("observation_error"):
        return step["observation_error"]
    observation = step.get("observation")
    if isinstance(observation, dict) and observation.get("error"):
        return observation["error"]
    result = step.get("result")
    if isinstance(result, dict):
        return result.get("observation_error")
    return None


def render(evidence):
    """Create a bounded, escaped report of supplied evidence, without replay."""
    if not isinstance(evidence, dict):
        raise DesktopError("Evidence must be a JSON object")
    redactor = Redactor()
    data = redactor.apply(evidence)
    raw_steps = data.get("steps", [])
    if not isinstance(raw_steps, list):
        raise DesktopError("Evidence steps must be a list")
    steps = [step for step in raw_steps[:MAX_STEPS] if isinstance(step, dict)]
    run_checks = checks_from(data)
    all_checks = [c for step in steps for c in checks_from(step)] + run_checks
    # A standalone saved predicate result is also a useful report input.
    if not steps and not all_checks and "predicate" in data:
        run_checks = all_checks = [data]
    limited = (
        redactor.truncated
        or len(raw_steps) > MAX_STEPS
        or len(all_checks) > MAX_CHECKS
        or len(steps) != len(raw_steps)
    )
    all_checks = all_checks[:MAX_CHECKS]
    violated = sum(check_status(c) == "violated" for c in all_checks)
    unknown = sum(check_status(c) == "unknown" for c in all_checks)
    satisfied = sum(check_status(c) == "satisfied" for c in all_checks)
    observation_errors = bool(observation_error(data)) or any(
        observation_error(step) for step in steps
    )
    uncertain_delivery = any(
        step.get("dispatch_state", step.get("delivery", "unknown"))
        not in ("acknowledged", "observed", "delivered")
        for step in steps
    )
    incomplete_run = data.get("state") in (
        "submitted",
        "running",
        "stopped",
        "cancelled",
        "delivery_unknown",
    )
    needs_review = (
        incomplete_run
        or violated
        or unknown
        or limited
        or observation_errors
        or uncertain_delivery
        or not all_checks
    )
    heading = (
        "Review the result before continuing"
        if needs_review
        else "Inspect the recorded checks"
    )
    findings = f"{satisfied} satisfied, {violated} violated, {unknown} unknown."
    if not all_checks:
        findings = "Outcome unknown: no outcome checks were recorded."
    if limited:
        findings += " Evidence coverage is limited; omitted results remain unknown."
    if uncertain_delivery:
        findings += " At least one action has unconfirmed delivery."
    if observation_errors:
        findings += " Follow-up observation failed."
    if incomplete_run and not uncertain_delivery:
        findings += " Run execution is incomplete or its delivery remains unknown."
    parts = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\">",
        "<title>Desktop evidence review</title><style>"
        + CSS
        + "</style></head><body><main>",
        "<h1>Desktop evidence review</h1>",
        '<p class="intro">Read what was requested, what returned, and what the checks actually establish.</p>',
        '<div class="meta"><span>Session: '
        + escaped(data.get("session", "not recorded"))
        + "</span>",
        "<span>Operation: "
        + escaped(data.get("operation_id", "saved evidence"))
        + "</span></div>",
        '<section class="notice" aria-labelledby="finding"><h2 id="finding">'
        + heading
        + "</h2>",
        "<p>" + escaped(findings) + "</p></section>",
        "<p>Delivery responses alone do not confirm task completion. Check statuses below are recorded evidence, not new verification.</p>",
    ]
    check_budget = MAX_CHECKS
    if steps:
        parts.append('<h2>Requested actions</h2><ol class="timeline">')
        for step in steps:
            request = step.get("request", {})
            action = action_label(request)
            delivery = step.get("dispatch_state", step.get("delivery", "unknown"))
            if delivery not in (
                "acknowledged",
                "observed",
                "delivered",
                "pending",
                "dispatching",
                "failed",
                "uncertain",
            ):
                delivery = "unknown"
            label = {
                "acknowledged": "Response returned",
                "observed": "Response and observation recorded",
                "delivered": "Reported delivered",
                "pending": "Pending",
                "dispatching": "Dispatch in progress",
                "failed": "Reported failure",
                "uncertain": "Delivery unknown",
                "unknown": "Delivery unknown",
            }[delivery]
            parts.append(
                f'<li class="step"><h3>{escaped(action)}</h3><p class="delivery"><span class="label">Delivery</span><strong class="{delivery}">{label}</strong></p>'
            )
            error = observation_error(step)
            if error:
                parts.append(
                    '<p class="unknown">Observation unavailable: '
                    + escaped(error)
                    + "</p>"
                )
            checks = checks_from(step)
            if checks:
                parts.append('<ul class="checks">')
                parts.extend(check_html(c) for c in checks[:check_budget])
                parts.append("</ul>")
                check_budget = max(0, check_budget - len(checks))
            else:
                parts.append(
                    '<p class="unknown">Outcome unknown: no step check was recorded.</p>'
                )
            parts.append(evidence_html(step, "Action and response evidence") + "</li>")
        parts.append("</ol>")
    else:
        parts.append(
            '<h2>Requested actions</h2><p class="unknown">No action sequence was recorded. Delivery is unknown.</p>'
        )
    if run_checks:
        parts.append('<h2>Run checks</h2><ul class="checks">')
        parts.extend(check_html(c) for c in run_checks[:check_budget])
        parts.append("</ul>")
    advice = data.get("recovery")
    if not isinstance(advice, str):
        advice = "Inspect the actual desktop or output before repeating an action with uncertain delivery. Resolve violated or unknown checks before continuing."
    parts.append(
        '<section class="recovery"><h2>Before continuing</h2><p>'
        + escaped(advice)
        + "</p></section>"
    )
    parts.append(evidence_html(data, "All saved evidence, with redactions"))
    parts.append(
        "<footer>Experimental local review. Text, values, command arguments, structured file paths and URL queries are redacted by default. Review before sharing: free-form evidence can still contain private information. This report performs no actions, opens no external links, and does not contact a service. Human review benefit has not been measured.</footer></main></body></html>"
    )
    result = "\n".join(parts)
    if len(result.encode()) > MAX_OUTPUT_BYTES:
        raise DesktopError(
            "Rendered evidence exceeds the report size limit; narrow the input"
        )
    return result


def write_report(evidence, output):
    """Atomically replace a private output file, without following output symlinks."""
    rendered = render(evidence)
    destination = Path(output).expanduser().absolute()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=".desktop-review-",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(rendered)
        os.replace(temporary, destination)
    except OSError as error:
        raise DesktopError(f"Cannot write review report: {error}") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {
        "path": str(destination),
        "bytes": len(rendered.encode()),
        "experimental": True,
    }


def from_file(source, output):
    try:
        descriptor = os.open(Path(source).expanduser(), os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise DesktopError("Evidence input must be a regular JSON file")
            raw = stream.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise DesktopError("Evidence input exceeds the 2 MiB limit")
        data = json.loads(raw)
    except (OSError, ValueError, RecursionError) as error:
        raise DesktopError(f"Cannot read evidence JSON: {error}") from error
    return write_report(data, output)
