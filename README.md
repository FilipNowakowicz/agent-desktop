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
uv run agent-desktop focus SESSION WINDOW_ID
uv run agent-desktop screenshot SESSION
uv run agent-desktop type SESSION 'hello café λ'
uv run agent-desktop key SESSION Return
uv run agent-desktop click SESSION 640 360
uv run agent-desktop drag SESSION 300 400 900 400
uv run agent-desktop scroll SESSION 120
uv run agent-desktop status SESSION
uv run agent-desktop logs SESSION
uv run agent-desktop destroy SESSION
uv run agent-desktop list
```

Headless mode never opens a host window. Visible mode requires a Wayland host and
opens a nested desktop window that you can inspect and interact with directly.
Opening that window can change host focus; closing it ends the nested session.
While the nested window has host focus, your physical keyboard input also reaches
the agent's desktop, so do not type into it unintentionally. Use the read-only `view`
observer below to watch a headless session without this.

To observe a headless session without forwarding human input, install optional
`wayvnc` and TigerVNC's `vncviewer`, then run:

```sh
uv run agent-desktop view SESSION
```

The observer uses a Unix VNC socket inside the private session runtime directory,
with input disabled on the server and clipboard transfer/remote resizing disabled
in the client. It opens no TCP listener. Closing the viewer preserves the desktop.
TigerVNC's graphical client needs a host X11 display or Xwayland; the applications
inside the private desktop remain native Wayland. Override optional tools with
`--wayvnc`, `--viewer`, `AGENT_DESKTOP_WAYVNC` or `AGENT_DESKTOP_VIEWER`.

Each session has private display sockets, D-Bus, configuration and application
profiles. The session supervisor is a child subreaper and starts the private bus
itself, so daemonizing applications and D-Bus-activated services remain in its
process tree and are stopped at teardown. `status` lists those processes. A small
guardian process watches the supervisor; if the supervisor dies, the guardian stops
the session's processes and marks it `failed`. If both are killed, `destroy`
recovers the session using its environment token (processes that cleared their
environment cannot be found then).
Screenshots and bounded log tails remain in
`~/.local/state/agent-desktop/SESSION/` after teardown. Set
`AGENT_DESKTOP_STATE_DIR` to choose another state directory. Input reports delivery;
verify its outcome using screenshots or application evidence.

`windows` lists each window's id, title, app_id, states (`activated`, `maximized`,
`minimized`, `fullscreen`) and parent; `focus` activates one by id. Each screenshot
returns an `observation` token describing the output and windows (ids, app ids,
states, parents; not titles). Pass it with `--observation` (CLI) or `observation`
(MCP) to input requests: if a window appeared, closed or changed focus/state, or
the output changed, the request fails with `StaleObservation` and sends nothing.
Changes inside a window are not detected, and a change between the check and the
input is still possible.

Pointer input uses one persistent wlroots virtual pointer per session with absolute
coordinates in screenshot pixels. Output mode changes are tracked; anything other
than one output at scale 1 is rejected.

Keyboard input uses one persistent virtual keyboard per session. Typed text gets a
generated keymap with one key per character, so it does not depend on a keyboard
layout; up to 10000 characters per request, without fixed delays. `key` accepts
XKB keysym names (validated with the compositor's libxkbcommon) and ctrl/alt/shift/logo
modifiers. The private compositor binds only Alt-Tab, Alt-Shift-Tab and Alt-F4; labwc's
default bindings, which execute host commands such as `brightnessctl`, are not loaded.
Accessibility trees remain unimplemented. Applications run as your user, with
host filesystem and network access; graphical separation is not a security sandbox.

## Checks

```sh
uv run ruff check src scripts tests
uv run ruff format --check src scripts tests
uv run python -m unittest discover -s tests -v
# Optional: opens and tears down a visible test desktop.
DESKTOP_TEST_VISIBLE=1 uv run python -m unittest discover -s tests -v
# Repeated lifecycle cycles, optionally with busy CPU processes.
uv run scripts/lifecycle_stress.py --cycles 20 --load 4
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
`AGENT_DESKTOP_LABWC` and `AGENT_DESKTOP_GRIM` with their executable paths in the client's environment.
The protocol is tested with the official Python SDK's stdio client, including
actual image blocks and observed GUI input. Individual client applications have
not yet been configured or validated.

## Run the experiment

The runtime needs `labwc`, `grim` and `dbus-daemon`; tests also use `foot`.
The original M0 experiment script additionally needs `wtype` and `wlrctl`. Install
them using your distribution's package manager. Python is managed with uv:

```sh
uv sync --managed-python
uv run scripts/m0_headless.py
uv run scripts/m0_headless.py --text 'agent café λ 123'
```

On NixOS, an optional temporary shell can supply the actual desktop runtime tools.
Python and project dependencies remain managed with uv:

```sh
nix shell nixpkgs#labwc nixpkgs#foot nixpkgs#grim nixpkgs#wtype nixpkgs#wlrctl \
  nixpkgs#wayvnc nixpkgs#tigervnc --command zsh
# Inside that temporary shell:
uv run agent-desktop create
```

Runtime executable paths can be supplied with `--labwc` and `--grim` (the M0
script also accepts `--foot`, `--wtype` and `--wlrctl`). The tested NixOS invocation is
in the development log. Beyond the Ubuntu CI runner, other Linux distributions
have not yet been tested.

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

Harden session ownership and input readiness, expand application coverage, and
validate an interactive MCP client. See [the compatibility matrix](docs/COMPATIBILITY.md)
for tested configurations and [the roadmap](PROJECT_PLAN.md) for remaining stages.

For a scripted Chromium GUI task with a disposable profile and local HTML fixture:

```sh
uv run scripts/browser_smoke.py
```

For an optional graphical observer smoke test on Hyprland (opens and closes its
own viewer window):

```sh
uv run scripts/viewer_smoke.py
```
