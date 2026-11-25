"""After a login handoff, session-only cookies are kept for a day."""

import datetime
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path

from test_profiles import FIREFOX_COOKIES, mozlz4, session_cookie

from agent_desktop import cookies
from agent_desktop.worker import Worker

DAY = cookies.SESSION_COOKIE_HOURS * 3600


class KeepSessionCookiesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="desktop-keep-")
        self.addCleanup(temporary.cleanup)
        self.profile = Path(temporary.name) / "home/.mozilla/agent-desktop"
        self.profile.mkdir(parents=True)

    def database(self, version=16, rows=()):
        with sqlite3.connect(self.profile / "cookies.sqlite") as connection:
            connection.execute(FIREFOX_COOKIES)
            connection.execute(f"PRAGMA user_version = {version}")
            connection.executemany(
                "INSERT INTO moz_cookies (name, value, host, path, expiry) "
                "VALUES (?, ?, ?, '/', ?)",
                rows,
            )
        connection.close()

    def store(self, cookies_, name="sessionstore.jsonlz4", written=None):
        path = self.profile / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            mozlz4({"version": ["sessionrestore", 1], "cookies": cookies_})
        )
        if written is not None:
            os.utime(path, (written, written))
        return path

    def stored(self):
        with sqlite3.connect(self.profile / "cookies.sqlite") as connection:
            rows = connection.execute(
                "SELECT name, value, host, originAttributes, expiry, isSecure "
                "FROM moz_cookies ORDER BY name"
            ).fetchall()
        connection.close()
        return rows

    def test_session_cookies_become_persistent_for_a_day(self):
        later = int(time.time()) + 30 * 86400
        self.database(rows=[("keep", "private-keep", "shop.example", later)])
        self.store(
            [
                session_cookie("shop.example", "sid", "private-sid", secure=True),
                session_cookie(
                    "login.example",
                    "box",
                    "private-box",
                    attributes={"userContextId": 2},
                ),
                session_cookie(
                    "login.example",
                    "pb",
                    "private-pb",
                    attributes={"privateBrowsingId": 1},
                ),
            ]
        )
        now = time.time()
        result = cookies.keep_session_cookies(self.profile, since=now - 60, now=now)
        self.assertEqual(result["kept"], 2)
        self.assertEqual(result["store"], "sessionstore.jsonlz4")
        self.assertEqual(result["problems"], [])
        until = int(now + DAY)
        self.assertEqual(
            self.stored(),
            [
                ("box", "private-box", "login.example", "^userContextId=2", until, 0),
                ("keep", "private-keep", "shop.example", "", later, None),
                ("sid", "private-sid", "shop.example", "", until, 1),
            ],
        )
        stamp = datetime.datetime.fromisoformat(result["expires"])
        self.assertEqual(int(stamp.timestamp()), until)
        # Values never appear in the result.
        self.assertNotIn("private", repr(result))

    def test_milliseconds_and_replacing_an_older_copy(self):
        later = (int(time.time()) + 86400 * 30) * 1000
        self.database(version=17, rows=[("sid", "private-old", "shop.example", later)])
        self.store([session_cookie("shop.example", "sid", "private-new")])
        now = time.time()
        self.assertEqual(cookies.keep_session_cookies(self.profile, now=now)["kept"], 1)
        ((name, value, _, _, expiry, _),) = self.stored()
        self.assertEqual((name, value), ("sid", "private-new"))
        self.assertEqual(expiry, int((now + DAY) * 1000))

    def test_stale_and_unclean_stores(self):
        self.database()
        started = time.time()
        # Written before the login's Firefox started: a previous run's store.
        self.store(
            [session_cookie("old.example", "sid", "private-old")], written=started - 600
        )
        result = cookies.keep_session_cookies(self.profile, since=started)
        self.assertEqual((result["kept"], result["store"]), (0, None))
        self.assertEqual(self.stored(), [])
        # After a kill only the periodic recovery file is fresh; it is used.
        self.store(
            [session_cookie("new.example", "sid", "private-new")],
            name="sessionstore-backups/recovery.jsonlz4",
        )
        result = cookies.keep_session_cookies(self.profile, since=started)
        self.assertEqual(result["store"], "sessionstore-backups/recovery.jsonlz4")
        self.assertEqual([r[2] for r in self.stored()], ["new.example"])

    def test_unreadable_files_are_reported_not_raised(self):
        (self.profile / "sessionstore.jsonlz4").write_bytes(b"not mozlz4 at all")
        result = cookies.keep_session_cookies(self.profile)
        self.assertEqual(result["kept"], 0)
        self.assertEqual(
            result["problems"],
            ["sessionstore.jsonlz4 is unreadable (not a mozLz4 file)"],
        )
        self.store([session_cookie("shop.example", "sid", "private-sid")])
        result = cookies.keep_session_cookies(self.profile)
        self.assertEqual(result["problems"], ["cookies.sqlite is missing"])
        (self.profile / "cookies.sqlite").write_bytes(b"x" * 4096)
        result = cookies.keep_session_cookies(self.profile)
        self.assertEqual(result["kept"], 0)
        self.assertTrue(result["problems"][0].startswith("cookies.sqlite could not"))


class LoginCookieReplyTests(unittest.TestCase):
    """Worker.keep_login_cookies reports problems and never raises."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="desktop-keep-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.profile = self.home / cookies.SESSION_FIREFOX
        self.profile.mkdir(parents=True)
        with sqlite3.connect(self.profile / "cookies.sqlite") as connection:
            connection.execute(FIREFOX_COOKIES)
        connection.close()
        self.worker = types.SimpleNamespace(
            info={"pinned_browsers": ["firefox"]}, env={"HOME": str(self.home)}
        )

    def exited(self, status):
        process = subprocess.Popen(
            [sys.executable, "-c", f"raise SystemExit({status})"]
        )
        process.wait()
        return process

    def keep(self, process, login=None):
        login = {"started": time.time() - 60} if login is None else login
        return Worker.keep_login_cookies(self.worker, login, process)

    def test_clean_quit(self):
        (self.profile / "sessionstore.jsonlz4").write_bytes(
            mozlz4({"cookies": [session_cookie("shop.example", "sid", "private")]})
        )
        reply = self.keep(self.exited(0))
        self.assertEqual(reply["kept_session_cookies"], 1)
        self.assertEqual(reply["session_cookies_from"], "sessionstore.jsonlz4")
        self.assertIn("session_cookies_expire", reply)
        self.assertNotIn("session_cookies_note", reply)

    def test_problems_are_notes(self):
        reply = self.keep(self.exited(9))
        self.assertEqual(reply["kept_session_cookies"], 0)
        self.assertIn("did not quit cleanly (status 9)", reply["session_cookies_note"])
        self.assertIn("no session store", reply["session_cookies_note"])
        self.worker.info["pinned_browsers"] = []
        self.assertIn("not pinned", self.keep(None)["session_cookies_note"])
        self.worker.info["pinned_browsers"] = ["firefox"]
        self.worker.env = {}  # no HOME: an unexpected error is still a note
        reply = self.keep(None)
        self.assertEqual(reply["kept_session_cookies"], 0)
        self.assertIn("KeyError", reply["session_cookies_note"])
        running = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"]
        )
        try:
            reply = self.keep(running)
        finally:
            running.kill()
            running.wait()
        self.assertIn("still running", reply["session_cookies_note"])
