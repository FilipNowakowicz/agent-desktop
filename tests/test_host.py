"""Host sessions act on a person's own desktop only after approval.

A private headless session stands in for the person's desktop, so these tests
never touch the real screen; notifications are disabled.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from test_runtime import wait_for

from agent_desktop import core
from agent_desktop.worker import Worker, owned_processes


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "foot", "dbus-daemon")),
    "desktop tools unavailable",
)
class HostTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-host-")
        self.root = Path(self.temporary.name)
        keys = (
            "AGENT_DESKTOP_STATE_DIR",
            "XDG_RUNTIME_DIR",
            "WAYLAND_DISPLAY",
            "HYPRLAND_INSTANCE_SIGNATURE",
            "AGENT_DESKTOP_HOST_NOTIFY",
        )
        self.previous = {k: os.environ.get(k) for k in keys}
        (self.root / "runtime").mkdir(mode=0o700)
        os.environ["AGENT_DESKTOP_STATE_DIR"] = str(self.root / "state")
        os.environ["XDG_RUNTIME_DIR"] = str(self.root / "runtime")
        os.environ["AGENT_DESKTOP_HOST_NOTIFY"] = "0"
        os.environ.pop("HYPRLAND_INSTANCE_SIGNATURE", None)
        # The stand-in for the person's desktop.
        self.person = core.create()["session"]
        self.sessions = [self.person]
        os.environ["WAYLAND_DISPLAY"] = core.manifest(self.person)["wayland_display"]

    def tearDown(self):
        for session in reversed(self.sessions):
            token = core.manifest(session)["token"]
            core.destroy(session)
            wait_for(lambda token=token: not owned_processes(token))
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temporary.cleanup()

    def person_terminal(self):
        directory = self.root / "fixture"
        directory.mkdir()
        script = Path(__file__).resolve().parents[1] / "scripts/m0_terminal.py"
        core.request(
            self.person,
            "launch",
            argv=[
                "foot",
                "--config=/dev/null",
                sys.executable,
                str(script),
                str(directory),
            ],
        )
        wait_for((directory / "ready").exists)
        time.sleep(0.4)
        return directory

    def approved(self, minutes=1):
        result = {}

        def ask():
            result.update(core.request_host("Open the report", minutes, wait=20))

        asking = threading.Thread(target=ask)
        asking.start()
        wait_for((core.state_root() / core.HOST_REQUEST).exists)
        self.assertEqual(core.answer_host(True)["answer"], "approved")
        asking.join(20)
        self.sessions.append(result["session"])
        return result["session"]

    def test_only_with_approval(self):
        with self.assertRaisesRegex(core.DesktopError, "approval"):
            core.create("host")
        threading.Timer(0.5, core.answer_host, (False,)).start()
        with self.assertRaisesRegex(core.DesktopError, "declined"):
            core.request_host("Open the report", 1, wait=20)
        # Without an answer the call returns, and the request stays open.
        self.assertEqual(
            core.request_host("Open the report", 1, wait=0.2)["status"], "pending"
        )
        threading.Timer(0.3, core.answer_host, (True,)).start()
        approved = core.request_host("Open the report", 1, wait=20)
        self.sessions.append(approved["session"])
        core.stop_host()
        with mock.patch.object(core, "HOST_REQUEST_SECONDS", 0.3):
            core.request_host("Expire", 1, wait=0)
            time.sleep(0.5)
            with self.assertRaisesRegex(core.DesktopError, "No answer"):
                core.request_host("Expire", 1, wait=1)

    def test_acts_on_the_desktop_and_leaves_it_open(self):
        fixture = self.person_terminal()
        host = self.approved()
        self.assertEqual(core.active_host_session(), host)
        self.assertEqual(core.request_host("again", 1)["session"], host)
        window = core.request(host, "windows")["windows"][0]
        core.request(host, "focus", window=window["id"])
        observation = core.request(host, "screenshot")["observation"]
        core.request(host, "type", text="from the agent\n", observation=observation)
        wait_for((fixture / "typed.txt").exists)
        self.assertEqual((fixture / "typed.txt").read_text(), "from the agent")
        for operation in ("take", "ui", "request_human"):
            with self.assertRaisesRegex(core.DesktopError, "not available on the host"):
                core.request(host, operation, reason="x")
        core.stop_host()
        self.assertIsNone(core.active_host_session())
        # The person's window and desktop are untouched.
        self.assertEqual(len(core.request(self.person, "windows")["windows"]), 1)
        self.assertEqual(core.request(self.person, "status")["status"], "ready")

    def test_pauses_while_the_person_uses_the_computer(self):
        self.person_terminal()
        host = self.approved()
        time.sleep(1)  # the person has been idle
        core.request(host, "move", x=20, y=20)
        time.sleep(0.6)  # the agent looks and thinks between steps
        # The person moves their own mouse (another device on the same seat).
        core.request(self.person, "move", x=200, y=200)
        with self.assertRaisesRegex(core.DesktopError, "UserActive"):
            core.request(host, "move", x=30, y=30)
        time.sleep(4.5)
        core.request(host, "move", x=40, y=40)

    def test_old_screenshots_and_locked_screens_are_refused(self):
        self.person_terminal()
        host = self.approved()
        time.sleep(1)
        observation = core.request(host, "screenshot")["observation"]
        core.request(self.person, "move", x=200, y=200)
        time.sleep(3.5)  # the pause is over, but the screenshot predates it
        with self.assertRaisesRegex(core.DesktopError, "after that screenshot"):
            core.request(host, "move", x=30, y=30, observation=observation)
        fresh = core.request(host, "screenshot")["observation"]
        core.request(host, "move", x=30, y=30, observation=fresh)
        # A screen locker is running: nothing is sent until it is gone.
        locker = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "open('/proc/self/comm', 'w').write('swaylock'); "
                "import time; time.sleep(30)",
            ]
        )
        try:
            wait_for(
                lambda: (
                    Path(f"/proc/{locker.pid}/comm").read_text().strip() == "swaylock"
                )
            )
            with self.assertRaisesRegex(core.DesktopError, "screen is locked"):
                core.request(host, "move", x=40, y=40)
        finally:
            locker.kill()
            locker.wait()
        core.request(host, "move", x=40, y=40)

    @unittest.skipUnless(shutil.which("firefox"), "Firefox unavailable")
    def test_works_in_the_person_firefox_in_background_tabs(self):
        # The person's Firefox, started with a BiDi port and its own profile.
        profiles = self.root / "mozilla"
        (profiles / "person").mkdir(parents=True)
        page = self.root / "mine.html"
        page.write_text("<title>Their tab</title><button>Danger</button>")
        os.environ["MOZ_APP_DATA"] = str(profiles)
        self.addCleanup(os.environ.pop, "MOZ_APP_DATA", None)
        core.request(
            self.person,
            "launch",
            argv=[
                "firefox",
                "--profile",
                str(profiles / "person"),
                "--remote-debugging-port=0",
                page.as_uri(),
                # A privileged page: listing tabs must not fail on it.
                "about:preferences",
            ],
        )
        wait_for((profiles / "person/WebDriverBiDiServer.json").exists, timeout=30)
        host = self.approved()

        def browser(action, **arguments):
            return core.request(host, "browser", action=action, **arguments)

        tabs = browser("start")["tabs"]
        self.assertEqual(tabs[0]["title"], "Their tab")
        browser("tabs", tab=0)
        self.assertIn("Danger", browser("text")["text"])
        # Their current tab is not acted on unless named explicitly.
        with self.assertRaisesRegex(core.DesktopError, "tabs you opened"):
            browser("click", text="Danger")
        work = self.root / "work.html"
        work.write_text(
            "<title>Agent tab</title><input id=q>"
            "<button onclick=\"document.title='done '+q.value\">Go</button>"
        )
        browser("open", url=work.as_uri(), new_tab=True)
        done = browser(
            "steps",
            steps=[
                {"action": "fill", "selector": "#q", "value": "ok"},
                {"action": "click", "text": "Go"},
            ],
        )
        self.assertIsNone(done["stopped"], done)
        titles = [t["title"] for t in browser("tabs")["tabs"]]
        self.assertEqual(titles[0], "Their tab")
        self.assertEqual(titles[-1], "done ok")
        closed = browser("close")
        self.assertEqual(len(closed["tabs"]), len(titles) - 1)
        with self.assertRaisesRegex(core.DesktopError, "tabs you opened"):
            browser("close")

    @unittest.skipUnless(shutil.which("systemd-inhibit"), "no systemd-inhibit")
    def test_keeps_the_computer_awake_until_it_ends(self):
        def inhibitors():
            listing = subprocess.run(
                ["systemd-inhibit", "--list", "--no-pager"],
                capture_output=True,
                text=True,
            ).stdout
            return f"Host session {host}" in listing

        host = self.approved()
        if not inhibitors():
            self.skipTest("no logind inhibitors here")
        core.stop_host()
        wait_for(lambda: not inhibitors())

    def test_expires(self):
        host = self.approved(minutes=0.02)
        wait_for(lambda: core.manifest(host)["status"] == "stopped", timeout=10)
        self.assertIsNone(core.active_host_session())


class HostLaunchTests(unittest.TestCase):
    def test_launches_outside_the_session(self):
        worker = Worker.__new__(Worker)
        worker.env = {"PATH": os.environ["PATH"], "HYPRLAND_INSTANCE_SIGNATURE": "x"}
        calls = []

        def run(argv, **_):
            calls.append(argv)
            return mock.Mock(returncode=0, stdout="ok", stderr="")

        with (
            mock.patch("shutil.which", lambda name, path=None: f"/bin/{name}"),
            mock.patch("subprocess.run", run),
        ):
            result = worker.launch_on_host(["/bin/firefox", "a b"], "/home/u")
        self.assertEqual(result["launched_via"], "hyprctl")
        self.assertEqual(
            calls[0],
            ["hyprctl", "dispatch", "exec", "cd /home/u && exec /bin/firefox 'a b'"],
        )
        worker.env = {"PATH": "/nonexistent"}
        with mock.patch("shutil.which", lambda name, path=None: None):
            with self.assertRaisesRegex(ValueError, "outside the session"):
                worker.launch_on_host(["/bin/firefox"], "/home/u")


class KeysymFallbackTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("labwc"), "labwc unavailable")
    def test_undumpable_compositor(self):
        # Like Hyprland with CAP_SYS_NICE, init's memory map is unreadable.
        from agent_desktop.wayland import Keysyms

        self.assertEqual(Keysyms(1).resolve("Return"), 0xFF0D)


class HostPromptTests(unittest.TestCase):
    def test_click_and_dismiss_are_recorded(self):
        import json
        import subprocess

        for printed, expected in (("default", "approved"), ("", "declined")):
            with (
                tempfile.TemporaryDirectory() as directory,
                self.subTest(printed=printed),
            ):
                fake = Path(directory) / "notify-send"
                fake.write_text(f"#!/bin/sh\nprintf '{printed}'\n")
                fake.chmod(0o755)
                path = Path(directory) / "request.json"
                request = {
                    "id": "r1",
                    "reason": "x",
                    "minutes": 1,
                    "expires": time.time() + 30,
                }
                path.write_text(json.dumps(request))
                env = {**os.environ, "PATH": f"{directory}:{os.environ['PATH']}"}
                subprocess.run(
                    [sys.executable, "-m", "agent_desktop.hostprompt", str(path)],
                    env=env,
                    check=True,
                    timeout=30,
                )
                self.assertEqual(json.loads(path.read_text())["answer"], expected)
