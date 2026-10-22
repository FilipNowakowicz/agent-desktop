"""Dispatch failures preserve uncertainty; invalid evidence cannot satisfy waits."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from agent_desktop import atlas, core
from agent_desktop.atspi import Accessibility, AccessibilityError
from agent_desktop.wayland import Toplevels
from agent_desktop.worker import Worker


class DispatchEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        worker = self.worker = Worker.__new__(Worker)
        worker.info = {"id": "0" * 12, "mode": "headless"}
        worker.root = self.root
        worker.env = {"HOME": str(self.root), "PATH": os.environ["PATH"]}
        worker.compositor = mock.Mock()
        worker.compositor.poll.return_value = None
        worker.check_lease = mock.Mock()
        worker.control = {"owner": "agent"}
        worker.needs_screenshot = False
        worker.effects = None
        worker.settle_after = mock.Mock()
        worker.settle = mock.Mock()
        self.pointer = mock.Mock()
        worker.pointer = mock.Mock(return_value=self.pointer)
        self.keyboard = mock.Mock()
        worker.keyboard = mock.Mock(return_value=self.keyboard)
        worker.keysyms = mock.Mock()
        worker.keysyms.resolve.return_value = 97
        worker.ui_ids = {}
        self.accessibility = Accessibility.__new__(Accessibility)
        self.accessibility.action_names = mock.Mock(return_value=["press"])
        self.accessibility.call = mock.Mock()
        worker.accessibility = mock.Mock(return_value=self.accessibility)
        tracker = worker.toplevels = Toplevels.__new__(Toplevels)
        tracker.connection = mock.Mock()
        tracker.seat = 3
        tracker.windows = {4: {"id": "w1", "states": []}}
        tracker.current = mock.Mock(return_value=[])

    def request(self, operation, **arguments):
        """Run real worker dispatch and error encoding through the real client."""
        connection = mock.MagicMock()
        stream = connection.makefile.return_value.__enter__.return_value

        def dispatch(payload):
            try:
                reply = {
                    "ok": True,
                    "result": self.worker.handle_with_effects(json.loads(payload)),
                }
            except Exception as error:
                reply = self.worker.error_reply(error)
            self.reply = reply
            stream.readline.return_value = (json.dumps(reply) + "\n").encode()

        connection.sendall.side_effect = dispatch
        with (
            mock.patch.object(core, "manifest", return_value={"control_socket": "s"}),
            mock.patch.object(core.socket, "socket") as factory,
        ):
            factory.return_value.__enter__.return_value = connection
            try:
                return core.request(self.worker.info["id"], operation, **arguments)
            finally:
                connection.sendall.assert_called_once()

    def test_partial_pointer_click_is_unknown_and_not_retried(self):
        self.pointer.button.side_effect = [None, BrokenPipeError("release lost")]
        with self.assertRaises(core.DeliveryUnknown):
            self.request("click", x=1, y=2)
        self.assertTrue(self.reply["uncertain"])
        self.assertEqual(
            self.pointer.button.call_args_list,
            [mock.call("left", True), mock.call("left", False)],
        )

    def test_partial_typing_preserves_uncertainty(self):
        self.keyboard.type.side_effect = [None, BrokenPipeError("second chunk")]
        with self.assertRaises(core.DeliveryUnknown):
            self.request("type", text="prefix\n")
        self.assertEqual(
            self.keyboard.type.call_args_list, [mock.call("prefix"), mock.call("\n")]
        )

    def test_scroll_failure_after_position_move_preserves_uncertainty(self):
        self.pointer.scroll.side_effect = BrokenPipeError("scroll lost")
        with self.assertRaises(core.DeliveryUnknown):
            self.request("scroll", x=1, y=2, dy=1)
        self.pointer.move.assert_called_once_with(1, 2)
        self.pointer.scroll.assert_called_once_with(1, 0)

    def test_focus_closing_after_activation_is_unknown(self):
        with self.assertRaises(core.DeliveryUnknown):
            self.request("focus", window="w1")
        self.worker.toplevels.connection.send.assert_called_once()

    def test_ui_action_lost_reply_is_unknown(self):
        self.accessibility.call.side_effect = AccessibilityError("reply lost")
        with self.assertRaises(core.DeliveryUnknown):
            self.request("ui_action", node=":1.1/a", action="press")
        self.accessibility.call.assert_called_once()

    def test_set_text_fallback_focus_failure_is_unknown(self):
        self.accessibility.call.side_effect = [
            AccessibilityError("UnknownMethod"),
            AccessibilityError("focus reply lost"),
        ]
        with self.assertRaises(core.DeliveryUnknown):
            self.request("ui_action", node=":1.1/a", action="set_text", text="new")
        self.assertEqual(self.accessibility.call.call_count, 2)
        self.keyboard.type.assert_not_called()

    def test_partial_atlas_write_is_unknown_and_not_repeated(self):
        entry = {
            "app": "editor",
            "label": "Option",
            "kind": "menu",
            "menu": "View",
            "verified": True,
            "effect": [
                {"file": "~/one.ini", "key": "[a] x", "from": None, "to": "1"},
                {"file": "~/two.ini", "key": "[a] y", "from": None, "to": "2"},
            ],
        }
        write = Path.write_text

        def fail_second(path, *args, **kwargs):
            if path.name == "two.ini":
                raise OSError("disk full")
            return write(path, *args, **kwargs)

        with (
            mock.patch.object(atlas, "load", return_value=[entry]),
            mock.patch.object(Path, "write_text", fail_second),
            self.assertRaises(core.DeliveryUnknown),
        ):
            self.request("set", app="editor", control="Option")
        self.assertEqual((self.root / "one.ini").read_text().strip(), "[a]\nx=1")
        self.assertFalse((self.root / "two.ini").exists())

    def test_key_lost_ack_is_unknown(self):
        self.keyboard.key.side_effect = BrokenPipeError("key reply lost")
        with self.assertRaises(core.DeliveryUnknown):
            self.request("key", key="a")
        self.keyboard.key.assert_called_once_with(97, [], 1)

    def test_launch_failure_after_process_creation_is_unknown(self):
        process = mock.Mock()
        process.poll.side_effect = OSError("status unavailable")
        self.worker.apps = {}
        with (
            mock.patch("agent_desktop.worker.shutil.which", return_value="/bin/app"),
            mock.patch(
                "agent_desktop.worker.subprocess.Popen", return_value=process
            ) as launch,
            mock.patch("agent_desktop.worker.time.sleep"),
            self.assertRaises(core.DeliveryUnknown),
        ):
            self.request("launch", argv=["app"])
        launch.assert_called_once()
        self.assertIn(process, self.worker.apps.values())

    def test_prevalidation_failure_is_known_and_resets_prior_uncertainty(self):
        self.pointer.button.side_effect = BrokenPipeError("lost")
        with self.assertRaises(core.DeliveryUnknown):
            self.request("click", x=1, y=2)
        cases = [
            ("click", {"x": float("nan"), "y": 2}),
            ("scroll", {"x": 1, "y": 2, "dy": 101}),
            ("key", {"key": "a", "repeat": 0}),
            ("type", {"text": None}),
            ("focus", {"window": "absent"}),
            ("ui_action", {"node": "invalid", "action": "press"}),
            ("ui_action", {"node": ":1.1/a", "action": "set_text", "text": None}),
            ("launch", {"argv": []}),
            ("set", {"app": "absent", "control": "absent"}),
        ]
        self.pointer.reset_mock()
        for operation, arguments in cases:
            with self.subTest(operation=operation, arguments=arguments):
                with self.assertRaises(core.DesktopError) as raised:
                    self.request(operation, **arguments)
                self.assertNotIsInstance(raised.exception, core.DeliveryUnknown)
                self.assertNotIn("uncertain", self.reply)
        self.pointer.move.assert_not_called()
        self.keyboard.type.assert_not_called()
        self.accessibility.call.assert_not_called()

    def test_unsupported_selection_is_known_without_keyboard_fallback(self):
        self.accessibility.get = mock.Mock(return_value=(":1.1", "/parent"))
        self.accessibility.action_names.return_value = []
        self.accessibility.call.side_effect = [
            (0,),
            AccessibilityError("UnknownMethod"),
        ]
        with self.assertRaises(core.DesktopError) as raised:
            self.request("ui_action", node=":1.1/a", action="select")
        self.assertNotIsInstance(raised.exception, core.DeliveryUnknown)
        self.assertNotIn("uncertain", self.reply)
        self.keyboard.key.assert_not_called()

    def test_socket_worker_preserves_uncertainty_then_clears_it(self):
        worker = self.worker
        worker.info["control_socket"] = str(self.root / "control.sock")
        worker.stop = False
        worker.apps = {}
        worker.activity = None
        worker.trim_logs = mock.Mock()
        worker.tracked = mock.Mock(return_value=[])
        worker.trace_start = mock.Mock(return_value=None)
        worker.trace_finish = mock.Mock()
        ready = threading.Event()
        worker.save = mock.Mock(side_effect=lambda *_a, **_kw: ready.set())
        self.pointer.button.side_effect = [None, BrokenPipeError("release lost")]
        errors = []

        def serve():
            try:
                worker.serve()
            except Exception as error:
                errors.append(error)
                ready.set()

        with (
            mock.patch("agent_desktop.worker.reap_orphans"),
            mock.patch.object(core, "manifest", return_value=worker.info),
        ):
            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            try:
                self.assertTrue(ready.wait(5), "worker never started listening")
                self.assertFalse(errors)
                with self.assertRaisesRegex(core.DeliveryUnknown, "release lost"):
                    core.request(worker.info["id"], "click", x=1, y=2)
                with self.assertRaises(core.DesktopError) as raised:
                    core.request(worker.info["id"], "key", key="a", repeat=0)
                self.assertNotIsInstance(raised.exception, core.DeliveryUnknown)
            finally:
                worker.stop = True
                thread.join(5)
        self.assertFalse(thread.is_alive(), "worker did not stop")
        self.assertFalse(errors)
        self.assertEqual(self.pointer.button.call_count, 2)


class FileConditionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "result.txt"

    def wait(self, contains=None, key=None, value=None):
        with mock.patch.object(core, "request", return_value={}):
            return core.wait(
                "0" * 12,
                file=str(self.path),
                contains=contains,
                key=key,
                value=value,
                timeout=0,
            )

    def test_valid_file_content_and_ini_still_satisfy(self):
        self.path.write_text("[a]\nx=1\n")
        self.assertTrue(self.wait(contains="x=1")["satisfied"])
        self.assertTrue(self.wait(key="a/x", value="1")["satisfied"])

    def test_invalid_utf8_cannot_fabricate_matching_text(self):
        self.path.write_bytes(b"bad\xfftext")
        result = self.wait(contains="bad\ufffdtext")
        self.assertFalse(result["satisfied"])
        self.assertIn("not valid UTF-8", result["reason"])

    def test_oversized_file_cannot_match_a_readable_prefix(self):
        self.path.write_bytes(b"needle" + b"x" * core.FILE_READ_LIMIT)
        result = self.wait(contains="needle")
        self.assertFalse(result["satisfied"])
        self.assertIn("file read limit", result["reason"])

    def test_fifo_never_blocks_or_satisfies_a_content_wait(self):
        os.mkfifo(self.path)
        # Bound the regression itself: a blocking-open implementation must not
        # hang the test runner while waiting for a nonexistent FIFO writer.
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; import sys; "
                "from agent_desktop import core; "
                "print(core.file_condition(Path(sys.argv[1]), '', None, None))",
                str(self.path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        self.assertIn("not a regular file", result.stdout)

    def test_path_replacement_after_read_cannot_satisfy(self):
        self.path.write_text("needle")
        replacement = self.path.with_name("other")
        replacement.write_text("different")
        original_stat = Path.stat

        def replace_then_stat(path, **kwargs):
            if path == self.path:
                replacement.replace(path)
            return original_stat(path, **kwargs)

        with mock.patch.object(Path, "stat", replace_then_stat):
            result = self.wait(contains="needle")
        self.assertFalse(result["satisfied"])
        self.assertIn("changed during", result["reason"])

    def test_mutation_during_read_cannot_satisfy(self):
        self.path.write_text("needle")
        info = self.path.stat()
        changed = SimpleNamespace(
            **{
                name: getattr(info, name)
                for name in (
                    "st_mode",
                    "st_dev",
                    "st_ino",
                    "st_size",
                    "st_mtime_ns",
                    "st_ctime_ns",
                )
            }
        )
        changed.st_mtime_ns += 1
        with mock.patch.object(core.os, "fstat", side_effect=[info, changed]):
            result = self.wait(contains="needle")
        self.assertFalse(result["satisfied"])
        self.assertIn("changed during", result["reason"])
