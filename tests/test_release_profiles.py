"""Release and profile-lock edge cases from the 2026-10-05 review, without a desktop."""

import fcntl
import os
import tempfile
import unittest
from pathlib import Path

from agent_desktop import core
from agent_desktop.worker import Worker


def releasing_worker(directory):
    worker = Worker.__new__(Worker)
    worker.root = Path(directory)
    worker.info = {
        "id": "0" * 12,
        "wayland_display": str(Path(directory) / "missing-wayland-socket"),
        "runtime": directory,
    }
    worker.save_control = lambda: None
    worker.takeover = None
    worker.needs_screenshot = False
    worker.control = {"owner": "human", "epoch": 1, "request": None, "last": None}
    return worker


class ReleaseTests(unittest.TestCase):
    def test_failed_clipboard_clear_keeps_control_with_the_person(self):
        with tempfile.TemporaryDirectory() as directory:
            worker = releasing_worker(directory)
            with self.assertRaisesRegex(RuntimeError, "control stays"):
                worker.release("released by the user")
            self.assertEqual(worker.control["owner"], "human")
            self.assertIn("release_error", worker.control)
            self.assertFalse(worker.needs_screenshot)

    def test_forced_release_records_uncleared_clipboard(self):
        with tempfile.TemporaryDirectory() as directory:
            worker = releasing_worker(directory)
            state = worker.release("released by the user", force=True)
            self.assertEqual(state["owner"], "agent")
            self.assertFalse(state["last"]["clipboard_cleared"])
            self.assertNotIn("release_error", worker.control)
            self.assertTrue(worker.needs_screenshot)


class ProfileLockTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.previous = os.environ.get("AGENT_DESKTOP_STATE_DIR")
        os.environ["AGENT_DESKTOP_STATE_DIR"] = self.temporary.name

    def tearDown(self):
        if self.previous is None:
            os.environ.pop("AGENT_DESKTOP_STATE_DIR", None)
        else:
            os.environ["AGENT_DESKTOP_STATE_DIR"] = self.previous
        self.temporary.cleanup()

    def test_held_lock_blocks_delete_and_create_and_survives_deletion(self):
        home = core.profile_path("work") / "home"
        home.mkdir(parents=True)
        lock_path = core.profile_lock(home.parent)
        # Outside the directory that deletion removes.
        self.assertEqual(lock_path.parent, home.parent.parent)
        with lock_path.open("a") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(core.DesktopError, "in use"):
                core.delete_profile("work")
            with self.assertRaisesRegex(core.DesktopError, "in use"):
                core.create(profile="work")
            self.assertTrue(home.is_dir())
        core.delete_profile("work")
        self.assertFalse(home.parent.exists())
        self.assertTrue(lock_path.exists())
        self.assertEqual(core.profiles(), [])


if __name__ == "__main__":
    unittest.main()
