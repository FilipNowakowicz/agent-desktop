"""Guarded sessions refuse host-affecting commands; all sessions render GTK in software.

Only harmless commands are used, so a broken guard cannot change the host.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from test_runtime import wait_for

from agent_desktop import core
from agent_desktop.worker import owned_processes

PROBE = (
    'systemctl --version >/dev/null 2>&1; echo "systemctl=$?"; '
    'pkill -0 -x agent-desktop-no-such-process; echo "pkill=$?"; '
    'echo "bus=$DBUS_SYSTEM_BUS_ADDRESS"; echo "gsk=$GSK_RENDERER"'
)


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "dbus-daemon")),
    "desktop tools unavailable",
)
class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-guard-")
        root = Path(self.temporary.name)
        self.previous = {
            k: os.environ.get(k) for k in ("AGENT_DESKTOP_STATE_DIR", "XDG_RUNTIME_DIR")
        }
        (root / "runtime").mkdir(mode=0o700)
        os.environ["AGENT_DESKTOP_STATE_DIR"] = str(root / "state")
        os.environ["XDG_RUNTIME_DIR"] = str(root / "runtime")
        self.sessions = []

    def tearDown(self):
        for session in self.sessions:
            token = core.manifest(session)["token"]
            core.destroy(session)
            wait_for(lambda token=token: not owned_processes(token))
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temporary.cleanup()

    def probe(self, guard_host):
        session = core.create(guard_host=guard_host)["session"]
        self.sessions.append(session)
        app = core.request(session, "launch", argv=["sh", "-c", PROBE])

        def output():
            for entry in core.request(session, "status")["applications"]:
                if entry["pid"] == app["pid"] and entry["exit_code"] is not None:
                    return Path(app["logs"]).read_text()
            return None

        # The log also holds stderr, such as the guard's refusal messages.
        lines = dict(
            line.split("=", 1)
            for line in wait_for(output).splitlines()
            if line.split("=", 1)[0] in ("systemctl", "pkill", "bus", "gsk")
        )
        return session, lines

    def test_guarded_session_refuses_and_logs(self):
        session, lines = self.probe(True)
        self.assertTrue(core.request(session, "status")["guard_host"])
        self.assertEqual(lines["systemctl"], "1")
        self.assertEqual(lines["pkill"], "1")
        self.assertEqual(lines["bus"], "unix:path=/nonexistent/system_bus_socket")
        self.assertEqual(lines["gsk"], "cairo")
        log = core.logs(session)["guard.log"]
        self.assertIn("blocked: systemctl --version", log)
        self.assertIn("blocked: pkill -0 -x agent-desktop-no-such-process", log)

    def test_unguarded_session_keeps_host_tools(self):
        session, lines = self.probe(False)
        self.assertFalse(core.request(session, "status")["guard_host"])
        self.assertNotIn("guard.log", core.logs(session))
        self.assertNotEqual(lines["bus"], "unix:path=/nonexistent/system_bus_socket")
        # Software rendering applies to every session.
        self.assertEqual(lines["gsk"], "cairo")
        if shutil.which("systemctl"):
            self.assertEqual(lines["systemctl"], "0")


if __name__ == "__main__":
    unittest.main()
