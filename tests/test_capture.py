"""Partial and scaled screenshots keep coordinates and observations usable."""

import json
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
    all(shutil.which(t) for t in ("labwc", "grim", "dbus-daemon")),
    "desktop tools unavailable",
)
class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-capture-")
        root = Path(self.temporary.name)
        self.previous = {
            k: os.environ.get(k) for k in ("AGENT_DESKTOP_STATE_DIR", "XDG_RUNTIME_DIR")
        }
        (root / "runtime").mkdir(mode=0o700)
        os.environ["AGENT_DESKTOP_STATE_DIR"] = str(root / "state")
        os.environ["XDG_RUNTIME_DIR"] = str(root / "runtime")
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

    def test_region_and_scale(self):
        full = core.request(self.session, "screenshot")
        width, height = full["width"], full["height"]
        self.assertEqual(full["region"], [0, 0, width, height])
        self.assertEqual(full["scale"], 1)
        for arguments, size in (
            ({"region": [100, 50, 200, 120]}, (200, 120)),
            ({"scale": 0.5}, (width // 2, height // 2)),
            ({"region": [0, 0, 400, 200], "scale": 0.25}, (100, 50)),
            ({"region": [width - 1, height - 1, 1, 1]}, (1, 1)),
        ):
            with self.subTest(arguments=arguments):
                capture = core.request(self.session, "screenshot", **arguments)
                self.assertEqual((capture["width"], capture["height"]), size)
                self.assertTrue(Path(capture["path"]).is_file())
                # The token checks the desktop layout; its suffix maps the image.
                layout, _, mapping = capture["observation"].partition("@")
                self.assertEqual(layout, full["observation"])
                self.assertTrue(mapping)
        for arguments in (
            {"region": [-1, 0, 10, 10]},
            {"region": [0, 0, width + 1, 10]},
            {"region": [0, 0, 0, 10]},
            {"region": [0, 0, 10]},
            {"region": [0, 0, 10, True]},
            {"region": "0,0,10,10"},
            {"scale": 0},
            {"scale": 1.5},
            {"scale": True},
        ):
            with self.subTest(arguments=arguments):
                with self.assertRaises(core.DesktopError):
                    core.request(self.session, "screenshot", **arguments)

    @unittest.skipUnless(shutil.which("foot"), "foot unavailable")
    def test_image_tokens_map_coordinates(self):
        fixture = Path(self.temporary.name) / "pointer"
        fixture.mkdir()
        script = Path(__file__).resolve().parents[1] / "scripts/pointer_fixture.py"
        core.request(
            self.session,
            "launch",
            argv=[
                "foot",
                "--config=/dev/null",
                sys.executable,
                str(script),
                str(fixture),
            ],
        )
        wait_for((fixture / "ready").exists)
        time.sleep(0.4)
        log = fixture / "events.jsonl"

        def presses():
            if not log.exists():
                return []
            events = [json.loads(line) for line in log.read_text().splitlines()]
            return [
                (e["column"], e["row"])
                for e in events
                if not e["motion"] and e.get("pressed", True) and not e["wheel"]
            ]

        full = core.request(self.session, "screenshot")
        cx, cy = full["width"] // 2, full["height"] // 2
        core.request(self.session, "click", x=cx, y=cy, observation=full["observation"])
        reference = wait_for(presses)[-1]
        half = core.request(self.session, "screenshot", scale=0.5)
        self.assertIn("@0,0,0.5", half["observation"])
        crop = core.request(
            self.session, "screenshot", region=[cx - 50, cy - 40, 100, 80]
        )
        for observation, x, y in (
            (half["observation"], cx / 2, cy / 2),
            (crop["observation"], 50, 40),
        ):
            with self.subTest(observation=observation):
                count = len(presses())
                core.request(self.session, "click", x=x, y=y, observation=observation)
                wait_for(lambda count=count: len(presses()) > count)
                self.assertEqual(presses()[-1], reference)
        # Every step of a sequence planned on a scaled screenshot is mapped.
        count = len(presses())
        result = core.run_actions(
            self.session,
            [
                {"action": "click", "x": cx / 2, "y": cy / 2},
                {"action": "click", "x": cx / 2, "y": cy / 2},
            ],
            half["observation"],
        )
        self.assertIsNone(result["stopped"], result)
        wait_for(lambda: len(presses()) >= count + 2)
        self.assertEqual(presses()[-2:], [reference, reference])
        with self.assertRaises(core.DesktopError):
            core.request(
                self.session,
                "click",
                x=1,
                y=1,
                observation=full["observation"] + "@0,0,7",
            )


if __name__ == "__main__":
    unittest.main()
