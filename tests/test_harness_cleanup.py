"""The one-task client harness always destroys sessions, whatever the client does.

A fake client stands in for the paid model: it never contacts any service.
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

from agent_desktop.worker import owned_processes
from scripts import claude_code_task

HANGING_CLIENT = """
import json, sys, time
from agent_desktop import core
if sys.argv[1] == "desktop":
    created = core.create()
    print(json.dumps(created), file=sys.stderr, flush=True)
print("{not json", flush=True)
time.sleep(60)
"""


class HarnessCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-harness-")
        self.root = Path(self.temporary.name)
        (self.root / "runtime").mkdir(mode=0o700)
        self.artifact = self.root / "artifact"
        self.artifact.mkdir()
        self.state = self.root / "state"
        self.previous = {
            k: os.environ.get(k) for k in ("AGENT_DESKTOP_STATE_DIR", "XDG_RUNTIME_DIR")
        }
        os.environ["XDG_RUNTIME_DIR"] = str(self.root / "runtime")
        self.environment = {**os.environ, "AGENT_DESKTOP_STATE_DIR": str(self.state)}

    def tearDown(self):
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temporary.cleanup()

    def run_fake(self, mode, timeout):
        command = [sys.executable, "-c", HANGING_CLIENT, mode]
        started = time.monotonic()
        report = claude_code_task.run_task(
            command, self.environment, self.artifact, self.state, timeout
        )
        self.assertLess(time.monotonic() - started, timeout + 30)
        return report

    def test_timeout_and_bad_transcript_are_reported(self):
        report = self.run_fake("none", timeout=1)
        self.assertIsNone(report["exit_code"])
        self.assertIn("client timed out after 1 s", report["errors"])
        self.assertTrue(any(e.startswith("transcript:") for e in report["errors"]))
        self.assertEqual(report["cleanup"], {"sessions": {}, "leftovers": []})
        self.assertFalse(report["passed"])

    @unittest.skipUnless(
        all(shutil.which(t) for t in ("labwc", "grim", "dbus-daemon")),
        "desktop tools unavailable",
    )
    def test_session_of_a_timed_out_client_is_destroyed(self):
        report = self.run_fake("desktop", timeout=8)
        self.assertIn("client timed out after 8 s", report["errors"], report)
        created = json.loads(report["stderr"].strip().splitlines()[-1])
        session = created["session"]
        token = json.loads((self.state / session / "session.json").read_text())["token"]
        self.assertEqual(report["cleanup"]["sessions"][session]["status"], "stopped")
        self.assertEqual(report["cleanup"]["leftovers"], [])
        self.assertEqual(owned_processes(token), [])
        self.assertFalse(report["passed"])


if __name__ == "__main__":
    unittest.main()
