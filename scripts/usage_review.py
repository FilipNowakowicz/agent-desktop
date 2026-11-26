"""Find and summarise Agent Desktop use in local agent transcripts.

Reads Claude Code (~/.claude/projects) and Codex (~/.codex/sessions) transcripts,
keeps the Agent Desktop MCP calls and the shell commands that touched Agent
Desktop, and writes a private review folder:

- summary.json: counts and short error categories (no arguments, messages or
  full results);
- summary.md: the same counts plus flagged moments to read, with transcript
  paths and times;
- timelines/: one condensed timeline per transcript (user messages, calls,
  shortened results, related shell commands).

Transcripts hold personal data and sometimes secrets, so the folder is created
0700 outside the repository and nothing in it is meant to be committed. Field
reports copy aggregates and paraphrase; see docs/project/USAGE_REVIEW.md.

    uv run python scripts/usage_review.py --since 2026-11-18
"""

import argparse
import collections
import datetime
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = re.compile(r"agent[-_]desktop__(desktop_\w+)$")
SESSION = re.compile(r'"session":\s*"([0-9a-f]{12})"')
STOP = re.compile(r'"stopped\\?"?:\s*\{[^{}]*?"reason\\?"?:\s*\\?"((?:[^"\\]|\\.)*)')
IDLE_MINUTES = 10
REMARK_WINDOW = datetime.timedelta(minutes=15)
TIMELINE_RESULT = 240

# Shell commands worth reading: each is a way of working around (or beside)
# the MCP tools. The categories are what a field report counts.
SHELL_PATTERNS = (
    ("profile internals", re.compile(r"cookies\.sqlite|sessionstore|\.mozilla/")),
    ("profile files", re.compile(r"agent-desktop/profiles/|profiles/[\w.-]+/home")),
    ("mcp bridge", re.compile(r"agent-desktop-mcp|mcp\.client|ClientSession")),
    ("cli", re.compile(r"(^|[\s/;&|(])agent-desktop\s+[a-z]")),
    ("session state", re.compile(r"\.local/state/agent-desktop/[0-9a-f]{12}")),
)
# A file a tool reply named (save, send, download): reading it in the shell is
# the documented route, so such a command is counted as "tool output" instead.
RETURNED_FILE = re.compile(r'\\?"(?:to_file|file)\\?":\s*\\?"([^"\\]+)')
STATE_PART = re.compile(r"\.local/state/agent-desktop/(.+)")
CORRECTION = re.compile(
    r"\b(actually|instead|why (did|do|is)|can you not|can't you|don'?t|stop|"
    r"wrong|again|still|annoying|not working|doesn'?t work)\b",
    re.IGNORECASE,
)


def parse_time(value):
    if not value:
        return None
    try:
        moment = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=datetime.UTC)


def flatten(content):
    """Tool result content as one string (images become [image])."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(item.get("text", "[image]"))
            else:
                parts.append(str(item))
        return " ".join(parts)
    if content is None:
        return ""
    return json.dumps(content)


def human_text(content):
    """A user message's own words, skipping tool results and injected blocks."""
    texts = []
    if isinstance(content, str):
        texts = [content]
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") in ("text", "input_text"):
                texts.append(item.get("text", ""))
    words = [t for t in texts if t.strip() and not t.lstrip().startswith("<")]
    return " ".join(words).strip()


class Transcript:
    def __init__(self, path, source):
        self.path, self.source = path, source
        self.project = None
        self.calls = []  # dicts: id, time, tool, args, result, error
        self.shell = []  # (time, command)
        self.messages = []  # (time, text)


def read_claude(path):
    transcript = Transcript(path, "claude")
    by_id = {}
    with open(path, errors="replace") as lines:
        for line in lines:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            transcript.project = transcript.project or record.get("cwd")
            message = record.get("message")
            if not isinstance(message, dict):
                continue
            moment = parse_time(record.get("timestamp"))
            content = message.get("content")
            if record.get("type") == "user":
                text = human_text(content)
                if text and not text.startswith("This session is being continued"):
                    transcript.messages.append((moment, text))
                for item in content if isinstance(content, list) else ():
                    if isinstance(item, dict) and item.get("type") == "tool_result":
                        call = by_id.get(item.get("tool_use_id"))
                        if call is not None:
                            call["result"] = flatten(item.get("content"))
                            call["error"] = bool(item.get("is_error"))
            elif record.get("type") == "assistant" and isinstance(content, list):
                for item in content:
                    if not isinstance(item, dict) or item.get("type") != "tool_use":
                        continue
                    name = item.get("name") or ""
                    match = TOOL.search(name)
                    arguments = item.get("input") or {}
                    if match:
                        call = {
                            "id": item.get("id"),
                            "time": moment,
                            "tool": match.group(1),
                            "args": arguments,
                            "result": "",
                            "error": False,
                        }
                        by_id[call["id"]] = call
                        transcript.calls.append(call)
                    elif name == "Bash" and isinstance(arguments, dict):
                        command = arguments.get("command") or ""
                        transcript.shell.append((moment, command))
    return transcript


