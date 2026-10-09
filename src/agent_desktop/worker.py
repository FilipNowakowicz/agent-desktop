"""One supervisor, private D-Bus and compositor per session."""

import ctypes
import fcntl
import hashlib
import json
import math
import os
import pwd
import re
import shlex
import shutil
import signal
import socket
import struct
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .atspi import Accessibility, Unsupported, wait_for_registry
from .effects import EffectLedger
from .wayland import (
    BUTTONS,
    InputActivity,
    Keysyms,
    Toplevels,
    VirtualKeyboard,
    VirtualPointer,
    clear_selection,
    peer_pid,
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


def session_process_starts(token, tree=True):
    """{pid: start time} of live session processes: token carriers, plus this
    supervisor's subtree."""
    table = process_table()
    pids = set(owned_processes(token))
    if tree:
        pids |= set(descendants(os.getpid(), table))
    # Never this supervisor or its parent (the worker's guardian).
    pids -= {os.getpid(), os.getppid()}
    return {p: table[p][2] for p in pids if p in table and table[p][1] not in "ZX"}


def session_processes(token, tree=True):
    return sorted(session_process_starts(token, tree))


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


def cleanup_processes(token, tracked=(), spare=(), tree=True):
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
                for pid, started in session_process_starts(token, tree).items()
                if pid not in excluded
            }
            if not remaining:
                break
            for pid, started in remaining - signalled:
                signalled.add((pid, started))
                signal_process(pid, started, sig)
            reap_orphans(tracked)
            time.sleep(0.05)
        if not session_processes(token, tree):
            return
    raise RuntimeError("Session processes remain after cleanup")


INPUT_OPERATIONS = ("click", "move", "drag", "scroll", "type", "key")
# Operations that change the desktop; they need the controller lease (below).
MUTATING_OPERATIONS = (
    *INPUT_OPERATIONS,
    "launch",
    "focus",
    "ui_action",
    "request_human",
    "set",
    "browser",
)
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
        kept["key"] = key if len(key) > 1 else "<character>"
    argv = request.get("argv")
    if isinstance(argv, list) and argv:
        kept["program"] = Path(str(argv[0])).name
        kept["argc"] = len(argv)
    return kept


class StaleObservation(RuntimeError):
    pass


class HumanControl(RuntimeError):
    pass


class LeaseHeld(RuntimeError):
    pass


