"""F3 lifecycle events, each checked against docs/project/LIFETIMES.md.

Every test keeps an unrelated process outside the session running `sleep D`,
the same command line as a process inside it, and checks that only the
session's own processes were stopped. Private sessions only.
"""

import functools
import hashlib
import http.server
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from test_runtime import running, sleeping, unique_duration, wait_for
from test_takeover import connect

from agent_desktop import core, operations, viewer
from agent_desktop.worker import descendants, owned_processes, start_time
from scripts import lifecycle_stress

DESKTOP = all(shutil.which(t) for t in ("labwc", "grim", "foot", "dbus-daemon"))
FIXTURE = Path(__file__).resolve().parents[1] / "scripts/m0_terminal.py"
CLIENT = "f3-client"

# A viewer stand-in: completes the RFB handshake on the socket it is given
# (the last argument, as vncviewer gets it), then closes, as a person would.
FAKE_VIEWER = f"""#!{sys.executable}
import socket, struct, sys
def receive(c, n):
    data = b""
    while len(data) < n:
        chunk = c.recv(n - len(data))
        if not chunk:
            raise SystemExit("closed")
        data += chunk
    return data
c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
c.settimeout(5)
c.connect(sys.argv[-1])
receive(c, 12)
c.sendall(b"RFB 003.008\\n")
receive(c, receive(c, 1)[0])
c.sendall(b"\\1")
receive(c, 4)
c.sendall(b"\\1")
header = receive(c, 24)
receive(c, struct.unpack(">I", header[20:])[0])
c.close()
"""


class LifecycleCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-f3-")
        self.root = Path(self.temporary.name)
        self.previous = {
            k: os.environ.get(k) for k in ("AGENT_DESKTOP_STATE_DIR", "XDG_RUNTIME_DIR")
        }
        (self.root / "runtime").mkdir(mode=0o700)
        os.environ["AGENT_DESKTOP_STATE_DIR"] = str(self.root / "state")
        os.environ["XDG_RUNTIME_DIR"] = str(self.root / "runtime")
        self.created = []
        self.duration = unique_duration()
        environment = {
            k: v for k, v in os.environ.items() if k != "AGENT_DESKTOP_SESSION_TOKEN"
        }
        self.unrelated = subprocess.Popen(
            ["sleep", self.duration], env=environment, start_new_session=True
        )

    def tearDown(self):
        try:
            for session in self.created:
                info = core.manifest(session)
                if info["status"] == "ready":
                    core.destroy(session)
                wait_for(lambda info=info: not owned_processes(info["token"]))
        finally:
            self.unrelated.kill()
            self.unrelated.wait()
            for key, value in self.previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            self.temporary.cleanup()

    def create(self, profile=None):
        result = core.create(profile=profile)
        self.created.append(result["session"])
        return result

    def assert_unrelated_running(self):
        self.assertIsNone(self.unrelated.poll(), "an unrelated process was stopped")

    def session_daemons(self):
        """`sleep D` processes other than the unrelated one."""
        return sorted(set(sleeping(self.duration)) - {self.unrelated.pid})

    def start_daemon(self, session):
        """A child that leaves the session's process group and environment."""
        core.request(
            session,
            "launch",
            argv=[
                "sh",
                "-c",
                f"setsid env -i sleep {self.duration} </dev/null >/dev/null 2>&1 &",
            ],
        )
        return wait_for(self.session_daemons)

    def fixture(self, session, name, controller=None):
        directory = self.root / name
        directory.mkdir()
        app = core.request(
            session,
            "launch",
            controller,
            argv=[
                "foot",
                "--config=/dev/null",
                "--window-size-pixels=800x500",
                sys.executable,
                str(FIXTURE),
                str(directory),
            ],
        )
        wait_for((directory / "ready").exists, timeout=15)
        time.sleep(0.4)
        return directory, app

    def run_shell(self, session, script, controller=None):
        app = core.request(session, "launch", controller, argv=["sh", "-c", script])
        wait_for(lambda: self.exit_code(session, app["pid"]) is not None)
        return app

    def exit_code(self, session, pid):
        for entry in core.request(session, "status")["applications"]:
            if entry["pid"] == pid:
                return entry["exit_code"]
        return None

    def finished(self, session, ident, timeout=15):
        return wait_for(
            lambda: (
                r
                if (r := operations.status(session, ident))["state"]
                in operations.TERMINAL
                else None
            ),
            timeout=timeout,
        )

    def record_kept(self, session, screenshot):
        """The session record keeps manifest, logs, trace and screenshots."""
        root = core.session_path(session)
        for name in ("session.json", "session.log", "trace.jsonl"):
            self.assertTrue((root / name).is_file(), name)
        self.assertTrue((root / "screenshots" / screenshot).is_file())
        self.assertGreater(len(core.trace(session)["records"]), 0)

    def runtime_gone(self, info):
        """Processes, sockets and the controller lease go with the runtime."""
        wait_for(lambda: not owned_processes(info["token"]), timeout=15)
        self.assertFalse(Path(info["runtime"]).exists())
        self.assertEqual(self.session_daemons(), [])
        with self.assertRaises(core.DesktopError):
            core.request(info["id"], "status")
        self.assert_unrelated_running()


