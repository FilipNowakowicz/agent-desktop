"""Activity summaries, host workspaces and held keys around a final screenshot."""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from agent_desktop import core, mcp_server
from agent_desktop.worker import Worker


class ActivityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        patch = mock.patch.dict(os.environ, {"AGENT_DESKTOP_STATE_DIR": directory.name})
        patch.start()
        self.addCleanup(patch.stop)

    def session(self, name, mode, records):
        path = self.root / name
        path.mkdir()
        (path / "session.json").write_text(json.dumps({"id": name, "mode": mode}))
        lines = [json.dumps(r) for r in records] + ["not json"]
        (path / "trace.jsonl").write_text("\n".join(lines))

    def test_browser_batches_stops_waits_and_uncertain_deliveries(self):
        from agent_desktop.worker import stop_reason, trace_arguments

        now = time.time()
        steps = [
            {"action": "open", "url": "https://example.com/secret-path"},
            {"action": "wait", "seconds": 6},
            {"action": "wait", "text": "Dashboard", "timeout": 10},
            {"action": "click", "text": "Remove", "within": "box-1"},
        ]
        arguments = trace_arguments(
            {"operation": "browser", "action": "steps", "steps": steps}
        )
        self.assertNotIn("secret-path", json.dumps(arguments))
        self.assertNotIn("Dashboard", json.dumps(arguments))
        single = trace_arguments(
            {"operation": "browser", "action": "wait", "seconds": 4.5}
        )
        self.assertEqual(single["condition"], False)
        self.assertEqual(
            stop_reason({"step": 3, "reason": "2 elements match 'Remove' ({...})"}),
            "ambiguous",
        )
        self.assertEqual(stop_reason({"reason": "x", "uncertain": True}), "uncertain")
        self.assertEqual(
            stop_reason({"reason": "No visible element matches"}), "missing"
        )
        self.session(
            "c" * 12,
            "headless",
            [
                {
                    "at": now,
                    "operation": "browser",
                    "arguments": arguments,
                    "outcome": {"completed": 3, "total": 4, "stopped": "ambiguous"},
                },
                {
                    "at": now,
                    "operation": "browser",
                    "arguments": arguments,
                    "outcome": {"completed": 4, "total": 4},
                },
                {
                    "at": now,
                    "operation": "browser",
                    "arguments": single,
                    "outcome": {"delivered": None, "uncertain": True},
                },
                {"at": now, "operation": "click", "outcome": {"delivered": None}},
            ],
        )
        result = core.activity()
        self.assertEqual(result["errors_by_type"], {})
        self.assertEqual(result["browser_batches"], 2)
        self.assertEqual(result["browser_batches_stopped"], 1)
        self.assertEqual(result["browser_stops_by_reason"], {"ambiguous": 1})
        self.assertEqual(result["browser_waits_fixed"], 3)
        self.assertEqual(result["browser_waits_for_condition"], 2)
        self.assertEqual(result["browser_fixed_wait_seconds"], 16.5)
        self.assertEqual(result["uncertain_deliveries"], 2)

    def test_counts_without_content(self):
        now = time.time()
        self.session(
            "a" * 12,
            "host",
            [
                {
                    "at": now,
                    "operation": "key",
                    "arguments": {"key": "secret", "observation": "t"},
                    "outcome": {"delivered": True},
                },
                {
                    "at": now,
                    "operation": "click",
                    "arguments": {"x": 1},
                    "error": "UserActive: private detail",
                },
                {"at": now, "operation": "screenshot", "arguments": {"scale": 0.5}},
            ],
        )
        self.session(
            "b" * 12,
            "headless",
            [{"at": now - 864000, "operation": "key", "arguments": {}}],
        )
        result = core.activity()
        self.assertEqual(result["sessions"], 2)
        self.assertEqual(result["calls_by_operation"]["key"], 2)
        self.assertEqual(result["errors_by_type"], {"UserActive": 1})
        self.assertEqual(result["input_calls"], 3)
        self.assertEqual(result["input_calls_with_observation"], 1)
        self.assertEqual(result["screenshots_scaled"], 1)
        self.assertNotIn("secret", json.dumps(result))
        self.assertNotIn("private detail", json.dumps(result))
        recent = core.activity(days=1)
        self.assertEqual(recent["sessions_by_mode"], {"host": 1})
        self.assertEqual(core.activity("a" * 12)["calls"], 3)

    def test_empty_state(self):
        self.assertEqual(core.activity()["calls"], 0)


class WorkspaceTests(unittest.TestCase):
    def windows(self, clients):
        desktop = Worker.__new__(Worker)
        desktop.env = {"HYPRLAND_INSTANCE_SIGNATURE": "sig"}
        windows = [
            {"id": "w1", "app_id": "kitty", "title": "one"},
            {"id": "w2", "app_id": "kitty", "title": "same"},
        ]
        reply = mock.Mock(stdout=json.dumps(clients))
        with mock.patch("agent_desktop.worker.subprocess.run", return_value=reply):
            return desktop.with_workspaces(windows)

    def test_identical_windows_on_two_workspaces_stay_unknown(self):
        def client(title, workspace):
            return {
                "class": "kitty",
                "title": title,
                "workspace": {"name": workspace},
            }

        result = self.windows(
            [client("one", "2"), client("same", "3"), client("same", "4")]
        )
        self.assertEqual(result[0]["workspace"], "2")
        self.assertNotIn("workspace", result[1])

    def test_unreadable_clients_leave_windows_alone(self):
        self.assertNotIn("workspace", self.windows({"unexpected": True})[0])


class HeldScreenshotTests(unittest.TestCase):
    def test_keys_are_released_after_the_image(self):
        order = []
        actions = [{"action": "key_down", "key": "logo"}]

        def run(*_arguments, release_held):
            order.append(("run", release_held))
            return {"completed": 1}

        def looked(*_arguments):
            order.append("looked")
            return {}

        def release(*_arguments):
            order.append("released")

        function = getattr(
            mcp_server.desktop_actions, "__wrapped__", mcp_server.desktop_actions
        )
        with (
            mock.patch.object(mcp_server.core, "run_actions", run),
            mock.patch.object(mcp_server, "looked", looked),
            mock.patch.object(mcp_server.core, "release_held_keys", release),
        ):
            function("s", actions, screenshot=True)
        self.assertEqual(order, [("run", False), "looked", "released"])


if __name__ == "__main__":
    unittest.main()
