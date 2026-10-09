# Desktop user guide

Session control, observation, human handoff and runtime limits. Every operation
targets an explicit session identifier. For a first session, start with the
[quick start](../README.md#quick-start).

## Use a persistent desktop

Complete the [installation steps](../README.md#installation), then run:

```sh
uv sync --managed-python --locked
uv run agent-desktop create
# Optional alternative: create --mode visible opens a host window.
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

Typing is paced at about 8 ms per key (`AGENT_DESKTOP_KEY_INTERVAL_MS`), so
1,000 characters take about 8 s. In private sessions each switch between `type`
and `key` within a second, and each switch between characters and Tab/Return
inside a `type` text, first waits up to 1 s for the screen to stop changing. Without
this, LibreOffice applied Home, Down and Tab after text sent later, and text
sent right after a shortcut reached the cell instead of the Name Box. Host sessions skip the wait. Paste long text instead
of typing it.

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

## Waiting

`agent-desktop wait SESSION --title Settings --stable-ms 500 --timeout 10` (MCP:
`desktop_wait`) waits for a window whose title contains the text (or `--app-id`,
or `--gone` for its disappearance), then until the screen has not changed for
`--stable-ms`, ignoring changes of at most 400 px² such as a blinking caret. It
returns `satisfied: false` at the timeout instead of failing; when no window
matched, `open_windows` lists the titles and app ids that do exist.
With accessibility, `--element NAME`, `--role ROLE` and `--text TEXT` wait for a
matching UI element (e.g. a "Saved" label or a field containing a value), or for
its disappearance with `--gone`, so an action's outcome can be verified without a
screenshot.

## Semantic UI (accessibility)

When `at-spi2-core` is installed, each session runs its own AT-SPI registry on its
private bus and enables accessibility for its applications only (overriding host
settings such as `NO_AT_BRIDGE` or `GTK_A11Y=none` inside the session). The
registry is found in the usual libexec locations or through
`AGENT_DESKTOP_AT_SPI_REGISTRYD`; `status` reports `accessibility`.

`uv run agent-desktop ui SESSION [--app NAME] [--window TITLE]` (MCP: `desktop_ui`) lists
visible elements as a flat list with depth: role, name, states, text, value and
actions; unnamed layout containers are omitted. `ui-action SESSION NODE press|focus|set_text --text ...` (MCP: `desktop_ui_action`, also usable as a `ui_action` step in
action sequences) acts without coordinates, which Wayland does not provide to
AT-SPI. Coverage depends on the toolkit: GTK 3/4 expose rich trees; Chromium needs
`--force-renderer-accessibility` (sessions set `ACCESSIBILITY_ENABLED=1`) and gets
`set_text` by focusing the field and typing; Firefox needs `GNOME_ACCESSIBILITY=1`,
which sessions set; Qt 6 (kdialog) works;
X11-only and custom-drawn applications may expose little. Like other input, actions are refused while a person has control.

An action reported as delivered is only what the application said it accepted;
verify the effect. Observed exceptions: in a GTK 3 menu bar (Thunar), `click`
on any menu opened the first menu, so open menus with a pointer click or the
keyboard; Chromium accepted `press` on a settings radio button without changing
it; Chromium exposes only the part of a page it has rendered, so scroll before
waiting for an element further down.

## Partial and scaled screenshots

`screenshot --region X,Y,W,H --scale 0.5` (MCP: `desktop_screenshot(region=...,
scale=...)`) captures part of the desktop and/or shrinks it (0.1–1) to save image
tokens. The result reports `region` and `scale`. Coordinates follow the token you
pass: with this screenshot's `observation`, input tools (and every step of an
action sequence) take x/y in this image and convert them; without a token, x/y
are desktop pixels. Do not convert manually and also pass the token, or the
scaling is applied twice. The token's layout part always describes the whole
desktop.

## Act and see in one call

Input tools and `desktop_actions` accept `screenshot=true` (CLI: `--screenshot`):
after the input, the reply also carries a screenshot taken once the screen has
been still for 0.3 s (blinking carets ignored), at most 3 s later, with its
observation token. `settled` says which happened (`quiet` or `changing`) and
`settle_ms` how long it took. A still screen means the application stopped
repainting, not that it finished: a slow reply can arrive later, and a failed
input leaves the screen still too, so check the image. On their own,
`screenshot --settle-ms MS` (worker request `settle_ms`, `settle_timeout_ms`)
waits the same way before capturing. This saves a model round trip after most
inputs; `AGENT_DESKTOP_LOOK=0` hides the option (an experiment baseline).

## Web pages through the DOM (browser bridge)

`desktop_browser` (CLI: `agent-desktop browser SESSION ACTION ...`) drives Firefox
in a private session through WebDriver BiDi instead of pixels. `start` launches
Firefox (with the session's pinned profile) and `--remote-debugging-port=0`,
which listens on a free localhost port; Firefox must not already run in that
session. Then:

| Action | Does |
| --- | --- |
| `open` | navigate to `url` and wait for the load (`new_tab` for a new tab) |
| `tabs` | list tabs with url and title; `tab` picks one for later calls |
| `text` | visible text of the page or of `selector` (up to 8000 characters) |
| `find` | elements by CSS `selector`, or by visible `text`, label or placeholder (`exact` for the whole text) |
| `wait` | until an element is found, or `gone` (up to 60 s) |
| `click`, `fill`, `select` | act on the one visible, enabled match; `fill` replaces a field's text with `value` as typed keys; `select` picks an option by text or value |

`within` narrows a target to the row, list item, form or dialog containing a
text (`text="Edit", within="mallory"`). `steps` runs a list of these actions in
one call and stops at the first failure or unmet wait. Any action connects to a
Firefox already started in the session with `--remote-debugging-port`.
Clicks and keys are trusted input events from Firefox itself. If several
elements match, or the match is disabled, nothing happens and the matches are
listed. Replies carry the page url and title and the element's value afterwards,
never a password's. The bridge is a worker operation: it needs the controller
lease, is refused while a person has control and on host sessions. Any local
process of the same user could also connect to the port while Firefox runs,
like any other process of that user can control the session.

## Action sequences

`desktop_actions` (CLI: `agent-desktop actions SESSION '[...]' --observation TOKEN`)
runs up to 50 steps such as `{"action": "click", "x": 10, "y": 20}`,
`{"action": "type", "text": "hello"}` or `{"action": "wait", "title": "Saved"}`.
A `ui_action` step names its UI action as `name`, because `action` names the step:
`{"action": "ui_action", "node": "n5", "name": "set_text", "text": "Ada"}`.
Each input step is sent only while windows, focus and output match the state right
after the previous step (or the given screenshot token); otherwise the run stops
and reports the step and reason. `wait` and `focus` steps expect a change and take
a new baseline. Popups and changes inside a window are not detected, so verify the result:
`screenshot=true` appends the settled screen after the last step that ran.

### Guarded steps

Any step can carry `expect`, conditions in `wait` form (title, app_id, gone,
element, role, text, state, exact, stable_ms, timeout; default timeout 5 s)
that must hold after the step:

```json
[
  {"action": "ui_action", "role": "text", "state": "editable",
   "name": "set_text", "text": "https://example.org/hook"},
  {"action": "ui_action", "element": "Save", "role": "push button", "exact": true,
   "name": "press", "expect": {"element": "Saved", "timeout": 10}}
]
```

If an expectation fails, the run stops with `"expectation": true`; that step
counts as done, later steps are not sent. A `ui_action` step can name its
target (element, role, state, exact, window, app) instead of a node id.
The target is looked up when the step runs and must match exactly one visible
element (one with the whole name wins over substring matches); otherwise
nothing is sent and the run stops, listing what matched. `timeout` on
`desktop_actions` (CLI `--timeout`) bounds the whole run. Element conditions
need the accessibility tree, so private sessions only.

`wait` (and expectations) accept `state`: checked, unchecked, enabled, disabled,
focused, selected, expanded, collapsed, editable, pressed, busy or idle, and
`exact` to match the whole element name. Listings mark controls that cannot be
used now as `disabled`. `press` also works on check boxes and radio buttons
that only offer `check` (Chromium).

## Effect ledger (experimental)

Create sessions with `AGENT_DESKTOP_EFFECTS=1` in the environment of the CLI or
MCP server (and optionally `AGENT_DESKTOP_EFFECT_DIRS=/abs/dir:/other` for
directories outside the session home). Replies to input, launch, focus,
`ui_action` and action sequences then include `effects`: files written in the
session home (documents under `files` with a short line diff, OpenDocument
spreadsheet cells as `Sheet!B2: value [formula]`, application state under
`app_state` or as per-directory counts), windows opened, closed or retitled,
focus changes, and processes started or exited. Caches, locks and temporary
files are only counted (`noise_files`).

Applications often write after the reply. `desktop_effects(session, effect_id)`
reports everything since that action, and `wait_for_file="~/*.ods"` (or an
absolute glob) waits until a matching file has been written and gone quiet. An
empty report means nothing was observed in that window, nothing more: effects
outside the watched directories, in memory, in binary stores such as dconf, or
over the network are not seen. Research notes and measurements:
[docs/research/2026-10-08-effect-ledger.md](research/2026-10-08-effect-ledger.md).

## Effect atlas (experimental)

`scripts/effect_atlas.py APP` learns which configuration key each menu toggle
and preferences check box of an application changes, by clicking each once in
fresh private sessions, and verifies every entry. With `AGENT_DESKTOP_ATLAS`
pointing to a directory of atlas files, the MCP server offers
`desktop_atlas(query, app)` (where a setting is and which key it changes) and
`desktop_set(session, app, control)`, which writes a verified entry into a
private session's configuration without the GUI. Some applications apply such
a change while running, others at their next start; check the result.
`desktop_set` refuses host sessions, needs the session's controller lease like
any input, is refused while a person has control, and writes nothing when a key
no longer holds the value the change was learned from (for example a plugin list
another control already changed). Details:
[docs/research/2026-10-09-effect-atlas.md](research/2026-10-09-effect-atlas.md).

## Taking control (logins, 2FA, CAPTCHAs)

An agent that reaches a login page calls `desktop_request_human` with a reason
instead of asking for your password. `agent-desktop list` shows the pending request.
Take the session yourself:

```sh
uv run agent-desktop take SESSION
```

This opens an interactive viewer on a separate Unix socket. While you hold control,
the session refuses the agent's desktop tools (input, focus, launch, window
listing, screenshots and UI listing). This is cooperative routing, not a
confidentiality boundary: a read-only observer that is already open keeps
streaming, logs stay readable, and any process running as your user, including an
agent with shell access, can reach the session's sockets or call `release`. Treat
takeover as protection from the agent's tools, not from a hostile process. Closing the viewer (or `agent-desktop release
SESSION`) hands control back; the agent must then take a new screenshot before any
input, and all earlier observation tokens are stale. The agent can wait for this
with `desktop_control(session, wait_seconds=...)`; release is a cooperative user handoff, not an authentication check.
The session's clipboard is never copied to your host. `take --paste` sends your
host clipboard into the session (e.g. a password from your password manager);
without it nothing is transferred. `desktop_request_human` and `desktop_control`
return both commands (`take_command`, `paste_command`). Whenever control returns, the session's
clipboard and primary selection are cleared first, so a pasted secret is not left
for the agent; if clearing fails, control stays with you and `release` reports
the error (`release --force` hands back anyway). The session keymap is US, so
characters missing from that layout may not reach the session when typed
(pasting avoids this).

To keep a website login after the browser closes, tick its "Remember me" box.
Some sites, such as freedesktop.org GitLab, have a separate one for "sign in
with" buttons; otherwise the login is a session cookie that the browser drops
on exit, even in a saved profile.

Applications start in the session's private home directory unless `launch`
is given an absolute `cwd`; the CLI passes your current directory, so relative
paths on its command line work as in a shell. They never inherit the directory
the session happened to be created from. Unguarded sessions inherit the rest of your
environment, except variables whose value is a single path inside your home
directory (for example `MOZ_APP_DATA`, `GNUPGHOME` or `ZDOTDIR`), which would
otherwise send applications to your own files; `status` lists their names as
`home_removed_variables`. Colon-separated search paths such as `PATH` are kept.
Firefox always gets a profile in the session home (`~/.mozilla/agent-desktop`),
because a wrapper can hard-code your own profile directory: home-manager does
this with `MOZ_APP_DATA`. A `firefox` shim first on the session's `PATH` adds
`--profile` unless the arguments already choose one (`--profile`, `-P`).
Applications that start Firefox by absolute path bypass the shim.

## Your own screen (host session, experimental)

When you ask an agent to do something on your screen ("open Firefox and go to
the settings page"), it can request a host session. A notification shows its
reason: click it to allow, dismiss it to decline. From a terminal, use
`agent-desktop host approve` or `agent-desktop host deny`. The agent then uses
the normal tools on your real desktop until the session expires (default 15
minutes, at most 240) or is destroyed.

```sh
agent-desktop host start --minutes 10   # allow without a request
agent-desktop host status
agent-desktop host stop                 # end it now (bind this to a key if you like)
```

- **You come first.** When you use the mouse or keyboard, agent input is refused
  for about 3 seconds after your last activity ("UserActive", nothing sent).
  Activity is noticed after a 0.3 s pause in the agent's input, so a fast burst of
  agent steps can finish before it stops. Input that carries the observation
  token of a screenshot taken before your activity is refused too; the agent
  must look again.
- **Locked or dark screen.** While a screen locker runs (hyprlock, swaylock,
  gtklock, waylock, i3lock) or Hyprland reports every display off, input is
  refused ("ScreenUnavailable", nothing sent).
- **Notifications.** You get one when the session starts and ends.
- **Stays awake.** The session holds a logind idle inhibitor (`systemd-inhibit
  --what=idle`), so idle locking, screen blanking and idle suspend wait until it
  ends or expires; it is released with the session, even if the worker is
  killed. Lid close and manual suspend still work. Set
  `AGENT_DESKTOP_HOST_KEEP_AWAKE=0` to disable it.
- **Your windows stay open.** Applications the agent starts open through your
  desktop (`hyprctl dispatch exec` on Hyprland, otherwise `systemd-run --user`).
  Ending the session never closes your windows.
- **Not available:** takeover, viewers, `request_human` and semantic UI (the
  accessibility bus belongs to your desktop). Use a private session for those.
- **Waiting:** a live desktop rarely stops changing (clocks, terminals, video),
  so `stable_ms` waits usually time out. Wait for a window title or app id;
  element waits use the accessibility tree, which host sessions do not read.
- **Screenshots** show your whole screen, including notifications and other
  windows, and the agent's model provider receives them.
- **Requirements:** a wlroots-style Wayland desktop with virtual keyboard and
  pointer, foreign-toplevel, screencopy and ext-idle-notify (Hyprland, Sway,
  labwc), and a single monitor at scale 1 (for now).

## Guarding the host

Applications in a session run as your user. A panel button, widget or script can
therefore still power off the machine, change Wi-Fi or kill your processes
(`pkill` matches processes outside the session). `create --guard-host` (MCP:
`desktop_create(guard_host=True)`) points the session's system bus at a
non-existent socket and puts refusing stand-ins first on `PATH` for common
host-affecting commands (systemctl, loginctl, shutdown/poweroff/reboot, nmcli,
bluetoothctl, rfkill, brightnessctl, powerprofilesctl, tailscale, mullvad,
udisksctl, pkill, killall, hyprctl, swaymsg). It also removes credential
variables inherited from your environment (SSH and GPG agents, Kerberos, cloud
prefixes such as `AWS_`, and names containing TOKEN, SECRET, PASSWORD or
API_KEY); `status` lists their names. Refusals are written to `guard.log`,
which `logs` returns. This prevents accidents; it is not a
security boundary, since absolute paths and other mechanisms still reach the
host.

GTK 4 applications render in software in every session (`GSK_RENDERER=cairo`,
override with `AGENT_DESKTOP_GSK_RENDERER`); without it, layer-shell panels came
up blank.

## Saved logins (profiles)

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

`profiles` and a `create` with a profile report the profile's previous session
(`last_session` / `previous_session`): its id and whether it ended `stopped`,
`failed` (with the error) or `recovered`. After a failed or recovered end,
applications may offer to restore a crashed session. If both of that session's
supervisors were killed (`abandoned`), the next `create` on the profile first
stops the old session's processes by token, as `destroy` would, so they cannot
keep writing to the profile.

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
returns an `observation` token: a window-topology and focus guard describing the
output and windows (ids, app ids, states, parents; not titles, positions or
pixels). Pass it with `--observation` (CLI) or `observation` (MCP) to input
requests: if a window appeared, closed or changed focus/state, or the output
changed, the request fails with `StaleObservation` and sends nothing. A moved or
resized window, changes inside a window and a change between the check and the
input are not detected; verify outcomes explicitly.

Pointer input uses one persistent wlroots virtual pointer per session with absolute
coordinates in screenshot pixels. Output mode changes are tracked; anything other
than one output at scale 1 is rejected.

Keyboard input uses one persistent virtual keyboard per session with a US layout
on real key codes (Shift for capitals and symbols). Characters a US keyboard lacks
(accents, Greek, CJK) are mapped on demand to spare keys, so any Unicode text can
be typed regardless of layout: up to 10000 characters per request, paced at
about 8 ms per key (`AGENT_DESKTOP_KEY_INTERVAL_MS`). `key` accepts `repeat` (1–100) for repeated presses such as arrow keys. `key` accepts
XKB keysym names (validated with the compositor's libxkbcommon) and ctrl/alt/shift/logo
modifiers. The private compositor binds only Alt-Tab, Alt-Shift-Tab and Alt-F4; labwc's
default bindings, which execute host commands such as `brightnessctl`, are not loaded.
Applications run as your user, with
host filesystem and network access; graphical separation is not a security sandbox.

## Disk use

Each session keeps its newest 200 screenshots (`AGENT_DESKTOP_KEEP_SCREENSHOTS`);
logs are trimmed per file. Stopped and failed sessions keep their logs and
screenshots until pruned:

```sh
uv run agent-desktop usage                         # sessions by status, bytes, profiles
uv run agent-desktop prune --older-than 7 --dry-run
uv run agent-desktop prune --older-than 7
```

`prune` never removes live sessions or named profiles (`delete-profile` does that).

## Preflight and troubleshooting

```sh
uv run agent-desktop doctor          # tools, runtime directory, wlroots, accessibility
uv run agent-desktop doctor --smoke  # also create, capture and destroy a session
```

Each check reports `ok`, `warn` or `fail` with a hint; the command exits 1 on any
failure. It warns when labwc uses a stock wlroots version with the reproduced
X11 mapping race (0.19.3, 0.20.2) and recognises the project's repaired runtime
by the marker `scripts/build_xwayland_runtime.sh` writes beside the library.


For the reproduced stock wlroots 0.19.3/0.20.2 X11 mapping failure, see the
optional [project-local runtime repair](../runtime/README.md). If a window does
not appear, inspect `status`, `windows` and `logs` before sending input.

### Action trace

Each session records its recent actions in `trace.jsonl`: input, launch, focus,
UI actions, screenshots, leases and takeover changes. Each record holds the
controller, the arguments, the focused window before and after, the duration, and
the outcome or error. Typed text and `set_text` values are recorded only as their
length, single-character keys as `<character>`, and launches as the program name
and argument count. Input a person sends during takeover is never recorded. The
file is kept under 1 MB and survives `destroy` until `prune`.

```sh
uv run agent-desktop trace SESSION --limit 20
```

Set `AGENT_DESKTOP_TRACE=0` before creating a session to turn it off.

See the [compatibility matrix](COMPATIBILITY.md) for the scope of validation.
