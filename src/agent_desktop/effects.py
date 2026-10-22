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
import io
import os
import re
import select
import struct
import threading
import time
import zipfile
import zlib
from collections import deque
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
VERSIONS = 6
LINE_CHARS = 160
MAX_EVENTS = 8192
MAX_PATHS = 2048
MAX_WATCHES = 4096
MAX_FAILURES = 32


def text_size(text):
    """Retained UTF-8 payload bytes (Python/container overhead is separate)."""
    return len(text.encode("utf-8")) if text is not None else 0


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
MAX_XML_ELEMENTS = 100000
MAX_XML_DEPTH = 128
MAX_REPEAT = 10**9


def column_name(index):
    name = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


class DocumentText(str):
    """Canonical text with extraction limits, retained with version history."""

    def __new__(cls, value, reasons=()):
        result = super().__new__(cls, value)
        result.coverage = {"complete": not reasons, "reasons": list(reasons)}
        return result


def odf_lines(path, coverage=None):
    """Bounded canonical ODF extraction; coverage describes omitted content."""
    coverage = coverage if coverage is not None else {}
    reasons = []
    try:
        if path.stat().st_size > DOCUMENT_LIMIT:
            raise ValueError("document size limit")
        if path.suffix.lower() == ".fods":
            with path.open("rb") as stream:
                data = stream.read(DOCUMENT_LIMIT + 1)
        else:
            with zipfile.ZipFile(path) as archive:
                if archive.getinfo("content.xml").file_size > DOCUMENT_LIMIT:
                    raise ValueError("decompressed XML size limit")
                with archive.open("content.xml") as stream:
                    data = stream.read(DOCUMENT_LIMIT + 1)
        if len(data) > DOCUMENT_LIMIT:
            raise ValueError("decompressed XML size limit")
        # ODF needs no DTD/entities. Reject them before parsing to bound expansion.
        if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
            raise ValueError("XML declarations unsupported")
        # Reject alternate encodings that could bypass the declaration check.
        if b"\0" in data:
            raise ValueError("non UTF-8 XML unsupported")
        parser = ElementTree.iterparse(io.BytesIO(data), events=("start", "end"))
        depth, elements = 0, 0
        for event, _element in parser:
            if event == "start":
                depth += 1
                elements += 1
                if depth > MAX_XML_DEPTH or elements > MAX_XML_ELEMENTS:
                    raise ValueError("XML depth/element limit")
            else:
                depth -= 1
        root = parser.root
        table, text = f"{{{ODF['table']}}}", f"{{{ODF['text']}}}"
        lines, chars = [], 0

        def append(line):
            nonlocal chars
            cost = len(line) + bool(lines)
            if len(lines) >= MAX_CELLS or chars + cost > TEXT_LIMIT:
                raise OverflowError("extracted text limit")
            lines.append(line)
            chars += cost

        try:
            for sheet in root.iter(table + "table"):
                name = sheet.get(table + "name", "?")
                row_index = 0
                for row in sheet.iter(table + "table-row"):
                    rows = int(row.get(table + "number-rows-repeated", "1"))
                    column = 0
                    for cell in row:
                        if cell.tag not in (
                            table + "table-cell",
                            table + "covered-table-cell",
                        ):
                            continue
                        columns = int(cell.get(table + "number-columns-repeated", "1"))
                        if not (1 <= rows <= MAX_REPEAT and 1 <= columns <= MAX_REPEAT):
                            raise ValueError(
                                "repeated cell count outside supported limits"
                            )
                        value = "\n".join(
                            "".join(p.itertext()) for p in cell.iter(text + "p")
                        )
                        formula = cell.get(table + "formula")
                        if value or formula:
                            if rows > 1000 or columns > 1000:
                                reasons.append("repeated rows/columns limited to 1000")
                            for r in range(min(rows, 1000)):
                                for c in range(min(columns, 1000)):
                                    line = f"{name}!{column_name(column + c)}{row_index + r + 1}: {value}"
                                    if formula:
                                        line += f"  [{formula}]"
                                    append(line)
                        column += columns
                    row_index += rows
            if not lines:
                body = root.find(f"{{{ODF['office']}}}body")
                if body is not None:
                    for paragraph in body.iter():
                        if paragraph.tag in (text + "p", text + "h"):
                            content = "".join(paragraph.itertext()).strip()
                            if content:
                                append(content)
        except OverflowError as error:
            reasons.append(str(error))
        result = DocumentText("\n".join(lines), sorted(set(reasons)))
        coverage.update(result.coverage)
        return result
    except (
        OSError,
        KeyError,
        ValueError,
        zipfile.BadZipFile,
        ElementTree.ParseError,
        RuntimeError,
        EOFError,
        zlib.error,
    ) as error:
        coverage.update(
            complete=False, reasons=[f"document extraction unavailable: {error}"]
        )
        return None


