"""Explore control-panel tiles through accessibility and record what they ran.

For each home tile: press it and record stand-in tool calls. If a detail view
opens (it has a back button), press its unnamed switch twice (off, then on),
record those calls too, and go back. Writes results to panel-checks.json.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from agent_desktop import core  # noqa: E402

TRIAL = Path(sys.argv[1] if len(sys.argv) > 1 else "artifacts/shell-trial").resolve()
SESSION = json.loads((TRIAL / "session.json").read_text())["session"]
LOG = TRIAL / "calls.jsonl"
POLLING = {("makoctl", "mode"), ("wpctl", "status")}


def nodes():
    return core.request(SESSION, "ui", app="python3")["nodes"]


def offset():
    return len(LOG.read_text().splitlines())


def actions_since(start):
    found = []
    for line in LOG.read_text().splitlines()[start:]:
        call = json.loads(line)
        if call.get("source") != "stub":
            continue
        argv = [call["tool"], *call["args"]]
        if (
            tuple(argv) in POLLING
            or (
                argv[1:2]
                and argv[1]
                in ("get-volume", "inspect", "-m", "show", "-t", "-x", "list")
            )
            or argv[:3] == ["nmcli", "radio", "wifi"]
            and len(argv) == 3
        ):
            continue
        if argv not in found:
            found.append(argv)
    return found


def press(node_id, settle=1.2):
    start = offset()
    core.request(SESSION, "ui_action", node=node_id, action="press")
    time.sleep(settle)
    return actions_since(start)


def home_tiles():
    return [n for n in nodes() if n["role"] == "button" and len(n["name"].split()) >= 3]


results = []
for label in [t["name"].split()[1] for t in home_tiles()]:
    tile = next(t for t in home_tiles() if t["name"].split()[1] == label)
    entry = {"tile": label, "state_before": tile["name"].split(" ", 2)[2]}
    entry["tile_commands"] = press(tile["id"])
    view = nodes()
    back = next((n for n in view if n["name"] == "‹"), None)
    if back:
        title_index = next(i for i, n in enumerate(view) if n is back)
        switch = next(
            (
                n
                for n in view[title_index + 1 :]
                if n["role"] == "button" and not n["name"]
            ),
            None,
        )
        entry["view"] = True
        entry["switch_accessible_name"] = switch["name"] if switch else None
        if switch:
            entry["switch_off_commands"] = press(switch["id"])
            entry["switch_on_commands"] = press(switch["id"])
        press(back["id"], settle=0.6)
    else:
        entry["view"] = False
        after = next((t for t in home_tiles() if t["name"].split()[1] == label), None)
        entry["state_after"] = after["name"].split(" ", 2)[2] if after else None
        if entry["tile_commands"]:
            entry["restore_commands"] = press(after["id"]) if after else []
    results.append(entry)
    print(json.dumps(entry, ensure_ascii=False), flush=True)
(TRIAL / "panel-checks.json").write_text(
    json.dumps(results, indent=2, ensure_ascii=False) + "\n"
)
