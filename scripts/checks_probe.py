"""Model-free acceptance probe for scoped checks on a disposable private session."""

import hashlib
import json
import os
import statistics
import tempfile
import time
from pathlib import Path
from unittest import mock

from agent_desktop import checks, core


def main():
    core.use_runtime()
    with tempfile.TemporaryDirectory(prefix="desktop-check-probe-") as directory:
        root = Path(directory)
        (root / "runtime").mkdir(mode=0o700)
        with mock.patch.dict(
            os.environ,
            {
                "AGENT_DESKTOP_STATE_DIR": str(root / "state"),
                "XDG_RUNTIME_DIR": str(root / "runtime"),
            },
        ):
            session = core.create()["session"]
            try:
                home = core.session_path(session) / "home"
                path = home / "result.txt"
                path.write_text("verified\n")
                (home / "config.ini").write_text("[view]\nwrap=true\n")
                samples = [
                    (
                        "correct file",
                        {"kind": "file", "path": "~/result.txt", "text": "verified\n"},
                        "satisfied",
                    ),
                    (
                        "wrong file",
                        {"kind": "file", "path": "~/result.txt", "text": "wrong"},
                        "violated",
                    ),
                    (
                        "missing result",
                        {"kind": "file", "path": "~/missing", "contains": "done"},
                        "violated",
                    ),
                    (
                        "known absence",
                        {"kind": "file", "path": "~/missing", "exists": False},
                        "satisfied",
                    ),
                    (
                        "correct config",
                        {
                            "kind": "config",
                            "path": "~/config.ini",
                            "key": "view/wrap",
                            "value": "true",
                        },
                        "satisfied",
                    ),
                    (
                        "wrong config",
                        {
                            "kind": "config",
                            "path": "~/config.ini",
                            "key": "view/wrap",
                            "value": "false",
                        },
                        "violated",
                    ),
                ]
                results = []
                for name, predicate, expected in samples:
                    result = checks.evaluate(session, predicate)
                    results.append(
                        {
                            "name": name,
                            "expected": expected,
                            "observed": result["status"],
                        }
                    )
                # Inject only the unavailable UI observation; real control/lease
                # requests still go through the private worker.
                original = core.request
                for flags in (
                    {"truncated": True, "unreadable": 0},
                    {"truncated": False, "unreadable": 1},
                    {},
                ):

                    def read(
                        target, operation, controller=None, _flags=flags, **arguments
                    ):
                        if operation == "ui":
                            return {"nodes": [], **_flags}
                        return original(target, operation, controller, **arguments)

                    with mock.patch.object(core, "request", side_effect=read):
                        result = checks.evaluate(
                            session, {"kind": "ui", "claim": "absent"}
                        )
                    results.append(
                        {
                            "name": f"incomplete UI {flags}",
                            "expected": "unknown",
                            "observed": result["status"],
                        }
                    )
                elapsed = []
                for _ in range(100):
                    start = time.perf_counter()
                    checks.evaluate(session, samples[0][1])
                    elapsed.append((time.perf_counter() - start) * 1000)
                report = {
                    "source_sha256": hashlib.sha256(
                        Path(checks.__file__).read_bytes()
                    ).hexdigest(),
                    "cases": results,
                    "mismatches": sum(r["observed"] != r["expected"] for r in results),
                    "false_successes": sum(
                        r["observed"] == "satisfied" and r["expected"] != "satisfied"
                        for r in results
                    ),
                    "false_refusals": sum(
                        r["observed"] != "satisfied" and r["expected"] == "satisfied"
                        for r in results
                    ),
                    "file_check_latency_ms": {
                        "runs": len(elapsed),
                        "median": statistics.median(elapsed),
                        "p95": sorted(elapsed)[94],
                    },
                    "limits": "Seeded fixtures and one local private runtime; no model trials, human study or general reliability estimate.",
                }
                print(json.dumps(report, indent=2))
                return int(bool(report["mismatches"]))
            finally:
                core.destroy(session)


if __name__ == "__main__":
    raise SystemExit(main())