class UserActive(RuntimeError):
    pass


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
    "browser",
)
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

    The screen locker, blanking and idle suspend wait while it is held, so input
    cannot land on a lock screen. It ends with this worker even if the worker is
    killed. AGENT_DESKTOP_HOST_KEEP_AWAKE=0 disables it.
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
        self.atspi = None
        self.ui_ids, self.ui_names = {}, {}  # short id <-> AT-SPI bus name + path
        self.ui_counter = 0
        self.frames = {}  # recent raw frames for change detection, oldest first
        # ("type" or "key", monotonic end) of the last keyboard input.
        self.last_keys = (None, 0.0)
        self.virtual_pointer = None
        self.virtual_keyboard = None
        self.toplevels = None
        self.effects = None
        self.keysyms = None
        self.browser = None  # (BiDi connection, Firefox pid) once started
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
        result = subprocess.run(
            [self.info["tools"][tool], *map(str, arguments)],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
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
            "stop it with: agent-desktop host stop",
            self.env,
        )

    def user_active(self):
        """Whether the person used the computer recently (host sessions)."""
        now = time.monotonic()
        ours = self.agent_input
        theirs = [
            moment
            for moment in self.activity.resumed_at
            if not any(start - 0.05 <= moment <= end + 0.5 for start, end in ours)
        ]
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
        result = subprocess.run(
            launcher, env=self.env, capture_output=True, text=True, timeout=10
        )
        if result.returncode:
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
            "</keyboard></labwc_config>\n"
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
                "WLR_RENDERER": "pixman",
                "WLR_HEADLESS_OUTPUTS": "1",
                "WLR_WL_OUTPUTS": "1",
                "WLR_LIBINPUT_NO_DEVICES": "1",
                "XKB_DEFAULT_LAYOUT": "us",
                # Software sessions: GTK 4 would otherwise try Vulkan/GL on the
                # host GPU, which left layer-shell panels blank in a trial.
                "GSK_RENDERER": os.environ.get("AGENT_DESKTOP_GSK_RENDERER", "cairo"),
            }
        )
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
        for name in GUARDED_COMMANDS:
            shim = directory / name
            shim.write_text(
                "#!/bin/sh\n"
                f'printf "%s blocked: {name}" "$(date +%s)" >> "{log}"\n'
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

    def start_registry(self, registryd):
        # D-Bus activation of the registry fails without a systemd user session.
        with (self.root / "accessibility.log").open("ab") as log:
            self.registry = subprocess.Popen(
                [registryd],
                env=self.env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
            )
        wait_for_registry(self.env["DBUS_SESSION_BUS_ADDRESS"])

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

    def start_browser(self, url):
        """Firefox with WebDriver BiDi on a free localhost port: the bridged one,
        one started in the session with --remote-debugging-port, or a new one."""
        from . import browser

        if self.browser and self.browser[1].poll() is None:
            return self.browser[0]
        if self.browser:
            self.browser[0].close()
            self.browser = None
        # A Firefox launched in this session with --remote-debugging-port.
        for app, process in self.apps.items():
            log = self.root / f"app-{app}.log"
            if process.poll() is None and log.exists():
                found = BIDI_LISTENING.search(log.read_text(errors="replace"))
                if found:
                    self.browser = (browser.Browser(found.group(1)), process)
                    if url:
                        self.browser[0].command(
                            "browsingContext.navigate",
                            {"context": self.browser[0].target(), "url": url},
                        )
                    return self.browser[0]
        started = self.handle(
            {
                "operation": "launch",
                "argv": ["firefox", "--remote-debugging-port=0", url or "about:blank"],
            }
        )
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
        self.browser = (browser.Browser(found.group(1)), process)
        return self.browser[0]

    def browser_request(self, request):
        """Read and act on pages of a private Firefox through WebDriver BiDi."""
        from websockets.exceptions import ConnectionClosed

        from . import browser

        action = request.get("action")
        target = {
            "selector": request.get("selector"),
            "text": request.get("text"),
            "exact": request.get("exact") is True,
        }
        try:
            if action == "start":
                bridge = self.start_browser(request.get("url"))
                return {"tabs": bridge.tabs()[1]}
            if not self.browser or self.browser[1].poll() is not None:
                raise ValueError('No bridged Firefox; use action "start" first')
            bridge = self.browser[0]
            context = bridge.target(request.get("tab"))
            if action == "tabs":
                return {"tabs": bridge.tabs()[1]}
            if action == "open":
                url = request.get("url")
                if not isinstance(url, str) or not url:
                    raise ValueError("open needs a url")
                if request.get("new_tab"):
                    context = bridge.command("browsingContext.create", {"type": "tab"})[
                        "context"
                    ]
                    bridge.context = context
                bridge.command(
                    "browsingContext.navigate",
                    {"context": context, "url": url, "wait": "complete"},
                    timeout=60,
                )
                return self.page_state(bridge, context)
            if action == "find":
                return bridge.find(context, **target)
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
                }
            if action == "wait":
                timeout = request.get("timeout", 10)
                if not isinstance(timeout, (int, float)) or not 0 <= timeout <= 60:
                    raise ValueError("timeout must be between 0 and 60 seconds")
                gone = request.get("gone") is True
                deadline = time.monotonic() + timeout
                while True:
                    found = bridge.find(context, **target)
                    if bool(found["count"]) != gone:
                        return {"satisfied": True, **found}
                    if time.monotonic() >= deadline:
                        return {"satisfied": False, **found}
                    time.sleep(0.2)
            if action in ("click", "fill", "select"):
                element, described = bridge.element(context, **target)
                if described.get("disabled"):
                    raise ValueError(f"The element is disabled: {described}")
                if action == "click":
                    bridge.click(context, element)
                elif action == "fill":
                    value = request.get("value")
                    if not isinstance(value, str) or len(value) > 2000:
                        raise ValueError(
                            "fill needs a value of at most 2000 characters"
                        )
                    bridge.click(context, element)
                    bridge.keys(context, value, select_all=True)
                else:
                    option = request.get("value")
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
                after = bridge.call(
                    "(e) => e.isConnected ? JSON.stringify({value: e.type === "
                    "'password' ? undefined : e.value, checked: e.checked}) : null",
                    [element],
                    context,
                )
                result = {
                    "element": described,
                    "delivered": True,
                    **self.page_state(bridge, context),
                }
                after = browser.remote_value(after)
                if isinstance(after, str):
                    result["now"] = {
                        k: v for k, v in json.loads(after).items() if v is not None
                    }
                return result
            raise ValueError(
                "action must be start, tabs, open, find, text, wait, click, fill "
                "or select"
            )
        except browser.BrowserError as error:
            raise ValueError(str(error)) from None
        except ConnectionClosed:
            self.browser = None
            raise ValueError("Firefox closed the bridge; start it again") from None

    def page_state(self, bridge, context):
        from . import browser

        state = bridge.call(
            "() => JSON.stringify({url: location.href, title: document.title})",
            [],
            context,
        )
        return json.loads(browser.remote_value(state))

    def accessibility(self):
        if not self.info.get("accessibility"):
            raise RuntimeError(
                "Accessibility unavailable: install at-spi2-core or set "
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
            self.registry,
            self.compositor,
            self.viewer,
            self.takeover,
            *self.apps.values(),
        ]
        return {p.pid for p in processes if p}

    def screenshot(self, region=None, scale=None):
        self.virtual_pointer.connection.roundtrip()
        output = self.virtual_pointer.output
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
            if (
                not isinstance(scale, (int, float))
                or isinstance(scale, bool)
                or not 0.1 <= scale <= 1
            ):
                raise ValueError("Scale must be between 0.1 and 1")
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
        result = subprocess.run(
            [self.info["tools"]["grim"], "-t", "ppm", "-"],
            env=self.env,
            capture_output=True,
            timeout=10,
        )
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
        layout = [
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
            "take_command": f"agent-desktop take {self.info['id']}",
            # Sends the host clipboard in once, e.g. a password-manager entry.
            "paste_command": f"agent-desktop take --paste {self.info['id']}",
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

    def take(self, wayvnc, keyboard=None):
        endpoint = Path(self.info["runtime"]) / "takeover.sock"
        if keyboard is not None and (
            not isinstance(keyboard, str) or not KEYBOARD.fullmatch(keyboard)
        ):
            raise ValueError("Keyboard must look like us or us-dvorak")
        if self.control["owner"] != "human":
            self.takeover = self.start_vnc(
                wayvnc,
                endpoint,
                "takeover-control.sock",
                interactive=True,
                keyboard=keyboard,
            )
            self.control["keyboard"] = keyboard
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

    def handle(self, request):
        operation = request["operation"]
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
        if host and operation in (*INPUT_OPERATIONS, "focus") and self.user_active():
            raise UserActive(
                "The person is using the computer; nothing was sent. Wait a few "
                "seconds (desktop_wait with seconds) and try again."
            )
        # destroy, take, release and viewer_start stay available to everyone:
        # they are lifecycle and person controls, never agent input.
        self.check_lease(operation, controller)
        if operation == "status":
            return {
                "session": self.info["id"],
                "mode": self.info["mode"],
                "status": "ready",
                "accessibility": self.info.get("accessibility", False),
                "secret_service": self.info.get("secret_service", True),
                "guard_host": bool(self.info.get("guard_host")),
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
        if operation == "viewer_start":
            endpoint = Path(self.info["runtime"]) / "vnc.sock"
            if not (self.viewer and self.viewer.poll() is None):
                self.viewer = self.start_vnc(
                    request.get("wayvnc", "wayvnc"), endpoint, "vnc-control.sock"
                )
            return {"socket": str(endpoint), "read_only": True}
        if operation == "control":
            return self.control_state()
        if operation == "request_human":
            reason = request.get("reason")
            if not isinstance(reason, str) or not 0 < len(reason.strip()) <= 500:
                raise ValueError(
                    "Reason must be a nonempty string of at most 500 characters"
                )
            self.control["request"] = {"reason": reason.strip(), "at": time.time()}
            self.save_control()
            return self.control_state()
        if operation == "take":
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
            return {"windows": self.toplevels.current()}
        if operation == "focus":
            window = request.get("window")
            if not isinstance(window, str):
                raise ValueError("Focus requires a window identifier")
            focused = self.toplevels.activate(window)
            return {
                "session": self.info["id"],
                "operation": operation,
                "delivered": True,
                "window": focused,
            }
        if operation == "screenshot":
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
            capture = self.screenshot(request.get("region"), request.get("scale"))
            if settled:
                capture.update(settled)
            # Another client's screenshot must not vouch for the controller.
            if not self.active_lease() or self.lease["holder"] == controller:
                self.needs_screenshot = False
            return capture
        if operation == "ui":
            max_nodes = request.get("max_nodes", 300)
            if not isinstance(max_nodes, int) or not 1 <= max_nodes <= 2000:
                raise ValueError("max_nodes must be an integer from 1 to 2000")
            tree = self.accessibility().tree(
                request.get("app"), request.get("window"), max_nodes
            )
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
            try:
                return {
                    **accessibility.act(
                        node, request.get("action"), request.get("text")
                    ),
                    "node": request["node"],
                }
            except Unsupported:
                # e.g. Chromium: focus the field, verify, then replace by typing.
                accessibility.focus(node)
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
            for index, part in enumerate(re.findall(r"[\t\n]+|[^\t\n]+", text)):
                if index and not host:
                    self.settle()
                self.keyboard().type(part)
            self.last_keys = ("type", time.monotonic())
        elif operation == "key":
            key = request.get("key")
            modifiers = request.get("modifiers", [])
            if not isinstance(key, str) or not re_key(key):
                raise ValueError("Invalid key name")
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
            self.keyboard().key(self.keysyms.resolve(key), modifiers, repeat)
            self.last_keys = ("key", time.monotonic())
        elif operation == "scroll":
            dx, dy = request.get("dx", 0), request.get("dy", 0)
            if not all(
                isinstance(v, int) and not isinstance(v, bool) and abs(v) <= 100
                for v in (dx, dy)
            ):
                raise ValueError(
                    "Scroll amounts are wheel notches: integers between -100 and 100"
                )
            pointer = self.pointer()
            pointer.scroll(dy, dx)
            pointer.sync()
        else:
            raise ValueError(f"Unsupported operation: {operation}")
        return {"session": self.info["id"], "operation": operation, "delivered": True}

    def serve(self):
        endpoint = self.info["control_socket"]
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(endpoint)
            server.listen(16)
            server.settimeout(0.5)
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
                try:
                    connection, _ = server.accept()
                except TimeoutError:
                    continue
                trace = None
                with connection:
                    connection.settimeout(5)
                    try:
                        with connection.makefile("rb") as stream:
                            line = stream.readline(262145)
                        if len(line) > 262144:
                            raise ValueError("Request too large")
                        request = json.loads(line)
                        trace = self.trace_start(request)
                        started = time.monotonic()
                        effects = (
                            self.effects.begin()
                            if self.effects
                            and request.get("operation") in EFFECT_OPERATIONS
                            and self.control["owner"] == "agent"
                            else None
                        )
                        result = self.handle(request)
                        if effects and isinstance(result, dict):
                            result["effects"] = self.effects.finish(effects)
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
                        reply = {
                            "ok": False,
                            "error": f"{type(error).__name__}: {error}",
                        }
                    self.trace_finish(trace, reply)
                    trace = None
                    encoded = (json.dumps(reply) + "\n").encode()
                    if len(encoded) > 262144:
                        # A clear error instead of a reply the client cannot read.
                        encoded = (
                            json.dumps(
                                {
                                    "ok": False,
                                    "error": "ValueError: response exceeds the "
                                    "protocol limit; narrow the request",
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


def write_manifest(root, info):
    temporary = root / "session.json.tmp"
    temporary.write_text(json.dumps(info, indent=2) + "\n")
    temporary.replace(root / "session.json")


def remove_session_files(root, runtime):
    shutil.rmtree(runtime, ignore_errors=True)
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
    if not 0.1 <= mapping[2] <= 1:
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


def run_worker(root):
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


def guard(root, worker):
    """Wait for the worker; if it dies abnormally, stop everything it left behind."""

    def forward(signum, _frame):
        try:
            os.kill(worker, signum)
        except ProcessLookupError:
            pass

    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)
    _, status = os.waitpid(worker, 0)
    info = json.loads((root / "session.json").read_text())
    # The worker's orphans are now this process's children or token carriers.
    cleanup_processes(info["token"])
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
    global GUARDIAN_PROFILE_LOCK
    root = Path(sys.argv[1])
    # Both processes are subreapers: orphans stay with the worker while it lives,
    # then fall to the guardian, never to init or a host service manager.
    become_subreaper()
    GUARDIAN_PROFILE_LOCK = take_profile_lock(root)
    worker = os.fork()
    if worker == 0:
        code = 1
        try:
            become_subreaper()  # not inherited across fork
            code = run_worker(root)
        finally:
            os._exit(code)
    raise SystemExit(guard(root, worker))


if __name__ == "__main__":
    main()
