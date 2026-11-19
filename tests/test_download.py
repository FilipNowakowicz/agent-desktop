"""Browser downloads return a receipt instead of leaving agents to poll Downloads."""

import functools
import hashlib
import http.server
import json
import os
import shutil
import stat
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from agent_desktop import core
from agent_desktop.worker import Worker, owned_processes

BODY = b"%PDF-1.4\n" + bytes(range(256)) * 400


def fake_worker(home, on_navigate, url="https://site.test/course"):
    """A worker whose Firefox 'downloads' by running on_navigate(Downloads)."""
    worker = Worker.__new__(Worker)
    worker.info = {"mode": "headless"}
    worker.env = {"HOME": str(home)}
    worker.effects = None
    worker.agent_tabs = set()
    worker.threads = []
    page = {"url": url, "title": "Course", "ready": "complete"}

    def call(script, arguments, context):
        if "readyState" in script:
            return {"type": "string", "value": page["ready"]}
        return {
            "type": "string",
            "value": json.dumps({"url": page["url"], "title": page["title"]}),
        }

    def command(method, params, timeout=30):
        if method == "browsingContext.navigate":
            thread = threading.Thread(
                target=on_navigate, args=(home / "Downloads", page), daemon=True
            )
            worker.threads.append(thread)
            thread.start()
        return {}

    bridge = mock.Mock()
    bridge.target.return_value = "context"
    bridge.call.side_effect = call
    bridge.command.side_effect = command
    worker.browser = (bridge, lambda: None)
    worker.attach_browser = mock.Mock(return_value=True)
    return worker


def like_firefox(name, chunks=4, delay=0.3):
    """Write NAME (empty) and NAME.part, grow the part, then rename it."""

    def run(folder, page):
        (folder / name).write_bytes(b"")
        part = folder / f"{name}.part"
        size = len(BODY) // chunks
        with open(part, "wb") as file:
            for index in range(chunks):
                file.write(
                    BODY[
                        index * size : (index + 1) * size
                        if index < chunks - 1
                        else None
                    ]
                )
                file.flush()
                time.sleep(delay)
        os.replace(part, folder / name)

    return run


class DownloadTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)
        (self.home / "Downloads").mkdir()
        (self.home / "Downloads" / "older.pdf").write_bytes(b"old")

    def download(self, worker, **request):
        return worker.browser_request(
            {"action": "download", "url": "https://site.test/f?token=SIGNED", **request}
        )

    def test_waits_for_the_part_file_and_returns_a_receipt(self):
        worker = fake_worker(self.home, like_firefox("notes.pdf"))
        receipt = self.download(worker)
        self.assertTrue(receipt["downloaded"])
        self.assertEqual(receipt["name"], "notes.pdf")
        self.assertEqual(receipt["bytes"], len(BODY))
        self.assertEqual(receipt["sha256"], hashlib.sha256(BODY).hexdigest())
        self.assertEqual(Path(receipt["file"]).read_bytes(), BODY)
        self.assertNotIn("SIGNED", json.dumps(receipt))

    def test_moves_the_file_to_a_private_destination(self):
        worker = fake_worker(self.home, like_firefox("notes.pdf", chunks=1))
        receipt = self.download(worker, to_file="course/week1/notes.pdf")
        target = self.home / "course/week1/notes.pdf"
        self.assertEqual(receipt["file"], str(target))
        self.assertEqual(target.read_bytes(), BODY)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertFalse((self.home / "Downloads/notes.pdf").exists())
        with self.assertRaisesRegex(ValueError, "exists; pass overwrite"):
            self.download(worker, to_file="course/week1/notes.pdf")

    def test_a_page_instead_of_a_download_is_reported(self):
        def login(folder, page):
            page.update(url="https://login.test/sso?state=SECRET", title="Sign in")

        worker = fake_worker(self.home, login)
        with self.assertRaisesRegex(ValueError, "opened a page instead") as refused:
            self.download(worker, timeout=30)
        self.assertIn("'Sign in' at https://login.test/sso)", str(refused.exception))
        self.assertNotIn("SECRET", str(refused.exception))

    def test_a_slow_download_is_not_reported_as_finished(self):
        worker = fake_worker(self.home, like_firefox("big.pdf", chunks=20, delay=0.5))
        with self.assertRaisesRegex(ValueError, "Still downloading .* Do not start it"):
            self.download(worker, timeout=2)
        for thread in worker.threads:
            thread.join()

    def test_host_sessions_and_bad_arguments_are_refused(self):
        worker = fake_worker(self.home, like_firefox("x.pdf"))
        for request, message in (
            ({"url": "file:///etc/passwd"}, "http"),
            ({"timeout": 0}, "timeout"),
            ({"timeout": 601}, "timeout"),
        ):
            with self.assertRaisesRegex(ValueError, message):
                worker.browser_request(
                    {"action": "download", "url": "https://site.test/x", **request}
                )
        worker.info = {"mode": "host"}
        with self.assertRaisesRegex(ValueError, "private sessions"):
            self.download(worker)

    def test_budget_covers_the_timeout(self):
        self.assertGreater(
            core.request_budget("browser", {"action": "download", "timeout": 500}), 500
        )


class Files(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        if self.path.startswith("/notes.bin"):
            self.send_header("Content-Disposition", 'attachment; filename="notes.bin"')
        super().end_headers()

    def log_message(self, *_):
        pass


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "dbus-daemon", "firefox")),
    "desktop tools or Firefox unavailable",
)
class RealFirefoxDownloadTests(unittest.TestCase):
    def setUp(self):
        from test_runtime import wait_for

        self.wait_for = wait_for
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-download-")
        self.root = Path(self.temporary.name)
        served = self.root / "served"
        served.mkdir()
        (served / "notes.bin").write_bytes(BODY)
        (served / "page.html").write_text("<title>Just a page</title><p>Hello</p>")
        self.server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(Files, directory=served)
        )
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
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
        self.server.shutdown()
        self.server.server_close()
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temporary.cleanup()

    def browser(self, action, **arguments):
        return core.request(self.session, "browser", action=action, **arguments)

    def test_download_and_page(self):
        self.browser("start", url=f"{self.base}/page.html")
        self.assertTrue(self.browser("wait", text="Hello", timeout=30)["satisfied"])
        receipt = self.browser("download", url=f"{self.base}/notes.bin?sig=abc")
        self.assertTrue(receipt["downloaded"], receipt)
        self.assertEqual(receipt["bytes"], len(BODY))
        self.assertEqual(receipt["sha256"], hashlib.sha256(BODY).hexdigest())
        # The tab stays on its page.
        self.assertEqual(self.browser("text", selector="p")["text"], "Hello")
        with self.assertRaisesRegex(core.DesktopError, "opened a page instead"):
            self.browser("download", url=f"{self.base}/page.html?x=1", timeout=20)


if __name__ == "__main__":
    unittest.main()
