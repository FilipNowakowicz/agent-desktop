"""F2 matched trials with kills during agent runs (X2, 2026-11-26).

    uv run scripts/f2_trials.py run [--dry-run] [--log evidence/f2-trials.log]
    uv run scripts/f2_trials.py summary [--log ...] [--records OUT.jsonl]

`run` executes the plan of docs/research/2026-11-26-f2-trials-protocol.md in
its order (seed, task, arm; then the worker kill; then Chromium), one harness
invocation per run, and appends one JSON line per run to the log. A run starts
only if the reported cost so far plus its cap stays within the stop limit; an
API error stops everything. `summary` prints pass rates with exact intervals,
paired comparisons and per-injection outcomes, and can write the raw records.
"""

import argparse
import json
import math
import re
import statistics
import subprocess
import sys
from pathlib import Path

SEEDS = (22, 24, 25)
TASKS = {
    # task: (harness options, per-run cap, kill injection)
    "f2-document-edit": ([], 1.0, "office@2"),
    "f2-dataset-edit": (["--firefox", "--bridge"], 1.5, "browser@3"),
    "f2-mixed-upload": (["--firefox", "--bridge"], 1.5, "office@7"),
}
STOP = 9.50


def plan():
    runs = []
    for seed in SEEDS:
        for task, (options, cap, kill) in TASKS.items():
            for arm, injection in (("baseline", None), ("kill", kill)):
                runs.append((task, seed, arm, options, cap, injection))
    runs.append(("f2-document-edit", 22, "worker kill", [], 1.0, "worker@2"))
    for seed in (22, 24):
        runs.append(("f2-mixed-upload", seed, "chromium", [], 1.5, None))
    return runs


def command(task, seed, options, cap, injection, dry_run):
    argv = [
        sys.executable,
        "scripts/benchmark.py",
        "--suite",
        "f2",
        "--only",
        task,
        "--seed",
        str(seed),
        "--budget",
        str(cap),
        "--allow-launch",
        *options,
    ]
    if injection:
        argv += ["--inject", injection]
    if dry_run:
        argv.append("--dry-run")
    return argv


def entries(log):
    path = Path(log)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def init_event(entry):
    """The agent's init event (its tools, model and CLI version), or {}."""
    path = Path(entry["run"]) / "agents" / entry["task"] / "transcript.jsonl"
    try:
        for line in path.read_text().splitlines():
            if '"subtype":"init"' in line.replace(" ", ""):
                return json.loads(line)
    except OSError:
        pass
    return {}


def surface(entry):
    """The MCP tool surface a run had: 29 server tools before #240 (with
    desktop_drag among them), 17 after."""
    tools = init_event(entry).get("tools") or []
    return 29 if any(t.endswith("__desktop_drag") for t in tools) else 17


def valid(entry):
    data = json.loads((Path(entry["run"]) / "summary.json").read_text())
    return not data["records"][0].get("api_error")


def done(log):
    """Planned runs already done validly. A baseline/kill cell counts only as
    a complete pair on one tool surface, so no pair is split across the two
    surfaces; other arms count once on any surface."""
    finished = [e for e in entries(log) if not e.get("dry_run") and valid(e)]
    keys = {(e["task"], e["seed"], e["arm"]) for e in finished}
    keys = {k for k in keys if k[2] not in ("baseline", "kill")}
    by_cell = {}
    for e in finished:
        if e["arm"] in ("baseline", "kill"):
            key = (e["task"], e["seed"], surface(e))
            by_cell.setdefault(key, set()).add(e["arm"])
    for (task, seed, _), arms in by_cell.items():
        if arms == {"baseline", "kill"}:
            keys |= {(task, seed, "baseline"), (task, seed, "kill")}
    return keys


def run(args):
    spent = sum(e.get("cost_usd") or 0 for e in entries(args.log))
    skip = set() if args.dry_run else done(args.log)
    for task, seed, arm, options, cap, injection in plan():
        if (task, seed, arm) in skip:
            continue
        if args.dry_run and injection:
            injection = injection.split("@")[0] + "@0"  # No agent: fire at once.
        if not args.dry_run and spent + cap > STOP:
            print(f"BUDGET STOP before {task} {seed} {arm}: spent {spent:.3f}")
            return 0
        argv = command(task, seed, options, cap, injection, args.dry_run)
        print("$", " ".join(argv[1:]), flush=True)
        out = subprocess.run(argv, capture_output=True, text=True)
        found = re.search(r"artifacts/benchmark/[0-9a-f-]+", out.stdout)
        if not found:
            print(out.stdout[-2000:], out.stderr[-2000:], sep="\n")
            return 1
        data = json.loads((Path(found.group(0)) / "summary.json").read_text())
        record = data["records"][0]
        cost = record.get("cost_usd") or 0
        spent += cost
        entry = {
            "task": task,
            "seed": seed,
            "arm": arm,
            "inject": injection,
            "dry_run": args.dry_run,
            "run": found.group(0),
            "cost_usd": cost,
            "spent_usd": round(spent, 4),
            "passed": record.get("passed"),
            "verdict": record.get("verdict"),
            "injection_outcome": record.get("injection_outcome"),
        }
        with open(args.log, "a") as stream:
            stream.write(json.dumps(entry) + "\n")
        print(json.dumps(entry), flush=True)
        if record.get("api_error"):
            print("API ERROR STOP")
            return 0
    return 0


