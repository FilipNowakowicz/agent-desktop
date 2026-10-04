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

### Waiting

`agent-desktop wait SESSION --title Settings --stable-ms 500 --timeout 10` (MCP:
`desktop_wait`) waits for a window whose title contains the text (or `--app-id`,
or `--gone` for its disappearance), then until the screen has not changed for
`--stable-ms`, ignoring changes of at most 400 px² such as a blinking caret. It
returns `satisfied: false` at the timeout instead of failing.

### Semantic UI (accessibility)

When `at-spi2-core` is installed, each session runs its own AT-SPI registry on its
private bus and enables accessibility for its applications only (overriding host
settings such as `NO_AT_BRIDGE` or `GTK_A11Y=none` inside the session). The
registry is found in the usual libexec locations or through
`AGENT_DESKTOP_AT_SPI_REGISTRYD`; `status` reports `accessibility`.

`agent-desktop ui SESSION [--app NAME] [--window TITLE]` (MCP: `desktop_ui`) lists
visible elements as a flat list with depth: role, name, states, text, value and
actions; unnamed layout containers are omitted. `ui-action SESSION NODE press|focus|
set_text --text ...` (MCP: `desktop_ui_action`, also usable as a `ui_action` step in
action sequences) acts without coordinates, which Wayland does not provide to
AT-SPI. Coverage depends on the toolkit: GTK 3/4 and Qt expose rich trees; Chromium
needs `--force-renderer-accessibility`; X11-only and custom-drawn applications may
expose little. Like other input, actions are refused while a person has control.

### Partial and scaled screenshots

`screenshot --region X,Y,W,H --scale 0.5` (MCP: `desktop_screenshot(region=...,
scale=...)`) captures part of the desktop and/or shrinks it (0.1–1) to save image
tokens. The result reports `region` and `scale`; desktop coordinates are the region
origin plus image coordinates divided by the scale. The observation token always
describes the whole desktop.

### Action sequences

`desktop_actions` (CLI: `agent-desktop actions SESSION '[...]' --observation TOKEN`)
runs up to 50 steps such as `{"action": "click", "x": 10, "y": 20}`,
`{"action": "type", "text": "hello"}` or `{"action": "wait", "title": "Saved"}`.
Each input step is sent only while windows, focus and output match the state right
after the previous step (or the given screenshot token); otherwise the run stops
and reports the step and reason. `wait` and `focus` steps expect a change and take
a new baseline. Popups and changes inside a window are not detected, and the
result carries no observation token, so take a screenshot to verify.

### Taking control (logins, 2FA, CAPTCHAs)

An agent that reaches a login page calls `desktop_request_human` with a reason
instead of asking for your password. `agent-desktop list` shows the pending request.
Take the session yourself:

```sh
uv run agent-desktop take SESSION
```

This opens an interactive viewer on a separate Unix socket. While you hold control,
the session refuses the agent's input, focus, launch, window listing and screenshots,
so it cannot watch what you type. Closing the viewer (or `agent-desktop release
SESSION`) hands control back; the agent must then take a new screenshot before any
input, and all earlier observation tokens are stale. The agent can wait for this
with `desktop_control(session, wait_seconds=...)`; only you can release control.
The session's clipboard is never copied to your host. `take --paste` sends your
host clipboard into the session (e.g. a password from your password manager);
without it nothing is transferred. Whenever control returns, the session's
clipboard and primary selection are cleared, so a pasted secret is not left for
the agent. The session keymap is US, so characters missing from that layout may
not reach the session when typed (pasting avoids this).

### Saved logins (profiles)

By default everything in a session is deleted at `destroy`. To keep a login, create
the session with a named profile:

```sh
uv run agent-desktop create --profile github     # MCP: desktop_create(profile="github")
uv run agent-desktop profiles                    # list, size, whether in use
uv run agent-desktop delete-profile github       # permanently remove saved logins
```

The profile becomes the session's `HOME` (and so its XDG config, cache and data),
stored under `$XDG_STATE_HOME/agent-desktop/profiles/NAME/home` with mode 0700.
Only one session can use a profile at a time. Teardown first closes every window
as a person would and waits briefly, so browsers write cookies before the
compositor stops; applications still open after that are terminated. Profiles
hold login cookies and tokens on disk, readable by any process running as your
user and by any agent given that profile; they are never your personal browser
profile. Deleting a profile is CLI-only.

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

