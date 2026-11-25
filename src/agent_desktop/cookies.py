"""Copy chosen sites' cookies from the person's Firefox into a named profile.

The person runs this; agents do not. It reads the Firefox profile's files on
disk, so it never touches the screen or the running browser: cookies.sqlite
and its write-ahead log are copied to a private temporary directory and read
there. Only rows whose host is one of the named sites (or a subdomain) are
written into the profile's Firefox (`~/.mozilla/agent-desktop` in its home).
Cookie values are never printed.

Session-only cookies (no expiry) are not in cookies.sqlite: Firefox keeps them
in memory and saves them in its session store (sessionstore-backups/
recovery.jsonlz4 while it runs, sessionstore.jsonlz4 after a clean shutdown).
The newest readable one is copied to the temporary directory too, decoded
(mozLz4: a magic, the decoded size and one LZ4 block) and its matching cookies
are written as persistent cookies that expire SESSION_COOKIE_HOURS after the
import, because Firefox reads only persistent cookies from cookies.sqlite. A
missing or unreadable session store is reported, not fatal. keep_session_cookies
does the same within a session's own profile after a login handoff, so a
login survives the private Firefox restarting under the bridge.
"""

import configparser
import datetime
import fcntl
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
import urllib.parse
from pathlib import Path

from . import core

# Sites where one browser can stay signed in to several accounts at once; an
# import copies all of them, and the site's default account may be the wrong one.
MULTI_ACCOUNT = (
    "google.com",
    "youtube.com",
    "live.com",
    "microsoft.com",
    "microsoftonline.com",
    "github.com",
)
SITE = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+")
# The pinned Firefox profile of a session home (see Worker.pin_browser_profiles).
SESSION_FIREFOX = Path(".mozilla/agent-desktop")
# Where Firefox saves session-only cookies, while it runs and after it quits.
SESSION_STORES = ("sessionstore-backups/recovery.jsonlz4", "sessionstore.jsonlz4")
MOZLZ4_MAGIC = b"mozLz40\0"
SESSION_STORE_BYTES = 256 * 1024 * 1024  # decoded; a larger claim is corrupt
# A copied session-only cookie becomes a persistent one that expires this long
# after the import: long enough for the task, short enough that a login the
# person did not ask to remember does not stay in the profile for weeks.
SESSION_COOKIE_HOURS = 24


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


SESSION_COLUMNS = {
    "originAttributes",
    "name",
    "value",
    "host",
    "path",
    "expiry",
    "lastAccessed",
    "creationTime",
    "isSecure",
    "isHttpOnly",
    "inBrowserElement",
    "sameSite",
    "rawSameSite",
    "schemeMap",
}


