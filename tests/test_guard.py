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
from agent_desktop.worker import credential_variable, owned_processes

PROBE = (
    'systemctl --version >/dev/null 2>&1; echo "systemctl=$?"; '
    'pkill -0 -x agent-desktop-no-such-process; echo "pkill=$?"; '
    'echo "bus=$DBUS_SYSTEM_BUS_ADDRESS"; echo "gsk=$GSK_RENDERER"; '
    'echo "ssh=${SSH_AUTH_SOCK:-none}"; echo "api=${TRIAL_API_TOKEN:-none}"; '
    'echo "aws=${AWS_PROFILE:-none}"; echo "lang=${LANG:-none}"; '
    'echo "pwd=$PWD"; echo "home=$HOME"'
)
FAKE_CREDENTIALS = {
    "SSH_AUTH_SOCK": "/nonexistent/agent.sock",
    "TRIAL_API_TOKEN": "not-a-real-token",
    "AWS_PROFILE": "trial",
}
SECRETS_PROBE = (
    "dbus-send --session --print-reply --dest=org.freedesktop.DBus "
    "/org/freedesktop/DBus org.freedesktop.DBus.StartServiceByName "
    'string:org.freedesktop.secrets uint32:0; echo "secrets=$?"'
)
KEYS = ("systemctl", "pkill", "bus", "gsk", "ssh", "api", "aws", "lang", "pwd", "home")


class CredentialNameTests(unittest.TestCase):
    def test_classification(self):
        for name in (
            "SSH_AUTH_SOCK",
            "GITHUB_TOKEN",
            "OPENAI_API_KEY",
            "AWS_SECRET_ACCESS_KEY",
            "DB_PASSWORD",
            "GNOME_KEYRING_CONTROL",
        ):
            self.assertTrue(credential_variable(name), name)
        for name in (
            "AGENT_DESKTOP_SESSION_TOKEN",
            "TERM",
            "LANG",
            "PATH",
            "DBUS_SESSION_BUS_ADDRESS",
            "XDG_SESSION_ID",
            "XKB_DEFAULT_LAYOUT",
        ):
            self.assertFalse(credential_variable(name), name)


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
        for key, value in FAKE_CREDENTIALS.items():
            self.previous[key] = os.environ.get(key)
            os.environ[key] = value

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
            if line.split("=", 1)[0] in KEYS
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
        # Credentials are removed; ownership (session token) and locale are not.
        self.assertEqual((lines["ssh"], lines["api"], lines["aws"]), ("none",) * 3)
        removed = core.request(session, "status")["guard_removed_variables"]
        self.assertLessEqual(set(FAKE_CREDENTIALS), set(removed))
        self.assertFalse(any(name.startswith("AGENT_DESKTOP_") for name in removed))
        self.assertEqual(lines["pwd"], lines["home"])

    def test_launch_directory(self):
        session = core.create()["session"]
        self.sessions.append(session)
        target = Path(self.temporary.name)
        app = core.request(session, "launch", argv=["sh", "-c", "pwd"], cwd=str(target))
        wait_for(lambda: Path(app["logs"]).read_text().strip())
        self.assertEqual(Path(app["logs"]).read_text().strip(), str(target))
        for bad in ("relative/dir", str(target / "missing")):
            with self.subTest(cwd=bad), self.assertRaises(core.DesktopError):
                core.request(session, "launch", argv=["true"], cwd=bad)

    def test_unguarded_session_keeps_host_tools(self):
        session, lines = self.probe(False)
        self.assertFalse(core.request(session, "status")["guard_host"])
        self.assertNotIn("guard.log", core.logs(session))
        self.assertNotEqual(lines["bus"], "unix:path=/nonexistent/system_bus_socket")
        # Software rendering and the private working directory apply to every session.
        self.assertEqual(lines["gsk"], "cairo")
        self.assertEqual(lines["pwd"], lines["home"])
        self.assertEqual(lines["api"], "not-a-real-token")
        if shutil.which("systemctl"):
            self.assertEqual(lines["systemctl"], "0")

    @unittest.skipUnless(shutil.which("dbus-send"), "dbus-send unavailable")
    def test_keyring_is_not_activated(self):
        # A host keyring service would prompt for a new keyring password.
        session = core.create()["session"]
        self.sessions.append(session)
        self.assertFalse(core.request(session, "status")["secret_service"])
        app = core.request(session, "launch", argv=["sh", "-c", SECRETS_PROBE])

        def output():
            for entry in core.request(session, "status")["applications"]:
                if entry["pid"] == app["pid"] and entry["exit_code"] is not None:
                    return Path(app["logs"]).read_text()
            return None

        self.assertIn("secrets=1", wait_for(output))


if __name__ == "__main__":
    unittest.main()
