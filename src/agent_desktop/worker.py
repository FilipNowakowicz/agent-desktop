"""One supervisor, private D-Bus and compositor per session."""

import base64
import ctypes
import fcntl
import hashlib
import json
import math
import os
import pwd
import re
import select
import shlex
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from . import printed
from .atspi import (
    Accessibility,
    AccessibilityError,
    Interrupted,
    Unsupported,
    name_has_owner,
    wait_for_registry,
)
from .effects import EffectLedger, ui_lines
from .secret_text import hide_fields
from .wayland import (
    BUTTONS,
    BindLayout,
    InputActivity,
    Keysyms,
    Toplevels,
    VirtualKeyboard,
    VirtualPointer,
    WaylandError,
    clear_selection,
    peer_pid,
    read_selection,
    set_output_size,
)

PR_SET_CHILD_SUBREAPER = 36


def become_subreaper():
    """Keep orphaned descendants, including daemons, inside this worker's tree."""
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0):
        raise OSError(ctypes.get_errno(), "Cannot become a child subreaper")


def process_table():
    """Return {pid: (parent pid, state, start time)} for every visible process.

    The start time (clock ticks since boot, /proc/<pid>/stat field 22) tells a
    process apart from a later one that reuses its number.
    """
    table = {}
    for path in Path("/proc").iterdir():
        if not path.name.isdecimal():
            continue
        try:
            stat = (path / "stat").read_text()
        except OSError:
            continue
        # The command name may contain spaces or parentheses; fields follow the last ")".
        fields = stat[stat.rindex(")") + 2 :].split()
        table[int(path.name)] = (int(fields[1]), fields[0], int(fields[19]))
    return table


def process_groups(table):
    """{pid: (process group, session)} for the processes in `table`."""
    groups = {}
    for pid in table:
        try:
            stat = Path(f"/proc/{pid}/stat").read_text()
        except OSError:
            continue
        fields = stat[stat.rindex(")") + 2 :].split()
        groups[pid] = (int(fields[2]), int(fields[3]))
    return groups


def boot_id():
    """This boot's identifier: a process start time means nothing across boots."""
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return None


def start_time(pid):
    """A process's start time, or None if it no longer exists."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    return int(stat[stat.rindex(")") + 2 :].split()[19])


def signal_process(pid, started, sig):
    """Signal pid only if it is still the process that started at `started`.

    Teardown scans /proc and signals later, so a number may meanwhile belong to
    an unrelated process. A pidfd, where available, pins the process between
    the check and the signal; otherwise a short check-to-kill window remains.
    Returns whether the signal was sent.
    """
    descriptor = None
    if hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"):
        try:
            descriptor = os.pidfd_open(pid)
        except ProcessLookupError:
            return False
        except OSError:
            descriptor = None  # e.g. a kernel without pidfd support
    try:
        if start_time(pid) != started:
            return False
        if descriptor is not None:
            signal.pidfd_send_signal(descriptor, sig)
        else:
            os.kill(pid, sig)
        return True
    except ProcessLookupError:
        return False
    finally:
        if descriptor is not None:
            os.close(descriptor)


def descendants(root, table=None):
    table = process_table() if table is None else table
    children = {}
    for pid, (parent, _state, _start) in table.items():
        children.setdefault(parent, []).append(pid)
    found, pending = [], [root]
    while pending:
        for child in children.get(pending.pop(), []):
            found.append(child)
            pending.append(child)
    return found


def owned_processes(token):
    """Processes still carrying a session's environment token (any parent)."""
    marker = f"AGENT_DESKTOP_SESSION_TOKEN={token}".encode()
    found = []
    for path in Path("/proc").iterdir():
        if not path.name.isdecimal() or int(path.name) == os.getpid():
            continue
        try:
            if marker in (path / "environ").read_bytes().split(b"\0"):
                found.append(int(path.name))
        except OSError:
            pass
    return found


def scope_name(session):
    return f"agent-desktop-{session}.scope"


def own_scope(session):
    """This process's cgroup if it is the session's systemd scope, else None."""
    try:
        lines = Path("/proc/self/cgroup").read_text().splitlines()
    except OSError:
        return None
    for line in lines:
        if line.startswith("0::"):
            path = line[3:]
            if path.rsplit("/", 1)[-1] == scope_name(session):
                return path
    return None


def scope_members(cgroup):
    """Processes in a session's cgroup (cgroup v2), including any that cleared
    their environment or left its process group; none without a cgroup."""
    if cgroup is None:
        return []
    for mount in ("/sys/fs/cgroup", "/sys/fs/cgroup/unified"):
        try:
            text = Path(mount + cgroup, "cgroup.procs").read_text()
        except OSError:
            continue
        return [int(pid) for pid in text.split()]
    return []  # the scope is gone: systemd removes it once it is empty


# STATE/<session>/processes.json: the guardian's record of its subtree.
LINEAGE_FILE = "processes.json"
LINEAGE_INTERVAL = 0.5


class SubtreeWatch:
    """The live descendants of `root`, a subreaper, kept up to date cheaply.

    Under a subreaper a descendant never leaves the subtree while it lives (an
    orphan is reparented to an ancestor inside it), and a process outside never
    joins it. So each scan reads /proc/<pid>/stat only for process numbers it
    has not classified yet, plus the members' own to confirm their start times.
    """

    def __init__(self, root):
        self.root = root
        self.members = {}  # pid: start time
        self.outside = set()

    def scan(self):
        pids = {int(name) for name in os.listdir("/proc") if name.isdecimal()}
        self.outside &= pids
        for pid, started in list(self.members.items()):
            if start_time(pid) != started:
                del self.members[pid]
        new = []
        for pid in pids - self.outside - self.members.keys() - {self.root}:
            try:
                stat = Path(f"/proc/{pid}/stat").read_text()
            except OSError:
                continue
            fields = stat[stat.rindex(")") + 2 :].split()
            new.append((int(fields[19]), pid, int(fields[1])))
        # A parent starts before its child, so it is classified first.
        for started, pid, parent in sorted(new):
            if parent == self.root or parent in self.members:
                self.members[pid] = started
            else:
                self.outside.add(pid)
        return dict(self.members)


def record_lineage(root, guardian, stop):
    """Guardian thread: keep the session record's list of live descendants.

    Both supervisors are subreapers, so while either lives every descendant
    stays in this subtree, including one that cleared its environment, left
    its session or daemonized. Recovery after both die starts from this list.
    It is rewritten only when the subtree changes.
    """
    path, temporary = root / LINEAGE_FILE, root / (LINEAGE_FILE + ".tmp")
    boot, last, watch = boot_id(), None, SubtreeWatch(guardian)
    while True:
        members = watch.scan()
        if members != last:
            entries = sorted([pid, started] for pid, started in members.items())
            try:
                write_private(
                    temporary, json.dumps({"boot_id": boot, "processes": entries})
                )
                temporary.replace(path)
                last = members
            except OSError as error:  # a full disk: try again next time
                print(f"Process record not written: {error}", file=sys.stderr)
        if stop.wait(LINEAGE_INTERVAL):
            return


def read_lineage(root):
    """{(pid, start time)} the guardian last recorded in this boot, else empty."""
    try:
        data = json.loads((root / LINEAGE_FILE).read_text())
        boot, entries = data["boot_id"], data["processes"]
    except (OSError, ValueError, TypeError, KeyError):
        return set()
    if boot is None or boot != boot_id() or not isinstance(entries, list):
        return set()
    return {
        tuple(entry)
        for entry in entries
        if isinstance(entry, list)
        and len(entry) == 2
        and all(type(value) is int and value > 0 for value in entry)
    }


def lineage_members(known, table):
    """Live processes descended from the known session processes, or sharing a
    process group or session with one of them.

    `known` holds (pid, start time) pairs, so a number since reused is not taken
    for a session process. A process group or session number cannot be reused
    while any member is alive, and a process can only join a group in its own
    session, so a live known member vouches for every other member: children it
    forked after the record whose parent has since exited, for example. The
    caller's own group and session, and those of init and the kernel, never do.
    """
    groups = process_groups(table)
    me = groups.get(os.getpid(), (None, None))
    never = {0, 1, *me}
    children, by_group, by_session = {}, {}, {}
    for pid, (parent, _state, _start) in table.items():
        children.setdefault(parent, []).append(pid)
    for pid, (group, session) in groups.items():
        by_group.setdefault(group, []).append(pid)
        by_session.setdefault(session, []).append(pid)
    pending = [
        pid for pid, started in known if table.get(pid, (0, "", None))[2] == started
    ]
    found, seen = set(), set()
    while pending:
        pid = pending.pop()
        if pid in found or pid not in table:
            continue
        found.add(pid)
        pending += children.get(pid, [])
        group, session = groups.get(pid, (0, 0))
        for key, members in (
            ("g", by_group.get(group)),
            ("s", by_session.get(session)),
        ):
            number = group if key == "g" else session
            if number not in never and (key, number) not in seen:
                seen.add((key, number))
                pending += members or []
    return found


def session_process_starts(token, tree=True, cgroup=None, lineage=None):
    """{pid: start time} of live session processes: token carriers, members of
    the session's systemd scope, plus this supervisor's subtree.

    With `lineage`, a set of (pid, start time) pairs from read_lineage, also the
    processes lineage_members finds from it. The set grows with each scan, so a
    process found once still vouches for its group after its parent is stopped.
    """
    table = process_table()
    pids = set(owned_processes(token)) | set(scope_members(cgroup))
    if tree:
        pids |= set(descendants(os.getpid(), table))
    if lineage is not None:
        found = lineage_members(lineage, table) - {os.getpid(), os.getppid()}
        lineage.update((pid, table[pid][2]) for pid in found)
        pids |= found
    # Never this supervisor or its parent (the worker's guardian).
    pids -= {os.getpid(), os.getppid()}
    return {p: table[p][2] for p in pids if p in table and table[p][1] not in "ZX"}


def session_processes(token, tree=True, cgroup=None, lineage=None):
    return sorted(session_process_starts(token, tree, cgroup, lineage))


def child_pids(pid):
    """Direct children of a process, or None when the kernel does not list them.

    Much cheaper than scanning every process, which the worker's twice-a-second
    loop otherwise did (about 11 ms per scan with 370 processes).
    """
    children = set()
    try:
        for task in Path(f"/proc/{pid}/task").iterdir():
            children.update(int(c) for c in (task / "children").read_text().split())
    except OSError:
        return None
    return children


def process_state(pid):
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    return stat[stat.rindex(")") + 2 :].split()[0]


def reap_orphans(tracked=()):
    """Collect adopted orphans without stealing exit codes from Popen objects."""
    me = os.getpid()
    children = child_pids(me)
    if children is None:
        zombies = {
            pid
            for pid, (parent, state, _start) in process_table().items()
            if parent == me and state == "Z"
        }
    else:
        zombies = {pid for pid in children if process_state(pid) == "Z"}
    for pid in zombies - set(tracked):
        try:
            os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            pass


def cleanup_processes(
    token, tracked=(), spare=(), tree=True, cgroup=None, lineage=None
):
    """Stop the session tree; processes in spare get SIGTERM only after the rest.

    Each process is identified by its number and start time, so a number reused
    by an unrelated process after the scan is never signalled.
    """
    phases = [(signal.SIGTERM, 2, set(spare))] if spare else []
    phases += [(signal.SIGTERM, 2, set()), (signal.SIGKILL, 3, set())]
    for sig, wait, excluded in phases:
        signalled = set()
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            # Rescan: a process may fork while the tree is being stopped.
            remaining = {
                (pid, started)
                for pid, started in session_process_starts(
                    token, tree, cgroup, lineage
                ).items()
                if pid not in excluded
            }
            if not remaining:
                break
            for pid, started in remaining - signalled:
                signalled.add((pid, started))
                signal_process(pid, started, sig)
            reap_orphans(tracked)
            time.sleep(0.05)
        if not session_processes(token, tree, cgroup, lineage):
            return
    raise RuntimeError("Session processes remain after cleanup")


INPUT_OPERATIONS = (
    *("click", "move", "drag", "scroll", "type", "key"),
    *("key_down", "key_up"),
)
# Operations that change the desktop; they need the controller lease (below).
MUTATING_OPERATIONS = (
    *INPUT_OPERATIONS,
    "launch",
    "focus",
    "ui_action",
    "request_human",
    "set",
    "browser",
    "attach_profile",
)
CHORD_MODIFIERS = {
    "control": "ctrl",
    "ctl": "ctrl",
    "super": "logo",
    "meta": "logo",
    "win": "logo",
    "cmd": "logo",
}
# Names key_down and key_up accept for a modifier, as physical keys.
HELD_MODIFIERS = {
    "logo": "Super_L",
    "ctrl": "Control_L",
    "alt": "Alt_L",
    "shift": "Shift_L",
}
# Keys left held by a client that vanished are released after this long.
KEY_HOLD_SECONDS = 30
BIND_LAYOUT_SECONDS = 10
KEYBOARD = re.compile(r"[a-z0-9_]{1,32}(-[a-z0-9_]{1,32})?")
CONTROLLER_ID = re.compile(r"[A-Za-z0-9._:@-]{1,64}")
# Requests recorded in the session's action trace (trace.jsonl).
EFFECT_OPERATIONS = (
    *INPUT_OPERATIONS,
    *("launch", "focus", "ui_action", "set", "browser"),
)
TRACED_OPERATIONS = (*MUTATING_OPERATIONS, "screenshot", "lease", "take", "release")
TRACE_FIELDS = (
    *("x", "y", "to_x", "to_y", "dx", "dy", "button", "repeat", "modifiers"),
    *("window", "node", "action", "observation", "region", "scale", "force"),
)
TRACE_BYTES = 1024 * 1024
# Written by `take` before it queues behind the request in progress; waits in the
# worker stop when they see it, so a person gets control within about 0.1 s.
TAKE_REQUESTED = "take-requested"
TAKE_MARKER_SECONDS = 10
# Long typing checks for a take between chunks of this many characters (about
# 0.1 s each at the default key interval).
TYPE_CHUNK = 10
TAKEN_OVER = (
    "A person is taking control; nothing more was sent. "
    "Wait with desktop_control until control returns, then take a new screenshot."
)
# On the person's screen, a screenshot this soon after the agent's input waits
# (up to a second) for animations such as a workspace switch to finish.
HOST_SETTLE_AFTER = 1.0


# Values moved by browser "send" (secrets such as generated API keys).
COOKIE_BYTES = 1024 * 1024


def netscape_cookies(bridge, site):
    """The browser's live cookies for one site, as a Netscape cookies.txt.

    Read with BiDi storage.getCookies, so session-only cookies that Firefox
    keeps in memory are included. site matches the domain and its subdomains
    (and the parent domains' cookies the site would also receive). Returns
    (bytes, count); the values never reach the reply.
    """
    if not isinstance(site, str) or not re.fullmatch(
        r"[a-z0-9.-]+\.[a-z]{2,}|localhost|\d{1,3}(\.\d{1,3}){3}", site.lower()
    ):
        raise ValueError("The cookies source needs site, a domain such as example.com")
    site = site.lower().strip(".")
    cookies = bridge.command("storage.getCookies", {})["cookies"]
    lines = ["# Netscape HTTP Cookie File"]
    count = 0
    for cookie in cookies:
        domain = (cookie.get("domain") or "").lower()
        bare = domain.lstrip(".")
        if not (bare == site or bare.endswith("." + site) or site.endswith("." + bare)):
            continue
        value = cookie.get("value") or {}
        if value.get("type") != "string":
            continue  # base64 values are binary; tools expect text
        expiry = cookie.get("expiry") or 0
        flag = "TRUE" if domain.startswith(".") else "FALSE"
        prefix = "#HttpOnly_" if cookie.get("httpOnly") else ""
        fields = (
            prefix + domain,
            flag,
            cookie.get("path") or "/",
            "TRUE" if cookie.get("secure") else "FALSE",
            str(int(expiry)),
            cookie.get("name") or "",
            value.get("value") or "",
        )
        if any("\t" in f or "\n" in f for f in fields):
            continue
        lines.append("\t".join(fields))
        count += 1
    if not count:
        raise ValueError(f"The browser has no cookies for {site}; sign in first")
    data = ("\n".join(lines) + "\n").encode()
    if len(data) > COOKIE_BYTES:
        raise ValueError(f"The cookies for {site} exceed {COOKIE_BYTES} bytes")
    return data, count


def pdf_name(name, url):
    """A file name for a PDF taken from the viewer: the server's, else the URL's."""
    from urllib.parse import unquote, urlsplit

    path = urlsplit(url or "").path if re.match(r"https?://", url or "", re.I) else ""
    for candidate in (name, unquote(path.rsplit("/", 1)[-1])):
        if isinstance(candidate, str):
            candidate = re.sub(r"[/\\\x00-\x1f]", "_", candidate).strip().lstrip(".")
            if candidate:
                break
    else:
        candidate = "document"
    suffix = ".pdf"
    if candidate.lower().endswith(".pdf"):
        candidate, suffix = candidate[:-4], candidate[-4:]
    # At most PDF_NAME_BYTES in UTF-8 with the suffix, so the hidden .part file
    # beside it and a "(N)" for a second copy stay under the 255-byte limit.
    stem = candidate.encode()[: PDF_NAME_BYTES - 4].decode(errors="ignore")
    return (stem.rstrip() or "document") + suffix


def private_path(home, to_file):
    """A file path for send or download: relative paths are in the session home.

    Missing folders inside the home are created 0700 (each level, since
    mkdir(parents=True) would give the upper ones the umask); a missing folder
    elsewhere is refused.
    """
    if not isinstance(to_file, str) or not to_file:
        raise ValueError("to_file must be a path")
    path = Path(to_file)
    if to_file == "~" or to_file.startswith("~/"):
        path = home / to_file[2:]
    elif not path.is_absolute():
        path = home / path
    if not path.parent.is_dir():
        parent, root = path.parent.resolve(), home.resolve()
        if parent != root and root not in parent.parents:
            raise ValueError(f"No such directory: {path.parent}")
        missing = []
        folder = path.parent
        while not folder.is_dir():
            missing.append(folder)
            folder = folder.parent
        for folder in reversed(missing):
            folder.mkdir(mode=0o700, exist_ok=True)
            os.chmod(folder, 0o700)
    return path


SECRET_BYTES = 64 * 1024
SECRET_COMMAND_SECONDS = 60
SAVE_BYTES = 8 * 1024 * 1024  # under the 16 MiB BiDi message limit
DOWNLOAD_SECONDS = 120  # default wait for a download to finish
DOWNLOAD_MAX_SECONDS = 600
DOWNLOAD_PAGE_SECONDS = 5  # no download by then and a page loaded: not a download
# How long open (or start with a url) waits, at most, for the page to settle.
OPEN_SETTLE_SECONDS = 10

PDF_BYTES = 256 * 1024 * 1024  # largest PDF copied out of Firefox's viewer
PDF_NAME_BYTES = 200  # a viewer PDF's file name, with .pdf
PDF_CHUNK = 6 * 1024 * 1024  # 8 MiB as base64, under the 16 MiB BiDi message limit
# Firefox's own PDF viewer (pdf.js) shows an application/pdf document; a site's
# copy of pdf.js runs in an HTML page and is not taken for it.
PDF_VIEWER = (
    "document.contentType === 'application/pdf' && "
    "typeof PDFViewerApplication === 'object'"
)
BROWSER_ACTIONS = (
    "start tabs open close find text wait click fill select send save download steps"
).split()
# Browser actions agents try for keyboard input, which desktop_browser lacks.
KEY_ACTIONS = {"key", "keys", "press", "keypress", "hotkey", "shortcut", "type"}


def unknown_browser_action(action):
    message = (
        "action must be start, tabs, open, close, find, text, wait, click, "
        "fill, select, send, save, download or steps"
    )
    if action in KEY_ACTIONS:
        message += (
            ". Keys go through desktop_key (e.g. Escape, ctrl+a) and text "
            "through fill, or desktop_type for the focused field; in "
            "desktop_actions they are key and type steps"
        )
    return message


