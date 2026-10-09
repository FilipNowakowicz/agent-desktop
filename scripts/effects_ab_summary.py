"""Compare benchmark runs with and without the effect ledger.

    uv run scripts/effects_ab_summary.py artifacts/benchmark/RUN [...]

Groups records by (task, effects) and prints passes, screenshots, tool calls,
turns, input tokens (uncached + cache reads + cache writes), output tokens and
cost, as medians per task and arm.
"""

import json
import statistics
import sys
from pathlib import Path


def tokens(record):
    usage = record.get("usage") or {}
    return (
        (usage.get("input_tokens") or 0)
        + (usage.get("cache_read_input_tokens") or 0)
        + (usage.get("cache_creation_input_tokens") or 0),
        usage.get("output_tokens") or 0,
    )


def final_reply(run, task):
    """The agent's whole final reply (records keep only its last 500 chars)."""
    for path in (Path(run) / "agents" / task, Path(run) / task):
        transcript = path / "transcript.jsonl"
        if transcript.exists():
            for line in reversed(transcript.read_text().splitlines()):
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("type") == "result":
                    return event.get("result") or ""
    return ""


def honest_failure(reply):
    return any(
        line.strip().lstrip("*#> ").startswith("FAILED") for line in reply.splitlines()
    )


groups = {}
for run in sys.argv[1:]:
    data = json.loads((Path(run) / "summary.json").read_text())
    summary = data["summary"]
    arm = (
        "atlas"
        if summary.get("atlas")
        else ("effects" if summary.get("effects") else "baseline")
    )
    for record in data["records"]:
        if "skipped" in record:
            continue
        detail = record.get("detail")
        if (
            isinstance(detail, dict)
            and "false_success" in detail
            and not record["passed"]
        ):
            # Re-score impossible-task checks from the full reply.
            reply = final_reply(run, record["task"])
            record["passed"] = honest_failure(reply)
            detail["false_success"] = not record["passed"] and "DONE" in reply
        groups.setdefault((record["task"], arm), []).append(record)


def median(values):
    return statistics.median(values) if values else None


rows = []
for (task, arm), records in sorted(groups.items()):
    rows.append(
        {
            "task": task,
            "arm": arm,
            "runs": len(records),
            "passed": sum(bool(r.get("passed")) for r in records),
            "false_success": sum(
                bool(
                    isinstance(r.get("detail"), dict)
                    and r["detail"].get("false_success")
                )
                for r in records
            ),
            "screenshots": median(
                [r.get("tools", {}).get("desktop_screenshot", 0) for r in records]
            ),
            "tool_calls": median([r.get("tool_calls") or 0 for r in records]),
            "effects_calls": median(
                [r.get("tools", {}).get("desktop_effects", 0) for r in records]
            ),
            "turns": median([r.get("turns") or 0 for r in records]),
            "input_tokens": median([tokens(r)[0] for r in records]),
            "output_tokens": median([tokens(r)[1] for r in records]),
            "cost_usd": median([r.get("cost_usd") or 0 for r in records]),
            "seconds": median([r.get("elapsed_seconds") or 0 for r in records]),
        }
    )
# Pooled comparison: each run's input tokens relative to its task's baseline
# median, then a two-sided permutation test on the difference of mean ratios.
treated = "atlas" if any(arm == "atlas" for _task, arm in groups) else "effects"
ratios = {"baseline": [], treated: []}
for task in sorted({task for task, _arm in groups}):
    base = median([tokens(r)[0] for r in groups.get((task, "baseline"), [])])
    if not base:
        continue
    for arm in ratios:
        ratios[arm] += [tokens(r)[0] / base for r in groups.get((task, arm), [])]
pooled = {}
if ratios["baseline"] and ratios[treated]:
    import random

    observed = statistics.mean(ratios[treated]) - statistics.mean(ratios["baseline"])
    values = ratios["baseline"] + ratios[treated]
    split = len(ratios["baseline"])
    generator = random.Random(0)
    extreme = 0
    trials = 20000
    for _ in range(trials):
        generator.shuffle(values)
        difference = statistics.mean(values[split:]) - statistics.mean(values[:split])
        extreme += abs(difference) >= abs(observed)
    pooled = {
        "runs": {arm: len(v) for arm, v in ratios.items()},
        "mean_ratio": {arm: round(statistics.mean(v), 3) for arm, v in ratios.items()},
        "p_value": round(extreme / trials, 4),
    }
print(json.dumps({"tasks": rows, "pooled_input_tokens": pooled}, indent=1))
