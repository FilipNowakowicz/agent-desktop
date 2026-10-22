"""Durable jobs keep delivery evidence across client loss and cancellation."""

import copy
import json
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import test_browser
from test_runtime import wait_for

from agent_desktop import core, operations
from agent_desktop.worker import owned_processes, signal_process


class OperationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.session = "a" * 12
        self.ident = "b" * 32
        self.path_patch = mock.patch.object(
            core, "session_path", return_value=self.root
        )
        self.path_patch.start()
        self.record = {
            "schema_version": 1,
            "session": self.session,
            "operation_id": self.ident,
            "kind": "browser",
            "state": "submitted",
            "created_at": time.time() - 10,
            "completed": 0,
            "total": 2,
            "current_step": None,
            "steps": [
                {
                    "index": 0,
                    "request": {"action": "click", "selector": "#submit"},
                    "dispatch_state": "pending",
                },
                {
                    "index": 1,
                    "request": {"action": "click", "selector": "#submit"},
                    "dispatch_state": "pending",
                },
            ],
            "checks": [],
            "observation": None,
            "controller": "test",
            "release_lease": False,
            "timeout": 10,
        }
        self.path = operations.record_path(self.session, self.ident)

    def tearDown(self):
        self.path_patch.stop()
        self.temp.cleanup()

    def prepare(self):
        operations.save(self.path, self.record)
        self.path.with_suffix(".ready").touch()

    def test_cancel_before_dispatch_sends_nothing(self):
        self.prepare()
        self.path.with_suffix(".cancel").touch()
        with mock.patch.object(core, "request") as send:
            operations.run_job(self.session, self.ident)
        send.assert_not_called()
        self.assertEqual(
            operations.status(self.session, self.ident)["state"], "cancelled"
        )

    def test_browser_cancel_after_known_delivery_keeps_prefix(self):
        self.prepare()

        def send(session, operation, *args, **kwargs):
            if operation == "browser":
                self.path.with_suffix(".cancel").touch()
                return {"delivered": True, "context": "stable"}
            return {}

        with mock.patch.object(core, "request", side_effect=send) as requests:
            operations.run_job(self.session, self.ident)
        record = operations.status(self.session, self.ident)
        self.assertEqual(record["state"], "cancelled")
        self.assertEqual(record["completed"], 1)
        self.assertTrue(record["steps"][0]["result"]["delivered"])
        self.assertEqual(record["steps"][1]["dispatch_state"], "pending")
        self.assertEqual(
            sum(c.args[1] == "browser" for c in requests.call_args_list), 1
        )

    def test_lost_ack_and_cancel_are_unknown_and_never_retried(self):
        self.prepare()

        def send(session, operation, *args, **kwargs):
            if operation == "browser":
                self.path.with_suffix(".cancel").touch()
                raise core.DeliveryUnknown("reply lost")
            return {}

        with mock.patch.object(core, "request", side_effect=send) as requests:
            operations.run_job(self.session, self.ident)
        record = operations.status(self.session, self.ident)
        self.assertEqual(record["state"], "delivery_unknown")
        self.assertEqual(record["completed"], 0)
        self.assertEqual(record["steps"][0]["dispatch_state"], "uncertain")
        self.assertEqual(
            sum(c.args[1] == "browser" for c in requests.call_args_list), 1
        )

    def test_crash_before_and_after_dispatch_are_distinguished(self):
        for phase, state in (
            ("pending", "stopped"),
            ("dispatching", "delivery_unknown"),
        ):
            with self.subTest(phase=phase):
                self.record["steps"][0]["dispatch_state"] = phase
                operations.save(self.path, self.record)
                result = operations.status(self.session, self.ident)
                self.assertEqual(result["state"], state)
                if phase == "dispatching":
                    self.assertEqual(result["steps"][0]["dispatch_state"], "uncertain")

    def test_missing_illtyped_and_oversized_evidence_is_unknown(self):
        for mutation in (
            lambda r: r.pop("steps"),
            lambda r: r.update(completed="2"),
            lambda r: r["steps"][0].update(
                dispatch_state="acknowledged", result={"delivered": "yes"}
            ),
            lambda r: r.update(state="success"),
        ):
            record = copy.deepcopy(self.record)
            mutation(record)
            operations.save(self.path, record)
            with self.assertRaisesRegex(core.DesktopError, "unknown"):
                operations.status(self.session, self.ident)
        self.path.write_bytes(b"x" * (operations.MAX_BYTES + 1))
        with self.assertRaisesRegex(core.DesktopError, "unknown"):
            operations.status(self.session, self.ident)

    def test_private_only_validation_and_bounded_output(self):
        with mock.patch.object(
            core, "manifest", return_value={"mode": "host", "status": "ready"}
        ):
            with self.assertRaisesRegex(core.DesktopError, "private"):
                operations.start(self.session, [{"action": "key", "key": "Return"}])
        with self.assertRaisesRegex(core.DesktopError, "64 KiB"):
            operations.validate_actions(
                [{"action": "type", "text": "x" * 65536}], "actions"
            )
        reduced = operations.bounded_result(
            {"delivered": True, "observation_error": "bad read", "text": "x" * 10000}
        )
        self.assertTrue(reduced["delivered"])
        self.assertTrue(reduced["evidence_truncated"])
        self.assertEqual(reduced["observation_error"], "bad read")

    def test_gui_progress_reports_delivery_before_failed_observation(self):
        events = []

        def request(session, operation, *args, **kwargs):
            if operation == "type":
                return {"delivered": True}
            raise core.DesktopError("observation failed")

        with mock.patch.object(core, "request", side_effect=request):
            result = core.run_steps(
                "s",
                [{"action": "type", "text": "once"}],
                "baseline",
                "test",
                progress=lambda *args: events.append(args),
            )
        self.assertEqual(result["completed"], 1)
        self.assertEqual([e[1] for e in events], ["dispatching", "acknowledged"])
        self.assertTrue(events[1][2]["delivered"])


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "dbus-daemon", "firefox")),
    "desktop tools or Firefox unavailable",
)
class OperationDesktopTests(unittest.TestCase):
    setUp = test_browser.BrowserTests.setUp
    tearDown = test_browser.BrowserTests.tearDown
    browser = test_browser.BrowserTests.browser

    def prepare_page(self):
        self.page.write_text(
            '<title>Operation</title><input id="value"><button id="add">Add</button>'
            '<p id="count">0</p><script>add.onclick=()=>count.textContent=+count.textContent+1</script>'
        )
        self.browser("start", url=self.page.as_uri())

    def finished(self, ident):
        return wait_for(
            lambda: (
                r
                if (r := operations.status(self.session, ident))["state"]
                in operations.TERMINAL
                else None
            ),
            timeout=15,
        )

    def test_job_survives_submitting_client_exit_and_reconnect(self):
        self.prepare_page()
        actions = [
            {"action": "wait", "seconds": 0.5},
            {"action": "click", "selector": "#add"},
        ]
        client = subprocess.run(
            [
                sys.executable,
                "-c",
                "from agent_desktop.cli import main; raise SystemExit(main())",
                "operation",
                self.session,
                "start",
                "--kind",
                "browser",
                "--actions",
                json.dumps(actions),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(client.returncode, 0, client.stderr + client.stdout)
        submitted = json.loads(client.stdout)
        self.assertEqual(submitted["state"], "submitted")
        self.assertEqual(submitted["completed"], 0)
        result = self.finished(submitted["operation_id"])
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["completed"], 2)
        self.assertEqual(self.browser("text", selector="#count")["text"], "1")
        self.assertEqual(
            operations.list_operations(self.session)[0]["operation_id"],
            submitted["operation_id"],
        )

    def test_cancel_stays_responsive_during_worker_wait(self):
        self.prepare_page()
        job = operations.start(
            self.session,
            [{"action": "wait", "seconds": 2}, {"action": "click", "selector": "#add"}],
            kind="browser",
        )
        ident = job["operation_id"]
        wait_for(
            lambda: (
                operations.status(self.session, ident)["steps"][0]["dispatch_state"]
                == "dispatching"
            )
        )
        started = time.monotonic()
        requested = operations.cancel(self.session, ident)
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertTrue(requested["cancel_requested"])
        self.assertEqual(requested["state"], "running")
        result = self.finished(ident)
        self.assertEqual(result["state"], "cancelled")
        self.assertEqual(result["completed"], 1)
        self.assertEqual(self.browser("text", selector="#count")["text"], "0")

    def test_helper_death_marks_current_step_uncertain(self):
        self.prepare_page()
        job = operations.start(
            self.session,
            [{"action": "wait", "seconds": 2}, {"action": "click", "selector": "#add"}],
            kind="browser",
        )
        ident = job["operation_id"]
        running = wait_for(
            lambda: (
                r
                if (r := operations.status(self.session, ident))["steps"][0][
                    "dispatch_state"
                ]
                == "dispatching"
                else None
            )
        )
        self.assertTrue(
            signal_process(running["pid"], running["process_start"], signal.SIGKILL)
        )
        result = self.finished(ident)
        self.assertEqual(result["state"], "delivery_unknown")
        self.assertEqual(result["steps"][0]["dispatch_state"], "uncertain")
        self.assertEqual(
            core.request(
                self.session,
                "browser",
                running["controller"],
                action="text",
                selector="#count",
            )["text"],
            "0",
        )

    def test_gui_job_delivers_input_once_and_destroy_owns_helper(self):
        self.prepare_page()
        self.browser("click", selector="#value")
        job = operations.start(
            self.session, [{"action": "type", "text": "one delivery"}]
        )
        result = self.finished(job["operation_id"])
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["steps"][0]["dispatch_state"], "observed")
        self.assertTrue(result["steps"][0]["result"]["delivered"])
        self.assertEqual(
            self.browser("find", selector="#value")["items"][0]["value"], "one delivery"
        )
        running = operations.start(
            self.session, [{"action": "wait", "seconds": 2}], kind="browser"
        )
        wait_for(
            lambda: (
                operations.status(self.session, running["operation_id"])["state"]
                == "running"
            )
        )
        self.assertIn(running["pid"], owned_processes(self.token))
        core.destroy(self.session)
        wait_for(lambda: not owned_processes(self.token))

    def test_lease_gate_refuses_job_before_any_action(self):
        self.prepare_page()
        core.request(self.session, "lease", "other-controller")
        job = operations.start(
            self.session,
            [{"action": "click", "selector": "#add"}],
            kind="browser",
            controller="new-controller",
        )
        result = self.finished(job["operation_id"])
        self.assertEqual(result["state"], "stopped")
        self.assertEqual(result["completed"], 0)
        self.assertEqual(result["steps"][0]["dispatch_state"], "pending")
        self.assertEqual(
            core.request(
                self.session,
                "browser",
                "other-controller",
                action="text",
                selector="#count",
            )["text"],
            "0",
        )
