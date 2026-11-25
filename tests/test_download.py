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
from agent_desktop.worker import Worker, owned_processes, pdf_name

BODY = b"%PDF-1.4\n" + bytes(range(256)) * 400


def fixture_pdf(padding=b""):
    """A one-page PDF that pdf.js can show, with every byte value in a stream
    and bytes after %%EOF, so a re-encoded copy would not match its digest."""
    text = b"BT /F1 24 Tf 20 100 Td (Fixture page) Tj ET"
    blob = bytes(range(256)) * 64 + padding
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(text), text),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(blob), blob),
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out) + b"% trailing bytes \x00\xff\n"


PDF = fixture_pdf()
# Over two PDF_CHUNKs, so it crosses the bridge in three pieces.
BIG_PDF = fixture_pdf(os.urandom(13 * 1024 * 1024))


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

    def test_without_a_url_only_a_shown_pdf_is_saved(self):
        worker = fake_worker(self.home, like_firefox("x.pdf"))
        with self.assertRaisesRegex(ValueError, "this tab shows no PDF"):
            worker.browser_request({"action": "download"})
        self.assertEqual(sorted(os.listdir(self.home / "Downloads")), ["older.pdf"])

    def test_budget_covers_the_timeout(self):
        self.assertGreater(
            core.request_budget("browser", {"action": "download", "timeout": 500}), 500
        )


BLOB_PAGE = b"""<title>Blob</title><p id=state>loading</p><a id=blob>Open blob</a>
<script>
fetch("/doc.pdf").then(r => r.blob()).then(b => {
  document.getElementById("blob").href = URL.createObjectURL(b);
  document.getElementById("state").textContent = "ready";
});
</script>"""
FORM_PAGE = b"""<title>Report</title><form method=post action=/report>
<input name=month value=11><button>Make report</button></form>"""


class Files(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/login"):
            self.reply(b"<title>Signed in</title><p>Signed in</p>", "text/html")
        elif self.path.startswith("/doc.pdf"):
            if "sid=ok" not in (self.headers.get("Cookie") or ""):
                self.reply(b"<title>Forbidden</title><p>Sign in</p>", "text/html", 403)
            else:
                self.reply(PDF, "application/pdf")
        elif self.path.startswith("/big.pdf"):
            self.reply(BIG_PDF, "application/pdf")
        elif self.path.startswith("/blob.html"):
            self.reply(BLOB_PAGE, "text/html")
        elif self.path.startswith("/form.html"):
            self.reply(FORM_PAGE, "text/html")
        else:
            super().do_GET()

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path == "/report" and "sid=ok" in (self.headers.get("Cookie") or ""):
            self.reply(PDF, "application/pdf")
        else:
            self.reply(b"<title>Forbidden</title><p>No</p>", "text/html", 403)

    def reply(self, body, content_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if self.path.startswith("/login"):
            self.send_header("Set-Cookie", "sid=ok; Path=/; HttpOnly")
        if content_type == "application/pdf":
            self.send_header("Content-Disposition", 'inline; filename="lecture 3.pdf"')
        http.server.BaseHTTPRequestHandler.end_headers(self)
        self.wfile.write(body)

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

    def test_a_pdf_the_viewer_shows_is_saved_as_the_original_bytes(self):
        digest = hashlib.sha256(PDF).hexdigest()
        self.browser("start", url=f"{self.base}/doc.pdf")
        # Without the cookie the server refuses: a page, not a PDF.
        self.assertTrue(self.browser("wait", text="Sign in", timeout=30)["satisfied"])
        with self.assertRaisesRegex(core.DesktopError, "this tab shows no PDF"):
            self.browser("download")
        self.browser("open", url=f"{self.base}/login")
        receipt = self.browser("download", url=f"{self.base}/doc.pdf?sig=abc")
        self.assertTrue(receipt["downloaded"], receipt)
        self.assertTrue(receipt["from_viewer"])
        self.assertEqual(receipt["content_type"], "application/pdf")
        self.assertEqual(receipt["name"], "lecture 3.pdf")
        self.assertEqual(receipt["bytes"], len(PDF))
        self.assertEqual(receipt["sha256"], digest)
        path = Path(receipt["file"])
        self.assertEqual(path.parent.name, "Downloads")
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertNotIn("sig=abc", json.dumps(receipt))
        # The tab shows the PDF now: without a url, that one is saved; a second
        # copy in Downloads gets a new name rather than replacing the first.
        again = self.browser("download")
        self.assertEqual(Path(again["file"]).name, "lecture 3(1).pdf")
        self.assertEqual(again["sha256"], digest)
        target = self.browser("download", to_file="course/lecture3.pdf")
        self.assertEqual(Path(target["file"]).read_bytes(), PDF)
        with self.assertRaisesRegex(core.DesktopError, "exists; pass overwrite"):
            self.browser("download", to_file="course/lecture3.pdf")
        self.assertEqual(
            self.browser("download", to_file="course/lecture3.pdf", overwrite=True)[
                "sha256"
            ],
            digest,
        )

    def test_a_large_pdf_crosses_in_chunks(self):
        self.browser("start", url=f"{self.base}/page.html")
        receipt = self.browser("download", url=f"{self.base}/big.pdf", timeout=120)
        self.assertTrue(receipt["from_viewer"], receipt)
        self.assertEqual(receipt["bytes"], len(BIG_PDF))
        self.assertEqual(receipt["sha256"], hashlib.sha256(BIG_PDF).hexdigest())
        self.assertEqual(Path(receipt["file"]).read_bytes(), BIG_PDF)

    def test_a_posted_or_blob_pdf_is_saved_from_the_tab(self):
        digest = hashlib.sha256(PDF).hexdigest()
        self.browser("start", url=f"{self.base}/login")
        self.assertTrue(self.browser("wait", text="Signed in", timeout=30)["satisfied"])
        self.browser("open", url=f"{self.base}/form.html")
        self.browser("click", text="Make report")
        self.wait_for(
            lambda: self.browser("tabs")["tabs"][-1]["url"].endswith("/report"), 30
        )
        receipt = self.wait_for(lambda: self.saved_from_tab(), 30)
        self.assertEqual(receipt["sha256"], digest)
        self.assertEqual(receipt["name"], "lecture 3.pdf")
        self.browser("open", url=f"{self.base}/blob.html")
        self.assertTrue(self.browser("wait", text="ready", timeout=30)["satisfied"])
        self.browser("click", text="Open blob")
        self.wait_for(
            lambda: self.browser("tabs")["tabs"][-1]["url"].startswith("blob:"), 30
        )
        receipt = self.wait_for(lambda: self.saved_from_tab(), 30)
        self.assertEqual(receipt["sha256"], digest)
        self.assertTrue(receipt["name"].endswith(".pdf"), receipt)

    def saved_from_tab(self):
        try:
            return self.browser("download")
        except core.DesktopError as error:
            if "this tab shows no PDF" in str(error):
                return None  # the viewer is still loading
            raise


class PdfNameTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(pdf_name("lecture 3.pdf", None), "lecture 3.pdf")
        self.assertEqual(pdf_name("../../x", None), "_.._x.pdf")
        self.assertEqual(pdf_name(None, "https://s.test/a/b%20c.PDF?sig=1"), "b c.PDF")
        self.assertEqual(pdf_name(None, "https://s.test/"), "document.pdf")
        self.assertEqual(pdf_name("", "blob:https://s.test/1234"), "document.pdf")


if __name__ == "__main__":
    unittest.main()