def read_codex(path):
    transcript = Transcript(path, "codex")
    with open(path, errors="replace") as lines:
        for line in lines:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue
            moment = parse_time(record.get("timestamp"))
            kind = payload.get("type")
            if record.get("type") == "session_meta":
                transcript.project = payload.get("cwd")
            elif kind == "mcp_tool_call_end":
                invocation = payload.get("invocation") or {}
                server = invocation.get("server") or ""
                if "desktop" not in server.replace("_", "-"):
                    continue
                result = payload.get("result")
                error = isinstance(result, dict) and "Err" in result
                if isinstance(result, dict):
                    result = result.get("Ok", result.get("Err"))
                    if isinstance(result, dict):
                        error = error or bool(result.get("isError"))
                        result = result.get("content", result)
                transcript.calls.append(
                    {
                        "id": payload.get("call_id"),
                        "time": moment,
                        "tool": invocation.get("tool") or "",
                        "args": invocation.get("arguments") or {},
                        "result": flatten(result),
                        "error": error,
                    }
                )
            elif kind == "function_call" and payload.get("name") == "exec_command":
                try:
                    arguments = json.loads(payload.get("arguments") or "{}")
                except ValueError:
                    arguments = {}
                command = arguments.get("cmd") or arguments.get("command") or ""
                if isinstance(command, list):
                    command = " ".join(command)
                transcript.shell.append((moment, command))
            elif kind == "message" and payload.get("role") == "user":
                text = human_text(payload.get("content"))
                if text:
                    transcript.messages.append((moment, text))
    return transcript


def find_transcripts(claude_root, codex_root):
    for root, reader in ((claude_root, read_claude), (codex_root, read_codex)):
        if root and root.is_dir():
            for path in sorted(root.rglob("*.jsonl")):
                try:
                    with open(path, errors="replace") as file:
                        if "desktop" not in file.read():
                            continue
                except OSError:
                    continue
                yield reader(path)


def exposed_tools():
    source = (REPO / "src/agent_desktop/mcp_server.py").read_text()
    # Registered by default: decorated with @tool. Opt-in experiments
    # (desktop_run, desktop_atlas, ...) are registered later, only with their variable.
    return sorted(set(re.findall(r"\n@tool\([^)]*\)\ndef (desktop_\w+)\(", source)))


def steps_of(call):
    if call["tool"] != "desktop_browser":
        return []
    arguments = call["args"]
    if arguments.get("action") == "steps" and isinstance(arguments.get("steps"), list):
        return [s for s in arguments["steps"] if isinstance(s, dict)]
    return [arguments]


def error_kind(text):
    """A short error category without paths, ids or values."""
    text = re.sub(r"^Error executing tool \w+: ", "", text.strip())
    text = re.sub(r"/[\w./~-]+", "<path>", text)
    text = re.sub(r"\b[0-9a-f]{8,}\b", "<id>", text)
    return text.split(";")[0].split("\n")[0][:90]


def reads_returned_file(command, returned):
    """Whether a shell command names a file that a tool reply returned: its
    full path, or its folder (under the state directory) and its name."""
    for path in returned:
        if path in command:
            return True
        part = STATE_PART.search(path)
        if part:
            folder, _, name = part.group(1).rpartition("/")
            if folder and folder in command and name in command:
                return True
    return False


