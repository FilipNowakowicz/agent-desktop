"""F1: a person takes control while a durable job runs (real private session)."""

import os
import shutil
import time
import unittest
from pathlib import Path

import test_browser
from test_runtime import wait_for

from agent_desktop import core, operations

PAGE = (
    '<title>Job</title><p id="count">0</p>'
    '<button id="add" onclick="count.textContent = +count.textContent + 1">Add</button>'
)


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "dbus-daemon", "firefox", "wayvnc")),
    "desktop tools, Firefox or wayvnc unavailable",
)
class TakeoverDuringJobTests(unittest.TestCase):
    setUp = test_browser.BrowserTests.setUp
    tearDown = test_browser.BrowserTests.tearDown
    browser = test_browser.BrowserTests.browser

    def finished(self, ident):
        return wait_for(
            lambda: (
                r
                if (r := operations.status(self.session, ident))["state"]
                in operations.TERMINAL
                else None
            ),
            timeout=20,
        )

    def test_takeover_stops_further_job_input(self):
        self.page.write_text(PAGE)
        self.browser("start", url=self.page.as_uri())
        self.assertTrue(self.browser("wait", selector="#add", timeout=20)["satisfied"])
        job = operations.start(
            self.session,
            [
                {"action": "click", "selector": "#add"},
                {"action": "wait", "seconds": 3},
                {"action": "click", "selector": "#add"},
                {"action": "click", "selector": "#add"},
            ],
            kind="browser",
        )
        ident = job["operation_id"]
        wait_for(
            lambda: (
                operations.status(self.session, ident)["steps"][1]["dispatch_state"]
                == "dispatching"
            ),
            timeout=20,
        )
        started = time.monotonic()
        taken = core.request(self.session, "take")
        acknowledged = time.monotonic() - started
        self.assertEqual(taken["owner"], "human")
        # The takeover is acknowledged while the job's pause is still running.
        self.assertLess(acknowledged, 2.5, acknowledged)
        result = self.finished(ident)
        # The pause gave way to the person: a known stop, nothing uncertain.
        self.assertEqual(result["state"], "stopped", result)
        self.assertEqual(result["completed"], 1, result)
        self.assertEqual(result["steps"][1]["dispatch_state"], "failed")
        self.assertIn("taking control", result["steps"][1]["result"]["reason"])
        self.assertEqual(result["steps"][2]["dispatch_state"], "pending")
        core.request(self.session, "release")
        time.sleep(1)
        # Only the click before the takeover reached the page.
        self.assertEqual(self.browser("text", selector="#count")["text"], "1")
        self.assertIsNone(core.request(self.session, "status")["lease"])

    def test_a_refused_take_leaves_later_waits_alone(self):
        self.page.write_text(PAGE)
        self.browser("start", url=self.page.as_uri())
        with self.assertRaisesRegex(core.DesktopError, "Keyboard"):
            core.request(self.session, "take", keyboard="!!")
        self.assertTrue(self.browser("wait", seconds=0.2)["satisfied"])
        # A marker left by a client that died before sending take is ignored
        # once it is old.
        marker = Path(core.manifest(self.session)["runtime"]) / "take-requested"
        marker.touch()
        old = time.time() - 60
        os.utime(marker, (old, old))
        self.assertTrue(self.browser("wait", seconds=0.2)["satisfied"])


if __name__ == "__main__":
    unittest.main()
