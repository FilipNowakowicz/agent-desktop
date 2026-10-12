"""desktop_run (D1, experimental): a Python script acts on a private session."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from test_runtime import wait_for

from agent_desktop import core, mcp_server
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