@unittest.skipUnless(DESKTOP, "desktop tools unavailable")
class ApplicationRestartTests(LifecycleCase):
    def test_application_killed_and_restarted_in_its_session(self):
        session = self.create()["session"]
        info = core.manifest(session)
        home = core.session_path(session) / "home"
        first, app = self.fixture(session, "first")
        sibling = self.start_daemon(session)
        self.run_shell(session, 'echo saved > "$HOME/notes.txt"', CLIENT)
        self.assertEqual(core.request(session, "status")["lease"]["holder"], CLIENT)
        terminal = [app["pid"], *descendants(app["pid"])]

        os.kill(app["pid"], signal.SIGKILL)
        wait_for(lambda: self.exit_code(session, app["pid"]) == -signal.SIGKILL)
        wait_for(lambda: not any(running(p) for p in terminal))
        status = core.request(session, "status")
        self.assertEqual(status["status"], "ready")
        self.assertEqual(status["lease"]["holder"], CLIENT)
        self.assertEqual(self.session_daemons(), sibling)
        self.assert_unrelated_running()
        self.assertEqual((home / "notes.txt").read_text(), "saved\n")
        self.assertTrue(Path(app["logs"]).is_file())

        # The same application again: it gets input and sees the saved file.
        second, again = self.fixture(session, "second", CLIENT)
        self.assertNotEqual(again["pid"], app["pid"])
        shot = core.request(session, "screenshot", CLIENT)
        core.request(session, "type", CLIENT, text="after restart café")
        core.request(session, "key", CLIENT, key="Return")
        wait_for((second / "typed.txt").exists)
        self.assertEqual((second / "typed.txt").read_text(), "after restart café")
        self.assertFalse((first / "typed.txt").exists())
        output = self.root / "read-back"
        self.run_shell(session, f'cat "$HOME/notes.txt" > {output}', CLIENT)
        self.assertEqual(output.read_text(), "saved\n")

        core.destroy(session)
        self.runtime_gone(info)
        self.assertFalse(home.exists())
        self.assertFalse((core.session_path(session) / "config").exists())
        self.assertEqual(core.manifest(session)["status"], "stopped")
        self.record_kept(session, Path(shot["path"]).name)
        # Both terminals' logs stay with the record.
        self.assertTrue(Path(app["logs"]).is_file())
        self.assertTrue(Path(again["logs"]).is_file())


PAGE = """<!doctype html><meta charset="utf-8"><title>Restart</title>
<p id="cookie"></p><script>
if (location.search == "?set") document.cookie = "kept=yes; max-age=3600; path=/";
document.getElementById("cookie").textContent = document.cookie || "none";
</script>"""
BODY = bytes(range(256)) * 64


