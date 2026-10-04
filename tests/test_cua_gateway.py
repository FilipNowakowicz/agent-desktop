"""Verify that comparison tools cannot retarget or bypass GUI interaction."""

import unittest
from types import SimpleNamespace

from mcp import types

from scripts.cua_gui_mcp import Gateway


class FakeClient:
    def __init__(self):
        self.calls = []
        self.result = types.CallToolResult(content=[], isError=True)

    async def list_tools(self):
        return SimpleNamespace(
            tools=[
                types.Tool(
                    name=name,
                    inputSchema={
                        "type": "object",
                        "properties": {"sandbox": {"type": "string"}},
                        "required": ["sandbox"],
                    },
                )
                for name in (
                    "computer_screenshot",
                    "computer_shell",
                    "computer_file_write",
                    "computer_launch",
                    "computer_get_accessibility_tree",
                    "sandbox_create",
                )
            ]
        )

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.result


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_target_and_restricted_tools(self):
        client = FakeClient()
        gateway = Gateway(client, "local:fixture")
        tools = await gateway.list_tools()
        self.assertEqual([t.name for t in tools], ["computer_screenshot"])
        self.assertNotIn("sandbox", tools[0].inputSchema["properties"])
        self.assertFalse(tools[0].inputSchema["additionalProperties"])
        result = await gateway.call_tool("computer_screenshot", {})
        self.assertIs(
            result, client.result
        )  # Preserve upstream errors and image content.
        self.assertEqual(
            client.calls, [("computer_screenshot", {"sandbox": "local:fixture"})]
        )
        for name, arguments in [
            ("computer_shell", {}),
            ("computer_screenshot", {"sandbox": "host"}),
        ]:
            with self.assertRaises(ValueError):
                await gateway.call_tool(name, arguments)
        self.assertEqual(len(client.calls), 1)

    def test_target_required(self):
        for target in ("", "host", "local:", "cloud:fixture", "fixture"):
            with self.assertRaises(ValueError):
                Gateway(None, target)
