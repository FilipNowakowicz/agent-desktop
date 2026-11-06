"""Positive and negative controls for the tier suite, run before any model.

For each task and several seeds, a correct solution (a scripted page in
headless Chromium, and direct file changes where the task works on files) must
pass the task's check, and every plausible wrong solution (the distractor
taken, a duplicate, the wrong environment, the uncorrected data, nothing at
all) must fail. The untouched start state is the "nothing at all" variant.
"""

import random
import shutil
import subprocess
import tempfile
import types
import unittest
from pathlib import Path

from test_runtime import CHROMIUM
from test_web_fixtures import FILL, snap_wrapper

from benchmarks import tiers
from benchmarks.tasks import Reports

SEEDS = (101, 102, 103, 7, 8)


def js_set(**fields):
    return "".join(f"set(document.getElementById('{k}'),{v!r});" for k, v in fields.items())


# Each solver returns (python side effect or None, javascript) for a variant.


def incident(context, variant):
    a = dict(context.answer)
    if variant == "nothing":
        return None, ""
    if variant == "loadtest-counted":
        a["count"] += 2
    elif variant == "wrong-service":
        a["service"] = next(s for s in tiers.SERVICES if s != a["service"])
    elif variant == "wrong-first":
        a["first"] = "14:00:05"
    elif variant == "wrong-request":
        a["slowest"] = "r-zzzzzz"
    return None, js_set(svc=a["service"], n=a["count"], first=a["first"], req=a["slowest"]) + "go.click();"


def bulk(context, variant):
    entries = list(context.answer["new"])
    if variant == "nothing":
        return None, ""
    if variant == "missing-last":
        entries = entries[:-1]
    if variant == "wrong-amount":
        entries[0] = dict(entries[0], amount=entries[0]["amount"] + 1)
    script = "const E=%r;const wait=ms=>new Promise(r=>setTimeout(r,ms));(async()=>{" % (entries,)
    script += (
        "for(let i=0;i<E.length;i++){const e=E[i];"
        "if(!login.hidden){set(u,'finance');set(p,PW);si.click()}"
        "set(eid,e.id);set(edate,e.date);set(ev,e.vendor);set(ea,String(e.amount));add.click();"
        "await wait(1600)}"
    )
    if variant == "no-login":
        script = script.replace("if(!login.hidden){set(u,'finance');set(p,PW);si.click()}", "")
    script += "})();"
    return None, script


def rollout(context, variant):
    if variant == "nothing":
        return None, ""

    def effect():
        for name in context.low:
            old_t, old_r = context.old[name]
            envs = ["staging"] + (["prod"] if variant == "prod-too" else [])
            for env in envs:
                path, text = context.files[(env, name)]
                text = text.replace(f"timeout_ms = {old_t}", "timeout_ms = 2500", 1)
                text = text.replace(f"retries = {old_r}", "retries = 3", 1)
                if variant == "admin-too":
                    text = text.replace("timeout_ms = 1000", "timeout_ms = 2500")
                path.write_text(text)
        if variant == "high-too":
            high = next(n for n in ("orders", "billing", "catalog") if n not in context.low)
            path, text = context.files[("staging", high)]
            path.write_text(text.replace("timeout_ms = 3000", "timeout_ms = 2500", 1))
        if variant != "no-note":
            context.note.write_text(
                "".join(
                    f"{n}: timeout {t}, retries {r}\n" for n, (t, r) in context.old.items()
                )
            )

    count = len(context.low) + (1 if variant == "high-too" else 0)
    return effect, js_set(n=count) + "done.click();"


def meeting(context, variant):
    day, start, room = context.answer
    if variant == "nothing":
        return None, ""
    if variant == "wrong-room":
        room = (room + 1) % 3
    if variant == "wrong-start":
        start += 1
    return None, js_set(day=tiers.DAYS[day], start=tiers.hm(start), room=tiers.ROOMS[room]) + "book.click();yes.click();"


def moving(context, variant):
    if variant == "nothing":
        return None, ""
    target = dict(context.answer)
    if variant == "uncorrected":
        target = dict(context.uncorrected)
    script = (
        "const T=%r;const wait=ms=>new Promise(r=>setTimeout(r,ms));(async()=>{"
        "for(const [sku,v] of Object.entries(T)){const i=rows.findIndex(r=>r.sku===sku);"
        "if(rows[i].stock===v)continue;app.querySelectorAll('button')[i].click();"
        "set(st,v);sv.click();await wait(300)}})();" % (target,)
    )
    return None, script


