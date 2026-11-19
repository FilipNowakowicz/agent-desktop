"""Browser save: large text goes to a file, not into the reply."""

import json
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_desktop import core
from agent_desktop.worker import SAVE_BYTES, Worker, owned_processes

LISTING = json.dumps([{"id": i, "name": f"file {i}.pdf"} for i in range(5000)])


def worker_with(home, text, count=1):
    worker = Worker.__new__(Worker)
    worker.info = {"mode": "headless"}
    worker.env = {"HOME": str(home)}
    worker.effects = None
    worker.agent_tabs = set()

    def call(script, arguments, context):
        if "location.href" in script:
            return {
                "type": "string",
                "value": json.dumps({"url": "https://x.test/api", "title": ""}),
            }
        return {"type": "string", "value": text}

    bridge = mock.Mock()
    bridge.target.return_value = "context"
    bridge.find.return_value = {"count": count, "items": []}
    bridge.element.return_value = ({"sharedId": "e"}, {})
    bridge.call.side_effect = call
    worker.browser = (bridge, lambda: None)
    worker.attach_browser = mock.Mock(return_value=True)
    return worker


class SaveTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)

    def save(self, worker, **request):
        return worker.browser_request({"action": "save", **request})

    def test_large_text_is_saved_whole_and_not_returned(self):
        self.assertGreater(len(LISTING), 64 * 1024)
        saved = self.save(
            worker_with(self.home, LISTING), selector="pre", to_file="api/files.json"
        )
        path = self.home / "api/files.json"
        self.assertEqual(path.read_text(), LISTING)
        self.assertEqual(saved["bytes"], len(LISTING.encode()))
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertNotIn("file 1.pdf", json.dumps(saved))
        self.assertEqual(saved["url"], "https://x.test/api")

    def test_existing_files_ambiguous_targets_and_huge_text_are_refused(self):
        (self.home / "done.json").write_text("old")
        with self.assertRaisesRegex(ValueError, "exists; pass overwrite"):
            self.save(worker_with(self.home, "new"), to_file="done.json")
        self.save(worker_with(self.home, "new"), to_file="done.json", overwrite=True)
        self.assertEqual((self.home / "done.json").read_text(), "new")
        with self.assertRaisesRegex(ValueError, "2 visible elements match"):
            self.save(worker_with(self.home, "x", count=2), selector="pre", to_file="a")
        huge = "x" * (SAVE_BYTES + 1)
        with self.assertRaisesRegex(ValueError, "nothing was saved"):
            self.save(worker_with(self.home, huge), to_file="huge.txt")
        self.assertFalse((self.home / "huge.txt").exists())
        self.assertEqual(
            [p.name for p in self.home.iterdir() if p.name.startswith(".")], []
        )
        with self.assertRaisesRegex(ValueError, "needs to_file"):
            self.save(worker_with(self.home, "x"))


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "dbus-daemon", "firefox")),
    "desktop tools or Firefox unavailable",
)
class RealFirefoxSaveTests(unittest.TestCase):
    def setUp(self):
        from test_runtime import wait_for

        self.wait_for = wait_for
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-save-")
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
        self.wait_for(lambda: not owned_processes(self.token))
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temporary.cleanup()

    def test_a_long_element_is_saved_in_full(self):
        page = self.root / "long.html"
        page.write_text(f"<title>Long</title><pre id='data'>{LISTING}</pre>")
        browser = lambda **a: core.request(self.session, "browser", **a)  # noqa: E731
        browser(action="start", url=page.as_uri())
        self.assertTrue(
            browser(action="wait", selector="#data", timeout=30)["satisfied"]
        )
        saved = browser(action="save", selector="#data", to_file="data.json")
        self.assertEqual(json.loads(Path(saved["to_file"]).read_text())[-1]["id"], 4999)
        self.assertEqual(saved["bytes"], len(LISTING.encode()))


if __name__ == "__main__":
    unittest.main()
