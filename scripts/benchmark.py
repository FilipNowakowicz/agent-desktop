"""Run the representative GUI task suite with Claude Code and record outcomes.

Each task gets a fresh harness-created session with its application already
launched. The agent receives only the agent-desktop MCP tools; the harness
verifies the outcome independently, then destroys the session and checks cleanup.
"""

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_desktop import core  # noqa: E402
from agent_desktop.worker import find_registryd, owned_processes  # noqa: E402
from benchmarks.atlas import ATLAS_TASKS  # noqa: E402
from benchmarks.effects import EFFECT_TASKS  # noqa: E402
from benchmarks.hard import HARD_TASKS  # noqa: E402
from benchmarks.office import OFFICE_TASKS  # noqa: E402
from benchmarks.tasks import TASKS  # noqa: E402

SUITES = {
    "standard": TASKS,
    "hard": HARD_TASKS,
    "office": OFFICE_TASKS,
    "effects": EFFECT_TASKS,
    "atlas": ATLAS_TASKS,
}

# Tool profiles for comparisons. "basic" is the tool set before waiting, action
# sequences and semantic UI were added (screenshot region/scale arguments remain
# available in both). Harness-owned lifecycle and launch are always disabled.
LIFECYCLE = ["create", "destroy", "launch"]
NEWER = [
    "wait",
    "actions",
    "ui",
    "ui_action",
    "request_human",
    "control",
    "profiles",
]
TOOL_PROFILES = {"basic": LIFECYCLE + NEWER, "full": LIFECYCLE}

PROMPT = """You control a private Linux desktop through the agent-desktop tools.
Use session {session}; it already exists and the application is already open.
Do not create or destroy sessions.

Task: {task}

Use the available tools as you judge best. When finished, reply with one line
starting with DONE, or FAILED with a short reason."""


class Context:
    def __init__(self, session, directory):
        self.session = session
        self.directory = directory
        self.application = None
        self.applications = []
        self.wait_windows = None

    def windows(self):
        return core.request(self.session, "windows")["windows"]

    def status_of(self, application):
        for entry in core.request(self.session, "status")["applications"]:
            if entry["pid"] == application["pid"]:
                return entry
        return None

    def application_status(self):
        return self.status_of(self.application)

    def application_output(self):
        return Path(self.application["logs"]).read_text(errors="replace")


def run_agent(
    prompt,
    artifact,
    budget,
    model,
    *,
    mcp_config=".mcp.json",
    server="agent-desktop",
    disallowed=None,
):
    if disallowed is None:
        disallowed = [
            f"mcp__{server}__desktop_{name}" for name in ("create", "destroy", "launch")
        ]
    command = [
        "claude",
        "-p",
        prompt,
        "--mcp-config",
        mcp_config,
        "--strict-mcp-config",
        "--tools",
        "",
        "--allowedTools",
        f"mcp__{server}",
        *(["--disallowedTools", *disallowed] if disallowed else []),
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
        "--max-budget-usd",
        str(budget),
    ]
    if model:
        command += ["--model", model]
    started = time.monotonic()
    with (artifact / "transcript.jsonl").open("w") as transcript:
        try:
            process = subprocess.run(
                command,
                stdout=transcript,
                stderr=subprocess.PIPE,
                text=True,
                timeout=900,
            )
            exit_code, stderr = process.returncode, process.stderr[-2000:]
        except subprocess.TimeoutExpired:
            exit_code, stderr = None, "agent timed out after 900 s"
    elapsed = round(time.monotonic() - started, 1)
    events = []
    for line in (artifact / "transcript.jsonl").read_text().splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    calls = [
        block
        for event in events
        if event.get("type") == "assistant"
        for block in event["message"]["content"]
        if block.get("type") == "tool_use"
    ]
    errors = [
        block
        for event in events
        if event.get("type") == "user"
        for block in event["message"].get("content", [])
        if isinstance(block, dict)
        and block.get("type") == "tool_result"
        and block.get("is_error")
    ]
    result = next((e for e in reversed(events) if e.get("type") == "result"), {})
    init = next((e for e in events if e.get("subtype") == "init"), {})
    names = [c["name"].removeprefix(f"mcp__{server}__") for c in calls]
    return {
        "model": init.get("model"),
        "exit_code": exit_code,
        "stderr": stderr,
        "elapsed_seconds": elapsed,
        "tool_calls": len(calls),
        "tool_errors": len(errors),
        "tools": {n: names.count(n) for n in sorted(set(names))},
        "reply": (result.get("result") or "")[-500:],
        "cost_usd": result.get("total_cost_usd"),
        "usage": result.get("usage", {}),
        "model_usage": result.get("modelUsage", {}),
        "turns": result.get("num_turns"),
    }


def effects_enabled():
    return os.environ.get("AGENT_DESKTOP_EFFECTS") == "1"


def agent_directory(root, task):
    """The transcript lives outside the task directory, which the effect
    ledger watches: otherwise the agent is shown its own transcript."""
    path = root / "agents" / task.name
    path.mkdir(parents=True, exist_ok=True)
    return path


def mcp_config_for(root):
    """The MCP config, with the effect-ledger setting passed explicitly."""
    path = root / "mcp.json"
    if not path.exists():
        config = json.loads(Path(".mcp.json").read_text())
        for server in config["mcpServers"].values():
            server["env"] = {
                **server.get("env", {}),
                "AGENT_DESKTOP_EFFECTS": os.environ.get("AGENT_DESKTOP_EFFECTS", "0"),
                "AGENT_DESKTOP_ATLAS": os.environ.get("AGENT_DESKTOP_ATLAS", ""),
            }
        path.write_text(json.dumps(config, indent=2) + "\n")
    return str(path)


