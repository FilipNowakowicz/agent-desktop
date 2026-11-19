"""send source="cookies": a site's live browser cookies for a shell tool."""

import functools
import http.server
import json
import os
import shutil
import stat
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from agent_desktop import core
from agent_desktop.worker import Worker, netscape_cookies, owned_processes

TARGET = {"selector": None, "text": None, "exact": False, "within": None}


def cookie(domain, name, value, **extra):
    return {
        "domain": domain,
        "name": name,
        "value": {"type": "string", "value": value},
        "path": "/",
        **extra,
    }


JAR = [
    cookie(".uni.example", "SSO", "persistent-SECRET", secure=True, expiry=1900000000),
    cookie("video.uni.example", "AUTH", "session-SECRET", httpOnly=True),
    cookie("other.example", "TRACK", "unrelated-SECRET"),
    cookie("evil-uni.example", "NOPE", "lookalike-SECRET"),
]


def bridge_with(jar):
    bridge = mock.Mock()
    bridge.command.return_value = {"cookies": jar}
    return bridge


class CookieExportTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name)

    def test_only_the_site_and_its_parent_domains(self):
        data, count = netscape_cookies(bridge_with(JAR), "video.uni.example")
        text = data.decode()
        self.assertEqual(count, 2)
        lines = text.splitlines()
        self.assertEqual(lines[0], "# Netscape HTTP Cookie File")
        self.assertIn(
            ".uni.example\tTRUE\t/\tTRUE\t1900000000\tSSO\tpersistent-SECRET", lines
        )
        # A session cookie (no expiry), marked HttpOnly as curl and yt-dlp expect.
        self.assertIn(
            "#HttpOnly_video.uni.example\tFALSE\t/\tFALSE\t0\tAUTH\tsession-SECRET",
            lines,
        )
        self.assertNotIn("unrelated", text)
        self.assertNotIn("lookalike", text)

    def test_bad_sites_and_empty_jars_are_refused(self):
        for site in (None, "", "uni", "a b.example", "*.example"):
            with self.assertRaisesRegex(ValueError, "needs site"):
                netscape_cookies(bridge_with(JAR), site)
        with self.assertRaisesRegex(ValueError, "no cookies for nothing.example"):
            netscape_cookies(bridge_with(JAR), "nothing.example")

    def worker(self, mode="headless"):
        worker = Worker.__new__(Worker)
        worker.info = {"mode": mode}
        worker.env = {"HOME": str(self.home)}
        worker.effects = None
        worker.browser = (bridge_with(JAR), lambda: None)
        worker.attach_browser = mock.Mock(return_value=True)
        return worker

    def test_send_writes_a_private_file_and_reveals_nothing(self):
        sent = self.worker().send_secret(
            {"source": "cookies", "site": "uni.example", "to_file": "c/cookies.txt"},
            TARGET,
        )
        path = self.home / "c/cookies.txt"
        self.assertEqual(sent["cookies"], 2)
        self.assertEqual(sent["to_file"], str(path))
        self.assertNotIn("prefix", sent)
        self.assertNotIn("SECRET", json.dumps(sent))
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertTrue(path.read_text().endswith("\n"))

    def test_never_from_the_persons_firefox(self):
        with self.assertRaisesRegex(ValueError, "private sessions only"):
            self.worker("host").send_secret(
                {"source": "cookies", "site": "uni.example", "to_file": "/tmp/x"},
                TARGET,
            )


class SetsCookies(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        if self.path == "/login":
            self.send_header("Set-Cookie", "session=live-value; HttpOnly; Path=/")
        self.end_headers()
        self.wfile.write(b"<title>Signed in</title><p>ok</p>")

    def log_message(self, *_):
        pass


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "dbus-daemon", "firefox")),
    "desktop tools or Firefox unavailable",
)
class RealFirefoxCookieTests(unittest.TestCase):
    def setUp(self):
        from test_runtime import wait_for

        self.wait_for = wait_for
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-cookies-")
        self.root = Path(self.temporary.name)
        self.server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(SetsCookies)
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

    def test_a_session_cookie_set_by_the_server_is_exported(self):
        browser = functools.partial(core.request, self.session, "browser")
        browser(action="start", url=f"{self.base}/login")
        self.assertTrue(browser(action="wait", text="ok", timeout=30)["satisfied"])
        sent = browser(
            action="send", source="cookies", site="127.0.0.1", to_file="cookies.txt"
        )
        self.assertEqual(sent["cookies"], 1, sent)
        self.assertNotIn("live-value", json.dumps(sent))
        home = Path(sent["to_file"])
        self.assertIn("\tsession\tlive-value", home.read_text())


if __name__ == "__main__":
    unittest.main()
