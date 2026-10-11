"""Compare model tiers (E1) across benchmark runs of the same suite.

    uv run scripts/tier_summary.py artifacts/benchmark/RUN [...]

Per model: passes, and medians over runs of wall time, turns, seconds per
turn, looks (screenshots), wrong-action proxy (tool errors), cost and the
time split. Per task and model: passes and median wall time.
"""

import json
import statistics
import sys
from pathlib import Path


def median(values):
    values = [v for v in values if v is not None]
    return round(statistics.median(values), 2) if values else None


models = {}
for run in sys.argv[1:]:
    if not (Path(run) / "summary.json").exists():
        print(f"skipping {run}: no summary (still running?)", file=sys.stderr)
        continue
    data = json.loads((Path(run) / "summary.json").read_text())
    for record in data["records"]:
        if "skipped" in record:
            continue
        model = record.get("model") or data["summary"].get("model") or "?"
        models.setdefault(model, []).append(record)

report = {}
for model, records in sorted(models.items()):
    split = [r.get("time_split") or {} for r in records]
    report[model] = {
        "runs": len(records),
        "passed": sum(bool(r.get("passed")) for r in records),
        "seconds_median": median([r.get("elapsed_seconds") for r in records]),
        "turns_median": median([r.get("turns") for r in records]),
        "seconds_per_turn": median(
            [
                r["elapsed_seconds"] / r["turns"]
                for r in records
                if r.get("turns") and r.get("elapsed_seconds")
            ]
        ),
        "looks_median": median([r.get("screenshots") for r in records]),
        "tool_errors": sum(r.get("tool_errors") or 0 for r in records),
        "cost_median_usd": median([r.get("cost_usd") for r in records]),
        "api_share": round(
            sum(s.get("api_seconds", 0) for s in split)
            / max(sum(r.get("elapsed_seconds") or 0 for r in records), 1e-9),
            3,
        ),
        "tasks": {
            task: {
                "passed": f"{sum(bool(r.get('passed')) for r in rs)}/{len(rs)}",
                "seconds_median": median([r.get("elapsed_seconds") for r in rs]),
            }
            for task in sorted({r["task"] for r in records})
            for rs in [[r for r in records if r["task"] == task]]
        },
    }
print(json.dumps(report, indent=1))
