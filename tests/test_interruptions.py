"""F1: durable jobs interrupted at each boundary (real private sessions).

Each test kills the job's helper at one boundary and checks what the record
says against what the page actually shows: delivered steps stay delivered,
work the application finishes later is not repeated, and verification is
never claimed without its checks.
"""

import json
import shutil
import signal
import time
import unittest

import test_browser
from test_runtime import wait_for

from agent_desktop import core, operations
from agent_desktop.worker import signal_process

PAGE = (
    '<title>Interrupted</title><p id="count">0</p>'
    '<button id="add" onclick="count.textContent = +count.textContent + 1">Add</button>'
    # Application work that finishes after the click was acknowledged.
    '<button id="slow" onclick="setTimeout(() => '
    'count.textContent = +count.textContent + 1, 1500)">Slow</button>'
)


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "dbus-daemon", "firefox")),
    "desktop tools or Firefox unavailable",
)
class InterruptionTests(unittest.TestCase):
    setUp = test_browser.BrowserTests.setUp
    tearDown = test_browser.BrowserTests.tearDown
    browser = test_browser.BrowserTests.browser

    def start_page(self):
        self.page.write_text(PAGE)
        self.browser("start", url=self.page.as_uri())
        self.assertTrue(self.browser("wait", selector="#slow", timeout=20)["satisfied"])

    def count(self):
        return self.browser("text", selector="#count")["text"]

    def kill_when(self, ident, ready):
        running = wait_for(
            lambda: r if ready(r := operations.status(self.session, ident)) else None,
            timeout=20,
        )
        self.assertTrue(
            signal_process(running["pid"], running["process_start"], signal.SIGKILL)
        )
        return wait_for(
            lambda: (
                r
                if (r := operations.status(self.session, ident))["state"]
                in operations.TERMINAL
                else None
            ),
            timeout=15,
        )

    def test_during_application_work(self):
        self.start_page()
        job = operations.start(
            self.session,
            [
                {"action": "click", "selector": "#slow"},
                {"action": "wait", "seconds": 5},
            ],
            kind="browser",
        )
        result = self.kill_when(
            job["operation_id"],
            lambda r: r["steps"][0]["dispatch_state"] in ("acknowledged", "observed"),
        )
        self.assertEqual(result["state"], "delivery_unknown")
        # The click was acknowledged before the kill and stays known.
        self.assertIn(
            result["steps"][0]["dispatch_state"], ("acknowledged", "observed")
        )
        self.assertEqual(result["completed"], 1)
        # The page finishes its own work once, and nothing repeats the click.
        self.assertTrue(wait_for(lambda: self.count() == "1", timeout=10))
        time.sleep(2)
        self.assertEqual(self.count(), "1")

    def test_after_a_committed_effect(self):
        self.start_page()
        job = operations.start(
            self.session,
            [{"action": "click", "selector": "#add"}, {"action": "wait", "seconds": 5}],
            kind="browser",
        )
        result = self.kill_when(
            job["operation_id"],
            lambda r: r["steps"][0]["dispatch_state"] in ("acknowledged", "observed"),
        )
        self.assertEqual(result["completed"], 1)
        self.assertEqual(self.count(), "1")
        # Reading the record again changes nothing and sends nothing.
        again = operations.status(self.session, job["operation_id"])
        self.assertEqual(again["state"], result["state"])
        self.assertEqual(self.count(), "1")

    def test_before_evidence_collection(self):
        self.start_page()
        context = self.browser("tabs")["tabs"][0]["context"]
        job = operations.start(
            self.session,
            [{"action": "click", "selector": "#add"}, {"action": "wait", "seconds": 5}],
            kind="browser",
            predicates=[
                {
                    "kind": "browser_context",
                    "context": context,
                    "url": self.page.as_uri(),
                }
            ],
        )
        result = self.kill_when(
            job["operation_id"],
            lambda r: r["steps"][1]["dispatch_state"] == "dispatching",
        )
        # The checks never ran, so nothing may claim they passed.
        self.assertEqual(result["verification"], "unknown")
        self.assertEqual(result["checks"], [])
        self.assertEqual(self.count(), "1")

    def test_during_evidence_collection(self):
        self.start_page()
        context = self.browser("tabs")["tabs"][0]["context"]
        # Accessibility-tree checks take long enough to interrupt between them.
        predicates = [{"kind": "browser_context", "context": context}] + [
            {"kind": "ui", "query": {"element": "Add"}} for _ in range(19)
        ]
        job = operations.start(
            self.session,
            [{"action": "click", "selector": "#add"}],
            kind="browser",
            predicates=predicates,
        )
        result = self.kill_when(
            job["operation_id"],
            lambda r: r["state"] == "running" and 1 <= len(r["checks"]) < 20,
        )
        # Every step finished before the checks began, so delivery is known;
        # only the verification is left unknown, with the checks that did run.
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["verification"], "unknown")
        self.assertLess(len(result["checks"]), 20)
        self.assertIn("checks", result["reason"])
        self.assertEqual(self.count(), "1")

    def test_cancel_during_application_work(self):
        # Cancellation is checked between steps: the pause in flight finishes,
        # the step after it never runs, and the page's own work still lands.
        self.start_page()
        job = operations.start(
            self.session,
            [
                {"action": "click", "selector": "#slow"},
                {"action": "wait", "seconds": 3},
                {"action": "click", "selector": "#add"},
            ],
            kind="browser",
        )
        ident = job["operation_id"]
        wait_for(
            lambda: (
                operations.status(self.session, ident)["steps"][0]["dispatch_state"]
                in ("acknowledged", "observed")
            ),
            timeout=20,
        )
        operations.cancel(self.session, ident)
        result = wait_for(
            lambda: (
                r
                if (r := operations.status(self.session, ident))["state"]
                in operations.TERMINAL
                else None
            ),
            timeout=15,
        )
        self.assertEqual(result["state"], "cancelled")
        self.assertEqual(result["completed"], 2)
        self.assertEqual(result["steps"][2]["dispatch_state"], "pending")
        self.assertTrue(wait_for(lambda: self.count() == "1", timeout=10))
        time.sleep(1)
        self.assertEqual(self.count(), "1")
        self.assertIsNone(core.request(self.session, "status")["lease"])

    def test_target_lost_after_an_interrupted_job_is_not_retargeted(self):
        # R1 under interruption: a job bound to one tab is killed, that tab
        # closes, and a later job for the same context must refuse rather than
        # act on whichever tab is left.
        self.start_page()
        context = self.browser("tabs")["tabs"][0]["context"]
        self.browser("open", url=self.page.as_uri(), new_tab=True)
        other = self.browser("tabs")["tabs"][-1]["context"]
        job = operations.start(
            self.session,
            [
                {"action": "wait", "seconds": 5, "context": context},
                {"action": "click", "selector": "#add", "context": context},
            ],
            kind="browser",
        )
        self.kill_when(
            job["operation_id"],
            lambda r: r["steps"][0]["dispatch_state"] == "dispatching",
        )
        self.browser("close", context=context)
        retry = operations.start(
            self.session,
            [{"action": "click", "selector": "#add", "context": context}],
            kind="browser",
        )
        result = wait_for(
            lambda: (
                r
                if (r := operations.status(self.session, retry["operation_id"]))[
                    "state"
                ]
                in operations.TERMINAL
                else None
            ),
            timeout=15,
        )
        # Refused before any input: a known stop, not an uncertain one.
        self.assertEqual(result["state"], "stopped", result)
        self.assertEqual(result["steps"][0]["dispatch_state"], "failed")
        self.assertIn("target_lost", json.dumps(result))
        self.assertEqual(
            self.browser("text", selector="#count", context=other)["text"], "0"
        )


if __name__ == "__main__":
    unittest.main()
