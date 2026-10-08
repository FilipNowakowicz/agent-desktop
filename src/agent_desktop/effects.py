"""Experimental effect ledger: what an action changed inside a private session.

The session owns its home directory, process tree and windows, so the runtime
can report observed effects instead of leaving an agent to infer them from
screenshots. Files are watched with inotify; small text files are kept so a
change can be reported as a line diff. Windows and processes are compared
before and after each action.

Observed effects are evidence, not proof of intent: an application may write
later (asynchronously), write elsewhere (outside the home, over the network)
or change only memory. "Nothing observed" is reported with its time window.
"""

import ctypes
import ctypes.util
import difflib
import fnmatch
import os
import re
import select
import struct
import threading
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree

IN_MODIFY = 0x2
IN_ATTRIB = 0x4
IN_CLOSE_WRITE = 0x8
IN_MOVED_FROM = 0x40
IN_MOVED_TO = 0x80
IN_CREATE = 0x100
IN_DELETE = 0x200
IN_DELETE_SELF = 0x400
IN_Q_OVERFLOW = 0x4000
IN_IGNORED = 0x8000
IN_ISDIR = 0x40000000
IN_NONBLOCK = 0o4000
IN_CLOEXEC = 0o2000000
WATCH_MASK = (
    IN_MODIFY | IN_CLOSE_WRITE | IN_MOVED_FROM | IN_MOVED_TO | IN_CREATE | IN_DELETE
)
EVENT = struct.Struct("iIII")

# Paths whose changes are bookkeeping rather than results: caches, locks,
# journals and crash/telemetry data. Counted, not listed.
NOISE = re.compile(
    r"(^|/)(\.cache|cache2?|Cache|Code Cache|GPUCache|GrShaderCache|ShaderCache|"
    r"DawnCache|DawnGraphiteCache|DawnWebGPUCache|startupCache|Crashpad|"
    r"Crash Reports|crashes|datareporting|saved-telemetry-pings|"
    r"Service Worker|blob_storage|shm|\.lock|lock|SingletonLock|"
    r"SingletonSocket|SingletonCookie|\.~lock\..*#)(/|$)"
    r"|(-journal|-wal|-shm|\.tmp|\.temp|~|\.swp|\.lck)$"
    r"|(^|/)(sessionstore-backups|session|Session Storage|Local Storage|"
    r"IndexedDB|leveldb|TransportSecurity|Network Persistent State|"
    r"Trust Tokens|Reporting and NEL|Favicons|History|Visited Links|"
    r"Top Sites|Shortcuts|Web Data|Preferences|Local State|"
    r"\.local/share/recently-used\.xbel|user-places\.xbel)"
)
TEXT_LIMIT = 256 * 1024
TEXT_BUDGET = 32 * 1024 * 1024
DIFF_LINES = 20
STATE_LIST = 8
LINE_CHARS = 160


def _libc():
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    libc.inotify_init1.argtypes = [ctypes.c_int]
    libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
    return libc


ODF = {
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
}
DOCUMENT_LIMIT = 16 * 1024 * 1024
MAX_CELLS = 20000


def column_name(index):
    name = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def odf_lines(path):
    """An OpenDocument file as canonical lines: spreadsheet cells as
    "Sheet!B3: value" (with "formula" when present), text documents as
    paragraphs. None if it is not readable ODF."""
    try:
        if path.stat().st_size > DOCUMENT_LIMIT:
            return None
        with zipfile.ZipFile(path) as archive:
            root = ElementTree.fromstring(archive.read("content.xml"))
    except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError):
        return None
    table, text = f"{{{ODF['table']}}}", f"{{{ODF['text']}}}"
    lines = []
    tables = root.iter(table + "table")
    for sheet in tables:
        name = sheet.get(table + "name", "?")
        row_index = 0
        for row in sheet.iter(table + "table-row"):
            rows = int(row.get(table + "number-rows-repeated", "1"))
            column = 0
            for cell in row:
                if cell.tag not in (table + "table-cell", table + "covered-table-cell"):
                    continue
                columns = int(cell.get(table + "number-columns-repeated", "1"))
                value = "\n".join("".join(p.itertext()) for p in cell.iter(text + "p"))
                formula = cell.get(table + "formula")
                if value or formula:
                    for r in range(min(rows, 1000)):
                        for c in range(min(columns, 1000)):
                            line = f"{name}!{column_name(column + c)}{row_index + r + 1}: {value}"
                            if formula:
                                line += f"  [{formula}]"
                            lines.append(line)
                            if len(lines) > MAX_CELLS:
                                return "\n".join(lines)
                column += columns
            row_index += rows
    if not lines:
        body = root.find(f"{{{ODF['office']}}}body")
        if body is not None:
            for paragraph in body.iter():
                if paragraph.tag in (text + "p", text + "h"):
                    content = "".join(paragraph.itertext()).strip()
                    if content:
                        lines.append(content)
    return "\n".join(lines)


