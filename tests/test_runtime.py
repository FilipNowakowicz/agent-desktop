"""Real compositor tests, skipped when desktop tools are unavailable."""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

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


def unique_duration():
    # A unique sleep duration identifies test processes without name matching.
    return f"{time.time_ns() % 10**6 + 10**6}.5"


def sleeping(duration):
    found = []
    for path in Path("/proc").iterdir():
        try:
            argv = (path / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if argv[:2] == [b"sleep", duration.encode()]:
            found.append(int(path.name))
    return found


class RoutingTests(unittest.TestCase):
    def test_invalid_session_identifiers(self):
        for session in ("", "../main", "/tmp/other", None, "a" * 13):
            with self.subTest(session=session), self.assertRaises(core.DesktopError):
                core.request(session, "type", text="must not reach a display")

    def test_unknown_session(self):
        with self.assertRaises(core.DesktopError):
            core.request("0" * 12, "click", x=0, y=0)

    def test_invalid_mode(self):
        with self.assertRaises(core.DesktopError):
            core.create("physical")


@unittest.skipUnless(
    all(
        shutil.which(t)
        for t in ("labwc", "grim", "wtype", "wlrctl", "foot", "dbus-daemon")
    ),
    "desktop tools unavailable",
)
class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-test-")
        self.root = Path(self.temporary.name)
        self.previous = {
            k: os.environ.get(k) for k in ("AGENT_DESKTOP_STATE_DIR", "XDG_RUNTIME_DIR")
        }
        os.environ["AGENT_DESKTOP_STATE_DIR"] = str(self.root / "state")
        if not os.environ.get("XDG_RUNTIME_DIR"):
            (self.root / "run").mkdir(mode=0o700)
            os.environ["XDG_RUNTIME_DIR"] = str(self.root / "run")
        self.created = []

    def tearDown(self):
        for session in self.created:
            info = core.manifest(session)
            if info["status"] == "ready":
                core.destroy(session)
            wait_for(lambda info=info: not owned_processes(info["token"]))
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temporary.cleanup()

    def new_session(self, mode="headless"):
        session = core.create(mode)["session"]
        self.created.append(session)
        return session

    def fixture(self, session):
        directory = self.root / session
        directory.mkdir()
        script = Path(__file__).resolve().parents[1] / "scripts/m0_terminal.py"
        core.request(
            session,
            "launch",
            argv=[
                "foot",
                "--config=/dev/null",
                "--window-size-pixels=800x500",
                "--title=Session fixture",
                sys.executable,
                str(script),
                str(directory),
            ],
        )
        wait_for((directory / "ready").exists)
        time.sleep(0.4)
        return directory

    def exercise(self, mode):
        session = self.new_session(mode)
        fixture = self.fixture(session)
        self.assertTrue(
            any(
                "Session fixture" in w
                for w in core.request(session, "windows")["windows"]
            )
        )
        before = core.request(session, "screenshot")
        self.assertGreater(before["width"], 0)
        for operation, args in (
            ("click", {"x": -1, "y": 0}),
            ("click", {"x": 0, "y": 0, "button": "invalid"}),
            ("launch", {"argv": ["/not/an/executable"]}),
        ):
            with self.assertRaises(core.DesktopError):
                core.request(session, operation, **args)
        self.assertEqual(core.request(session, "status")["status"], "ready")
        core.request(session, "type", text="private café λ")
        core.request(session, "key", key="Return")
        wait_for((fixture / "mouse-ready").exists)
        self.assertEqual((fixture / "typed.txt").read_text(), "private café λ")
        current = core.request(session, "screenshot")
        core.request(
            session, "click", x=current["width"] // 2, y=current["height"] // 2
        )
        wait_for((fixture / "mouse.json").exists)
        self.assertEqual(json.loads((fixture / "mouse.json").read_text())["button"], 0)
        time.sleep(0.2)
        after = core.request(session, "screenshot")
        self.assertNotEqual(
            Path(before["path"]).read_bytes(), Path(after["path"]).read_bytes()
        )
        info = core.manifest(session)
        result = core.destroy(session)
        self.assertTrue(result["runtime_removed"])
        self.assertFalse(Path(info["runtime"]).exists())
        self.assertEqual(core.destroy(session)["status"], "stopped")
        with self.assertRaises(core.DesktopError):
            core.request(session, "type", text="after shutdown")

    def test_headless_round_trip(self):
        self.exercise("headless")

    def test_cli_honors_runtime_executable_environment(self):
        alias = self.root / "chosen-labwc"
        alias.symlink_to(shutil.which("labwc"))
        environment = os.environ.copy()
        environment["AGENT_DESKTOP_LABWC"] = str(alias)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from agent_desktop.cli import main; raise SystemExit(main())",
                "create",
            ],
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )
        session = json.loads(result.stdout)["session"]
        self.created.append(session)
        self.assertEqual(core.manifest(session)["tools"]["labwc"], str(alias))

    @unittest.skipUnless(
        os.environ.get("DESKTOP_TEST_VISIBLE") == "1", "visible mode opt-in"
    )
    def test_visible_round_trip(self):
        self.exercise("visible")

    def test_two_sessions_have_distinct_input(self):
        first, second = self.new_session(), self.new_session()
        fixture_a, fixture_b = self.fixture(first), self.fixture(second)
        core.request(first, "type", text="only first")
        core.request(first, "key", key="Return")
        wait_for((fixture_a / "typed.txt").exists)
        self.assertFalse((fixture_b / "typed.txt").exists())
        core.request(second, "type", text="only second")
        core.request(second, "key", key="Return")
        wait_for((fixture_b / "typed.txt").exists)
        self.assertEqual((fixture_a / "typed.txt").read_text(), "only first")
        self.assertEqual((fixture_b / "typed.txt").read_text(), "only second")

    def test_absolute_pointer_drag_and_scroll_reach_application(self):
        session = self.new_session()
        directory = self.root / f"pointer-{session}"
        directory.mkdir()
        script = Path(__file__).resolve().parents[1] / "scripts/pointer_fixture.py"
        core.request(
            session,
            "launch",
            argv=[
                "foot",
                "--config=/dev/null",
                "--maximized",
                sys.executable,
                str(script),
                str(directory),
            ],
        )
        wait_for((directory / "ready").exists)
        time.sleep(0.4)
        log = directory / "events.jsonl"

        def complete():
            # The fixture may be mid-write; ignore an unterminated final line.
            return log.read_text().split("\n")[:-1] if log.exists() else []

        def events(count):
            def read():
                lines = complete()
                return lines if len(lines) >= count else None

            return [json.loads(line) for line in wait_for(read)]

        def settled():
            # Wait until no further events arrive, then return all of them.
            previous = -1
            while True:
                time.sleep(0.2)
                lines = complete()
                if len(lines) == previous:
                    return [json.loads(line) for line in lines]
                previous = len(lines)

        with self.assertRaises(core.DesktopError):
            core.request(session, "click", x=-1, y=0)
        core.request(session, "click", x=400, y=300)
        core.request(session, "click", x=400, y=300)
        core.request(session, "click", x=800, y=300)
        clicks = events(6)
        self.assertEqual([e["pressed"] for e in clicks], [True, False] * 3)
        # Absolute positioning: repeated clicks land on the same cell.
        self.assertEqual(clicks[0]["column"], clicks[2]["column"])
        self.assertEqual(clicks[0]["row"], clicks[4]["row"])
        self.assertGreater(clicks[4]["column"], clicks[0]["column"])

        core.request(session, "drag", x=300, y=400, to_x=900, to_y=450)
        drag = settled()[6:]
        press, release = drag[0], drag[-1]
        motion = drag[1:-1]
        self.assertTrue(press["pressed"] and not press["motion"])
        self.assertFalse(release["pressed"] or release["motion"])
        self.assertGreaterEqual(len(motion), 3)
        self.assertTrue(
            all(e["motion"] and e["pressed"] and e["button"] == 0 for e in motion)
        )
        columns = [e["column"] for e in drag]
        self.assertEqual(columns, sorted(columns))
        self.assertGreater(release["column"], press["column"])
        self.assertGreater(release["row"], press["row"])

        before = len(drag) + 6
        core.request(session, "scroll", dy=120)
        self.assertTrue(any(e["wheel"] for e in events(before + 1)[before:]))

        for arguments in ({"to_x": 5000, "to_y": 0}, {"to_x": -1, "to_y": 10}):
            with self.assertRaises(core.DesktopError):
                core.request(session, "drag", x=10, y=10, **arguments)

    @unittest.skipUnless(shutil.which("wlr-randr"), "wlr-randr unavailable")
    def test_output_changes_update_bounds_and_scale_fails_closed(self):
        session = self.new_session()
        environment = {
            **os.environ,
            "WAYLAND_DISPLAY": core.manifest(session)["wayland_display"],
        }

        def randr(*arguments):
            subprocess.run(
                ["wlr-randr", "--output", "HEADLESS-1", *arguments],
                env=environment,
                check=True,
                capture_output=True,
            )

        randr("--custom-mode", "1024x768")
        capture = core.request(session, "screenshot")
        self.assertEqual((capture["width"], capture["height"]), (1024, 768))
        core.request(session, "click", x=1000, y=700)
        with self.assertRaises(core.DesktopError):
            core.request(session, "click", x=1100, y=10)
        randr("--scale", "2")
        with self.assertRaisesRegex(core.DesktopError, "scale"):
            core.request(session, "move", x=10, y=10)

    def test_daemonizing_application_without_token_is_cleaned_up(self):
        session = self.new_session()
        duration = unique_duration()
        core.request(
            session,
            "launch",
            argv=[
                "sh",
                "-c",
                f"setsid env -i sleep {duration} </dev/null >/dev/null 2>&1 &",
            ],
        )
        pid = wait_for(lambda: sleeping(duration))[0]
        self.assertNotIn(
            b"AGENT_DESKTOP_SESSION_TOKEN",
            Path(f"/proc/{pid}/environ").read_bytes(),
        )
        status = core.request(session, "status")
        self.assertIn(pid, [p["pid"] for p in status["processes"]])
        core.destroy(session)
        wait_for(lambda: not sleeping(duration), timeout=5)

    def test_private_bus_and_term_ignoring_forks_are_cleaned_up(self):
        session = self.new_session()
        runtime = core.manifest(session)["runtime"]
        output = self.root / "bus-address"
        duration = unique_duration()
        core.request(
            session,
            "launch",
            argv=[
                "sh",
                "-c",
                f'echo "$DBUS_SESSION_BUS_ADDRESS" > {output}; trap "" TERM; '
                f"while :; do sleep {duration} & sleep 0.02; done",
            ],
        )
        wait_for(lambda: len(sleeping(duration)) > 3)
        self.assertEqual(output.read_text().strip(), f"unix:path={runtime}/bus")
        # Activated services inherit the bus environment, never host display/home.
        bus = next(
            p["pid"]
            for p in core.request(session, "status")["processes"]
            if p["command"] == "dbus-daemon"
        )
        environment = dict(
            entry.split(b"=", 1)
            for entry in Path(f"/proc/{bus}/environ").read_bytes().split(b"\0")
            if b"=" in entry
        )
        self.assertTrue(environment[b"HOME"].startswith(str(self.root).encode()))
        self.assertEqual(environment[b"XDG_RUNTIME_DIR"], runtime.encode())
        self.assertNotIn(b"HYPRLAND_INSTANCE_SIGNATURE", environment)
        self.assertEqual(
            environment[b"WAYLAND_DISPLAY"],
            core.manifest(session)["wayland_display"].encode(),
        )
        core.destroy(session)
        self.assertEqual(sleeping(duration), [])

    def test_crashes_preserve_errors_and_cleanup(self):
        session = self.new_session()
        app = core.request(
            session,
            "launch",
            argv=[sys.executable, "-c", "raise RuntimeError('fixture app failure')"],
        )
        wait_for(
            lambda: any(
                p["exit_code"] is not None
                for p in core.request(session, "status")["applications"]
            )
        )
        self.assertIn("fixture app failure", Path(app["logs"]).read_text())
        info = core.manifest(session)
        os.kill(info["compositor_pid"], signal.SIGKILL)
        wait_for(lambda: core.manifest(session)["status"] == "failed")
        self.assertFalse(Path(info["runtime"]).exists())
        with self.assertRaises(core.DesktopError):
            core.request(session, "screenshot")


if __name__ == "__main__":
    unittest.main()
