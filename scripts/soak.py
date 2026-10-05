"""Long-running soak: one persistent session plus repeated short sessions.

The persistent session types numbered lines into a terminal fixture and checks
every line arrives exactly, takes screenshots and waits; short sessions are
created, exercised and destroyed. Latencies, worker memory/CPU, state bytes
and leftover processes are sampled into a JSON report.
"""

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_desktop import core  # noqa: E402
from agent_desktop.worker import owned_processes  # noqa: E402

ECHO = """
import sys, pathlib
out = pathlib.Path(sys.argv[1])
(out.parent / "ready").touch()
for line in sys.stdin:
    with out.open("a") as f:
        f.write(line)
"""


def timed(latencies, name, function, *args, **kwargs):
    started = time.monotonic()
    result = function(*args, **kwargs)
    latencies.setdefault(name, []).append(time.monotonic() - started)
    return result


def process_usage(pid):
    stat = Path(f"/proc/{pid}/stat").read_text()
    fields = stat[stat.rindex(")") + 2 :].split()
    cpu = (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")
    rss = int(Path(f"/proc/{pid}/statm").read_text().split()[1]) * os.sysconf(
        "SC_PAGE_SIZE"
    )
    return round(cpu, 2), round(rss / 2**20, 1)


def wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def start_echo(session, directory):
    directory.mkdir(parents=True)
    script = directory / "echo.py"
    script.write_text(ECHO)
    core.request(
        session,
        "launch",
        argv=[
            "foot",
            "--config=/dev/null",
            sys.executable,
            str(script),
            str(directory / "lines.txt"),
        ],
    )
    if not wait_for((directory / "ready").exists, 15):
        raise RuntimeError("echo fixture did not start")
    wait_for(
        lambda: any(
            "activated" in w["states"]
            for w in core.request(session, "windows")["windows"]
        )
    )
    time.sleep(0.3)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=float, default=60)
    parser.add_argument("--report", default="artifacts/soak/report.json")
    args = parser.parse_args()
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="soak-"))
    latencies, samples, failures = {}, [], []
    persistent = core.create()["session"]
    info = core.manifest(persistent)
    start_echo(persistent, work / "persistent")
    lines = work / "persistent/lines.txt"
    sent = 0
    short_cycles = 0
    started = time.monotonic()
    next_sample = started
    try:
        while time.monotonic() - started < args.minutes * 60:
            # Persistent session: exact receipt of a numbered, mixed-script line.
            text = f"line {sent} café λ {sent * 7919 % 100000}"
            observation = timed(
                latencies, "screenshot", core.request, persistent, "screenshot"
            )["observation"]
            timed(
                latencies,
                "type",
                core.request,
                persistent,
                "type",
                text=text,
                observation=observation,
            )
            timed(latencies, "key", core.request, persistent, "key", key="Return")
            sent += 1
            if not wait_for(
                lambda count=sent: (
                    lines.exists() and len(lines.read_text().splitlines()) >= count
                ),
                5,
            ):
                failures.append(
                    {
                        "t": round(time.monotonic() - started),
                        "kind": "line missing",
                        "line": sent - 1,
                    }
                )
            elif lines.read_text().splitlines()[sent - 1] != text:
                failures.append(
                    {
                        "t": round(time.monotonic() - started),
                        "kind": "line wrong",
                        "line": sent - 1,
                    }
                )
            timed(latencies, "wait", core.wait, persistent, stable_ms=200, timeout=5)
            # Short session every tenth iteration.
            if sent % 10 == 0:
                try:
                    session = timed(latencies, "create", core.create)["session"]
                    token = core.manifest(session)["token"]
                    timed(
                        latencies,
                        "short_screenshot",
                        core.request,
                        session,
                        "screenshot",
                    )
                    timed(latencies, "destroy", core.destroy, session)
                    if not wait_for(lambda token=token: not owned_processes(token), 10):
                        failures.append(
                            {"kind": "leftover processes", "session": session}
                        )
                    short_cycles += 1
                except core.DesktopError as error:
                    failures.append(
                        {"kind": "short session", "error": str(error)[:300]}
                    )
            if time.monotonic() >= next_sample:
                cpu, rss = process_usage(info["worker_pid"])
                usage = core.usage()
                samples.append(
                    {
                        "minute": round((time.monotonic() - started) / 60, 1),
                        "lines": sent,
                        "worker_cpu_s": cpu,
                        "worker_rss_mb": rss,
                        "session_bytes": usage["session_bytes"],
                        "processes": len(
                            core.request(persistent, "status")["processes"]
                        ),
                    }
                )
                next_sample += 300
                write_report(
                    report_path, args, sent, short_cycles, latencies, samples, failures
                )
    finally:
        core.destroy(persistent)
    write_report(report_path, args, sent, short_cycles, latencies, samples, failures)
    print(json.dumps(json.loads(report_path.read_text())["summary"], indent=2))


def write_report(path, args, sent, short_cycles, latencies, samples, failures):
    def stats(values):
        values = sorted(values)
        return {
            "n": len(values),
            "p50_ms": round(statistics.median(values) * 1000, 1),
            "p95_ms": round(values[int(len(values) * 0.95) - 1] * 1000, 1)
            if len(values) > 1
            else None,
            "max_ms": round(values[-1] * 1000, 1),
        }

    report = {
        "summary": {
            "minutes": args.minutes,
            "lines_sent": sent,
            "short_sessions": short_cycles,
            "failures": len(failures),
            "latency": {k: stats(v) for k, v in latencies.items() if v},
        },
        "samples": samples,
        "failures": failures,
    }
    path.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