def lz4_block(data, size):
    """Decode one LZ4 block (https://github.com/lz4/lz4/blob/dev/doc/lz4_Block_format.md)
    that must expand to exactly `size` bytes. Raises ValueError if it is corrupt."""
    out = bytearray()
    i, end = 0, len(data)
    try:
        while i < end:
            token = data[i]
            i += 1
            length = token >> 4
            if length == 15:
                while True:
                    extra = data[i]
                    i += 1
                    length += extra
                    if extra != 255:
                        break
            if i + length > end:
                raise ValueError("truncated")
            out += data[i : i + length]
            i += length
            if i == end:
                break  # the last sequence has literals only
            offset = data[i] | data[i + 1] << 8
            i += 2
            length = token & 15
            if length == 15:
                while True:
                    extra = data[i]
                    i += 1
                    length += extra
                    if extra != 255:
                        break
            length += 4
            if not 0 < offset <= len(out):
                raise ValueError("match offset outside the output")
            start = len(out) - offset
            if offset >= length:
                out += out[start : start + length]
            else:  # the match overlaps itself: it repeats the last `offset` bytes
                pattern = bytes(out[start:])
                out += (pattern * (length // offset + 1))[:length]
            if len(out) > size:
                break
    except IndexError:
        raise ValueError("truncated") from None
    if len(out) != size:
        raise ValueError("decoded size does not match its header")
    return bytes(out)


def read_mozlz4(path):
    """The decoded bytes of a Firefox mozLz4 file. Raises ValueError if corrupt."""
    data = Path(path).read_bytes()
    if len(data) < 12 or data[:8] != MOZLZ4_MAGIC:
        raise ValueError("not a mozLz4 file")
    size = int.from_bytes(data[8:12], "little")
    if size > SESSION_STORE_BYTES:
        raise ValueError("decoded size too large")
    return lz4_block(data[12:], size)


def read_session_cookies(source, sites, since=None):
    """(matching session-only cookies, the store they came from, problems).

    The session stores are copied to a private temporary directory and the
    newest readable one is used. `sites` None matches every host; a store
    last written before `since` (a time.time() value) is left out as stale.
    Problems name a file and what is wrong with it, never its contents.
    """
    stores = []
    for name in SESSION_STORES:
        path = Path(source) / name
        if path.is_file():
            written = path.stat().st_mtime
            if since is None or written >= since:
                stores.append((written, name, path))
    stores.sort(reverse=True)
    problems = []
    with tempfile.TemporaryDirectory(prefix="agent-desktop-cookies-") as temporary:
        for _, name, path in stores:
            copy = Path(temporary) / Path(name).name
            try:
                shutil.copyfile(path, copy)
                store = json.loads(read_mozlz4(copy))
            except OSError:
                problems.append(f"{name} could not be read")
                continue
            except UnicodeDecodeError:  # its message quotes the bytes
                problems.append(f"{name} is unreadable (not UTF-8)")
                continue
            except (json.JSONDecodeError, RecursionError):
                problems.append(f"{name} is unreadable (not JSON)")
                continue
            except ValueError as error:  # read_mozlz4's own messages
                problems.append(f"{name} is unreadable ({error})")
                continue
            entries = store.get("cookies") if isinstance(store, dict) else None
            if not isinstance(entries, list):
                entries = []
            found = [
                c
                for c in entries
                if isinstance(c, dict)
                and all(isinstance(c.get(k, ""), str) for k in ("name", "path"))
                and isinstance(c.get("host"), str)
                and isinstance(c.get("value"), str)
                and (sites is None or matches(c["host"], sites))
                and origin_suffix(c.get("originAttributes")) is not None
            ]
            return found, name, problems
    return [], None, problems


def origin_suffix(attributes):
    """Firefox's originAttributes text (e.g. "^userContextId=2") for the
    session store's object, or None for a private-browsing cookie."""
    if not isinstance(attributes, dict):
        return ""
    if attributes.get("privateBrowsingId"):
        return None
    parts = []
    container = attributes.get("userContextId") or 0
    if container:
        if not isinstance(container, int):
            return None
        parts.append(f"userContextId={container}")
    for key in ("firstPartyDomain", "geckoViewSessionContextId", "partitionKey"):
        value = attributes.get(key) or ""
        if value:
            if not isinstance(value, str):
                return None
            parts.append(f"{key}={urllib.parse.quote(value, safe='*-._')}")
    return "^" + "&".join(parts) if parts else ""


def session_row(cookie, expiry, now, index):
    """moz_cookies column values for one session store cookie."""
    same_site = cookie.get("sameSite") if isinstance(cookie.get("sameSite"), int) else 0
    scheme = cookie.get("schemeMap") if isinstance(cookie.get("schemeMap"), int) else 0
    return {
        "originAttributes": origin_suffix(cookie.get("originAttributes")),
        "name": cookie.get("name", ""),
        "value": cookie["value"],
        "host": cookie["host"],
        "path": cookie.get("path", "/"),
        "expiry": expiry,
        # Microseconds; distinct creation times keep Firefox's ordering stable.
        "lastAccessed": now + index,
        "creationTime": now + index,
        "isSecure": int(cookie.get("secure") is True),
        "isHttpOnly": int(cookie.get("httponly") is True),
        "inBrowserElement": 0,
        "sameSite": same_site,
        "rawSameSite": same_site,
        "schemeMap": scheme,
    }


def read_cookies(source, sites):
    """(column names, rows, table schema, user_version, expiry in milliseconds)
    of the matching cookies."""
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
    # Firefox 160 (schema 17) stores expiry in milliseconds, older ones in
    # seconds. Go by the stored values (any year-5000+ second count is a
    # millisecond one), else by the schema version.
    (latest,) = connection.execute("SELECT max(expiry) FROM moz_cookies").fetchone()
    milliseconds = latest > 10**11 if latest else version >= 17
    return columns, rows, schema, version, milliseconds


def import_firefox_cookies(profile, sites, source=None):
    """Copy the cookies of `sites` from the person's Firefox into `profile`.

    The profile must not be in use (its own Firefox would hold the database).
    Existing cookies with the same name, host, path and origin are replaced.
    """
    sites = site_names(sites)
    path = core.profile_path(profile)
    source = Path(source).expanduser() if source else default_firefox_profile()
    columns, rows, schema, version, milliseconds = read_cookies(source, sites)
    session, store, problems = read_session_cookies(source, sites)
    now = time.time()
    until = now + SESSION_COOKIE_HOURS * 3600
    expiry = int(until * 1000) if milliseconds else int(until)
    session_rows = [
        session_row(c, expiry, int(now * 1_000_000), i) for i, c in enumerate(session)
    ]
    # A cookie is one (name, host, path, originAttributes); the session store's
    # copy is the browser's current one, so it replaces a persistent row.
    key = [c for c in ("name", "host", "path", "originAttributes") if c in columns]
    replaced = {tuple(r[c] for c in key) for r in session_rows}
    indexes = [columns.index(c) for c in key]
    rows = [r for r in rows if tuple(r[i] for i in indexes) not in replaced]
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
            # Columns this module does not know keep their defaults.
            known = [c for c in kept if c in SESSION_COLUMNS]
            with connection:
                connection.executemany(
                    f"INSERT OR REPLACE INTO moz_cookies ({', '.join(kept)}) "
                    f"VALUES ({', '.join('?' for _ in kept)})",
                    [[row[i] for i in indexes] for row in rows],
                )
                connection.executemany(
                    f"INSERT OR REPLACE INTO moz_cookies ({', '.join(known)}) "
                    f"VALUES ({', '.join('?' for _ in known)})",
                    [[row[c] for c in known] for row in session_rows],
                )
        finally:
            connection.close()
        database.chmod(0o600)
    host = columns.index("host")
    hosts = sorted({row[host] for row in rows} | {r["host"] for r in session_rows})
    result = {
        "profile": profile,
        "source": str(source),
        "sites": sites,
        "cookies": len(rows) + len(session_rows),
        "persistent_cookies": len(rows),
        "session_cookies": len(session_rows),
        "hosts": hosts,
    }
    if session_rows:
        stamp = datetime.datetime.fromtimestamp(until, datetime.UTC)
        result["session_cookies_expire"] = stamp.isoformat(timespec="seconds")
    if store:
        detail = (
            f"Session-only cookies were read from {store} and copied with a "
            f"{SESSION_COOKIE_HOURS}-hour expiry, so they also survive the private "
            "Firefox restarting until then; the site may still end the login "
            "sooner."
        )
    else:
        detail = "No session store was found, so no session-only cookies were copied."
    if problems:
        detail += f" Skipped: {'; '.join(problems)}."
    result["detail"] = detail + " Values are never shown."
    several = sorted({m for m in MULTI_ACCOUNT for h in hosts if matches(h, [m])})
    if several:
        result["warning"] = (
            f"{', '.join(several)} can keep several accounts signed in at once, "
            "and every one of them was copied; the site's default account may not "
            "be the one you want. To bring a single account, sign only that one in "
            "to a fresh Firefox profile (MOZ_NO_REMOTE=1 firefox --new-instance "
            "--profile DIR), then import with --from DIR. forget-site removes a "
            "site from this profile again. Record which account the profile "
            "uses with profile-note."
        )
    return result


def keep_session_cookies(directory, since=None, now=None):
    """Make the session-only cookies a quit Firefox saved in its session store
    persistent in its own cookies.sqlite, expiring SESSION_COOKIE_HOURS from now.

    For a session's own profile after a login handoff: Firefox started under
    the bridge does not restore the session store, so without this a login
    that did not "remember me" is gone. Firefox must not be running on
    `directory`. Returns {"kept": count, "store": file or None, "expires":
    ISO time or None, "problems": [...]}; nothing here raises for unreadable
    files.
    """
    directory = Path(directory)
    now = time.time() if now is None else now
    result = {"kept": 0, "store": None, "expires": None, "problems": []}
    session, store, problems = read_session_cookies(directory, None, since)
    result.update(store=store, problems=problems)
    if not session:
        return result
    database = directory / "cookies.sqlite"
    if not database.is_file() or database.is_symlink():
        problems.append("cookies.sqlite is missing")
        return result
    until = now + SESSION_COOKIE_HOURS * 3600
    try:
        connection = sqlite3.connect(database)
        try:
            existing = [
                r[1] for r in connection.execute("PRAGMA table_info(moz_cookies)")
            ]
            if not existing:
                problems.append("cookies.sqlite has no moz_cookies table")
                return result
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            (latest,) = connection.execute(
                "SELECT max(expiry) FROM moz_cookies"
            ).fetchone()
            # As in cookie_rows: milliseconds from Firefox 160 (schema 17).
            milliseconds = latest > 10**11 if latest else version >= 17
            expiry = int(until * 1000) if milliseconds else int(until)
            rows = [
                session_row(c, expiry, int(now * 1_000_000), i)
                for i, c in enumerate(session)
            ]
            known = [c for c in rows[0] if c in existing]
            with connection:
                connection.executemany(
                    f"INSERT OR REPLACE INTO moz_cookies ({', '.join(known)}) "
                    f"VALUES ({', '.join('?' for _ in known)})",
                    [[row[c] for c in known] for row in rows],
                )
        finally:
            connection.close()
    except sqlite3.DatabaseError as error:
        problems.append(f"cookies.sqlite could not be written ({error})")
        return result
    stamp = datetime.datetime.fromtimestamp(until, datetime.UTC)
    result.update(kept=len(rows), expires=stamp.isoformat(timespec="seconds"))
    return result


def storage_host(name):
    """The host of a Firefox storage/default directory name, or None.

    Names look like https+++accounts.example.com, with an optional +PORT and
    ^attributes suffix.
    """
    scheme, separator, rest = name.partition("+++")
    if not separator or not scheme.isalpha():
        return None
    return re.split(r"[+^]", rest, maxsplit=1)[0] or None


def forget_site(profile, sites):
    """Remove `sites` (and their subdomains) from a profile's Firefox.

    Deletes their cookies and their site storage (localStorage, IndexedDB and
    caches under storage/default). History, bookmarks and the session store are
    left alone. The profile must not be in use.
    """
    sites = site_names(sites)
    path = core.profile_path(profile)
    if not path.is_dir():
        raise core.DesktopError(f"No profile named {profile}")
    target = path / "home" / SESSION_FIREFOX
    with core.profile_lock(path).open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise core.DesktopError(
                f"Profile {profile} is in use by a session; destroy it first"
            ) from None
        removed_cookies = 0
        database = target / "cookies.sqlite"
        if database.is_file() and not database.is_symlink():
            connection = sqlite3.connect(database)
            try:
                hosts = [
                    h
                    for (h,) in connection.execute(
                        "SELECT DISTINCT host FROM moz_cookies"
                    )
                    if matches(h, sites)
                ]
                with connection:
                    for h in hosts:
                        removed_cookies += connection.execute(
                            "DELETE FROM moz_cookies WHERE host = ?", (h,)
                        ).rowcount
            except sqlite3.DatabaseError as error:
                raise core.DesktopError(f"Unreadable cookies.sqlite: {error}") from None
            finally:
                connection.close()
        removed_storage = []
        storage = target / "storage" / "default"
        if storage.is_dir() and not storage.is_symlink():
            for entry in sorted(storage.iterdir()):
                host = storage_host(entry.name)
                if host and matches(host, sites) and not entry.is_symlink():
                    shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
                    removed_storage.append(entry.name)
    return {
        "profile": profile,
        "sites": sites,
        "cookies_removed": removed_cookies,
        "storage_removed": removed_storage,
        "detail": "History, bookmarks and the session store are not changed.",
    }


def expiry_text(expiry, milliseconds):
    """ISO time (UTC) of a stored expiry, or "session" for none."""
    if not expiry or expiry <= 0:
        return "session"
    seconds = expiry / 1000 if milliseconds else expiry
    try:
        moment = datetime.datetime.fromtimestamp(seconds, datetime.UTC)
    except (OverflowError, OSError, ValueError):
        return "never"
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def site_cookies(profile, sites):
    """List the cookies of `sites` (and subdomains) a saved profile holds.

    Read-only and never shows values: only host, name, path, expiry and the
    secure/httpOnly flags, plus the names of the site's storage directories.
    The profile must not be in use. The database is read from a copy, so a
    write by Firefox can never be corrupted.
    """
    sites = site_names(sites)
    path = core.profile_path(profile)
    if not path.is_dir():
        raise core.DesktopError(f"No profile named {profile}")
    target = path / "home" / SESSION_FIREFOX
    with core.profile_lock(path).open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise core.profile_busy(profile, path) from None
        listed = []
        database = target / "cookies.sqlite"
        if database.is_file() and not database.is_symlink():
            columns, rows, _schema, _version, milliseconds = read_cookies(target, sites)
            index = {name: i for i, name in enumerate(columns)}
            for row in rows:
                listed.append(
                    {
                        "host": row[index["host"]],
                        "name": row[index["name"]],
                        "path": row[index["path"]],
                        "expires": expiry_text(row[index["expiry"]], milliseconds),
                        "secure": bool(row[index["isSecure"]]),
                        "http_only": bool(row[index["isHttpOnly"]]),
                    }
                )
            listed.sort(key=lambda c: (c["host"].lstrip("."), c["name"], c["path"]))
        storage_names = []
        storage = target / "storage" / "default"
        if storage.is_dir() and not storage.is_symlink():
            for entry in sorted(storage.iterdir()):
                host = storage_host(entry.name)
                if host and matches(host, sites) and not entry.is_symlink():
                    storage_names.append(entry.name)
    return {
        "profile": profile,
        "sites": sites,
        "cookies": listed,
        "storage": storage_names,
        "detail": "Values are never shown. forget-site removes a site again.",
    }
