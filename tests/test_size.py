"""Session size and enlarged crops."""

import os
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

from test_runtime import wait_for

from agent_desktop import core
from agent_desktop.worker import owned_processes, token_mapping


def png_size(path):
    with open(path, "rb") as stream:
        return list(struct.unpack(">II", stream.read(24)[16:24]))


class SizeValidationTests(unittest.TestCase):
    def test_forms_and_limits(self):
        self.assertIsNone(core.session_size(None))
        self.assertEqual(core.session_size("1920x1080"), [1920, 1080])
        self.assertEqual(core.session_size(" 1600X900 "), [1600, 900])
        self.assertEqual(core.session_size([2560, 1440]), [2560, 1440])
        for bad in ("1920", "100x100", "9999x9999", "axb", [1920], [True, 900], 5):
            with self.subTest(size=bad), self.assertRaises(core.DesktopError):
                core.session_size(bad)

    def test_only_headless_sessions_take_a_size(self):
        with self.assertRaisesRegex(core.DesktopError, "headless"):
            core.create("visible", size="1920x1080")

    def test_enlarged_crop_tokens_map_back(self):
        self.assertEqual(token_mapping("layout@10,20,2"), (10, 20, 2.0))
        with self.assertRaises(ValueError):
            token_mapping("layout@0,0,3")


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "dbus-daemon")),
    "desktop tools unavailable",
)
class SizedSessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-size-")
        root = Path(self.temporary.name)
        self.previous = {
            k: os.environ.get(k) for k in ("AGENT_DESKTOP_STATE_DIR", "XDG_RUNTIME_DIR")
        }
        (root / "runtime").mkdir(mode=0o700)
        os.environ["AGENT_DESKTOP_STATE_DIR"] = str(root / "state")
        os.environ["XDG_RUNTIME_DIR"] = str(root / "runtime")
        self.page = root / "page.html"
        self.page.write_text(
            "<title>Size</title><p id='size'></p><script>size.textContent = "
            "'viewport ' + innerWidth</script>"
        )
        self.session = core.create(size="1920x1080")["session"]
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

    def test_output_size_status_and_crops(self):
        status = core.request(self.session, "status")
        self.assertEqual(status["size"], [1920, 1080])
        whole = core.request(self.session, "screenshot")
        self.assertEqual(png_size(whole["path"]), [1920, 1080])
        crop = core.request(
            self.session, "screenshot", region=[100, 100, 200, 50], scale=2
        )
        self.assertEqual(png_size(crop["path"]), [400, 100])
        self.assertTrue(crop["observation"].endswith("@100,100,2"))
        with self.assertRaisesRegex(core.DesktopError, "region"):
            core.request(self.session, "screenshot", scale=2)

    @unittest.skipUnless(shutil.which("firefox"), "Firefox unavailable")
    def test_firefox_follows_the_size(self):
        core.request(self.session, "browser", action="start", url=self.page.as_uri())
        found = core.request(
            self.session, "browser", action="wait", text="viewport", timeout=30
        )
        self.assertTrue(found["satisfied"], found)
        text = core.request(self.session, "browser", action="text", selector="#size")
        width = int(text["text"].split()[1])
        # Maximised Firefox: wider than the default desktop could hold.
        self.assertGreater(width, 1280, text)


if __name__ == "__main__":
    unittest.main()