class Files(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        if self.path.startswith("/file.bin"):
            self.send_header("Content-Disposition", 'attachment; filename="file.bin"')
        super().end_headers()

    def log_message(self, *_):
        pass


@unittest.skipUnless(
    DESKTOP and shutil.which("firefox"), "desktop tools or Firefox unavailable"
)
class FirefoxRestartTests(LifecycleCase):
    def setUp(self):
        super().setUp()
        served = self.root / "served"
        served.mkdir()
        (served / "page.html").write_text(PAGE)
        (served / "file.bin").write_bytes(BODY)
        self.server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(Files, directory=served)
        )
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def browser(self, action, **arguments):
        return core.request(self.session, "browser", action=action, **arguments)

    def test_firefox_restart_keeps_profile_files_and_drops_old_tabs(self):
        self.session = session = self.create("f3-browser")["session"]
        info = core.manifest(session)
        home = Path(info["home"])
        started = self.browser("start", url=f"{self.base}/page.html?set")
        old = started["tabs"][0]["context"]
        self.assertTrue(self.browser("wait", text="kept=yes", timeout=30)["satisfied"])
        receipt = self.browser("download", url=f"{self.base}/file.bin")
        self.assertEqual(receipt["sha256"], hashlib.sha256(BODY).hexdigest())
        downloaded = Path(receipt["file"])
        self.assertTrue(downloaded.is_relative_to(home))
        job = operations.start(
            session,
            [{"action": "find", "selector": "#cookie", "context": old}],
            kind="browser",
        )
        self.assertEqual(
            self.finished(session, job["operation_id"])["state"], "completed"
        )
        firefox = core.request(session, "status")["applications"][0]["pid"]
        tree = {p: start_time(p) for p in [firefox, *descendants(firefox)]}
        self.assertGreater(len(tree), 1)

        # A clean exit, as a person closing it would; content processes follow.
        os.kill(firefox, signal.SIGTERM)
        wait_for(lambda: self.exit_code(session, firefox) is not None, timeout=30)
        wait_for(
            lambda: all(start_time(p) != begun for p, begun in tree.items()),
            timeout=15,
        )
        self.assertEqual(core.request(session, "status")["status"], "ready")
        with self.assertRaisesRegex(core.DesktopError, "No bridged Firefox"):
            self.browser("tabs")
        self.assert_unrelated_running()

        restarted = self.browser("start", url=f"{self.base}/page.html")
        new = restarted["tabs"][0]["context"]
        self.assertNotEqual(new, old)
        with self.assertRaisesRegex(core.DesktopError, "target_lost"):
            self.browser("find", selector="#cookie", context=old)
        self.assertTrue(self.browser("wait", text="kept=yes", timeout=30)["satisfied"])
        self.assertEqual(
            hashlib.sha256(downloaded.read_bytes()).hexdigest(), receipt["sha256"]
        )
        record = operations.status(session, job["operation_id"])
        self.assertEqual(record["state"], "completed")
        self.assertEqual(record["steps"][0]["request"]["context"], old)

        core.destroy(session)
        self.runtime_gone(info)
        # The profile keeps the download and the login cookie for later sessions.
        self.assertTrue(downloaded.is_file())
        self.assertFalse(core.profiles()[0]["in_use"])
        self.assertEqual(
            operations.status(session, job["operation_id"])["state"], "completed"
        )


