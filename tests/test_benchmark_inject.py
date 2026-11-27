"""Failure injection during agent runs (benchmarks/inject.py, X2).

Real processes stand in for LibreOffice, Firefox and a durable job's helper:
sleeping Python scripts named like them (so their comm is that name), some
carrying a fake session token. A
fake call log plays the agent's completed tool calls. No desktop is needed.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from agent_desktop.worker import owned_processes
from benchmarks import inject
from scripts import benchmark

SLEEP = "import time; time.sleep(60)"


class InjectorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="inject-test-")
        self.root = Path(self.temporary.name)
        self.token = uuid.uuid4().hex
        self.processes = []
        self.log = self.root / "calls.jsonl"
        self.log.write_text("")

    def tearDown(self):
        for process in self.processes:
            if process.poll() is None:
                process.kill()
            process.wait()
        self.temporary.cleanup()

    def spawn(self, name=None, *, owned=True, argv=None):
        """A sleeping process: a script called `name` (its comm), or Python
        with `argv` as its command line."""
        env = dict(os.environ)
        if owned:
            env["AGENT_DESKTOP_SESSION_TOKEN"] = self.token
        if argv:
            argv = [argv[0], "-c", SLEEP, *argv[1:]]  # The rest: script args.
            options = {"executable": sys.executable, "stderr": subprocess.DEVNULL}
        else:
            program = self.root / name
            if not program.exists():
                program.write_text(f"#!{sys.executable}\n{SLEEP}\n")
                program.chmod(0o700)
            argv, options = [str(program)], {}
        process = subprocess.Popen(argv, env=env, **options)
        self.processes.append(process)
        time.sleep(0.1)  # Let it exec, so /proc shows its own name.
        return process

    def call(self, started):
        with self.log.open("a") as stream:
            stream.write(json.dumps({"tool": "x", "start": started, "end": started}))
            stream.write("\n")

    def injector(self, target, calls, **options):
        return inject.Injector(
            target, calls, self.log, lambda: owned_processes(self.token), **options
        ).start()

    def wait(self, process, timeout=5):
        try:
            process.wait(timeout)
        except subprocess.TimeoutExpired:
            pass
        return process.poll()

    def test_parse(self):
        self.assertEqual(inject.parse("office@2"), ("office", 2))
        self.assertEqual(inject.parse("worker@0"), ("worker", 0))
        for bad in ("office", "office@", "office@x", "shell@1", "@2"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                inject.parse(bad)

    def test_office_killed_after_the_nth_call_and_nothing_else(self):
        office = self.spawn("soffice.bin")
        splash = self.spawn("oosplash")
        browser = self.spawn("firefox")
        outsider = self.spawn("soffice.bin", owned=False)  # Not in the session.
        self.call(time.time() - 60)  # An earlier run's call does not count.
        injector = self.injector("office", 2)
        self.call(time.time())
        time.sleep(0.3)
        self.assertIsNone(office.poll(), "killed after one call")
        self.assertFalse(injector.record["fired"])
        self.call(time.time())
        self.assertTrue(injector.fired.wait(5))
        record = injector.stop()
        self.assertEqual(self.wait(office), -9)
        self.assertEqual(self.wait(splash), -9)
        self.assertIsNone(browser.poll())
        self.assertIsNone(outsider.poll())
        self.assertEqual(record["calls_at_fire"], 2)
        self.assertEqual(
            sorted(k["comm"] for k in record["killed"]), ["oosplash", "soffice.bin"]
        )

    def test_browser_and_its_children(self):
        main = self.spawn("firefox")
        other = self.spawn("foot")  # Another application in the session.
        # A content process: another comm, the browser in argv[0].
        content = self.spawn(argv=["/usr/lib/firefox/firefox"])
        injector = self.injector("browser", 0)
        self.assertTrue(injector.fired.wait(5))
        injector.stop()
        self.assertEqual(self.wait(main), -9)
        self.assertEqual(self.wait(content), -9)
        self.assertIsNone(other.poll())

    def test_helper_waits_until_a_job_runs(self):
        injector = self.injector("helper", 0)
        time.sleep(0.3)
        self.assertFalse(injector.record["fired"])  # No job yet.
        helper = self.spawn(argv=["python", "-m", "agent_desktop.operations"])
        self.assertTrue(injector.fired.wait(5))
        injector.stop()
        self.assertEqual(self.wait(helper), -9)

    def test_worker_target_is_the_given_pid(self):
        worker = self.spawn("worker-stand-in", owned=False)
        injector = self.injector("worker", 1, worker_pid=worker.pid)
        self.call(time.time())
        self.assertTrue(injector.fired.wait(5))
        self.assertEqual(
            injector.stop()["killed"], [{"pid": worker.pid, "comm": "worker"}]
        )
        self.assertEqual(self.wait(worker), -9)

    def test_never_fired_when_the_run_ends_first(self):
        office = self.spawn("soffice.bin")
        injector = self.injector("office", 3)
        self.call(time.time())
        record = injector.stop()
        self.assertFalse(record["fired"])
        self.assertIsNone(office.poll())
        self.assertEqual(inject.outcome({"injection": record}), "not fired")

    def test_outcome(self):
        fired = {"fired": True}
        self.assertIsNone(inject.outcome({"passed": True}))
        self.assertEqual(
            inject.outcome({"injection": fired, "passed": True}), "recovered"
        )
        self.assertEqual(
            inject.outcome({"injection": fired, "reply": "DONE. Saved."}),
            "false success",
        )
        self.assertEqual(
            inject.outcome({"injection": fired, "reply": "FAILED: Writer crashed"}),
            "honest failure",
        )
        self.assertEqual(inject.outcome({"injection": fired}), "honest failure")


class ApiErrorTests(unittest.TestCase):
    """A run the service ended (a usage limit, HTTP 429) is invalid: neither a
    pass, a failure nor an injection outcome."""

    # The result event of the 2026-11-26 run stopped by a usage limit.
    LIMIT = {
        "type": "result",
        "subtype": "success",
        "is_error": True,
        "terminal_reason": "api_error",
        "api_error_status": 429,
        "api_error_type": "rate_limit_error",
        "api_error": "usage_limit_reached",
        "result": "You've hit your 5-hour limit",
    }

    def test_api_error_found_in_the_result(self):
        self.assertEqual(benchmark.api_error(self.LIMIT), "usage_limit_reached")
        status_only = {**self.LIMIT, "api_error": None}
        self.assertEqual(benchmark.api_error(status_only), "HTTP 429")
        reason_only = {"is_error": True, "terminal_reason": "api_error"}
        self.assertEqual(benchmark.api_error(reason_only), "api_error")
        # A run stopped by its own budget cap is a scored failure, not invalid.
        capped = {"is_error": True, "subtype": "error_max_budget_usd"}
        self.assertIsNone(benchmark.api_error(capped))
        self.assertIsNone(benchmark.api_error({**self.LIMIT, "is_error": False}))

    def test_invalid_run_is_not_scored(self):
        fired = {"fired": True}
        record = {
            "injection": fired,
            "reply": self.LIMIT["result"],
            "api_error": "usage_limit_reached",
        }
        self.assertEqual(inject.outcome(record), "invalid (api error)")
        self.assertEqual(benchmark.verdict(record), "invalid (api error)")
        self.assertEqual(benchmark.verdict({"passed": True}), "pass")
        self.assertEqual(benchmark.verdict({"passed": False}), "fail")


if __name__ == "__main__":
    unittest.main()
