"""A login handoff reopens the bridged Firefox without the remote agent."""

import http.server
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from test_runtime import wait_for

from agent_desktop import core
from agent_desktop.worker import owned_processes

# Each load reports whether the page sees a remote-controlled browser, and the
# person's turn (webdriver false) leaves a cookie, as a real sign-in would.
PAGE = b"""<!doctype html><title>Sign in</title><p id="state">loading</p><script>
const wd = navigator.webdriver;
if (!wd) document.cookie = "signed_in=yes; max-age=3600; path=/";
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
        self.assertEqual(released["owner"], "agent")
        self.assertEqual(
            released["last"]["browser"], {"restarted": True, "url": self.url}
        )
        # The bridge is back on the same profile and keeps the new cookie.
        self.assertTrue(
            wait_for(lambda: Site.reports[-1:] == ["true"], timeout=30), Site.reports
        )
        found = self.browser("wait", text="signed_in=yes", timeout=15)
        self.assertTrue(found["satisfied"], self.browser("text", selector="#state"))
        self.assertIn("reported true", self.browser("text", selector="#state")["text"])
