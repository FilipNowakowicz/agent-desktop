"""One supervisor, private D-Bus and compositor per session."""

import ctypes
import fcntl
import hashlib
import json
import math
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .wayland import BUTTONS, Keysyms, Toplevels, VirtualKeyboard, VirtualPointer

PR_SET_CHILD_SUBREAPER = 36


def become_subreaper():
    """Keep orphaned descendants, including daemons, inside this worker's tree."""
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0):
        raise OSError(ctypes.get_errno(), "Cannot become a child subreaper")


def process_table():
    """Return {pid: (parent pid, state)} for every visible process."""
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
        table[int(path.name)] = (int(fields[1]), fields[0])
    return table


def descendants(root, table=None):
    table = process_table() if table is None else table
    children = {}
    for pid, (parent, _state) in table.items():
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


def session_processes(token, tree=True):
    """Live session processes: token carriers, plus this supervisor's subtree."""
    table = process_table()
    pids = set(owned_processes(token))
    if tree:
        pids |= set(descendants(os.getpid(), table))
    # Never this supervisor or its parent (the worker's guardian).
    pids -= {os.getpid(), os.getppid()}
    return sorted(p for p in pids if p in table and table[p][1] not in "ZX")


def reap_orphans(tracked=()):
    """Collect adopted orphans without stealing exit codes from Popen objects."""
    me = os.getpid()
    for pid, (parent, state) in process_table().items():
        if parent == me and state == "Z" and pid not in tracked:
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass


def cleanup_processes(token, tracked=(), spare=(), tree=True):
    """Stop the session tree; processes in spare get SIGTERM only after the rest."""
    phases = [(signal.SIGTERM, 2, set(spare))] if spare else []
    phases += [(signal.SIGTERM, 2, set()), (signal.SIGKILL, 3, set())]
    for sig, wait, excluded in phases:
        signalled = set()
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            # Rescan: a process may fork while the tree is being stopped.
            remaining = set(session_processes(token, tree)) - excluded
            if not remaining:
                break
            for pid in remaining - signalled:
                signalled.add(pid)
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    pass
            reap_orphans(tracked)
            time.sleep(0.05)
        if not session_processes(token, tree):
            return
    raise RuntimeError("Session processes remain after cleanup")


INPUT_OPERATIONS = ("click", "move", "drag", "scroll", "type", "key")


class StaleObservation(RuntimeError):
    pass


