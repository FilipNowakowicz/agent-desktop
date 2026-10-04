"""Exercise the real stdio transport, image blocks and desktop tools."""

import asyncio
import base64
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agent_desktop import core
from agent_desktop.worker import owned_processes


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "foot", "dbus-daemon")),
    "desktop tools unavailable",
)
class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_desktop_round_trip(self):
        with tempfile.TemporaryDirectory(prefix="desktop-mcp-test-") as directory:
            root = Path(directory)
            (root / "runtime").mkdir(mode=0o700)
            environment = os.environ.copy()
            environment["AGENT_DESKTOP_STATE_DIR"] = str(root / "state")
            environment["XDG_RUNTIME_DIR"] = str(root / "runtime")
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "agent_desktop.mcp_server"],
                env=environment,
            )
            session_id = None
            async with (
                stdio_client(params) as (read, write),
                ClientSession(read, write) as client,
            ):
                await client.initialize()
                tools = await client.list_tools()
                names = {tool.name for tool in tools.tools}
                self.assertIn("desktop_screenshot", names)
                self.assertLessEqual(
                    {"desktop_request_human", "desktop_control"}, names
                )
                # Only the person can hand control back.
                self.assertNotIn("desktop_release", names)
                unknown = await client.call_tool(
                    "desktop_type", {"session": "0" * 12, "text": "never delivered"}
                )
                self.assertTrue(unknown.isError)
                created = await client.call_tool("desktop_create", {})
                self.assertFalse(created.isError)
                session_id = json.loads(created.content[0].text)["session"]
                try:
                    fixture = root / "fixture"
                    fixture.mkdir()
                    script = (
                        Path(__file__).resolve().parents[1] / "scripts/m0_terminal.py"
                    )
                    launched = await client.call_tool(
                        "desktop_launch",
                        {
                            "session": session_id,
                            "argv": [
                                "foot",
                                "--config=/dev/null",
                                "--window-size-pixels=800x500",
                                "--title=MCP fixture",
                                sys.executable,
                                str(script),
                                str(fixture),
                            ],
                        },
                    )
                    self.assertFalse(launched.isError)
                    for _ in range(100):
                        if (fixture / "ready").exists():
                            break
                        await asyncio.sleep(0.05)
                    self.assertTrue((fixture / "ready").exists())
                    await asyncio.sleep(0.4)
                    screenshot = await client.call_tool(
                        "desktop_screenshot", {"session": session_id}
                    )
                    self.assertFalse(screenshot.isError)
                    images = [
                        block for block in screenshot.content if block.type == "image"
                    ]
                    self.assertEqual(len(images), 1)
                    self.assertTrue(
                        base64.b64decode(images[0].data).startswith(
                            b"\x89PNG\r\n\x1a\n"
                        )
                    )
                    capture = json.loads(screenshot.content[0].text)
                    text = await client.call_tool(
                        "desktop_type", {"session": session_id, "text": "MCP café λ"}
                    )
                    self.assertFalse(text.isError)
                    key = await client.call_tool(
                        "desktop_key", {"session": session_id, "key": "Return"}
                    )
                    self.assertFalse(key.isError)
                    for _ in range(100):
                        if (fixture / "mouse-ready").exists():
                            break
                        await asyncio.sleep(0.05)
                    self.assertEqual((fixture / "typed.txt").read_text(), "MCP café λ")
                    click = await client.call_tool(
                        "desktop_click",
                        {
                            "session": session_id,
                            "x": capture["width"] // 2,
                            "y": capture["height"] // 2,
                        },
                    )
                    self.assertFalse(click.isError)
                    for _ in range(100):
                        if (fixture / "mouse.json").exists():
                            break
                        await asyncio.sleep(0.05)
                    self.assertEqual(
                        json.loads((fixture / "mouse.json").read_text())["button"], 0
                    )
                    result = await client.call_tool(
                        "desktop_destroy", {"session": session_id}
                    )
                    self.assertFalse(result.isError)
                    self.assertTrue(
                        json.loads(result.content[0].text)["runtime_removed"]
                    )
                    # Disconnecting an MCP client does not implicitly own session lifecycle.
                    created_again = await client.call_tool("desktop_create", {})
                    session_id = json.loads(created_again.content[0].text)["session"]
                except BaseException:
                    await client.call_tool("desktop_destroy", {"session": session_id})
                    raise
            previous = os.environ.get("AGENT_DESKTOP_STATE_DIR")
            os.environ["AGENT_DESKTOP_STATE_DIR"] = str(root / "state")
            try:
                self.assertEqual(core.request(session_id, "status")["status"], "ready")
                token = core.manifest(session_id)["token"]
                core.destroy(session_id)
                for _ in range(100):
                    if not owned_processes(token):
                        break
                    await asyncio.sleep(0.05)
                self.assertFalse(owned_processes(token))
            finally:
                if previous is None:
                    os.environ.pop("AGENT_DESKTOP_STATE_DIR", None)
                else:
                    os.environ["AGENT_DESKTOP_STATE_DIR"] = previous