def clopper_pearson(k, n, alpha=0.05):
    """Exact two-sided interval for k successes of n."""

    def tail(p, upper):
        # P(X >= k) for upper=False bound search, P(X <= k) for upper=True.
        values = range(0, k + 1) if upper else range(k, n + 1)
        return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in values)

    def solve(f, target):
        lo, hi = 0.0, 1.0
        for _ in range(60):
            mid = (lo + hi) / 2
            if f(mid) > target:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    low = 0.0 if k == 0 else 1 - solve(lambda q: tail(1 - q, False), alpha / 2)
    high = 1.0 if k == n else solve(lambda p: tail(p, True), alpha / 2)
    return round(low, 3), round(high, 3)


def mcnemar(b, c):
    """Exact two-sided McNemar p-value for b and c discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    p = sum(math.comb(n, i) for i in range(0, min(b, c) + 1)) / 2**n
    return round(min(1.0, 2 * p), 4)


def load(entry):
    data = json.loads((Path(entry["run"]) / "summary.json").read_text())
    record = data["records"][0]
    return {**entry, "model": data["summary"].get("model"), "record": record}


KEEP = (
    "passed",
    "detail",
    "error",
    "model",
    "exit_code",
    "elapsed_seconds",
    "turns",
    "tool_calls",
    "tool_errors",
    "tools",
    "screenshots",
    "cost_usd",
    "usage",
    "reply",
    "api_error",
    "time_split",
    "injection",
    "injection_outcome",
    "leftover_processes",
    "cleanup_error",
    "final_screenshot_error",
)


def median(values):
    values = [v for v in values if v is not None]
    return round(statistics.median(values), 1) if values else None


def summary(args):
    every = [load(e) for e in entries(args.log) if not e.get("dry_run")]
    for r in every:
        r["surface"] = surface(r)
        r["cli"] = init_event(r).get("claude_code_version")
        invalid = bool(r["record"].get("api_error"))
        r["verdict"] = (
            "invalid (api error)"
            if invalid
            else ("pass" if r["record"].get("passed") else "fail")
        )
    if args.records:
        heads = ("task", "seed", "arm", "inject", "run", "surface", "cli", "verdict")
        with open(args.records, "w") as stream:
            for r in every:
                kept = {k: r["record"].get(k) for k in KEEP if k in r["record"]}
                if r["verdict"].startswith("invalid") and "injection" in kept:
                    kept["injection_outcome"] = r["verdict"]  # Not scored.
                stream.write(json.dumps({**{k: r[k] for k in heads}, **kept}) + "\n")
    runs = [r for r in every if not r["record"].get("api_error")]
    report = {
        "runs": len(runs),
        "invalid_api_error": [
            f"{r['task']} {r['seed']} {r['arm']} ({r['run']})"
            for r in every
            if r["record"].get("api_error")
        ],
        "cost_usd_all": round(sum(r["cost_usd"] for r in every), 3),
        "cost_usd_valid": round(sum(r["cost_usd"] for r in runs), 3),
    }
    cells = {}
    for r in runs:
        cells.setdefault((r["task"], r["arm"]), []).append(r)
    report["arms"] = {}
    for (task, arm), rs in sorted(cells.items()):
        k, n = sum(bool(r["passed"]) for r in rs), len(rs)
        recs = [r["record"] for r in rs]
        report["arms"][f"{task} {arm}"] = {
            "passed": f"{k}/{n}",
            "ci95": clopper_pearson(k, n),
            "turns_median": median([x.get("turns") for x in recs]),
            "tool_calls_median": median([x.get("tool_calls") for x in recs]),
            "wall_s_median": median([x.get("elapsed_seconds") for x in recs]),
            "cost_usd": round(sum(x.get("cost_usd") or 0 for x in recs), 3),
            "outcomes": [
                x.get("injection_outcome") for x in recs if x.get("injection")
            ],
            "seed_surface": [f"{r['seed']}/{r['surface']}" for r in rs],
        }
    for arm in ("baseline", "kill"):
        rs = [r for r in runs if r["arm"] == arm]
        k, n = sum(bool(r["passed"]) for r in rs), len(rs)
        if n:
            report[f"all {arm}"] = {"passed": f"{k}/{n}", "ci95": clopper_pearson(k, n)}
    pairs = {}
    for r in runs:  # Matched within one tool surface only.
        if r["arm"] in ("baseline", "kill"):
            key = (r["task"], r["seed"], r["surface"])
            pairs.setdefault(key, {})[r["arm"]] = bool(r["passed"])
    complete = [p for p in pairs.values() if len(p) == 2]
    b = sum(p["baseline"] and not p["kill"] for p in complete)
    c = sum(p["kill"] and not p["baseline"] for p in complete)
    report["pairs"] = {
        "complete": len(complete),
        "baseline_only_passed": b,
        "kill_only_passed": c,
        "mcnemar_p": mcnemar(b, c),
    }
    print(json.dumps(report, indent=1))
    return 0


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    for name in ("run", "summary"):
        p = sub.add_parser(name)
        p.add_argument("--log", default="evidence/f2-trials.log")
        if name == "run":
            p.add_argument("--dry-run", action="store_true")
        else:
            p.add_argument("--records", help="write the raw records here (JSONL)")
    args = parser.parse_args()
    return run(args) if args.mode == "run" else summary(args)


if __name__ == "__main__":
    raise SystemExit(main())
