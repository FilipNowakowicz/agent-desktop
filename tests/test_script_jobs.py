"""Script job lifetime independent of desktop dependency availability."""

import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import anyio

from agent_desktop import script_jobs

# The job timeout starts when the script begins, so it covers only the script's own
# work. Tests that need a child process to be running first do not race a timeout:
# they wait for the child, then stop the job (`run_until_child`).
TIMEOUT = 1
# Upper bounds on a whole job. They separate "returned after cleanup" from "blocked
# on a child or never returned" (the scripts here would run for 30 s or more).
BOUND = 20


class ScriptJobTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="script-job-test-")
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def child_script(self, inherited=False, parent_wait=True):
        pid_file = self.root / "pid"
        # Written atomically, so a reader sees a whole pid or no file.
        child = (
            "import os,time; from pathlib import Path; "
            f"t = Path({str(pid_file) + '.tmp'!r}); t.write_text(str(os.getpid())); "
            f"t.rename({str(pid_file)!r}); time.sleep(60)"
        )
        redirect = (
            ""
            if inherited
            else ", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL"
        )
        return (
            "import subprocess,sys,time\n"
            f"subprocess.Popen([sys.executable, '-c', {child!r}]{redirect})\n"
            # Return only once the child is running, however loaded the machine.
            f"while not __import__('os').path.exists({str(pid_file)!r}):\n"
            "    time.sleep(.01)\n" + ("time.sleep(30)\n" if parent_wait else "")
        )

    def assert_child_reaped(self):
        pid = int((self.root / "pid").read_text())
        self.assertFalse(
            Path(f"/proc/{pid}").exists(), f"child {pid} survived or is a zombie"
        )

    def run_until_child(self, code):
        """Run a job, stop it once its child has written its pid, return the result.

        Stopping uses the same cleanup path as a timeout; waiting for the child
        replaces a deadline that load could reach before the child had started.
        """
        stop = threading.Event()
        outcome = []

        def job():
            script_jobs.CANCELLATION.set(stop)
            outcome.append(script_jobs.run(code, dict(os.environ), 300))

        thread = threading.Thread(target=job)
        thread.start()
        deadline = time.monotonic() + BOUND * 3
        while not (self.root / "pid").exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        stopped = time.monotonic()
        stop.set()  # also on a missing pid, so the job never outlives a failure
        thread.join(BOUND)
        self.assertFalse(thread.is_alive(), "job did not return after being stopped")
        self.assertLess(time.monotonic() - stopped, BOUND)
        return outcome[0]

    def test_stopping_reaps_redirected_child(self):
        result = self.run_until_child(self.child_script())
        self.assertTrue(result["cancelled"], result)
        self.assertEqual(result["cleanup"]["state"], "complete", result)
        self.assert_child_reaped()

    def test_stopping_is_bounded_with_child_holding_output(self):
        result = self.run_until_child(self.child_script(inherited=True))
        self.assertEqual(result["cleanup"]["state"], "complete", result)
        self.assert_child_reaped()

    def test_successful_script_does_not_leave_background_child(self):
        result = script_jobs.run(
            self.child_script(parent_wait=False), dict(os.environ), BOUND
        )
        self.assertEqual(result["exit_code"], 0, result)
        self.assertEqual(result["cleanup"]["state"], "complete", result)
        self.assert_child_reaped()

    def test_cancel_waits_for_child_cleanup(self):
        async def trial():
            async with anyio.create_task_group() as group:
                group.start_soon(
                    script_jobs.cancellable_call,
                    lambda: script_jobs.run(self.child_script(), dict(os.environ), 20),
                )
                with anyio.fail_after(BOUND):
                    while not (self.root / "pid").exists():
                        await anyio.sleep(0.02)
                group.cancel_scope.cancel()
            self.assert_child_reaped()

        anyio.run(trial)

    def test_term_ignoring_child_is_killed_and_reaped(self):
        code = self.child_script(inherited=True).replace(
            "import os,time;",
            "import os,time,signal; signal.signal(signal.SIGTERM, signal.SIG_IGN);",
        )
        result = self.run_until_child(code)
        self.assertEqual(result["cleanup"]["state"], "complete", result)
        self.assert_child_reaped()

    def test_timeout_does_not_count_slow_startup(self):
        # A loaded machine can take longer than a short timeout merely to start
        # the interpreter and import the helpers. Delay the supervisor longer
        # than the timeout: a script that finishes at once must not time out.
        launch = subprocess.Popen
        delay = "import runpy,sys,time; time.sleep(3); sys.argv[1:] = [sys.argv[-1]]; "

        def slow(argv, *args, **kwargs):
            if "-m" in argv:
                argv = [
                    *argv[:2],
                    "-c",
                    delay + "runpy.run_module('agent_desktop.script_jobs', "
                    "run_name='__main__')",
                    argv[-1],
                ]
            return launch(argv, *args, **kwargs)

        with mock.patch.object(script_jobs.subprocess, "Popen", slow):
            result = script_jobs.run("print('ran')", dict(os.environ), 2)
        self.assertNotIn("timed_out", result)
        self.assertEqual(result["exit_code"], 0, result)
        self.assertEqual(result["stdout"].strip(), "ran")
        self.assertGreaterEqual(result["seconds"], 3)

    def test_stopped_supervisor_does_not_defeat_script_timeout(self):
        pid_file = self.root / "pid"
        code = (
            "import os,signal,time\nfrom pathlib import Path\n"
            f"Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
            "os.kill(os.getppid(), signal.SIGSTOP)\ntime.sleep(30)\n"
        )
        result = script_jobs.run(code, dict(os.environ), TIMEOUT)
        self.assertTrue(result["timed_out"], result)
        self.assertTrue(result["supervisor_recovered"], result)
        self.assertEqual(result["cleanup"]["state"], "complete", result)
        self.assertLess(result["seconds"], BOUND)
        pid = int(pid_file.read_text())
        self.assertFalse(Path(f"/proc/{pid}").exists())

    def test_reports_returned_and_in_flight_operations(self):
        code = (
            "import time\nfrom agent_desktop.script_jobs import operation\n"
            "operation('first', lambda: None)\n"
            "operation('second', lambda: time.sleep(30))\n"
        )
        result = script_jobs.run(code, dict(os.environ), TIMEOUT)
        self.assertEqual(result["operations"]["returned"], 1)
        self.assertEqual(result["operations"]["in_flight"], ["second"])
        self.assertEqual(result["operations"]["delivery"], "unknown")

    def test_later_return_does_not_erase_prior_uncertain_delivery(self):
        code = (
            "from agent_desktop.script_jobs import operation\n"
            "try:\n    operation('first', lambda: 1 / 0)\n"
            "except ZeroDivisionError:\n    pass\n"
            "operation('second', lambda: None)\n"
        )
        result = script_jobs.run(code, dict(os.environ), BOUND)
        self.assertEqual(result["exit_code"], 0, result)
        self.assertEqual(result["operations"]["returned"], 1)
        self.assertEqual(result["operations"]["uncertain"], ["first"])
        self.assertEqual(result["operations"]["delivery"], "unknown")

    def test_output_is_bounded_and_stderr_is_preserved(self):
        result = script_jobs.run(
            "import sys,time\nprint('x' * 20000, flush=True)\n"
            "print('failure detail', file=sys.stderr, flush=True)\ntime.sleep(30)",
            dict(os.environ),
            TIMEOUT,
        )
        self.assertEqual(len(result["stdout"]), script_jobs.OUTPUT_LIMIT)
        self.assertIn("failure detail", result["stderr"])
        self.assertTrue(result["timed_out"])

    def test_continuous_output_is_capped_without_stalling_timeout(self):
        result = script_jobs.run(
            "import os\nwhile True:\n    os.write(1, b'x' * 65536)\n    os.write(2, b'y' * 65536)\n",
            dict(os.environ),
            TIMEOUT,
        )
        self.assertTrue(result["timed_out"], result)
        self.assertEqual(len(result["stdout"]), script_jobs.OUTPUT_LIMIT)
        self.assertEqual(len(result["stderr"]), script_jobs.OUTPUT_LIMIT)
        self.assertEqual(result["output_truncated"], {"stdout": True, "stderr": True})
        self.assertEqual(result["cleanup"]["state"], "complete", result)
        self.assertLess(result["seconds"], BOUND)

    def test_journal_limit_exposes_lost_coverage(self):
        result = script_jobs.run(
            "from agent_desktop import script_jobs\n"
            "script_jobs.JOURNAL_LIMIT = 100\n"
            "for n in range(10):\n    script_jobs.operation('read', lambda: None)\n",
            dict(os.environ),
            BOUND,
        )
        self.assertEqual(result["exit_code"], 0, result)
        self.assertTrue(result["operations"]["truncated"], result)
        self.assertEqual(result["operations"]["delivery"], "unknown")

    def test_cancellable_call_preserves_original_exception(self):
        async def trial():
            def fail():
                raise ValueError("original failure")

            with self.assertRaisesRegex(ValueError, "original failure"):
                await script_jobs.cancellable_call(fail)

        anyio.run(trial)

    def test_detached_child_is_explicitly_outside_cleanup_guarantee(self):
        pid_file = self.root / "pid"
        child = (
            "import os,time; from pathlib import Path; "
            f"t = Path({str(pid_file) + '.tmp'!r}); t.write_text(str(os.getpid())); "
            f"t.rename({str(pid_file)!r}); time.sleep(60)"
        )
        code = (
            "import os,subprocess,sys,time\n"
            f"subprocess.Popen([sys.executable, '-c', {child!r}], "
            "start_new_session=True, stdout=subprocess.DEVNULL, "
            "stderr=subprocess.DEVNULL)\n"
            f"while not os.path.exists({str(pid_file)!r}):\n"
            "    time.sleep(.01)\n"
            "time.sleep(30)"
        )
        result = self.run_until_child(code)
        try:
            self.assertEqual(result["cleanup"]["state"], "incomplete", result)
            self.assertEqual(
                result["cleanup"]["detached_descendants"], "not_guaranteed"
            )
        finally:
            os.kill(int(pid_file.read_text()), 9)