@unittest.skipUnless(DESKTOP, "desktop tools unavailable")
class RuntimeLossTests(LifecycleCase):
    def test_compositor_loss_then_a_new_session_on_the_profile(self):
        session = self.create("f3-runtime")["session"]
        info = core.manifest(session)
        home = Path(info["home"])
        self.run_shell(session, 'echo before > "$HOME/kept.txt"', CLIENT)
        shot = core.request(session, "screenshot", CLIENT)
        core.request(session, "lease", CLIENT, action="release")
        done = operations.start(session, [{"action": "wait", "seconds": 0.1}])
        self.assertEqual(
            self.finished(session, done["operation_id"])["state"], "completed"
        )
        self.start_daemon(session)
        busy = operations.start(session, [{"action": "wait", "seconds": 5}])
        wait_for(
            lambda: (
                operations.status(session, busy["operation_id"])["steps"][0][
                    "dispatch_state"
                ]
                == "dispatching"
            )
        )

        started = time.monotonic()
        os.kill(info["compositor_pid"], signal.SIGKILL)
        failed = wait_for(
            lambda: (m := core.manifest(session))["status"] == "failed" and m,
            timeout=20,
        )
        detected = time.monotonic() - started
        print(f"\ncompositor loss reported as failed after {detected:.2f} s")
        self.assertIn("compositor", failed["error"])
        wait_for(lambda: not running(info["guardian_pid"]), timeout=15)
        self.runtime_gone(info)

        self.record_kept(session, Path(shot["path"]).name)
        self.assertEqual(
            operations.status(session, done["operation_id"])["state"], "completed"
        )
        lost = self.finished(session, busy["operation_id"])
        self.assertIn(lost["state"], ("delivery_unknown", "stopped"))
        self.assertNotEqual(lost["steps"][0]["dispatch_state"], "observed")
        self.assertEqual((home / "kept.txt").read_text(), "before\n")
        profile = core.profiles()[0]
        self.assertFalse(profile["in_use"])
        self.assertEqual(profile["last_session"]["status"], "failed")

        # The runtime is recreated, not restarted: a new session on the profile.
        result = self.create("f3-runtime")
        self.assertEqual(result["previous_session"]["status"], "failed")
        self.assertEqual(result["previous_session"]["session"], session)
        again = result["session"]
        self.assertIsNone(core.request(again, "status")["lease"])
        output = self.root / "read-back"
        self.run_shell(again, f'cat "$HOME/kept.txt" > {output}')
        self.assertEqual(output.read_text(), "before\n")
        self.assertEqual(operations.list_operations(again), [])
        core.destroy(again)
        self.assert_unrelated_running()

    def test_compositor_loss_during_typing_is_uncertain(self):
        session = self.create()["session"]
        info = core.manifest(session)
        self.fixture(session, "fixture")
        outcome = {}

        def typing():
            try:
                core.request(session, "type", text="x" * 3000)
                outcome["reply"] = "delivered"
            except core.DeliveryUnknown:
                outcome["reply"] = "uncertain"
            except core.DesktopError as error:
                outcome["reply"] = f"refused: {error}"

        thread = threading.Thread(target=typing)
        thread.start()
        time.sleep(1)
        started = time.monotonic()
        os.kill(info["compositor_pid"], signal.SIGKILL)
        thread.join(30)
        replied = time.monotonic() - started
        wait_for(lambda: core.manifest(session)["status"] == "failed", timeout=20)
        print(f"\ntyping reply {replied:.2f} s after compositor loss")
        # Typing had started, so it is never reported as delivered or not sent.
        self.assertEqual(outcome.get("reply"), "uncertain")
        self.assertLess(replied, 5)
        wait_for(lambda: not running(info["guardian_pid"]), timeout=15)
        self.runtime_gone(info)
        self.assertIn(
            "type", [r.get("operation") for r in core.trace(session)["records"]]
        )


