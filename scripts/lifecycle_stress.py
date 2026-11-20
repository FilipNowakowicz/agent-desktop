"""Repeat create/use/destroy cycles, optionally under CPU load.

Each cycle creates a private session (every --profile-every'th one on the named
profile "stress"), types into a terminal fixture, starts a daemonizing child
and a lease-holding launch, takes a screenshot and runs a short operation job,
then destroys the session. After each destroy it checks the state against
docs/project/LIFETIMES.md: no process carries the session token, the runtime
directory (control, Wayland and bus sockets) is gone, a non-profile home is
removed, the profile keeps every earlier cycle's file and is unlocked, the
session record keeps its manifest, trace, screenshot and operation record, and
an unrelated process with the same command line as the daemon is still running.
At the end, prune removes every record and never the profile.
"""

import argparse
import json
import multiprocessing
import os
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path

from agent_desktop import core, operations
from agent_desktop.worker import owned_processes

PROFILE = "stress"
CONTROLLER = "stress-client"


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


def open_descriptors():
    return len(os.listdir("/proc/self/fd"))


def cycle(index, artifact, duration, sentinel, profile=None, profile_cycles=0):
    """One create/use/destroy cycle; `sentinel` runs `sleep duration` outside it."""
    fixture = artifact / f"fixture-{index}"
    fixture.mkdir()
    text = f"cycle {index} café λ"
    result = {"cycle": index, "profile": profile, "passed": False}
    started = time.monotonic()
    created = core.create(profile=profile)
    session = created["session"]
    info = core.manifest(session)
    result["session"] = session
    try:
        result["lease_at_start"] = core.request(session, "status")["lease"]
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
        # The same command line as the unrelated sentinel: cleanup must go by
        # session ownership, never by name.
        core.request(
            session,
            "launch",
            argv=["sh", "-c", f"setsid env -i sleep {duration} >/dev/null 2>&1 &"],
        )
        # A named controller's launch takes the lease; a file in the home.
        core.request(
            session,
            "launch",
            CONTROLLER,
            argv=["sh", "-c", f'echo {index} >> "$HOME/cycles.log"'],
        )
        result["lease_holder"] = (core.request(session, "status")["lease"] or {}).get(
            "holder"
        )
        if not wait_for((fixture / "ready").exists, 15):
            raise RuntimeError("Terminal fixture did not start")
        result["ready_seconds"] = round(time.monotonic() - started, 3)
        core.request(session, "type", CONTROLLER, text=text)
        core.request(session, "key", CONTROLLER, key="Return")
        received = wait_for(
            lambda: (
                (fixture / "typed.txt").exists() and (fixture / "typed.txt").read_text()
            ),
            10,
        )
        result["received"] = received
        result["text_exact"] = received == text
        result["daemon_seen"] = bool(
            wait_for(lambda: set(sleeping(duration)) - {sentinel}, 5)
        )
        shot = core.request(session, "screenshot", CONTROLLER)
        result["screenshot"] = Path(shot["path"]).name
        core.request(session, "lease", CONTROLLER, action="release")
        job = operations.start(session, [{"action": "wait", "seconds": 0.1}])
        result["operation"] = job["operation_id"]
        finished = wait_for(
            lambda: (
                r
                if (r := operations.status(session, job["operation_id"]))["state"]
                in operations.TERMINAL
                else None
            ),
            15,
        )
        result["operation_state"] = finished and finished["state"]
        if profile:
            lines = wait_for(
                lambda: (
                    (Path(info["home"]) / "cycles.log").exists()
                    and (Path(info["home"]) / "cycles.log").read_text().split()
                ),
                5,
            )
            result["profile_lines"] = len(lines or [])
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        try:
            result["cleanup"] = core.destroy(session)
        except core.DesktopError as error:
            result["cleanup_error"] = str(error)
        result["seconds"] = round(time.monotonic() - started, 3)
        result.update(after_destroy(session, info, duration, sentinel))
    result["passed"] = bool(
        result.get("text_exact")
        and result.get("daemon_seen")
        and result.get("lease_at_start") is None
        and result.get("lease_holder") == CONTROLLER
        and result.get("operation_state") == "completed"
        and (not profile or result.get("profile_lines") == profile_cycles + 1)
        and "cleanup_error" not in result
        and not result["problems"]
    )
    return result


