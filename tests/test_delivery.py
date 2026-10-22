"""Deadline and post-delivery failures retain evidence without repeating input."""

import json
import time
import unittest
from unittest import mock

from agent_desktop import core, mcp_server
from agent_desktop.browser import Browser
from agent_desktop.worker import Worker


class DeliveryTests(unittest.TestCase):
    def worker(self):
        worker = Worker.__new__(Worker)
        worker.info = {"mode": "headless"}
        bridge = mock.Mock()
        bridge.target.return_value = "context"
        bridge.element.return_value = ({}, {"name": "Submit"})
        bridge.find.return_value = {"count": 1, "items": []}
        worker.browser = (bridge, lambda: None)
        worker.attach_browser = mock.Mock(return_value=True)
        return worker, bridge

    def test_browser_wait_and_batches_have_larger_transport_budgets(self):
        step = {"action": "wait", "timeout": 60, "seconds": 30}
        budget = core.request_budget("browser", step)
        self.assertGreater(budget, 90)
        self.assertEqual(
            core.request_budget("browser", {"action": "steps", "steps": [step] * 30}),
            budget * 30,
        )
        connection = mock.MagicMock()
        connection.makefile.return_value.__enter__.return_value.readline.return_value = b'{"ok": true, "result": {"satisfied": true}}\n'
        with (
            mock.patch.object(
                core, "manifest", return_value={"control_socket": "socket"}
            ),
            mock.patch.object(core.socket, "socket") as factory,
        ):
            factory.return_value.__enter__.return_value = connection
            self.assertTrue(core.request("s", "browser", **step)["satisfied"])
        connection.settimeout.assert_called_once_with(budget + 5)
        sent = json.loads(connection.sendall.call_args.args[0])
        self.assertGreater(sent["deadline"], time.monotonic() + 90)

    def test_lost_transport_reply_is_uncertain_and_never_retried(self):
        connection = mock.MagicMock()
        connection.makefile.side_effect = TimeoutError("lost reply")
        with (
            mock.patch.object(
                core, "manifest", return_value={"control_socket": "socket"}
            ),
            mock.patch.object(core.socket, "socket") as factory,
        ):
            factory.return_value.__enter__.return_value = connection
            with self.assertRaises(core.DeliveryUnknown):
                core.request("s", "click", x=1, y=2)
        connection.sendall.assert_called_once()

    def test_interrupted_send_is_conservatively_uncertain(self):
        connection = mock.MagicMock()
        connection.sendall.side_effect = BrokenPipeError("partial send")
        with (
            mock.patch.object(
                core, "manifest", return_value={"control_socket": "socket"}
            ),
            mock.patch.object(core.socket, "socket") as factory,
        ):
            factory.return_value.__enter__.return_value = connection
            with self.assertRaises(core.DeliveryUnknown):
                core.request("s", "click", x=1, y=2)
        connection.sendall.assert_called_once()

    def test_expired_command_does_not_send(self):
        bridge = Browser.__new__(Browser)
        bridge.deadline = time.monotonic() - 1
        bridge.socket = mock.Mock()
        with self.assertRaisesRegex(TimeoutError, "before"):
            bridge.command("input.performActions", {})
        bridge.socket.send.assert_not_called()

    def test_command_reply_wait_uses_shared_request_deadline(self):
        bridge = Browser.__new__(Browser)
        bridge.next_id = 0
        bridge.deadline = 105
        bridge.socket = mock.Mock()
        bridge.socket.recv.return_value = '{"id": 1, "result": {}}'
        with mock.patch("agent_desktop.browser.time.monotonic", return_value=100):
            bridge.command("browsingContext.navigate", {}, timeout=60)
        bridge.socket.recv.assert_called_once_with(timeout=5)

    def test_screenshot_failure_preserves_delivery_even_when_image_is_missing(self):
        for capture in (
            core.DesktopError("capture failed"),
            {"path": "/missing/image.png"},
        ):
            with self.subTest(capture=capture):
                with mock.patch.object(mcp_server, "call") as call:
                    if isinstance(capture, Exception):
                        call.side_effect = capture
                    else:
                        call.return_value = capture
                    result = mcp_server.looked("s", {"delivered": True}, True)
                self.assertTrue(result["delivered"])
                self.assertIn("observation_error", result)
                self.assertNotIn("screenshot", result)
                call.assert_called_once()

    def test_browser_read_failure_preserves_click_and_stops_batch(self):
        worker, bridge = self.worker()
        bridge.call.side_effect = TimeoutError("post-click read failed")
        result = worker.browser_request(
            {"action": "steps", "steps": [{"action": "click"}, {"action": "click"}]}
        )
        self.assertEqual(result["completed"], 1)
        self.assertTrue(result["results"][0]["delivered"])
        self.assertIn("post-click", result["results"][0]["observation_error"])
        bridge.click.assert_called_once()

    def test_browser_lost_ack_preserves_prefix_and_uncertain_current_step(self):
        worker, bridge = self.worker()
        bridge.click.side_effect = TimeoutError("reply lost")
        result = worker.browser_request(
            {
                "action": "steps",
                "steps": [{"action": "find"}, {"action": "click"}, {"action": "click"}],
            }
        )
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["stopped"]["step"], 1)
        self.assertTrue(result["stopped"]["uncertain"])
        self.assertIsNone(result["results"][1]["delivered"])
        bridge.click.assert_called_once()

    def test_expired_batch_stops_before_next_step(self):
        worker, bridge = self.worker()
        result = worker.browser_steps(
            [{"action": "click"}], deadline=time.monotonic() - 1
        )
        self.assertEqual(result["completed"], 0)
        bridge.click.assert_not_called()
        with self.assertRaisesRegex(ValueError, "nothing delivered"):
            worker.handle({"operation": "click", "deadline": time.monotonic() - 1})

    def test_malformed_batch_is_rejected_before_any_step(self):
        worker, bridge = self.worker()
        with self.assertRaisesRegex(ValueError, "Step 1"):
            worker.browser_steps([{"action": "click"}, {"action": "steps"}])
        bridge.click.assert_not_called()

    def test_navigation_and_close_preserve_acknowledgement_after_read_failure(self):
        for action in ("open", "close"):
            with self.subTest(action=action):
                worker, bridge = self.worker()
                worker.agent_tabs = set()
                worker.page_state = mock.Mock(
                    side_effect=TimeoutError("page read failed")
                )
                bridge.tabs.side_effect = TimeoutError("tabs read failed")
                result = worker.browser_request(
                    {"action": action, "url": "about:blank"}
                )
                self.assertTrue(result["delivered"])
                self.assertIn("observation_error", result)
                bridge.command.assert_called_once()

    def test_optional_effects_failure_keeps_action_result(self):
        worker = Worker.__new__(Worker)
        worker.effects = mock.Mock()
        worker.control = {"owner": "agent"}
        worker.handle = mock.Mock(return_value={"delivered": True})
        for method in ("begin", "finish"):
            with self.subTest(method=method):
                worker.effects.reset_mock(side_effect=True)
                getattr(worker.effects, method).side_effect = RuntimeError(
                    "recorder failed"
                )
                result = worker.handle_with_effects({"operation": "click"})
                self.assertTrue(result["delivered"])
                self.assertEqual(result["effects_error"], "recorder failed")
        self.assertEqual(worker.handle.call_count, 2)