@unittest.skipUnless(DESKTOP, "desktop tools unavailable")
class SupervisorLossTests(LifecycleCase):
    def prepare(self, profile=None):
        session = self.create(profile)["session"]
        info = core.manifest(session)
        self.run_shell(session, 'echo before > "$HOME/kept.txt"', CLIENT)
        shot = core.request(session, "screenshot", CLIENT)
        app = core.request(session, "launch", CLIENT, argv=["sleep", self.duration])
        core.request(session, "lease", CLIENT, action="release")
        job = operations.start(session, [{"action": "wait", "seconds": 3}])
        wait_for(
            lambda: (
                operations.status(session, job["operation_id"])["steps"][0][
                    "dispatch_state"
                ]
                == "dispatching"
            )
        )
        (Path(info["runtime"]) / "take-requested").touch()
        return session, info, Path(shot["path"]).name, app, job

    def test_worker_killed_and_the_guardian_cleans_up(self):
        session, info, shot, app, job = self.prepare("f3-worker")
        os.kill(info["worker_pid"], signal.SIGKILL)
        failed = wait_for(
            lambda: (m := core.manifest(session))["status"] == "failed" and m,
            timeout=15,
        )
        self.assertIn("Supervisor", failed["error"])
        wait_for(lambda: not running(info["guardian_pid"]), timeout=15)
        self.runtime_gone(info)
        self.assertFalse(running(app["pid"]))

        self.record_kept(session, shot)
        record = self.finished(session, job["operation_id"])
        self.assertEqual(record["state"], "delivery_unknown")
        self.assertEqual(record["steps"][0]["dispatch_state"], "uncertain")
        self.assertEqual(record["lease_cleanup"], "unknown")
        self.assertEqual((Path(info["home"]) / "kept.txt").read_text(), "before\n")
        result = self.create("f3-worker")
        self.assertEqual(result["previous_session"]["status"], "failed")
        self.assertIsNone(core.request(result["session"], "status")["lease"])
        self.assertEqual(core.request(result["session"], "control")["owner"], "agent")

    def test_both_supervisors_killed_until_destroy_recovers(self):
        session, info, shot, app, job = self.prepare()
        home = core.session_path(session) / "home"
        for pid in (info["guardian_pid"], info["worker_pid"]):
            os.kill(pid, signal.SIGKILL)
        wait_for(
            lambda: (
                {s["session"]: s["status"] for s in core.sessions()}[session]
                == "unavailable"
            )
        )
        # Nothing cleans up yet: the application and the home stay.
        self.assertTrue(running(app["pid"]))
        self.assertTrue((home / "kept.txt").is_file())
        # The job outlives the supervisors and ends on its own: its wait
        # step needs the worker for its last read.
        record = self.finished(session, job["operation_id"])
        self.assertIn(record["state"], ("delivery_unknown", "stopped"))
        self.assertNotEqual(record["steps"][0]["dispatch_state"], "observed")
        print(
            f"\njob after both supervisors died: {record['state']}, "
            f"{record['steps'][0]['dispatch_state']}: {record['result'].get('stopped')}"
        )

        result = core.destroy(session)
        self.assertTrue(result["recovered"])
        self.assertTrue(result["runtime_removed"])
        self.runtime_gone(info)
        self.assertFalse(running(app["pid"]))
        self.assertFalse(home.exists())
        self.assertFalse((core.session_path(session) / "config").exists())
        manifest = core.manifest(session)
        self.assertEqual((manifest["status"], manifest["recovered"]), ("stopped", True))
        self.record_kept(session, shot)
        self.assertEqual(
            operations.status(session, job["operation_id"])["state"], record["state"]
        )

    @unittest.skipUnless(shutil.which("wayvnc"), "wayvnc unavailable")
    def test_worker_killed_during_a_takeover(self):
        session = self.create("f3-take")["session"]
        info = core.manifest(session)
        taken = core.request(session, "take")
        self.assertEqual(taken["owner"], "human")
        connection = connect(taken["socket"])
        try:
            os.kill(info["worker_pid"], signal.SIGKILL)
            wait_for(lambda: core.manifest(session)["status"] == "failed", timeout=15)
            wait_for(lambda: not running(info["guardian_pid"]), timeout=15)
        finally:
            connection.close()
        # The takeover server carried the token and went with the session.
        self.runtime_gone(info)
        self.assertFalse(Path(taken["socket"]).exists())
        self.assertFalse(core.profiles()[0]["in_use"])
        result = self.create("f3-take")
        self.assertEqual(result["previous_session"]["status"], "failed")
        control = core.request(result["session"], "control")
        self.assertEqual(control["owner"], "agent")
        self.assertIsNone(control["lease"])

    @unittest.expectedFailure
    def test_env_cleared_daemon_is_stopped_by_recovery(self):
        """Known limit (CAPABILITY_MATRIX: detached descendants that clear
        their environment). With both supervisors gone, recovery finds
        processes by token only, so `setsid env -i` children are left."""
        session = self.create()["session"]
        info = core.manifest(session)
        self.start_daemon(session)
        self.addCleanup(self.stop_session_daemons)
        for pid in (info["guardian_pid"], info["worker_pid"]):
            os.kill(pid, signal.SIGKILL)
        wait_for(lambda: not core.supervisor_alive(info))
        self.assertTrue(core.destroy(session)["recovered"])
        self.assertEqual(owned_processes(info["token"]), [])
        self.assertEqual(self.session_daemons(), [])

    def stop_session_daemons(self):
        for pid in self.session_daemons():
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