def read_document(path):
    """Text, or canonical lines for a supported document format, else None."""
    if path.suffix.lower() in (".ods", ".odt", ".fods", ".odp"):
        try:
            if path.is_symlink() or not path.is_file():
                return None
        except OSError:
            return None
        return odf_lines(path)
    return read_text(path)


def read_text(path):
    """Content of a small UTF-8 text file, else None."""
    try:
        if path.is_symlink() or not path.is_file():
            return None
        if path.stat().st_size > TEXT_LIMIT:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:4096]:
        return None
    try:
        return data.decode()
    except UnicodeDecodeError:
        return None


def line_diff(before, after):
    """At most DIFF_LINES changed lines, as '-old' / '+new', each shortened."""
    lines = []
    for line in difflib.unified_diff(
        before.splitlines(), after.splitlines(), lineterm="", n=0
    ):
        if line.startswith(("---", "+++", "@@")):
            continue
        if len(line) > LINE_CHARS:
            line = line[: LINE_CHARS - 1] + "…"
        lines.append(line)
    if len(lines) > DIFF_LINES:
        lines = [*lines[:DIFF_LINES], f"… {len(lines) - DIFF_LINES} more lines"]
    return lines


class FileRecorder:
    """Records file events under a directory tree, with timestamps."""

    def __init__(self, root, label=None):
        self.root = Path(root)
        # Reported paths start with this: "~" for the session home.
        self.label = label or str(self.root)
        self.libc = _libc()
        self.fd = self.libc.inotify_init1(IN_NONBLOCK | IN_CLOEXEC)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1 failed")
        self.watches = {}  # watch descriptor -> directory
        self.events = []  # (monotonic time, kind, path relative to root)
        self.overflowed = False
        self.texts = {}
        self.text_bytes = 0
        self.known = set()  # paths that existed when last reported
        self.lock = threading.Lock()
        self.stopped = False
        started = time.monotonic()
        self.add_tree(self.root, index=True)
        self.index_seconds = time.monotonic() - started
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def add_tree(self, directory, index=False):
        for current, _directories, files in os.walk(directory):
            self.add_watch(Path(current))
            if index:
                for name in files:
                    path = Path(current) / name
                    self.known.add(self.relative(path))
                    self.remember(path)

    def add_watch(self, directory):
        descriptor = self.libc.inotify_add_watch(
            self.fd, os.fsencode(directory), WATCH_MASK
        )
        if descriptor >= 0:
            self.watches[descriptor] = directory

    def relative(self, path):
        return str(path.relative_to(self.root))

    def remember(self, path):
        relative = self.relative(path)
        if NOISE.search(relative):
            return
        text = read_document(path)
        if text is None:
            return
        previous = self.texts.get(relative)
        growth = len(text) - (len(previous) if previous is not None else 0)
        if self.text_bytes + growth > TEXT_BUDGET:
            return
        self.texts[relative] = text
        self.text_bytes += growth

    def run(self):
        while not self.stopped:
            ready, _, _ = select.select([self.fd], [], [], 0.5)
            if not ready:
                continue
            try:
                data = os.read(self.fd, 65536)
            except BlockingIOError:
                continue
            except OSError:
                return
            now = time.monotonic()
            offset = 0
            while offset + EVENT.size <= len(data):
                descriptor, mask, _cookie, length = EVENT.unpack_from(data, offset)
                name = data[offset + EVENT.size : offset + EVENT.size + length]
                offset += EVENT.size + length
                name = name.rstrip(b"\0").decode(errors="replace")
                self.handle(now, descriptor, mask, name)

    def handle(self, now, descriptor, mask, name):
        if mask & IN_Q_OVERFLOW:
            self.overflowed = True
            return
        directory = self.watches.get(descriptor)
        if directory is None or mask & IN_IGNORED:
            self.watches.pop(descriptor, None)
            return
        path = directory / name if name else directory
        if mask & IN_ISDIR:
            if mask & (IN_CREATE | IN_MOVED_TO):
                self.add_tree(path)
            return
        if mask & (IN_CREATE | IN_MOVED_TO):
            kind = "created"
        elif mask & (IN_DELETE | IN_MOVED_FROM):
            kind = "deleted"
        else:
            kind = "modified"
        with self.lock:
            self.events.append((now, kind, self.relative(path)))

    def since(self, start, end=None):
        with self.lock:
            return [
                e for e in self.events if e[0] >= start and (end is None or e[0] <= end)
            ]

    def last_event(self):
        with self.lock:
            return self.events[-1][0] if self.events else None

    def summarize(self, events):
        """Net change per path since it was last reported; text gets a line diff.

        A file created and removed within the window (a temporary file) is
        counted as noise, not listed.
        """
        paths = dict.fromkeys(relative for _at, _kind, relative in events)
        files, noise = [], 0
        for relative in paths:
            path = self.root / relative
            existed, exists = relative in self.known, path.is_file()
            if NOISE.search(relative) or not (existed or exists):
                noise += 1
                continue
            if exists:
                self.known.add(relative)
            else:
                self.known.discard(relative)
            change = (
                "modified"
                if existed and exists
                else ("created" if exists else "deleted")
            )
            entry = {"path": f"{self.label}/{relative}", "change": change}
            if exists:
                before = self.texts.get(relative, "" if not existed else None)
                after = read_document(path)
                if after is None:
                    try:
                        entry["bytes"] = path.stat().st_size
                    except OSError:
                        pass
                else:
                    try:
                        entry["bytes"] = path.stat().st_size
                    except OSError:
                        entry["bytes"] = len(after.encode())
                    if before is not None:
                        diff = line_diff(before, after)
                        if diff:
                            entry["diff"] = diff
                        elif existed:
                            entry["change"] = "rewritten unchanged"
                    self.remember(path)
            else:
                self.texts.pop(relative, None)
            files.append(entry)
        files.sort(key=lambda e: e["path"])
        return files, noise

    def close(self):
        self.stopped = True
        try:
            os.close(self.fd)
        except OSError:
            pass


