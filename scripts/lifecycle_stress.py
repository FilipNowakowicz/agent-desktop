"""Repeat create/type/daemonize/destroy cycles, optionally under CPU load."""

import argparse
import json
import multiprocessing
import os
import sys
import time
import uuid
from pathlib import Path

from agent_desktop import core
from agent_desktop.worker import owned_processes


def busy(stop):
    while not stop.is_set():
        pass


def wait_for(predicate, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    return None


def sleeping(duration):
    found = []
    for path in Path("/proc").iterdir():
        try:
            argv = (path / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if argv[:2] == [b"sleep", duration.encode()]:
            found.append(int(path.name))
    return found


def cycle(index, artifact):
    fixture = artifact / f"fixture-{index}"
    fixture.mkdir()
    text = f"cycle {index} café λ"
    duration = f"{time.time_ns() % 10**6 + 10**6}.5"
    result = {"cycle": index, "passed": False}
    started = time.monotonic()
    session = core.create()["session"]
    info = core.manifest(session)
    result["session"] = session
    try:
        script = Path(__file__).resolve().with_name("m0_terminal.py")
        core.request(
            session,
            "launch",
            argv=[
                "foot",
                "--config=/dev/null",
                sys.executable,
                str(script),
                str(fixture),
            ],
        )
        core.request(
            session,
            "launch",
            argv=["sh", "-c", f"setsid env -i sleep {duration} >/dev/null 2>&1 &"],
        )
        if not wait_for((fixture / "ready").exists, 15):
            raise RuntimeError("Terminal fixture did not start")
        result["ready_seconds"] = round(time.monotonic() - started, 3)
        core.request(session, "type", text=text)
        core.request(session, "key", key="Return")
        received = wait_for(
            lambda: (
                (fixture / "typed.txt").exists() and (fixture / "typed.txt").read_text()
            ),
            10,
        )
        result["received"] = received
        result["text_exact"] = received == text
        result["daemon_seen"] = bool(wait_for(lambda: sleeping(duration), 5))
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        try:
            result["cleanup"] = core.destroy(session)
        except core.DesktopError as error:
            result["cleanup_error"] = str(error)
        result["token_processes"] = owned_processes(info["token"])
        result["daemon_remaining"] = sleeping(duration)
        result["runtime_removed"] = not Path(info["runtime"]).exists()
        result["seconds"] = round(time.monotonic() - started, 3)
    result["passed"] = bool(
        result.get("text_exact")
        and result.get("daemon_seen")
        and not result["token_processes"]
        and not result["daemon_remaining"]
        and result["runtime_removed"]
        and "cleanup_error" not in result
    )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=10)
    parser.add_argument("--load", type=int, default=0, help="busy CPU processes")
    args = parser.parse_args()
    # Absolute: applications start in the session home, not this directory.
    artifact = (Path("artifacts/stress") / uuid.uuid4().hex[:12]).resolve()
    artifact.mkdir(parents=True, mode=0o700)
    os.environ["AGENT_DESKTOP_STATE_DIR"] = str((artifact / "state").resolve())
    stop = multiprocessing.Event()
    load = [
        multiprocessing.Process(target=busy, args=(stop,), daemon=True)
        for _ in range(args.load)
    ]
    for process in load:
        process.start()
    try:
        results = [cycle(i, artifact) for i in range(args.cycles)]
    finally:
        stop.set()
        for process in load:
            process.join(timeout=5)
    report = {
        "cycles": args.cycles,
        "load_processes": args.load,
        "cpu_count": os.cpu_count(),
        "passed": sum(r["passed"] for r in results),
        "failures": [r for r in results if not r["passed"]],
        "results": results,
    }
    (artifact / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    summary = {k: report[k] for k in ("cycles", "load_processes", "passed")}
    print(json.dumps({"artifacts": str(artifact), **summary}, indent=2))
    return 0 if report["passed"] == args.cycles else 1


if __name__ == "__main__":
    raise SystemExit(main())
