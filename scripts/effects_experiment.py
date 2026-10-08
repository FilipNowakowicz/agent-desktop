"""Scripted scenarios for the experimental effect ledger (no model calls).

Each scenario drives real applications in a private session with
AGENT_DESKTOP_EFFECTS=1 and records, per step, what the ledger reported, how
long the step took and how large the report is compared with a screenshot.
The expectation per scenario is written before running; the result says
whether the ledger showed it.

    uv run scripts/effects_experiment.py [--only NAME] [--output FILE]
"""

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

# --no-effects measures the same steps without the ledger (latency baseline).
os.environ["AGENT_DESKTOP_EFFECTS"] = "0" if "--no-effects" in sys.argv else "1"

from agent_desktop import core  # noqa: E402

# A full screenshot of the 1280x720 desktop, using Anthropic's documented
# estimate of width * height / 750 image tokens; text at about 4 characters
# per token. Both are estimates for comparison, not billing measurements.
SCREENSHOT_TOKENS = round(1280 * 720 / 750)


def text_tokens(value):
    return round(len(json.dumps(value, ensure_ascii=False)) / 4)


class Run:
    def __init__(self, name, expectation):
        self.name = name
        self.expectation = expectation
        self.steps = []
        self.session = core.create()["session"]

    def step(self, label, operation, **arguments):
        started = time.monotonic()
        result = core.request(self.session, operation, **arguments)
        elapsed = time.monotonic() - started
        effects = result.get("effects") if isinstance(result, dict) else None
        self.steps.append(
            {
                "step": label,
                "operation": operation,
                "ms": round(elapsed * 1000),
                "effects": effects,
                "effect_tokens": text_tokens(effects) if effects else 0,
            }
        )
        return result

    def wait(self, label, **conditions):
        result = core.wait(self.session, **conditions)
        self.steps.append(
            {"step": label, "operation": "wait", "satisfied": result["satisfied"]}
        )
        return result["satisfied"]

    def late(self, label, effect_id, pause=2.0):
        """Effects of an earlier step observed after a pause (late writes)."""
        time.sleep(pause)
        result = core.request(self.session, "effects", effect_id=effect_id)
        self.steps.append(
            {
                "step": label,
                "operation": "effects",
                "effects": result,
                "effect_tokens": text_tokens(result),
            }
        )
        return result

    def wait_effect(self, label, effect_id, path, timeout=10):
        """Wait for a file effect instead of sleeping or taking screenshots."""
        started = time.monotonic()
        result = core.wait_effect(self.session, effect_id, path, timeout=timeout)
        self.steps.append(
            {
                "step": label,
                "operation": "wait_effect",
                "path": path,
                "satisfied": result["satisfied"],
                "ms": round((time.monotonic() - started) * 1000),
                "effects": result["effects"],
                "effect_tokens": text_tokens(result["effects"]),
            }
        )
        return result

    def finish(self, **outcome):
        shot = core.request(self.session, "screenshot", scale=0.5)
        core.destroy(self.session)
        return {
            "scenario": self.name,
            "expectation": self.expectation,
            **outcome,
            "final_screenshot": shot.get("path"),
            "screenshot_tokens_full": SCREENSHOT_TOKENS,
            "steps": self.steps,
        }


def files_in(effects):
    return {f["path"]: f for f in (effects or {}).get("files", [])}


def terminal():
    run = Run(
        "terminal-write",
        "Typing a shell command that writes a file reports that file with its "
        "content; a second command reports the appended line.",
    )
    run.step("launch foot", "launch", argv=["foot", "--title", "term"])
    run.wait("terminal window", title="term", timeout=10)
    run.wait("shell ready", seconds=1.5)
    run.step("type command", "type", text="echo hello > notes.txt")
    first = run.step("press Return", "key", key="Return")["effects"]
    run.step("type append", "type", text="echo again >> notes.txt")
    second = run.step("press Return", "key", key="Return")["effects"]
    notes1, notes2 = (
        files_in(first).get("~/notes.txt"),
        files_in(second).get("~/notes.txt"),
    )
    return run.finish(
        shown=bool(notes1 and notes2 and notes2.get("diff") == ["+again"]),
        notes={"first": notes1, "second": notes2},
    )


