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


class HostSettleAndOpenTests(unittest.TestCase):
    """Stand-ins for the person's screen: no host session is created."""

    def test_screenshots_right_after_input_settle(self):
        desktop = Worker.__new__(Worker)
        self.assertFalse(desktop.just_acted())
        desktop.mark_mutation()
        self.assertTrue(desktop.just_acted())
        with mock.patch("agent_desktop.worker.time.monotonic", return_value=10**9):
            self.assertFalse(desktop.just_acted())

    def test_open_without_a_bridge_uses_the_running_firefox(self):
        desktop = Worker.__new__(Worker)
        desktop.info = {"mode": "host"}
        desktop.env = {"HOME": "/home/person"}
        desktop.browser = None
        desktop.attach_browser = mock.Mock(return_value=False)
        desktop.launch_on_host = mock.Mock()
        result = desktop.browser_request(
            {"action": "open", "url": "https://example.com/a", "new_tab": True}
        )
        desktop.launch_on_host.assert_called_once_with(
            ["firefox", "--new-tab", "https://example.com/a"], "/home/person"
        )
        self.assertTrue(result["delivered"])
        self.assertIn("cannot be read", result["note"])
        # Only a new tab, only web URLs, and nothing else without a bridge.
        for request in (
            {"action": "open", "url": "https://example.com/a"},
            {"action": "open", "url": "file:///etc/passwd", "new_tab": True},
            {"action": "text"},
        ):
            with self.subTest(request=request), self.assertRaises(ValueError):
                desktop.browser_request(request)
        desktop.launch_on_host.assert_called_once()

    def test_host_launch_uses_lua_dispatch_when_hyprland_asks(self):
        from agent_desktop.worker import lua_string

        self.assertEqual(lua_string('a "b" \\ c'), '"a \\"b\\" \\\\ c"')
        desktop = Worker.__new__(Worker)
        desktop.env = {"HYPRLAND_INSTANCE_SIGNATURE": "sig", "PATH": "/bin"}
        replies = [
            subprocess.CompletedProcess(
                [],
                0,
                "error: 3 ...: ')' expected\n Note: dispatch in lua is a shorthand",
                "",
            ),
            subprocess.CompletedProcess([], 0, "ok\n", ""),
        ]
        with (
            mock.patch(
                "agent_desktop.worker.shutil.which", return_value="/bin/hyprctl"
            ),
            mock.patch(
                "agent_desktop.worker.subprocess.run", side_effect=replies
            ) as run,
        ):
            desktop.launch_on_host(
                ["firefox", "--new-tab", "https://e.example/"], "/home/p"
            )
        second = run.call_args_list[1].args[0]
        self.assertEqual(second[:2], ["hyprctl", "dispatch"])
        self.assertTrue(
            second[2].startswith('hl.dsp.exec_cmd("cd /home/p && exec firefox')
        )
        # An answer other than "ok" is a failure, even with exit status 0.
        with (
            mock.patch(
                "agent_desktop.worker.shutil.which", return_value="/bin/hyprctl"
            ),
            mock.patch(
                "agent_desktop.worker.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    [], 0, "error: no such dispatcher", ""
                ),
            ),
            self.assertRaisesRegex(RuntimeError, "no such dispatcher"),
        ):
            desktop.launch_on_host(["true"], "/")