def read_document(path, coverage=None):
    """Text or canonical document lines, with explicit extraction coverage."""
    coverage = coverage if coverage is not None else {}
    if path.suffix.lower() in (".ods", ".odt", ".fods", ".odp"):
        if path.is_symlink() or not path.is_file():
            coverage.update(complete=False, reasons=["not a regular document"])
            return None
        return odf_lines(path, coverage)
    result = read_text(path)
    coverage.update(
        complete=result is not None,
        reasons=[]
        if result is not None
        else ["text unavailable: unreadable, binary or size limit"],
    )
    return result


def read_text(path):
    """Content of a small UTF-8 text file, else None."""
    try:
        if path.is_symlink() or not path.is_file():
            return None
        if path.stat().st_size > TEXT_LIMIT:
            return None
        with path.open("rb") as stream:
            data = stream.read(TEXT_LIMIT + 1)
        if len(data) > TEXT_LIMIT:
            return None
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
        if line.startswith(("---", "+++", "@@")) or not line[1:].strip():
            continue  # headers and blank lines say nothing
        if len(line) > LINE_CHARS:
            line = line[: LINE_CHARS - 1] + "…"
        lines.append(line)
    if len(lines) > DIFF_LINES:
        lines = [*lines[:DIFF_LINES], f"… {len(lines) - DIFF_LINES} more lines"]
    return lines


SECTION = re.compile(r"\[([^\]]+)\]")
KEY_CHANGES = 12


def ini_values(text):
    """{"section/key": value} for INI-style text (GSettings keyfiles, .conf,
    .ini), else None. Needs a [section] header; most other lines must be
    key=value or comments."""
    values, section, other, headers = {}, "", 0, 0
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        header = SECTION.fullmatch(line)
        if header:
            section, headers = header.group(1).strip(), headers + 1
        elif "=" in line:
            key, value = line.split("=", 1)
            values[f"{section}/{key.strip()}"] = value.strip()
        else:
            other += 1
    if not headers or other > len(values) // 4:
        return None
    return values


def key_changes(before, after):
    """Changed keys between two INI texts as "[section] key: old → new", or
    None when either is not INI-style."""
    old, new = ini_values(before or ""), ini_values(after)
    if new is None or (before and old is None):
        return None
    old = old or {}
    changes = []
    for name in sorted(set(old) | set(new)):
        if old.get(name) != new.get(name):
            section, _, key = name.rpartition("/")
            label = f"[{section}] {key}" if section else key
            changes.append(f"{label}: {old.get(name)} → {new.get(name)}")
    if len(changes) > KEY_CHANGES:
        changes = [*changes[:KEY_CHANGES], f"… {len(changes) - KEY_CHANGES} more"]
    return changes


UI_LINES = 12
UI_REUSE_S = 2.0
UI_SETTLE_S = 0.8
UI_POLL_S = 0.08


