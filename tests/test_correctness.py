"""Edge cases found by the 2026-10-05 review, checked without a desktop."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from agent_desktop import core
from agent_desktop.worker import StaleObservation, Worker


def bare_worker(root):
    worker = Worker.__new__(Worker)
    worker.root = root
    worker.info = {"id": "0" * 12}
    worker.needs_screenshot = True
    worker.virtual_pointer = SimpleNamespace(
        connection=SimpleNamespace(roundtrip=lambda: None),
        output={"width": 10, "height": 10, "scale": 1},
    )
    worker.ui_ids, worker.ui_names, worker.ui_counter = {}, {}, 0
    return worker


class CaptureTests(unittest.TestCase):
    def test_unstable_capture_fails_and_keeps_screenshot_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            worker = bare_worker(Path(directory))
            tokens = iter(range(100))
            worker.observation = lambda: f"{next(tokens):016x}"
            worker.command = lambda *_args, **_kwargs: None
            with self.assertRaises(StaleObservation):
                worker.screenshot()
            self.assertTrue(worker.needs_screenshot)
            self.assertEqual(list((Path(directory) / "screenshots").iterdir()), [])


class IdentifierTests(unittest.TestCase):
    def test_ids_are_never_reused_after_forgetting(self):
        with tempfile.TemporaryDirectory() as directory:
            worker = bare_worker(Path(directory))
            first = worker.short_id(":1.1/a")
            self.assertEqual(worker.short_id(":1.1/a"), first)
            worker.ui_ids.update({f"x{i}": "y" for i in range(50000)})
            later = worker.short_id(":1.1/b")
            self.assertNotEqual(later, first)
            self.assertNotIn(first, worker.ui_ids)


class SequenceTests(unittest.TestCase):
    def test_delivered_step_is_reported_when_observation_fails(self):
        replies = iter(
            [
                {"observation": "a" * 16},  # baseline
                {"delivered": True},  # the key step
            ]
        )

        def fake_request(_session, operation, _controller=None, **_arguments):
            if operation == "lease":
                return {}
            if operation == "observe" and fake_request.observed:
                raise core.DesktopError("Session unavailable")
            if operation == "observe":
                fake_request.observed = True
            return next(replies)

        fake_request.observed = False
        with mock.patch.object(core, "request", fake_request):
            result = core.run_actions(
                "0" * 12,
                [{"action": "key", "key": "Return"}, {"action": "key", "key": "a"}],
            )
        self.assertEqual(result["completed"], 1)
        self.assertIn("step 0 was delivered", result["stopped"]["reason"])

    def test_uncertain_step_is_reported_and_never_retried(self):
        sent = []

        def fake_request(_session, operation, controller=None, **arguments):
            sent.append((operation, controller))
            if operation == "lease":
                return {}
            if operation == "observe":
                return {"observation": "a" * 16}
            raise core.DeliveryUnknown("No reply after sending type")

        with mock.patch.object(core, "request", fake_request):
            result = core.run_actions(
                "0" * 12,
                [{"action": "type", "text": "pay"}, {"action": "key", "key": "a"}],
                controller="client-a",
            )
        self.assertEqual(result["completed"], 0)
        self.assertTrue(result["stopped"]["uncertain"])
        self.assertEqual([op for op, _ in sent].count("type"), 1)
        self.assertNotIn("key", [op for op, _ in sent])
        self.assertTrue(all(c == "client-a" for _, c in sent))


class WaitTests(unittest.TestCase):
    def test_plain_pause_requires_an_existing_session(self):
        for session in ("0" * 12, "../x"):
            with self.subTest(session=session), self.assertRaises(core.DesktopError):
                core.wait(session, seconds=0.01, timeout=0)


if __name__ == "__main__":
    unittest.main()
