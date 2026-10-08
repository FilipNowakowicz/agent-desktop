"""Action latency with and without the experimental effect ledger.

Runs the same 40 type/key actions in a terminal session for each setting and
prints median and 90th-percentile milliseconds per action.

    uv run scripts/effects_latency.py
"""

import json
import os
import statistics
import time

from agent_desktop import core


def measure(enabled):
    os.environ["AGENT_DESKTOP_EFFECTS"] = "1" if enabled else "0"
    session = core.create()["session"]
    try:
        core.request(session, "launch", argv=["foot", "--title", "term", "cat"])
        core.wait(session, title="term", timeout=10, stable_ms=500)
        times = []
        for index in range(20):
            for operation, arguments in (
                ("type", {"text": f"line {index}"}),
                ("key", {"key": "Return"}),
            ):
                started = time.monotonic()
                core.request(session, operation, **arguments)
                times.append((time.monotonic() - started) * 1000)
        return times
    finally:
        core.destroy(session)


results = {}
for enabled in (False, True, False, True):
    key = "effects" if enabled else "baseline"
    results.setdefault(key, []).extend(measure(enabled))
summary = {
    key: {
        "actions": len(values),
        "median_ms": round(statistics.median(values)),
        "p90_ms": round(sorted(values)[int(0.9 * len(values))]),
    }
    for key, values in results.items()
}
print(json.dumps(summary))