def mousepad():
    run = Run(
        "editor-save",
        "Saving a new document reports the save dialog opening and the created "
        "file with its text; typing alone writes no document (application "
        "state may change).",
    )
    run.step("launch mousepad", "launch", argv=["mousepad"])
    run.wait("editor window", app_id="org.xfce.mousepad", timeout=20, stable_ms=500)
    typed = run.step("type text", "type", text="hello effects")["effects"]
    dialog = run.step("Ctrl+S", "key", key="s", modifiers=["ctrl"])["effects"]
    run.wait("save dialog", title="Save As", timeout=10, stable_ms=300)
    run.step("type name", "type", text="letter.txt")
    saved = run.step("press Return", "key", key="Return")["effects"]
    waited = run.wait_effect(
        "wait for ~/letter.txt", saved["effect_id"], "~/letter.txt"
    )
    letter = files_in(waited["effects"]).get("~/letter.txt")
    seen_dialog = "Save As" in json.dumps(
        dialog.get("windows")
    ) or "Save As" in json.dumps(waited["effects"].get("windows"))
    return run.finish(
        shown=bool(
            letter
            and "+hello effects" in letter.get("diff", [])
            and not files_in(typed)
            and seen_dialog
        ),
        letter=letter,
    )


def thunar():
    run = Run(
        "file-manager-hidden-files",
        "Pilot session 15: Ctrl+H shows hidden files in the window, but without "
        "xfconfd nothing is saved. The ledger should report no settings file.",
    )
    run.step("launch thunar", "launch", argv=["thunar"])
    run.wait("thunar window", app_id="thunar", timeout=20, stable_ms=800)
    toggled = run.step("Ctrl+H", "key", key="h", modifiers=["ctrl"])["effects"]
    late = run.late("3 s later", toggled["effect_id"], pause=3)
    settings = [
        p
        for p in [*files_in(toggled), *files_in(late)]
        if "xfce4" in p or "Thunar" in p
    ]
    return run.finish(
        shown=not settings, settings_files=settings, toggled=toggled, late=late
    )


def calc():
    run = Run(
        "calc-save-and-format-dialog",
        "Saving as .ods reports the created document. Saving as .csv opens the "
        "'Keep current format' dialog and writes no file until it is answered.",
    )
    run.step(
        "launch calc",
        "launch",
        argv=["libreoffice", "--calc", "--norestore", "--nologo"],
    )
    run.wait("calc window", title="Calc", timeout=60, stable_ms=1000)
    run.step("type value", "type", text="42")
    run.step("Return", "key", key="Return")
    run.step("Ctrl+S", "key", key="s", modifiers=["ctrl"])
    run.wait("save dialog", title="Save", timeout=15, stable_ms=500)
    run.step("type name", "type", text="numbers")
    ods = run.step("press Return", "key", key="Return")["effects"]
    ods_late = run.wait_effect(
        "wait for ~/numbers.ods", ods["effect_id"], "~/numbers.ods"
    )["effects"]
    run.wait("saved", title="numbers", timeout=15, stable_ms=500)
    run.step("Ctrl+Shift+S", "key", key="s", modifiers=["ctrl", "shift"])
    run.wait("save as dialog", title="Save", timeout=15, stable_ms=500)
    run.step("select name", "key", key="a", modifiers=["ctrl"])
    run.step("type csv name", "type", text="numbers.csv")
    csv = run.step("press Return", "key", key="Return")["effects"]
    csv_wait = run.wait_effect(
        "wait for ~/numbers.csv", csv["effect_id"], "~/numbers.csv", timeout=4
    )
    csv_late = csv_wait["effects"]
    ods_files = {**files_in(ods), **files_in(ods_late)}
    csv_files = {**files_in(csv), **files_in(csv_late)}
    windows = csv_late.get("windows") or csv.get("windows") or {}
    return run.finish(
        shown=bool(
            "~/numbers.ods" in ods_files
            and "~/numbers.csv" not in csv_files
            and windows.get("opened")
        ),
        ods=ods_files.get("~/numbers.ods"),
        csv_windows=windows,
        csv_files=sorted(csv_files),
    )


