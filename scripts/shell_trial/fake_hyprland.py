"""A small fake of Hyprland's IPC sockets for testing bars and widgets.

Serves request/response queries on .socket.sock (as waybar and hyprctl send
them) and broadcasts events on .socket2.sock. `dispatch workspace N` switches
the active workspace and emits the events a real compositor would, so a bar's
workspace module can be exercised (and stress-tested) without Hyprland.
Every request is appended to $SHELL_TRIAL_LOG as JSON.
"""

import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

WORKSPACES = 5


class FakeHyprland:
    def __init__(self, directory, log):
        self.directory = directory
        self.log = log
        self.active = 1
        self.listeners = []
        self.lock = threading.Lock()

    def record(self, kind, value):
        with self.lock, open(self.log, "a") as stream:
            stream.write(
                json.dumps({"t": time.time(), "source": "hyprland", kind: value}) + "\n"
            )

    def monitor(self):
        return {
            "id": 0,
            "name": "HEADLESS-1",
            "description": "fake",
            "width": 1280,
            "height": 720,
            "refreshRate": 60.0,
            "x": 0,
            "y": 0,
            "activeWorkspace": {"id": self.active, "name": str(self.active)},
            "specialWorkspace": {"id": 0, "name": ""},
            "reserved": [0, 0, 0, 0],
            "scale": 1.0,
            "transform": 0,
            "focused": True,
            "dpmsStatus": True,
            "vrr": False,
            "disabled": False,
        }

    def workspace(self, number):
        return {
            "id": number,
            "name": str(number),
            "monitor": "HEADLESS-1",
            "monitorID": 0,
            "windows": 1 if number == self.active else 0,
            "hasfullscreen": False,
            "lastwindow": "0x0",
            "lastwindowtitle": "",
            "ispersistent": False,
        }

    def answer(self, request):
        command = request.split("/", 1)[1] if "/" in request[:3] else request
        if command.startswith("dispatch workspace"):
            target = command.split()[-1]
            if target.lstrip("+-").isdigit():
                number = int(target)
                if target[0] in "+-":
                    number = (self.active - 1 + number) % WORKSPACES + 1
                if 1 <= number <= WORKSPACES:
                    self.switch(number)
                    return "ok"
            return "invalid workspace"
        if command.startswith("dispatch") or command.startswith("keyword"):
            return "ok"
        if command == "workspaces":
            return json.dumps([self.workspace(n) for n in range(1, WORKSPACES + 1)])
        if command == "activeworkspace":
            return json.dumps(self.workspace(self.active))
        if command == "monitors" or command.startswith("monitors "):
            return json.dumps([self.monitor()])
        if command in ("clients", "workspacerules"):
            return "[]"
        if command == "activewindow":
            return "{}"
        if command == "layers":
            return json.dumps(
                {"HEADLESS-1": {"levels": {"0": [], "1": [], "2": [], "3": []}}}
            )
        if command == "version":
            return json.dumps({"branch": "fake", "tag": "fake-ipc"})
        return "[]" if request.startswith("j/") else "unknown request"

    def switch(self, number):
        previous, self.active = self.active, number
        events = (
            f"workspace>>{number}\n"
            f"workspacev2>>{number},{number}\n"
            f"focusedmon>>HEADLESS-1,{number}\n"
            f"focusedmonv2>>HEADLESS-1,{number}\n"
        )
        self.record("event", {"from": previous, "to": number})
        with self.lock:
            alive = []
            for connection in self.listeners:
                try:
                    connection.sendall(events.encode())
                    alive.append(connection)
                except OSError:
                    connection.close()
            self.listeners = alive

    def serve_requests(self, server):
        while True:
            connection, _ = server.accept()
            with connection:
                data = b""
                connection.settimeout(1)
                try:
                    while True:
                        chunk = connection.recv(65536)
                        if not chunk:
                            break
                        data += chunk
                        if len(chunk) < 65536:
                            break
                except TimeoutError:
                    pass
                request = data.decode(errors="replace").strip()
                self.record("request", request)
                try:
                    connection.sendall(self.answer(request).encode())
                except OSError:
                    pass

    def serve_events(self, server):
        while True:
            connection, _ = server.accept()
            with self.lock:
                self.listeners.append(connection)

    def run(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        servers = []
        for name, handler in (
            (".socket.sock", self.serve_requests),
            (".socket2.sock", self.serve_events),
        ):
            path = self.directory / name
            path.unlink(missing_ok=True)
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(path))
            server.listen(32)
            servers.append(server)
            threading.Thread(target=handler, args=(server,), daemon=True).start()
        (self.directory / "ready").touch()
        threading.Event().wait()


def main():
    runtime = Path(os.environ["XDG_RUNTIME_DIR"])
    signature = os.environ["HYPRLAND_INSTANCE_SIGNATURE"]
    log = os.environ.get("SHELL_TRIAL_LOG", str(runtime / "shell-trial.jsonl"))
    FakeHyprland(runtime / "hypr" / signature, log).run()


if __name__ == "__main__":
    sys.exit(main())
