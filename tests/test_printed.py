"""Commands printed for the person run as printed, even off the server's PATH."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_desktop import printed


class PrintedCommandTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.venv = self.root / "venv with space"
        (self.venv / "bin").mkdir(parents=True)
        script = self.venv / "bin" / "agent-desktop"
        script.write_text("#!/bin/sh\nexit 0\n")
        script.chmod(0o755)
        self.other = self.root / "other"
        self.other.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def test_uv_run_path_alone_gives_the_absolute_script(self):
        # uv run puts the virtual environment first; the person's PATH lacks it.
        environ = {"PATH": f"{self.venv / 'bin'}:/usr/bin:/bin"}
        command = printed.command("take", "s1", environ=environ, base=self.venv)
        self.assertEqual(command, f"'{self.venv / 'bin' / 'agent-desktop'}' take s1")

    def test_bare_name_when_another_path_entry_has_it(self):
        found = self.other / "agent-desktop"
        found.write_text("#!/bin/sh\n")
        found.chmod(0o755)
        environ = {"PATH": f"{self.venv / 'bin'}:{self.other}"}
        self.assertEqual(
            printed.command("take", "--paste", "s1", environ=environ, base=self.venv),
            "agent-desktop take --paste s1",
        )

    def test_override(self):
        environ = {"AGENT_DESKTOP_CLI": "uv --directory /src run agent-desktop"}
        self.assertEqual(
            printed.command("host", "stop", environ=environ, base=self.venv),
            "uv --directory /src run agent-desktop host stop",
        )

    def test_printed_command_runs_without_the_venv_on_path(self):
        # The real installation: drop this interpreter's bin from PATH, as the
        # person's terminal would not have it, and run what is printed.
        own = Path(sys.prefix) / "bin" / "agent-desktop"
        if not own.exists():
            self.skipTest("agent-desktop is not installed in this environment")
        path = os.pathsep.join(
            e
            for e in os.environ.get("PATH", "").split(os.pathsep)
            if e and Path(e).resolve() != own.parent.resolve()
        )
        environ = {**os.environ, "PATH": path}
        environ.pop("AGENT_DESKTOP_CLI", None)
        command = printed.command("--help", environ=environ)
        result = subprocess.run(
            command, shell=True, env=environ, capture_output=True, timeout=60
        )
        self.assertEqual(result.returncode, 0, (command, result.stderr))


if __name__ == "__main__":
    unittest.main()
