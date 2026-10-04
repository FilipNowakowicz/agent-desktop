"""Action sequences run several steps but stop at the first surprise."""

import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

from test_runtime import wait_for

from agent_desktop import core
from agent_desktop.worker import owned_processes


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "foot", "dbus-daemon")),
    "desktop tools unavailable",
)
class ActionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-actions-")
        self.root = Path(self.temporary.name)
        self.previous = {
            k: os.environ.get(k) for k in ("AGENT_DESKTOP_STATE_DIR", "XDG_RUNTIME_DIR")
        }
        (self.root / "runtime").mkdir(mode=0o700)
        os.environ["AGENT_DESKTOP_STATE_DIR"] = str(self.root / "state")
        os.environ["XDG_RUNTIME_DIR"] = str(self.root / "runtime")
        self.session = core.create()["session"]
        self.token = core.manifest(self.session)["token"]

    def tearDown(self):
        core.destroy(self.session)
        wait_for(lambda: not owned_processes(self.token))
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temporary.cleanup()

    def fixture(self, name, wait=True):
        directory = self.root / name
        directory.mkdir()
        script = Path(__file__).resolve().parents[1] / "scripts/m0_terminal.py"
        core.request(
            self.session,
            "launch",
            argv=[
                "foot",
                "--config=/dev/null",
                f"--title={name}",
                sys.executable,
                str(script),
                str(directory),
            ],
        )
        if wait:
            wait_for((directory / "ready").exists)
            # Keys sent before the window has keyboard focus are dropped, while
            # later ones arrive: wait for activation, not just the process.
            wait_for(
                lambda: any(
                    w["title"] == name and "activated" in w["states"]
                    for w in core.request(self.session, "windows")["windows"]
                )
            )
            time.sleep(0.2)
        return directory

    def test_steps_run_in_order(self):
        first = self.fixture("first")
        observation = core.request(self.session, "screenshot")["observation"]
        result = core.run_actions(
            self.session,
            [
                {"action": "type", "text": "one "},
                {"action": "type", "text": "café"},
                {"action": "key", "key": "Return"},
            ],
            observation,
        )
        self.assertEqual(result, {"completed": 3, "total": 3, "stopped": None})
        wait_for((first / "typed.txt").exists)
        self.assertEqual((first / "typed.txt").read_text(), "one café")

    def test_expected_window_with_wait_step(self):
        self.fixture("first")
        observation = core.request(self.session, "screenshot")["observation"]
        second = self.fixture("second", wait=False)
        result = core.run_actions(
            self.session,
            [
                {"action": "wait", "title": "second", "stable_ms": 300, "timeout": 15},
                {"action": "type", "text": "after wait"},
                {"action": "key", "key": "Return"},
            ],
            observation,
        )
        self.assertIsNone(result["stopped"], result)
        wait_for((second / "typed.txt").exists)
        self.assertEqual((second / "typed.txt").read_text(), "after wait")

    def test_surprises_stop_before_input(self):
        first = self.fixture("first")
        stale = core.request(self.session, "screenshot")["observation"]
        second = self.fixture("second")
        result = core.run_actions(
            self.session,
            [{"action": "type", "text": "never"}, {"action": "key", "key": "Return"}],
            stale,
        )
        self.assertEqual(result["completed"], 0)
        self.assertEqual(result["stopped"]["step"], 0)
        self.assertIn("changed", result["stopped"]["reason"])
        failed = core.run_actions(
            self.session,
            [
                {"action": "wait", "title": "absent", "timeout": 0.2},
                {"action": "type", "text": "never"},
            ],
        )
        self.assertEqual(failed["stopped"], {"step": 0, "reason": "wait: no window"})
        unknown = core.run_actions(
            self.session,
            [{"action": "key", "key": "Return"}, {"action": "focus", "window": "w99"}],
        )
        self.assertEqual(unknown["completed"], 1)
        self.assertIn("Unknown window", unknown["stopped"]["reason"])
        time.sleep(0.5)
        self.assertFalse((first / "typed.txt").exists())
        self.assertEqual((second / "typed.txt").read_text(), "")
        for bad in (
            [],
            [{"action": "launch", "argv": ["foot"]}],
            [{"action": "type", "text": "x", "observation": stale}],
            [{"action": "key"}] * 51,
            "type",
        ):
            with self.subTest(bad=bad), self.assertRaises(core.DesktopError):
                core.run_actions(self.session, bad)


if __name__ == "__main__":
    unittest.main()
