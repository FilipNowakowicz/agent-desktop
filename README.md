# Private agent desktop

Give an existing agent its own Linux desktop while you keep using your computer.

An initial persistent desktop runtime and CLI work on NixOS + Hyprland, with
headless operation and a visible nested window for testing. The runtime is still
experimental. See [PROJECT_PLAN.md](PROJECT_PLAN.md) for stage status and
[DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md) for observed results.

## Use a persistent desktop

Install the runtime tools listed below, then run:

```sh
uv sync --managed-python
uv run agent-desktop create
uv run agent-desktop create --mode visible
# Commands return JSON. Use the returned session identifier:
uv run agent-desktop launch SESSION -- foot --config=/dev/null
uv run agent-desktop windows SESSION
uv run agent-desktop screenshot SESSION
uv run agent-desktop type SESSION 'hello café λ'
uv run agent-desktop key SESSION Return
uv run agent-desktop click SESSION 640 360
uv run agent-desktop scroll SESSION 120
uv run agent-desktop status SESSION
uv run agent-desktop logs SESSION
uv run agent-desktop destroy SESSION
uv run agent-desktop list
```

Headless mode never opens a host window. Visible mode requires a Wayland host and
opens a nested desktop window that you can inspect and interact with directly.
Opening that window can change host focus; closing it ends the nested session.
This is not yet an independent viewer for an existing headless session.

Each session has private display sockets, D-Bus, configuration and application
profiles. Screenshots and bounded log tails remain in
`~/.local/state/agent-desktop/SESSION/` after teardown. Set
`AGENT_DESKTOP_STATE_DIR` to choose another state directory. Input reports delivery;
verify its outcome using screenshots or application evidence.

Coordinates currently assume one output at scale 1. Drag, accessibility trees and
other keyboard layouts remain unimplemented. Applications run as your user, with
host filesystem and network access; graphical separation is not a security sandbox.

## Checks

```sh
uv run ruff check src scripts tests
uv run ruff format --check src scripts tests
uv run python -m unittest discover -s tests -v
# Optional: opens and tears down a visible test desktop.
DESKTOP_TEST_VISIBLE=1 uv run python -m unittest discover -s tests -v
```

Integration tests skip when desktop tools are missing. CI installs them explicitly
on Ubuntu; passing unit-only checks must not be described as a desktop validation.

## MCP

Run the stdio server with `uv run agent-desktop-mcp`. It exposes session lifecycle,
launch, windows, PNG images with dimensions, input and logs through the same core.
Desktop sessions persist when an MCP client disconnects; destroy them explicitly.

A generic client configuration looks like:

```json
{
  "mcpServers": {
    "private-desktop": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/private-agent-desktop", "run", "agent-desktop-mcp"]
    }
  }
}
```

The client must pass the user runtime environment (`XDG_RUNTIME_DIR` and, for
visible mode, `WAYLAND_DISPLAY`). If runtime tools are not on PATH, configure
`AGENT_DESKTOP_LABWC`, `AGENT_DESKTOP_GRIM`, `AGENT_DESKTOP_WTYPE` and
`AGENT_DESKTOP_WLRCTL` with their executable paths in the client's environment.
The protocol is tested with the official Python SDK's stdio client, including
actual image blocks and observed GUI input. Individual client applications have
not yet been configured or validated.

## Run the experiment

Install `labwc`, `foot`, `wtype`, `wlrctl`, `grim` and `dbus-run-session` using your
distribution's package manager. Python is managed with uv:

```sh
uv sync --managed-python
uv run scripts/m0_headless.py
uv run scripts/m0_headless.py --text 'agent café λ 123'
```

Executable paths can be supplied with `--labwc`, `--foot`, `--wtype`, `--wlrctl`
and `--grim`. The tested NixOS invocation is in the development log. Other Linux
distributions have not yet been tested.

The experiment creates a temporary headless labwc session with software rendering,
a private runtime directory, disposable home/configuration and a separate D-Bus
session. It launches a terminal fixture, captures screenshots, types a message and
delivers a virtual mouse click. The fixture checks actual received text and mouse
events. Session resources are stopped and removed; screenshots, logs and a JSON
report remain under `artifacts/m0/`.

When launched from Hyprland, the report compares the host workspace, focused window
and pointer position before and after. These snapshots cannot prove there was no
transient disturbance, and normal human activity can change them.

Graphical separation and disposable configuration do not constitute a security
sandbox. Applications still run as your user with host filesystem and network access.

## Next

Harden session ownership and input readiness, test real applications, and add an
independent viewer. The current roadmap records which configurations are actually validated.