# The checked state of a clicked toggle: a checkbox, radio or switch, or the one
# a clicked label controls. "true", "false" or "mixed"; null for anything else.
TOGGLE_STATE = (
    "(e) => { let t = e; if (!(e instanceof HTMLInputElement)) { "
    "const label = e.closest('label'); if (label && label.control) "
    "t = label.control; } if (t instanceof HTMLInputElement && "
    "(t.type === 'checkbox' || t.type === 'radio')) "
    "return t.indeterminate ? 'mixed' : String(t.checked); "
    "const toggle = t.closest('[role=switch], [role=checkbox], [role=radio], "
    "[role=menuitemcheckbox], [role=menuitemradio], [aria-checked], "
    "[aria-pressed]'); return toggle ? toggle.getAttribute('aria-checked') ?? "
    "toggle.getAttribute('aria-pressed') : null; }"
)
# Cropped screenshots may be enlarged up to this factor.
MAX_CROP_SCALE = 2


def lua_string(text):
    """A double-quoted Lua string literal for `text`."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def trace_arguments(request):
    """What the trace keeps of a request: never typed text or command arguments.

    Text and set_text values become their length; single-character key names
    (which could spell a secret) become "<character>"; launch keeps only the
    program name and argument count.
    """
    kept = {key: request[key] for key in TRACE_FIELDS if key in request}
    if isinstance(request.get("text"), str):
        kept["text_chars"] = len(request["text"])
    key = request.get("key")
    if isinstance(key, str):
        chord = "+" in key[1:]
        # A shortcut (with ctrl, alt or logo) spells nothing; plain keys might.
        shortcut = chord or bool(
            {"ctrl", "alt", "logo"} & set(kept.get("modifiers") or [])
        )
        kept["key"] = key if len(key) > 1 or shortcut else "<character>"
    argv = request.get("argv")
    if isinstance(argv, list) and argv:
        kept["program"] = Path(str(argv[0])).name
        kept["argc"] = len(argv)
    if request.get("operation") == "browser":
        kept.update(browser_trace(request))
        steps = request.get("steps")
        if isinstance(steps, list):
            kept["steps"] = [
                {"action": step.get("action"), **browser_trace(step)}
                for step in steps[:30]
                if isinstance(step, dict) and isinstance(step.get("action"), str)
            ]
    return kept


def settle_limit(request):
    """Seconds that open (or start with a url) waits for the page to settle."""
    limit = request.get("timeout", OPEN_SETTLE_SECONDS)
    if (
        not isinstance(limit, (int, float))
        or isinstance(limit, bool)
        or not 0 <= limit <= 60
    ):
        raise ValueError("timeout must be between 0 and 60 seconds")
    return limit


def fixed_wait_hint(steps, index):
    """One line for a plain pause right after open or click in a batch."""
    step = steps[index]
    if (
        step.get("action") != "wait"
        or not step.get("seconds")
        or step.get("selector")
        or step.get("text")
        or index == 0
        or steps[index - 1].get("action") not in ("open", "start", "click")
    ):
        return None
    if steps[index - 1]["action"] == "click":
        return (
            '{"action": "wait"} without seconds returns as soon as the page '
            "stops loading and changing; add text or selector to wait for "
            "something specific"
        )
    return (
        "open already waited until the page stopped loading and changing "
        '(see settled); to wait longer, add {"action": "wait", "text": ...}'
    )


def browser_trace(step):
    """For a browser wait: its pause and whether it waits for a condition."""
    if step.get("action") != "wait":
        return {}
    seconds = step.get("seconds")
    # A wait with no pause and no target waits for the page to settle.
    kept = {
        "condition": bool(
            step.get("selector") or step.get("text") or not step.get("seconds")
        )
    }
    if isinstance(seconds, (int, float)) and not isinstance(seconds, bool):
        kept["seconds"] = seconds
    return kept


def stop_reason(stopped):
    """A batch stop as a category, without page text."""
    if stopped.get("uncertain"):
        return "uncertain"
    reason = str(stopped.get("reason", ""))
    for marker, category in (
        ("elements match", "ambiguous"),
        ("No visible element", "missing"),
        ("No element", "missing"),
        ("disabled", "disabled"),
        ("wait not satisfied", "wait_unmet"),
        ("deadline", "deadline"),
        ("target_lost", "target_lost"),
    ):
        if marker in reason:
            return category
    return "other"


class StaleObservation(RuntimeError):
    pass


class HumanControl(RuntimeError):
    pass


class TakenOver(RuntimeError):
    """A person took control after the current step had begun to act."""


class LeaseHeld(RuntimeError):
    pass


class UserActive(RuntimeError):
    pass


class ScreenUnavailable(RuntimeError):
    """The person's screen is locked or off (host sessions)."""


# Operations a host session refuses: the person is already at this screen, and
# its accessibility bus and viewers belong to them.
HOST_UNSUPPORTED = (
    "take",
    "release",
    "viewer_start",
    "request_human",
    "ui",
    "ui_action",
    "set",
    "attach_profile",
)
# Processes that mean the person's screen is locked (host sessions).
SCREEN_LOCKERS = {"hyprlock", "swaylock", "gtklock", "waylock", "i3lock"}
# Pause agent input this long after the person last used the computer.
HOST_PAUSE_SECONDS = 3.0


class HostCompositor:
    """The person's own compositor: never started or stopped by a session."""

    def __init__(self, display):
        self.display = Path(display)
        self.pid = peer_pid(display)

    def poll(self):
        return None if self.display.is_socket() else 1


def notify(summary, body, env):
    """Tell the person on their own screen (best effort)."""
    if env.get("AGENT_DESKTOP_HOST_NOTIFY") == "0":
        return
    for argv in (
        ["notify-send", "--app-name=Agent Desktop", summary, body],
        ["hyprctl", "notify", "1", "8000", "0", f"{summary}: {body}"],
    ):
        if shutil.which(argv[0], path=env.get("PATH")):
            try:
                subprocess.run(argv, env=env, capture_output=True, timeout=5)
                return
            except (OSError, subprocess.SubprocessError):
                continue


