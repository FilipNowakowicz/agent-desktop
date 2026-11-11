"""Events for shells and notifiers: derived from persisted state, no content."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from test_runtime import wait_for

from agent_desktop import core, events, operations
from agent_desktop.worker import owned_processes


class EventDerivationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        patch = mock.patch.dict(os.environ, {"AGENT_DESKTOP_STATE_DIR": directory.name})
        patch.start()
        self.addCleanup(patch.stop)

    def write(self, name, **info):
        path = self.root / name
        path.mkdir(exist_ok=True)
        (path / "session.json").write_text(json.dumps({"id": name, **info}))
        return path

    def names(self, found):
        return [e["event"] for e in found]

    def test_requests_control_and_lifecycle(self):
        self.write("s1", status="ready", mode="headless", profile=None)
        first = events.state(offsets={})
        self.assertEqual(self.names(events.changes({}, first)), ["session_ready"])
        self.write(
            "s1",
            status="ready",
            mode="headless",
            control={"owner": "agent", "request": {"reason": "Sign in", "login": True}},
        )
        second = events.state(offsets={})
        requested = events.changes(first, second)
        self.assertEqual(self.names(requested), ["human_requested"])
        self.assertTrue(requested[0]["login"])
        self.assertIn("take s1", requested[0]["take_command"])
        self.write("s1", status="ready", mode="headless", control={"owner": "human"})
        third = events.state(offsets={})
        self.assertEqual(self.names(events.changes(second, third)), ["control_taken"])
        self.write(
            "s1",
            status="ready",
            mode="headless",
            control={"owner": "agent", "last": {"how": "released by the user"}},
        )
        fourth = events.state(offsets={})
        returned = events.changes(third, fourth)
        self.assertEqual(self.names(returned), ["control_returned"])
        self.assertEqual(returned[0]["how"], "released by the user")
        self.write("s1", status="failed", mode="headless", error="boom\nsecond line")
        failed = events.changes(fourth, events.state(offsets={}))
        self.assertEqual(failed[0]["event"], "session_failed")
        self.assertEqual(failed[0]["error"], "boom")

    def test_first_look_reports_only_live_state(self):
        # Ended sessions keep their record, sometimes with a request still in it;
        # a shell starting later must not raise banners for them.
        self.write("old", status="stopped", control={"request": {"reason": "stale"}})
        self.write("bad", status="failed", error="Compositor exited")
        self.write("live", status="ready", control={"request": {"reason": "now"}})
        host = self.root / core.HOST_REQUEST
        host.write_text(json.dumps({"id": "h0", "answer": "approved", "expires": 0}))
        finished = set()
        first = events.changes({}, events.state(offsets={}, finished=finished))
        self.assertEqual(self.names(first), ["session_ready", "human_requested"])
        self.assertEqual(first[1]["reason"], "now")
        self.assertEqual(finished, {"old", "bad"})
        # A follower reads ended sessions once, then skips them.
        self.write("old", status="stopped", control={"request": {"reason": "edited"}})
        again = events.state(offsets={}, finished=finished)
        self.assertEqual(set(again["sessions"]), {"live"})

    def test_session_ending_with_a_request_is_only_stopped(self):
        self.write("s1", status="ready", control={"request": {"reason": "x"}})
        before = events.state(offsets={})
        self.write("s1", status="stopped", control={"request": {"reason": "x"}})
        self.assertEqual(
            self.names(events.changes(before, events.state(offsets={}))),
            ["session_stopped"],
        )

    def test_returned_control_carries_no_url(self):
        self.write("s1", status="ready", control={"owner": "human"})
        before = events.state(offsets={})
        browser = {
            "restarted": False,
            "url": "https://private.example/path",
            "error": "port\nmore",
        }
        self.write(
            "s1",
            status="ready",
            control={"owner": "agent", "last": {"how": "released", "browser": browser}},
        )
        returned = events.changes(before, events.state(offsets={}))
        self.assertEqual(returned[0]["browser"], {"restarted": False, "error": "port"})
        self.assertNotIn("private.example", json.dumps(returned))

    def test_withdrawn_request(self):
        self.write("s1", status="ready", control={"request": {"reason": "x"}})
        before = events.state(offsets={})
        self.write("s1", status="ready", control={"request": None})
        self.assertEqual(
            self.names(events.changes(before, events.state(offsets={}))),
            ["human_withdrawn"],
        )

    def test_host_requests_answers_and_expiry(self):
        host = self.root / core.HOST_REQUEST
        host.write_text(
            json.dumps(
                {
                    "id": "h1",
                    "reason": "Open a page",
                    "minutes": 15,
                    "expires": time.time() + 60,
                }
            )
        )
        first = events.state(offsets={})
        requested = events.changes({}, first)
        self.assertEqual(self.names(requested), ["host_requested"])
        self.assertIn("host approve", requested[0]["approve_command"])
        host.write_text(
            json.dumps({**json.loads(host.read_text()), "answer": "declined"})
        )
        second = events.state(offsets={})
        answered = events.changes(first, second)
        self.assertEqual(
            answered, [{**answered[0], "event": "host_answered", "answer": "declined"}]
        )
        host.write_text(
            json.dumps({"id": "h2", "reason": "Again", "expires": time.time() - 1})
        )
        third = events.changes(second, events.state(offsets={}))
        self.assertEqual(self.names(third), ["host_expired"])

    def test_trace_outcomes_and_operations_without_content(self):
        path = self.write("s1", status="ready")
        offsets = {}
        events.state(offsets=offsets)  # the trace does not exist yet
        (path / "trace.jsonl").write_text("")
        events.state(offsets=offsets)
        records = [
            {
                "at": 1,
                "operation": "browser",
                "arguments": {"text_chars": 9},
                "outcome": {"completed": 1, "total": 3, "stopped": "ambiguous"},
            },
            {"at": 2, "operation": "click", "outcome": {"delivered": None}},
            {"at": 3, "operation": "type", "outcome": {"delivered": True}},
        ]
        with (path / "trace.jsonl").open("a") as stream:
            for record in records:
                stream.write(json.dumps(record) + "\n")
            stream.write('{"partial": ')  # an unfinished line waits for its end
        found = events.state(offsets=offsets)["outcomes"]
        self.assertEqual(
            [(e["event"], e.get("reason")) for e in found],
            [("batch_stopped", "ambiguous"), ("step_uncertain", None)],
        )
        operation = path / "operations"
        operation.mkdir()
        before = events.state(offsets={})
        (operation / ("a" * 32 + ".json")).write_text(
            json.dumps(
                {
                    "operation_id": "a" * 32,
                    "state": "delivery_unknown",
                    "completed": 1,
                    "total": 2,
                    "steps": [{"request": {"text": "SECRET"}}],
                }
            )
        )
        finished = events.changes(before, events.state(offsets={}))
        self.assertEqual(finished[0]["event"], "operation_finished")
        self.assertEqual(finished[0]["state"], "delivery_unknown")
        self.assertNotIn("SECRET", json.dumps(finished))


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "dbus-daemon", "foot")),
    "desktop tools unavailable",
)
class EventStreamTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-events-")
        root = Path(self.temporary.name)
        self.previous = {
            k: os.environ.get(k) for k in ("AGENT_DESKTOP_STATE_DIR", "XDG_RUNTIME_DIR")
        }
        (root / "runtime").mkdir(mode=0o700)
        os.environ["AGENT_DESKTOP_STATE_DIR"] = str(root / "state")
        os.environ["XDG_RUNTIME_DIR"] = str(root / "runtime")
        (root / "state").mkdir(mode=0o700)
        self.output = root / "events.jsonl"
        self.handle = self.output.open("w")
        self.stream = subprocess.Popen(
            [str(Path(sys.prefix) / "bin" / "agent-desktop"), "events", "--follow"],
            stdout=self.handle,
            stderr=subprocess.DEVNULL,
            env=os.environ.copy(),
        )

    def tearDown(self):
        self.stream.terminate()
        self.stream.wait(timeout=10)
        self.handle.close()
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temporary.cleanup()

    def seen(self):
        lines = self.output.read_text().splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def wait_event(self, name, timeout=10):
        return wait_for(
            lambda: next((e for e in self.seen() if e["event"] == name), None), timeout
        )

    def test_events_follow_the_existing_verbs(self):
        planted = "PLANTED-7f3c"
        session = core.create()["session"]
        token = core.manifest(session)["token"]
        try:
            self.assertTrue(self.wait_event("session_ready"))
            app = core.request(
                session,
                "launch",
                argv=["foot", "--config=/dev/null", f"--title={planted}"],
            )
            wait_for(lambda: core.request(session, "windows")["windows"])
            core.request(session, "type", text=planted)
            core.request(session, "request_human", reason="Sign in to the fixture")
            requested = self.wait_event("human_requested")
            self.assertEqual(requested["reason"], "Sign in to the fixture")
            self.assertTrue(requested["take_command"].endswith(f"take {session}"))
            core.request(session, "request_human", withdraw=True)
            self.assertTrue(self.wait_event("human_withdrawn"))
            core.request(session, "request_human", reason="Still pending at destroy")
            job = operations.start(session, [{"action": "wait", "seconds": 0.2}])
            finished = self.wait_event("operation_finished", timeout=20)
            self.assertEqual(finished["operation"], job["operation_id"])
            self.assertEqual(finished["state"], "completed")
            self.assertTrue(app["pid"])
        finally:
            core.destroy(session)
            wait_for(lambda: not owned_processes(token))
        self.assertTrue(self.wait_event("session_stopped"))
        self.assertNotIn(planted, self.output.read_text())
        # A later snapshot shows nothing for the ended session or its open request.
        self.assertEqual(events.snapshot(), [])


if __name__ == "__main__":
    unittest.main()
