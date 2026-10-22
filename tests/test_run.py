"""desktop_run (D1, experimental): a Python script acts on a private session."""

import functools
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import anyio
from test_runtime import wait_for

from agent_desktop import core, mcp_server, script_jobs
from agent_desktop.worker import owned_processes


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "foot", "dbus-daemon")),
    "desktop tools unavailable",
)
class RunTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-run-")
        root = Path(self.temporary.name)
        self.previous = {
            k: os.environ.get(k) for k in ("AGENT_DESKTOP_STATE_DIR", "XDG_RUNTIME_DIR")
        }
        (root / "runtime").mkdir(mode=0o700)
        os.environ["AGENT_DESKTOP_STATE_DIR"] = str(root / "state")
        os.environ["XDG_RUNTIME_DIR"] = str(root / "runtime")
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

    def test_a_script_types_waits_and_reads_the_result(self):
        core.request(
            self.session,
            "launch",
            argv=["foot", "--config=/dev/null", "--title=Run target", "sh"],
        )
        self.assertTrue(
            core.wait(self.session, title="Run target", timeout=10)["satisfied"]
        )
        result = mcp_server.desktop_run(
            self.session,
            "focus('Run target')\n"
            "for n in range(3):\n"
            "    type_text(f'echo line{n} >> ~/out.txt\\n')\n"
            "wait(file='~/out.txt', contains='line2')\n"
            "lines = (home() / 'out.txt').read_text().split()\n"
            "assert lines == ['line0', 'line1', 'line2'], lines\n"
            "print(len(lines), [w['title'] for w in windows()])\n",
        )
        self.assertEqual(result["exit_code"], 0, result)
        self.assertIn("3 ['Run target']", result["stdout"])
        # The script ran as this server's controller, which now holds the lease.
        lease = core.request(self.session, "control")["lease"]
        self.assertEqual(lease["holder"], mcp_server.CONTROLLER)

    def test_an_unmet_wait_stops_the_script(self):
        result = mcp_server.desktop_run(
            self.session,
            "print('before')\nwait(timeout=0.5, title='Never opens')\nprint('after')\n",
        )
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(result["stdout"].split(), ["before"])
        self.assertIn("TimeoutError", result["stderr"])

    def test_a_long_script_is_stopped_at_the_timeout(self):
        result = mcp_server.desktop_run(
            self.session,
            "import time\nprint('started', flush=True)\ntime.sleep(30)\n",
            timeout=1,
        )
        self.assertTrue(result["timed_out"])
        self.assertIn("started", result["stdout"])
        self.assertLess(result["seconds"], 5)

    def test_session_launched_application_survives_script_cancellation(self):
        pid_file = Path(self.temporary.name) / "app-pid"
        code = (
            "app = launch(['foot', '--config=/dev/null', '--title=Surviving app', 'sh'])\n"
            f"from pathlib import Path\nPath({str(pid_file)!r}).write_text(str(app['pid']))\n"
            "wait(timeout=30, title='Never opens')\n"
        )

        async def trial():
            async with anyio.create_task_group() as group:
                group.start_soon(
                    script_jobs.cancellable_call,
                    functools.partial(mcp_server.desktop_run, self.session, code),
                )
                with anyio.fail_after(10):
                    while not pid_file.exists():
                        await anyio.sleep(0.02)
                group.cancel_scope.cancel()

        anyio.run(trial)
        self.assertTrue(Path(f"/proc/{pid_file.read_text()}").exists())
        self.assertTrue(
            core.wait(
                self.session,
                title="Surviving app",
                timeout=5,
                controller=mcp_server.CONTROLLER,
            )["satisfied"]
        )
        self.assertTrue(
            core.request(self.session, "screenshot", mcp_server.CONTROLLER)["path"]
        )

    def test_timeout_reports_pending_worker_operation(self):
        result = mcp_server.desktop_run(
            self.session,
            "from agent_desktop.script import request\n"
            "request('screenshot', settle_ms=2000, settle_timeout_ms=3000)\n",
            timeout=1,
        )
        self.assertTrue(result["timed_out"], result)
        self.assertEqual(result["operations"]["in_flight"], ["screenshot"], result)
        self.assertEqual(result["operations"]["delivery"], "unknown", result)
        self.assertEqual(result["cleanup"]["state"], "complete", result)
        # Stopping the caller does not retract a worker operation. It still
        # finishes; later requests can use the desktop normally.
        self.assertTrue(core.request(self.session, "windows", mcp_server.CONTROLLER))
