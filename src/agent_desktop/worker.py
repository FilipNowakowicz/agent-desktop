"""One supervisor, private D-Bus and compositor per session."""

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


def owned_processes(token):
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


def cleanup_processes(token, excluded=()):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid in owned_processes(token):
            if pid in excluded:
                continue
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if not set(owned_processes(token)) - set(excluded):
                return
            time.sleep(0.05)
    if set(owned_processes(token)) - set(excluded):
        raise RuntimeError("Session processes remain after cleanup")


class Worker:
    def __init__(self, root):
        self.root = root
        self.info = json.loads((root / "session.json").read_text())
        self.env = os.environ.copy()
        self.compositor = None
        self.apps = {}
        self.stop = False

    def save(self, status, **values):
        self.info.update(status=status, **values)
        temporary = self.root / "session.json.tmp"
        temporary.write_text(json.dumps(self.info, indent=2) + "\n")
        temporary.replace(self.root / "session.json")

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
        ):
            self.env.pop(key, None)
        home = self.root / "home"
        home.mkdir(mode=0o700)
        config = self.root / "config"
        config.mkdir(mode=0o700)
        (config / "rc.xml").write_text(
            "<labwc_config><keyboard><default/></keyboard></labwc_config>\n"
        )
        for name in ("environment", "autostart", "shutdown"):
            (config / name).write_text("")
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
                return
            time.sleep(0.05)
        raise TimeoutError("Private compositor socket did not appear")

    def screenshot(self):
        directory = self.root / "screenshots"
        directory.mkdir(exist_ok=True, mode=0o700)
        path = directory / (uuid.uuid4().hex + ".png")
        self.command("grim", path)
        with path.open("rb") as stream:
            header = stream.read(24)
        if not header.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("Capture did not produce a PNG")
        width, height = struct.unpack(">II", header[16:24])
        return {"path": str(path), "width": width, "height": height}

    def position(self, x, y):
        if not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            for v in (x, y)
        ):
            raise ValueError("Coordinates must be finite numbers")
        capture = self.screenshot()
        if not (0 <= x < capture["width"] and 0 <= y < capture["height"]):
            raise ValueError("Coordinates outside private desktop")
        # Single output, scale 1. Relative pointer movement supplies the initial MVP.
        self.command("wlrctl", "pointer", "move", -100000, -100000)
        self.command("wlrctl", "pointer", "move", x, y)

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
                "applications": [
                    {"pid": p.pid, "exit_code": p.poll()} for p in self.apps.values()
                ],
            }
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
            return {"windows": self.command("wlrctl", "toplevel", "list").splitlines()}
        if operation == "screenshot":
            return self.screenshot()
        if operation in ("click", "move"):
            if operation == "click":
                button = request.get("button", "left")
                if button not in ("left", "middle", "right"):
                    raise ValueError("Unsupported mouse button")
            self.position(request.get("x"), request.get("y"))
            if operation == "click":
                self.command("wlrctl", "pointer", "click", button)
        elif operation == "type":
            text = request.get("text")
            if not isinstance(text, str) or "\0" in text or len(text) > 16384:
                raise ValueError(
                    "Text must be a string of at most 16384 characters without NUL"
                )
            self.command("wtype", "-s", "200", "-d", "20", "--", text, timeout=25)
        elif operation == "key":
            key = request.get("key")
            modifiers = request.get("modifiers", [])
            if not isinstance(key, str) or not re_key(key):
                raise ValueError("Invalid key name")
            if not isinstance(modifiers, list) or any(
                m not in ("ctrl", "alt", "shift", "logo") for m in modifiers
            ):
                raise ValueError("Modifiers must be ctrl, alt, shift or logo")
            args = ["-s", "200"]
            for modifier in modifiers:
                args += ["-M", modifier]
            args += ["-k", key]
            for modifier in reversed(modifiers):
                args += ["-m", modifier]
            self.command("wtype", *args)
        elif operation == "scroll":
            dx, dy = request.get("dx", 0), request.get("dy", 0)
            if not all(
                isinstance(v, int) and not isinstance(v, bool) and abs(v) <= 10000
                for v in (dx, dy)
            ):
                raise ValueError(
                    "Scroll distances must be integers between -10000 and 10000"
                )
            self.command("wlrctl", "pointer", "scroll", dy, dx)
        else:
            raise ValueError(f"Unsupported operation: {operation}")
        return {"session": self.info["id"], "operation": operation, "delivered": True}

    def serve(self):
        endpoint = self.info["control_socket"]
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(endpoint)
            server.listen(16)
            server.settimeout(0.5)
            self.save("ready", worker_pid=os.getpid())
            while not self.stop:
                self.trim_logs()
                if self.compositor.poll() is not None:
                    raise RuntimeError("Private compositor crashed")
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
        for path in [self.root / "session.log", *self.root.glob("app-*.log")]:
            if path.stat().st_size > 1024 * 1024:
                with path.open("r+b") as stream:
                    stream.seek(-512 * 1024, 2)
                    tail = stream.read()
                    stream.seek(0)
                    stream.write(tail)
                    stream.truncate()

    def cleanup(self):
        if self.compositor and self.compositor.poll() is None:
            try:
                self.command("labwc", "-e", timeout=3)
                self.compositor.wait(timeout=3)
            except (RuntimeError, subprocess.SubprocessError):
                pass
        # The parent D-Bus wrapper and daemon must survive until this worker exits.
        protected = [os.getppid()]
        bus_pid = os.environ.get("DBUS_SESSION_BUS_PID")
        if bus_pid:
            protected.append(int(bus_pid))
        cleanup_processes(self.info["token"], excluded=protected)
        if self.compositor:
            self.compositor.wait(timeout=3)
        for process in self.apps.values():
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        shutil.rmtree(self.info["runtime"])
        for name in ("home", "config"):
            shutil.rmtree(self.root / name, ignore_errors=True)


def re_key(key):
    import re

    return re.fullmatch(r"[A-Za-z0-9_]+", key)


def main():
    worker = Worker(Path(sys.argv[1]))

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


if __name__ == "__main__":
    main()
