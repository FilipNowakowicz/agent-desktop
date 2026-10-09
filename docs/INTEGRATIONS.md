# Integrations

Agent Desktop provides a CLI and a stdio MCP server for clients that support
local MCP tools. No model or cloud service is required by the runtime itself.

## MCP

Run the stdio server with `uv run agent-desktop-mcp`. It exposes session lifecycle,
launch, windows, PNG images with dimensions, input and logs through the same core.
Desktop sessions persist when an MCP client disconnects; destroy them explicitly.
The server sends instructions to the client describing the screenshot/act/verify
loop and the login handoff (`desktop_request_human`, `desktop_control`, profiles).

A generic client configuration looks like:

```json
{
  "mcpServers": {
    "agent-desktop": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/agent-desktop", "run", "agent-desktop-mcp"]
    }
  }
}
```

The client must pass the user runtime environment (`XDG_RUNTIME_DIR` and, for
visible mode, `WAYLAND_DISPLAY`). The server selects the desktop runtime itself
(`AGENT_DESKTOP_RUNTIME`, then `~/.local/share/agent-desktop/runtime`, then PATH;
see [runtime/INSTALL.md](../runtime/INSTALL.md#selecting-a-runtime)), so the
client does not need to adjust PATH. The protocol is also tested with the official Python SDK's
stdio client.

### Claude Code

This repository includes a project-scoped `.mcp.json` declaring the
`agent-desktop` server. Start `claude` in the repository and approve the project
server when asked; the desktop tools then appear as `mcp__agent-desktop__*`.
With the Nix runtime linked at `~/.local/share/agent-desktop/runtime`, or the
Ubuntu packages installed, no further environment setup is needed.

The project file applies only to sessions started in this repository. To give
every Claude Code session on the machine the desktop tools, register the server
at user scope with the checkout's absolute path:

```sh
claude mcp add --scope user agent-desktop -- \
  uv --directory /path/to/agent-desktop run agent-desktop-mcp
```

The server's instructions (sessions, host requests, login handoff) reach the
client with the tools, so no separate skill or prompt is needed. The server runs
whatever is checked out at that path.

`scripts/claude_code_task.py` runs a real end-to-end check. It starts Claude Code
non-interactively, with no built-in tools and only this MCP server. The agent must
create a session, launch Chromium on a local page, read a code that exists only
in the rendered screenshot, type it, drag a box into a target and submit. The
harness then verifies the page state itself, records host focus and pointer
(Hyprland only), and destroys the session. It uses your Claude Code account.
A 20-task suite and its results are in [the benchmark report](BENCHMARK.md).

