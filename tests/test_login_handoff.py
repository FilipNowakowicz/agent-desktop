"""A login handoff reopens the bridged Firefox without the remote agent."""

import datetime
import http.server
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

from test_runtime import wait_for

from agent_desktop import core
from agent_desktop.worker import owned_processes

# Each load reports whether the page sees a remote-controlled browser, and the
# person's turn (webdriver false) leaves a cookie, as a real sign-in would, and
# a session-only one, as a sign-in without "Remember me" would.
PAGE = b"""<!doctype html><title>Sign in</title><p id="state">loading</p><script>
const wd = navigator.webdriver;
if (!wd) document.cookie = "signed_in=yes; max-age=3600; path=/";
if (!wd) document.cookie = "session_login=yes; path=/";
fetch("/report?webdriver=" + wd).then(() => {
  state.textContent = "reported " + wd + " cookies " + document.cookie;
});
</script>"""


class Site(http.server.BaseHTTPRequestHandler):
    reports = []

    def do_GET(self):
        if self.path.startswith("/report"):
            Site.reports.append(self.path.partition("=")[2])
            body = b"ok"
        else:
            body = PAGE
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "dbus-daemon", "firefox", "wayvnc")),
    "desktop tools, Firefox or wayvnc unavailable",
)
class LoginHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-login-")
        root = Path(self.temporary.name)
        self.previous = {
            k: os.environ.get(k) for k in ("AGENT_DESKTOP_STATE_DIR", "XDG_RUNTIME_DIR")
        }
        (root / "runtime").mkdir(mode=0o700)
        os.environ["AGENT_DESKTOP_STATE_DIR"] = str(root / "state")
        os.environ["XDG_RUNTIME_DIR"] = str(root / "runtime")
        Site.reports = []
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/"
        self.session = core.create()["session"]
        self.token = core.manifest(self.session)["token"]

    def tearDown(self):
        core.destroy(self.session)
        wait_for(lambda: not owned_processes(self.token))
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

    def test_person_signs_in_without_the_remote_agent(self):
        self.browser("start", url=self.url)
        self.assertTrue(wait_for(lambda: Site.reports == ["true"], timeout=30))
        plain = core.request(self.session, "request_human", reason="Sign in")
        self.assertIn("login=true", plain["hint"])
        requested = core.request(
            self.session, "request_human", reason="Sign in", login=True
        )
        self.assertTrue(requested["request"]["login"])
        taken = core.request(self.session, "take")
        self.assertEqual(taken["owner"], "human")
        self.assertEqual(taken["login_browser"]["url"], self.url)
        self.assertTrue(taken["login_browser"]["swapped"])
        # The person's Firefox is not remote-controlled, so the page sets its cookie.
        self.assertTrue(
            wait_for(lambda: Site.reports[-1:] == ["false"], timeout=30), Site.reports
        )
        released = core.request(self.session, "release")
        released_at = time.time()
        self.assertEqual(released["owner"], "agent")
        browser = released["last"]["browser"]
        # The window close is a clean quit: Firefox writes its session store,
        # and its one session-only cookie is kept for a day.
        self.assertEqual(
            {k: v for k, v in browser.items() if k != "session_cookies_expire"},
            {
                "restarted": True,
                "url": self.url,
                "kept_session_cookies": 1,
                "session_cookies_from": "sessionstore.jsonlz4",
            },
        )
        expires = datetime.datetime.fromisoformat(browser["session_cookies_expire"])
        self.assertAlmostEqual(expires.timestamp(), released_at + 86400, delta=120)
        self.assertEqual(
            core.request(self.session, "control")["last"]["browser"], browser
        )
        # The bridge is back on the same profile and keeps both new cookies.
        self.assertTrue(
            wait_for(lambda: Site.reports[-1:] == ["true"], timeout=30), Site.reports
        )
        found = self.browser("wait", text="session_login=yes", timeout=15)
        self.assertTrue(found["satisfied"], self.browser("text", selector="#state"))
        state = self.browser("text", selector="#state")["text"]
        self.assertIn("reported true", state)
        self.assertIn("signed_in=yes", state)
        # Stored as a persistent cookie expiring about 24 hours after release.
        profile = core.session_path(self.session) / "home/.mozilla/agent-desktop"
        copy = Path(self.temporary.name) / "cookies-copy.sqlite"
        for suffix in ("", "-wal"):
            source = Path(f"{profile / 'cookies.sqlite'}{suffix}")
            if source.is_file():
                shutil.copyfile(source, f"{copy}{suffix}")
        connection = sqlite3.connect(copy)
        try:
            ((expiry,),) = connection.execute(
                "SELECT expiry FROM moz_cookies WHERE name = 'session_login'"
            ).fetchall()
        finally:
            connection.close()
        seconds = expiry / 1000 if expiry > 10**11 else expiry
        self.assertAlmostEqual(seconds, released_at + 86400, delta=120)
