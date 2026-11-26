# Integrations

Agent Desktop provides a CLI and a stdio MCP server for clients that support
local MCP tools. No model or cloud service is required by the runtime itself.

## MCP

Run the stdio server with `uv run agent-desktop-mcp`. It exposes session lifecycle,
launch, windows, PNG images with dimensions, input, accessibility, the Firefox
bridge and handoffs through the same core: 17 tools by default, listed in the
[desktop guide](USAGE.md#mcp-tools). On 2026-11-26 twelve rarely chosen tools
were removed or made opt-in; that guide says what replaces each one.
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

The client should pass the user runtime environment (`XDG_RUNTIME_DIR` and, for
visible mode, `WAYLAND_DISPLAY`). Without `XDG_RUNTIME_DIR` (containers, cron,
CI) headless sessions use a private `/tmp/agent-desktop-<uid>` directory, which
must be owned by the user and closed to others. The server selects the desktop runtime itself
(`AGENT_DESKTOP_RUNTIME`, then `~/.local/share/agent-desktop/runtime`, then PATH;
see [runtime/INSTALL.md](../runtime/INSTALL.md#selecting-a-runtime)), so the
client does not need to adjust PATH. The protocol is also tested with the official Python SDK's
stdio client.

Some replies and notifications give the person a command to run (`take_command`,
`paste_command`, `host approve`, `host stop`, `import-cookies`). `uv run` puts the
project's virtual environment on the server's PATH but not on the terminal's, so
these commands use `agent-desktop` only when it is on PATH outside that
environment. Otherwise they use the installed script's absolute path, which runs
as printed. To get the short form, put the CLI on PATH with
`uv tool install --editable /absolute/path/to/agent-desktop`. A different form can
be set with `AGENT_DESKTOP_CLI` in the server's environment.

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

#### Asking in Claude Code

A host request can be asked as a Claude Code permission prompt instead of a desktop
notification, so it can be answered wherever the session is followed. A
`PreToolUse` hook answers `ask` for that one tool, which Claude Code honours even
when permission prompts are otherwise bypassed:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "mcp__agent-desktop__desktop_request_host",
        "hooks": [
          {
            "type": "command",
            "command": "printf '%s' '{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"ask\",\"permissionDecisionReason\":\"Agent Desktop asks to use your screen. Nothing runs on it until you approve; no answer means no, and the agent should ask you in chat before trying again.\"}}'"
          }
        ]
      }
    ]
  }
}
```

Then add `"env": {"AGENT_DESKTOP_HOST_APPROVAL": "client"}` to the server's entry,
so that answer is the only one (see [host sessions](USAGE.md#your-own-screen-host-session-experimental)).
Keep the hook and the variable together: the variable without the hook lets an
agent use the screen without asking. In bypass mode an agent can still run
`agent-desktop host start` through its shell, so a matching hook on that command
is worth adding too.

The reason is written for two readers, because Claude Code shows it in two places:

- **Interactive session:** the person sees it in the permission prompt. If they
  approve, the call runs and the session starts. If they decline, Claude Code
  gives the agent its own rejection message, and the server is not called.
- **Non-interactive run (`claude -p`, the SDK)** without a permission prompt tool:
  no one can answer, so Claude Code denies the call and returns the reason itself
  to the agent as an error result (`is_error: true`). The run's `result` lists it
  in `permission_denials`. This happens in `bypassPermissions` mode too.

The server is never called in either refusal, so it can't reply. The error flag is
Claude Code's, and no `PreToolUse` output turns a refused prompt into a normal
result. The only part we control is the text, so the reason says what happened
and what to do next. With the earlier reason ("An agent asks to use your
screen"), a non-interactive agent concluded it should wait for the person to
answer a prompt that was already gone. In the same check with the reason above,
it said it would ask in chat and not retry (Claude Code 2.1.332, 2026-11-25; see
the development log). The `desktop_request_host` description says the same. A
`PermissionRequest` hook can't tell an unattended run from a person who hasn't
answered yet: a hook that denied with a clearer message would also deny in
interactive sessions, so this setup doesn't use one.

`scripts/claude_code_task.py` runs a real end-to-end check. It starts Claude Code
non-interactively, with no built-in tools and only this MCP server. The agent must
create a session, launch Chromium on a local page, read a code that exists only
in the rendered screenshot, type it, drag a box into a target and submit. The
harness then verifies the page state itself, records host focus and pointer
(Hyprland only), and destroys the session. It uses your Claude Code account.
A 20-task suite and its results are in [the benchmark report](BENCHMARK.md).