def ui_lines(nodes):
    """One comparable line per UI element: role, name, text or value, states."""
    lines = []
    for node in nodes:
        line = node["role"]
        if node.get("name"):
            line += f" {node['name'][:80]!r}"
        for field in ("text", "value"):
            if node.get(field) not in (None, ""):
                line += f" {field}={str(node[field])[:80]!r}"
        if node.get("states"):
            line += f" [{','.join(node['states'])}]"
        lines.append(line)
    return lines


def ui_delta(before, after):
    """What appeared, disappeared or changed in the focused window's UI.

    Lines are compared as multisets; an element whose role and name stay but
    whose text, value or states change is reported once as "changed"."""
    if before is None or after is None:
        return None
    if before["window"] != after["window"]:
        shown = after["lines"][:UI_LINES]
        return {"window": after.get("title", after["window"]), "now": shown}
    removed = list(before["lines"])
    added = []
    for line in after["lines"]:
        if line in removed:
            removed.remove(line)
        else:
            added.append(line)

    def key(line):
        return line.split(" text=")[0].split(" value=")[0].split(" [")[0]

    changed = []
    for line in list(added):
        match = next((old for old in removed if key(old) == key(line)), None)
        if match is not None:
            removed.remove(match)
            added.remove(line)
            changed.append(f"{match} → {line[len(key(line)) :].strip() or '(no text)'}")
    delta = {}
    for name, lines in (("added", added), ("removed", removed), ("changed", changed)):
        if lines:
            if len(lines) > UI_LINES:
                lines = [*lines[:UI_LINES], f"… {len(lines) - UI_LINES} more"]
            delta[name] = lines
    return delta


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
        self.events = deque()  # (monotonic time, kind, path relative to root)
        self.overflowed = False
        self.failures = deque(maxlen=MAX_FAILURES)
        self.failure_count = 0
        self.expired_before = 0.0
        self.expiry_lock = threading.Lock()
        self.baseline_gaps = False
        # relative path -> [(time observed, exists, text or None)], oldest first,
        # so a report can diff against the state before any given action.
        self.versions = {}
        self.text_bytes = 0
        self.pending = {}  # relative path -> time of its latest unobserved event
        self.state_lock = threading.RLock()
        self.lock = threading.Lock()
        self.stopped = False
        started = time.monotonic()
        self.add_tree(self.root, index=True)
        self.index_seconds = time.monotonic() - started
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def add_tree(self, directory, index=False, found=None):
        """Watch a tree. `index` remembers existing files (start); `found` is the
        time a new directory appeared: files already inside it were written
        before its watch existed, so they are recorded as created then."""
        for current, _directories, files in os.walk(directory, onerror=self.failure):
            self.add_watch(Path(current))
            for name in files:
                path = Path(current) / name
                if index:
                    self.record(self.relative(path), 0.0)
                elif found is not None:
                    with self.lock:
                        self.event(found, "created", self.relative(path))

    def failure(self, error):
        with self.state_lock:
            self.failure_count += 1
            self.failures.append(str(error))

    def expire(self, at):
        with self.expiry_lock:
            self.expired_before = max(self.expired_before, at)

    def event(self, at, kind, relative):
        if len(self.events) >= MAX_EVENTS:
            self.expire(self.events.popleft()[0])
        self.events.append((at, kind, relative))

    def add_watch(self, directory):
        if len(self.watches) >= MAX_WATCHES:
            self.failure(f"watch limit: {directory}")
            return
        descriptor = self.libc.inotify_add_watch(
            self.fd, os.fsencode(directory), WATCH_MASK
        )
        if descriptor >= 0:
            self.watches[descriptor] = directory
        else:
            self.failure(
                f"watch registration failed: {directory} (errno {ctypes.get_errno()})"
            )

    def relative(self, path):
        return str(path.relative_to(self.root))

    def record(self, relative, at):
        """Observe a file now and keep it as a version (bounded history)."""
        with self.state_lock:
            return self._record(relative, at)

    def _record(self, relative, at):
        path = self.root / relative
        try:
            exists = path.is_file() and not path.is_symlink()
            text = (
                read_document(path) if exists and not NOISE.search(relative) else None
            )
        except OSError as error:
            self.failure(f"file read failed: {relative}: {error}")
            exists, text = None, None
        if text is not None and self.text_bytes + text_size(text) > TEXT_BUDGET:
            text = None
        if relative not in self.versions and len(self.versions) >= MAX_PATHS:
            removed = self.versions.pop(next(iter(self.versions)))
            self.text_bytes -= sum(text_size(v[2]) for v in removed)
            self.expire(time.monotonic())
            self.baseline_gaps = True
        history = self.versions.setdefault(relative, [])
        history.append((at, exists, text))
        self.text_bytes += text_size(text)
        while len(history) > VERSIONS:
            removed = history.pop(0)
            self.text_bytes -= text_size(removed[2])
            self.expire(history[0][0])
        return exists, text

    def before(self, relative, start):
        """(existed, text) as last observed before `start`."""
        with self.state_lock:
            if start <= self.expired_before and self.expired_before:
                return None, None
            for at, exists, text in reversed(self.versions.get(relative, [])):
                if at < start:
                    return exists, text
            # Initial indexing establishes absence only without gaps, and a
            # first creation event is the only safe missing-history baseline.
            events = [e for e in self.since(0) if e[2] == relative]
            if (
                not self.failure_count
                and not self.overflowed
                and not self.baseline_gaps
                and events
            ):
                if events[0][1] == "created" and events[0][0] >= start:
                    return False, None
        return None, None

    def observe_quiet(self, quiet=0.1):
        """Version files whose events stopped `quiet` seconds ago, stamped with
        their last event time: the state they reached then."""
        now = time.monotonic()
        with self.lock:
            ready = [(r, at) for r, at in self.pending.items() if now - at >= quiet]
            for relative, _at in ready:
                del self.pending[relative]
        for relative, at in ready:
            self.record(relative, at)

    def run(self):
        while not self.stopped:
            try:
                ready, _, _ = select.select(
                    [self.fd], [], [], 0.05 if self.pending else 0.5
                )
            except (OSError, ValueError) as error:
                if not self.stopped:
                    self.failure(f"watch read failed: {error}")
                return
            if self.stopped:
                return
            self.observe_quiet()
            if not ready:
                continue
            try:
                data = os.read(self.fd, 65536)
            except BlockingIOError:
                continue
            except OSError as error:
                if not self.stopped:
                    self.failure(f"watch read failed: {error}")
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
                self.add_tree(path, found=now)
            return
        if mask & (IN_CREATE | IN_MOVED_TO):
            kind = "created"
        elif mask & (IN_DELETE | IN_MOVED_FROM):
            kind = "deleted"
        else:
            kind = "modified"
        relative = self.relative(path)
        with self.lock:
            self.event(now, kind, relative)
            if relative not in self.pending and len(self.pending) >= MAX_PATHS:
                self.expire(self.pending.pop(next(iter(self.pending))))
                self.baseline_gaps = True
            self.pending[relative] = now

    def since(self, start, end=None):
        with self.lock:
            return [
                e for e in self.events if e[0] >= start and (end is None or e[0] <= end)
            ]

    def last_event(self):
        with self.lock:
            return self.events[-1][0] if self.events else None

    def summarize(self, events, start):
        """Net change per path relative to its state before `start`; text gets a
        line diff. A file created and removed within the window (a temporary
        file) is counted as noise, not listed. Repeated reports for the same
        start give the same answer (versions, not a single moving baseline)."""
        paths = dict.fromkeys(relative for _at, _kind, relative in events)
        files, noise = [], 0
        for relative in paths:
            if NOISE.search(relative):
                noise += 1
                continue
            existed, before = self.before(relative, start)
            path = self.root / relative
            coverage = {}
            try:
                exists = path.is_file() and not path.is_symlink()
            except OSError as error:
                exists = None
                coverage.update(complete=False, reasons=[str(error)])
            try:
                after = read_document(path, coverage) if exists else None
            except OSError as error:
                after = None
                coverage.update(
                    complete=False, reasons=[f"document read failed: {error}"]
                )
            if existed is False and exists is False:
                noise += 1
                continue
            change = (
                "baseline_unknown"
                if existed is None
                else "current_unknown"
                if exists is None
                else "modified"
                if existed and exists
                else ("created" if exists else "deleted")
            )
            entry = {"path": f"{self.label}/{relative}", "change": change}
            if coverage and not coverage.get("complete"):
                entry["document_coverage"] = coverage
            prior_coverage = getattr(before, "coverage", None)
            if prior_coverage and not prior_coverage["complete"]:
                entry["baseline_document_coverage"] = prior_coverage
            elif existed and before is None:
                entry["baseline_document_coverage"] = {
                    "complete": False,
                    "reasons": ["baseline text unavailable or retention text budget"],
                }
            if exists:
                try:
                    entry["bytes"] = (self.root / relative).stat().st_size
                except OSError:
                    pass
                if after is not None:
                    if existed is False:
                        before = ""
                    if before is not None:
                        keys = key_changes(before, after)
                        diff = keys if keys is not None else line_diff(before, after)
                        if diff:
                            entry["keys" if keys is not None else "diff"] = diff
                        elif (
                            existed
                            and before == after
                            and coverage.get("complete")
                            and (not prior_coverage or prior_coverage["complete"])
                        ):
                            entry["change"] = (
                                "canonical text unchanged"
                                if isinstance(after, DocumentText)
                                else "rewritten unchanged"
                            )
            files.append(entry)
        files.sort(key=lambda e: e["path"])
        return files, noise

    def close(self):
        if self.stopped:
            return
        self.stopped = True
        self.thread.join(timeout=1)
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
                return window
        return None

    old_focus, new_focus = focused(before), focused(after)
    # By id: a retitled window keeps its focus.
    if (old_focus or {}).get("id") != (new_focus or {}).get("id"):
        result["focus"] = (
            f"{label(old_focus) if old_focus else None} → "
            f"{label(new_focus) if new_focus else None}"
        )
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

    def __init__(
        self, home, windows, processes, quiet=0.15, limit=0.6, extra=(), ui=None
    ):
        self.recorders = [FileRecorder(home, "~")] + [
            FileRecorder(directory) for directory in extra if Path(directory).is_dir()
        ]
        self.windows = windows  # callable -> current window list
        # callable -> {"window": id, "title": ..., "lines": ui_lines(...)} or None
        self.ui = ui
        self.last_ui = None  # (monotonic time, snapshot)
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
        windows = self.windows()
        return {
            "start": time.monotonic(),
            "windows": windows,
            "processes": processes,
            "ui": self.recent_snapshot(windows),
        }

    def settled_ui(self, state):
        """The UI at its first observed change, or as it is after UI_SETTLE_S
        when nothing changed (applications such as Chromium update their tree
        some hundred milliseconds after input). Later changes are reported by
        desktop_effects with the action's effect_id."""
        before = state["ui"]
        if before is None:
            return self.snapshot()
        deadline = state["start"] + UI_SETTLE_S
        while True:
            current = self.snapshot()
            if current is not None and current != before:
                return current
            if time.monotonic() >= deadline:
                return current
            time.sleep(UI_POLL_S)

    def recent_snapshot(self, windows):
        """The last report's UI when it is fresh and still the focused window
        (back-to-back steps), else a new snapshot: one tree walk, not two."""
        focused = next(
            (w["id"] for w in windows if "activated" in w.get("states", [])), None
        )
        cached = self.last_ui
        if (
            cached
            and cached[1] is not None
            and time.monotonic() - cached[0] < UI_REUSE_S
            and cached[1]["window"] == focused
        ):
            return cached[1]
        return self.snapshot()

    def snapshot(self):
        if not self.ui:
            return None
        try:
            found = self.ui()
        except Exception:  # noqa: BLE001 - UI deltas are best effort
            found = None
        self.last_ui = (time.monotonic(), found)
        return found

    def finish(self, state):
        """Wait briefly for file activity to go quiet, then report effects."""
        deadline = state["start"] + self.limit
        while time.monotonic() < deadline:
            last = max((r.last_event() or 0 for r in self.recorders), default=0) or None
            idle_since = max(last or state["start"], state["start"])
            if time.monotonic() - idle_since >= self.quiet:
                break
            time.sleep(0.03)
        after_ui = self.settled_ui(state)
        end = time.monotonic()
        self.sequence += 1
        action = self.sequence
        self.records[action] = (state["start"], state["windows"], state["ui"])
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
        ui = ui_delta(state["ui"], after_ui)
        if ui:
            report["ui"] = ui
        report["effect_id"] = action
        return report

    def report(self, start, end=None):
        files, noise = [], 0
        for recorder in self.recorders:
            found, ignored = recorder.summarize(recorder.since(start, end), start)
            files += found
            noise += ignored
        report = {"observed_s": round((end or time.monotonic()) - start, 2)}

        # Documents are what a person would call results; application state
        # (dot-directories) is listed separately and shortened.
        def is_state(entry):
            return any(part.startswith(".") for part in entry["path"].split("/")[1:])

        documents = [f for f in files if not is_state(f)]
        state = [
            {**f, "diff": f["diff"][:3]} if "diff" in f else f
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
        coverage = []
        for recorder in self.recorders:
            reasons = []
            if recorder.overflowed:
                reasons.append("file event queue overflowed")
            with recorder.state_lock:
                failure_count = recorder.failure_count
                failures = list(recorder.failures)
            if failure_count:
                reasons.append("watch registration, traversal or read failures")
            if recorder.expired_before and start <= recorder.expired_before:
                reasons.append("file evidence expired")
            coverage.append(
                {
                    "root": recorder.label,
                    "complete": not reasons,
                    "reasons": reasons,
                    "failure_count": failure_count,
                    "failures": failures,
                    "expired_before": recorder.expired_before,
                }
            )
        report["file_coverage"] = coverage
        if any(not item["complete"] for item in coverage):
            report["incomplete"] = "file evidence has gaps; see file_coverage"
        return report

    def since(self, action):
        """File effects from an earlier action until now (late writes included)."""
        if action not in self.records:
            raise ValueError("Unknown or expired effect_id")
        start, windows, ui = self.records[action]
        report = {"effect_id": action, **self.report(start)}
        changed = window_changes(windows, self.windows())
        if changed:
            report["windows"] = changed
        ui = ui_delta(ui, self.snapshot())
        if ui:
            report["ui"] = ui
        return report

    def matches(self, action, pattern, quiet=0.3):
        """Whether a file matching `pattern` (e.g. "~/*.ods") changed since the
        action and has had no further events for `quiet` seconds. Does not
        consume the report, so it can be polled."""
        if action not in self.records:
            raise ValueError("Unknown or expired effect_id")
        if not isinstance(pattern, str) or not pattern.startswith(("~/", "/")):
            raise ValueError('File patterns start with "~/" or "/", e.g. "~/*.ods"')
        start = self.records[action][0]
        last = {}
        for recorder in self.recorders:
            for at, kind, relative in recorder.since(start):
                if NOISE.search(relative):
                    continue
                path = f"{recorder.label}/{relative}"
                # A deleted file is not a written one.
                if kind == "deleted" or not (recorder.root / relative).is_file():
                    last.pop(path, None)
                else:
                    last[path] = at
        now = time.monotonic()
        return any(
            fnmatch.fnmatchcase(path, pattern) and now - at >= quiet
            for path, at in last.items()
        )

    def close(self):
        for recorder in self.recorders:
            recorder.close()
