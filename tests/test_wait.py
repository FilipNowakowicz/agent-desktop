"""Waiting for windows and a settled screen instead of polling screenshots."""

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from test_runtime import CHROMIUM, wait_for

from agent_desktop import core
from agent_desktop.worker import changed_box, owned_processes


def image(width, height, painted=()):
    pixels = bytearray(width * height * 3)
    for x, y in painted:
        pixels[(y * width + x) * 3] = 255
    return bytes(pixels)


class ChangedBoxTests(unittest.TestCase):
    def test_boxes(self):
        blank = image(40, 30)
        self.assertFalse(changed_box(blank, blank, 40, 30))
        self.assertEqual(
            changed_box(blank, image(40, 30, [(0, 0)]), 40, 30), [0, 0, 1, 1]
        )
        self.assertEqual(
            changed_box(blank, image(40, 30, [(39, 29)]), 40, 30), [39, 29, 1, 1]
        )
        self.assertEqual(
            changed_box(blank, image(40, 30, [(5, 7), (12, 3), (8, 20)]), 40, 30),
            [5, 3, 8, 18],
        )


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "foot", "dbus-daemon")),
    "desktop tools unavailable",
)
class WaitTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-wait-")
        self.root = root = Path(self.temporary.name)
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

    def launch(self, title, script):
        core.request(
            self.session,
            "launch",
            argv=["foot", "--config=/dev/null", f"--title={title}", "sh", "-c", script],
        )

    def test_window_appears_settles_and_goes(self):
        missing = core.wait(self.session, title="Absent", timeout=0.3)
        self.assertFalse(missing["satisfied"])
        self.assertEqual(missing["reason"], "no window")
        self.launch("Quiet window", "printf ready; sleep 60")
        found = core.wait(self.session, title="Quiet", stable_ms=500, timeout=15)
        self.assertTrue(found["satisfied"], found)
        self.assertEqual(found["windows"][0]["app_id"], "foot")
        self.assertGreaterEqual(found["elapsed_ms"], 500)
        self.assertTrue(core.wait(self.session, app_id="foot", timeout=1)["satisfied"])
        core.request(self.session, "key", key="F4", modifiers=["alt"])
        gone = core.wait(self.session, title="Quiet", gone=True, timeout=10)
        self.assertTrue(gone["satisfied"], gone)

    def test_changing_screen_never_settles(self):
        self.launch("Busy window", "while :; do date +%N; sleep 0.02; done")
        self.assertTrue(core.wait(self.session, title="Busy", timeout=15)["satisfied"])
        started = time.monotonic()
        busy = core.wait(self.session, stable_ms=500, timeout=2)
        self.assertFalse(busy["satisfied"])
        self.assertEqual(busy["reason"], "screen still changing")
        self.assertLess(time.monotonic() - started, 4)

    def test_frames_report_changed_region(self):
        first = core.request(self.session, "frame")
        self.assertIsNone(first["changed"])
        same = core.request(self.session, "frame", since=first["frame"])
        self.assertFalse(same["changed"])
        self.assertEqual(
            core.request(self.session, "frame", since="unknown")["changed"], "unknown"
        )
        self.launch("Region window", "sleep 60")
        core.wait(self.session, title="Region", timeout=15)
        changed = core.request(self.session, "frame", since=same["frame"])["changed"]
        self.assertGreater(changed[2] * changed[3], 10000)
        for bad in ({"timeout": -1}, {"timeout": 121}, {"stable_ms": 1.5}):
            with self.subTest(bad=bad), self.assertRaises(core.DesktopError):
                core.wait(self.session, **bad)

    @unittest.skipUnless(CHROMIUM, "chromium unavailable")
    def test_blinking_caret_counts_as_settled(self):
        page = self.root / "caret.html"
        page.write_text(
            "<!doctype html><title>caret</title>"
            '<input autofocus style="font-size:30px">'
        )
        argv = [
            CHROMIUM,
            f"--user-data-dir={self.root / 'chromium'}",
            "--no-first-run",
            "--ozone-platform=wayland",
            "--disable-gpu",
            "--password-store=basic",
        ]
        if os.geteuid() == 0:  # CI containers; never used for real profiles
            argv.append("--no-sandbox")
        app = core.request(self.session, "launch", argv=[*argv, page.as_uri()])
        found = core.wait(self.session, title="caret", timeout=30)
        if (
            not found["satisfied"]
            and "No usable sandbox" in Path(app["logs"]).read_text()
        ):
            self.skipTest("Chromium sandbox unavailable in this environment")
        self.assertTrue(found["satisfied"], found)
        # The caret blinks about every 0.5 s; 1.5 s must span several blinks.
        settled = core.wait(self.session, stable_ms=1500, timeout=30)
        self.assertTrue(settled["satisfied"], settled)


if __name__ == "__main__":
    unittest.main()
