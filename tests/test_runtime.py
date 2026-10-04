"""Real compositor tests, skipped when desktop tools are unavailable."""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from agent_desktop import core
from agent_desktop.wayland import POOL
from agent_desktop.worker import owned_processes


def wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for an observed result")


CHROMIUM = shutil.which("chromium") or shutil.which("chromium-browser")


def running(pid):
    # Zombies count as stopped: a container's PID 1 may never reap orphans.
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    return stat[stat.rindex(")") + 2] not in "ZX"


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
    all(shutil.which(t) for t in ("labwc", "grim", "foot", "dbus-daemon")),
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
        self.previous_display = os.environ.get("DISPLAY")

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
        keep = os.environ.get("DESKTOP_TEST_ARTIFACTS")
        if keep:
            # Screenshots, logs and fixture output for diagnosing CI failures.
            shutil.copytree(
                self.root,
                Path(keep) / self.id(),
                ignore=lambda d, names: [n for n in names if (Path(d) / n).is_socket()],
                symlinks=True,
                dirs_exist_ok=True,
            )
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
                "Session fixture" in w["title"]
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
        started = time.monotonic()
        result = core.destroy(session)
        # Escalation phases take 2 s each; a clean teardown needs none of them.
        self.assertLess(time.monotonic() - started, 2)
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

    def test_keyboard_is_ready_once_window_is_active(self):
        # labwc's default W-Return binding runs this; it must never be reached.
        bindir = self.root / "bin"
        bindir.mkdir()
        marker = self.root / "default-binding-ran"
        fake = bindir / "lab-sensible-terminal"
        fake.write_text(f"#!/bin/sh\ntouch {marker}\n")
        fake.chmod(0o755)
        path = os.environ["PATH"]
        os.environ["PATH"] = f"{bindir}:{path}"
        self.addCleanup(os.environ.__setitem__, "PATH", path)
        session = self.new_session()
        directory = self.root / f"keys-{session}"
        directory.mkdir()
        script = Path(__file__).resolve().parents[1] / "scripts/m0_terminal.py"
        title = f"Keyboard fixture {session}"
        core.request(
            session,
            "launch",
            argv=[
                "foot",
                "--config=/dev/null",
                f"--title={title}",
                sys.executable,
                str(script),
                str(directory),
            ],
        )
        wait_for(directory.joinpath("ready").exists)
        wait_for(
            lambda: any(
                w["title"] == title and "activated" in w["states"]
                for w in core.request(session, "windows")["windows"]
            )
        )
        # No settling delay: the first character must arrive.
        core.request(session, "type", text="discarded")
        core.request(session, "key", key="u", modifiers=["ctrl"])
        with self.assertRaises(core.DesktopError):
            core.request(session, "key", key="NotARealKeyName")
        # More distinct characters than one keymap holds, plus repeats.
        wide = "".join(chr(0x4E00 + i) for i in range(300))
        text = f"aa café λ {wide} zz"
        core.request(session, "type", text=text + "XY")
        core.request(session, "key", key="BackSpace", repeat=2)
        core.request(session, "key", key="Return")
        wait_for(directory.joinpath("typed.txt").exists)
        self.assertEqual(directory.joinpath("typed.txt").read_text(), text)
        # Without labwc's default bindings, logo+Return launches nothing.
        core.request(session, "key", key="Return", modifiers=["logo"])
        time.sleep(1)
        self.assertFalse(marker.exists())

    def test_focus_and_stale_observations(self):
        session = self.new_session()
        first = self.fixture(session)
        second = self.root / f"second-{session}"
        second.mkdir()
        script = Path(__file__).resolve().parents[1] / "scripts/m0_terminal.py"
        core.request(
            session,
            "launch",
            argv=[
                "foot",
                "--config=/dev/null",
                "--title=Second fixture",
                sys.executable,
                str(script),
                str(second),
            ],
        )
        wait_for(second.joinpath("ready").exists)

        def windows():
            return {w["title"]: w for w in core.request(session, "windows")["windows"]}

        wait_for(lambda: "activated" in windows()["Second fixture"]["states"])
        listed = windows()
        self.assertEqual(listed["Session fixture"]["app_id"], "foot")
        self.assertNotIn("activated", listed["Session fixture"]["states"])

        token = core.request(session, "screenshot")["observation"]
        core.request(session, "move", x=5, y=5, observation=token)
        focused = core.request(session, "focus", window=listed["Session fixture"]["id"])
        self.assertIn("activated", focused["window"]["states"])
        # Focus changed after the screenshot: refuse, and send nothing.
        with self.assertRaisesRegex(core.DesktopError, "StaleObservation"):
            core.request(session, "type", text="stale", observation=token)
        with self.assertRaises(core.DesktopError):
            core.request(session, "focus", window="w999")
        token = core.request(session, "screenshot")["observation"]
        core.request(session, "type", text="fresh", observation=token)
        core.request(session, "key", key="Return", observation=token)
        wait_for(first.joinpath("typed.txt").exists)
        core.request(session, "screenshot")  # evidence if the text went elsewhere
        self.assertEqual(first.joinpath("typed.txt").read_text(), "fresh")
        self.assertFalse(second.joinpath("typed.txt").exists())
        # A newly mapped window also invalidates the token.
        core.request(session, "launch", argv=["foot", "--config=/dev/null", "sh"])
        wait_for(lambda: len(core.request(session, "windows")["windows"]) == 3)
        with self.assertRaisesRegex(core.DesktopError, "StaleObservation"):
            core.request(session, "click", x=5, y=5, observation=token)
        # Closing a window must keep the window list working.
        third = next(
            w
            for w in core.request(session, "windows")["windows"]
            if w["title"] not in ("Session fixture", "Second fixture")
        )
        core.request(session, "focus", window=third["id"])
        core.request(session, "key", key="d", modifiers=["ctrl"])
        wait_for(lambda: len(core.request(session, "windows")["windows"]) == 2)

    def test_immediate_typing_after_repeated_focus_switches(self):
        session = self.new_session()
        script = self.root / "receive.py"
        script.write_text(
            "import json, pathlib, sys\n"
            "directory = pathlib.Path(sys.argv[1])\n"
            "directory.joinpath('ready').touch()\n"
            "lines = []\n"
            "for line in sys.stdin:\n"
            "    lines.append(line.rstrip('\\n'))\n"
            "    directory.joinpath('lines.json').write_text(json.dumps(lines))\n"
        )
        directories = [self.root / "left", self.root / "right"]
        for directory in directories:
            directory.mkdir()
            core.request(
                session,
                "launch",
                argv=[
                    "foot",
                    "--config=/dev/null",
                    f"--title={directory.name}",
                    sys.executable,
                    str(script),
                    str(directory),
                ],
            )
            wait_for(directory.joinpath("ready").exists)

        def two_windows():
            ws = core.request(session, "windows")["windows"]
            return ws if len(ws) == 2 else None

        listed = wait_for(two_windows)
        ids = {w["title"]: w["id"] for w in listed}
        expected = {d.name: [] for d in directories}
        for index in range(20):
            directory = directories[index % 2]
            result = core.request(session, "focus", window=ids[directory.name])
            self.assertEqual(result["window"]["id"], ids[directory.name])
            self.assertIn("activated", result["window"]["states"])
            text = f"{directory.name}-{index} café λ"
            # No external focus polling or sleep between focus and input.
            core.request(session, "type", text=text)
            core.request(session, "key", key="Return")
            expected[directory.name].append(text)
        for directory in directories:
            path = directory / "lines.json"

            def received(path=path, directory=directory):
                try:
                    return json.loads(path.read_text()) == expected[directory.name]
                except (OSError, ValueError):
                    return False

            wait_for(received)

    @unittest.skipUnless(shutil.which("mousepad"), "mousepad unavailable")
    def test_editor_file_dialogs_and_save_as(self):
        session = self.new_session()
        folder = self.root / "project with spaces"
        folder.mkdir()
        source = folder / "source café.txt"
        source.write_text("Original draft\n")
        target = folder / "saved λ.txt"
        core.request(session, "launch", argv=["mousepad", "--disable-server"])

        def active():
            return next(
                (
                    w
                    for w in core.request(session, "windows")["windows"]
                    if "activated" in w["states"]
                ),
                None,
            )

        wait_for(active)
        core.request(session, "key", key="o", modifiers=["ctrl"])
        wait_for(lambda: (w := active()) and "Open" in w["title"])
        core.request(session, "screenshot")
        core.request(session, "key", key="l", modifiers=["ctrl"])
        # GTK creates the location entry asynchronously inside the same window;
        # activated toplevel state alone does not imply widget readiness.
        time.sleep(0.2)
        core.request(session, "type", text=str(source))
        # The chooser validates the typed path before enabling its Open action.
        time.sleep(0.3)
        core.request(session, "key", key="Return")
        core.request(session, "screenshot")
        wait_for(lambda: (w := active()) and source.name in w["title"])
        before = core.request(session, "screenshot")
        core.request(session, "key", key="a", modifiers=["ctrl"])
        text = "Plan for Q3\nStatus: FINAL\nOwner: café λ\nBudget: 4200\n"
        core.request(session, "type", text=text)
        core.request(session, "key", key="s", modifiers=["ctrl"])
        wait_for(lambda: source.read_text() == text)
        core.request(session, "key", key="s", modifiers=["ctrl", "shift"])
        wait_for(lambda: (w := active()) and "Save" in w["title"])
        core.request(session, "screenshot")
        core.request(session, "key", key="a", modifiers=["ctrl"])
        core.request(session, "type", text=str(target))
        time.sleep(0.3)
        core.request(session, "key", key="Return")
        wait_for(lambda: target.exists() and target.read_text() == text)
        self.assertEqual(source.read_text(), text)
        wait_for(lambda: (w := active()) and target.name in w["title"])
        after = core.request(session, "screenshot")
        self.assertNotEqual(
            Path(before["path"]).read_bytes(), Path(after["path"]).read_bytes()
        )

    @unittest.skipUnless(shutil.which("mousepad"), "mousepad unavailable")
    def test_editor_clipboards_are_private_to_each_session(self):
        sessions = [self.new_session(), self.new_session()]
        messages = ["First session café λ", "Second session résumé Ω"]
        files = [self.root / "first.txt", self.root / "second.txt"]
        for session, text, path in zip(sessions, messages, files, strict=True):
            path.write_text(text)
            core.request(
                session,
                "launch",
                argv=["mousepad", "--disable-server", str(path)],
            )
            window = wait_for(
                lambda session=session, path=path: next(
                    (
                        w
                        for w in core.request(session, "windows")["windows"]
                        if path.name in w["title"] and "activated" in w["states"]
                    ),
                    None,
                )
            )
            core.request(session, "focus", window=window["id"])
            core.request(session, "key", key="a", modifiers=["ctrl"])
            core.request(session, "key", key="c", modifiers=["ctrl"])
            core.request(session, "key", key="BackSpace")
            core.request(session, "key", key="s", modifiers=["ctrl"])
            wait_for(lambda path=path: path.read_text() == "")
        # Both clipboards have owners before either paste: leaked sharing would
        # replace the first message with the second one.
        for session, text, path in zip(sessions, messages, files, strict=True):
            core.request(session, "key", key="v", modifiers=["ctrl"])
            core.request(session, "key", key="s", modifiers=["ctrl"])
            wait_for(lambda path=path, text=text: path.read_text() == text)
            core.request(session, "screenshot")

    @unittest.skipUnless(shutil.which("xterm"), "xterm unavailable")
    def test_xwayland_application_receives_input(self):
        session = self.new_session()
        x_display = core.request(session, "status")["x_display"]
        if not x_display:
            self.skipTest("compositor has no Xwayland support")
        self.assertNotEqual(x_display, self.previous_display)
        directory = self.root / f"x11-{session}"
        directory.mkdir()
        script = Path(__file__).resolve().parents[1] / "scripts/m0_terminal.py"
        core.request(
            session,
            "launch",
            argv=[
                "xterm",
                "-u8",
                "-title",
                "X11 fixture",
                "-e",
                sys.executable,
                str(script),
                str(directory),
            ],
        )
        wait_for(directory.joinpath("ready").exists, timeout=20)
        wait_for(
            lambda: any(
                w["title"] == "X11 fixture" and "activated" in w["states"]
                for w in core.request(session, "windows")["windows"]
            )
        )
        core.request(session, "type", text="x11 café λ")
        core.request(session, "key", key="Return")
        wait_for(directory.joinpath("mouse-ready").exists)
        self.assertEqual(directory.joinpath("typed.txt").read_text(), "x11 café λ")
        capture = core.request(session, "screenshot")
        core.request(
            session, "click", x=capture["width"] // 2, y=capture["height"] // 2
        )
        wait_for(directory.joinpath("mouse.json").exists)
        processes = {p["command"] for p in core.request(session, "status")["processes"]}
        self.assertIn("Xwayland", processes)

    def test_toolkit_dialogs_receive_text(self):
        cases = {
            "gtk-wayland": ("zenity", "GDK_BACKEND=wayland"),
            "gtk-x11": ("zenity", "GDK_BACKEND=x11"),
            "qt-wayland": ("kdialog", "QT_QPA_PLATFORM=wayland"),
            "qt-x11": ("kdialog", "QT_QPA_PLATFORM=xcb"),
        }
        available = {k: v for k, v in cases.items() if shutil.which(v[0])}
        if not available:
            self.skipTest("zenity and kdialog unavailable")
        session = self.new_session()
        x11 = core.request(session, "status")["x_display"]
        for case, (program, backend) in available.items():
            if backend.endswith(("x11", "xcb")) and not x11:
                continue
            with self.subTest(case=case):
                title = f"Toolkit {case}"
                if program == "zenity":
                    dialog = ["zenity", "--entry", f"--title={title}", "--text=Message"]
                else:
                    dialog = ["kdialog", "--title", title, "--inputbox", "Message"]
                app = core.request(session, "launch", argv=["env", backend, *dialog])

                def active(title=title):
                    return any(
                        w["title"] == title and "activated" in w["states"]
                        for w in core.request(session, "windows")["windows"]
                    )

                wait_for(active, timeout=20)
                text = f"{case} café λ"
                core.request(session, "type", text=text)
                core.request(session, "key", key="Return")

                def exit_code(app=app):
                    for entry in core.request(session, "status")["applications"]:
                        if entry["pid"] == app["pid"]:
                            return entry["exit_code"] is not None
                    return False

                wait_for(exit_code)
                output = Path(app["logs"]).read_text().splitlines()
                self.assertIn(text, output)

    @unittest.skipUnless(shutil.which("xev"), "xev unavailable")
    def test_keys_use_physical_us_codes(self):
        # Applications such as Chromium act on physical codes: a character must
        # never land on another key's code (space on Backspace's code deleted text).
        session = self.new_session()
        if not core.request(session, "status")["x_display"]:
            self.skipTest("compositor has no Xwayland support")
        app = core.request(
            session, "launch", argv=["xev", "-event", "keyboard", "-event", "focus"]
        )
        wait_for(
            lambda: any(
                "activated" in w["states"]
                for w in core.request(session, "windows")["windows"]
            ),
            timeout=20,
        )
        core.request(session, "type", text="a Aλ")
        core.request(session, "key", key="BackSpace")

        def presses():
            log = Path(app["logs"]).read_text()
            found = re.findall(
                r"KeyPress event.*?state (0x[0-9a-f]+), keycode (\d+) "
                r"\(keysym 0x([0-9a-f]+)",
                log,
                re.S,
            )
            return found if len(found) >= 5 else None

        events = [(int(m, 16), int(c), int(k, 16)) for m, c, k in wait_for(presses)]
        by_keysym = {k: (c, m) for m, c, k in events}
        self.assertEqual(by_keysym[0x61], (38, 0))  # a on KEY_A, unshifted
        self.assertEqual(by_keysym[0x20][0], 65)  # space on KEY_SPACE
        self.assertEqual(by_keysym[0x41][0], 38)  # A on KEY_A
        self.assertTrue(by_keysym[0x41][1] & 1)  # with Shift
        self.assertEqual(by_keysym[0xFF08][0], 22)  # BackSpace on KEY_BACKSPACE
        self.assertIn(by_keysym[0x10003BB][0] - 8, POOL)  # λ on a spare code

    @unittest.skipUnless(CHROMIUM, "chromium unavailable")
    def test_chromium_receives_every_character(self):
        session = self.new_session()
        page = self.root / "input.html"
        page.write_text(
            '<!doctype html><meta charset="utf-8"><title>t</title><input id=i '
            'autofocus oninput="document.title=JSON.stringify(i.value)">'
        )
        argv = [
            CHROMIUM,
            f"--user-data-dir={self.root / 'chromium'}",
            "--no-first-run",
            "--ozone-platform=wayland",
            "--disable-gpu",
            "--password-store=basic",
        ]
        if os.geteuid() == 0:  # CI containers; never used for real profiles
            argv.append("--no-sandbox")
        app = core.request(session, "launch", argv=[*argv, page.as_uri()])

        def ready():
            if any(
                w["title"].startswith("t") and "activated" in w["states"]
                for w in core.request(session, "windows")["windows"]
            ):
                return True
            status = core.request(session, "status")["applications"]
            if any(
                a["pid"] == app["pid"] and a["exit_code"] is not None for a in status
            ):
                if "No usable sandbox" in Path(app["logs"]).read_text():
                    # e.g. Ubuntu 24.04 AppArmor; the sandbox is not disabled for users.
                    self.skipTest("Chromium sandbox unavailable in this environment")
                raise AssertionError(Path(app["logs"]).read_text()[-2000:])
            return False

        wait_for(ready, timeout=30)
        # More distinct non-US characters than spare keys, so keys are reused.
        text = "Browser café: " + "".join(chr(0x3B1 + i) for i in range(25)) + " ok!"
        core.request(session, "type", text=text)
        expected = json.dumps(text, ensure_ascii=False)
        wait_for(
            lambda: any(
                w["title"].startswith(expected)
                for w in core.request(session, "windows")["windows"]
            )
        )

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

    def test_killed_supervisor_is_cleaned_up_by_guardian(self):
        session = self.new_session()
        duration = unique_duration()
        core.request(
            session,
            "launch",
            argv=["sh", "-c", f"setsid env -i sleep {duration} >/dev/null 2>&1 &"],
        )
        wait_for(lambda: sleeping(duration))
        info = core.manifest(session)
        os.kill(info["worker_pid"], signal.SIGKILL)
        wait_for(lambda: core.manifest(session)["status"] == "failed")
        self.assertIn("Supervisor", core.manifest(session)["error"])
        self.assertEqual(sleeping(duration), [])
        # The guardian publishes failure after cleaning its children, then exits.
        # It still carries the token during that short interval.
        wait_for(lambda: not running(info["guardian_pid"]))
        self.assertEqual(owned_processes(info["token"]), [])
        self.assertFalse(Path(info["runtime"]).exists())
        with self.assertRaises(core.DesktopError):
            core.request(session, "status")

    def test_destroy_recovers_session_without_supervisors(self):
        session = self.new_session()
        info = core.manifest(session)
        compositor = info["compositor_pid"]
        for pid in (info["guardian_pid"], info["worker_pid"]):
            os.kill(pid, signal.SIGKILL)
        wait_for(
            lambda: (
                {s["session"]: s["status"] for s in core.sessions()}[session]
                == "unavailable"
            )
        )
        result = core.destroy(session)
        self.assertTrue(result["recovered"])
        self.assertTrue(result["runtime_removed"])
        wait_for(lambda: not running(compositor), timeout=5)
        self.assertEqual(owned_processes(info["token"]), [])
        self.assertEqual(core.manifest(session)["status"], "stopped")

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