def calc_cells():
    run = Run(
        "calc-cell-diff",
        "Pilot session 20 lost data into wrong cells. After saving, the ledger "
        "lists every cell written (with formulas); changing one value and saving "
        "again shows that cell and the recalculated formula, nothing else.",
    )
    run.step(
        "launch calc",
        "launch",
        argv=["libreoffice", "--calc", "--norestore", "--nologo"],
    )
    run.wait("calc window", title="Calc", timeout=60, stable_ms=1000)
    for label, text in (("A1", "Item"), ("B1", "Qty"), ("C1", "Price")):
        run.step(f"type {label}", "type", text=text)
        run.step("Tab", "key", key="Tab")
    run.step("next row", "key", key="Return")
    for label, text in (("A2", "Widget"), ("B2", "3"), ("C2", "4"), ("D2", "=B2*C2")):
        run.step(f"type {label}", "type", text=text)
        run.step("Tab", "key", key="Tab")
    run.step("finish row", "key", key="Return")
    run.step("Ctrl+S", "key", key="s", modifiers=["ctrl"])
    run.wait("save dialog", title="Save", timeout=15, stable_ms=500)
    run.step("type name", "type", text="order")
    first = run.step("press Return", "key", key="Return")["effects"]
    saved = run.wait_effect("wait for ~/order.ods", first["effect_id"], "~/order.ods")
    run.wait("saved", title="order", timeout=15, stable_ms=500)
    run.step("go to B2", "key", key="Home", modifiers=["ctrl"])
    run.step("down", "key", key="Down")
    run.step("right", "key", key="Right")
    run.step("type 7", "type", text="7")
    run.step("Return", "key", key="Return")
    again = run.step("Ctrl+S", "key", key="s", modifiers=["ctrl"])["effects"]
    resaved = run.wait_effect(
        "wait for ~/order.ods again", again["effect_id"], "~/order.ods"
    )
    created = files_in(saved["effects"]).get("~/order.ods") or {}
    changed = files_in(resaved["effects"]).get("~/order.ods") or {}
    expected_first = {"+Sheet1!B2: 3", "+Sheet1!D2: 12  [of:=[.B2]*[.C2]]"}
    expected_change = {
        "-Sheet1!B2: 3",
        "+Sheet1!B2: 7",
        "-Sheet1!D2: 12  [of:=[.B2]*[.C2]]",
        "+Sheet1!D2: 28  [of:=[.B2]*[.C2]]",
    }
    return run.finish(
        shown=expected_first <= set(created.get("diff", []))
        and set(changed.get("diff", [])) == expected_change,
        created=created,
        changed=changed,
    )


def firefox():
    run = Run(
        "browser-start-noise",
        "Starting a browser and loading a page writes many profile files. The "
        "ledger should keep them as a noise count or a short list, not flood.",
    )
    launched = run.step(
        "launch firefox",
        "launch",
        argv=["firefox", "--new-instance", "about:blank"],
    )["effects"]
    run.wait("browser window", app_id="firefox", timeout=40, stable_ms=1500)
    late = run.late("5 s later", launched["effect_id"], pause=5)
    listed = len(late.get("files", []))
    return run.finish(
        shown=listed <= 15,
        listed=listed,
        noise=late.get("noise_files", 0),
        listed_paths=[f["path"] for f in late.get("files", [])],
    )


SCENARIOS = {
    "terminal": terminal,
    "mousepad": mousepad,
    "thunar": thunar,
    "calc": calc,
    "calc_cells": calc_cells,
    "firefox": firefox,
}
REQUIRES = {
    "terminal": "foot",
    "mousepad": "mousepad",
    "thunar": "thunar",
    "calc": "libreoffice",
    "calc_cells": "libreoffice",
    "firefox": "firefox",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", action="append", choices=sorted(SCENARIOS))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-effects", action="store_true", help="latency baseline")
    args = parser.parse_args()
    results = []
    for name in args.only or SCENARIOS:
        if not shutil.which(REQUIRES[name]):
            results.append({"scenario": name, "skipped": f"{REQUIRES[name]} not found"})
            continue
        try:
            results.append(SCENARIOS[name]())
        except Exception as error:  # record and continue with other scenarios
            results.append(
                {"scenario": name, "error": f"{type(error).__name__}: {error}"}
            )
        print(json.dumps({k: v for k, v in results[-1].items() if k != "steps"}))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n")
    return 0 if all(r.get("shown") for r in results if "shown" in r) else 1


if __name__ == "__main__":
    sys.exit(main())
