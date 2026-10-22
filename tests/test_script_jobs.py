"""Script job lifetime independent of desktop dependency availability."""

import os
import tempfile
import time
import unittest
from pathlib import Path

import anyio

from agent_desktop import script_jobs


class ScriptJobTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="script-job-test-")
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def child_script(self, inherited=False, parent_wait=True):
        pid_file = self.root / "pid"
        marker = self.root / "late-marker"
        child = (
            "import os,time; from pathlib import Path; "
            f"Path({str(pid_file)!r}).write_text(str(os.getpid())); "
            f"time.sleep(2); Path({str(marker)!r}).write_text('late')"
        )
        redirect = (
            ""
            if inherited
            else ", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL"
        )
        return (
            "import subprocess,sys,time\n"
            f"subprocess.Popen([sys.executable, '-c', {child!r}]{redirect})\n"
            + ("time.sleep(30)\n" if parent_wait else "time.sleep(.15)\n")
        )

    def assert_child_reaped(self):
        pid = int((self.root / "pid").read_text())
        self.assertFalse(
            Path(f"/proc/{pid}").exists(), f"child {pid} survived or is a zombie"
        )
        self.assertFalse((self.root / "late-marker").exists())

    def test_timeout_reaps_redirected_child(self):
        result = script_jobs.run(self.child_script(), dict(os.environ), timeout=0.5)
        self.assertTrue(result["timed_out"], result)
        self.assertEqual(result["cleanup"]["state"], "complete", result)
        self.assert_child_reaped()

    def test_timeout_is_bounded_with_child_holding_output(self):
        result = script_jobs.run(
            self.child_script(inherited=True), dict(os.environ), 0.5
        )
        self.assertLess(result["seconds"], 2)
        self.assertEqual(result["cleanup"]["state"], "complete", result)
        self.assert_child_reaped()

    def test_successful_script_does_not_leave_background_child(self):
        result = script_jobs.run(
            self.child_script(parent_wait=False), dict(os.environ), 5
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
                with anyio.fail_after(5):
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
        result = script_jobs.run(code, dict(os.environ), 0.5)
        self.assertEqual(result["cleanup"]["state"], "complete", result)
        self.assert_child_reaped()

    def test_reports_returned_and_in_flight_operations(self):
        code = (
            "import time\nfrom agent_desktop.script_jobs import operation\n"
            "operation('first', lambda: None)\n"
            "operation('second', lambda: time.sleep(30))\n"
        )
        result = script_jobs.run(code, dict(os.environ), 0.5)
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
        result = script_jobs.run(code, dict(os.environ), 5)
        self.assertEqual(result["exit_code"], 0, result)
        self.assertEqual(result["operations"]["returned"], 1)
        self.assertEqual(result["operations"]["uncertain"], ["first"])
        self.assertEqual(result["operations"]["delivery"], "unknown")

    def test_output_is_bounded_and_stderr_is_preserved(self):
        result = script_jobs.run(
            "import sys,time\nprint('x' * 20000, flush=True)\n"
            "print('failure detail', file=sys.stderr, flush=True)\ntime.sleep(30)",
            dict(os.environ),
            0.5,
        )
        self.assertEqual(len(result["stdout"]), script_jobs.OUTPUT_LIMIT)
        self.assertIn("failure detail", result["stderr"])
        self.assertTrue(result["timed_out"])

    def test_continuous_output_is_capped_without_stalling_timeout(self):
        result = script_jobs.run(
            "import os\nwhile True:\n    os.write(1, b'x' * 65536)\n    os.write(2, b'y' * 65536)\n",
            dict(os.environ),
            0.5,
        )
        self.assertTrue(result["timed_out"], result)
        self.assertEqual(len(result["stdout"]), script_jobs.OUTPUT_LIMIT)
        self.assertEqual(len(result["stderr"]), script_jobs.OUTPUT_LIMIT)
        self.assertEqual(result["output_truncated"], {"stdout": True, "stderr": True})
        self.assertEqual(result["cleanup"]["state"], "complete", result)
        self.assertLess(result["seconds"], 3)

    def test_journal_limit_exposes_lost_coverage(self):
        result = script_jobs.run(
            "from agent_desktop import script_jobs\n"
            "script_jobs.JOURNAL_LIMIT = 100\n"
            "for n in range(10):\n    script_jobs.operation('read', lambda: None)\n",
            dict(os.environ),
            5,
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
        code = (
            "import subprocess,sys,time\n"
            "subprocess.Popen([sys.executable, '-c', "
            f"{('import os,time; from pathlib import Path; Path(' + repr(str(pid_file)) + ').write_text(str(os.getpid())); time.sleep(4)')!r}], "
            "start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
            "time.sleep(30)"
        )
        result = script_jobs.run(code, dict(os.environ), 0.5)
        try:
            self.assertEqual(result["cleanup"]["state"], "incomplete", result)
            self.assertEqual(
                result["cleanup"]["detached_descendants"], "not_guaranteed"
            )
        finally:
            os.kill(int(pid_file.read_text()), 9)
            time.sleep(0.02)
