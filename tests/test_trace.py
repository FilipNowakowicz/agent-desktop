"""The action trace links requests to focus and outcome without typed content."""

import json
import os
import shutil
import unittest

import test_actions
from test_runtime import wait_for

from agent_desktop import core
from agent_desktop.worker import TRACE_BYTES, trace_arguments


class TraceArgumentTests(unittest.TestCase):
    def test_secrets_are_not_kept(self):
        kept = trace_arguments(
            {
                "operation": "type",
                "text": "hunter2",
                "observation": "abc@0,0,1",
                "controller": "agent",
            }
        )
        self.assertEqual(kept, {"text_chars": 7, "observation": "abc@0,0,1"})
        self.assertEqual(trace_arguments({"key": "a"})["key"], "<character>")
        self.assertEqual(trace_arguments({"key": "Return"})["key"], "Return")
        launch = trace_arguments({"argv": ["/usr/bin/curl", "-u", "user:pass"]})
        self.assertEqual(launch, {"program": "curl", "argc": 3})


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "foot", "dbus-daemon")),
    "desktop tools unavailable",
)
class TraceTests(unittest.TestCase):
    # The session lifecycle and terminal fixture of the action tests.
    setUp = test_actions.ActionTests.setUp
    tearDown = test_actions.ActionTests.tearDown
    fixture = test_actions.ActionTests.fixture

    def test_records_focus_and_outcome_without_text(self):
        directory = self.fixture("traced")
        observation = core.request(self.session, "screenshot")["observation"]
        core.request(
            self.session, "type", text="private words\n", observation=observation
        )
        with self.assertRaises(RuntimeError):
            core.request(self.session, "focus", window="w99")
        records = core.trace(self.session)["records"]
        operations = [r["operation"] for r in records]
        self.assertEqual(operations[-3:], ["screenshot", "type", "focus"])
        screenshot, typed, focus = records[-3:]
        self.assertEqual(screenshot["outcome"]["observation"], observation)
        self.assertEqual(typed["arguments"]["text_chars"], 14)
        self.assertEqual(typed["arguments"]["observation"], observation)
        self.assertTrue(typed["outcome"]["delivered"])
        self.assertEqual(typed["focus_before"]["id"], typed["focus_after"]["id"])
        self.assertIn("w99", focus["error"])
        raw = (core.session_path(self.session) / "trace.jsonl").read_text()
        self.assertNotIn("private words", raw)
        wait_for((directory / "typed.txt").exists)
        self.assertEqual((directory / "typed.txt").read_text(), "private words")

    def test_trace_is_bounded_and_survives_destroy(self):
        path = core.session_path(self.session) / "trace.jsonl"
        filler = json.dumps({"operation": "filler", "pad": "x" * 1000}) + "\n"
        path.write_text(filler * (TRACE_BYTES // len(filler) + 1))
        core.request(self.session, "screenshot")
        self.assertLessEqual(path.stat().st_size, TRACE_BYTES // 2 + 4096)
        records = core.trace(self.session, 1000)["records"]
        self.assertEqual(records[-1]["operation"], "screenshot")
        core.destroy(self.session)
        self.assertEqual(
            core.trace(self.session, 1)["records"][0]["operation"], "screenshot"
        )

    def test_can_be_disabled(self):
        # The worker reads the setting when the session starts.
        os.environ["AGENT_DESKTOP_TRACE"] = "0"
        try:
            session = core.create()["session"]
        finally:
            os.environ.pop("AGENT_DESKTOP_TRACE")
        try:
            core.request(session, "screenshot")
            self.assertEqual(core.trace(session)["records"], [])
        finally:
            core.destroy(session)
