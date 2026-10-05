"""Retained state stays bounded: screenshots per session, pruning, accounting."""

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from test_runtime import wait_for

from agent_desktop import core
from agent_desktop.worker import owned_processes


def fake_session(root, name, status, age_days=0, size=1000):
    directory = root / name
    (directory / "screenshots").mkdir(parents=True)
    (directory / "screenshots" / "a.png").write_bytes(b"x" * size)
    manifest = directory / "session.json"
    manifest.write_text(
        json.dumps(
            {"id": name, "status": status, "token": "t" + name, "mode": "headless"}
        )
    )
    stamp = time.time() - age_days * 86400
    os.utime(manifest, (stamp, stamp))
    return directory


class PruneTests(unittest.TestCase):
    def test_prune_removes_only_finished_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.dict(os.environ, {"AGENT_DESKTOP_STATE_DIR": directory}):
                old = fake_session(root, "a" * 12, "stopped", age_days=3)
                failed = fake_session(root, "b" * 12, "failed", age_days=3)
                recent = fake_session(root, "c" * 12, "stopped", age_days=0)
                live = fake_session(root, "d" * 12, "ready", age_days=3)
                (root / "profiles").mkdir()  # not a session
                usage = core.usage()
                self.assertEqual(
                    usage["sessions"], {"stopped": 2, "failed": 1, "ready": 1}
                )
                self.assertEqual(usage["screenshot_bytes"], 4000)

                preview = core.prune(older_than_days=1, dry_run=True)
                self.assertEqual(sorted(preview["removed"]), ["a" * 12, "b" * 12])
                self.assertTrue(old.exists())

                result = core.prune(older_than_days=1)
                self.assertFalse(old.exists())
                self.assertFalse(failed.exists())
                self.assertTrue(recent.exists())
                self.assertTrue(live.exists())
                self.assertGreater(result["bytes_freed"], 2000)
                reasons = {k["session"]: k["reason"] for k in result["kept"]}
                self.assertEqual(reasons["c" * 12], "newer than the cutoff")
                self.assertEqual(reasons["d" * 12], "status ready")


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "dbus-daemon")),
    "desktop tools unavailable",
)
class ScreenshotRetentionTests(unittest.TestCase):
    def test_only_the_newest_screenshots_are_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "runtime").mkdir(mode=0o700)
            environment = {
                "AGENT_DESKTOP_STATE_DIR": str(Path(directory) / "state"),
                "XDG_RUNTIME_DIR": str(Path(directory) / "runtime"),
                "AGENT_DESKTOP_KEEP_SCREENSHOTS": "3",
            }
            with mock.patch.dict(os.environ, environment):
                session = core.create()["session"]
                token = core.manifest(session)["token"]
                try:
                    paths = [
                        core.request(session, "screenshot")["path"] for _ in range(6)
                    ]
                    kept = sorted(
                        (core.session_path(session) / "screenshots").glob("*.png")
                    )
                    self.assertEqual(len(kept), 3)
                    self.assertTrue(Path(paths[-1]).exists())
                    self.assertFalse(Path(paths[0]).exists())
                finally:
                    core.destroy(session)
                    wait_for(lambda: not owned_processes(token))


if __name__ == "__main__":
    unittest.main()