@unittest.skipUnless(
    DESKTOP and shutil.which("wayvnc"), "desktop tools or wayvnc unavailable"
)
class ViewerClosureTests(LifecycleCase):
    CLOSURES = 5

    def wayvnc(self, session):
        return sorted(
            p["pid"]
            for p in core.request(session, "status")["processes"]
            if p["command"] == "wayvnc"
        )

    def test_repeated_viewer_closure_keeps_the_session(self):
        session = self.create()["session"]
        info = core.manifest(session)
        fixture, _ = self.fixture(session, "fixture")
        core.request(session, "lease", CLIENT, seconds=300)
        fake = self.root / "fake-viewer"
        fake.write_text(FAKE_VIEWER)
        fake.chmod(0o700)

        server = core.request(session, "viewer_start")
        servers = self.wayvnc(session)
        self.assertEqual(len(servers), 1)
        for closure in range(self.CLOSURES):
            with self.subTest(read_only=closure):
                connection = connect(server["socket"])
                connection.close()
                time.sleep(0.2)
                again = core.request(session, "viewer_start")
                self.assertEqual(again["socket"], server["socket"])
                self.assertEqual(self.wayvnc(session), servers)
                status = core.request(session, "status")
                self.assertEqual(status["status"], "ready")
                self.assertEqual(status["lease"]["holder"], CLIENT)
        # The CLI viewer path: closing it reports the desktop still running.
        closed = viewer.view(session, viewer=str(fake))
        self.assertEqual(
            (closed["viewer_closed"], closed["desktop_running"]), (True, True)
        )
        self.assertEqual(self.wayvnc(session), servers)

        epoch = core.request(session, "control")["epoch"]
        for closure in range(self.CLOSURES):
            with self.subTest(take=closure):
                returned = viewer.take(session, viewer=str(fake), keyboard="us")
                self.assertEqual(returned["control"], "agent")
                self.assertIsNone(returned["release_error"])
                self.assertTrue(returned["desktop_running"])
                control = core.request(session, "control")
                self.assertEqual(control["owner"], "agent")
                # Taking and returning control each advance the epoch.
                self.assertEqual(control["epoch"], epoch + 2 * (closure + 1))
                self.assertTrue(control["needs_screenshot"])
                self.assertEqual(control["lease"]["holder"], CLIENT)
                self.assertFalse((Path(info["runtime"]) / "takeover.sock").exists())
                # Only the read-only server remains; each takeover server exited.
                wait_for(lambda: self.wayvnc(session) == servers)
                core.request(session, "screenshot", CLIENT)

        core.request(session, "type", CLIENT, text="after viewers")
        core.request(session, "key", CLIENT, key="Return")
        wait_for((fixture / "typed.txt").exists)
        self.assertEqual((fixture / "typed.txt").read_text(), "after viewers")
        core.destroy(session)
        self.runtime_gone(info)
        self.assertFalse(any(running(p) for p in servers))
        self.assertEqual(core.manifest(session)["status"], "stopped")
        for name in ("viewer.log", "takeover.log"):
            self.assertTrue((core.session_path(session) / name).is_file(), name)


@unittest.skipUnless(DESKTOP, "desktop tools unavailable")
class RepeatedCycleTests(unittest.TestCase):
    CYCLES = 4

    def test_repeated_create_use_destroy_cycles(self):
        with tempfile.TemporaryDirectory(prefix="desktop-cycles-") as directory:
            root = Path(directory)
            previous = {
                k: os.environ.get(k)
                for k in ("AGENT_DESKTOP_STATE_DIR", "XDG_RUNTIME_DIR")
            }
            (root / "runtime").mkdir(mode=0o700)
            os.environ["AGENT_DESKTOP_STATE_DIR"] = str(root / "state")
            os.environ["XDG_RUNTIME_DIR"] = str(root / "runtime")
            try:
                report = lifecycle_stress.run(root, self.CYCLES, profile_every=2)
            finally:
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
        print(
            f"\n{report['passed']}/{report['cycles']} cycles in "
            f"{report['total_seconds']} s, per cycle {report['cycle_seconds']}, "
            f"descriptors {report['open_descriptors']}"
        )
        self.assertEqual(report["failures"], [])
        self.assertEqual(report["profile_cycles"], self.CYCLES // 2)
        self.assertEqual(report["profile_kept_lines"], self.CYCLES // 2)
        self.assertEqual(report["pruned"], self.CYCLES)
        self.assertTrue(report["sentinel_alive"])
        self.assertTrue(report["ok"], report)


if __name__ == "__main__":
    unittest.main()
