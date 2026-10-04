"""Activation must fail when the compositor never confirms the target."""

import unittest
from unittest.mock import Mock, patch

from agent_desktop.wayland import Toplevels, WaylandError


class FocusTests(unittest.TestCase):
    def tracker(self):
        tracker = Toplevels.__new__(Toplevels)
        tracker.connection = Mock()
        tracker.seat = 3
        tracker.windows = {4: {"id": "w1", "states": []}}
        return tracker

    def test_activation_waits_for_state(self):
        tracker = self.tracker()
        active = {"id": "w1", "states": ["activated"]}
        tracker.current = Mock(side_effect=[[tracker.windows[4]], [active]])
        with patch("agent_desktop.wayland.time.sleep"):
            self.assertEqual(tracker.activate("w1"), active)

    def test_refused_activation_times_out(self):
        tracker = self.tracker()
        tracker.current = Mock(return_value=[tracker.windows[4]])
        with (
            patch("agent_desktop.wayland.time.monotonic", side_effect=[0, 3]),
            self.assertRaisesRegex(WaylandError, "activation timed out"),
        ):
            tracker.activate("w1")

    def test_target_closes_during_activation(self):
        tracker = self.tracker()
        tracker.current = Mock(return_value=[])
        with self.assertRaisesRegex(WaylandError, "closed during activation"):
            tracker.activate("w1")

    def test_unknown_target_sends_no_activation(self):
        tracker = self.tracker()
        with self.assertRaisesRegex(ValueError, "Unknown window"):
            tracker.activate("w999")
        tracker.connection.send.assert_not_called()