def review(transcripts, since=None, until=None):
    """Count, deduplicate and flag the calls; returns (summary, flags, kept)."""
    seen = set()
    kept = []
    for transcript in transcripts:
        calls = []
        for call in transcript.calls:
            moment = call["time"]
            if call["id"] in seen:
                continue
            if since and (moment is None or moment < since):
                continue
            if until and (moment is None or moment >= until):
                continue
            seen.add(call["id"])
            calls.append(call)
        if calls:
            transcript.calls = calls
            kept.append(transcript)

    counts = collections.Counter()
    steps = collections.Counter()
    errors = collections.Counter()
    stops = collections.Counter()
    shell = collections.Counter()
    projects = collections.Counter()
    flags = []
    totals = collections.Counter()

    def flag(kind, transcript, moment, detail):
        flags.append((kind, transcript, moment, detail))

    for transcript in kept:
        project = Path(transcript.project or transcript.path.parent.name).name
        projects[f"{transcript.source}:{project}"] += len(transcript.calls)
        created, destroyed, last_use, returned = set(), set(), {}, set()
        previous = None
        for call in transcript.calls:
            tool, arguments, moment = call["tool"], call["args"], call["time"]
            counts[tool] += 1
            session = arguments.get("session")
            if tool == "desktop_create" and not call["error"]:
                found = SESSION.search(call["result"])
                if found:
                    created.add(found.group(1))
                    session = found.group(1)
            if tool == "desktop_request_host" and not call["error"]:
                found = SESSION.search(call["result"])
                if found:
                    created.add(found.group(1))
                    session = found.group(1)
                    totals["host sessions"] += 1
            if session and session in destroyed and tool != "desktop_destroy":
                flag("call after destroy", transcript, moment, f"{tool} on {session}")
            if tool == "desktop_destroy" and session:
                destroyed.add(session)
            if session and session in last_use and moment and last_use[session]:
                gap = (moment - last_use[session]).total_seconds() / 60
                if gap >= IDLE_MINUTES and tool != "desktop_destroy":
                    flag(
                        "idle session", transcript, moment, f"{session}: {gap:.0f} min"
                    )
                elif gap >= IDLE_MINUTES:
                    flag(
                        "idle before destroy",
                        transcript,
                        moment,
                        f"{session}: {gap:.0f} min",
                    )
            if session:
                last_use[session] = moment
            returned.update(RETURNED_FILE.findall(call["result"]))
            if call["error"]:
                errors[(tool, error_kind(call["result"]))] += 1
                flag(
                    "tool error",
                    transcript,
                    moment,
                    f"{tool}: {error_kind(call['result'])}",
                )
            if (
                previous
                and previous["error"]
                and previous["tool"] == tool
                and previous["args"] == arguments
            ):
                flag("repeated after error", transcript, moment, tool)
            for reason in STOP.findall(call["result"]):
                reason = error_kind(reason.encode().decode("unicode_escape", "replace"))
                stops[reason] += 1
                flag("batch stopped", transcript, moment, reason)
            for step in steps_of(call):
                action = step.get("action") or "?"
                steps[action] += 1
                if action == "wait":
                    conditional = any(
                        k in step for k in ("text", "selector", "url", "title", "gone")
                    )
                    totals[
                        "waits for a condition" if conditional else "fixed waits"
                    ] += 1
            if call["tool"] == "desktop_browser" and arguments.get("action") == "steps":
                totals["browser batches"] += 1
            # Pointer input: the single tools, and since 2026-11-26 (when move,
            # drag and scroll became steps only) pointer steps in desktop_actions.
            pointer = 0
            if tool in ("desktop_click", "desktop_scroll", "desktop_drag"):
                pointer = 1
            elif tool == "desktop_actions" and isinstance(
                arguments.get("actions"), list
            ):
                pointer = sum(
                    isinstance(step, dict)
                    and step.get("action") in ("click", "scroll", "drag", "move")
                    and "x" in step
                    for step in arguments["actions"]
                )
            if pointer:
                totals["coordinate input"] += pointer
                if arguments.get("observation"):
                    totals["coordinate input with observation"] += pointer
            if tool == "desktop_screenshot" and not arguments.get("scale"):
                totals["unscaled screenshots"] += 1
            if tool == "desktop_create" and arguments.get("renderer") not in (
                None,
                "pixman",
            ):
                totals["GPU creates"] += 1
                if call["error"]:
                    totals["failed GPU creates"] += 1
            previous = call
        for session in sorted(created - destroyed):
            flag("left running", transcript, None, session)
        totals["sessions created"] += len(created)

        start = transcript.calls[0]["time"]
        end = transcript.calls[-1]["time"]
        for moment, command in transcript.shell:
            if (
                moment
                and start
                and end
                and not (
                    start - datetime.timedelta(hours=1)
                    <= moment
                    <= end + datetime.timedelta(hours=1)
                )
            ):
                continue
            for kind, pattern in SHELL_PATTERNS:
                if pattern.search(command):
                    if kind in ("profile files", "session state") and (
                        reads_returned_file(command, returned)
                    ):
                        shell["tool output"] += 1
                        break
                    shell[kind] += 1
                    flag(f"shell: {kind}", transcript, moment, command[:160])
                    break
        times = [c["time"] for c in transcript.calls if c["time"]]
        for moment, text in transcript.messages:
            near = moment and any(abs(moment - t) <= REMARK_WINDOW for t in times)
            if not near or text.startswith("Stop hook feedback"):
                continue
            if CORRECTION.search(text):
                flag("person's remark", transcript, moment, text[:200])

    exposed = exposed_tools()
    summary = {
        "calls": sum(counts.values()),
        "transcripts": len(kept),
        "calls_by_project": dict(projects.most_common()),
        "calls_by_tool": dict(counts.most_common()),
        "tools_not_called": [t for t in exposed if not counts[t]],
        "browser_steps": dict(steps.most_common()),
        "batch_stops": dict(stops.most_common()),
        "errors": {f"{tool}: {kind}": n for (tool, kind), n in errors.most_common()},
        "shell_commands": dict(shell.most_common()),
        "totals": dict(sorted(totals.items())),
        "flags": dict(collections.Counter(kind for kind, *_ in flags).most_common()),
    }
    return summary, flags, kept