def run_task(task, root, budget, model, dry_run=False, profile="full"):
    directory = (root / task.name).resolve()
    directory.mkdir(parents=True)
    record = {"task": task.name, "passed": False}
    # With --effects, the ledger also watches the task's output directory.
    os.environ["AGENT_DESKTOP_EFFECT_DIRS"] = str(directory)
    session = core.create()["session"]
    info = core.manifest(session)
    context = Context(session, directory)
    context.mcp_config = mcp_config_for(root)
    try:
        argv, goal = task.setup(context)
        # A task may launch several applications; the last one holds its answer.
        commands = argv if isinstance(argv[0], list) else [argv]
        before = {w["id"] for w in context.windows()}
        for command in commands:
            context.applications.append(core.request(session, "launch", argv=command))
            time.sleep(0.5)  # keep the window stacking order deterministic
        context.application = context.applications[-1]
        expected = context.wait_windows or len(commands)
        deadline = time.monotonic() + 30
        while len({w["id"] for w in context.windows()} - before) < expected:
            if time.monotonic() > deadline:
                raise RuntimeError("Application window did not appear")
            time.sleep(0.2)
        time.sleep(1)  # let the first frame render before the agent looks
        if not dry_run:
            record.update(
                run_agent(
                    PROMPT.format(session=session, task=goal),
                    agent_directory(root, task),
                    budget,
                    model,
                    mcp_config=context.mcp_config,
                    disallowed=[
                        f"mcp__agent-desktop__desktop_{name}"
                        for name in TOOL_PROFILES[profile]
                        + ([] if effects_enabled() else ["effects"])
                        + (
                            []
                            if os.environ.get("AGENT_DESKTOP_ATLAS")
                            else ["atlas", "set"]
                        )
                    ],
                )
            )
        time.sleep(0.5)
        # Some checks judge an honest FAILED reply (an impossible task).
        context.reply = record.get("reply")
        context.home = str(core.session_path(session) / "home")
        passed, detail = task.check(context)
        record["passed"] = bool(passed)
        record["detail"] = detail
        record["final_screenshot"] = core.request(session, "screenshot")["path"]
    except Exception as error:
        record["error"] = f"{type(error).__name__}: {error}"
    finally:
        try:
            record["cleanup"] = core.destroy(session)
        except core.DesktopError as error:
            record["cleanup_error"] = str(error)
        record["leftover_processes"] = owned_processes(info["token"])
    (directory / "record.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=SUITES, default="standard")
    parser.add_argument("--only", nargs="*", help="task names")
    parser.add_argument("--budget", type=float, default=1.0, help="USD per task")
    parser.add_argument("--model")
    parser.add_argument("--seed", type=int, help="Reproduce randomized fixture inputs")
    parser.add_argument(
        "--tools",
        choices=TOOL_PROFILES,
        default="full",
        help="agent tool profile (basic: before wait/actions/semantic UI)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="set up and check without an agent"
    )
    parser.add_argument(
        "--atlas",
        type=Path,
        help="directory of effect-atlas files for the desktop_atlas tool",
    )
    parser.add_argument(
        "--effects",
        action="store_true",
        help="experimental effect ledger in sessions and MCP replies",
    )
    args = parser.parse_args()
    random.seed(args.seed)
    # Sessions inherit this from the harness; the MCP server from claude.
    os.environ["AGENT_DESKTOP_EFFECTS"] = "1" if args.effects else "0"
    if args.atlas:
        os.environ["AGENT_DESKTOP_ATLAS"] = str(args.atlas.resolve())
    else:
        os.environ.pop("AGENT_DESKTOP_ATLAS", None)
    if not args.dry_run and not shutil.which("claude"):
        raise SystemExit("Requires the claude CLI")
    root = Path("artifacts/benchmark") / time.strftime("%Y%m%d-%H%M%S")
    root = root.with_name(root.name + "-" + uuid.uuid4().hex[:4])
    root.mkdir(parents=True, mode=0o700)
    os.environ["AGENT_DESKTOP_STATE_DIR"] = str((root / "state").resolve())
    records = []
    for task in SUITES[args.suite]:
        if args.only and task.name not in args.only:
            continue
        missing = [r for r in task.requires if not shutil.which(r)]
        if missing:
            records.append({"task": task.name, "skipped": f"missing {missing}"})
            continue
        record = run_task(task, root, args.budget, args.model, args.dry_run, args.tools)
        records.append(record)
        print(
            json.dumps(
                {
                    k: record.get(k)
                    for k in (
                        "task",
                        "passed",
                        "tool_calls",
                        "tool_errors",
                        "elapsed_seconds",
                        "cost_usd",
                        "detail",
                        "error",
                    )
                },
                default=str,
            ),
            flush=True,
        )
    ran = [r for r in records if "skipped" not in r]
    summary = {
        "seed": args.seed,
        "tools": args.tools,
        "effects": args.effects,
        "atlas": bool(args.atlas),
        "accessibility": bool(find_registryd()),
        "tasks": len(ran),
        "passed": sum(r["passed"] for r in ran),
        "skipped": [r["task"] for r in records if "skipped" in r],
        "cleanup_failures": [
            r["task"]
            for r in ran
            if r.get("cleanup_error") or r.get("leftover_processes")
        ],
        "total_cost_usd": round(sum(r.get("cost_usd") or 0 for r in ran), 3),
        "total_seconds": round(sum(r.get("elapsed_seconds") or 0 for r in ran), 1),
        "model": next((r.get("model") for r in ran if r.get("model")), None),
    }
    (root / "summary.json").write_text(
        json.dumps({"summary": summary, "records": records}, indent=2, default=str)
        + "\n"
    )
    print(json.dumps({"artifacts": str(root), **summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