def triage(context, variant):
    if variant == "nothing":
        return None, ""

    def effect():
        for path in context.inbox.rglob("*"):
            if path.is_file():
                path.unlink()
        expected = dict(context.expected)
        if variant == "near-duplicate-deleted":
            expected = {p: t for p, t in expected.items() if "budget-v2" not in p}
        if variant == "no-dedupe":
            expected["misc/photo-final-2.txt"] = expected["misc/photo-final.txt"]
        for rel, text in expected.items():
            (context.inbox / rel).parent.mkdir(parents=True, exist_ok=True)
            (context.inbox / rel).write_text(text)
        if variant != "no-manifest":
            (context.inbox / "manifest.csv").write_text(
                "\n".join(sorted(context.expected)) + "\n"
            )

    return effect, ""


SOLVERS = {
    "tier-incident-triage": (incident, ["loadtest-counted", "wrong-service", "wrong-first", "wrong-request"]),
    "tier-bulk-entry": (bulk, ["missing-last", "wrong-amount", "no-login"]),
    "tier-config-rollout": (rollout, ["prod-too", "admin-too", "high-too", "no-note"]),
    "tier-meeting-slot": (meeting, ["wrong-room", "wrong-start"]),
    "tier-moving-target": (moving, ["uncorrected"]),
    "tier-file-triage": (triage, ["near-duplicate-deleted", "no-dedupe", "no-manifest"]),
}


@unittest.skipUnless(
    CHROMIUM and not snap_wrapper(CHROMIUM), "a non-snap Chromium is needed"
)
class TierControls(unittest.TestCase):
    def run_variant(self, task, variant):
        directory = Path(tempfile.mkdtemp(prefix="tier-", dir=self.root))
        reports = Reports()
        self.addCleanup(reports.close)
        context = types.SimpleNamespace(
            directory=directory, reports=reports, report_url=reports.url, home=str(directory)
        )
        task.setup(context)
        if task.name == "tier-moving-target":
            # What a run that never rereads the note would produce.
            context.uncorrected = None
        solver = SOLVERS[task.name][0]
        if task.name == "tier-moving-target":
            context.uncorrected = uncorrected(context)
        effect, script = solver(context, variant)
        page = directory / "page.html"
        if page.exists():
            if script:
                page.write_text(
                    page.read_text()
                    + f"<script>setTimeout(()=>{{{FILL}{script}}},200)</script>"
                )
            process = subprocess.Popen(
                [
                    CHROMIUM, "--headless", "--disable-gpu", "--no-sandbox",
                    f"--user-data-dir={directory / 'profile'}",
                    "--virtual-time-budget=25000", "--dump-dom", page.as_uri(),
                ],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                start_new_session=True,
            )
            process.communicate(timeout=60)
        if effect:
            effect()
        return task.check(context)

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="tier-controls-")
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_controls(self):
        for task in tiers.TIER_TASKS:
            variants = ["right", "nothing", *SOLVERS[task.name][1]]
            for seed in SEEDS:
                for variant in variants:
                    with self.subTest(task=task.name, seed=seed, variant=variant):
                        random.seed(seed)
                        passed, detail = self.run_variant(task, variant)
                        self.assertEqual(passed, variant == "right", detail)


def uncorrected(context):
    """The stock a run would leave if it ignored the correction."""
    text = context.note.read_text()
    first = {}
    for line in text.split("\nCORRECTION")[0].splitlines():
        m = tiers.re.match(r"(SKU-\d+)\s+\+(\d+)", line)
        if m:
            first[m.group(1)] = int(m.group(2))
    start = {}
    for s, v in context.answer.items():
        start[s] = v
    # Recover the initial stock from the page rows.
    rows = tiers.re.search(r"const rows=(\[.*?\]);let cur", (context.directory / "page.html").read_text())
    initial = {r["sku"]: r["stock"] for r in eval(rows.group(1))}  # noqa: S307 (own data)
    return {s: initial[s] + first.get(s, 0) for s in initial}


if __name__ == "__main__":
    unittest.main()
