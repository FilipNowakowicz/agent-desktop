"""Partial and scaled screenshots keep coordinates and observations usable."""

import os
import shutil
import tempfile
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
                # The token describes the desktop, not the image.
                self.assertEqual(capture["observation"], full["observation"])
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


if __name__ == "__main__":
    unittest.main()