X11 applications run through the private compositor's own Xwayland when labwc
supports it (install `xwayland`); `status` reports its `x_display`. The host's
`DISPLAY` is never passed to applications.

`windows` lists each window's id, title, app_id, states (`activated`, `maximized`,
`minimized`, `fullscreen`) and parent; `focus` activates one by id and returns its
observed window state. It waits up to two seconds for the compositor to report
`activated`, failing if the window closes or activation is not observed. Focus
can change again afterward; this does not prove the application received input.
Each screenshot
returns an `observation` token describing the output and windows (ids, app ids,
states, parents; not titles). Pass it with `--observation` (CLI) or `observation`
(MCP) to input requests: if a window appeared, closed or changed focus/state, or
the output changed, the request fails with `StaleObservation` and sends nothing.
Changes inside a window are not detected, and a change between the check and the
input is still possible.

Pointer input uses one persistent wlroots virtual pointer per session with absolute
coordinates in screenshot pixels. Output mode changes are tracked; anything other
than one output at scale 1 is rejected.

Keyboard input uses one persistent virtual keyboard per session with a US layout
on real key codes (Shift for capitals and symbols). Characters a US keyboard lacks
(accents, Greek, CJK) are mapped on demand to spare keys, so any Unicode text can
be typed regardless of layout: up to 10000 characters per request, without fixed
delays. `key` accepts `repeat` (1–100) for repeated presses such as arrow keys. `key` accepts
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
The server sends instructions to the client describing the screenshot/act/verify
loop and the login handoff (`desktop_request_human`, `desktop_control`, profiles).

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
`AGENT_DESKTOP_LABWC` and `AGENT_DESKTOP_GRIM` with their executable paths in the
client's environment. The protocol is also tested with the official Python SDK's
stdio client.

### Claude Code

This repository includes a project-scoped `.mcp.json` declaring the
`private-desktop` server. Start `claude` in the repository and approve the project
server when asked; the desktop tools then appear as `mcp__private-desktop__*`.
The server inherits Claude Code's environment, so the runtime tools must be on
its PATH (on NixOS, for example, start `claude` inside the `nix shell` shown below).

`scripts/claude_code_task.py` runs a real end-to-end check. It starts Claude Code
non-interactively, with no built-in tools and only this MCP server. The agent must
create a session, launch Chromium on a local page, read a code that exists only
in the rendered screenshot, type it, drag a box into a target and submit. The
harness then verifies the page state itself, records host focus and pointer
(Hyprland only), and destroys the session. It uses your Claude Code account.
A 20-task suite and its results are in [docs/BENCHMARK.md](docs/BENCHMARK.md).

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
in the development log. Headless CI also runs in Fedora and Arch containers;
desktop installs on those distributions remain untested.

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

Expand application coverage and measure baseline efficiency. See [the compatibility matrix](docs/COMPATIBILITY.md)
for tested configurations and [the roadmap](PROJECT_PLAN.md) for remaining stages.

For a scripted Chromium GUI task with a disposable profile and local HTML fixture:

```sh
uv run scripts/browser_smoke.py
```

For Writer document creation and a Calc formula/save workflow, install optional
LibreOffice Writer, Calc and GTK3 integration, then run:

```sh
uv run scripts/office_smoke.py
uv run scripts/office_smoke.py --component writer
```

The script uses native Wayland, separate disposable office profiles, and validates
the saved ODT paragraphs and ODS formula/result. It handles known first-run
Welcome/Tip dialogs, checks session cleanup and writes artifacts under
`artifacts/office/`. File-dialog validation includes a short fixture delay;
this does not establish general application widget readiness.

For an optional graphical observer smoke test on Hyprland (opens and closes its
own viewer window):

```sh
uv run scripts/viewer_smoke.py
```

See [the benchmark report](docs/BENCHMARK.md) for verified GUI tasks and a
restricted local-container comparison. Its optional harness uses an existing
local runtime and performs no host installation or configuration.

For the reproduced X11 mapping race on wlroots 0.19.3/0.20.2, see the optional
[project-local runtime repair](runtime/README.md). Stock-package passes do not
establish reliable X11 mapping on that version.