def window_changes(before, after):
    """Opened, closed and retitled windows and the focus change between lists."""
    old = {w["id"]: w for w in before}
    new = {w["id"]: w for w in after}
    result = {}

    def label(window):
        return f"{window['title']!r} ({window['app_id']})"

    opened = [label(new[i]) for i in new if i not in old]
    closed = [label(old[i]) for i in old if i not in new]
    retitled = [
        f"{old[i]['title']!r} → {new[i]['title']!r}"
        for i in new
        if i in old and old[i]["title"] != new[i]["title"]
    ]
    for key, value in (("opened", opened), ("closed", closed), ("retitled", retitled)):
        if value:
            result[key] = value

    def focused(windows):
        for window in windows:
            if "activated" in window["states"]:
                return label(window)
        return None

    if focused(before) != focused(after):
        result["focus"] = f"{focused(before)} → {focused(after)}"
    return result


def process_changes(before, after, names):
    """Started and exited processes, by command name. before/after: {pid: start}."""
    started = sorted(
        {names(p) or str(p) for p in after if before.get(p) != after[p]} - {None}
    )
    exited = sorted(
        {names.cache.get(p) or str(p) for p in before if after.get(p) != before[p]}
    )
    result = {}
    if started:
        result["started"] = started
    if exited:
        result["exited"] = exited
    return result


class Names:
    """Command names, remembered so exited processes can still be named."""

    def __init__(self):
        self.cache = {}

    def __call__(self, pid):
        try:
            name = Path(f"/proc/{pid}/comm").read_text().strip()
        except OSError:
            return self.cache.get(pid)
        self.cache[pid] = name
        return name


