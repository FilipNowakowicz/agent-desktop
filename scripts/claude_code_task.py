"""Have Claude Code complete a GUI task through the project MCP server, then verify it.

The agent gets no built-in tools: only the private-desktop MCP tools. The harness
checks the outcome itself and destroys the session afterwards.
"""

import argparse
import json
import os
import secrets
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from agent_desktop import core

PAGE = """<!doctype html><meta charset="utf-8"><title>Agent task</title>
<style>body{{font:18px sans-serif;margin:24px}}#zone{{position:absolute;left:520px;
top:300px;width:200px;height:140px;border:3px dashed #383}}#box{{position:absolute;
left:80px;top:320px;width:90px;height:90px;background:#c33;color:#fff;cursor:grab;
display:flex;align-items:center;justify-content:center;user-select:none}}</style>
<p>1. Type the code shown below into the field.</p>
<canvas id="code" width="260" height="60"></canvas>
<p><input id="answer" placeholder="code" autocomplete="off"></p>
<p>2. Drag the red box into the dashed target. 3. Press Submit.</p>
<button id="submit">Submit</button><div id="zone">target</div><div id="box">box</div>
<script>
const code = "{code}";
const g = document.getElementById("code").getContext("2d");
g.font = "bold 40px monospace"; g.fillText(code, 10, 45);
let drag = null;
box.onpointerdown = (e) => {{ drag = [e.clientX - box.offsetLeft, e.clientY - box.offsetTop];
  box.setPointerCapture(e.pointerId); }};
box.onpointermove = (e) => {{ if (drag) {{ box.style.left = (e.clientX - drag[0]) + "px";
  box.style.top = (e.clientY - drag[1]) + "px"; }} }};
box.onpointerup = () => {{ drag = null; }};
function inside() {{ const b = box.getBoundingClientRect(), z = zone.getBoundingClientRect();
  return b.left >= z.left && b.right <= z.right && b.top >= z.top && b.bottom <= z.bottom; }}
submit.onclick = () => {{ const ok = answer.value.trim() === code;
  document.title = "Agent task - " + (ok && inside() ? "complete" :
    "incomplete code=" + ok + " box=" + inside()); }};
</script>
"""

PROMPT = """You have tools for a private Linux desktop that does not affect the user's screen.

1. Create a headless desktop session.
2. Launch exactly this argument list in it:
   {argv}
3. Wait for the browser window, take screenshots and complete the task shown on the page:
   read the code drawn on the page, type it into the field, drag the red box fully
   inside the dashed target, then press Submit.
4. Confirm the window title ends with "complete". If it says "incomplete", fix it and
   submit again.
5. Do NOT destroy the session. Reply with one line: SESSION=<id> RESULT=<window title>.
"""


def host_state():
    """Read-only Hyprland focus/pointer snapshot, when available."""
    if not shutil.which("hyprctl"):
        return None
    window = subprocess.run(
        ["hyprctl", "activewindow", "-j"], capture_output=True, text=True
    )
    cursor = subprocess.run(["hyprctl", "cursorpos"], capture_output=True, text=True)
    try:
        active = json.loads(window.stdout).get("address")
    except ValueError:
        active = None
    return {"active_window": active, "cursor": cursor.stdout.strip()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model")
    parser.add_argument("--budget", default="2")
    args = parser.parse_args()
    browser = shutil.which("chromium")
    if not browser or not shutil.which("claude"):
        raise SystemExit("Requires chromium and the claude CLI")
    artifact = Path("artifacts/claude-code") / uuid.uuid4().hex[:12]
    artifact.mkdir(parents=True, mode=0o700)
    state = (artifact / "state").resolve()
    code = "".join(secrets.choice("ABCDEFGHJKMNPQRSTUVWXYZ23456789") for _ in range(6))
    page = artifact / "task.html"
    page.write_text(PAGE.format(code=code))
    argv = [
        browser,
        f"--user-data-dir={(artifact / 'profile').resolve()}",
        "--no-first-run",
        "--no-default-browser-check",
        "--ozone-platform=wayland",
        "--disable-gpu",
        "--password-store=basic",
        "--window-size=1200,680",
        page.resolve().as_uri(),
    ]
    environment = {**os.environ, "AGENT_DESKTOP_STATE_DIR": str(state)}
    command = [
        "claude",
        "-p",
        PROMPT.format(argv=json.dumps(argv)),
        "--mcp-config",
        ".mcp.json",
        "--strict-mcp-config",
        "--tools",
        "",
        "--allowedTools",
        "mcp__private-desktop",
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
        "--max-budget-usd",
        args.budget,
    ]
    if args.model:
        command += ["--model", args.model]
    host_before = host_state()
    started = time.monotonic()
    with (artifact / "transcript.jsonl").open("w") as transcript:
        process = subprocess.run(
            command,
            env=environment,
            stdout=transcript,
            stderr=subprocess.PIPE,
            text=True,
            timeout=1200,
        )
    elapsed = round(time.monotonic() - started, 1)
    host_after = host_state()
    events = [json.loads(line) for line in (artifact / "transcript.jsonl").open()]
    tools = [
        block["name"]
        for event in events
        if event.get("type") == "assistant"
        for block in event["message"]["content"]
        if block.get("type") == "tool_use"
    ]
    final = next((e for e in reversed(events) if e.get("type") == "result"), {})
    init = next((e for e in events if e.get("subtype") == "init"), {})
    report = {
        "code": code,
        "model": init.get("model"),
        "exit_code": process.returncode,
        "stderr": process.stderr[-2000:],
        "elapsed_seconds": elapsed,
        "tool_calls": len(tools),
        "tools": {name: tools.count(name) for name in sorted(set(tools))},
        "result": final.get("result"),
        "cost_usd": final.get("total_cost_usd"),
        "turns": final.get("num_turns"),
        "passed": False,
        "host_before": host_before,
        "host_after": host_after,
        "host_unchanged": host_before == host_after,
    }
    # Independent verification: the harness reads the session itself.
    os.environ["AGENT_DESKTOP_STATE_DIR"] = str(state)
    sessions = [s for s in core.sessions() if s["status"] == "ready"]
    report["sessions"] = sessions
    for session in sessions:
        windows = core.request(session["session"], "windows")["windows"]
        report["windows"] = [w["title"] for w in windows]
        capture = core.request(session["session"], "screenshot")
        report["final_screenshot"] = capture["path"]
        report["passed"] = len(sessions) == 1 and any(
            w["title"].startswith("Agent task - complete") for w in windows
        )
        report["cleanup"] = core.destroy(session["session"])
    (artifact / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"artifacts": str(artifact), **report}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
