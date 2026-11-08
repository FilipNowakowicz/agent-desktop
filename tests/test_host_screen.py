"""Host desktops on a terminal that is not showing, without a real host."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_desktop import core, mcp_server
from agent_desktop.worker import Worker


def worker(runtime):
    desktop = Worker.__new__(Worker)
    desktop.env = {"HYPRLAND_INSTANCE_SIGNATURE": "sig", "XDG_RUNTIME_DIR": runtime}
    return desktop


class OffScreenTests(unittest.TestCase):
    def check(self, terminal, active):
        with tempfile.TemporaryDirectory() as runtime:
            lock = Path(runtime, "hypr", "sig", "hyprland.lock")
            lock.parent.mkdir(parents=True)
            lock.write_text("4242\nwayland-1\n")
            real_read_text, real_read_bytes = Path.read_text, Path.read_bytes

            def read_text(path, *args, **kwargs):
                if str(path) == "/sys/class/tty/tty0/active":
                    return active + "\n"
                return real_read_text(path, *args, **kwargs)

            def read_bytes(path):
                if str(path) == "/proc/4242/environ":
                    return b"A=1\0XDG_VTNR=" + terminal + b"\0"
                return real_read_bytes(path)

            with (
                mock.patch.object(Path, "read_text", read_text),
                mock.patch.object(Path, "read_bytes", read_bytes),
            ):
                return worker(runtime).host_off_screen()

    def test_another_terminal_showing_is_reported(self):
        self.assertIn("tty3", self.check(b"3", "tty2"))

    def test_the_showing_terminal_is_fine(self):
        self.assertIsNone(self.check(b"3", "tty3"))

    def test_unknown_state_does_not_block(self):
        self.assertIsNone(worker("/nonexistent").host_off_screen())

    def test_tool_timeout_hides_the_command_line(self):
        desktop = Worker.__new__(Worker)
        desktop.compositor = None
        desktop.env = {}
        desktop.info = {"tools": {"grim": "/secret/path/grim"}}
        with (
            mock.patch(
                "agent_desktop.worker.subprocess.run",
                side_effect=subprocess.TimeoutExpired("grim", 10),
            ),
            self.assertRaises(RuntimeError) as caught,
        ):
            desktop.command("grim", "out.png")
        self.assertEqual(str(caught.exception), "grim did not finish within 10 s")


class RendererArgumentTests(unittest.TestCase):
    def test_arguments_override_the_environment(self):
        with mock.patch.dict(
            "os.environ",
            {"AGENT_DESKTOP_RENDERER": "vulkan", "AGENT_DESKTOP_RENDER_DEVICE": ""},
        ):
            self.assertEqual(
                core.compositor_renderer("gles2"), {"name": "gles2", "device": None}
            )

    def test_software_ignores_a_configured_device(self):
        with mock.patch.dict(
            "os.environ",
            {"AGENT_DESKTOP_RENDERER": "gles2", "AGENT_DESKTOP_RENDER_DEVICE": "/x"},
        ):
            self.assertEqual(
                core.compositor_renderer("pixman"), {"name": "pixman", "device": None}
            )


class ScaleTests(unittest.TestCase):
    def test_a_reply_without_a_token_reuses_the_last_scale(self):
        capture = {"path": "/nonexistent.png", "unchanged": True}
        with (
            mock.patch.dict(mcp_server.SCALES, {"s": 0.5}),
            mock.patch.object(mcp_server, "call", return_value=capture) as call,
        ):
            mcp_server.looked("s", {"delivered": True}, True)
        self.assertEqual(call.call_args.kwargs["scale"], 0.5)


if __name__ == "__main__":
    unittest.main()