def keep_awake(session, env):
    """Hold a logind idle inhibitor for a host session (best effort).

    Idle locking, blanking and idle suspend wait while it is held; a manual lock
    still happens, and host input is then refused (host_unavailable). It ends
    with this worker even if the worker is killed. AGENT_DESKTOP_HOST_KEEP_AWAKE=0 disables it.
    """
    if env.get("AGENT_DESKTOP_HOST_KEEP_AWAKE") == "0":
        return None
    if not shutil.which("systemd-inhibit", path=env.get("PATH")):
        return None
    watch = f"while kill -0 {os.getpid()} 2>/dev/null; do sleep 5; done"
    try:
        return subprocess.Popen(
            [
                "systemd-inhibit",
                "--what=idle",
                "--mode=block",
                "--who=Agent Desktop",
                f"--why=Host session {session}",
                "sh",
                "-c",
                watch,
            ],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return None


def lease_seconds_default():
    """Inactivity limit for controller leases (AGENT_DESKTOP_LEASE_SECONDS, 60 s)."""
    try:
        seconds = float(os.environ.get("AGENT_DESKTOP_LEASE_SECONDS", 60))
    except ValueError:
        return 60.0
    return min(max(seconds, 1.0), 3600.0)


class Worker:
    held_since = None  # when keys were last held down
    bind_layout_cache = None
    nested_layout_cache = None

    def __init__(self, root):
        self.root = root
        self.info = json.loads((root / "session.json").read_text())
        self.env = os.environ.copy()
        self.bus = None
        self.compositor = None
        self.apps = {}
        self.viewer = None
        # A person may take control through an interactive VNC server; agent
        # operations are refused until control returns and a new screenshot is taken.
        self.takeover = None
        self.control = {"owner": "agent", "epoch": 0, "request": None, "last": None}
        self.needs_screenshot = False
        # One exclusive controller per session: {"holder", "seconds", "expires"}.
        self.lease = None
        self.lease_seconds = lease_seconds_default()
        self.registry = None
        self.bus_launcher = None
        self.atspi = None
        self.ui_ids, self.ui_names = {}, {}  # short id <-> AT-SPI bus name + path
        self.ui_counter = 0
        self.frames = {}  # recent raw frames for change detection, oldest first
        # The last whole frame shown to the agent: changed_only screenshots
        # send only what differs from it (experimental, E3).
        self.seen = None
        # ("type" or "key", monotonic end) of the last keyboard input.
        self.last_keys = (None, 0.0)
        self.virtual_pointer = None
        self.virtual_keyboard = None
        self.toplevels = None
        self.effects = None
        self.keysyms = None
        self.browser = None  # (BiDi connection, Firefox pid) once started
        self.screenshot_at = 0.0  # monotonic start of the latest screenshot
        self.agent_tabs = set()  # host: Firefox tabs the agent opened
        self.stop = False
        self.profile_lock = None
        self.activity = None  # host sessions: the person's input
        self.awake = None  # host sessions: the idle inhibitor
        self.agent_input = []  # host sessions: (start, end) of our input

    def save(self, status, **values):
        self.info.update(status=status, **values)
        write_manifest(self.root, self.info)

    def command(self, tool, *arguments, timeout=10):
        if self.compositor and self.compositor.poll() is not None:
            raise RuntimeError("Private compositor has exited")
        try:
            result = subprocess.run(
                [self.info["tools"][tool], *map(str, arguments)],
                env=self.env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"{tool} did not finish within {timeout} s") from None
        except FileNotFoundError:
            raise RuntimeError(
                runtime_changed(tool, self.info["tools"][tool])
            ) from None
        if result.returncode:
            raise RuntimeError(
                f"{tool} failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        return result.stdout.strip()

    def start_host(self):
        """Attach to the person's own desktop instead of starting a compositor."""
        self.env.pop("AGENT_DESKTOP_CONTROLLER", None)
        display = self.info["host_wayland"]
        self.compositor = HostCompositor(display)
        self.info["compositor_pid"] = self.compositor.pid
        self.info["wayland_display"] = display
        self.virtual_pointer = VirtualPointer(display)
        self.virtual_keyboard = VirtualKeyboard(display, self.root)
        self.keysyms = Keysyms(self.compositor.pid)
        self.toplevels = Toplevels(display)
        # Agents pause between steps longer than this, so the person's input after
        # one of those pauses is noticed even while the agent is working.
        self.activity = InputActivity(display, idle_ms=300)
        self.awake = keep_awake(self.info["id"], self.env)
        until = time.strftime("%H:%M", time.localtime(self.info["expires_at"]))
        notify(
            "An agent is using your screen",
            f"Until {until}. Using the mouse or keyboard pauses it; "
            f"stop it with: {printed.command('host', 'stop')}",
            self.env,
        )

    def person_input(self):
        """Times the person (not the agent) resumed using the computer."""
        ours = self.agent_input
        return [
            moment
            for moment in self.activity.resumed_at
            if not any(start - 0.05 <= moment <= end + 0.5 for start, end in ours)
        ]

    def host_unavailable(self):
        """Why the person's screen cannot take input now, or None: another
        terminal is showing, a screen locker is running, or Hyprland reports
        every display switched off."""
        off_screen = self.host_off_screen()
        if off_screen:
            return off_screen
        for entry in Path("/proc").iterdir():
            if entry.name.isdigit():
                try:
                    name = (entry / "comm").read_text().strip()
                except OSError:
                    continue
                if name in SCREEN_LOCKERS:
                    return f"the screen is locked ({name})"
        if self.env.get("HYPRLAND_INSTANCE_SIGNATURE") and shutil.which(
            "hyprctl", path=self.env.get("PATH")
        ):
            try:
                result = subprocess.run(
                    ["hyprctl", "-j", "monitors"],
                    env=self.env,
                    capture_output=True,
                    timeout=2,
                )
                monitors = json.loads(result.stdout or b"[]")
            except (OSError, ValueError, subprocess.TimeoutExpired):
                return None
            if monitors and not any(m.get("dpmsStatus", True) for m in monitors):
                return "the display is switched off"
        return None

    def host_off_screen(self):
        """Which terminal is showing when it is not this session's Hyprland.

        A compositor on an inactive terminal draws nothing, so capture hangs
        and input reaches nobody. None when it cannot be determined.
        """
        signature = self.env.get("HYPRLAND_INSTANCE_SIGNATURE")
        runtime = self.env.get("XDG_RUNTIME_DIR")
        if not signature or not runtime:
            return None
        try:
            lock = Path(runtime, "hypr", signature, "hyprland.lock")
            pid = int(lock.read_text().split()[0])
            environment = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
            active = Path("/sys/class/tty/tty0/active").read_text().strip()
        except (OSError, ValueError, IndexError):
            return None
        terminal = next(
            (v[9:].decode() for v in environment if v.startswith(b"XDG_VTNR=")), None
        )
        if terminal and active != f"tty{terminal}":
            return f"this desktop is on tty{terminal}, but {active} is on screen"
        return None

    def user_active(self):
        """Whether the person used the computer recently (host sessions)."""
        now = time.monotonic()
        theirs = self.person_input()
        if not theirs:
            return False
        latest = theirs[-1]
        # Still active since their last input (no idle period yet) or recently.
        still = not self.activity.idle and latest == self.activity.resumed_at[-1]
        return still or now - latest < HOST_PAUSE_SECONDS

    def launch_on_host(self, argv, cwd):
        """Start an application the way the person's desktop would, outside the
        session, so it stays open when the session ends."""
        command = f"cd {shlex.quote(cwd)} && exec {shlex.join(argv)}"
        if self.env.get("HYPRLAND_INSTANCE_SIGNATURE") and shutil.which(
            "hyprctl", path=self.env.get("PATH")
        ):
            launcher = ["hyprctl", "dispatch", "exec", command]
        elif shutil.which("systemd-run", path=self.env.get("PATH")):
            launcher = [
                "systemd-run",
                "--user",
                "--collect",
                "--quiet",
                f"--working-directory={cwd}",
                "--",
                *argv,
            ]
        else:
            raise ValueError(
                "No way to start an application outside the session: needs "
                "Hyprland (hyprctl) or a systemd user manager"
            )
        self.mark_mutation()
        result = subprocess.run(
            launcher, env=self.env, capture_output=True, text=True, timeout=10
        )
        if launcher[0] == "hyprctl" and "lua" in result.stdout.lower():
            # Hyprland with a Lua configuration (0.57) parses dispatches as Lua
            # and refused the classic form before running anything.
            launcher = [
                "hyprctl",
                "dispatch",
                f"hl.dsp.exec_cmd({lua_string(command)})",
            ]
            result = subprocess.run(
                launcher, env=self.env, capture_output=True, text=True, timeout=10
            )
        refused = launcher[0] == "hyprctl" and result.stdout.strip() != "ok"
        if result.returncode or refused:
            raise RuntimeError(
                f"{launcher[0]} failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        return {"launched_via": launcher[0], "argv": argv}

    def start(self):
        if self.info["mode"] == "host":
            return self.start_host()
        for key in (
            "DISPLAY",
            "WAYLAND_DISPLAY",
            "WAYLAND_SOCKET",
            "HYPRLAND_INSTANCE_SIGNATURE",
            "AT_SPI_BUS_ADDRESS",
            "SWAYSOCK",
            "I3SOCK",
            "SESSION_MANAGER",
            "XAUTHORITY",
            "DESKTOP_STARTUP_ID",
            "XDG_ACTIVATION_TOKEN",
            "DBUS_SESSION_BUS_ADDRESS",
            "DBUS_SESSION_BUS_PID",
            # Session applications must not act as the creator's controller.
            "AGENT_DESKTOP_CONTROLLER",
        ):
            self.env.pop(key, None)
        # A variable naming a place in the person's home, such as a browser's
        # profile root (MOZ_APP_DATA), would bypass the private home.
        removed = home_variables(self.env, host_homes(self.env))
        for key in removed:
            del self.env[key]
        self.info["home_removed_variables"] = removed
        if self.info.get("home"):
            home = Path(self.info["home"])
            # Taken by the guardian and shared with this process, so it is held
            # until the guardian has stopped everything the session left behind.
            if GUARDIAN_PROFILE_LOCK is None:
                raise RuntimeError("Profile is in use by another session")
            self.profile_lock = GUARDIAN_PROFILE_LOCK
            if not home.is_dir():
                raise RuntimeError("Profile was deleted while the session started")
        else:
            home = self.root / "home"
            home.mkdir(mode=0o700)
        if not any(
            (home / name).exists()
            for name in (".zshenv", ".zprofile", ".zshrc", ".zlogin")
        ):
            # Without startup files, an interactive zsh (the default shell of
            # many terminals) shows its first-run menu, which takes the first
            # key typed into it: "echo" arrived as "cho". This is that menu's
            # own "create an empty ~/.zshrc" answer.
            (home / ".zshrc").write_text("# Created by agent-desktop\n")
        config = self.root / "config"
        config.mkdir(mode=0o700)
        # Explicit window bindings only: labwc's defaults include Execute actions
        # (terminal, pactl, brightnessctl) that could act on the host.
        (config / "rc.xml").write_text(
            "<labwc_config><keyboard>"
            '<keybind key="A-Tab"><action name="NextWindow"/></keybind>'
            '<keybind key="A-S-Tab"><action name="PreviousWindow"/></keybind>'
            '<keybind key="A-F4"><action name="Close"/></keybind>'
            "</keyboard>"
            # A size is asked for to fit wide pages: Firefox otherwise opens at
            # its own default width (1280), not the desktop's.
            + (
                '<windowRules><windowRule identifier="firefox">'
                '<action name="Maximize"/></windowRule></windowRules>'
                if self.info.get("size")
                else ""
            )
            + "</labwc_config>\n"
        )
        for name in ("environment", "shutdown"):
            (config / name).write_text("")
        # labwc sets DISPLAY for its lazily started Xwayland only in its own
        # process; autostart inherits it, so record it for applications.
        display_file = Path(self.info["runtime"]) / "x-display"
        (config / "autostart").write_text(
            f'printf "%s" "${{DISPLAY:-}}" > "{display_file}.tmp" && '
            f'mv "{display_file}.tmp" "{display_file}"\n'
        )
        self.env.update(
            {
                "HOME": str(home),
                "XDG_RUNTIME_DIR": self.info["runtime"],
                "XDG_CONFIG_HOME": str(home / ".config"),
                "XDG_CACHE_HOME": str(home / ".cache"),
                "XDG_DATA_HOME": str(home / ".local/share"),
                "XDG_STATE_HOME": str(home / ".local/state"),
                "XDG_SESSION_TYPE": "wayland",
                "XDG_CURRENT_DESKTOP": "labwc",
                "WLR_BACKENDS": "headless"
                if self.info["mode"] == "headless"
                else "wayland",
                "WLR_RENDERER": self.info["renderer"]["name"],
                "WLR_HEADLESS_OUTPUTS": "1",
                "WLR_WL_OUTPUTS": "1",
                "WLR_LIBINPUT_NO_DEVICES": "1",
                "XKB_DEFAULT_LAYOUT": "us",
                # Software sessions: GTK 4 would otherwise try Vulkan/GL on the
                # host GPU, which left layer-shell panels blank in a trial.
                "GSK_RENDERER": os.environ.get("AGENT_DESKTOP_GSK_RENDERER", "cairo"),
            }
        )
        # Only the session's own choice, never a render node set for the host.
        self.env.pop("WLR_RENDER_DRM_DEVICE", None)
        if self.info["renderer"]["device"]:
            self.env["WLR_RENDER_DRM_DEVICE"] = self.info["renderer"]["device"]
        self.pin_browser_profiles()
        if self.info["mode"] == "visible":
            self.env["WAYLAND_DISPLAY"] = self.info["parent_wayland"]
        self.compositor = subprocess.Popen(
            [
                self.info["tools"]["labwc"],
                "-C",
                str(config),
            ],
            env=self.env,
        )
        self.info["compositor_pid"] = self.compositor.pid
        runtime = Path(self.info["runtime"])
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.compositor.poll() is not None:
                raise RuntimeError("Compositor exited during startup")
            display = next(
                (p for p in runtime.glob("wayland-*") if p.is_socket()), None
            )
            if display:
                self.env["WAYLAND_DISPLAY"] = str(display)
                self.info["wayland_display"] = str(display)
                # Activated services get the private display, never the host's.
                if self.info.get("guard_host"):
                    self.guard_host()
                registryd = self.prepare_accessibility()
                self.mask_secret_service()
                self.start_bus()
                if registryd:
                    self.start_registry(registryd)
                if self.info.get("size"):
                    # Before the pointer and applications, which read the size.
                    set_output_size(display, *self.info["size"])
                # Create the pointer before applications so its seat capability is stable.
                self.virtual_pointer = VirtualPointer(display)
                self.virtual_keyboard = VirtualKeyboard(display, self.root)
                self.keysyms = Keysyms(self.compositor.pid)
                self.toplevels = Toplevels(display)
                if os.environ.get("AGENT_DESKTOP_EFFECTS") == "1":
                    # Experimental: report observed effects with each action.
                    self.effects = EffectLedger(
                        self.env["HOME"],
                        self.toplevels.current,
                        lambda: session_process_starts(self.info["token"]),
                        extra=[
                            d
                            for d in os.environ.get(
                                "AGENT_DESKTOP_EFFECT_DIRS", ""
                            ).split(":")
                            if os.path.isabs(d)
                        ],
                        ui=(
                            self.ui_snapshot
                            if os.environ.get("AGENT_DESKTOP_UI_DELTA") != "0"
                            else None
                        ),
                    )
                self.start_xwayland_environment(
                    display_file_deadline=time.monotonic() + 5
                )
                return
            time.sleep(0.05)
        raise TimeoutError("Private compositor socket did not appear")

    def start_xwayland_environment(self, display_file_deadline):
        path = Path(self.info["runtime"]) / "x-display"
        while not path.exists():
            if time.monotonic() > display_file_deadline:
                raise TimeoutError("labwc autostart did not report its X display")
            time.sleep(0.02)
        value = path.read_text().strip()
        # Only accept the display labwc created for this session.
        if value and not value.startswith(":"):
            raise RuntimeError(f"Unexpected X display from compositor: {value!r}")
        if value:
            self.env["DISPLAY"] = value
        self.info["x_display"] = value or None

    def attach_profile(self, request):
        """Give a running session a named profile as its home.

        Applications started afterwards (Firefox included) use the profile.
        Refused while any application of this session is running, since its
        files and environment stay in the old home.
        """
        from . import core

        if self.info.get("profile"):
            raise ValueError(f"Session already uses profile {self.info['profile']}")
        running = [p.pid for p in self.apps.values() if p.poll() is None]
        if running:
            raise ValueError(
                f"Applications are still running (pid {running[0]}"
                f"{', ...' if len(running) > 1 else ''}): close them first, since "
                "they keep the session's old home. Nothing was changed"
            )
        name = request.get("profile")
        path = core.profile_path(name)
        home = path / "home"
        if path.is_symlink() or home.is_symlink() or not home.is_dir():
            raise ValueError("Unsafe or missing profile directory")
        lock = core.profile_lock(path).open("a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            raise ValueError(f"Profile {name} is in use by another session") from None
        # The guardian receives and holds its own descriptor for the same open
        # file description (see receive_profile_locks), so the lock survives
        # this process dying, as at create.
        if GUARDIAN_HANDOFF is not None:
            socket.send_fds(GUARDIAN_HANDOFF, [b"l"], [lock.fileno()])
        self.profile_lock = lock
        if not any(
            (home / n).exists() for n in (".zshenv", ".zprofile", ".zshrc", ".zlogin")
        ):
            (home / ".zshrc").write_text("# Created by agent-desktop\n")
        self.env.update(
            {
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(home / ".config"),
                "XDG_CACHE_HOME": str(home / ".cache"),
                "XDG_DATA_HOME": str(home / ".local/share"),
                "XDG_STATE_HOME": str(home / ".local/state"),
            }
        )
        (path / "last-session.json").write_text(
            json.dumps({"session": self.info["id"]}) + "\n"
        )
        self.info.update(
            profile=name, home=str(home), profile_lock=str(core.profile_lock(path))
        )
        write_manifest(self.root, self.info)
        return {"session": self.info["id"], "profile": name, "home": str(home)}

    def pin_browser_profiles(self):
        """Start Firefox with a profile in the session home.

        A wrapper may hard-code the person's own profile root (home-manager
        exports MOZ_APP_DATA with an absolute path), which no environment
        change overrides. A shim first on PATH adds --profile unless the caller
        chose a profile; it also covers applications that open links.
        """
        directory = self.root / "shims"
        pinned = []
        for name in FIREFOX_NAMES:
            real = shutil.which(name, path=self.env.get("PATH"))
            if not real:
                continue
            directory.mkdir(mode=0o700, exist_ok=True)
            shim = directory / name
            shim.write_text(
                "#!/bin/sh\n"
                'for a in "$@"; do case "$a" in\n'
                f'  {FIREFOX_PROFILE_PATTERNS}) exec {shlex.quote(real)} "$@";;\n'
                "esac; done\n"
                'profile="$HOME/.mozilla/agent-desktop"\n'
                'mkdir -p "$profile"\n'
                f'exec {shlex.quote(real)} --profile "$profile" "$@"\n'
            )
            shim.chmod(0o700)
            pinned.append(name)
        if pinned:
            self.env["PATH"] = f"{directory}:{self.env.get('PATH', '')}"
        self.info["pinned_browsers"] = pinned

    def guard_host(self):
        """Refuse common host-affecting commands and the system bus.

        Accident prevention for applications such as panels and widgets, not a
        security boundary: absolute paths and other mechanisms still work.
        """
        directory = self.root / "guard"
        directory.mkdir(mode=0o700, exist_ok=True)
        log = self.root / "guard.log"
        original_path = self.env.get("PATH", "")
        # The host's Hyprland sockets: under the runtime sessions are made in
        # (<host runtime>/agent-desktop/<session>), and under the login
        # runtime, which differs when the server runs without XDG_RUNTIME_DIR.
        hosts = sorted(
            {
                os.path.realpath(Path(self.info["runtime"]).parent.parent / "hypr"),
                os.path.realpath(f"/run/user/{os.getuid()}/hypr"),
            }
        )
        for name in GUARDED_COMMANDS:
            shim = directory / name
            # hyprctl may reach a Hyprland started inside this session. That
            # instance cannot keep its sockets under the session's own runtime
            # directory, whose socket paths exceed the 108-byte limit, so a
            # harness gives it a short private XDG_RUNTIME_DIR. A runtime is
            # accepted when its hypr directory (symlinks resolved) is not the
            # host's and every instance hyprctl could pick in it is a real
            # directory there, not a link out. The instance comes from
            # HYPRLAND_INSTANCE_SIGNATURE or --instance/-i; hyprctl joins it to
            # the path unchecked, so one containing "/" is refused.
            nested = (
                f"hosts={shlex.quote(chr(10).join(hosts))}\n"
                'sig="${HYPRLAND_INSTANCE_SIGNATURE:-}"; next=\n'
                'for a in "$@"; do\n'
                '  [ -n "$next" ] && sig="$a"; next=\n'
                '  case "$a" in -i|--instance) next=1 ;; esac\n'
                "done\n"
                "nested_ok() {\n"
                '  case "$sig" in */*|.|..) return 1 ;; esac\n'
                '  hypr=$(cd -P "${XDG_RUNTIME_DIR:-/nonexistent}/hypr" 2>/dev/null '
                "&& pwd -P) || return 1\n"
                '  printf "%s\\n" "$hosts" | grep -qxF "$hypr" && return 1\n'
                '  case "$sig" in\n'
                '  ""|*[!0-9]*) ;;\n'
                "  *) sig= ;;\n"  # an index into the instances listed below
                "  esac\n"
                '  if [ -n "$sig" ]; then set -- "$hypr/$sig"; '
                'else set -- "$hypr"/*; fi\n'
                '  for d in "$@"; do\n'
                '    [ -e "$d" ] || continue\n'
                '    [ "$(cd -P "$d" 2>/dev/null && pwd -P)" = "$d" ] || return 1\n'
                '    [ ! -L "$d/.socket.sock" ] || return 1\n'
                "  done\n"
                '  [ -z "$sig" ] || [ -S "$hypr/$sig/.socket.sock" ]\n'
                "}\n"
                "if nested_ok; then\n"
                f'  PATH={shlex.quote(original_path)} exec hyprctl "$@"\n'
                "fi\n"
                if name == "hyprctl"
                else ""
            )
            shim.write_text(
                "#!/bin/sh\n"
                + nested
                + f'printf "%s blocked: {name}" "$(date +%s)" >> "{log}"\n'
                f'for a in "$@"; do printf " %s" "$a" >> "{log}"; done\n'
                f'echo >> "{log}"\n'
                f'echo "agent-desktop: {name} is blocked in a guarded session" >&2\n'
                "exit 1\n"
            )
            shim.chmod(0o700)
        self.env["PATH"] = f"{directory}:{self.env.get('PATH', '')}"
        self.env["DBUS_SYSTEM_BUS_ADDRESS"] = "unix:path=/nonexistent/system_bus_socket"
        # Host credentials and agents (SSH, GPG, cloud and API tokens).
        removed = sorted(k for k in self.env if credential_variable(k))
        for key in removed:
            del self.env[key]
        self.info["guard_removed_variables"] = removed

    def prepare_accessibility(self):
        """Enable AT-SPI for this session when at-spi2-core is installed."""
        registryd = find_registryd()
        self.info["accessibility"] = registryd is not None
        if not registryd:
            return None
        # Hosts may disable accessibility globally; enable it for this session only.
        for key in ("NO_AT_BRIDGE", "GTK_A11Y"):
            self.env.pop(key, None)
        self.env["QT_LINUX_ACCESSIBILITY_ALWAYS_ON"] = "1"
        self.env["ACCESSIBILITY_ENABLED"] = "1"  # Chromium/Electron
        self.env["GNOME_ACCESSIBILITY"] = "1"  # Firefox exposes no tree otherwise
        # Let the private bus activate the matching bus launcher (e.g. from Nix).
        share = Path(registryd).resolve().parent.parent / "share"
        if (share / "dbus-1/services/org.a11y.Bus.service").is_file():
            current = self.env.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
            self.env["XDG_DATA_DIRS"] = f"{share}:{current}"
        return registryd

    def mask_secret_service(self):
        """Keep the private bus from starting a keyring that prompts for a password.

        Host service files would start gnome-keyring inside the session, which
        asks for a new keyring password that an agent cannot answer. Services in
        $XDG_RUNTIME_DIR/dbus-1/services take precedence over the host's, and this
        Exec fails at once, so applications fall back (Chromium to its basic
        store). AGENT_DESKTOP_SECRET_SERVICE=1 keeps the host's keyring service.
        """
        if os.environ.get("AGENT_DESKTOP_SECRET_SERVICE") == "1":
            self.info["secret_service"] = True
            return
        self.info["secret_service"] = False
        # dbus-daemon ignores this directory if it is writable by anyone else
        # ("can be written by others"), which Ubuntu's default umask 002
        # produced; the keyring then started anyway.
        services = Path(self.info["runtime"]) / "dbus-1/services"
        services.mkdir(parents=True, exist_ok=True)
        for directory in (services.parent, services):
            directory.chmod(0o700)
        for name in SECRET_SERVICES:
            (services / f"{name}.service").write_text(
                f"[D-BUS Service]\nName={name}\n"
                "Exec=/nonexistent/agent-desktop-has-no-secret-service\n"
            )

    def start_bus_launcher(self, registryd):
        """Start the accessibility bus launcher from this worker, not by D-Bus
        activation.

        On SELinux-enforcing Fedora the private bus may not execute it: the
        policy computes gnome_atspi_t for it, which the user's role does not
        allow. Started from here it keeps the worker's own context. Without a
        launcher beside the registry, or if it does not take its name, the bus
        activates org.a11y.Bus as before.
        """
        launcher = Path(registryd).resolve().parent / "at-spi-bus-launcher"
        if not os.access(launcher, os.X_OK):
            return
        with (self.root / "accessibility.log").open("ab") as log:
            self.bus_launcher = subprocess.Popen(
                [str(launcher), "--launch-immediately"],
                env=self.env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
            )
        address = self.env["DBUS_SESSION_BUS_ADDRESS"]
        deadline = time.monotonic() + 5
        while not name_has_owner(address, "org.a11y.Bus"):
            if self.bus_launcher.poll() is not None or time.monotonic() > deadline:
                stop_process(self.bus_launcher)
                self.bus_launcher = None
                return
            time.sleep(0.05)
        self.info["accessibility_bus"] = "launched"

    def start_registry(self, registryd):
        self.start_bus_launcher(registryd)
        # D-Bus activation of the registry fails without a systemd user session.
        with (self.root / "accessibility.log").open("ab") as log:
            self.registry = subprocess.Popen(
                [registryd],
                env=self.env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
            )
        try:
            wait_for_registry(self.env["DBUS_SESSION_BUS_ADDRESS"])
        except AccessibilityError as error:
            # The desktop works without it; say why the UI tools are unavailable.
            stop_process(self.registry)
            self.registry = None
            self.info["accessibility"] = False
            self.info["accessibility_error"] = accessibility_failure(str(error))

    def short_id(self, node):
        """Short, stable identifiers for UI nodes, to keep listings small."""
        if node not in self.ui_names:
            if len(self.ui_ids) >= 50000:
                # Forget old ids but never reuse them: a stale id must fail,
                # not silently address a different element.
                self.ui_ids.clear()
                self.ui_names.clear()
            self.ui_counter += 1
            short = f"n{self.ui_counter}"
            self.ui_ids[short] = node
            self.ui_names[node] = short
        return self.ui_names[node]

    def start_browser(self, url, controller=None):
        """Firefox with WebDriver BiDi on a free localhost port: the bridged one,
        one started in the session with --remote-debugging-port, or a new one.
        A new one is launched as `controller`, the holder of the lease that the
        browser request has just taken."""
        from . import browser

        if self.browser and self.browser[1]() is None:
            return self.browser[0]
        if self.attach_browser():
            if url:
                self.browser[0].command(
                    "browsingContext.navigate",
                    {"context": self.browser[0].target(), "url": url},
                )
            return self.browser[0]
        launch = {
            "operation": "launch",
            "argv": ["firefox", "--remote-debugging-port=0", url or "about:blank"],
        }
        if controller is not None:
            launch["controller"] = controller
        started = self.handle(launch)
        process = self.apps[started["application"]]
        log = Path(started["logs"])
        deadline = time.monotonic() + 30
        while True:
            found = BIDI_LISTENING.search(log.read_text(errors="replace"))
            if found:
                break
            if process.poll() is not None:
                raise ValueError(
                    "Firefox exited at once: it is probably already running in "
                    "this session without the browser bridge. Close it and retry."
                )
            if time.monotonic() > deadline:
                raise TimeoutError("Firefox did not open its BiDi port in 30 s")
            time.sleep(0.2)
        self.browser = (browser.Browser(found.group(1)), process.poll)
        return self.browser[0]

    def attach_browser(self):
        """Connect to a Firefox launched in this session with
        --remote-debugging-port, if one is running. Returns whether connected."""
        from . import browser

        if self.browser and self.browser[1]() is None:
            return True
        if self.browser:
            self.browser[0].close()
            self.browser = None
        if self.info["mode"] == "host":
            url = person_firefox_bridge(self.env)
            if url:
                bridge = browser.Browser(url)
                self.browser = (bridge, lambda: None if bridge.alive() else 1)
                self.agent_tabs = set()
                return True
            return False
        for app, process in self.apps.items():
            log = self.root / f"app-{app}.log"
            if process.poll() is None and log.exists():
                found = BIDI_LISTENING.search(log.read_text(errors="replace"))
                if found:
                    self.browser = (browser.Browser(found.group(1)), process.poll)
                    return True
        return False

    def browser_request(self, request):
        """Read and act on pages of a private Firefox through WebDriver BiDi."""
        from websockets.exceptions import ConnectionClosed

        from . import browser

        action = request.get("action")
        mutation_started = False
        context = None
        target = {
            "selector": request.get("selector"),
            "text": request.get("text"),
            "exact": request.get("exact") is True,
            "within": request.get("within"),
        }
        try:
            if action not in BROWSER_ACTIONS:
                raise ValueError(unknown_browser_action(action))
            if action == "steps":
                return self.browser_steps(
                    request.get("steps"),
                    request.get("controller"),
                    request.get("deadline"),
                )
            if action == "send":
                return self.send_secret(request, target)
            host = self.info["mode"] == "host"
            if action == "start" and host:
                if not self.attach_browser():
                    raise ValueError(
                        "The person's Firefox has no WebDriver BiDi port. Ask them "
                        "to restart it with --remote-debugging-port=0; the agent "
                        "never restarts their browser."
                    )
                self.browser[0].deadline = request.get("deadline")
                return {"tabs": self.browser[0].tabs()[1]}
            if action == "start":
                limit = settle_limit(request) if request.get("url") else 0
                mutation_started = True
                bridge = self.start_browser(
                    request.get("url"), request.get("controller")
                )
                bridge.deadline = request.get("deadline")
                return self.browser_observed(
                    {"started": True, "delivered": True},
                    lambda: {
                        **(
                            bridge.settle(
                                bridge.target(),
                                limit=limit,
                                interrupt=self.take_requested,
                            )
                            if limit
                            else {}
                        ),
                        "tabs": bridge.tabs()[1],
                    },
                )
            if not self.attach_browser():
                if host and action == "open" and request.get("new_tab"):
                    return self.open_in_person_firefox(request.get("url"))
                raise ValueError('No bridged Firefox; use action "start" first')
            bridge = self.browser[0]
            bridge.deadline = request.get("deadline")
            if action == "tabs":
                if request.get("tab") is not None or request.get("context") is not None:
                    bridge.target(request.get("tab"), request.get("context"))
                return {"tabs": bridge.tabs()[1]}
            creating = (
                action == "open"
                and request.get("new_tab")
                and request.get("tab") is None
                and request.get("context") is None
            )
            context = (
                None
                if creating
                else bridge.target(request.get("tab"), request.get("context"))
            )
            if (
                host
                and action in ("open", "click", "fill", "select", "close")
                and not (action == "open" and request.get("new_tab"))
                and request.get("tab") is None
                and request.get("context") is None
                and context not in self.agent_tabs
            ):
                raise ValueError(
                    "On the person's Firefox, act only in tabs you opened (open "
                    "with new_tab, in the background) or name a tab explicitly "
                    "with tab or context; their current tab is left alone."
                )
            if action == "save":
                return self.browser_save(request, bridge, context, target)
            if action == "download":
                if host:
                    raise ValueError(
                        "download is for private sessions: the person's Downloads "
                        "folder is not the agent's"
                    )
                return self.browser_download(request, bridge, context)
            if action == "open":
                url = request.get("url")
                if not isinstance(url, str) or not url:
                    raise ValueError("open needs a url")
                limit = settle_limit(request)
                if url.lower().startswith("view-source:"):
                    raise ValueError(
                        "Firefox refuses view-source: URLs over the bridge; open "
                        "the URL itself and read it with text (for JSON, click "
                        "Raw Data first)"
                    )
                mutation_started = True
                if request.get("new_tab"):
                    created = {"type": "tab"}
                    if host:
                        # Do not switch the person's view to the agent's tab.
                        created["background"] = True
                    context = bridge.command("browsingContext.create", created)[
                        "context"
                    ]
                    bridge.context = context
                    if host:
                        self.agent_tabs.add(context)
                bridge.command(
                    "browsingContext.navigate",
                    {"context": context, "url": url, "wait": "complete"},
                    timeout=60,
                    interrupt=self.take_requested,
                )
                return self.browser_observed(
                    {"delivered": True, "context": context},
                    lambda: {
                        **(
                            bridge.settle(
                                context, limit=limit, interrupt=self.take_requested
                            )
                            if limit
                            else {}
                        ),
                        **self.page_state(bridge, context),
                        **bridge.challenge(context),
                    },
                )
            if action == "close":
                mutation_started = True
                bridge.command("browsingContext.close", {"context": context})
                self.agent_tabs.discard(context)
                # Keep the closed identity: later actions require an explicit
                # selection rather than silently inheriting another tab.
                return self.browser_observed(
                    {"closed": True, "delivered": True},
                    lambda: {"tabs": bridge.tabs()[1]},
                )
            if action == "find":
                found = bridge.find(context, **target)
                return {**found, **bridge.challenge(context)}
            if action == "text":
                text = bridge.call(
                    "(s) => (s ? document.querySelector(s) : document.body)"
                    "?.innerText ?? null",
                    [request.get("selector")],
                    context,
                )
                text = browser.remote_value(text)
                if text is None:
                    raise ValueError("No element matches that selector")
                return {
                    "text": text[: browser.MAX_TEXT],
                    "truncated": len(text) > browser.MAX_TEXT,
                    **self.page_state(bridge, context),
                    **bridge.challenge(context),
                }
            if action == "wait":
                timeout = request.get("timeout", 10)
                if not isinstance(timeout, (int, float)) or not 0 <= timeout <= 60:
                    raise ValueError("timeout must be between 0 and 60 seconds")
                # A plain pause, as in desktop_actions; then the condition, if any.
                seconds = request.get("seconds", 0)
                if (
                    not isinstance(seconds, (int, float))
                    or isinstance(seconds, bool)
                    or not 0 <= seconds <= 30
                ):
                    raise ValueError("seconds must be between 0 and 30")
                self.pause(seconds)
                if not (target["selector"] or target["text"]):
                    if seconds:
                        return {"satisfied": True, "waited": seconds}
                    # Neither: until the page stops loading and changing.
                    settled = bridge.settle(
                        context, limit=timeout, interrupt=self.take_requested
                    )
                    self.pause(0)  # a take stopped it: say so, as other waits do
                    return {
                        "satisfied": settled["settled"],
                        **settled,
                        **self.page_state(bridge, context),
                        **bridge.challenge(context),
                    }
                gone = request.get("gone") is True
                deadline = time.monotonic() + timeout
                while True:
                    found = bridge.find(context, **target)
                    # A text is also looked for in the document title, which no
                    # element holds ("Just a moment..." on a bot-check page). Not
                    # with within: the title lies in no row or dialog.
                    in_title = bool(
                        target["text"]
                        and not target["selector"]
                        and not target["within"]
                        and bridge.title_matches(
                            context, target["text"], target["exact"]
                        )
                    )
                    if in_title:
                        found = {**found, "title_matches": True}
                    if bool(found["count"] or in_title) != gone:
                        return {"satisfied": True, **found, **bridge.challenge(context)}
                    if time.monotonic() >= deadline:
                        return {
                            "satisfied": False,
                            **found,
                            **bridge.challenge(context),
                        }
                    self.pause(0.2)
            if action in ("click", "fill", "select"):
                element, described = bridge.element(context, **target)
                if described.get("disabled"):
                    raise ValueError(f"The element is disabled: {described}")
                toggle_before = None
                if action in ("click", "fill"):
                    bridge.uncovered(context, element)
                if action == "click":
                    try:
                        toggle_before = browser.remote_value(
                            bridge.call(TOGGLE_STATE, [element], context)
                        )
                    except Exception:
                        # Optional evidence: a failed read must not stop the click.
                        toggle_before = None
                    mutation_started = True
                    bridge.click(context, element)
                elif action == "fill":
                    value = request.get("value")
                    if not isinstance(value, str) or len(value) > 2000:
                        raise ValueError(
                            "fill needs a value of at most 2000 characters"
                        )
                    mutation_started = True
                    bridge.click(context, element)
                    bridge.keys(context, value, select_all=True)
                else:
                    option = request.get("value")
                    mutation_started = True
                    chosen = bridge.call(
                        "(e, o) => { const m = [...e.options].find((x) => "
                        "x.text.trim() === o || x.value === o); if (!m) return null; "
                        "e.value = m.value; e.dispatchEvent(new Event('input', "
                        "{bubbles: true})); e.dispatchEvent(new Event('change', "
                        "{bubbles: true})); return m.text.trim(); }",
                        [element, option],
                        context,
                    )
                    if browser.remote_value(chosen) is None:
                        raise ValueError(f"No option {option!r}: {described}")
                result = {"element": described, "delivered": True, "context": context}

                def observe():
                    after = bridge.call(
                        "(e) => e.isConnected ? JSON.stringify({value: e.type === "
                        "'password' ? undefined : e.value, checked: e.checked}) : null",
                        [element],
                        context,
                    )
                    state = self.page_state(bridge, context)
                    after = browser.remote_value(after)
                    if isinstance(after, str):
                        state["now"] = hide_fields(
                            {
                                k: v
                                for k, v in json.loads(after).items()
                                if v is not None
                            },
                            ("value",),
                        )
                    if isinstance(toggle_before, str):
                        # A label or switch click can be delivered and change nothing.
                        toggle_after = browser.remote_value(
                            bridge.call(TOGGLE_STATE, [element], context)
                        )
                        toggle = {"before": toggle_before, "after": toggle_after}
                        toggle["changed"] = toggle_after != toggle_before
                        state["toggle"] = toggle
                    return state

                return self.browser_observed(result, observe)
            raise ValueError(unknown_browser_action(action))
        except Exception as error:
            if isinstance(error, ConnectionClosed):
                self.browser = None
            if isinstance(error, browser.Interrupted):
                # The navigation was sent; Firefox may still finish loading it.
                return {
                    "delivered": None,
                    "uncertain": True,
                    "interrupted": True,
                    "context": context,
                    "error": "A person is taking control; the page was still "
                    "loading and may finish. " + TAKEN_OVER,
                    "recovery": "When control returns, check the tab before "
                    "opening it again.",
                }
            if mutation_started:
                return {
                    "delivered": None,
                    "uncertain": True,
                    "context": context,
                    "error": str(error),
                    "recovery": "Observe/reconcile before retrying; browser input may have run.",
                }
            if isinstance(
                error, (browser.BrowserError, ConnectionClosed, TimeoutError, OSError)
            ):
                raise ValueError(str(error)) from None
            raise
        finally:
            if self.browser:
                self.browser[0].deadline = None

    def send_secret(self, request, target):
        """Move a value to a file or a command's stdin without returning it.

        The source is one page element's text (or a field's value), the
        session clipboard, or the browser's cookies for one site (Netscape
        format, for tools such as curl or yt-dlp). The reply gives only its length, an optional short
        prefix and a SHA-256 digest; command output is discarded, since a
        command could print its input. This keeps the value out of the agent's
        transcript and the runtime's records; it is not confinement.
        """
        from . import browser

        host = self.info["mode"] == "host"
        to_file, to_command = request.get("to_file"), request.get("to_command")
        if (to_file is None) == (to_command is None):
            raise ValueError("send needs exactly one of to_file or to_command")
        if to_command is not None and (
            not isinstance(to_command, list)
            or not 1 <= len(to_command) <= 64
            or not all(isinstance(a, str) and a for a in to_command)
        ):
            raise ValueError("to_command must be a list of 1 to 64 arguments")
        if to_command is not None and host:
            raise ValueError("to_command is for private sessions only")
        reveal = request.get("reveal", 4)
        if (
            not isinstance(reveal, int)
            or isinstance(reveal, bool)
            or not 0 <= reveal <= 8
        ):
            raise ValueError("reveal must be between 0 and 8 characters")
        home = Path(self.env["HOME"])
        if to_file is not None:
            path = private_path(home, to_file)
        source = request.get("source", "element")
        cookie_count = None
        if source == "cookies":
            if host:
                raise ValueError(
                    "The cookies source is for private sessions only: the "
                    "person's own cookies are never exported"
                )
            if not self.attach_browser():
                raise ValueError('No bridged Firefox; use action "start" first')
            bridge = self.browser[0]
            bridge.deadline = request.get("deadline")
            value, cookie_count = netscape_cookies(bridge, request.get("site"))
            reveal = 0
        elif source == "clipboard":
            if host:
                raise ValueError("The clipboard source is for private sessions only")
            try:
                value = read_selection(self.info["wayland_display"], SECRET_BYTES)
            except (OSError, WaylandError) as error:
                raise ValueError(f"Clipboard not read: {error}") from None
            if not value:
                raise ValueError("The session clipboard is empty")
        elif source == "element":
            if not (target["selector"] or target["text"]):
                raise ValueError(
                    "send needs a selector or a text (or source clipboard)"
                )
            if not self.attach_browser():
                raise ValueError('No bridged Firefox; use action "start" first')
            bridge = self.browser[0]
            bridge.deadline = request.get("deadline")
            context = bridge.target(request.get("tab"), request.get("context"))
            # Count first: an ambiguity error must not list the matches' text.
            count = bridge.find(context, **target)["count"]
            if count != 1:
                raise ValueError(
                    f"{count} visible elements match; send needs exactly one "
                    "(matches are not listed, since they may hold the value)"
                )
            try:
                element, _ = bridge.element(context, **target)
            except browser.BrowserError:
                # The page changed after the count: never pass on the match list.
                raise ValueError(
                    "The match changed while it was looked up; nothing was sent"
                ) from None
            value = browser.remote_value(
                bridge.call(
                    "(e) => (e instanceof HTMLInputElement || e instanceof "
                    "HTMLTextAreaElement) ? e.value : e.innerText",
                    [element],
                    context,
                )
            )
            if not isinstance(value, str):
                raise ValueError("The element has no text")
            value = value.encode()
            if len(value) > SECRET_BYTES:
                raise ValueError(f"The value is longer than {SECRET_BYTES} bytes")
        else:
            raise ValueError('source must be "element", "clipboard" or "cookies"')
        if request.get("strip", True) and cookie_count is None:
            value = value.strip()
        if not value:
            raise ValueError("The value is empty")
        result = {
            "sent": True,
            "bytes": len(value),
            "sha256": hashlib.sha256(value).hexdigest(),
        }
        if reveal:
            result["prefix"] = value.decode(errors="replace")[:reveal]
        if cookie_count is not None:
            result["cookies"] = cookie_count
        if to_file is not None:
            if self.effects:
                self.effects.hide(path)
            flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
            flags |= os.O_TRUNC if request.get("overwrite") is True else os.O_EXCL
            try:
                descriptor = os.open(path, flags, 0o600)
            except FileExistsError:
                raise ValueError(
                    f"{path} exists; pass overwrite to replace it"
                ) from None
            except OSError as error:
                raise ValueError(f"Not written: {error}") from None
            try:
                os.fchmod(descriptor, 0o600)
                os.write(descriptor, value)
            finally:
                os.close(descriptor)
            return {**result, "to_file": str(path)}
        try:
            # Its own process group, so stopping it also stops its children.
            process = subprocess.Popen(
                to_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=self.env,
                cwd=home,
                start_new_session=True,
            )
        except FileNotFoundError:
            raise ValueError(f"No such program: {to_command[0]}") from None
        deadline = time.monotonic() + SECRET_COMMAND_SECONDS
        # Written here rather than by communicate, so the reply can say how
        # much of the value reached the command's stdin when it is stopped.
        # Each wait is at most 0.1 s, so a person taking control does not wait
        # for a command that reads slowly or not at all.
        descriptor = process.stdin.fileno()
        os.set_blocking(descriptor, False)
        written, stopped = 0, None
        while stopped is None:
            if not process.stdin.closed:
                select.select([], [descriptor], [], 0.1)
                try:
                    written += os.write(descriptor, value[written:])
                except BlockingIOError:
                    pass
                except BrokenPipeError:
                    process.stdin.close()  # it closed its input early
                if written == len(value) and not process.stdin.closed:
                    process.stdin.close()
            else:
                try:
                    process.wait(timeout=0.1)
                    return {
                        **result,
                        "exit_status": process.returncode,
                        "bytes_written": written,
                    }
                except subprocess.TimeoutExpired:
                    pass
            if self.take_requested():
                stopped = "taken"
            elif time.monotonic() >= deadline:
                stopped = "timeout"
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if not process.stdin.closed:
            process.stdin.close()
        process.wait()
        if written == len(value):
            given = f"after the whole value ({written} bytes) was written to its stdin"
        else:
            given = (
                f"after {written} of {len(value)} bytes of the value were written "
                "to its stdin (the rest was not sent)"
            )
        if stopped == "timeout":
            return {
                **result,
                "exit_status": None,
                "bytes_written": written,
                "timed_out": True,
                "note": f"The command was killed {given}.",
            }
        # The command was started, so it never counts as not run: it may have
        # read and acted on what was written before it was killed.
        return {
            **result,
            "exit_status": None,
            "bytes_written": written,
            "uncertain": True,
            "interrupted": True,
            "error": "A person is taking control; the command was killed while "
            f"it ran, {given}, and may have partly run. " + TAKEN_OVER,
        }

    def browser_save(self, request, bridge, context, target):
        """Write a page's or element's text to a file instead of the reply.

        For data too large to read in the conversation (an API listing in
        Firefox's JSON viewer, a long table). Unlike send, it is not for
        secrets: the reply gives the size and digest, and the file is the
        whole text or nothing (up to SAVE_BYTES).
        """
        from . import browser

        if request.get("to_file") is None:
            raise ValueError("save needs to_file")
        path = private_path(Path(self.env["HOME"]), request["to_file"])
        if path.exists() and request.get("overwrite") is not True:
            raise ValueError(f"{path} exists; pass overwrite to replace it")
        if target["selector"] or target["text"]:
            count = bridge.find(context, **target)["count"]
            if count != 1:
                raise ValueError(f"{count} visible elements match; save needs one")
            element, _ = bridge.element(context, **target)
            value = browser.remote_value(
                bridge.call(
                    "(e) => (e instanceof HTMLInputElement || e instanceof "
                    "HTMLTextAreaElement) ? e.value : e.innerText",
                    [element],
                    context,
                )
            )
        else:
            # The whole page's visible text (a text/plain response is its body).
            value = browser.remote_value(
                bridge.call("() => document.body?.innerText ?? null", [], context)
            )
        if not isinstance(value, str):
            raise ValueError("Nothing to save: the target has no text")
        data = value.encode()
        if len(data) > SAVE_BYTES:
            raise ValueError(
                f"The text is {len(data)} bytes, over {SAVE_BYTES}; nothing was "
                "saved. Save a smaller part (a page of results, or one element)"
            )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.part")
        try:
            descriptor = os.open(temporary, flags, 0o600)
        except OSError as error:
            raise ValueError(f"Not written: {error}") from None
        try:
            with os.fdopen(descriptor, "wb") as file:
                file.write(data)
            if path.exists() and request.get("overwrite") is not True:
                raise ValueError(f"{path} exists; pass overwrite to replace it")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return {
            "saved": True,
            "to_file": str(path),
            "bytes": len(data),
            "characters": len(value),
            "sha256": hashlib.sha256(data).hexdigest(),
            **self.page_state(bridge, context),
        }

    def browser_download(self, request, bridge, context):
        """Download a URL with the browser's login and return a receipt.

        Firefox saves into the session's ~/Downloads, writing NAME.part and
        renaming it when the transfer ends. The download is the one new file
        there without a .part beside it, once its size is stable. A PDF that
        Firefox shows in its own viewer instead is saved from the viewer's copy
        of the original bytes (browser_pdf); without a url, the PDF the tab
        shows now is saved, which covers PDFs from a form post or a blob. Any
        other page (a login redirect) is reported as such. The reply names the
        file, its size and SHA-256, never the URL, which may carry a signed
        query.
        """
        from . import browser

        url = request.get("url")
        if url is not None and (
            not isinstance(url, str) or not re.match(r"https?://", url, re.I)
        ):
            raise ValueError(
                "download needs an http(s) url, or no url to save the PDF the tab shows"
            )
        timeout = request.get("timeout", DOWNLOAD_SECONDS)
        if (
            not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or not 1 <= timeout <= DOWNLOAD_MAX_SECONDS
        ):
            raise ValueError(
                f"timeout must be between 1 and {DOWNLOAD_MAX_SECONDS} seconds"
            )
        home = Path(self.env["HOME"])
        destination = None
        if request.get("to_file") is not None:
            destination = private_path(home, request["to_file"])
            if destination.exists() and request.get("overwrite") is not True:
                raise ValueError(f"{destination} exists; pass overwrite to replace it")
        folder = home / "Downloads"
        folder.mkdir(mode=0o700, exist_ok=True)
        started = time.monotonic()
        if url is None:
            if self.pdf_viewer(bridge, context) is None:
                raise ValueError(
                    "download without a url saves the PDF that the tab shows in "
                    "Firefox's PDF viewer, and this tab shows no PDF. Give the "
                    "file's url (a PDF inside a frame of a page: its own url)"
                )
            return self.browser_pdf(
                bridge,
                context,
                destination,
                folder,
                started,
                timeout,
                request.get("overwrite"),
            )

        def entries():
            found = {}
            for entry in os.scandir(folder):
                if entry.is_file(follow_symlinks=False):
                    stat = entry.stat(follow_symlinks=False)
                    found[entry.name] = (stat.st_size, stat.st_mtime_ns)
            return found

        before = entries()
        page = self.page_state(bridge, context).get("url")
        # The page's realm: a PDF viewer only counts once a new document has
        # replaced it, never the one showing before the navigation.
        old_realm = self.pdf_viewer(bridge, context, realm=True)
        try:
            bridge.command(
                "browsingContext.navigate",
                {"context": context, "url": url, "wait": "none"},
                timeout=30,
            )
        except browser.BrowserError as error:
            # A navigation that becomes a download can be reported as aborted.
            if "abort" not in str(error).lower():
                raise ValueError(f"The download did not start: {error}") from None
        last = {}
        while True:
            time.sleep(0.25)
            now = entries()
            partial = {n: v for n, v in now.items() if n.endswith(".part")}
            new = {
                n: v
                for n, v in now.items()
                if not n.endswith(".part")
                and before.get(n) != v
                and f"{n}.part" not in now
            }
            settled = {n: v for n, v in new.items() if last.get(n) == v[0]}
            last = {n: v[0] for n, v in new.items()}
            if settled and len(settled) == len(new) and not partial:
                if len(settled) > 1:
                    raise ValueError(
                        f"{len(settled)} downloads finished at once "
                        f"({', '.join(sorted(settled))}); start one at a time"
                    )
                name = next(iter(settled))
                break
            elapsed = time.monotonic() - started
            if not new and not partial:
                realm = self.pdf_viewer(bridge, context)
                if realm is not None and realm != old_realm:
                    return self.browser_pdf(
                        bridge,
                        context,
                        destination,
                        folder,
                        started,
                        timeout,
                        request.get("overwrite"),
                    )
            if not new and not partial and elapsed >= DOWNLOAD_PAGE_SECONDS:
                state = self.page_state(bridge, context)
                ready = browser.remote_value(
                    bridge.call("() => document.readyState", [], context)
                )
                if ready == "complete" and state.get("url") != page:
                    where = re.sub(r"[?#].*", "", state.get("url") or "")
                    raise ValueError(
                        "The URL opened a page instead of a download "
                        f"({state.get('title')!r} at {where}). It may need a "
                        "login, or the browser shows this file type itself "
                        '(send source="cookies" gives curl the login for it); '
                        "nothing was saved"
                    )
            if elapsed >= timeout:
                if partial or new:
                    size = sum(v[0] for v in {**partial, **new}.values())
                    raise ValueError(
                        f"Still downloading after {timeout:g} s ({size} bytes so "
                        "far in ~/Downloads); it continues in the background. "
                        "Do not start it again"
                    )
                raise ValueError(f"No download started within {timeout:g} s")
        path = folder / name
        digest = hashlib.sha256()
        with open(path, "rb") as file:
            for block in iter(lambda: file.read(1 << 20), b""):
                digest.update(block)
        size = path.stat().st_size
        if destination is not None:
            shutil.move(path, destination)
            os.chmod(destination, 0o600)
            path = destination
        return {
            "downloaded": True,
            "name": name,
            "file": str(path),
            "bytes": size,
            "sha256": digest.hexdigest(),
            "seconds": round(time.monotonic() - started, 1),
            "context": context,
        }

    @staticmethod
    def pdf_viewer(bridge, context, realm=False):
        """The realm of the tab's document if Firefox's PDF viewer shows it.

        With realm, the document's realm whatever it shows. None when the tab
        shows something else, or no script can run in it yet (a navigation
        in progress, a privileged page).
        """
        from . import browser

        try:
            result = bridge.command(
                "script.evaluate",
                {
                    "expression": "true" if realm else PDF_VIEWER,
                    "target": {"context": context},
                    "awaitPromise": False,
                },
                timeout=5,
            )
        except (browser.BrowserError, TimeoutError):
            return None
        if result.get("type") != "success":
            return None
        if browser.remote_value(result) is not True:
            return None
        return result.get("realm")

    def browser_pdf(
        self, bridge, context, destination, folder, started, timeout, overwrite
    ):
        """Save the PDF that Firefox's viewer shows: the original bytes.

        pdf.js keeps the file it was given (getData() returns those bytes, not
        a re-rendering), so nothing is requested again: a cookie, a form post
        or a blob URL behind the PDF does not matter. The bytes cross the BiDi
        socket as base64 in chunks under its message limit, into a 0600 file
        written beside the destination and renamed into place.
        """
        from . import browser

        deadline = started + timeout

        def run(function, arguments=(), ownership="none"):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError(
                    f"The PDF was not saved within {timeout:g} s; nothing was saved"
                )
            try:
                result = bridge.command(
                    "script.callFunction",
                    {
                        "functionDeclaration": function,
                        "arguments": list(arguments),
                        "target": {"context": context},
                        "awaitPromise": True,
                        "resultOwnership": ownership,
                    },
                    timeout=remaining,
                )
            except TimeoutError:
                raise ValueError(
                    f"The PDF was not saved within {timeout:g} s; nothing was saved"
                ) from None
            except browser.BrowserError as error:
                raise ValueError(
                    f"The PDF viewer could not be read ({error}); nothing was saved"
                ) from None
            if result.get("type") == "exception":
                details = result.get("exceptionDetails", {})
                raise ValueError(
                    "The PDF viewer could not give the file "
                    f"({details.get('text', 'script error')}); nothing was saved"
                )
            return result["result"]

        # Wait for the document (a large file still loading), then its bytes.
        data = run(
            "async () => { const app = PDFViewerApplication;"
            " await app.initializedPromise;"
            " while (!app.pdfDocument) {"
            "  if (app.pdfLoadingTask) await app.pdfLoadingTask.promise;"
            "  else await new Promise(r => setTimeout(r, 100)); }"
            " return await app.pdfDocument.getData(); }",
            ownership="root",
        )
        handle = data.get("handle")
        try:
            if data.get("type") != "typedarray" or handle is None:
                raise ValueError("The PDF viewer gave no file; nothing was saved")
            reference = {"handle": handle}
            size = browser.remote_value(run("(d) => d.length", [reference]))
            if not isinstance(size, int) or size <= 0:
                raise ValueError("The PDF viewer gave an empty file; nothing was saved")
            if size > PDF_BYTES:
                raise ValueError(
                    f"The PDF is {size} bytes, over {PDF_BYTES}; nothing was saved. "
                    'Use send source="cookies" with curl for it'
                )
            name = pdf_name(
                browser.remote_value(
                    run(
                        "() => PDFViewerApplication._contentDispositionFilename || null"
                    )
                ),
                self.page_state(bridge, context).get("url"),
            )
            if destination is None:
                stem, index = name[:-4], 1
                destination = folder / name
                while destination.exists():
                    destination = folder / f"{stem}({index}).pdf"
                    index += 1
            temporary = destination.with_name(
                f".{destination.name}.{uuid.uuid4().hex[:8]}.part"
            )
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
            try:
                descriptor = os.open(temporary, flags, 0o600)
            except OSError as error:
                raise ValueError(f"Not written: {error}") from None
            digest = hashlib.sha256()
            try:
                with os.fdopen(descriptor, "wb") as file:
                    for start in range(0, size, PDF_CHUNK):
                        chunk = browser.remote_value(
                            run(
                                "(d, start, end) => new Promise((ok, fail) => {"
                                " const reader = new FileReader();"
                                " reader.onload = () =>"
                                "  ok(reader.result.slice(reader.result.indexOf(',') + 1));"
                                " reader.onerror = () => fail(reader.error);"
                                " reader.readAsDataURL("
                                "  new Blob([d.subarray(start, end)])); })",
                                [
                                    reference,
                                    {"type": "number", "value": start},
                                    {"type": "number", "value": start + PDF_CHUNK},
                                ],
                            )
                        )
                        block = base64.b64decode(chunk or "", validate=True)
                        if len(block) != min(PDF_CHUNK, size - start):
                            raise ValueError(
                                "The PDF viewer gave a short chunk; nothing was saved"
                            )
                        digest.update(block)
                        file.write(block)
                if destination.exists() and overwrite is not True:
                    raise ValueError(
                        f"{destination} exists; pass overwrite to replace it"
                    )
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        finally:
            if handle is not None:
                try:
                    bridge.command(
                        "script.disown",
                        {"handles": [handle], "target": {"context": context}},
                        timeout=5,
                    )
                except (browser.BrowserError, TimeoutError):
                    pass  # the page's next navigation frees it anyway
        return {
            "downloaded": True,
            "name": name,
            "file": str(destination),
            "bytes": size,
            "sha256": digest.hexdigest(),
            "content_type": "application/pdf",
            "from_viewer": True,
            "seconds": round(time.monotonic() - started, 1),
            "context": context,
        }

    @staticmethod
    def browser_observed(result, observe):
        """A follow-up read must never erase an acknowledged mutation."""
        try:
            return {**result, **observe()}
        except Exception as error:
            return {
                **result,
                "observation_error": str(error),
                "recovery": "Observe/reconcile before repeating the delivered action.",
            }

    def browser_steps(self, steps, controller=None, deadline=None):
        """Several browser actions in one request, stopping at the first error."""
        if not isinstance(steps, list) or not steps:
            raise ValueError("steps must be a list of 1 to 30 browser actions")
        if len(steps) > 30:
            raise ValueError(
                f"steps has {len(steps)} actions, more than 30; nothing was run. "
                "Split it into batches of up to 30"
            )
        for index, step in enumerate(steps):
            if not isinstance(step, dict) or step.get("action") in (None, "steps"):
                raise ValueError(f"Step {index} needs an action other than steps")
            if step["action"] not in BROWSER_ACTIONS:
                raise ValueError(
                    f"Step {index}: {unknown_browser_action(step['action'])}; "
                    "nothing was run"
                )
        results = []
        for index, step in enumerate(steps):
            try:
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError("Browser batch deadline reached before step")
                result = self.browser_request(
                    {**step, "controller": controller, "deadline": deadline}
                )
            except (ValueError, TimeoutError, HumanControl) as error:
                return {
                    "completed": index,
                    "total": len(steps),
                    "results": results,
                    "stopped": {"step": index, "reason": str(error)},
                }
            if result.get("uncertain") or result.get("observation_error"):
                results.append(result)
                return {
                    "completed": index + (1 if result.get("delivered") else 0),
                    "total": len(steps),
                    "results": results,
                    "stopped": {
                        "step": index,
                        "reason": result.get("error") or result["observation_error"],
                        "uncertain": bool(result.get("uncertain")),
                    },
                }
            hint = fixed_wait_hint(steps, index)
            if hint:
                result = {**result, "hint": hint}
            if step["action"] == "wait" and not result.get("satisfied"):
                results.append(result)
                return {
                    "completed": index + 1,
                    "total": len(steps),
                    "results": results,
                    "stopped": {"step": index, "reason": "wait not satisfied"},
                }
            results.append(result)
        return {
            "completed": len(steps),
            "total": len(steps),
            "results": results,
            "stopped": None,
        }

    def page_state(self, bridge, context):
        from . import browser

        state = bridge.call(
            "() => JSON.stringify({url: location.href, title: document.title})",
            [],
            context,
        )
        return {**json.loads(browser.remote_value(state)), "context": context}

    def ui_snapshot(self):
        """The focused window's UI as comparable lines, for effect reports."""
        if not self.info.get("accessibility"):
            return None
        focused = next(
            (w for w in self.toplevels.current() if "activated" in w["states"]),
            None,
        )
        if focused is None or not focused["title"]:
            return None
        # Not by title: the frame's name can lag it (a page that retitled itself).
        accessibility = self.accessibility()
        frame = accessibility.focused_frame(focused["app_id"], focused["title"])
        if frame is None:
            return None
        # Without action lists: fewer D-Bus calls per element.
        tree = accessibility.tree(None, frame, 400, budget=0.5, actions=False)
        nodes = [n for n in tree["nodes"] if n["depth"] > 1]
        if not nodes:
            return None  # not readable now: no delta rather than a false one
        # In a browser, the page: the toolbar and tabs say nothing new.
        document = next(
            (i for i, n in enumerate(nodes) if n["role"].startswith("document")), None
        )
        if document is not None:
            depth = nodes[document]["depth"]
            end = next(
                (
                    i
                    for i in range(document + 1, len(nodes))
                    if nodes[i]["depth"] <= depth
                ),
                len(nodes),
            )
            nodes = nodes[document:end]
        return {
            "window": focused["id"],
            "title": focused["title"],
            "lines": ui_lines(nodes),
        }

    def accessibility(self):
        if not self.info.get("accessibility"):
            raise RuntimeError(
                self.info.get("accessibility_error")
                or "Accessibility unavailable: install at-spi2-core or set "
                "AGENT_DESKTOP_AT_SPI_REGISTRYD"
            )
        if self.atspi is None:
            self.atspi = Accessibility(self.env["DBUS_SESSION_BUS_ADDRESS"])
        return self.atspi

    def start_bus(self):
        # A child bus keeps D-Bus-activated services inside this worker's tree.
        bus = Path(self.info["runtime"]) / "bus"
        daemon = self.info["tools"]["dbus-daemon"]
        # Some builds (e.g. Nix) default to /etc/dbus-1/session.conf, which only
        # their own distribution provides; prefer the configuration shipped beside
        # the daemon.
        shipped = Path(daemon).resolve().parent.parent / "share/dbus-1/session.conf"
        config = [f"--config-file={shipped}"] if shipped.is_file() else ["--session"]
        with (self.root / "dbus.log").open("ab") as log:
            self.bus = subprocess.Popen(
                [
                    daemon,
                    *config,
                    "--nofork",
                    "--nopidfile",
                    f"--address=unix:path={bus}",
                ],
                env=self.env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
            )
        deadline = time.monotonic() + 10
        while not bus.is_socket():
            if self.bus.poll() is not None or time.monotonic() > deadline:
                detail = (self.root / "dbus.log").read_text()[-4096:]
                raise RuntimeError(f"Private D-Bus did not start\n{detail}")
            time.sleep(0.02)
        self.env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus}"

    def tracked(self):
        processes = [
            self.bus,
            self.bus_launcher,
            self.registry,
            self.compositor,
            self.viewer,
            self.takeover,
            *self.apps.values(),
        ]
        return {p.pid for p in processes if p}

    def output_size(self):
        """The desktop's current [width, height] (None before it has started)."""
        if self.virtual_pointer is None:
            return None
        self.virtual_pointer.connection.roundtrip()
        output = self.virtual_pointer.output
        return [output["width"], output["height"]]

    def screenshot(self, region=None, scale=None):
        self.virtual_pointer.connection.roundtrip()
        output = self.virtual_pointer.output
        region_given = region is not None
        arguments = []
        if region is not None:
            if (
                not isinstance(region, list)
                or len(region) != 4
                or not all(
                    isinstance(v, int) and not isinstance(v, bool) for v in region
                )
            ):
                raise ValueError("Region must be [x, y, width, height] integers")
            x, y, width, height = region
            if (
                x < 0
                or y < 0
                or width < 1
                or height < 1
                or x + width > output["width"]
                or y + height > output["height"]
            ):
                raise ValueError(
                    f"Region must lie within the {output['width']}x{output['height']} desktop"
                )
            arguments += ["-g", f"{x},{y} {width}x{height}"]
        else:
            region = [0, 0, output["width"], output["height"]]
        if scale is not None:
            # Enlarging only helps a crop: a small region seen more sharply.
            largest = MAX_CROP_SCALE if region_given else 1
            if (
                not isinstance(scale, (int, float))
                or isinstance(scale, bool)
                or not 0.1 <= scale <= largest
            ):
                raise ValueError(
                    "Scale must be between 0.1 and 1, or up to "
                    f"{MAX_CROP_SCALE} with a region"
                )
            arguments += ["-s", str(scale)]
        directory = self.root / "screenshots"
        directory.mkdir(exist_ok=True, mode=0o700)
        self.prune_screenshots(directory)
        path = directory / (uuid.uuid4().hex + ".png")
        # Retry so the token describes the layout the image actually shows.
        for _ in range(3):
            before = self.observation()
            self.command("grim", *arguments, path)
            if self.observation() == before:
                break
        else:
            path.unlink(missing_ok=True)
            raise StaleObservation(
                "Windows or focus kept changing during capture; no screenshot "
                "was taken. Try again once the desktop has settled."
            )
        with path.open("rb") as stream:
            header = stream.read(24)
        if not header.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("Capture did not produce a PNG")
        width, height = struct.unpack(">II", header[16:24])
        return {
            "path": str(path),
            "width": width,
            "height": height,
            "region": region,
            "scale": scale or 1,
            "observation": image_token(before, region, scale),
        }

    def changed_screenshot(self, scale=None):
        """Only the part of the screen that changed since the last whole frame
        shown: the changed box plus a margin, the whole frame when most of the
        screen changed or nothing was shown before, or no image at all when
        nothing changed. The token maps the region's coordinates as usual."""
        width, height, pixels = self.capture_pixels()
        previous, self.seen = self.seen, (width, height, pixels)
        if previous is None or previous[:2] != (width, height):
            return {**self.screenshot(None, scale), "changed_only": "whole frame"}
        box = changed_box(previous[2], pixels, width, height)
        if not box:
            # No token: the last image's own token still maps its coordinates.
            return {"unchanged": True}
        x, y, w, h = box
        margin = CHANGED_MARGIN
        left, top = max(0, x - margin), max(0, y - margin)
        right, bottom = min(width, x + w + margin), min(height, y + h + margin)
        if (right - left) * (bottom - top) > CHANGED_WHOLE * width * height:
            return {**self.screenshot(None, scale), "changed_only": "whole frame"}
        capture = self.screenshot([left, top, right - left, bottom - top], scale)
        return {**capture, "changed_only": "region"}

    def prune_screenshots(self, directory):
        """Keep the newest screenshots only, so long sessions do not fill the disk."""
        keep = int(os.environ.get("AGENT_DESKTOP_KEEP_SCREENSHOTS", 200))
        shots = sorted(directory.glob("*.png"), key=lambda p: p.stat().st_mtime)
        for old in shots[: max(0, len(shots) - (keep - 1))]:
            old.unlink(missing_ok=True)

    def capture_pixels(self):
        """Capture the output as raw RGB without writing a file."""
        if self.compositor.poll() is not None:
            raise RuntimeError("Private compositor has exited")
        try:
            result = subprocess.run(
                [self.info["tools"]["grim"], "-t", "ppm", "-"],
                env=self.env,
                capture_output=True,
                timeout=10,
            )
        except FileNotFoundError:
            raise RuntimeError(
                runtime_changed("grim", self.info["tools"]["grim"])
            ) from None
        if result.returncode:
            raise RuntimeError(f"grim failed: {result.stderr.decode(errors='replace')}")
        data = result.stdout
        # Binary PPM: "P6", width, height, maxval, then one whitespace byte.
        fields, offset = [], 0
        while len(fields) < 4:
            while data[offset : offset + 1].isspace():
                offset += 1
            end = offset
            while not data[end : end + 1].isspace():
                end += 1
            fields.append(data[offset:end])
            offset = end
        if fields[0] != b"P6" or fields[3] != b"255":
            raise RuntimeError("Capture did not produce an 8-bit PPM")
        width, height = int(fields[1]), int(fields[2])
        pixels = data[offset + 1 :]
        if len(pixels) != width * height * 3:
            raise RuntimeError("Truncated capture")
        return width, height, pixels

    def frame(self, since):
        """Capture a frame and report the bounding box changed since another one."""
        width, height, pixels = self.capture_pixels()
        token = uuid.uuid4().hex[:12]
        previous = self.frames.get(since) if isinstance(since, str) else None
        self.frames[token] = (width, height, pixels)
        while len(self.frames) > 4:
            self.frames.pop(next(iter(self.frames)))
        result = {"frame": token, "width": width, "height": height}
        if previous is None:
            result["changed"] = None if since is None else "unknown"
        elif previous[:2] != (width, height):
            result["changed"] = [0, 0, width, height]
        else:
            result["changed"] = changed_box(previous[2], pixels, width, height)
        return result

    def settle_after(self, kind, host):
        """Settle when switching between `type` and `key` within a second.

        Text sent right after a shortcut can arrive before the shortcut has
        moved focus (Calc's Name Box), and a key right after text can overtake
        it. Consecutive keys or consecutive texts are not delayed.
        """
        last, at = self.last_keys
        if last == kind and time.monotonic() - at < 1 and not host:
            self.settle()

    def settle(self, quiet=0.15, limit=1.0):
        """Wait until the screen has not changed for `quiet` seconds, at most `limit`.

        A key sent while an application is still working through typed text can
        overtake it: LibreOffice applied Home and Down after the text sent before
        them (F006). A quiet screen makes that less likely; it does not prove the
        application is done (a slow reply can arrive later). Returns whether the
        screen went quiet ("quiet") or was still changing at the limit
        ("changing"), and how long it took.
        """
        started = time.monotonic()
        deadline = started + limit
        token = self.frame(None)["frame"]
        quiet_since = time.monotonic()
        while time.monotonic() - quiet_since < quiet and time.monotonic() < deadline:
            if self.take_requested():
                break  # the caller checks again and gives way
            time.sleep(0.03)
            latest = self.frame(token)
            token, box = latest["frame"], latest["changed"]
            if box == "unknown" or (box and box[2] * box[3] > SETTLE_AREA):
                quiet_since = time.monotonic()
        return {
            "settled": (
                "quiet" if time.monotonic() - quiet_since >= quiet else "changing"
            ),
            "settle_ms": round((time.monotonic() - started) * 1000),
        }

    def observation(self):
        """Token for the window layout: output, windows, focus and states.

        Titles are excluded because many applications update them continuously.
        """
        self.virtual_pointer.connection.roundtrip()
        output = self.virtual_pointer.output
        windows = sorted(
            (w["id"], w["app_id"], w["states"], w["parent"])
            for w in self.toplevels.current()
        )
        # The control epoch makes every token stale after a person had control.
        # The session id keeps one session's token from validating in another.
        layout = [
            self.info["id"],
            output["width"],
            output["height"],
            output["scale"],
            windows,
            self.control["epoch"],
        ]
        return hashlib.sha256(json.dumps(layout).encode()).hexdigest()[:16]

    def check_observation(self, token):
        if not isinstance(token, str):
            raise ValueError("Observation must be a token from screenshot")
        if token.partition("@")[0] != self.observation():
            raise StaleObservation(
                "Windows, focus or output changed since that screenshot; "
                "no input was sent. Take a new screenshot."
            )

    def control_state(self):
        return {
            "session": self.info["id"],
            **self.control,
            "needs_screenshot": self.needs_screenshot,
            "take_command": printed.command("take", self.info["id"]),
            # Sends the host clipboard in once, e.g. a password-manager entry.
            "paste_command": printed.command("take", "--paste", self.info["id"]),
            "lease": self.lease_state(),
        }

    def active_lease(self):
        if self.lease and time.monotonic() >= self.lease["expires"]:
            self.lease = None
        return self.lease

    def lease_state(self):
        lease = self.active_lease()
        if not lease:
            return None
        return {
            "holder": lease["holder"],
            "seconds": lease["seconds"],
            "expires_in": round(lease["expires"] - time.monotonic(), 1),
        }

    def refuse_lease(self, controller):
        lease = self.lease
        who = "named no controller" if controller is None else f"is from {controller}"
        raise LeaseHeld(
            f"Controller {lease['holder']} holds this session's lease "
            f"({lease['expires'] - time.monotonic():.0f} s left unless renewed) and "
            f"this request {who}; nothing was sent. Each session has one "
            "controller: use a separate session, or wait until the holder "
            "releases the lease or it expires."
        )

    def check_lease(self, operation, controller):
        """Enforce one exclusive controller.

        Any request from the holder renews its lease. A mutating request from
        another controller, or with no controller id, is refused while the
        lease is active. Without an active lease, a mutating request with an id
        acquires the lease; one without an id runs without taking a lease (the
        compatible single-client behaviour). Reads are never refused.
        """
        lease = self.active_lease()
        if lease and controller == lease["holder"]:
            lease["expires"] = time.monotonic() + lease["seconds"]
        elif operation in MUTATING_OPERATIONS:
            if lease:
                self.refuse_lease(controller)
            if controller is not None:
                self.lease = {
                    "holder": controller,
                    "seconds": self.lease_seconds,
                    "expires": time.monotonic() + self.lease_seconds,
                }

    def lease_request(self, request, controller):
        action = request.get("action", "acquire")
        lease = self.active_lease()
        if action == "acquire":
            if controller is None:
                raise ValueError("Acquiring a lease requires a controller id")
            # Renewing keeps the holder's duration unless a new one is given.
            same = lease and lease["holder"] == controller
            seconds = request.get("seconds") or (
                lease["seconds"] if same else self.lease_seconds
            )
            if (
                not isinstance(seconds, (int, float))
                or isinstance(seconds, bool)
                or not 1 <= seconds <= 3600
            ):
                raise ValueError("Lease seconds must be between 1 and 3600")
            if lease and lease["holder"] != controller:
                self.refuse_lease(controller)
            self.lease = {
                "holder": controller,
                "seconds": seconds,
                "expires": time.monotonic() + seconds,
            }
            return {"session": self.info["id"], "lease": self.lease_state()}
        if action == "release":
            released = False
            if lease:
                if lease["holder"] != controller and request.get("force") is not True:
                    raise LeaseHeld(
                        f"Controller {lease['holder']} holds this session's lease; "
                        "only it can release the lease (a person can use --force)."
                    )
                self.lease, released = None, True
            return {"session": self.info["id"], "released": released, "lease": None}
        raise ValueError("Lease action must be acquire or release")

    def save_control(self):
        self.info["control"] = {
            "owner": self.control["owner"],
            "request": self.control["request"],
            # How control last came back (for `events`); no content.
            "last": self.control["last"],
        }
        write_manifest(self.root, self.info)

    def start_vnc(
        self, wayvnc, endpoint, control_socket, interactive=False, keyboard=None
    ):
        executable = shutil.which(wayvnc, path=self.env.get("PATH"))
        if not executable:
            raise ValueError("Missing optional viewer dependency: wayvnc")
        endpoint.unlink(missing_ok=True)
        help_result = subprocess.run(
            [executable, "--help"],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
        flags = [
            "-u",
            "-C",
            "/dev/null",
            "-f",
            "30" if interactive else "10",
            "-S",
            str(Path(self.info["runtime"]) / control_socket),
        ]
        if not interactive:
            flags.append("-d")
        elif "--exit-on-disconnect" in help_result.stdout:
            # The server exits with its client, which returns control.
            flags.append("-e")
        if keyboard:
            # Viewers send key positions; read them with the person's layout.
            flags.append(f"--keyboard={keyboard}")
        if "--disable-resizing" in help_result.stdout:
            flags.append("-R")
        if "--name" in help_result.stdout:
            role = "you have control" if interactive else "view only"
            flags += ["-n", f"Agent desktop {self.info['id']} ({role})"]
        log_path = self.root / ("takeover.log" if interactive else "viewer.log")
        with log_path.open("ab") as log:
            process = subprocess.Popen(
                [executable, *flags, str(endpoint)],
                env=self.env,
                stdout=log,
                stderr=log,
            )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if process.poll() is not None:
                detail = log_path.read_text()[-4096:]
                raise RuntimeError(f"Viewer server failed; see {log_path}\n{detail}")
            if endpoint.is_socket():
                return process
            time.sleep(0.05)
        process.terminate()
        process.wait(timeout=3)
        raise TimeoutError("Viewer socket did not appear")

    def take_requested(self):
        """A `take` is waiting behind the current request. A marker older than
        TAKE_MARKER_SECONDS was left by a client that died; it is ignored."""
        if not self.info.get("runtime"):
            return False
        try:
            written = (Path(self.info["runtime"]) / TAKE_REQUESTED).stat().st_mtime
        except OSError:
            return False
        return time.time() - written < TAKE_MARKER_SECONDS

    def pause(self, seconds):
        """Sleep inside a request, but give way at once to a person taking control.

        The worker serves one request at a time, so a long browser wait would
        otherwise hold back `take` until it ends. Raised before any input of the
        current step, so nothing is left half done.
        """
        deadline = time.monotonic() + seconds
        while True:
            if self.take_requested():
                raise HumanControl(
                    "A person is taking control; the wait was stopped and nothing "
                    "more was sent. Wait with desktop_control until control returns."
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.1, remaining))

    def just_acted(self):
        """Whether the agent sent input within the last HOST_SETTLE_AFTER seconds."""
        at = getattr(self, "mutated_at", None)
        return at is not None and time.monotonic() - at < HOST_SETTLE_AFTER

    def open_in_person_firefox(self, url):
        """Without a BiDi port, open a URL as a new tab of the person's running
        Firefox, the way a link from another app would. The tab cannot be read
        or driven afterwards. On Hyprland 0.57.1 the window Firefox chose for the
        tab stayed where it was rather than coming forward."""
        if not isinstance(url, str) or not re.match(r"https?://", url):
            raise ValueError("open needs an http or https url")
        self.launch_on_host(["firefox", "--new-tab", url], self.env["HOME"])
        return {
            "delivered": True,
            "opened_in": "the person's running Firefox, without the bridge",
            "url": url,
            "note": (
                "This tab cannot be read or driven: Firefox has no BiDi port. "
                "Firefox picks the window, which may stay in the background or on "
                "another workspace; check desktop_windows for the window title "
                "before a screenshot."
            ),
        }

    def bridged_firefox(self):
        """(application id, process) of a running Firefox with a BiDi port, found
        the way attach_browser finds it (its log), or None."""
        for app, process in self.apps.items():
            log = self.root / f"app-{app}.log"
            if process.poll() is None and log.exists():
                if BIDI_LISTENING.search(log.read_text(errors="replace")):
                    return app, process
        return None

    def stop_firefox(self, process, bridge=None):
        """Quit a Firefox and wait, so its profile is saved and unlocked.
        Returns whether it exited by itself (status 0) rather than being killed."""
        try:
            if bridge is not None:
                bridge.command("browser.close", {}, timeout=10)
            elif not self.toplevels.close_app("firefox"):
                process.terminate()
            # Closing its windows, as a person would, makes Firefox write its
            # cookies before it exits; a signal can lose the latest ones.
            process.wait(timeout=20)
        except Exception:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
        return process.returncode == 0

    def open_login_browser(self):
        """For a person's login: the bridged Firefox, reopened without the
        remote agent (sites see navigator.webdriver and refuse sign-in)."""
        found = self.bridged_firefox()
        if not found or not self.attach_browser():
            return {"swapped": False, "reason": "no bridged Firefox was running"}
        bridge = self.browser[0]
        url = None
        try:
            tree = bridge.command("browsingContext.getTree", {"maxDepth": 0})
            contexts = tree["contexts"]
            chosen = bridge.context or (contexts[-1]["context"] if contexts else None)
            url = next((c["url"] for c in contexts if c["context"] == chosen), None)
        except Exception:
            pass
        self.stop_firefox(found[1], bridge)
        bridge.socket.close()
        self.browser = None
        argv = ["firefox", *([url] if url and url != "about:blank" else [])]
        executable = shutil.which("firefox", path=self.env.get("PATH"))
        if not executable:
            return {"swapped": False, "url": url, "error": "firefox not found"}
        app = uuid.uuid4().hex[:12]
        started = time.time()
        with (self.root / f"app-{app}.log").open("ab") as log:
            self.apps[app] = subprocess.Popen(
                [executable, *argv[1:]],
                env=self.env,
                cwd=self.env["HOME"],
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
        return {"swapped": True, "application": app, "url": url, "started": started}

    def restore_bridge(self, login):
        """After the login: quit the plain Firefox, keep its session-only
        cookies for a day, and start it again under BiDi."""
        process = self.apps.get(login.get("application"))
        if process is not None and process.poll() is None:
            self.stop_firefox(process)
        kept = self.keep_login_cookies(login, process)
        lease = self.active_lease()
        try:
            self.start_browser(login.get("url"), lease["holder"] if lease else None)
        except Exception as error:
            return {
                "restarted": False,
                "error": str(error)[:300],
                "recovery": 'Start the bridge again with desktop_browser "start".',
                **kept,
            }
        return {"restarted": True, "url": login.get("url"), **kept}

    def keep_login_cookies(self, login, process):
        """Session-only cookies of the login (Firefox under BiDi does not
        restore them) become persistent ones in the session's own profile,
        expiring in cookies.SESSION_COOKIE_HOURS. Never raises: a problem is
        reported and the restart goes on."""
        from . import cookies

        notes = []
        try:
            if process is not None and process.poll() is None:
                return {
                    "kept_session_cookies": 0,
                    "session_cookies_note": "Firefox was still running; "
                    "its session-only cookies were not kept.",
                }
            if process is not None and process.returncode != 0:
                notes.append(
                    f"Firefox did not quit cleanly (status {process.returncode}), "
                    "so cookies set after its last periodic save may be missing"
                )
            if "firefox" not in self.info.get("pinned_browsers", []):
                notes.append("Firefox is not pinned to the session profile")
                kept = {"kept": 0, "expires": None, "problems": []}
            else:
                since = login.get("started")
                kept = cookies.keep_session_cookies(
                    Path(self.env["HOME"]) / cookies.SESSION_FIREFOX,
                    since=since - 2 if isinstance(since, (int, float)) else None,
                )
                if kept["store"] is None and not kept["problems"]:
                    notes.append("no session store was saved during the login")
            notes += kept["problems"]
        except Exception as error:
            kept = {"kept": 0, "expires": None}
            notes.append(f"{type(error).__name__}: {str(error)[:200]}")
        result = {"kept_session_cookies": kept["kept"]}
        if kept.get("store"):
            result["session_cookies_from"] = kept["store"]
        if kept["expires"]:
            result["session_cookies_expire"] = kept["expires"]
        if notes:
            result["session_cookies_note"] = "; ".join(notes) + "."
        return result

    def take(self, wayvnc, keyboard=None):
        endpoint = Path(self.info["runtime"]) / "takeover.sock"
        if keyboard is not None and (
            not isinstance(keyboard, str) or not KEYBOARD.fullmatch(keyboard)
        ):
            raise ValueError("Keyboard must look like us or us-dvorak")
        Path(self.info["runtime"], TAKE_REQUESTED).unlink(missing_ok=True)
        if self.control["owner"] != "human":
            request = self.control.get("request") or {}
            self.takeover = self.start_vnc(
                wayvnc,
                endpoint,
                "takeover-control.sock",
                interactive=True,
                keyboard=keyboard,
            )
            self.control["keyboard"] = keyboard
            if request.get("login") and self.info["mode"] != "host":
                # Only once the viewer runs, so a failed start leaves the
                # bridged Firefox alone and control with the agent.
                try:
                    self.control["login_browser"] = self.open_login_browser()
                except Exception as error:
                    self.control["login_browser"] = {
                        "swapped": False,
                        "error": str(error)[:300],
                    }
            self.control.update(owner="human", since=time.time())
            self.control["epoch"] += 1
            self.save_control()
            print("Control taken by a person", file=sys.stderr, flush=True)
        return {**self.control_state(), "socket": str(endpoint)}

    def release(self, how, force=False):
        if self.control["owner"] == "human":
            try:
                # Anything the person pasted (e.g. a password) must not stay
                # available to the agent; clear it while they still own control.
                clear_selection(self.info["wayland_display"])
                cleared = True
            except (OSError, RuntimeError) as error:
                print(f"Clipboard not cleared: {error}", file=sys.stderr, flush=True)
                if not force:
                    self.control["release_error"] = f"clipboard not cleared: {error}"
                    self.save_control()
                    raise RuntimeError(
                        f"Clipboard could not be cleared ({error}); control stays "
                        "with the person. Retry, or release with --force."
                    ) from None
                cleared = False
            if self.takeover and self.takeover.poll() is None:
                self.takeover.terminate()
                try:
                    self.takeover.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.takeover.kill()
                    self.takeover.wait()
            Path(self.info["runtime"], "takeover.sock").unlink(missing_ok=True)
            self.control.pop("release_error", None)
            self.control.update(
                owner="agent",
                request=None,
                last={
                    "released_at": time.time(),
                    "how": how,
                    "clipboard_cleared": cleared,
                },
            )
            self.control.pop("since", None)
            self.control["epoch"] += 1
            self.needs_screenshot = True
            self.seen = None
            self.save_control()
            login = self.control.pop("login_browser", None)
            if login and login.get("swapped"):
                self.control["last"]["browser"] = self.restore_bridge(login)
                self.save_control()
            print(f"Control returned to the agent: {how}", file=sys.stderr, flush=True)
        return self.control_state()

    def pointer(self):
        if self.compositor.poll() is not None:
            raise RuntimeError("Private compositor has exited")
        return self.virtual_pointer

    def keyboard(self):
        if self.compositor.poll() is not None:
            raise RuntimeError("Private compositor has exited")
        return self.virtual_keyboard

    def drag(self, pointer, start, end, button):
        pointer.move(*start)
        pointer.sync()
        pointer.button(button, True)
        pointer.sync()
        distance = math.dist(start, end)
        steps = min(60, max(8, int(distance / 16)))
        for step in range(1, steps + 1):
            time.sleep(0.01)
            pointer.move(
                round(start[0] + (end[0] - start[0]) * step / steps),
                round(start[1] + (end[1] - start[1]) * step / steps),
            )
        pointer.sync()
        time.sleep(0.05)
        pointer.button(button, False)

    def mark_mutation(self):
        """A mutation call is about to start; errors cannot establish rollback."""
        self.mutation_started = True
        self.mutated_at = time.monotonic()

    def error_reply(self, error):
        reply = {"ok": False, "error": f"{type(error).__name__}: {error}"}
        if getattr(self, "mutation_started", False):
            reply["uncertain"] = True
        return reply

    def handle_with_effects(self, request):
        """Optional instrumentation cannot erase known execution results."""
        self.mutation_started = False
        record = None
        effect_error = None
        if (
            self.effects
            and request.get("operation") in EFFECT_OPERATIONS
            and self.control["owner"] == "agent"
        ):
            try:
                record = self.effects.begin()
            except Exception as error:
                effect_error = str(error)
        result = self.handle(request)
        if record and isinstance(result, dict):
            try:
                result["effects"] = self.effects.finish(record)
            except Exception as error:
                effect_error = str(error)
        if effect_error is not None and isinstance(result, dict):
            result["effects_error"] = effect_error
        return result

    def handle(self, request):
        if (
            request.get("deadline") is not None
            and time.monotonic() >= request["deadline"]
        ):
            raise ValueError(
                "Request deadline expired before execution; nothing delivered"
            )
        operation = request["operation"]
        warning = None
        if operation == "destroy":
            self.stop = True
            return {"status": "stopping"}
        if self.compositor.poll() is not None:
            raise RuntimeError("Private compositor has exited")
        controller = request.get("controller")
        if controller is not None and (
            not isinstance(controller, str) or not CONTROLLER_ID.fullmatch(controller)
        ):
            raise ValueError(
                "Controller ids are 1-64 letters, digits or . _ : @ - characters"
            )
        if operation == "lease":
            return self.lease_request(request, controller)
        host = self.info["mode"] == "host"
        if host and operation in HOST_UNSUPPORTED:
            raise ValueError(
                f"{operation} is not available on the host session: the person "
                "is at this screen. Use a private session for it."
            )
        if operation == "release_keys":
            # A safety path: keys come up even when input is otherwise refused.
            self.release_held_keys()
            return {"session": self.info["id"], "released": True}
        if host and operation in (*INPUT_OPERATIONS, "focus") and operation != "key_up":
            unavailable = self.host_unavailable()
            if unavailable:
                raise ScreenUnavailable(
                    f"Nothing was sent: {unavailable}. Input would not reach the "
                    "person's windows. Stop and tell the person."
                )
            if self.user_active():
                raise UserActive(
                    "The person is using the computer, or a program outside these "
                    "tools sent input; nothing was sent. Wait a few seconds "
                    "(desktop_wait with seconds) and try again."
                )
            if request.get("observation") is not None and any(
                moment > self.screenshot_at for moment in self.person_input()
            ):
                raise StaleObservation(
                    "The person, or a program outside these tools, used the "
                    "computer after that screenshot; nothing was sent. Take a "
                    "new screenshot (its token can look the same "
                    "when the windows did not change; it is still the one to use)."
                )
        # destroy, take, release and viewer_start stay available to everyone:
        # they are lifecycle and person controls, never agent input.
        self.check_lease(operation, controller)
        if operation == "status":
            return {
                "session": self.info["id"],
                "mode": self.info["mode"],
                "status": "ready",
                "profile": self.info.get("profile"),
                "accessibility": self.info.get("accessibility", False),
                **(
                    {"accessibility_error": self.info["accessibility_error"]}
                    if self.info.get("accessibility_error")
                    else {}
                ),
                "secret_service": self.info.get("secret_service", True),
                "guard_host": bool(self.info.get("guard_host")),
                "renderer": self.info.get("renderer"),
                "size": self.output_size(),
                "guard_removed_variables": self.info.get("guard_removed_variables", []),
                "home_removed_variables": self.info.get("home_removed_variables", []),
                "pinned_browsers": self.info.get("pinned_browsers", []),
                "x_display": self.info.get("x_display"),
                "control": self.control["owner"],
                "human_requested": self.control["request"] is not None,
                "lease": self.lease_state(),
                "applications": [
                    {"pid": p.pid, "exit_code": p.poll()} for p in self.apps.values()
                ],
                "processes": [
                    {"pid": pid, "command": command_name(pid)}
                    for pid in session_processes(self.info["token"])
                ],
            }
        if operation == "attach_profile":
            return self.attach_profile(request)
        if operation == "viewer_start":
            endpoint = Path(self.info["runtime"]) / "vnc.sock"
            if not (self.viewer and self.viewer.poll() is None):
                self.viewer = self.start_vnc(
                    request.get("wayvnc", "wayvnc"), endpoint, "vnc-control.sock"
                )
            return {"socket": str(endpoint), "read_only": True}
        if operation == "control":
            return self.control_state()
        if operation == "request_human" and request.get("withdraw") is True:
            # The agent no longer needs the person; a takeover already under
            # way continues until they release it.
            self.control["request"] = None
            self.save_control()
            return self.control_state()
        if operation == "request_human":
            reason = request.get("reason")
            if not isinstance(reason, str) or not 0 < len(reason.strip()) <= 500:
                raise ValueError(
                    "Reason must be a nonempty string of at most 500 characters"
                )
            self.control["request"] = {"reason": reason.strip(), "at": time.time()}
            if request.get("login") is True:
                self.control["request"]["login"] = True
            self.save_control()
            state = self.control_state()
            if not request.get("login") and self.info["mode"] != "host":
                if self.bridged_firefox():
                    state["hint"] = (
                        "For a login in the bridged Firefox, pass login=true: "
                        "sites such as Google refuse sign-in in a remote-"
                        "controlled browser, so it is reopened without the "
                        "bridge for the person's turn."
                    )
            return state
        if operation == "take":
            # Cleared on receipt, so a take refused below leaves nothing behind.
            Path(self.info["runtime"], TAKE_REQUESTED).unlink(missing_ok=True)
            self.release_held_keys()
            return self.take(request.get("wayvnc", "wayvnc"), request.get("keyboard"))
        if operation == "release":
            return self.release(
                "released by the user", force=request.get("force") is True
            )
        if self.control["owner"] == "human":
            raise HumanControl(
                "A person has control of this private desktop; nothing was sent. "
                "Wait with desktop_control until control returns to the agent."
            )
        if self.needs_screenshot and operation in (
            *INPUT_OPERATIONS,
            "focus",
            "ui_action",
        ):
            raise StaleObservation(
                "A person used this desktop since your last screenshot; "
                "no input was sent. Take a new screenshot."
            )
        if operation == "launch":
            argv = request.get("argv")
            if (
                not isinstance(argv, list)
                or not argv
                or not all(isinstance(v, str) and "\0" not in v for v in argv)
            ):
                raise ValueError("Launch requires a nonempty argument list")
            cwd = request.get("cwd") or self.env["HOME"]
            if (
                not isinstance(cwd, str)
                or not os.path.isabs(cwd)
                or not os.path.isdir(cwd)
            ):
                raise ValueError("cwd must be an existing absolute directory")
            executable = shutil.which(argv[0], path=self.env.get("PATH"))
            if not executable:
                raise ValueError(f"Executable not found: {argv[0]}")
            if host:
                return self.launch_on_host([executable, *argv[1:]], cwd)
            app = uuid.uuid4().hex[:12]
            log_path = self.root / f"app-{app}.log"
            with log_path.open("ab") as log:
                self.mark_mutation()
                process = subprocess.Popen(
                    [executable, *argv[1:]],
                    env=self.env,
                    # The caller's choice, else the session home; never the
                    # directory the session happened to be created from.
                    cwd=cwd,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
            self.apps[app] = process
            time.sleep(0.1)
            return {
                "application": app,
                "pid": process.pid,
                "exit_code": process.poll(),
                "logs": str(log_path),
            }
        if operation == "windows":
            windows = self.toplevels.current()
            return {"windows": self.with_workspaces(windows) if host else windows}
        if operation == "focus":
            window = request.get("window")
            if not isinstance(window, str):
                raise ValueError("Focus requires a window identifier")
            focused = self.toplevels.activate(
                window, before_mutation=self.mark_mutation
            )
            return {
                "session": self.info["id"],
                "operation": operation,
                "delivered": True,
                "window": focused,
            }
        if operation == "screenshot":
            off_screen = self.host_off_screen() if host else None
            if off_screen:
                raise ScreenUnavailable(
                    f"No screenshot: {off_screen}. Tell the person, or wait until "
                    "this desktop is showing."
                )
            self.screenshot_at = time.monotonic()
            settled = None
            if request.get("settle_ms") is not None:
                quiet = request["settle_ms"]
                limit = request.get("settle_timeout_ms", 3000)
                if (
                    not all(isinstance(v, int) for v in (quiet, limit))
                    or not 0 < quiet <= 2000
                    or not quiet <= limit <= 10000
                ):
                    raise ValueError(
                        "settle_ms must be 1-2000 and settle_timeout_ms from "
                        "settle_ms to 10000"
                    )
                settled = self.settle(quiet / 1000, limit / 1000)
            elif host and self.just_acted():
                # Right after the agent's own input (a workspace switch, a new
                # window) the person's compositor is often still animating.
                settled = self.settle(0.15, 1.0)
            if request.get("changed_only") is True:
                capture = self.changed_screenshot(request.get("scale"))
            else:
                capture = self.screenshot(request.get("region"), request.get("scale"))
                if request.get("region") is None and request.get("track") is True:
                    self.seen = self.capture_pixels()  # for later changed_only
            if settled:
                capture.update(settled)
            hidden = self.host_unavailable() if host else None
            if hidden:
                capture["warning"] = (
                    f"{hidden}: the compositor may blank this capture, so it "
                    "may not show the person's windows"
                )
            # Another client's screenshot must not vouch for the controller.
            if not self.active_lease() or self.lease["holder"] == controller:
                self.needs_screenshot = False
            return capture
        if operation == "ui":
            max_nodes = request.get("max_nodes", 300)
            if not isinstance(max_nodes, int) or not 1 <= max_nodes <= 2000:
                raise ValueError("max_nodes must be an integer from 1 to 2000")
            try:
                # Checked before each element, so a person taking control
                # waits for one element's read, not the whole tree.
                tree = self.accessibility().tree(
                    request.get("app"),
                    request.get("window"),
                    max_nodes,
                    interrupt=self.take_requested,
                )
            except Interrupted:
                raise HumanControl(
                    "A person is taking control; the accessibility read was "
                    "stopped and nothing was sent. Wait with desktop_control "
                    "until control returns."
                ) from None
            for node in tree["nodes"]:
                node["id"] = self.short_id(node["id"])
            # Stay well under the protocol's response limit.
            while len(json.dumps(tree["nodes"])) > 200_000:
                del tree["nodes"][int(len(tree["nodes"]) * 0.9) :]
                tree.update(truncated=True, truncated_by="size limit")
            return tree
        if operation == "ui_action":
            if request.get("observation") is not None:
                self.check_observation(request["observation"])
            if not isinstance(request.get("action"), str) or not request["action"]:
                raise ValueError(
                    "ui_action needs an action name: press, focus, set_text or a "
                    "listed action"
                )
            accessibility = self.accessibility()
            node = request.get("node")
            if isinstance(node, str) and re.fullmatch(r"n[0-9]+", node):
                if node not in self.ui_ids:
                    raise ValueError("Unknown or expired UI node id; list the UI again")
                node = self.ui_ids[node]
            prior_mutation = getattr(self, "mutation_started", False)
            try:
                return {
                    **accessibility.act(
                        node,
                        request.get("action"),
                        request.get("text"),
                        before_mutation=self.mark_mutation,
                    ),
                    "node": request["node"],
                }
            except Unsupported as error:
                # Explicit unsupported-method replies establish that attempt
                # did not execute; retain any earlier mutation in this request.
                self.mutation_started = prior_mutation
                if request["action"] != "set_text":
                    # Nothing was sent; say why instead of guessing other input.
                    raise ValueError(str(error)) from None
                # e.g. Chromium: focus the field, verify, then replace by typing.
                accessibility.focus(node, before_mutation=self.mark_mutation)
                self.mark_mutation()
                self.keyboard().key(self.keysyms.resolve("a"), ["ctrl"], 1)
                self.keyboard().type(request["text"])
                return {
                    "node": request["node"],
                    "action": "set_text",
                    "delivered": True,
                    "method": "keyboard",
                }
        if operation == "browser":
            return self.browser_request(request)
        if operation == "set":
            from . import atlas

            # Through the worker, so the lease and a person's control apply.
            return atlas.apply(
                self.env["HOME"],
                request.get("app"),
                request.get("control"),
                request.get("atlas"),
                before_mutation=self.mark_mutation,
            )
        if operation == "effects":
            if not self.effects:
                raise ValueError(
                    "Effects are off; create the session with AGENT_DESKTOP_EFFECTS=1"
                )
            if request.get("match") is not None:
                return {
                    "matched": self.effects.matches(
                        request.get("effect_id"), request["match"]
                    )
                }
            return self.effects.since(request.get("effect_id"))
        if operation == "observe":
            return {"observation": self.observation()}
        if operation == "frame":
            return self.frame(request.get("since"))
        if operation in INPUT_OPERATIONS and request.get("observation") is not None:
            self.check_observation(request["observation"])
        if operation == "scroll":
            dx, dy = request.get("dx", 0), request.get("dy", 0)
            if not all(
                isinstance(v, int) and not isinstance(v, bool) and abs(v) <= 100
                for v in (dx, dy)
            ):
                raise ValueError(
                    "Scroll amounts are wheel notches: integers between -100 and 100"
                )
            if request.get("x") is not None or request.get("y") is not None:
                # Validate the whole request before moving the pointer.
                self.handle({**request, "operation": "move"})
        if operation in ("click", "move", "drag"):
            button = request.get("button", "left")
            if button not in BUTTONS:
                raise ValueError("Unsupported mouse button")
            names = ("x", "y", "to_x", "to_y") if operation == "drag" else ("x", "y")
            values = [request.get(name) for name in names]
            if not all(
                isinstance(v, (int, float))
                and not isinstance(v, bool)
                and math.isfinite(v)
                for v in values
            ):
                raise ValueError("Coordinates must be finite numbers")
            # A cropped or scaled screenshot's token makes x/y image coordinates.
            origin_x, origin_y, factor = token_mapping(request.get("observation"))
            points = [
                (
                    round(origin_x + values[i] / factor),
                    round(origin_y + values[i + 1] / factor),
                )
                for i in (0, len(values) - 2)
            ]
            pointer = self.pointer()
            for point in points:
                pointer.check(*point)
            self.mark_mutation()
            if operation == "drag":
                self.drag(pointer, points[0], points[1], button)
            else:
                pointer.move(*points[0])
                if operation == "click":
                    pointer.sync()
                    pointer.button(button, True)
                    pointer.button(button, False)
            pointer.sync()
        elif operation == "type":
            text = request.get("text")
            if not isinstance(text, str) or len(text) > 10000:
                raise ValueError("Text must be a string of at most 10000 characters")
            self.settle_after("key", host)
            # Characters and Tab/Return runs are sent separately, each after the
            # screen settles, so a Tab cannot overtake the text before or after it.
            typed = 0
            nested, warning = self.nested_layout()
            missing = 0
            for index, part in enumerate(re.findall(r"[\t\n]+|[^\t\n]+", text)):
                if index and not host:
                    self.settle()
                keyboard = self.keyboard()
                # Sent in chunks, so a person taking control waits for one
                # chunk rather than the whole text.
                for start in range(0, len(part), TYPE_CHUNK):
                    if self.take_requested():
                        if not typed:
                            raise HumanControl(TAKEN_OVER)
                        raise TakenOver(
                            f"Typing stopped after {typed} of {len(text)} "
                            "characters; the rest was not sent. " + TAKEN_OVER
                        )
                    self.mark_mutation()
                    chunk = part[start : start + TYPE_CHUNK]
                    if nested:
                        missing += keyboard.type(chunk, nested)
                    else:
                        keyboard.type(chunk)
                    typed += len(chunk)
            self.last_keys = ("type", time.monotonic())
            if nested and missing and not warning:
                warning = (
                    f"{missing} characters have no key in the nested Hyprland's "
                    "layout and were sent as US keys; verify the result."
                )
        elif operation == "key":
            key = request.get("key")
            modifiers = request.get("modifiers", [])
            if isinstance(key, str) and "+" in key[1:] and isinstance(modifiers, list):
                # Chord syntax: "ctrl+t", "ctrl+shift+Tab".
                *named, key = key.split("+")
                modifiers = [*modifiers, *named]
            if not isinstance(key, str) or not re_key(key):
                raise ValueError(
                    f"Invalid key name {key!r}: use an XKB keysym such as Return, "
                    "Tab, Escape or t, with modifiers (ctrl, alt, shift, logo) or "
                    'chord syntax such as "ctrl+t"'
                )
            if isinstance(modifiers, list):
                modifiers = [
                    CHORD_MODIFIERS.get(m.lower(), m.lower())
                    if isinstance(m, str)
                    else m
                    for m in modifiers
                ]
            if not isinstance(modifiers, list) or any(
                m not in ("ctrl", "alt", "shift", "logo") for m in modifiers
            ):
                raise ValueError("Modifiers must be ctrl, alt, shift or logo")
            repeat = request.get("repeat", 1)
            if (
                not isinstance(repeat, int)
                or isinstance(repeat, bool)
                or not (1 <= repeat <= 100)
            ):
                raise ValueError("Repeat must be an integer from 1 to 100")
            self.settle_after("type", host)
            keyboard = self.keyboard()
            keysym = self.keysyms.resolve(key)
            layout, warning = self.bind_layout()
            self.mark_mutation()
            keyboard.key(keysym, modifiers, repeat, layout)
            self.last_keys = ("key", time.monotonic())
        elif operation in ("key_down", "key_up"):
            key = request.get("key")
            if isinstance(key, str):
                name = CHORD_MODIFIERS.get(key.lower(), key)
                key = HELD_MODIFIERS.get(name, name)
            if not isinstance(key, str) or not re_key(key):
                raise ValueError(
                    f"Invalid key name {key!r}: use an XKB keysym such as Tab or "
                    "Super_L, or a modifier name (ctrl, alt, shift, logo)"
                )
            keyboard = self.keyboard()
            keysym = self.keysyms.resolve(key)
            layout, warning = self.bind_layout()
            if operation == "key_down":
                self.settle_after("key", host)
                self.mark_mutation()
                keyboard.down(keysym, layout)
                self.held_since = time.monotonic()
            else:
                self.mark_mutation()
                keyboard.up(keysym, layout)
                if not keyboard.held:
                    self.held_since = None
                self.last_keys = ("key", time.monotonic())
        elif operation == "scroll":
            pointer = self.pointer()
            self.mark_mutation()
            pointer.scroll(dy, dx)
            pointer.sync()
        else:
            raise ValueError(f"Unsupported operation: {operation}")
        reply = {"session": self.info["id"], "operation": operation, "delivered": True}
        return {**reply, "warning": warning} if warning else reply

    def nested_layout(self):
        """(layout, warning) of a Hyprland nested in this private session.

        Keys reach a nested compositor as codes and it reads them through its own
        layout, whatever keymap this session's compositor has. Only while that
        compositor's window has focus; (None, None) otherwise.
        """
        focused = self.focused_window()
        if (
            self.info["mode"] == "host"
            or not isinstance(focused, dict)
            or focused["app_id"] != "aquamarine"
        ):
            return None, None
        now = time.monotonic()
        if self.nested_layout_cache and now < self.nested_layout_cache[0]:
            return self.nested_layout_cache[1:]
        try:
            environment = self.nested_hyprland()
            if environment is None:
                result = None, None
            else:
                env = {**self.env, **environment}
                if self.hyprland_option("kb_file", env):
                    raise WaylandError("input:kb_file layouts are not read")
                devices = json.loads(
                    subprocess.run(
                        ["hyprctl", "-j", "devices"],
                        env=env,
                        capture_output=True,
                        timeout=2,
                        check=True,
                    ).stdout
                )
                keyboard = next(k for k in devices["keyboards"] if k.get("main"))
                index = keyboard.get("active_layout_index", 0)

                def nth(value):
                    parts = value.split(",")
                    return parts[index] if index < len(parts) else ""

                result = (
                    BindLayout(
                        self.keysyms.library,
                        typing=True,
                        rules=self.hyprland_option("kb_rules", env),
                        model=keyboard["model"],
                        layout=nth(keyboard["layout"]),
                        variant=nth(keyboard["variant"]),
                        options=keyboard["options"],
                    ),
                    None,
                )
        except (
            OSError,
            ValueError,
            KeyError,
            StopIteration,
            WaylandError,
            subprocess.SubprocessError,
        ):
            result = (
                None,
                (
                    "Could not read the nested Hyprland's keyboard layout, so keys "
                    "use US positions and may arrive as other characters. Verify "
                    "the result."
                ),
            )
        self.nested_layout_cache = (now + BIND_LAYOUT_SECONDS, *result)
        return result

    def nested_hyprland(self):
        """XDG_RUNTIME_DIR and instance signature of a Hyprland this session
        started, or None. The lock file in the instance directory names its pid."""
        for pid in session_processes(self.info["token"]):
            # comm is truncated to 15 characters: ".Hyprland-wrapp" on Nix.
            if "Hyprland" not in (command_name(pid) or ""):
                continue
            try:
                environment = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
                runtime = next(
                    v[16:].decode()
                    for v in environment
                    if v.startswith(b"XDG_RUNTIME_DIR=")
                )
                for lock in Path(runtime, "hypr").glob("*/hyprland.lock"):
                    if int(lock.read_text().split()[0]) == pid:
                        return {
                            "XDG_RUNTIME_DIR": runtime,
                            "HYPRLAND_INSTANCE_SIGNATURE": lock.parent.name,
                        }
            except (OSError, ValueError, IndexError, StopIteration):
                continue
        return None

    def bind_layout(self):
        """(layout shortcuts resolve through, warning), for Hyprland hosts.

        (None, None) elsewhere, or when Hyprland resolves shortcuts through each
        keyboard's own keymap and the virtual keyboard's positions already match.
        """
        if self.info["mode"] != "host" or not self.env.get(
            "HYPRLAND_INSTANCE_SIGNATURE"
        ):
            return self.nested_layout()
        now = time.monotonic()
        if self.bind_layout_cache and now < self.bind_layout_cache[0]:
            return self.bind_layout_cache[1:]
        try:
            options = {
                name: self.hyprland_option(name)
                for name in (
                    "resolve_binds_by_sym",
                    "kb_file",
                    *("kb_rules", "kb_model", "kb_layout", "kb_variant", "kb_options"),
                )
            }
            if options["resolve_binds_by_sym"]:
                result = None, None
            elif options["kb_file"]:
                raise WaylandError("input:kb_file layouts are not read")
            else:
                result = (
                    BindLayout(
                        self.keysyms.library,
                        rules=options["kb_rules"],
                        model=options["kb_model"],
                        layout=options["kb_layout"],
                        variant=options["kb_variant"],
                        options=options["kb_options"],
                    ),
                    None,
                )
        except (
            OSError,
            ValueError,
            KeyError,
            WaylandError,
            subprocess.SubprocessError,
        ):
            result = (
                None,
                (
                    "Could not read Hyprland's keyboard layout, so shortcuts use US key "
                    "positions and may fire the wrong bind. Verify the result."
                ),
            )
        self.bind_layout_cache = (now + BIND_LAYOUT_SECONDS, *result)
        return result

    def with_workspaces(self, windows):
        """Windows with their Hyprland workspace, matched by app id and title.

        Toplevels and Hyprland clients share no identifier, so identical windows
        on different workspaces are left without one.
        """
        if not self.env.get("HYPRLAND_INSTANCE_SIGNATURE"):
            return windows
        try:
            clients = json.loads(
                subprocess.run(
                    ["hyprctl", "-j", "clients"],
                    env=self.env,
                    capture_output=True,
                    timeout=2,
                    check=True,
                ).stdout
            )
            places = {}
            for client in clients:
                key = client["class"], client["title"]
                places.setdefault(key, set()).add(client["workspace"]["name"])
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            return windows
        result = []
        for window in windows:
            found = places.get((window["app_id"], window["title"]), ())
            one = {"workspace": next(iter(found))} if len(found) == 1 else {}
            result.append({**window, **one})
        return result

    def hyprland_option(self, name, env=None):
        """One input: option's value; an unset string reads as empty."""
        reply = json.loads(
            subprocess.run(
                ["hyprctl", "-j", "getoption", f"input:{name}"],
                env=env or self.env,
                capture_output=True,
                timeout=2,
                check=True,
            ).stdout
        )
        for field in ("str", "bool", "int"):
            if field in reply:
                return "" if reply[field] == "[[EMPTY]]" else reply[field]
        raise KeyError(name)

    def release_held_keys(self):
        self.held_since = None
        if self.virtual_keyboard and self.virtual_keyboard.held:
            try:
                self.virtual_keyboard.release_all()
            except (OSError, WaylandError):
                self.virtual_keyboard.held.clear()

    def serve(self):
        endpoint = self.info["control_socket"]
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(endpoint)
            server.listen(16)
            server.settimeout(0.5)
            if self.info.get("runtime"):
                Path(self.info["runtime"], TAKE_REQUESTED).unlink(missing_ok=True)
            self.save("ready", worker_pid=os.getpid(), guardian_pid=os.getppid())
            while not self.stop:
                if (
                    self.info.get("expires_at")
                    and time.time() >= self.info["expires_at"]
                ):
                    print("Host session expired", file=sys.stderr, flush=True)
                    break
                self.trim_logs()
                reap_orphans(self.tracked())
                # Collect exited applications, so they do not stay as zombies
                # that still look alive to a pid check.
                for process in self.apps.values():
                    process.poll()
                if self.compositor.poll() is not None:
                    raise RuntimeError("Private compositor crashed")
                if (
                    self.control["owner"] == "human"
                    and self.takeover
                    and self.takeover.poll() is not None
                    and "release_error" not in self.control
                ):
                    try:
                        self.release("viewer disconnected")
                    except RuntimeError:
                        pass  # recorded in the control state; the person decides
                if (
                    self.held_since is not None
                    and time.monotonic() - self.held_since > KEY_HOLD_SECONDS
                ):
                    self.release_held_keys()
                try:
                    connection, _ = server.accept()
                except TimeoutError:
                    continue
                trace = None
                with connection:
                    self.mutation_started = False
                    connection.settimeout(5)
                    try:
                        with connection.makefile("rb") as stream:
                            line = stream.readline(262145)
                        if len(line) > 262144:
                            raise ValueError("Request too large")
                        request = json.loads(line)
                        trace = self.trace_start(request)
                        started = time.monotonic()
                        result = self.handle_with_effects(request)
                        if self.activity and request.get("operation") in (
                            *INPUT_OPERATIONS,
                            "focus",
                        ):
                            # Activity during our own input is not the person's.
                            self.agent_input = [
                                *self.agent_input[-49:],
                                (started, time.monotonic()),
                            ]
                        reply = {"ok": True, "result": result}
                    except Exception as error:
                        reply = self.error_reply(error)
                    self.trace_finish(trace, reply)
                    trace = None
                    encoded = (json.dumps(reply) + "\n").encode()
                    if len(encoded) > 262144:
                        # A clear error instead of a reply the client cannot read.
                        encoded = (
                            json.dumps(
                                {
                                    "ok": False,
                                    "uncertain": True,
                                    "error": "Response exceeds the protocol limit "
                                    "after execution; delivery may have occurred. "
                                    "Reconcile before retrying, then narrow reads.",
                                }
                            )
                            + "\n"
                        ).encode()
                    try:
                        connection.sendall(encoded)
                    except OSError:
                        pass

    def focused_window(self):
        try:
            for window in self.toplevels.current():
                if "activated" in window["states"]:
                    return {"id": window["id"], "app_id": window["app_id"]}
        except Exception:  # the trace must never break a request
            return "unknown"
        return None

    def trace_start(self, request):
        """Begin a trace record (AGENT_DESKTOP_TRACE=0 disables the trace)."""
        operation = request.get("operation") if isinstance(request, dict) else None
        if (
            operation not in TRACED_OPERATIONS
            or os.environ.get("AGENT_DESKTOP_TRACE") == "0"
            or self.toplevels is None
        ):
            return None
        return {
            "at": round(time.time(), 3),
            "started": time.monotonic(),
            "operation": operation,
            "controller": request.get("controller"),
            "owner": self.control["owner"],
            "arguments": trace_arguments(request),
            "focus_before": self.focused_window(),
        }

    def trace_finish(self, trace, reply):
        if trace is None:
            return
        started = trace.pop("started")
        trace["ms"] = round((time.monotonic() - started) * 1000, 1)
        trace["focus_after"] = self.focused_window()
        if reply["ok"]:
            result = reply["result"] if isinstance(reply["result"], dict) else {}
            trace["outcome"] = {
                key: result[key]
                for key in ("delivered", "observation", "path", "pid")
                if key in result
            }
            if result.get("uncertain"):
                trace["outcome"]["uncertain"] = True
            if isinstance(result.get("total"), int) and "stopped" in result:
                trace["outcome"]["completed"] = result.get("completed")
                trace["outcome"]["total"] = result["total"]
                if isinstance(result["stopped"], dict):
                    trace["outcome"]["stopped"] = stop_reason(result["stopped"])
        else:
            trace["error"] = reply["error"][:300]
        path = self.root / "trace.jsonl"
        try:
            with path.open("a") as stream:
                stream.write(json.dumps(trace) + "\n")
            if path.stat().st_size > TRACE_BYTES:
                # Keep the newer half, starting at a whole record.
                data = path.read_bytes()[-TRACE_BYTES // 2 :]
                path.write_bytes(data[data.find(b"\n") + 1 :])
        except OSError:
            pass

    def trim_logs(self):
        for path in self.root.glob("*.log"):
            if path.stat().st_size > 1024 * 1024:
                with path.open("r+b") as stream:
                    stream.seek(-512 * 1024, 2)
                    tail = stream.read()
                    stream.seek(0)
                    stream.write(tail)
                    stream.truncate()

    def stop_applications(self, timeout=3):
        """Ask launched applications to exit while their display still exists.

        Browsers save state such as cookies when their windows close, but exit
        abruptly when the compositor disappears first.
        """
        running = [p for p in self.apps.values() if p.poll() is None]
        if not running:
            return
        try:
            # Closing windows lets applications shut down as if a person quit them;
            # one waiting on a dialog (e.g. unsaved changes) is terminated below.
            self.toplevels.close_all(timeout=3)
        except (OSError, RuntimeError):
            pass
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and any(p.poll() is None for p in running):
            reap_orphans(self.tracked())
            time.sleep(0.05)
        # Only the launched process: signalling its whole group would stop helpers
        # (e.g. Chromium's zygote) that it needs for an orderly shutdown.
        for process in running:
            process.terminate()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and any(p.poll() is None for p in running):
            reap_orphans(self.tracked())
            time.sleep(0.05)

    def cleanup_host(self):
        """Release the person's desktop: never close their windows."""
        if self.browser:
            # Ends the BiDi session; Firefox keeps it after a dropped connection.
            self.browser[0].close()
            self.browser = None
        for device in (
            self.virtual_pointer,
            self.virtual_keyboard,
            self.toplevels,
            self.activity,
        ):
            if device:
                device.close()
        if self.awake and self.awake.poll() is None:
            self.awake.terminate()
            try:
                self.awake.wait(5)
            except subprocess.TimeoutExpired:
                self.awake.kill()
        try:
            cleanup_processes(self.info["token"], self.tracked())
        finally:
            reap_orphans(self.tracked())
        shutil.rmtree(self.info["runtime"], ignore_errors=True)
        notify("The agent stopped using your screen", "Host session ended.", self.env)

    def cleanup(self):
        self.release_held_keys()
        if self.info["mode"] == "host":
            return self.cleanup_host()
        if self.toplevels and self.compositor and self.compositor.poll() is None:
            self.stop_applications()
        if self.effects:
            self.effects.close()
        if self.browser:
            self.browser[0].close()
        for device in (
            self.virtual_pointer,
            self.virtual_keyboard,
            self.toplevels,
            self.atspi,
        ):
            if device:
                device.close()
        if self.compositor and self.compositor.poll() is None:
            try:
                self.command("labwc", "-e", timeout=3)
                self.compositor.wait(timeout=3)
            except (RuntimeError, subprocess.SubprocessError):
                pass
        try:
            # Applications exit before their session bus disappears.
            spare = [self.bus.pid] if self.bus else []
            cleanup_processes(self.info["token"], self.tracked(), spare)
        finally:
            for process in (self.bus, self.compositor, self.viewer, self.takeover):
                if process:
                    process.poll()
            for process in self.apps.values():
                process.poll()
            reap_orphans(self.tracked())
        shutil.rmtree(self.info["runtime"])
        for name in ("home", "config"):
            shutil.rmtree(self.root / name, ignore_errors=True)


def write_private(path, text):
    """Write a file only the user can read (the manifest holds the session token)."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(text)
    os.chmod(path, 0o600)


def write_manifest(root, info):
    temporary = root / "session.json.tmp"
    write_private(temporary, json.dumps(info, indent=2) + "\n")
    temporary.replace(root / "session.json")


def remove_session_files(root, runtime):
    shutil.rmtree(runtime, ignore_errors=True)
    (root / LINEAGE_FILE).unlink(missing_ok=True)
    for name in ("home", "config"):
        shutil.rmtree(root / name, ignore_errors=True)


def image_token(layout, region, scale):
    """Observation token; cropped or scaled captures append their mapping."""
    x, y = region[:2]
    if (x, y) == (0, 0) and not scale:
        return layout
    return f"{layout}@{x},{y},{scale or 1}"


def token_mapping(token):
    """(origin x, origin y, scale) for image coordinates relative to a token."""
    if not isinstance(token, str) or "@" not in token:
        return 0, 0, 1
    try:
        x, y, scale = token.partition("@")[2].split(",")
        mapping = int(x), int(y), float(scale)
    except ValueError:
        raise ValueError("Malformed observation token") from None
    if not 0.1 <= mapping[2] <= MAX_CROP_SCALE:
        raise ValueError("Malformed observation token")
    return mapping


def first_difference(a, b):
    """Index of the first differing byte of equal-length bytes (binary search)."""
    low, high = 0, len(a)
    while high - low > 1:
        middle = (low + high) // 2
        if a[low:middle] != b[low:middle]:
            high = middle
        else:
            low = middle
    return low


# Changes of at most this many square pixels (a blinking caret) count as settled.
SETTLE_AREA = 400


# changed_only screenshots: context around the change, and the share of the
# screen above which the whole frame is sent instead.
CHANGED_MARGIN = 48
CHANGED_WHOLE = 0.4


def changed_box(before, after, width, height):
    """[x, y, width, height] around every changed pixel, or False if identical."""
    if before == after:
        return False
    stride = width * 3
    top = bottom = None
    left, right = width, -1
    for row in range(height):
        start = row * stride
        a, b = before[start : start + stride], after[start : start + stride]
        if a == b:
            continue
        if top is None:
            top = row
        bottom = row
        left = min(left, first_difference(a, b) // 3)
        right = max(right, width - 1 - first_difference(a[::-1], b[::-1]) // 3)
    return [left, top, right - left + 1, bottom - top + 1]


# Host-affecting commands that panels, widgets and scripts commonly run.
GUARDED_COMMANDS = (
    "systemctl",
    "loginctl",
    "systemd-inhibit",
    "shutdown",
    "poweroff",
    "reboot",
    "halt",
    "nmcli",
    "nmtui",
    "bluetoothctl",
    "rfkill",
    "brightnessctl",
    "powerprofilesctl",
    "tailscale",
    "mullvad",
    "udisksctl",
    "pkill",
    "killall",
    "hyprctl",
    "swaymsg",
)

CREDENTIAL_NAMES = (
    "SSH_AUTH_SOCK",
    "SSH_AGENT_PID",
    "GPG_AGENT_INFO",
    "KRB5CCNAME",
    "NETRC",
    "GIT_ASKPASS",
    "SSH_ASKPASS",
    "GNOME_KEYRING_CONTROL",
)
CREDENTIAL_PREFIXES = ("AWS_", "AZURE_", "GOOGLE_APPLICATION_", "GCLOUD_", "DOCKER_")
CREDENTIAL_PARTS = (
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "API_KEY",
    "APIKEY",
    "CREDENTIAL",
)


def credential_variable(name):
    """Whether an environment variable is likely to grant access to something."""
    upper = name.upper()
    return (
        upper in CREDENTIAL_NAMES
        or upper.startswith(CREDENTIAL_PREFIXES)
        or any(part in upper for part in CREDENTIAL_PARTS)
    ) and not upper.startswith("AGENT_DESKTOP_")


def person_firefox_bridge(env):
    """The BiDi WebSocket of the person's running Firefox, if it was started
    with --remote-debugging-port (Firefox writes WebDriverBiDiServer.json into
    the profile while listening)."""
    home = Path(env.get("HOME") or Path.home())
    # MOZ_APP_DATA, when set, is where this person's Firefox keeps profiles.
    roots = (
        [env["MOZ_APP_DATA"]]
        if env.get("MOZ_APP_DATA")
        else [home / ".config/mozilla/firefox", home / ".mozilla/firefox"]
    )
    found = []
    for root in roots:
        if root and Path(root).is_dir():
            found += Path(root).glob("*/WebDriverBiDiServer.json")
    for path in sorted(found, key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        port = data.get("ws_port") or data.get("port")
        host = data.get("ws_host") or data.get("host") or "127.0.0.1"
        if isinstance(port, int) and host in ("127.0.0.1", "localhost", "::1"):
            with socket.socket() as probe:
                probe.settimeout(0.5)
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    return f"ws://127.0.0.1:{port}"
    return None


BIDI_LISTENING = re.compile(r"WebDriver BiDi listening on (ws://127\.0\.0\.1:[0-9]+)")
FIREFOX_NAMES = ("firefox", "firefox-esr", "firefox-devedition", "firefox-nightly")
# Arguments by which the caller already chose a profile (shell case patterns).
FIREFOX_PROFILE_PATTERNS = (
    "-P|-p|--P|-profile|--profile|-profile=*|--profile=*|"
    "-ProfileManager|--ProfileManager|-profilemanager|--profilemanager"
)


def host_homes(env):
    """The person's real home directories (from HOME and the password database)."""
    homes = set()
    for home in (env.get("HOME"), pwd.getpwuid(os.getuid()).pw_dir):
        if home and os.path.isabs(home):
            homes.update({os.path.normpath(home), os.path.realpath(home)})
    homes.discard("/")
    return homes


def home_variables(env, homes):
    """Inherited variables whose value is a single path inside one of `homes`.

    Search-path lists (PATH, XDG_DATA_DIRS and other colon-separated values)
    are kept; they mostly name read-only installation directories. HOME is
    replaced by the session anyway, and the project's own settings are kept.
    """
    removed = []
    for key, value in env.items():
        if (
            key == "HOME"
            or key.startswith("AGENT_DESKTOP_")
            or ":" in value
            or not os.path.isabs(value)
        ):
            continue
        paths = {os.path.normpath(value), os.path.realpath(value)}
        if any(p == h or p.startswith(h + "/") for p in paths for h in homes):
            removed.append(key)
    return sorted(removed)


SECRET_SERVICES = (
    "org.freedesktop.secrets",
    "org.gnome.keyring",
    "org.freedesktop.impl.portal.Secret",
)
REGISTRYD_PATHS = (
    "/usr/libexec/at-spi2-registryd",
    "/usr/lib/at-spi2-registryd",
    "/usr/lib/at-spi2-core/at-spi2-registryd",
    "/usr/libexec/at-spi2-core/at-spi2-registryd",
)


def find_registryd():
    override = os.environ.get("AGENT_DESKTOP_AT_SPI_REGISTRYD")
    if override:
        candidates = [override]
    else:
        # Prefixes on PATH first (Nix profiles, local installs), then system paths.
        prefixes = {
            str(Path(entry).parent)
            for entry in os.environ.get("PATH", "").split(os.pathsep)
            if entry.endswith("/bin")
        }
        candidates = [
            f"{prefix}/libexec/at-spi2-registryd" for prefix in sorted(prefixes)
        ] + list(REGISTRYD_PATHS)
    return next((c for c in candidates if c and os.access(c, os.X_OK)), None)


def command_name(pid):
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip()
    except OSError:
        return None


def re_key(key):
    return re.fullmatch(r"[A-Za-z0-9_]+", key)


def stop_process(process):
    """Terminate a child, then kill it if it has not exited within 2 s."""
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def accessibility_failure(reason, enforce=Path("/sys/fs/selinux/enforce")):
    """Why the session has no accessibility tree, with the likely cause."""
    try:
        enforcing = enforce.read_text().strip() == "1"
    except OSError:
        enforcing = False
    if enforcing:
        reason += (
            ". SELinux is enforcing, and its policy refuses to let the session's "
            "bus start at-spi-bus-launcher"
        )
    return f"Accessibility unavailable: {reason}; the semantic UI tools cannot be used"


def runtime_changed(tool, path):
    """The error when a tool the session started with has since been removed."""
    return (
        f"{tool} is no longer at {path}: the desktop runtime changed after this "
        "session started (an upgrade). Destroy the session and create a new one"
    )


def load_request_modules():
    """Import now what requests would otherwise import on first use.

    A running session then keeps the code it started with when Agent Desktop
    is upgraded or removed underneath it (an editable checkout pulled, a tool
    reinstalled), instead of mixing in the new version's modules or failing
    with an ImportError on its first browser or `set` request.
    """
    import websockets.exceptions  # noqa: F401

    from . import atlas, browser, core  # noqa: F401


def run_worker(root):
    load_request_modules()
    worker = Worker(root)

    def stop(_signal, _frame):
        worker.stop = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    failure = None
    try:
        worker.start()
        worker.serve()
    except Exception as error:
        failure = str(error)
        print(failure, file=sys.stderr, flush=True)
    finally:
        try:
            worker.cleanup()
        except Exception as error:
            failure = f"Cleanup failed: {error}"
            print(failure, file=sys.stderr, flush=True)
        worker.save("failed" if failure else "stopped", error=failure)
    return 1 if failure else 0


def guard(root, worker, handoff=None):
    """Wait for the worker; if it dies abnormally, stop everything it left behind."""
    held = []  # profile locks attached to the session after it started
    if handoff is not None:
        threading.Thread(
            target=receive_profile_locks, args=(handoff, held), daemon=True
        ).start()

    def forward(signum, _frame):
        try:
            os.kill(worker, signum)
        except ProcessLookupError:
            pass

    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)
    stop = threading.Event()
    recorder = threading.Thread(
        target=record_lineage, args=(root, os.getpid(), stop), daemon=True
    )
    recorder.start()
    _, status = os.waitpid(worker, 0)
    info = json.loads((root / "session.json").read_text())
    # The worker's orphans are now this process's children or token carriers.
    cleanup_processes(info["token"])
    stop.set()
    recorder.join()
    (root / LINEAGE_FILE).unlink(missing_ok=True)
    if info["status"] in ("stopped", "failed"):
        return 0
    if os.WIFSIGNALED(status):
        reason = f"signal {os.WTERMSIG(status)}"
    else:
        reason = f"exit status {os.waitstatus_to_exitcode(status)}"
    error = f"Supervisor exited unexpectedly ({reason}); session processes stopped"
    print(error, file=sys.stderr, flush=True)
    remove_session_files(root, info["runtime"])
    info.update(status="failed", error=error)
    write_manifest(root, info)
    return 1


# The profile lock as an open file, taken before the worker is forked. Both
# processes share it, so the kernel releases it only when both have exited: a
# worker that dies abnormally cannot free the profile while the guardian is
# still stopping the session's applications.
GUARDIAN_PROFILE_LOCK = None
# In the worker: a socket to the guardian, which receives and holds a profile
# lock attached later.
GUARDIAN_HANDOFF = None


def receive_profile_locks(sock, held):
    """Guardian thread: keep every lock descriptor the worker sends.

    A received descriptor shares the sender's open file description, and so its
    flock, until every copy is closed. Holding it here keeps the profile locked
    after the worker dies, until this process has stopped the session's
    applications and exited. It ends when the worker's end closes.
    """
    while True:
        try:
            data, fds, _, _ = socket.recv_fds(sock, 16, 4)
        except OSError:
            return
        if not data and not fds:
            return  # end of stream: the worker has exited
        held.extend(os.fdopen(fd, "a") for fd in fds)


def record_scope(root):
    """Note the session's systemd scope (AGENT_DESKTOP_SYSTEMD_SCOPE=1), so that
    recovery after both supervisors die can find every process in it."""
    info = json.loads((root / "session.json").read_text())
    cgroup = own_scope(info["id"])
    if cgroup:
        info["cgroup"] = cgroup
        write_manifest(root, info)


def take_profile_lock(root):
    info = json.loads((root / "session.json").read_text())
    if not info.get("profile_lock"):
        return None
    lock = Path(info["profile_lock"]).open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return None  # the worker reports the profile as in use
    return lock


def main():
    global GUARDIAN_PROFILE_LOCK, GUARDIAN_HANDOFF
    root = Path(sys.argv[1])
    # Both processes are subreapers: orphans stay with the worker while it lives,
    # then fall to the guardian, never to init or a host service manager.
    become_subreaper()
    record_scope(root)
    GUARDIAN_PROFILE_LOCK = take_profile_lock(root)
    guardian_end, worker_end = socket.socketpair()
    worker = os.fork()
    if worker == 0:
        code = 1
        try:
            guardian_end.close()
            GUARDIAN_HANDOFF = worker_end
            become_subreaper()  # not inherited across fork
            code = run_worker(root)
        finally:
            os._exit(code)
    worker_end.close()
    raise SystemExit(guard(root, worker, guardian_end))


if __name__ == "__main__":
    main()
