"""Restrict a Cua stdio server to GUI tools on one explicit local sandbox."""

import argparse
import asyncio
import copy
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server import Server
from mcp.server.stdio import stdio_server

GUI_TOOLS = frozenset(
    "computer_" + name
    for name in (
        "screenshot",
        "click",
        "double_click",
        "move_cursor",
        "mouse_down",
        "mouse_up",
        "type",
        "key",
        "key_down",
        "key_up",
        "hotkey",
        "scroll",
        "drag",
        "window_list",
        "window_focus",
        "get_screen_size",
        "get_cursor_position",
        "get_current_window",
    )
)
PERMISSIONS = (
    "computer:screenshot,computer:click,computer:type,computer:key,"
    "computer:scroll,computer:drag,computer:hotkey,computer:window"
)


class Gateway:
    def __init__(self, client, sandbox):
        if not sandbox.startswith("local:") or not sandbox.removeprefix("local:"):
            raise ValueError("An explicit local:<name> sandbox is required")
        self.client = client
        self.sandbox = sandbox
        self.names = set()

    async def list_tools(self):
        tools = []
        for tool in (await self.client.list_tools()).tools:
            if tool.name not in GUI_TOOLS:
                continue
            tool = tool.model_copy(deep=True)
            schema = copy.deepcopy(tool.inputSchema)
            schema.get("properties", {}).pop("sandbox", None)
            schema["required"] = [
                x for x in schema.get("required", []) if x != "sandbox"
            ]
            schema["additionalProperties"] = False
            tool.inputSchema = schema
            tools.append(tool)
        self.names = {tool.name for tool in tools}
        return tools

    async def call_tool(self, name, arguments):
        if name not in self.names:
            raise ValueError("Tool is outside the GUI allowlist")
        if "sandbox" in arguments:
            raise ValueError("The sandbox target cannot be overridden")
        return await self.client.call_tool(name, {**arguments, "sandbox": self.sandbox})


async def serve(args):
    params = StdioServerParameters(
        command=args.cua,
        args=[
            "--embedded",
            "--state-dir",
            args.state_dir,
            "mcp",
            "--sandbox",
            args.sandbox,
            "--permissions",
            PERMISSIONS,
        ],
        env={**os.environ, "DO_NOT_TRACK": "1"},
    )
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as client,
    ):
        await client.initialize()
        gateway = Gateway(client, args.sandbox)
        await gateway.list_tools()
        server = Server("cua-gui")

        @server.list_tools()
        async def list_tools():
            return await gateway.list_tools()

        @server.call_tool()
        async def call_tool(name, arguments):
            return await gateway.call_tool(name, arguments or {})

        async with stdio_server() as (incoming, outgoing):
            await server.run(incoming, outgoing, server.create_initialization_options())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cua", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument(
        "--sandbox", required=True, help="Explicit local:<name> reference"
    )
    args = parser.parse_args()
    # Validate before starting an upstream process.
    Gateway(None, args.sandbox)
    asyncio.run(serve(args))


if __name__ == "__main__":
    main()
