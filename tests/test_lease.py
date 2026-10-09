"""One exclusive controller per session, enforced by a lease (real compositor)."""

import json
import os
import shutil
import sys
import tempfile
import threading
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
class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-lease-")
        self.root = Path(self.temporary.name)
        keys = (
            "AGENT_DESKTOP_STATE_DIR",
            "XDG_RUNTIME_DIR",
            "AGENT_DESKTOP_CONTROLLER",
        )
        self.previous = {k: os.environ.get(k) for k in keys}
        (self.root / "runtime").mkdir(mode=0o700)
        os.environ["AGENT_DESKTOP_STATE_DIR"] = str(self.root / "state")
        os.environ["XDG_RUNTIME_DIR"] = str(self.root / "runtime")
        os.environ.pop("AGENT_DESKTOP_CONTROLLER", None)
        self.session = core.create()["session"]
        self.token = core.manifest(self.session)["token"]

    def tearDown(self):
        # Destroy is anonymous and must work whoever holds the lease.
        core.destroy(self.session)
        wait_for(lambda: not owned_processes(self.token))
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temporary.cleanup()

    def fixture(self, name):
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
        wait_for((directory / "ready").exists)
        wait_for(
            lambda: any(
                w["title"] == name and "activated" in w["states"]
                for w in core.request(self.session, "windows")["windows"]
            )
        )
        time.sleep(0.2)
        return directory

    def lease(self):
        return core.request(self.session, "status")["lease"]

    def test_second_client_waits_for_release_or_expiry(self):
        fixture = self.fixture("leased")
        core.request(self.session, "type", "client-a", text="from A ")
        self.assertEqual(self.lease()["holder"], "client-a")
        for controller in ("client-b", None):
            with self.subTest(controller=controller):
                with self.assertRaisesRegex(
                    core.DesktopError, "LeaseHeld: Controller client-a holds"
                ):
                    core.request(self.session, "type", controller, text="INTRUDER")
                with self.assertRaisesRegex(core.DesktopError, "LeaseHeld"):
                    core.request(self.session, "launch", controller, argv=["foot"])
        # Reads stay available to everyone and do not take or renew the lease.
        core.request(self.session, "screenshot", "client-b")
        core.request(self.session, "windows", "client-b")
        self.assertEqual(
            core.request(self.session, "control")["lease"]["holder"], "client-a"
        )
        with self.assertRaisesRegex(core.DesktopError, "only it can release"):
            core.request(self.session, "lease", "client-b", action="release")
        released = core.request(self.session, "lease", "client-a", action="release")
        self.assertTrue(released["released"])
        self.assertIsNone(self.lease())

        core.request(self.session, "type", "client-b", text="then B")
        core.request(self.session, "key", "client-b", key="Return")
        wait_for((fixture / "typed.txt").exists)
        self.assertEqual((fixture / "typed.txt").read_text(), "from A then B")
        self.assertEqual(self.lease()["holder"], "client-b")

        # A short lease expires after inactivity, then another client may act.
        core.request(self.session, "lease", "client-b", seconds=1)
        with self.assertRaisesRegex(core.DesktopError, "LeaseHeld"):
            core.request(self.session, "move", "client-a", x=5, y=5)
        time.sleep(1.3)
        self.assertIsNone(self.lease())
        core.request(self.session, "move", "client-a", x=5, y=5)
        self.assertEqual(self.lease()["holder"], "client-a")
        # A person can break a stale lease explicitly.
        forced = core.request(
            self.session, "lease", "person", action="release", force=True
        )
        self.assertTrue(forced["released"])
        with self.assertRaisesRegex(core.DesktopError, "requires a controller"):
            core.request(self.session, "lease")
        with self.assertRaisesRegex(core.DesktopError, "Controller ids"):
            core.request(self.session, "move", "bad id!", x=1, y=1)

    def test_atlas_set_needs_the_lease(self):
        atlas = self.root / "atlas"
        atlas.mkdir()
        (atlas / "atlas-editor.json").write_text(
            json.dumps(
                {
                    "summary": {"app": "editor"},
                    "atlas": [
                        {
                            "kind": "menu",
                            "menu": "View",
                            "label": "Wrap",
                            "verified": True,
                            "effect": [
                                {
                                    "file": "~/.config/editor/settings.conf",
                                    "key": "[view] wrap",
                                    "from": None,
                                    "to": "true",
                                }
                            ],
                        }
                    ],
                }
            )
        )
        arguments = {"app": "editor", "control": "Wrap", "atlas": str(atlas)}
        core.request(self.session, "move", "client-a", x=5, y=5)
        with self.assertRaisesRegex(core.DesktopError, "LeaseHeld"):
            core.request(self.session, "set", "client-b", **arguments)
        home = core.session_path(self.session) / "home"
        self.assertFalse((home / ".config/editor/settings.conf").exists())
        result = core.request(self.session, "set", "client-a", **arguments)
        self.assertEqual(
            result["written"], ["~/.config/editor/settings.conf [view] wrap = true"]
        )
        self.assertIn("wrap=true", (home / ".config/editor/settings.conf").read_text())

    def test_action_sequence_cannot_be_interleaved(self):
        fixture = self.fixture("sequence")
        observation = core.request(self.session, "screenshot")["observation"]
        results = {}
        sequence = threading.Thread(
            target=lambda: results.setdefault(
                "a",
                core.run_actions(
                    self.session,
                    [
                        {"action": "type", "text": "alpha "},
                        {"action": "wait", "seconds": 2},
                        {"action": "type", "text": "omega"},
                        {"action": "key", "key": "Return"},
                    ],
                    observation,
                    controller="client-a",
                ),
            )
        )
        sequence.start()
        try:
            wait_for(lambda: (self.lease() or {}).get("holder") == "client-a")
            self.assertTrue(sequence.is_alive())
            with self.assertRaisesRegex(core.DesktopError, "LeaseHeld"):
                core.request(self.session, "type", "client-b", text="INTRUDER")
            # B's own sequence, named or anonymous, stops before sending anything.
            for controller in ("client-b", None):
                refused = core.run_actions(
                    self.session,
                    [{"action": "type", "text": "INTRUDER"}],
                    controller=controller,
                )
                self.assertEqual(refused["completed"], 0)
                self.assertIn("LeaseHeld", refused["stopped"]["reason"])
        finally:
            sequence.join(timeout=30)
        self.assertEqual(
            results["a"], {"completed": 4, "total": 4, "stopped": None}, results
        )
        wait_for((fixture / "typed.txt").exists)
        self.assertEqual((fixture / "typed.txt").read_text(), "alpha omega")
        # A named controller keeps its lease after the sequence.
        self.assertEqual(self.lease()["holder"], "client-a")
        core.request(self.session, "lease", "client-a", action="release")
        # An anonymous sequence holds a temporary lease only while it runs.
        done = core.run_actions(self.session, [{"action": "move", "x": 3, "y": 3}])
        self.assertIsNone(done["stopped"], done)
        self.assertIsNone(self.lease())


if __name__ == "__main__":
    unittest.main()
