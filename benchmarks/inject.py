"""Failure injection during an agent run (X2, `scripts/benchmark.py --inject`).

Once the agent's N-th tool call has completed (the MCP server's call log has N
lines that started during this run), SIGKILL a target's processes in the
session. Targets are found among the processes carrying the session token, by
executable name or command line; the worker target is the session worker.
A helper target waits, after N calls, until a durable job's helper runs.
"""

import json
import os
import signal
import threading
import time
from pathlib import Path

TARGETS = ("office", "browser", "helper", "worker")


def parse(value):
    """`TARGET@N` -> (target, N)."""
    target, _, calls = value.partition("@")
    if target not in TARGETS or not calls.isdecimal():
        raise ValueError(f"expected TARGET@N, TARGET one of {', '.join(TARGETS)}")
    return target, int(calls)


def describe(pid):
    """(comm, argv) of a process, or None once it is gone."""
    try:
        comm = Path(f"/proc/{pid}/comm").read_text().strip()
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except OSError:
        return None
    return comm, [a.decode(errors="replace") for a in argv if a]


def matches(target, comm, argv):
    names = {comm, Path(argv[0]).name if argv else ""}
    if target == "office":
        return any(n.startswith(("soffice", "oosplash")) for n in names)
    if target == "browser":
        # Firefox's and Chromium's child processes keep the browser in argv[0].
        return any(k in n for n in names for k in ("firefox", "chromium", "chrome"))
    if target == "helper":
        return "agent_desktop.operations" in argv
    return False


class Injector:
    """Kill `target` in a session after `calls` completed tool calls.

    `owned` returns the session's processes (worker.owned_processes for its
    token); `worker_pid` is the session worker's, for the worker target.
    """

    def __init__(self, target, calls, call_log, owned, worker_pid=None, poll=0.02):
        self.target, self.calls, self.poll = target, calls, poll
        self.call_log, self.owned, self.worker_pid = Path(call_log), owned, worker_pid
        self.started = time.time()
        self.done = threading.Event()
        self.fired = threading.Event()
        self.record = {"target": target, "after_calls": calls, "fired": False}
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.started = time.time()
        self.thread.start()
        return self

    def completed_calls(self):
        """Logged calls that started during this run."""
        try:
            lines = self.call_log.read_text().splitlines()
        except OSError:
            return 0
        count = 0
        for line in lines:
            try:
                count += json.loads(line)["start"] >= self.started
            except (ValueError, KeyError, TypeError):
                pass
        return count

    def victims(self):
        if self.target == "worker":
            return [(self.worker_pid, "worker")] if self.worker_pid else []
        found = []
        for pid in self.owned():
            described = describe(pid)
            if described and matches(self.target, *described):
                found.append((pid, described[0]))
        return found

    def run(self):
        while not self.done.is_set():
            calls = self.completed_calls()
            if calls >= self.calls and self.kill(self.victims(), calls):
                return
            self.done.wait(self.poll)

    def kill(self, victims, calls):
        killed = []
        for pid, comm in victims:
            try:
                os.kill(pid, signal.SIGKILL)
                killed.append({"pid": pid, "comm": comm})
            except ProcessLookupError:
                pass
        if killed:
            self.record.update(
                fired=True,
                calls_at_fire=calls,
                seconds_after_start=round(time.time() - self.started, 1),
                killed=killed,
            )
            self.fired.set()
        return bool(killed)

    def stop(self):
        self.done.set()
        self.thread.join(timeout=5)
        return dict(self.record)


def outcome(record):
    """A kill run's outcome: recovered, honest failure, false success or not
    fired. None for a run without an injection."""
    injection = record.get("injection")
    if not injection:
        return None
    if not injection.get("fired"):
        return "not fired"
    if record.get("passed"):
        return "recovered"
    reply = (record.get("reply") or "").strip()
    return "false success" if reply.startswith("DONE") else "honest failure"
