"""Named profiles keep a session home (e.g. logins) for later sessions only."""

import asyncio
import http.server
import json
import os
import random
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from test_runtime import CHROMIUM, wait_for

from agent_desktop import cookies, core
from agent_desktop.worker import owned_processes, process_state


class ProfileNameTests(unittest.TestCase):
    def test_invalid_names(self):
        for name in ("", "../x", "UPPER", "a/b", ".hidden", "x" * 33, 5):
            with self.subTest(name=name), self.assertRaises(core.DesktopError):
                core.profile_path(name)


# The moz_cookies table as Firefox 14x creates it (schema version 16).
FIREFOX_COOKIES = """CREATE TABLE moz_cookies (id INTEGER PRIMARY KEY,
originAttributes TEXT NOT NULL DEFAULT '', name TEXT, value TEXT, host TEXT,
path TEXT, expiry INTEGER, lastAccessed INTEGER, creationTime INTEGER,
isSecure INTEGER, isHttpOnly INTEGER, inBrowserElement INTEGER DEFAULT 0,
sameSite INTEGER DEFAULT 0, schemeMap INTEGER DEFAULT 0,
isPartitionedAttributeSet INTEGER DEFAULT 0,
CONSTRAINT moz_uniqueid UNIQUE (name, host, path, originAttributes))"""


def lz4_compress(data):
    """A small greedy LZ4 block compressor, so fixtures contain real matches."""
    out, literals, table, i = bytearray(), bytearray(), {}, 0

    def lengths(value):
        while value >= 255:
            out.append(255)
            value -= 255
        out.append(value)

    def sequence(match_length=None, offset=0):
        token_literal = min(len(literals), 15)
        token_match = 0 if match_length is None else min(match_length - 4, 15)
        out.append(token_literal << 4 | token_match)
        if len(literals) >= 15:
            lengths(len(literals) - 15)
        out.extend(literals)
        literals.clear()
        if match_length is not None:
            out.extend(offset.to_bytes(2, "little"))
            if match_length - 4 >= 15:
                lengths(match_length - 19)

    # The format keeps the last 5 bytes as literals and starts no match in the
    # last 12.
    while i < len(data) - 12:
        key = data[i : i + 4]
        candidate = table.get(key)
        table[key] = i
        if candidate is not None and i - candidate <= 0xFFFF:
            length = 4
            while (
                i + length < len(data) - 5
                and data[candidate + length] == data[i + length]
            ):
                length += 1
            sequence(length, i - candidate)
            i += length
            continue
        literals.append(data[i])
        i += 1
    literals.extend(data[i:])
    sequence()
    return bytes(out)


def mozlz4(document):
    data = json.dumps(document).encode()
    return b"mozLz40\0" + len(data).to_bytes(4, "little") + lz4_compress(data)


def session_cookie(host, name, value, **extra):
    attributes = {
        "firstPartyDomain": "",
        "geckoViewSessionContextId": "",
        "partitionKey": "",
        "privateBrowsingId": 0,
        "userContextId": 0,
    }
    attributes.update(extra.pop("attributes", {}))
    cookie = {"host": host, "value": value, "path": "/", "name": name}
    cookie.update(extra)
    cookie["originAttributes"] = attributes
    return cookie


class CookieImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-cookies-")
        self.root = Path(self.temporary.name)
        self.previous = os.environ.get("AGENT_DESKTOP_STATE_DIR")
        os.environ["AGENT_DESKTOP_STATE_DIR"] = str(self.root / "state")
        self.addCleanup(self.temporary.cleanup)

    def tearDown(self):
        if self.previous is None:
            os.environ.pop("AGENT_DESKTOP_STATE_DIR", None)
        else:
            os.environ["AGENT_DESKTOP_STATE_DIR"] = self.previous

    def person(self, rows):
        profile = self.root / "person"
        profile.mkdir(exist_ok=True)
        with sqlite3.connect(profile / "cookies.sqlite") as connection:
            connection.execute("DROP TABLE IF EXISTS moz_cookies")
            connection.execute(FIREFOX_COOKIES)
            connection.execute("PRAGMA user_version = 16")
            connection.executemany(
                "INSERT INTO moz_cookies (name, value, host, path, expiry) "
                "VALUES (?, ?, ?, '/', 4102444800)",
                rows,
            )
        connection.close()
        return profile

    def imported(self, profile):
        database = (
            core.profile_path(profile) / "home/.mozilla/agent-desktop/cookies.sqlite"
        )
        connection = sqlite3.connect(database)
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            rows = connection.execute(
                "SELECT host, name, value FROM moz_cookies ORDER BY host, name"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(database.stat().st_mode & 0o777, 0o600)
        return version, rows

    def test_only_the_named_sites_are_copied(self):
        source = self.person(
            [
                ("sid", "private-cookie-sid-fixture", ".shop.example"),
                ("sso", "private-cookie-sso-fixture", "login.shop.example"),
                ("x", "3", "notshop.example"),
                ("y", "4", "other.example"),
            ]
        )
        result = cookies.import_firefox_cookies("shop", ["Shop.Example"], source)
        self.assertEqual(result["cookies"], 2)
        # Distinct sentinels cannot accidentally match a random temporary path
        # (a one-digit cookie value can).
        self.assertNotIn("private-cookie-sid-fixture", str(result))
        self.assertNotIn("private-cookie-sso-fixture", str(result))
        self.assertEqual(
            self.imported("shop"),
            (
                16,
                [
                    (".shop.example", "sid", "private-cookie-sid-fixture"),
                    ("login.shop.example", "sso", "private-cookie-sso-fixture"),
                ],
            ),
        )
        # Importing again replaces cookies instead of duplicating them.
        self.person([("sid", "new", ".shop.example")])
        cookies.import_firefox_cookies("shop", ["shop.example"], source)
        self.assertEqual(
            self.imported("shop")[1],
            [
                (".shop.example", "sid", "new"),
                ("login.shop.example", "sso", "private-cookie-sso-fixture"),
            ],
        )

    def session_store(
        self, profile, cookies_, name="sessionstore-backups/recovery.jsonlz4"
    ):
        path = profile / name
        path.parent.mkdir(parents=True, exist_ok=True)
        # Other keys of a session store, as Firefox writes them.
        windows = [{"tabs": [{"entries": [{"url": "https://other.example/"}]}]}]
        path.write_bytes(
            mozlz4(
                {
                    "version": ["sessionrestore", 1],
                    "windows": windows,
                    "cookies": cookies_,
                }
            )
        )
        return path

    def test_lz4_block_decoder(self):
        generator = random.Random(7)
        samples = [
            b"",
            b"a" * 1000,  # matches that overlap themselves (offset 1)
            b"abc" * 400 + b"tail-literals",
            bytes(generator.randrange(256) for _ in range(5000)),  # literals over 270
            json.dumps([{"n": i, "v": "x" * (i % 40)} for i in range(3000)]).encode(),
        ]
        for data in samples:
            with self.subTest(size=len(data)):
                block = lz4_compress(data)
                self.assertEqual(cookies.lz4_block(block, len(data)), data)
        block = lz4_compress(samples[2])
        for corrupt, size in (
            (block[:-3], len(samples[2])),  # truncated
            (block, len(samples[2]) + 1),  # wrong size in the header
            (bytes([0x0F, 0x10, 0x00]), 19),  # match before any output
        ):
            with self.assertRaises(ValueError):
                cookies.lz4_block(corrupt, size)
        # Assembled by hand from the format description: the literals "ab",
        # a 6-byte match at offset 2 (overlapping itself) and a final literal.
        block = bytes([0x22]) + b"ab" + bytes([2, 0, 0x10]) + b"!"
        self.assertEqual(cookies.lz4_block(block, 9), b"abababab!")

    def test_session_cookies_are_imported(self):
        source = self.person(
            [
                ("sid", "private-stale-sid-fixture", ".shop.example"),
                ("keep", "private-keep-fixture", "shop.example"),
            ]
        )
        self.session_store(
            source,
            [
                session_cookie(
                    ".shop.example",
                    "sid",
                    "private-session-sid-fixture",
                    secure=True,
                    httponly=True,
                    sameSite=1,
                    schemeMap=2,
                ),
                session_cookie(
                    "login.shop.example",
                    "box",
                    "private-container-fixture",
                    attributes={"userContextId": 2},
                ),
                session_cookie(
                    "login.shop.example",
                    "pb",
                    "private-browsing-fixture",
                    attributes={"privateBrowsingId": 1},
                ),
                session_cookie("other.example", "x", "private-other-fixture"),
                {"host": 5, "value": "private-malformed-fixture"},
            ],
        )
        before = time.time()
        process = subprocess.run(
            [
                sys.executable,
                "-c",
                "from agent_desktop.cli import main; main()",
                "import-cookies",
                "shop",
                "--site",
                "shop.example",
                "--from",
                str(source),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        result = json.loads(process.stdout)
        for value in (
            "sid",
            "keep",
            "session-sid",
            "container",
            "browsing",
            "other",
            "malformed",
        ):
            self.assertNotIn(
                f"private-{value}-fixture", process.stdout + process.stderr
            )
        self.assertEqual(
            (
                result["cookies"],
                result["persistent_cookies"],
                result["session_cookies"],
            ),
            (3, 1, 2),
        )
        self.assertEqual(
            result["hosts"], [".shop.example", "login.shop.example", "shop.example"]
        )
        self.assertIn("recovery.jsonlz4", result["detail"])
        self.assertIn("24-hour", result["detail"])
        self.assertNotIn("warning", result)
        database = (
            core.profile_path("shop") / "home/.mozilla/agent-desktop/cookies.sqlite"
        )
        connection = sqlite3.connect(database)
        try:
            rows = connection.execute(
                "SELECT host, name, value, originAttributes, expiry, isSecure, "
                "isHttpOnly, sameSite, schemeMap FROM moz_cookies ORDER BY host, name"
            ).fetchall()
        finally:
            connection.close()
        expiry = rows[0][4]
        # The fixture stores seconds, so the copied session cookies do too.
        self.assertAlmostEqual(expiry, before + 24 * 3600, delta=60)
        self.assertEqual(
            rows,
            [
                (
                    ".shop.example",
                    "sid",
                    "private-session-sid-fixture",
                    "",
                    expiry,
                    1,
                    1,
                    1,
                    2,
                ),
                (
                    "login.shop.example",
                    "box",
                    "private-container-fixture",
                    "^userContextId=2",
                    expiry,
                    0,
                    0,
                    0,
                    0,
                ),
                (
                    "shop.example",
                    "keep",
                    "private-keep-fixture",
                    "",
                    4102444800,
                    None,
                    None,
                    0,
                    0,
                ),
            ],
        )
        self.assertEqual(
            result["session_cookies_expire"],
            time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(expiry)),
        )

    def test_millisecond_expiry_and_origin_attributes(self):
        source = self.person([])
        with sqlite3.connect(source / "cookies.sqlite") as connection:
            connection.execute("PRAGMA user_version = 17")
        connection.close()
        self.session_store(
            source,
            [
                session_cookie(
                    "shop.example",
                    "p",
                    "1",
                    attributes={
                        "partitionKey": "(https,shop.example)",
                        "firstPartyDomain": "a b",
                    },
                )
            ],
        )
        before = time.time()
        cookies.import_firefox_cookies("shop", ["shop.example"], source)
        connection = sqlite3.connect(
            core.profile_path("shop") / "home/.mozilla/agent-desktop/cookies.sqlite"
        )
        try:
            ((attributes, expiry),) = connection.execute(
                "SELECT originAttributes, expiry FROM moz_cookies"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(
            attributes,
            "^firstPartyDomain=a%20b&partitionKey=%28https%2Cshop.example%29",
        )
        self.assertAlmostEqual(expiry / 1000, before + 24 * 3600, delta=60)

    def test_newest_session_store_and_corrupt_ones(self):
        source = self.person([("keep", "1", "shop.example")])
        older = self.session_store(
            source,
            [session_cookie("shop.example", "old", "private-old-fixture")],
            "sessionstore.jsonlz4",
        )
        newer = self.session_store(
            source, [session_cookie("shop.example", "new", "private-new-fixture")]
        )
        os.utime(older, (1_000_000, 1_000_000))
        result = cookies.import_firefox_cookies("shop", ["shop.example"], source)
        self.assertEqual(result["session_cookies"], 1)
        self.assertIn("recovery.jsonlz4", result["detail"])
        self.assertEqual([r[1] for r in self.imported("shop")[1]], ["keep", "new"])
        # A corrupt newest store: the older one is used and the problem named.
        for damage, reason in (
            (b"not mozlz4 at all", "not a mozLz4 file"),
            (newer.read_bytes()[:-20], "truncated"),
            (
                b"mozLz40\0" + (5).to_bytes(4, "little") + bytes([0x50]) + b"{oops",
                "not JSON",
            ),
            (b"mozLz40\0" + (2**31).to_bytes(4, "little"), "decoded size too large"),
        ):
            with self.subTest(reason=reason):
                newer.write_bytes(damage)
                os.utime(newer, None)
                result = cookies.import_firefox_cookies(
                    "fall", ["shop.example"], source
                )
                self.assertEqual(result["session_cookies"], 1)
                self.assertIn("sessionstore.jsonlz4 and copied", result["detail"])
                self.assertIn(
                    f"recovery.jsonlz4 is unreadable ({reason}", result["detail"]
                )
                self.assertNotIn("private-", str(result))
        # Every store corrupt: persistent cookies are still copied.
        older.write_bytes(b"mozLz40\0garbage")
        result = cookies.import_firefox_cookies("bad", ["shop.example"], source)
        self.assertEqual(
            (result["persistent_cookies"], result["session_cookies"]), (1, 0)
        )
        self.assertNotIn("session_cookies_expire", result)
        self.assertIn("No session store was found", result["detail"])
        self.assertIn("sessionstore.jsonlz4 is unreadable", result["detail"])
        # None at all.
        older.unlink()
        newer.unlink()
        result = cookies.import_firefox_cookies("none", ["shop.example"], source)
        self.assertEqual(
            result["detail"],
            "No session store was found, so no "
            "session-only cookies were copied. Values are never shown.",
        )

    def test_refusals(self):
        source = self.person([("sid", "1", "shop.example")])
        for sites in ([], ["localhost"], ["a b.example"], ["../x.example"]):
            with self.subTest(sites=sites), self.assertRaises(core.DesktopError):
                cookies.import_firefox_cookies("shop", sites, source)
        with self.assertRaisesRegex(core.DesktopError, "No cookies.sqlite"):
            cookies.import_firefox_cookies("shop", ["shop.example"], self.root)
        import fcntl

        path = core.profile_path("shop")
        with core.profile_lock(path).open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with self.assertRaisesRegex(core.DesktopError, "in use"):
                cookies.import_firefox_cookies("shop", ["shop.example"], source)

    def test_multi_account_sites_warn(self):
        source = self.person(
            [
                ("SID", "private-google-a", ".google.com"),
                ("x", "1", "login.tailscale.com"),
            ]
        )
        warned = cookies.import_firefox_cookies(
            "cloud", ["google.com", "tailscale.com"], source
        )
        self.assertIn("google.com", warned["warning"])
        self.assertIn("--from", warned["warning"])
        quiet = cookies.import_firefox_cookies("tail", ["tailscale.com"], source)
        self.assertNotIn("warning", quiet)

    def test_forget_site_removes_only_that_site(self):
        source = self.person(
            [
                ("SID", "private-google-a", ".google.com"),
                ("LSID", "private-google-b", "accounts.google.com"),
                ("x", "1", "login.tailscale.com"),
                ("y", "2", "notgoogle.com"),
            ]
        )
        cookies.import_firefox_cookies(
            "cloud", ["google.com", "tailscale.com", "notgoogle.com"], source
        )
        firefox = core.profile_path("cloud") / "home/.mozilla/agent-desktop"
        storage = firefox / "storage/default"
        for name in (
            "https+++accounts.google.com",
            "https+++mail.google.com^userContextId=1",
            "https+++login.tailscale.com",
            "https+++notgoogle.com+8443",
        ):
            (storage / name / "ls").mkdir(parents=True)
            (storage / name / "ls" / "data.sqlite").write_text("x")
        result = cookies.forget_site("cloud", ["google.com"])
        self.assertEqual(result["cookies_removed"], 2)
        self.assertEqual(
            result["storage_removed"],
            ["https+++accounts.google.com", "https+++mail.google.com^userContextId=1"],
        )
        self.assertEqual(
            [row[:2] for row in self.imported("cloud")[1]],
            [("login.tailscale.com", "x"), ("notgoogle.com", "y")],
        )
        self.assertEqual(
            sorted(p.name for p in storage.iterdir()),
            ["https+++login.tailscale.com", "https+++notgoogle.com+8443"],
        )
        import fcntl

        with core.profile_lock(core.profile_path("cloud")).open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with self.assertRaisesRegex(core.DesktopError, "in use"):
                cookies.forget_site("cloud", ["tailscale.com"])
        with self.assertRaisesRegex(core.DesktopError, "No profile"):
            cookies.forget_site("missing", ["google.com"])

    def listed_profile(self):
        source = self.person(
            [
                ("SID", "private-list-sid-fixture", ".google.com"),
                ("LSID", "private-list-lsid-fixture", "accounts.google.com"),
                ("x", "private-list-other-fixture", "login.tailscale.com"),
                ("y", "private-list-lookalike-fixture", "notgoogle.com"),
            ]
        )
        cookies.import_firefox_cookies(
            "cloud", ["google.com", "tailscale.com", "notgoogle.com"], source
        )
        firefox = core.profile_path("cloud") / "home/.mozilla/agent-desktop"
        with sqlite3.connect(firefox / "cookies.sqlite") as connection:
            connection.execute(
                "UPDATE moz_cookies SET isSecure = 1, isHttpOnly = 1, "
                "expiry = 1798761600 WHERE name = 'SID'"
            )
            connection.execute(
                "INSERT INTO moz_cookies (name, value, host, path, expiry) "
                "VALUES ('tmp', 'private-list-session-fixture', 'mail.google.com', "
                "'/mail', 0)"
            )
        for name in ("https+++mail.google.com", "https+++notgoogle.com"):
            (firefox / "storage/default" / name / "ls").mkdir(parents=True)
        return firefox

    def test_site_cookies_lists_names_never_values(self):
        firefox = self.listed_profile()
        before = (firefox / "cookies.sqlite").read_bytes()
        result = cookies.site_cookies("cloud", ["Google.com"])
        text = json.dumps(result)
        self.assertNotIn("private-list", text)
        self.assertEqual(result["sites"], ["google.com"])
        self.assertEqual(
            [(c["host"], c["name"]) for c in result["cookies"]],
            [
                ("accounts.google.com", "LSID"),
                (".google.com", "SID"),
                ("mail.google.com", "tmp"),
            ],
        )
        by_name = {c["name"]: c for c in result["cookies"]}
        self.assertEqual(sorted(by_name), ["LSID", "SID", "tmp"])
        self.assertEqual(by_name["SID"]["host"], ".google.com")
        self.assertEqual(by_name["SID"]["expires"], "2027-01-01T00:00:00Z")
        self.assertTrue(by_name["SID"]["secure"])
        self.assertTrue(by_name["SID"]["http_only"])
        self.assertEqual(by_name["tmp"]["expires"], "session")
        self.assertEqual(by_name["tmp"]["path"], "/mail")
        self.assertFalse(by_name["tmp"]["secure"])
        for cookie in result["cookies"]:
            self.assertEqual(
                set(cookie),
                {"host", "name", "path", "expires", "secure", "http_only"},
            )
        self.assertEqual(result["storage"], ["https+++mail.google.com"])
        # Nothing was changed, and a database copy is not left in the profile.
        self.assertEqual((firefox / "cookies.sqlite").read_bytes(), before)
        self.assertEqual(
            sorted(p.name for p in firefox.iterdir() if "cookies" in p.name),
            ["cookies.sqlite"],
        )

    def test_site_cookies_other_sites_missing_and_in_use(self):
        self.listed_profile()
        other = cookies.site_cookies("cloud", ["tailscale.com"])
        self.assertEqual([c["name"] for c in other["cookies"]], ["x"])
        self.assertEqual(other["storage"], [])
        none = cookies.site_cookies("cloud", ["example.org"])
        self.assertEqual((none["cookies"], none["storage"]), ([], []))
        import fcntl

        with core.profile_lock(core.profile_path("cloud")).open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with self.assertRaisesRegex(core.DesktopError, "in use"):
                cookies.site_cookies("cloud", ["google.com"])
        with self.assertRaisesRegex(core.DesktopError, "No profile"):
            cookies.site_cookies("missing", ["google.com"])
        with self.assertRaisesRegex(core.DesktopError, "Not a site name"):
            cookies.site_cookies("cloud", ["not a site"])
        # A profile that never held a login has no cookie file at all.
        (core.profile_path("blank") / "home").mkdir(parents=True)
        blank = cookies.site_cookies("blank", ["google.com"])
        self.assertEqual((blank["cookies"], blank["storage"]), ([], []))

    def test_site_cookies_milliseconds_expiry(self):
        self.listed_profile()
        database = (
            core.profile_path("cloud") / "home/.mozilla/agent-desktop/cookies.sqlite"
        )
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE moz_cookies SET expiry = expiry * 1000")
        result = cookies.site_cookies("cloud", ["google.com"])
        sid = [c for c in result["cookies"] if c["name"] == "SID"][0]
        self.assertEqual(sid["expires"], "2027-01-01T00:00:00Z")

    def test_site_cookies_cli(self):
        self.listed_profile()
        process = subprocess.run(
            [
                sys.executable,
                "-c",
                "from agent_desktop.cli import main; main()",
                "site-cookies",
                "cloud",
                "--site",
                "google.com",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertNotIn("private-list", process.stdout + process.stderr)
        self.assertEqual(
            sorted(c["name"] for c in json.loads(process.stdout)["cookies"]),
            ["LSID", "SID", "tmp"],
        )

    def test_default_profile_from_profiles_ini(self):
        source = self.person([("sid", "1", "shop.example")])
        (self.root / "profiles.ini").write_text(
            "[Profile0]\nName=default\nIsRelative=1\nPath=person\nDefault=1\n"
        )
        environment = {"MOZ_APP_DATA": str(self.root)}
        self.assertEqual(cookies.default_firefox_profile(environment), source)
        (self.root / "profiles.ini").write_text("[General]\n")
        with self.assertRaisesRegex(core.DesktopError, "--from"):
            cookies.default_firefox_profile(environment)


class CookieServer(http.server.BaseHTTPRequestHandler):
    seen = []

    def do_GET(self):
        CookieServer.seen.append((self.path, self.headers.get("Cookie")))
        self.send_response(200)
        if self.path == "/login":
            self.send_header("Set-Cookie", "login=yes; Max-Age=3600; Path=/")
        elif self.path == "/session-login":  # no expiry: a session-only cookie
            self.send_header("Set-Cookie", "session=yes; Path=/; HttpOnly")
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<title>page</title>ok")

    def log_message(self, *_):
        pass


class ProfileNoteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-note-")
        self.addCleanup(self.temporary.cleanup)
        self.previous = os.environ.get("AGENT_DESKTOP_STATE_DIR")
        os.environ["AGENT_DESKTOP_STATE_DIR"] = str(Path(self.temporary.name) / "state")
        self.addCleanup(self.restore)
        (core.profile_path("work") / "home").mkdir(parents=True)

    def restore(self):
        if self.previous is None:
            os.environ.pop("AGENT_DESKTOP_STATE_DIR", None)
        else:
            os.environ["AGENT_DESKTOP_STATE_DIR"] = self.previous

    def test_set_show_replace_and_clear(self):
        self.assertNotIn("note", core.profiles()[0])
        core.set_profile_note("work", "signs in to Google as the project account")
        self.assertEqual(
            core.profiles()[0]["note"], "signs in to Google as the project account"
        )
        core.set_profile_note("work", "second")
        self.assertEqual(core.profiles()[0]["note"], "second")
        self.assertEqual(
            core.set_profile_note("work", None), {"profile": "work", "note": None}
        )
        self.assertNotIn("note", core.profiles()[0])
        core.set_profile_note("work", "again")
        core.set_profile_note("work", "")  # empty text clears too
        self.assertNotIn("note", core.profiles()[0])

    def test_note_file_is_private_single_line_and_outside_home(self):
        core.set_profile_note("work", "line one\n  line   two\t")
        path = core.profile_path("work") / "note"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.read_text(), "line one line two\n")
        self.assertEqual(core.profiles()[0]["note"], "line one line two")
        self.assertFalse((core.profile_path("work") / "home" / "note").exists())
        self.assertFalse((core.profile_path("work") / "note.tmp").exists())

    def test_length_limit_and_unknown_profile(self):
        core.set_profile_note("work", "x" * core.NOTE_LIMIT)
        with self.assertRaisesRegex(core.DesktopError, "at most 200"):
            core.set_profile_note("work", "x" * (core.NOTE_LIMIT + 1))
        self.assertEqual(len(core.profiles()[0]["note"]), core.NOTE_LIMIT)
        with self.assertRaisesRegex(core.DesktopError, "Unknown profile"):
            core.set_profile_note("nobody", "x")
        with self.assertRaises(core.DesktopError):
            core.set_profile_note("../x", "x")
        with self.assertRaises(core.DesktopError):
            core.set_profile_note("work", 5)

    def test_delete_removes_note(self):
        core.set_profile_note("work", "kept until deletion")
        core.delete_profile("work")
        self.assertFalse(core.profile_path("work").exists())
        (core.profile_path("work") / "home").mkdir(parents=True)
        self.assertNotIn("note", core.profiles()[0])

    def test_mcp_tool_sets_lists_and_validates(self):
        from agent_desktop import mcp_server

        def call(**arguments):
            return asyncio.run(mcp_server.desktop_profiles(**arguments))

        self.assertEqual(
            call(profile="work", note="personal account"),
            {"profile": "work", "note": "personal account"},
        )
        self.assertEqual(call()[0]["note"], "personal account")
        self.assertEqual(
            call(profile="work", note=""), {"profile": "work", "note": None}
        )
        for arguments in (
            {"profile": "work"},
            {"note": "x"},
            {"profile": "work", "note": "x", "session": "s"},
            {"profile": "work", "note": "x", "attach": "work"},
        ):
            with (
                self.subTest(arguments=arguments),
                self.assertRaises(core.DesktopError),
            ):
                call(**arguments)
        self.assertNotIn("note", call()[0])

    def test_mcp_tool_cookie_listing_validates(self):
        from agent_desktop import mcp_server

        def call(**arguments):
            return asyncio.run(mcp_server.desktop_profiles(**arguments))

        for arguments in (
            {"cookies": "example.com"},
            {"profile": "work", "cookies": "example.com", "note": "x"},
            {"profile": "work", "cookies": "example.com", "session": "s"},
            {"profile": "work", "cookies": "example.com", "attach": "work"},
        ):
            with (
                self.subTest(arguments=arguments),
                self.assertRaisesRegex(core.DesktopError, "Listing cookies"),
            ):
                call(**arguments)
        with self.assertRaisesRegex(core.DesktopError, "No profile named nobody"):
            call(profile="nobody", cookies="example.com")
        self.assertEqual(call(profile="work", cookies="example.com")["cookies"], [])


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

    def test_profile_stays_locked_until_the_guardian_has_cleaned_up(self):
        session = self.create("crash")
        info = core.manifest(session)
        guardian, worker = info["guardian_pid"], info["worker_pid"]
        os.kill(guardian, signal.SIGSTOP)
        try:
            os.kill(worker, signal.SIGKILL)
            wait_for(lambda: process_state(worker) in (None, "Z"))
            # The worker is gone, but its applications may still be running.
            self.assertTrue(core.profiles()[0]["in_use"])
            with self.assertRaisesRegex(core.DesktopError, "in use"):
                core.create(profile="crash")
        finally:
            os.kill(guardian, signal.SIGCONT)
        wait_for(lambda: core.manifest(session)["status"] == "failed", timeout=15)
        wait_for(lambda: not core.profiles()[0]["in_use"], timeout=15)
        self.create("crash")

    def test_new_session_recovers_a_profile_whose_supervisors_died(self):
        session = self.create("orphaned")
        app = core.request(session, "launch", argv=["sleep", "300"])
        info = core.manifest(session)
        for pid in (info["guardian_pid"], info["worker_pid"]):
            os.kill(pid, signal.SIGKILL)
        # The lock goes with the supervisors, but the application still runs.
        wait_for(lambda: not core.profiles()[0]["in_use"])
        self.assertEqual(core.profiles()[0]["last_session"]["status"], "abandoned")
        self.assertNotIn(process_state(app["pid"]), (None, "Z"))

        result = core.create(profile="orphaned")
        self.created.append(result["session"])
        self.assertEqual(
            result["previous_session"],
            {"session": session, "status": "stopped", "recovered": True},
        )
        self.assertIn(process_state(app["pid"]), (None, "Z"))
        self.assertEqual(owned_processes(info["token"]), [])
        self.assertEqual(
            core.profiles()[0]["last_session"],
            {"session": result["session"], "status": "ready"},
        )

    def test_failed_end_is_reported_to_the_next_session(self):
        session = self.create("failed")
        os.kill(core.manifest(session)["worker_pid"], signal.SIGKILL)
        wait_for(lambda: core.manifest(session)["status"] == "failed", timeout=15)
        wait_for(lambda: not core.profiles()[0]["in_use"], timeout=15)
        result = core.create(profile="failed")
        self.created.append(result["session"])
        previous = result["previous_session"]
        self.assertEqual(previous["session"], session)
        self.assertEqual(previous["status"], "failed")
        self.assertIn("Supervisor exited unexpectedly", previous["error"])

    def test_attach_to_a_running_session(self):
        output = self.root / "output"
        session = self.create()
        self.run_shell(session, 'echo before > "$HOME/old-marker"')
        result = core.attach_profile(session, "late")
        self.assertEqual(result["profile"], "late")
        self.assertIsNone(result["previous_session"])
        self.assertEqual(core.request(session, "status")["profile"], "late")
        self.assertEqual(core.manifest(session)["profile"], "late")
        self.assertEqual(
            core.profiles()[0]["last_session"], {"session": session, "status": "ready"}
        )
        self.assertTrue(core.profiles()[0]["in_use"])
        # Applications started afterwards use the profile, not the old home.
        self.run_shell(
            session, 'echo after > "$HOME/marker"; echo "$HOME" > ' + str(output)
        )
        home = core.profile_path("late") / "home"
        self.assertEqual(output.read_text().strip(), str(home))
        self.assertEqual((home / "marker").read_text(), "after\n")
        self.assertFalse((home / "old-marker").exists())
        # The profile is exclusive from now on, and release works as at create.
        with self.assertRaisesRegex(core.DesktopError, "in use"):
            core.create(profile="late")
        with self.assertRaisesRegex(core.DesktopError, "in use"):
            core.delete_profile("late")
        core.destroy(session)
        self.assertFalse(core.profiles()[0]["in_use"])
        second = self.create("late")
        self.run_shell(second, f'cat "$HOME/marker" > {output}')
        self.assertEqual(output.read_text(), "after\n")

    def test_attach_is_refused_without_changing_the_session(self):
        session = self.create()
        for name in ("", "UPPER", "../x", "a" * 33, None):
            with self.assertRaisesRegex(core.DesktopError, "Profile names"):
                core.attach_profile(session, name)
        self.assertEqual(core.profiles(), [])
        # An application of the session is running: it would keep the old home.
        app = core.request(session, "launch", argv=["sleep", "300"])
        with self.assertRaisesRegex(
            core.DesktopError, "Applications are still running"
        ):
            core.attach_profile(session, "late")
        self.assertEqual(core.profiles(), [])  # a refusal leaves no profile behind
        self.assertIsNone(core.manifest(session).get("profile"))
        os.kill(app["pid"], signal.SIGKILL)
        wait_for(
            lambda: core.request(session, "status")["applications"][0]["exit_code"]
        )
        # Held by another session, which the refusal names.
        other = self.create("busy")
        with self.assertRaisesRegex(core.DesktopError, f"in use by session {other}"):
            core.attach_profile(session, "busy")
        self.assertIsNone(core.manifest(session).get("profile"))
        # A session keeps one profile.
        core.attach_profile(session, "late")
        with self.assertRaisesRegex(core.DesktopError, "already uses profile late"):
            core.attach_profile(session, "other")
        with self.assertRaisesRegex(core.DesktopError, "already uses profile busy"):
            core.attach_profile(other, "late")
        self.assertEqual(core.request(session, "status")["profile"], "late")

    def test_attached_profile_stays_locked_until_the_guardian_has_cleaned_up(self):
        session = self.create()
        core.attach_profile(session, "late")
        info = core.manifest(session)
        guardian, worker = info["guardian_pid"], info["worker_pid"]
        # The guardian holds its own descriptor of the lock file, received
        # from the worker, rather than leaving it queued in a socket.
        lock = str(core.profile_lock(core.profile_path("late")))
        wait_for(
            lambda: any(
                os.path.realpath(path) == os.path.realpath(lock)
                for path in (
                    os.readlink(f"/proc/{guardian}/fd/{fd}")
                    for fd in os.listdir(f"/proc/{guardian}/fd")
                )
            )
        )
        os.kill(guardian, signal.SIGSTOP)
        try:
            os.kill(worker, signal.SIGKILL)
            wait_for(lambda: process_state(worker) in (None, "Z"))
            self.assertTrue(core.profiles()[0]["in_use"])
            with self.assertRaisesRegex(core.DesktopError, "in use"):
                core.create(profile="late")
        finally:
            os.kill(guardian, signal.SIGCONT)
        wait_for(lambda: core.manifest(session)["status"] == "failed", timeout=15)
        wait_for(lambda: not core.profiles()[0]["in_use"], timeout=15)

    @unittest.skipUnless(shutil.which("firefox"), "Firefox unavailable")
    def test_firefox_started_after_attach_uses_the_profile(self):
        CookieServer.seen = []
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), CookieServer)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            first = self.create()
            core.attach_profile(first, "login")
            core.request(first, "browser", action="start", url=base + "/login")
            wait_for(
                lambda: any(path == "/login" for path, _ in CookieServer.seen),
                timeout=30,
            )
            core.destroy(first)
            self.assertTrue(
                (core.profile_path("login") / "home/.mozilla/agent-desktop").is_dir()
            )
            second = self.create("login")
            core.request(second, "browser", action="start", url=base + "/check")
            wait_for(
                lambda: any(path == "/check" for path, _ in CookieServer.seen),
                timeout=30,
            )
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(dict(CookieServer.seen)["/check"], "login=yes")

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

    @unittest.skipUnless(shutil.which("firefox"), "Firefox unavailable")
    def test_imported_firefox_cookie_is_sent(self):
        CookieServer.seen = []
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), CookieServer)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        # A stand-in for the person's Firefox logs in with its own profile.
        person = self.root / "person-firefox"
        person.mkdir()
        try:
            session = self.create()
            core.request(
                session,
                "launch",
                argv=["firefox", "--profile", str(person), base + "/login"],
            )

            def logged_in():
                try:
                    return cookies.read_cookies(person, ["127.0.0.1"])[1]
                except core.DesktopError:
                    return False  # Firefox has not created the table yet

            wait_for(logged_in, timeout=30)
            result = cookies.import_firefox_cookies("imported", ["127.0.0.1"], person)
            self.assertEqual(result["cookies"], 1, result)
            # The person's Firefox keeps running; a new session uses the copy.
            agent = self.create("imported")
            core.request(agent, "browser", action="start", url=base + "/check")
            wait_for(
                lambda: any(path == "/check" for path, _ in CookieServer.seen),
                timeout=30,
            )
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(dict(CookieServer.seen)["/check"], "login=yes")

    @unittest.skipUnless(shutil.which("firefox"), "Firefox unavailable")
    def test_imported_session_cookie_is_sent(self):
        CookieServer.seen = []
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), CookieServer)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        person = self.root / "person-firefox"
        person.mkdir()
        # Save the session store every second instead of every 15.
        (person / "user.js").write_text(
            'user_pref("browser.sessionstore.interval", 1000);\n'
        )
        try:
            session = self.create()
            core.request(
                session,
                "launch",
                argv=["firefox", "--profile", str(person), base + "/session-login"],
            )

            def saved():
                try:
                    return cookies.read_session_cookies(person, ["127.0.0.1"])[0]
                except core.DesktopError:
                    return False

            wait_for(lambda: (person / "cookies.sqlite").is_file(), timeout=30)
            wait_for(saved, timeout=30)
            result = cookies.import_firefox_cookies("imported", ["127.0.0.1"], person)
            self.assertEqual(result["session_cookies"], 1, result)
            agent = self.create("imported")
            core.request(agent, "browser", action="start", url=base + "/check")
            wait_for(
                lambda: any(path == "/check" for path, _ in CookieServer.seen),
                timeout=30,
            )
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(dict(CookieServer.seen)["/check"], "session=yes")
