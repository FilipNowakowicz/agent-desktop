"""Named profiles keep a session home (e.g. logins) for later sessions only."""

import http.server
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from test_runtime import CHROMIUM, wait_for

from agent_desktop import core
from agent_desktop.worker import owned_processes


class ProfileNameTests(unittest.TestCase):
    def test_invalid_names(self):
        for name in ("", "../x", "UPPER", "a/b", ".hidden", "x" * 33, 5):
            with self.subTest(name=name), self.assertRaises(core.DesktopError):
                core.profile_path(name)


class CookieServer(http.server.BaseHTTPRequestHandler):
    seen = []

    def do_GET(self):
        CookieServer.seen.append((self.path, self.headers.get("Cookie")))
        self.send_response(200)
        if self.path == "/login":
            self.send_header("Set-Cookie", "login=yes; Max-Age=3600; Path=/")
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<title>page</title>ok")

    def log_message(self, *_):
        pass


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "dbus-daemon")),
    "desktop tools unavailable",
)
class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-profile-")
        self.root = Path(self.temporary.name)
        self.previous = {
            k: os.environ.get(k) for k in ("AGENT_DESKTOP_STATE_DIR", "XDG_RUNTIME_DIR")
        }
        (self.root / "runtime").mkdir(mode=0o700)
        os.environ["AGENT_DESKTOP_STATE_DIR"] = str(self.root / "state")
        os.environ["XDG_RUNTIME_DIR"] = str(self.root / "runtime")
        self.created = []

    def tearDown(self):
        for session in self.created:
            info = core.manifest(session)
            if info["status"] == "ready":
                core.destroy(session)
            wait_for(lambda info=info: not owned_processes(info["token"]))
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temporary.cleanup()

    def create(self, profile=None):
        session = core.create(profile=profile)["session"]
        self.created.append(session)
        return session

    def run_shell(self, session, script):
        app = core.request(session, "launch", argv=["sh", "-c", script])

        def exited():
            for entry in core.request(session, "status")["applications"]:
                if entry["pid"] == app["pid"] and entry["exit_code"] is not None:
                    return True
            return False

        wait_for(exited)

    def test_home_persists_and_is_exclusive(self):
        output = self.root / "output"
        first = self.create("work")
        self.run_shell(first, 'echo kept > "$HOME/marker"')
        with self.assertRaisesRegex(core.DesktopError, "in use"):
            core.create(profile="work")
        with self.assertRaisesRegex(core.DesktopError, "in use"):
            core.delete_profile("work")
        self.assertTrue(core.profiles()[0]["in_use"])
        core.destroy(first)
        listed = core.profiles()
        self.assertEqual([p["profile"] for p in listed], ["work"])
        self.assertFalse(listed[0]["in_use"])

        second = self.create("work")
        self.run_shell(second, f'cat "$HOME/marker" > {output}')
        self.assertEqual(output.read_text(), "kept\n")
        # A session without a profile neither sees nor keeps that home.
        third = self.create()
        self.run_shell(third, f'test -e "$HOME/marker"; echo $? > {output}')
        self.assertEqual(output.read_text(), "1\n")
        core.destroy(third)
        core.destroy(second)
        self.assertFalse((core.session_path(third) / "home").exists())
        self.assertEqual(
            core.delete_profile("work"), {"profile": "work", "deleted": True}
        )
        self.assertEqual(core.profiles(), [])
        with self.assertRaises(core.DesktopError):
            core.delete_profile("work")

    @unittest.skipUnless(CHROMIUM, "chromium unavailable")
    def test_browser_cookie_survives_sessions(self):
        CookieServer.seen = []
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), CookieServer)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        argv = [
            CHROMIUM,
            "--no-first-run",
            "--ozone-platform=wayland",
            "--disable-gpu",
            "--password-store=basic",
        ]
        if os.geteuid() == 0:  # CI containers; never used for real profiles
            argv.append("--no-sandbox")
        try:
            for path in ("/login", "/check"):
                session = self.create("browser")
                app = core.request(session, "launch", argv=[*argv, base + path])

                def loaded(path=path, app=app):
                    if any(seen == path for seen, _ in CookieServer.seen):
                        return True
                    log = Path(app["logs"]).read_text()
                    if "No usable sandbox" in log:
                        self.skipTest(
                            "Chromium sandbox unavailable in this environment"
                        )
                    return False

                wait_for(loaded, timeout=30)
                # Wait for the browser window too, as a person would before leaving.
                wait_for(
                    lambda session=session: any(
                        w["title"].startswith("page")
                        for w in core.request(session, "windows")["windows"]
                    ),
                    timeout=30,
                )
                core.destroy(session)
        finally:
            server.shutdown()
            server.server_close()
        cookies = dict(CookieServer.seen)
        self.assertIsNone(cookies["/login"])
        self.assertEqual(cookies["/check"], "login=yes")
        self.assertEqual(
            (core.profile_path("browser") / "home").stat().st_mode & 0o777, 0o700
        )
