"""Opt-in graphical observer test. Closes only the viewer it creates."""

import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from agent_desktop import core


def main():
    previous = os.environ.get("AGENT_DESKTOP_STATE_DIR")
    with tempfile.TemporaryDirectory(prefix="viewer-smoke-") as directory:
        os.environ["AGENT_DESKTOP_STATE_DIR"] = str(Path(directory) / "state")
        session = core.create()["session"]
        process = None
        try:
            process = subprocess.Popen(
                [shutil.which("agent-desktop"), "view", session],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            deadline = time.monotonic() + 10
            observed = False
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(process.communicate()[1])
                clients = json.loads(
                    subprocess.run(
                        ["hyprctl", "-j", "clients"],
                        capture_output=True,
                        check=True,
                        text=True,
                    ).stdout
                )
                if any(
                    "WayVNC" in client.get("title", "")
                    and "vnc" in client.get("class", "").lower()
                    for client in clients
                ):
                    observed = True
                    break
                time.sleep(0.1)
            if not observed:
                raise RuntimeError("Graphical viewer did not map on the host desktop")
            os.killpg(process.pid, signal.SIGINT)
            stdout, stderr = process.communicate(timeout=10)
            if process.returncode:
                raise RuntimeError(stderr)
            result = json.loads(stdout)
            assert result["desktop_running"]
            assert core.request(session, "status")["status"] == "ready"
            print(
                json.dumps({"viewer_mapped": observed, "desktop_survived_close": True})
            )
        finally:
            if process and process.poll() is None:
                os.killpg(process.pid, signal.SIGINT)
                process.communicate(timeout=10)
            core.destroy(session)
            if previous is None:
                os.environ.pop("AGENT_DESKTOP_STATE_DIR", None)
            else:
                os.environ["AGENT_DESKTOP_STATE_DIR"] = previous


if __name__ == "__main__":
    main()