class EffectLedger:
    """Per-action effects: files under the home, windows and processes."""

    def __init__(self, home, windows, processes, quiet=0.15, limit=0.6, extra=()):
        self.recorders = [FileRecorder(home, "~")] + [
            FileRecorder(directory) for directory in extra if Path(directory).is_dir()
        ]
        self.windows = windows  # callable -> current window list
        self.processes = processes  # callable -> {pid: start time}
        self.names = Names()
        self.quiet = quiet
        self.limit = limit
        self.records = {}  # action id -> (start, windows before)
        self.sequence = 0
        for pid in self.processes():
            self.names(pid)

    def begin(self):
        processes = self.processes()
        for pid in processes:
            self.names(pid)
        return {
            "start": time.monotonic(),
            "windows": self.windows(),
            "processes": processes,
        }

    def finish(self, state):
        """Wait briefly for file activity to go quiet, then report effects."""
        deadline = state["start"] + self.limit
        while time.monotonic() < deadline:
            last = max((r.last_event() or 0 for r in self.recorders), default=0) or None
            idle_since = max(last or state["start"], state["start"])
            if time.monotonic() - idle_since >= self.quiet:
                break
            time.sleep(0.03)
        end = time.monotonic()
        self.sequence += 1
        action = self.sequence
        self.records[action] = (state["start"], state["windows"])
        while len(self.records) > 200:
            self.records.pop(next(iter(self.records)))
        processes = self.processes()
        for pid in processes:
            self.names(pid)
        report = self.report(state["start"], end)
        windows = window_changes(state["windows"], self.windows())
        if windows:
            report["windows"] = windows
        changed = process_changes(state["processes"], processes, self.names)
        if changed:
            report["processes"] = changed
        report["effect_id"] = action
        return report

    def report(self, start, end=None):
        files, noise = [], 0
        for recorder in self.recorders:
            found, ignored = recorder.summarize(recorder.since(start, end))
            files += found
            noise += ignored
        report = {"observed_s": round((end or time.monotonic()) - start, 2)}

        # Documents are what a person would call results; application state
        # (dot-directories) is listed separately and shortened.
        def is_state(entry):
            return any(part.startswith(".") for part in entry["path"].split("/")[1:])

        documents = [f for f in files if not is_state(f)]
        state = [
            {**f, "diff": f["diff"][:2]} if "diff" in f else f
            for f in files
            if is_state(f)
        ]
        if documents:
            report["files"] = documents
        if len(state) > STATE_LIST:
            # Many application files (a browser profile starting): counts per
            # directory instead of a list longer than a screenshot.
            counts = {}
            for entry in state:
                directory = "/".join(entry["path"].split("/")[:3])
                counts[directory] = counts.get(directory, 0) + 1
            report["app_state_dirs"] = counts
        elif state:
            report["app_state"] = state
        if noise:
            report["noise_files"] = noise
        if any(r.overflowed for r in self.recorders):
            report["incomplete"] = "file event queue overflowed"
        return report

    def since(self, action):
        """File effects from an earlier action until now (late writes included)."""
        if action not in self.records:
            raise ValueError("Unknown or expired effect_id")
        start, windows = self.records[action]
        report = {"effect_id": action, **self.report(start)}
        changed = window_changes(windows, self.windows())
        if changed:
            report["windows"] = changed
        return report

    def matches(self, action, pattern, quiet=0.3):
        """Whether a file matching `pattern` (e.g. "~/*.ods") changed since the
        action and has had no further events for `quiet` seconds. Does not
        consume the report, so it can be polled."""
        if action not in self.records:
            raise ValueError("Unknown or expired effect_id")
        if not isinstance(pattern, str) or not pattern.startswith(("~/", "/")):
            raise ValueError('File patterns start with "~/" or "/", e.g. "~/*.ods"')
        start, _windows = self.records[action]
        last = {}
        for recorder in self.recorders:
            for at, _kind, relative in recorder.since(start):
                if not NOISE.search(relative):
                    last[f"{recorder.label}/{relative}"] = at
        now = time.monotonic()
        return any(
            fnmatch.fnmatchcase(path, pattern) and now - at >= quiet
            for path, at in last.items()
        )

    def close(self):
        for recorder in self.recorders:
            recorder.close()
