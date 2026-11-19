"""Fixes from the 2026-11-19 field report: clearer refusals and hints."""

import json
import os
import stat
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from agent_desktop import core
from agent_desktop.worker import Worker

TARGET = {"selector": "pre", "text": None, "exact": False, "within": None}


def bridged_worker(home):
    worker = Worker.__new__(Worker)
    worker.info = {"mode": "headless"}
    worker.env = {"HOME": str(home)}
    worker.effects = None
    worker.agent_tabs = set()
    bridge = mock.Mock()
    bridge.target.return_value = "context"
    bridge.find.return_value = {"count": 1, "items": []}
    bridge.element.return_value = ({"sharedId": "e"}, {})
    bridge.call.return_value = {"type": "string", "value": '{"items": []}'}
    worker.browser = (bridge, lambda: None)
    worker.attach_browser = mock.Mock(return_value=True)
    return worker, bridge


class FieldFindingTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def test_gpu_startup_failure_says_what_to_do(self):
        hint = core.renderer_hint(
            "[render/egl.c:208] EGL_EXT_platform_base not supported"
        )
        self.assertIn("runtime's Mesa", hint)
        self.assertIn("without renderer", hint)
        self.assertEqual(core.renderer_hint("Xwayland failed to start"), "")

    def test_a_busy_profile_names_its_idle_holder(self):
        with mock.patch.dict(os.environ, {"AGENT_DESKTOP_STATE_DIR": str(self.root)}):
            profile = self.root / "profiles" / "work"
            (profile / "home").mkdir(parents=True)
            session = "abcdef123456"
            (profile / "last-session.json").write_text(json.dumps({"session": session}))
            trace = self.root / session / "trace.jsonl"
            trace.parent.mkdir()
            trace.write_text("")
            old = time.time() - 7 * 60
            os.utime(trace, (old, old))
            message = str(core.profile_busy("work", profile))
        self.assertIn(session, message)
        self.assertIn("idle for 7 min", message)
        self.assertIn("destroy it", message)

    def test_too_many_steps_say_how_many_and_run_nothing(self):
        worker, bridge = bridged_worker(self.root)
        steps = [{"action": "open", "url": "https://example.test/"}] * 31
        with self.assertRaisesRegex(ValueError, "31 actions, more than 30"):
            worker.browser_steps(steps)
        bridge.command.assert_not_called()

    def test_view_source_is_refused_before_anything_is_sent(self):
        worker, bridge = bridged_worker(self.root)
        with self.assertRaisesRegex(ValueError, "open the URL itself"):
            worker.browser_request(
                {"action": "open", "url": "view-source:https://example.test/a"}
            )
        bridge.command.assert_not_called()

    def test_send_creates_missing_private_folders_inside_home(self):
        worker, _ = bridged_worker(self.root)
        sent = worker.send_secret(
            {"to_file": "exports/pages/1.json", "reveal": 0}, TARGET
        )
        written = self.root / "exports/pages/1.json"
        self.assertEqual(sent["to_file"], str(written))
        self.assertEqual(written.read_text(), '{"items": []}')
        for folder in (self.root / "exports", self.root / "exports/pages"):
            self.assertEqual(stat.S_IMODE(folder.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(written.stat().st_mode), 0o600)

    def test_send_still_refuses_missing_folders_outside_home(self):
        worker, _ = bridged_worker(self.root / "home")
        (self.root / "home").mkdir()
        for path in ("../outside/x.json", str(self.root / "elsewhere/x.json")):
            with self.assertRaisesRegex(ValueError, "No such directory"):
                worker.send_secret({"to_file": path}, TARGET)
        self.assertFalse((self.root / "outside").exists())
        self.assertFalse((self.root / "elsewhere").exists())


if __name__ == "__main__":
    unittest.main()
