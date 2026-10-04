"""A person can take control of a session; the agent cannot act meanwhile."""

import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from test_viewer import receive

from agent_desktop import core
from agent_desktop.worker import owned_processes


def wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for an observed result")


def connect(path):
    """Complete an unauthenticated RFB 3.8 handshake on a Unix socket."""
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(5)
    connection.connect(path)
    receive(connection, 12)
    connection.sendall(b"RFB 003.008\n")
    count = receive(connection, 1)[0]
    if 1 not in receive(connection, count):
        raise AssertionError("Server requires authentication")
    connection.sendall(b"\1")
    if receive(connection, 4) != b"\0" * 4:
        raise AssertionError("Security handshake failed")
    connection.sendall(b"\1")
    header = receive(connection, 24)
    receive(connection, struct.unpack(">I", header[20:])[0])
    return connection


def press(connection, keysym):
    connection.sendall(struct.pack(">BBHI", 4, 1, 0, keysym))
    time.sleep(0.03)
    connection.sendall(struct.pack(">BBHI", 4, 0, 0, keysym))
    time.sleep(0.03)


EXIT_ON_DISCONNECT = shutil.which("wayvnc") and "--exit-on-disconnect" in (
    subprocess.run(
        ["wayvnc", "--help"], capture_output=True, text=True, check=False
    ).stdout
)


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "foot", "dbus-daemon", "wayvnc")),
    "takeover runtime tools unavailable",
)
class TakeoverTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-takeover-")
        self.root = Path(self.temporary.name)
        self.previous = {
            k: os.environ.get(k) for k in ("AGENT_DESKTOP_STATE_DIR", "XDG_RUNTIME_DIR")
        }
        (self.root / "runtime").mkdir(mode=0o700)
        os.environ["AGENT_DESKTOP_STATE_DIR"] = str(self.root / "state")
        os.environ["XDG_RUNTIME_DIR"] = str(self.root / "runtime")
        self.session = core.create()["session"]
        self.token = core.manifest(self.session)["token"]

    def tearDown(self):
        core.destroy(self.session)
        wait_for(lambda: not owned_processes(self.token))
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temporary.cleanup()

    def fixture(self, name="fixture"):
        directory = self.root / name
        directory.mkdir()
        script = Path(__file__).resolve().parents[1] / "scripts/m0_terminal.py"
        core.request(
            self.session,
            "launch",
            argv=[
                "foot",
                "--config=/dev/null",
                "--window-size-pixels=800x500",
                sys.executable,
                str(script),
                str(directory),
            ],
        )
        wait_for((directory / "ready").exists)
        time.sleep(0.4)
        return directory

    def test_person_types_while_agent_is_refused(self):
        fixture = self.fixture()
        old = core.request(self.session, "screenshot")["observation"]
        state = core.request(
            self.session, "request_human", reason="Log in to the test site"
        )
        self.assertEqual(state["owner"], "agent")
        self.assertEqual(state["request"]["reason"], "Log in to the test site")
        listed = {s["session"]: s for s in core.sessions()}[self.session]
        self.assertEqual(listed["human_request"], "Log in to the test site")
        self.assertEqual(core.wait_for_agent_control(self.session, 1)["owner"], "agent")

        taken = core.request(self.session, "take")
        self.assertEqual(taken["owner"], "human")
        self.assertEqual(core.request(self.session, "status")["control"], "human")
        # Taking twice keeps the same server rather than starting another.
        self.assertEqual(core.request(self.session, "take")["epoch"], taken["epoch"])
        for operation, arguments in (
            ("type", {"text": "agent must not type"}),
            ("key", {"key": "Return"}),
            ("click", {"x": 10, "y": 10}),
            ("screenshot", {}),
            ("windows", {}),
            ("launch", {"argv": ["foot"]}),
        ):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(core.DesktopError, "HumanControl"):
                    core.request(self.session, operation, **arguments)

        connection = connect(taken["socket"])
        try:
            for character in "human":
                press(connection, ord(character))
            press(connection, 0xFF0D)  # Return
            wait_for((fixture / "typed.txt").exists)
        finally:
            connection.close()
        self.assertEqual((fixture / "typed.txt").read_text(), "human")

        if EXIT_ON_DISCONNECT:
            # Closing the viewer hands control back without a release request.
            state = wait_for(
                lambda: (
                    (s := core.request(self.session, "control"))["owner"] == "agent"
                    and s
                )
            )
            self.assertEqual(state["last"]["how"], "viewer disconnected")
        else:
            state = core.request(self.session, "release")
        self.assertEqual(state["owner"], "agent")
        self.assertIsNone(state["request"])
        self.assertTrue(state["needs_screenshot"])
        self.assertFalse(Path(taken["socket"]).exists())

        # The agent must look before acting again.
        with self.assertRaisesRegex(core.DesktopError, "new screenshot"):
            core.request(self.session, "type", text="blind")
        capture = core.request(self.session, "screenshot")
        fresh = capture["observation"]
        self.assertNotEqual(fresh, old)
        with self.assertRaisesRegex(core.DesktopError, "StaleObservation"):
            core.request(self.session, "move", x=5, y=5, observation=old)
        # Mouse delivery after takeover: the fixture now waits for a click.
        wait_for((fixture / "mouse-ready").exists)
        core.request(
            self.session,
            "click",
            x=capture["width"] // 2,
            y=capture["height"] // 2,
            observation=fresh,
        )
        wait_for((fixture / "mouse.json").exists)
        self.assertEqual(core.request(self.session, "control")["epoch"], 2)
        # The agent's own keyboard (and keymap) works again after the person's.
        second = self.fixture("second")
        observation = core.request(self.session, "screenshot")["observation"]
        core.request(self.session, "type", text="agent café λ", observation=observation)
        core.request(self.session, "key", key="Return")
        wait_for((second / "typed.txt").exists)
        self.assertEqual((second / "typed.txt").read_text(), "agent café λ")

    def test_release_and_requests_without_takeover(self):
        state = core.request(self.session, "release")
        self.assertEqual(state["owner"], "agent")
        self.assertFalse(state["needs_screenshot"])
        for reason in ("", " ", "x" * 501, None):
            with self.subTest(reason=reason):
                with self.assertRaises(core.DesktopError):
                    core.request(self.session, "request_human", reason=reason)
        core.request(self.session, "request_human", reason="Enter a code")
        started = time.monotonic()
        state = core.wait_for_agent_control(self.session, 1)
        self.assertGreaterEqual(time.monotonic() - started, 0.9)
        self.assertEqual(state["request"]["reason"], "Enter a code")

    def test_destroy_during_takeover_stops_the_server(self):
        self.assertEqual(core.request(self.session, "take")["owner"], "human")
        core.destroy(self.session)
        self.assertEqual(core.manifest(self.session)["status"], "stopped")
        self.assertFalse(owned_processes(self.token))


if __name__ == "__main__":
    unittest.main()
