"""A real VNC client must be unable to inject input or own desktop lifecycle."""

import os
import shutil
import socket
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path

from agent_desktop import core
from agent_desktop.worker import owned_processes


def receive(connection, size):
    output = b""
    while len(output) < size:
        chunk = connection.recv(size - len(output))
        if not chunk:
            raise AssertionError("Unexpected VNC disconnect")
        output += chunk
    return output


@unittest.skipUnless(
    all(
        shutil.which(t)
        for t in (
            "labwc",
            "grim",
            "foot",
            "dbus-daemon",
            "wayvnc",
        )
    ),
    "viewer runtime tools unavailable",
)
class ViewerTests(unittest.TestCase):
    def test_read_only_viewer_disconnect_preserves_session(self):
        with tempfile.TemporaryDirectory(prefix="desktop-vnc-") as directory:
            root = Path(directory)
            previous = {
                k: os.environ.get(k)
                for k in ("AGENT_DESKTOP_STATE_DIR", "XDG_RUNTIME_DIR")
            }
            (root / "runtime").mkdir(mode=0o700)
            os.environ["AGENT_DESKTOP_STATE_DIR"] = str(root / "state")
            os.environ["XDG_RUNTIME_DIR"] = str(root / "runtime")
            session = core.create()["session"]
            token = core.manifest(session)["token"]
            try:
                fixture = root / "fixture"
                fixture.mkdir()
                script = Path(__file__).resolve().parents[1] / "scripts/m0_terminal.py"
                core.request(
                    session,
                    "launch",
                    argv=[
                        "foot",
                        "--config=/dev/null",
                        "--window-size-pixels=800x500",
                        sys.executable,
                        str(script),
                        str(fixture),
                    ],
                )
                for _ in range(100):
                    if (fixture / "ready").exists():
                        break
                    time.sleep(0.05)
                self.assertTrue((fixture / "ready").exists())
                server = core.request(session, "viewer_start")
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                    connection.settimeout(5)
                    connection.connect(server["socket"])
                    self.assertTrue(receive(connection, 12).startswith(b"RFB 003."))
                    connection.sendall(b"RFB 003.008\n")
                    count = receive(connection, 1)[0]
                    types = receive(connection, count)
                    self.assertIn(1, types)
                    connection.sendall(b"\1")
                    self.assertEqual(receive(connection, 4), b"\0" * 4)
                    connection.sendall(b"\1")
                    header = receive(connection, 24)
                    width, height = struct.unpack(">HH", header[:4])
                    self.assertGreater(width, 0)
                    self.assertGreater(height, 0)
                    name_length = struct.unpack(">I", header[20:])[0]
                    receive(connection, name_length)
                    # Even a client ignoring ViewOnly must not be able to send keys.
                    connection.sendall(struct.pack(">BBHI", 4, 1, 0, ord("x")))
                    connection.sendall(struct.pack(">BBHI", 4, 0, 0, ord("x")))
                    time.sleep(0.2)
                self.assertEqual(core.request(session, "status")["status"], "ready")
                core.request(session, "type", text="observer cannot type")
                core.request(session, "key", key="Return")
                for _ in range(100):
                    if (fixture / "typed.txt").exists():
                        break
                    time.sleep(0.05)
                self.assertEqual(
                    (fixture / "typed.txt").read_text(), "observer cannot type"
                )
                self.assertTrue(
                    Path(core.request(session, "screenshot")["path"]).is_file()
                )
            finally:
                core.destroy(session)
                for _ in range(100):
                    if not owned_processes(token):
                        break
                    time.sleep(0.05)
                self.assertFalse(owned_processes(token))
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
