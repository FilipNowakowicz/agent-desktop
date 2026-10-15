"""Copy chosen sites' cookies from the person's Firefox into a named profile.

The person runs this; agents do not. It reads the Firefox profile's files on
disk, so it never touches the screen or the running browser: cookies.sqlite
and its write-ahead log are copied to a private temporary directory and read
there. Only rows whose host is one of the named sites (or a subdomain) are
written into the profile's Firefox (`~/.mozilla/agent-desktop` in its home).
Cookie values are never printed. Session-only cookies (no expiry) live in
Firefox's session store rather than cookies.sqlite and are not copied.
"""

import configparser
import fcntl
import os
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

from . import core

SITE = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+")
# The pinned Firefox profile of a session home (see Worker.pin_browser_profiles).
SESSION_FIREFOX = Path(".mozilla/agent-desktop")


def firefox_roots(env=None):
    env = os.environ if env is None else env
    if env.get("MOZ_APP_DATA"):
        return [Path(env["MOZ_APP_DATA"])]
    home = Path(env.get("HOME") or Path.home())
    return [home / ".mozilla/firefox", home / ".config/mozilla/firefox"]


def default_firefox_profile(env=None):
    """The person's default Firefox profile directory, from profiles.ini."""
    for root in firefox_roots(env):
        ini = root / "profiles.ini"
        if not ini.is_file():
            continue
        config = configparser.RawConfigParser()
        config.read(ini)
        # The install's default (current Firefox), else the profile marked Default=1.
        chosen = [
            (config[s].get("Default"), "1")
            for s in config.sections()
            if s.startswith("Install") and config[s].get("Default")
        ]
        chosen += [
            (config[s].get("Path"), config[s].get("IsRelative", "1"))
            for s in config.sections()
            if s.startswith("Profile") and config[s].get("Default") == "1"
        ]
        for path, relative in chosen:
            if not path:
                continue
            directory = root / path if relative == "1" else Path(path)
            if (directory / "cookies.sqlite").is_file():
                return directory
    raise core.DesktopError(
        "No Firefox profile with cookies found; pass the profile directory with --from"
    )


def site_names(sites):
    names = []
    for site in sites or []:
        name = site.strip().lower().lstrip(".") if isinstance(site, str) else ""
        if not SITE.fullmatch(name) or len(name) > 253:
            raise core.DesktopError(f"Not a site name: {site!r} (e.g. example.com)")
        names.append(name)
    if not names:
        raise core.DesktopError("Name at least one site, e.g. --site example.com")
    return names


def matches(host, sites):
    host = host.lstrip(".").lower()
    return any(host == s or host.endswith("." + s) for s in sites)


def read_cookies(source, sites):
    """(column names, rows, table schema, user_version) of the matching cookies."""
    database = Path(source) / "cookies.sqlite"
    if not database.is_file():
        raise core.DesktopError(f"No cookies.sqlite in {source}")
    with tempfile.TemporaryDirectory(prefix="agent-desktop-cookies-") as temporary:
        copy = Path(temporary) / "cookies.sqlite"
        # The log holds recent changes while Firefox runs; copy it with the file.
        for suffix in ("", "-wal"):
            if Path(f"{database}{suffix}").is_file():
                shutil.copyfile(f"{database}{suffix}", f"{copy}{suffix}")
        connection = sqlite3.connect(copy)
        try:
            return cookie_rows(connection, sites)
        except sqlite3.DatabaseError as error:
            raise core.DesktopError(f"Unreadable cookies.sqlite: {error}") from None
        finally:
            connection.close()


def cookie_rows(connection, sites):
    schema = [
        row[0]
        for row in connection.execute(
            "SELECT sql FROM sqlite_master WHERE tbl_name = 'moz_cookies' "
            "AND sql IS NOT NULL"
        )
    ]
    if not schema:
        raise core.DesktopError("cookies.sqlite has no moz_cookies table")
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    cursor = connection.execute("SELECT * FROM moz_cookies")
    columns = [d[0] for d in cursor.description]
    host = columns.index("host")
    rows = [r for r in cursor if matches(r[host], sites)]
    return columns, rows, schema, version


def import_firefox_cookies(profile, sites, source=None):
    """Copy the cookies of `sites` from the person's Firefox into `profile`.

    The profile must not be in use (its own Firefox would hold the database).
    Existing cookies with the same name, host, path and origin are replaced.
    """
    sites = site_names(sites)
    path = core.profile_path(profile)
    source = Path(source).expanduser() if source else default_firefox_profile()
    columns, rows, schema, version = read_cookies(source, sites)
    home = path / "home"
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or home.is_symlink():
        raise core.DesktopError("Unsafe profile directory")
    with core.profile_lock(path).open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise core.DesktopError(
                f"Profile {profile} is in use by a session; destroy it first"
            ) from None
        target = home / SESSION_FIREFOX
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        database = target / "cookies.sqlite"
        created = not database.exists()
        connection = sqlite3.connect(database)
        try:
            if created:
                # The same schema and version as the person's Firefox writes.
                for statement in schema:
                    connection.execute(statement)
                connection.execute(f"PRAGMA user_version = {int(version)}")
            existing = [
                r[1] for r in connection.execute("PRAGMA table_info(moz_cookies)")
            ]
            kept = [c for c in columns if c != "id" and c in existing]
            indexes = [columns.index(c) for c in kept]
            with connection:
                connection.executemany(
                    f"INSERT OR REPLACE INTO moz_cookies ({', '.join(kept)}) "
                    f"VALUES ({', '.join('?' for _ in kept)})",
                    [[row[i] for i in indexes] for row in rows],
                )
        finally:
            connection.close()
        database.chmod(0o600)
    host = columns.index("host")
    hosts = sorted({row[host] for row in rows})
    return {
        "profile": profile,
        "source": str(source),
        "sites": sites,
        "cookies": len(rows),
        "hosts": hosts,
        "detail": "Session-only cookies are not copied; values are never shown.",
    }