def after_destroy(session, info, duration, sentinel):
    """What LIFETIMES.md says remains after `destroy`; a list of problems."""
    problems = []
    root = core.session_path(session)
    token = owned_processes(info["token"])
    if token:
        problems.append(f"processes still carry the token: {token}")
    daemons = set(sleeping(duration)) - {sentinel}
    if daemons:
        problems.append(f"session daemon still running: {sorted(daemons)}")
    if sentinel not in sleeping(duration):
        problems.append("the unrelated process with the same command line was stopped")
    if Path(info["runtime"]).exists():
        problems.append("runtime directory (sockets) remains")
    for name in ("home", "config"):
        if (root / name).exists():
            problems.append(f"session {name} remains")
    manifest = core.manifest(session)
    if manifest["status"] != "stopped":
        problems.append(f"record status is {manifest['status']}")
    for name in ("session.log", "trace.jsonl"):
        if not (root / name).is_file():
            problems.append(f"record lost {name}")
    if not list((root / "screenshots").glob("*.png")):
        problems.append("record lost its screenshot")
    records = operations.list_operations(session)
    if [r["state"] for r in records] != ["completed"]:
        problems.append(f"operation records are {records}")
    if info.get("profile"):
        state = {p["profile"]: p for p in core.profiles()}.get(info["profile"])
        if not state or state["in_use"]:
            problems.append(f"profile not released: {state}")
    return {"problems": problems}


def run(artifact, cycles, load=0, profile_every=2):
    """Run the cycles with AGENT_DESKTOP_STATE_DIR already set; returns the report."""
    stop = multiprocessing.Event()
    workers = [
        multiprocessing.Process(target=busy, args=(stop,), daemon=True)
        for _ in range(load)
    ]
    for process in workers:
        process.start()
    duration = f"{time.time_ns() % 10**6 + 10**6}.5"
    environment = {
        k: v for k, v in os.environ.items() if k != "AGENT_DESKTOP_SESSION_TOKEN"
    }
    sentinel = subprocess.Popen(
        ["sleep", duration], env=environment, start_new_session=True
    )
    results, profile_cycles, descriptors = [], 0, []
    started = time.monotonic()
    try:
        for index in range(cycles):
            profile = PROFILE if profile_every and index % profile_every == 1 else None
            result = cycle(
                index, artifact, duration, sentinel.pid, profile, profile_cycles
            )
            profile_cycles += bool(profile)
            descriptors.append(open_descriptors())
            result["open_descriptors"] = descriptors[-1]
            results.append(result)
        pruned = core.prune()
        sentinel_alive = sentinel.poll() is None
    finally:
        stop.set()
        for process in workers:
            process.join(timeout=5)
        sentinel.kill()
        sentinel.wait()
    profiles = {p["profile"]: p for p in core.profiles()}
    profile_home = core.profile_path(PROFILE) / "home"
    kept_lines = (
        len((profile_home / "cycles.log").read_text().split())
        if (profile_home / "cycles.log").exists()
        else 0
    )
    seconds = [r["seconds"] for r in results]
    report = {
        "cycles": cycles,
        "load_processes": load,
        "cpu_count": os.cpu_count(),
        "profile_cycles": profile_cycles,
        "passed": sum(r["passed"] for r in results),
        "total_seconds": round(time.monotonic() - started, 1),
        "cycle_seconds": {
            "min": min(seconds, default=0),
            "median": statistics.median(seconds) if seconds else 0,
            "max": max(seconds, default=0),
        },
        # This client's descriptors after each cycle: a leak would grow.
        "open_descriptors": {
            "first": descriptors[0] if descriptors else 0,
            "last": descriptors[-1] if descriptors else 0,
        },
        "pruned": len(pruned["removed"]),
        "prune_kept": pruned["kept"],
        "profile_kept_lines": kept_lines,
        "profile_listed": PROFILE in profiles if profile_cycles else None,
        "sentinel_alive": sentinel_alive,
        "failures": [r for r in results if not r["passed"]],
        "results": results,
    }
    report["ok"] = bool(
        report["passed"] == cycles
        and report["pruned"] == cycles
        and not report["prune_kept"]
        and kept_lines == profile_cycles
        and report["profile_listed"] in (True, None)
        and sentinel_alive
        and report["open_descriptors"]["last"] <= report["open_descriptors"]["first"]
    )
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=10)
    parser.add_argument("--load", type=int, default=0, help="busy CPU processes")
    parser.add_argument(
        "--profile-every",
        type=int,
        default=2,
        help='use the profile "stress" every Nth cycle (0: never)',
    )
    args = parser.parse_args()
    # Absolute: applications start in the session home, not this directory.
    artifact = (Path("artifacts/stress") / uuid.uuid4().hex[:12]).resolve()
    artifact.mkdir(parents=True, mode=0o700)
    os.environ["AGENT_DESKTOP_STATE_DIR"] = str((artifact / "state").resolve())
    report = run(artifact, args.cycles, args.load, args.profile_every)
    (artifact / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    keys = (
        "cycles",
        "load_processes",
        "profile_cycles",
        "passed",
        "pruned",
        "total_seconds",
        "cycle_seconds",
        "open_descriptors",
        "ok",
    )
    print(json.dumps({"artifacts": str(artifact), **{k: report[k] for k in keys}}))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
