"""Teardown never signals a process number that now belongs to another process."""

import os
import signal
import subprocess
import time
import unittest
from unittest import mock

from agent_desktop import worker


class ProcessIdentityTests(unittest.TestCase):
    def setUp(self):
        self.process = subprocess.Popen(["sleep", "30"])
        self.addCleanup(self.stop)

    def stop(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait()

    def test_start_time_matches_process_table(self):
        started = worker.start_time(self.process.pid)
        self.assertIsInstance(started, int)
        self.assertEqual(worker.process_table()[self.process.pid][2], started)

    def test_signal_requires_the_recorded_start_time(self):
        pid = self.process.pid
        started = worker.start_time(pid)
        # A different start time stands for a reused number: never signalled.
        self.assertFalse(worker.signal_process(pid, started - 1, signal.SIGTERM))
        time.sleep(0.2)
        self.assertIsNone(self.process.poll())
        self.assertTrue(worker.signal_process(pid, started, signal.SIGTERM))
        self.assertEqual(self.process.wait(timeout=5), -signal.SIGTERM)
        self.assertIsNone(worker.start_time(pid))
        self.assertFalse(worker.signal_process(pid, started, signal.SIGTERM))

    def test_cleanup_skips_a_reused_number(self):
        pid = self.process.pid
        stale = {pid: worker.start_time(pid) - 1}
        with (
            mock.patch.object(
                worker, "session_process_starts", side_effect=[stale, {}]
            ),
            mock.patch.object(worker, "session_processes", return_value=[]),
        ):
            worker.cleanup_processes("unused-token")
        time.sleep(0.2)
        self.assertIsNone(self.process.poll())


if __name__ == "__main__":
    unittest.main()


class ReapOrphansTests(unittest.TestCase):
    def zombie(self):
        # A bare fork: subprocess would reap abandoned Popen children itself.
        pid = os.fork()
        if pid == 0:
            os._exit(0)
        deadline = time.monotonic() + 5
        while worker.process_state(pid) != "Z":
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)
        return pid

    def check(self):
        orphan, tracked = self.zombie(), self.zombie()
        self.assertIn(orphan, worker.child_pids(os.getpid()) or {orphan})
        worker.reap_orphans(tracked={tracked})
        self.assertIsNone(worker.process_state(orphan))
        # A tracked child keeps its exit status for its Popen object.
        self.assertEqual(worker.process_state(tracked), "Z")
        os.waitpid(tracked, 0)

    def test_reaps_untracked_children(self):
        self.check()

    def test_falls_back_to_scanning_without_children_lists(self):
        with mock.patch.object(worker, "child_pids", return_value=None):
            self.check()
