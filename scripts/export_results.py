"""Write compact benchmark summaries (no transcripts or paths) for the repository."""

import json
import sys
from pathlib import Path

KEEP = (
    "task",
    "passed",
    "tool_calls",
    "tool_errors",
    "elapsed_seconds",
    "cost_usd",
    "tools",
    "usage",
    "turns",
    "model",
)


def main():
    output, runs = Path(sys.argv[1]), sys.argv[2:]
    exported = []
    for run in runs:
        data = json.loads((Path(run) / "summary.json").read_text())
        exported.append(
            {
                "run": Path(run).name,
                "summary": data["summary"],
                "records": [{k: r[k] for k in KEEP if k in r} for r in data["records"]],
            }
        )
    output.write_text(json.dumps(exported, indent=2) + "\n")


if __name__ == "__main__":
    main()
