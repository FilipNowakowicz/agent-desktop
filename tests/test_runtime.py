"""Real compositor tests, skipped when desktop tools are unavailable."""

import json
import os
import shutil
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path

from agent_desktop import core
from agent_desktop.worker import owned_processes


def wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for an observed result")


class RoutingTests(unittest.TestCase):
    def test_invalid_session_identifiers(self):
        for session in ("", "../main", "/tmp/other", None, "a" * 13):
            with self.subTest(session=session), self.assertRaises(core.DesktopError):
                core.request(session, "type", text="must not reach a display")

    def test_unknown_session(self):
        with self.assertRaises(core.DesktopError):
            core.request("0" * 12, "click", x=0, y=0)

    def test_invalid_mode(self):
        with self.assertRaises(core.DesktopError):
            core.create("physical")


@unittest.skipUnless(
    all(
        shutil.which(t)
        for t in ("labwc", "grim", "wtype", "wlrctl", "foot", "dbus-run-session")
    ),
    "desktop tools unavailable",
)
class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-test-")
        self.root = Path(self.temporary.name)
        self.previous = {
            k: os.environ.get(k) for k in ("AGENT_DESKTOP_STATE_DIR", "XDG_RUNTIME_DIR")
        }
        os.environ["AGENT_DESKTOP_STATE_DIR"] = str(self.root / "state")
        if not os.environ.get("XDG_RUNTIME_DIR"):
            (self.root / "run").mkdir(mode=0o700)
            os.environ["XDG_RUNTIME_DIR"] = str(self.root / "run")
        self.created = []

    def tearDown(self):
        for session in self.created:
            info = core.manifest(session)
            if info["status"] == "ready":
                core.destroy(session)
            wait_for(lambda info=info: not owned_processes(info["token"]))
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temporary.cleanup()

    def new_session(self, mode="headless"):
        session = core.create(mode)["session"]
        self.created.append(session)
        return session

    def fixture(self, session):
        directory = self.root / session
        directory.mkdir()
        script = Path(__file__).resolve().parents[1] / "scripts/m0_terminal.py"
        core.request(
            session,
            "launch",
            argv=[
                "foot",
                "--config=/dev/null",
                "--window-size-pixels=800x500",
                "--title=Session fixture",
                sys.executable,
                str(script),
                str(directory),
            ],
        )
        wait_for((directory / "ready").exists)
        time.sleep(0.4)
        return directory

    def exercise(self, mode):
        session = self.new_session(mode)
        fixture = self.fixture(session)
        self.assertTrue(
            any(
                "Session fixture" in w
                for w in core.request(session, "windows")["windows"]
            )
        )
        before = core.request(session, "screenshot")
        self.assertGreater(before["width"], 0)
        for operation, args in (
            ("click", {"x": -1, "y": 0}),
            ("click", {"x": 0, "y": 0, "button": "invalid"}),
            ("launch", {"argv": ["/not/an/executable"]}),
        ):
            with self.assertRaises(core.DesktopError):
                core.request(session, operation, **args)
        self.assertEqual(core.request(session, "status")["status"], "ready")
        core.request(session, "type", text="private café λ")
        core.request(session, "key", key="Return")
        wait_for((fixture / "mouse-ready").exists)
        self.assertEqual((fixture / "typed.txt").read_text(), "private café λ")
        current = core.request(session, "screenshot")
        core.request(
            session, "click", x=current["width"] // 2, y=current["height"] // 2
        )
        wait_for((fixture / "mouse.json").exists)
        self.assertEqual(json.loads((fixture / "mouse.json").read_text())["button"], 0)
        time.sleep(0.2)
        after = core.request(session, "screenshot")
        self.assertNotEqual(
            Path(before["path"]).read_bytes(), Path(after["path"]).read_bytes()
        )
        info = core.manifest(session)
        result = core.destroy(session)
        self.assertTrue(result["runtime_removed"])
        self.assertFalse(Path(info["runtime"]).exists())
        self.assertEqual(core.destroy(session)["status"], "stopped")
        with self.assertRaises(core.DesktopError):
            core.request(session, "type", text="after shutdown")

    def test_headless_round_trip(self):
        self.exercise("headless")

    @unittest.skipUnless(
        os.environ.get("DESKTOP_TEST_VISIBLE") == "1", "visible mode opt-in"
    )
    def test_visible_round_trip(self):
        self.exercise("visible")

    def test_two_sessions_have_distinct_input(self):
        first, second = self.new_session(), self.new_session()
        fixture_a, fixture_b = self.fixture(first), self.fixture(second)
        core.request(first, "type", text="only first")
        core.request(first, "key", key="Return")
        wait_for((fixture_a / "typed.txt").exists)
        self.assertFalse((fixture_b / "typed.txt").exists())
        core.request(second, "type", text="only second")
        core.request(second, "key", key="Return")
        wait_for((fixture_b / "typed.txt").exists)
        self.assertEqual((fixture_a / "typed.txt").read_text(), "only first")
        self.assertEqual((fixture_b / "typed.txt").read_text(), "only second")

    def test_crashes_preserve_errors_and_cleanup(self):
        session = self.new_session()
        app = core.request(
            session,
            "launch",
            argv=[sys.executable, "-c", "raise RuntimeError('fixture app failure')"],
        )
        wait_for(
            lambda: any(
                p["exit_code"] is not None
                for p in core.request(session, "status")["applications"]
            )
        )
        self.assertIn("fixture app failure", Path(app["logs"]).read_text())
        info = core.manifest(session)
        os.kill(info["compositor_pid"], signal.SIGKILL)
        wait_for(lambda: core.manifest(session)["status"] == "failed")
        self.assertFalse(Path(info["runtime"]).exists())
        with self.assertRaises(core.DesktopError):
            core.request(session, "screenshot")


if __name__ == "__main__":
    unittest.main()