class HumanControl(RuntimeError):
    pass


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
        self.virtual_pointer = None
        self.virtual_keyboard = None
        self.toplevels = None
        self.keysyms = None
        self.stop = False
        self.profile_lock = None

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

    def start(self):
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
        ):
            self.env.pop(key, None)
        if self.info.get("home"):
            home = Path(self.info["home"])
            # Held for the session's lifetime; released by the kernel if it dies.
            self.profile_lock = (home.parent / "lock").open("a")
            try:
                fcntl.flock(self.profile_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("Profile is in use by another session") from None
        else:
            home = self.root / "home"
            home.mkdir(mode=0o700)
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
            }
        )
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
                self.start_bus()
                # Create the pointer before applications so its seat capability is stable.
                self.virtual_pointer = VirtualPointer(display)
                self.virtual_keyboard = VirtualKeyboard(display, self.root)
                self.keysyms = Keysyms(self.compositor.pid)
                self.toplevels = Toplevels(display)
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

    def start_bus(self):
        # A child bus keeps D-Bus-activated services inside this worker's tree.
        bus = Path(self.info["runtime"]) / "bus"
        with (self.root / "dbus.log").open("ab") as log:
            self.bus = subprocess.Popen(
                [
                    self.info["tools"]["dbus-daemon"],
                    "--session",
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
            self.compositor,
            self.viewer,
            self.takeover,
            *self.apps.values(),
        ]
        return {p.pid for p in processes if p}

    def screenshot(self):
        directory = self.root / "screenshots"
        directory.mkdir(exist_ok=True, mode=0o700)
        path = directory / (uuid.uuid4().hex + ".png")
        # Retry so the token describes the layout the image actually shows.
        for _ in range(3):
            before = self.observation()
            self.command("grim", path)
            if self.observation() == before:
                break
        self.needs_screenshot = False
        with path.open("rb") as stream:
            header = stream.read(24)
        if not header.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("Capture did not produce a PNG")
        width, height = struct.unpack(">II", header[16:24])
        return {
            "path": str(path),
            "width": width,
            "height": height,
            "observation": before,
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
        if token != self.observation():
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
        }

    def save_control(self):
        self.info["control"] = {
            "owner": self.control["owner"],
            "request": self.control["request"],
        }
        write_manifest(self.root, self.info)

    def start_vnc(self, wayvnc, endpoint, control_socket, interactive=False):
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

    def take(self, wayvnc):
        endpoint = Path(self.info["runtime"]) / "takeover.sock"
        if self.control["owner"] != "human":
            self.takeover = self.start_vnc(
                wayvnc, endpoint, "takeover-control.sock", interactive=True
            )
            self.control.update(owner="human", since=time.time())
            self.control["epoch"] += 1
            self.save_control()
            print("Control taken by a person", file=sys.stderr, flush=True)
        return {**self.control_state(), "socket": str(endpoint)}

    def release(self, how):
        if self.control["owner"] == "human":
            if self.takeover and self.takeover.poll() is None:
                self.takeover.terminate()
                try:
                    self.takeover.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.takeover.kill()
                    self.takeover.wait()
            Path(self.info["runtime"], "takeover.sock").unlink(missing_ok=True)
            self.control.update(
                owner="agent",
                request=None,
                last={"released_at": time.time(), "how": how},
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
        if operation == "status":
            return {
                "session": self.info["id"],
                "mode": self.info["mode"],
                "status": "ready",
                "x_display": self.info.get("x_display"),
                "control": self.control["owner"],
                "human_requested": self.control["request"] is not None,
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
            return self.take(request.get("wayvnc", "wayvnc"))
        if operation == "release":
            return self.release("released by the user")
        if self.control["owner"] == "human":
            raise HumanControl(
                "A person has control of this private desktop; nothing was sent. "
                "Wait with desktop_control until control returns to the agent."
            )
        if self.needs_screenshot and operation in (*INPUT_OPERATIONS, "focus"):
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
            executable = shutil.which(argv[0], path=self.env.get("PATH"))
            if not executable:
                raise ValueError(f"Executable not found: {argv[0]}")
            app = uuid.uuid4().hex[:12]
            log_path = self.root / f"app-{app}.log"
            with log_path.open("ab") as log:
                process = subprocess.Popen(
                    [executable, *argv[1:]],
                    env=self.env,
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
            return self.screenshot()
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
            points = [
                (int(values[i]), int(values[i + 1])) for i in (0, len(values) - 2)
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
            self.keyboard().type(text)
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
            self.keyboard().key(self.keysyms.resolve(key), modifiers, repeat)
        elif operation == "scroll":
            dx, dy = request.get("dx", 0), request.get("dy", 0)
            if not all(
                isinstance(v, int) and not isinstance(v, bool) and abs(v) <= 10000
                for v in (dx, dy)
            ):
                raise ValueError(
                    "Scroll distances must be integers between -10000 and 10000"
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
                self.trim_logs()
                reap_orphans(self.tracked())
                if self.compositor.poll() is not None:
                    raise RuntimeError("Private compositor crashed")
                if (
                    self.control["owner"] == "human"
                    and self.takeover
                    and self.takeover.poll() is not None
                ):
                    self.release("viewer disconnected")
                try:
                    connection, _ = server.accept()
                except TimeoutError:
                    continue
                with connection:
                    connection.settimeout(5)
                    try:
                        with connection.makefile("rb") as stream:
                            line = stream.readline(262145)
                        if len(line) > 262144:
                            raise ValueError("Request too large")
                        result = self.handle(json.loads(line))
                        reply = {"ok": True, "result": result}
                    except Exception as error:
                        reply = {
                            "ok": False,
                            "error": f"{type(error).__name__}: {error}",
                        }
                    try:
                        connection.sendall((json.dumps(reply) + "\n").encode())
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

    def cleanup(self):
        if self.toplevels and self.compositor and self.compositor.poll() is None:
            self.stop_applications()
        for device in (self.virtual_pointer, self.virtual_keyboard, self.toplevels):
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


def command_name(pid):
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip()
    except OSError:
        return None


def re_key(key):
    import re

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


def main():
    root = Path(sys.argv[1])
    # Both processes are subreapers: orphans stay with the worker while it lives,
    # then fall to the guardian, never to init or a host service manager.
    become_subreaper()
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