def short(moment):
    return moment.strftime("%m-%d %H:%M") if moment else "--"


def timeline(transcript):
    events = [(m, f"**person:** {t[:400]}") for m, t in transcript.messages]
    for call in transcript.calls:
        result = call["result"].replace("\n", " ")[:TIMELINE_RESULT]
        arguments = json.dumps(call["args"])[:300]
        mark = "ERROR " if call["error"] else ""
        events.append(
            (call["time"], f"`{call['tool']}` {arguments}\n  -> {mark}{result}")
        )
    for moment, command in transcript.shell:
        if any(p.search(command) for _, p in SHELL_PATTERNS):
            events.append((moment, f"shell: `{command[:300]}`"))
    minimum = datetime.datetime.min.replace(tzinfo=datetime.UTC)
    events.sort(key=lambda e: e[0] or minimum)
    lines = [
        f"# {transcript.source}: {transcript.project}",
        "",
        f"`{transcript.path}`",
        "",
    ]
    lines += [f"- {short(m)} {text}" for m, text in events]
    return "\n".join(lines) + "\n"


def markdown(summary, flags, since, until):
    span = f"{since.date() if since else 'start'} to {until.date() if until else 'now'}"
    lines = [f"# Agent Desktop usage review, {span}", ""]
    lines += [f"{summary['calls']} calls in {summary['transcripts']} transcripts.", ""]
    for key in (
        "calls_by_project",
        "calls_by_tool",
        "browser_steps",
        "batch_stops",
        "errors",
        "shell_commands",
        "totals",
        "flags",
    ):
        lines += [f"## {key.replace('_', ' ')}", ""]
        lines += [f"- {k}: {v}" for k, v in summary[key].items()] or ["- none"]
        lines.append("")
    lines += [
        "## tools not called",
        "",
        ", ".join(summary["tools_not_called"]) or "none",
        "",
    ]
    lines += ["## Flagged moments", ""]
    for kind, transcript, moment, detail in sorted(
        flags,
        key=lambda f: (
            f[0],
            str(f[1].path),
            f[2] or datetime.datetime.min.replace(tzinfo=datetime.UTC),
        ),
    ):
        lines.append(f"- **{kind}** {short(moment)} `{transcript.path.name}`: {detail}")
    return "\n".join(lines) + "\n"


def private_folder(path):
    path = path.expanduser().resolve()
    if path == REPO or REPO in path.parents:
        raise SystemExit("The review folder must be outside the repository")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    (path / "timelines").mkdir(exist_ok=True, mode=0o700)
    return path


def day(value):
    return datetime.datetime.fromisoformat(value).replace(tzinfo=datetime.UTC)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--since", type=day, help="first day to include (UTC)")
    parser.add_argument("--until", type=day, help="first day to leave out (UTC)")
    state = Path(os.environ.get("XDG_STATE_HOME", "~/.local/state")).expanduser()
    today = datetime.date.today().isoformat()
    parser.add_argument(
        "--out", type=Path, default=state / "agent-desktop/usage-review" / today
    )
    parser.add_argument(
        "--claude", type=Path, default=Path("~/.claude/projects").expanduser()
    )
    parser.add_argument(
        "--codex", type=Path, default=Path("~/.codex/sessions").expanduser()
    )
    options = parser.parse_args(argv)

    out = private_folder(options.out)
    summary, flags, kept = review(
        find_transcripts(options.claude, options.codex), options.since, options.until
    )
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out / "summary.md").write_text(
        markdown(summary, flags, options.since, options.until)
    )
    for transcript in kept:
        name = f"{transcript.source}-{Path(transcript.project or 'unknown').name}-{transcript.path.stem[-12:]}.md"
        (out / "timelines" / name).write_text(timeline(transcript))
    print(
        f"{summary['calls']} calls in {summary['transcripts']} transcripts; {len(flags)} flags"
    )
    print(f"Wrote {out}")


if __name__ == "__main__":
    sys.exit(main())
