# Development log

## 2026-10-04 — M1 persistent keyboard and safe compositor bindings

**Outcome:** keyboard input no longer uses wtype or fixed sleeps. Each session
creates one `zwp_virtual_keyboard_v1` (with the pointer, before applications)
and keeps a cumulative keymap with one keycode per keysym. A new keymap is
uploaded only when new characters appear, on the same ordered connection as the keys,
followed by a sync roundtrip. With the old wtype path, every request created a new
virtual keyboard and relied on a 200 ms start delay and 20 ms per key.

### Decisions

- Typed characters map to numeric keysyms with xkbcommon's Unicode rules
  (Latin-1 direct, otherwise `0x1000000 | codepoint`; newline, tab, backspace and
  escape map to their function keysyms). Numeric keysyms in `xkb_symbols` were
  verified with xkbcommon 1.13.2. Text is layout-independent; limit raised to
  10000 characters.
- At most 247 keys (keycodes 9–255, for X11 compatibility). When a chunk needs
  more, the keymap is replaced by that chunk's characters.
- `key` names are resolved with `xkb_keysym_from_name` from the libxkbcommon that the
  compositor already maps (found in `/proc/PID/maps`), so an invalid name fails
  before a broken keymap can reach clients. Modifiers use the virtual keyboard
  modifier request (shift 1, ctrl 4, alt 8, logo 64), as wtype did.
- The keymap is passed via `SCM_RIGHTS` from an unlinked file in the session
  state directory: `os.memfd_create` is also unavailable in the uv CPython build.
- **Host-interference fix:** `rc.xml` used `<keyboard><default/>`. labwc 0.20.2's
  defaults include Execute bindings: `W-Return` → `lab-sensible-terminal`, audio
  keys → `pactl`, brightness keys → `brightnessctl`. An agent's key request
  could therefore run host commands, including changing physical backlight. Now
  only A-Tab, A-S-Tab and A-F4 are bound. A test puts a fake
  `lab-sensible-terminal` on PATH; it ran with the old config (test failed) and
  did not run with the new one. Brightness/audio keys were not sent during testing.

### Validation

Executables came from `nix shell nixpkgs#labwc nixpkgs#foot nixpkgs#grim nixpkgs#wlrctl
nixpkgs#wayvnc nixpkgs#wlr-randr nixpkgs#chromium`, with no wtype on PATH.

- Full suite: 15 tests, 1 skipped (visible); visible test passed separately.
- Keyboard test (type immediately once foot is `state:active`, Ctrl-U line kill,
  invalid key, `aa café λ` + 300 distinct CJK ideographs + `zz`, exact receipt):
  10/10 idle, 10/10 with 12 busy CPU processes.
- With the same 12 busy processes: lifecycle stress 20/20
  (`artifacts/stress/397c9ca2d3dd`, median 1.86 s); Chromium smoke 3/3 including
  `browser café λ` and the 427 px drag.

### Remaining

- The unexplained extra character in visible mode is not reproduced. A plausible but
  unproven cause is host keyboard input reaching the focused nested window; the
  virtual keyboard cannot prevent that.
- IME/dead-key composition, apps reading physical layouts and key-repeat timing
  are untested. Xwayland clients are untested.
- Supervisor crash recovery is still open.

## 2026-10-04 — M1 absolute pointer and drag

**Outcome:** pointer input no longer depends on `wlrctl`. A small dependency-free
Wayland client (`agent_desktop.wayland`) binds `zwlr_virtual_pointer_manager_v1`
and `wl_output` on the private socket. It provides absolute moves, clicks, scroll
and the new `drag` operation (CLI `drag SESSION X Y TO_X TO_Y`, MCP `desktop_drag`).
Every pointer request finishes with a `wl_display.sync` roundtrip, so "delivered"
means the compositor processed the events. Whether the application acted on them
still needs a separate check. `wlrctl` is still used for window listing.

### Decisions and evidence

- **One persistent virtual pointer per session, created before any application.**
  The first version created a pointer per request. A second click at the same
  position was then lost, and so was the round-trip test's click after an
  invalid request. Destroying the seat's only pointer removes its pointer
  capability, and foot rebinds `wl_pointer` asynchronously, so the next press could
  arrive without pointer focus. With the persistent pointer the failure did not recur.
- Absolute motion uses the live output mode as its extent. Before each pointer
  operation a roundtrip processes pending `wl_output` events. Changes of mode
  update the bounds; scale other than 1 or more than one output fails closed.
  Coordinates are no longer checked by taking a screenshot.
- Drag: move, press, 8–60 interpolated motions about 10 ms apart, then release.
  Scroll matches `wlrctl` (finger source, axis, frame, axis stop).

### Validation

- `scripts/pointer_fixture.py` enables xterm button-event tracking in foot and records
  every SGR press/motion/release. Test: repeated absolute clicks hit the same
  cell; ordering is correct; a drag gives press, ≥3 held-button motions and a release with
  monotonic columns; scroll produces a wheel event; out-of-bounds drags fail.
  10/10 idle and 10/10 with 12 busy CPU processes.
- Full suite: 14 tests, 1 skipped (visible); visible test passed separately.
- `wlr-randr` 0.5.0 (optional test, added to CI): custom mode 1024×768 changes
  screenshot size and bounds; scale 2 is rejected.
- Chromium smoke task now drags across a DOM pointer-event pad: 3/3 reported exactly the
  requested 427 px over 16–17 `pointermove` events with the button held
  (`artifacts/browser/089056ae72a1`, `9160edf57803`, `6ffb5ea64282`).

### Remaining

- Keyboard input still used wtype with fixed delays at this stage.
- No HiDPI/fractional scaling or multiple outputs; drag speed is fixed; no
  modifier-held drag.

PR #11 passed Ubuntu CI (run `37161930144`; wlr-randr 0.3.0 test ran) and was merged.

## 2026-10-04 — M1 process ownership and private-bus environment

**Outcome:** session teardown now covers processes that daemonize, call `setsid`,
clear their environment or ignore SIGTERM while forking. This stage also fixed an
isolation bug in the earlier runtime: D-Bus-activated services used the host
environment.

### Decisions

- The worker marks itself a child subreaper (`prctl(PR_SET_CHILD_SUBREAPER)`),
  so orphaned descendants are reparented to it, not to init. Ownership is the
  worker's process subtree plus the existing environment-token scan.
- The worker starts `dbus-daemon --session --nofork` itself, listening on
  `RUNTIME/bus`, after the private compositor socket exists. This replaces
  `dbus-run-session`, whose daemon was outside the worker's tree. Runtime dependency
  changes from `dbus-run-session` to `dbus-daemon`.
- Teardown: graceful labwc exit, then SIGTERM to everything except the bus, then
  SIGTERM including the bus, then SIGKILL. Each phase rescans the tree so children
  forked during teardown are included. Adopted zombies are reaped without taking
  exit codes from tracked `Popen` objects. `os.pidfd_open` is still unavailable in
  the uv-managed CPython 3.12.13 build, so PID-reuse races are reduced by short
  rescans, not eliminated.
- `status` lists live session processes (PID and command name).

### Isolation bug found

The Chromium smoke task failed 4 times in a row on this branch: a GNOME Keyring
"Choose password for new keyring" dialog took focus inside the private desktop.
The same task passed on `main`. Inspecting a `main` session's bus process showed why:
`dbus-run-session` inherited the host environment, so `HOME=/home/user`, host
`WAYLAND_DISPLAY` and `HYPRLAND_INSTANCE_SIGNATURE` were set. Activated services
(gnome-keyring, mako, xdg-desktop-portal including the Hyprland backend) therefore ran
against the user's real home and host compositor. Those services were found in the
logs, but whether any of them actually changed host state was not investigated.

On this branch, activated services get the private home, runtime directory and
private Wayland socket. A test asserts the bus environment. gnome-keyring now
offers to create a keyring inside the private session. Chromium was never meant
to use a keyring here, so the disposable-profile smoke task passes
`--password-store=basic`. Other applications may still show this private prompt;
an agent sees it in screenshots.

### Validation

Executables came from `nix shell nixpkgs#labwc nixpkgs#foot nixpkgs#grim
nixpkgs#wtype nixpkgs#wlrctl nixpkgs#wayvnc nixpkgs#chromium`; `dbus-daemon` came from the system.

- `uv run python -m unittest discover -s tests`: 12 tests, 1 skipped (visible opt-in).
  The new daemonizing-application test failed before the change and left a
  `sleep` process running; that exact PID was removed manually.
- `DESKTOP_TEST_VISIBLE=1 ... -k visible`: passed once.
- `scripts/lifecycle_stress.py --cycles 20 --load 12` on the final code: 20/20
  (`artifacts/stress/c46e4769a583`, median cycle 1.79 s). Earlier branch runs:
  20/20 idle (median 1.45 s), 20/20 loaded (median 1.58 s). Each cycle verifies
  exact typed text, a token-less `setsid env -i` daemon, and no leftovers.
- `scripts/browser_smoke.py`: 3/3 passed (`artifacts/browser/3872f9b4f984`,
  `eb0281eda3fa`, `3d1d83c98dc4`). 23 session processes, including chromium,
  crashpad, xdg portals, document portal FUSE helper and mako. No Chromium D-Bus
  abort at teardown, no leftover processes or `agent-desktop` mounts.

PR #10 passed Ubuntu CI (run `37161251759`, including 5/5 loaded stress cycles)
and was merged.

### Remaining

- If the worker itself is SIGKILLed, its adopted orphans go to init. Only
  token-carrying processes are then discoverable. Crash recovery for stale
  sessions is not implemented.
- Processes started on the user's behalf by host services (host systemd user
  manager, host portals) are outside the session tree. The private bus reduces,
  but does not eliminate, this route.
- Input readiness still relies on fixed wtype delays; the stress runs did not
  reproduce a dropped or extra character. Drag was unimplemented at this stage.

## 2026-10-04 — Development handoff and checkout location

Updated the starter prompt to continue from the implemented stages, with current
issues and priorities instead of repeating M0. Removed obsolete packaging status
from the plan. The checkout is moving to `/home/user/private-agent-desktop` at the
user's request. Historical experiment paths remain unchanged as evidence.
This documentation change adds no new runtime validation claims.

## 2026-10-03 — M3 initial real application coverage

Added an opt-in Chromium smoke task with a new private user-data directory, explicit
native Wayland mode and a local HTML form. No personal profile was accessed, and
the browser sandbox was not disabled. The task typed `browser café λ`, submitted
the form through keyboard navigation, observed the expected submitted window title
and produced a changed screenshot. The final screenshot was visually inspected.

Observed version: Chromium 153.0.8010.52. Evidence is retained in
`artifacts/browser/cfac3e875848/`, including JSON report, before/after PNGs and logs.
Teardown removed the runtime and browser profile; the final owned-process scan
was empty. This is one scripted task, not a claim of general browser reliability
or model-agent completion rates. Chromium is an optional smoke-test dependency.

Added the compatibility matrix and replayable NixOS runtime-shell instructions.
The shell supplies Linux desktop executables; Python dependencies still use uv.
Ubuntu CI validates terminal/core/MCP behavior separately from this Chromium task.

Setup validation also found that CLI defaults masked runtime executable environment
overrides. The CLI now uses the same override resolution as MCP; a real CLI test
checks the selected labwc executable. Typing is capped at 1000 characters so its
paced input stays within the current tool timeout. Viewer helper discovery has a
deadline and reports its actual log tail on startup failure. CI records package
versions, and the graphical smoke test verifies ownership of the mapped viewer.

Observer PR #4 passed Ubuntu CI (run `37159636661`) and was merged. Remaining work
is tracked in issues #5 (runtime hardening), #7 (interactive client/action ownership)
and #6 (application and Linux compatibility).

## 2026-10-03 — M2 independent read-only observer

Added `agent-desktop view SESSION`, using optional wayvnc and TigerVNC. wayvnc runs
inside the private desktop and listens only on a Unix socket under its 0700 runtime
directory. Server-side input is disabled. The graphical client uses ViewOnly,
disables clipboard transfers and remote resizing, and uses disposable configuration.
No TCP endpoint or personal viewer configuration is used.

The actual VNC handshake was tested. A client deliberately sending a keyboard
event could not modify the terminal's next received message; the private input API
still worked. Disconnecting the observer preserved the session and screenshots.
The optional graphical smoke test mapped a real TigerVNC window on Hyprland, then
closed only its own viewer and confirmed that the headless desktop survived.
Tested optional packages: wayvnc 0.10.1 and TigerVNC 1.16.2, fetched temporarily
without host activation. The VNC server remains session-owned until teardown.

MCP PR #3 passed Ubuntu CI (run `37159264698`) and was merged. Observer tests are
added to CI with the distribution wayvnc package; that validation is pending.
The observer is distinct from the interactive nested testing mode: host input
cannot be forwarded through this observer, even by a client ignoring ViewOnly.

## 2026-10-03 — M2 stdio MCP integration

Added `agent-desktop-mcp`, a thin adapter over the persistent core. Tools expose
create/list/status, launch, windows, screenshot, keyboard and pointer input, logs
and destroy. Screenshot results include PNG image content and text with dimensions
and the retained artifact path. The server uses stdio and opens no network endpoint.
Runtime executable overrides are available through `AGENT_DESKTOP_*` variables.

Selected the official MCP Python SDK's stable v1 API and pinned the dependency to
`mcp>=1,<2` (resolved to 1.30.0), avoiding an incidental migration to the v2 API.
The API was checked against installed signatures and the
[official SDK](https://github.com/modelcontextprotocol/python-sdk).

A real stdio client integration test passed: initialize, discover tools, reject
an unknown session, create a desktop, launch the native Wayland terminal fixture,
receive a real PNG block, type exact `MCP café λ`, send Return, receive a left click,
and destroy the runtime. A second created session remained available after the
MCP client disconnected; it was explicitly destroyed afterward. This validates
the transport and tool/image semantics, not every client application's support.

No persistent MCP client configuration was changed. The README supplies a generic
configuration; a chosen interactive client and an independent viewer remain open.

The complete rerun passed all headless/core/MCP tests, but the visible test observed
` private café λ` (an extra leading space). Concurrent host input can reach a
nested desktop; this observation does not establish the source of that character.
Earlier visible round trips passed, but repeatability with a human using the host
is not established. The visible test remains explicit opt-in and this gap remains
tracked; it must not be reported as the same isolation guarantee as headless mode.

M1's corrected Ubuntu CI run passed (run `37159062985`), and PR #2 was merged.
The repository now requires the `runtime` status check and pull requests on main,
requires linear history and resolved conversations, and rejects force pushes and
branch deletion. No reviewer count was imposed. The private visibility was verified.

## 2026-10-03 — M1 initial persistent runtime and visible testing

Implemented a packaged `agent-desktop` CLI and persistent per-session supervisor.
The core handles create/list/status, application launch, window enumeration,
screenshots, type/key, pointer movement/click, scroll, bounded log tails and teardown.
All control requests identify a session and go to a private local Unix socket.
The supervisor serializes requests and uses a private D-Bus/display environment.

Added `create --mode visible`: labwc's Wayland backend connects to an explicit
parent display socket and opens a nested desktop window. The application's and
input clients' display remains the private socket. Headless stays the default.
The visible window's lifecycle is tied to the session; an independent observer
viewer is still deferred.

Seven local tests passed: invalid identifiers/mode, unknown session, actual app
and compositor crashes, headless input/capture/cleanup, distinct input to two
simultaneous sessions, and the opt-in visible round trip. Both round trips check
exact `private café λ` receipt, a real left mouse event, changed PNGs and removal
of the session runtime directory. Invalid requests fail without reaching a host
display. App crashes retain stderr/exit status; compositor crashes close the
endpoint, remove runtime resources and leave failure metadata/logs.

Initial validation reported unreaped supervisor warnings. A daemon reaper thread
now retains/waits for client-created supervisors, and workers reap compositors
during cleanup. The suite is rerun with ResourceWarning promoted to errors.
That rerun also exposed a fixed-coordinate assumption in the visible fixture:
the host can resize its nested output. The test now targets the center of a fresh
screenshot instead of assuming a 1280×720 desktop. Visible mode needs resize-aware
observations, and simultaneous human input can affect the nested desktop by design.

Runtime logs are trimmed above 1 MiB to a 512 KiB tail; the log API returns at most
16 KiB per file. Screenshots and session records are retained for evidence.
Cleanup still relies on a per-session environment ownership token; arbitrary
applications which daemonize or replace their environment need stronger ownership.
Input startup delays, drag, alternate layouts, accessibility and general
application compatibility remain open.

Repository setup: private GitHub repository, `main` default, issues enabled,
wiki/projects disabled, squash-only merges and automatic branch deletion. M0 was
merged through PR #1. Added CI, a PR template and a runtime failure issue form.
No host activation, permission changes or personal application profiles were used.

The first Ubuntu CI run failed at compositor startup. Inspection of older labwc
source confirmed it does not support the new `-t` title option used by the initial
runtime. Removed that optional argument for compatibility and included log tails
in startup errors so future CI failures expose their actual cause. CI is rerun
before integrating M1.

## 2026-10-03 — M0 headless experiment

**Outcome:** a disposable native Wayland application ran in an invisible labwc
desktop. Screenshots, exact text delivery, mouse-click receipt and cleanup passed
in two complete runs. The host Hyprland workspace, focused window and pointer
coordinates matched before and after both runs. This is a foundation experiment,
not M1/M2 completion or a benchmark against competing runtimes.

### Current choices

- Experiment: labwc with wlroots headless backend and pixman software rendering.
  No physical/nested display backend is requested.
- Experiment implementation: Python 3.12, uv-managed interpreter, no Python dependencies.
- Observe/input: grim, wtype and wlrctl; all target the private Wayland socket.
- Fixture: foot running a disposable Python terminal application which reports
  actual received keyboard text and SGR mouse events.
- Session services: private `dbus-run-session`, temporary runtime directory and
  home/configuration. Personal display/IPC addresses and startup hooks are excluded.
- Cleanup: graceful labwc exit followed by cleanup of remaining processes carrying
  the experiment's unique ownership token. This is prototype lifecycle handling;
  arbitrary daemonizing applications and stronger ownership mechanisms remain M1 work.

labwc was selected for this experiment because it supplies headless rendering and
the required virtual-input protocols. Hyprland was already installed, but its
v0.56.2 startup source attempts a DRM backend; it was not started as a second
compositor. Weston and KWin were not tested.

### Environment and exact invocation

| Component | Observed version |
| --- | --- |
| Host Hyprland | 0.56.2 |
| uv | 0.12.17 |
| uv-managed Python | CPython 3.12.13 |
| labwc / wlroots | 0.20.2 / 0.20.2 |
| foot | 1.28.0 |
| wtype | Nix package 0.4 |
| wlrctl | 0.2.2 |
| grim | Existing user-profile executable; exact version not established |

Temporary desktop runtime packages were fetched into the Nix store, without profile
installation or host activation. The system nixpkgs registry resolved to revision
`4975466d324710c576dc11ad614684e6bd8cad8e`.

```sh
nix build --no-link --print-out-paths nixpkgs#labwc nixpkgs#wtype nixpkgs#foot
nix build --no-link --print-out-paths nixpkgs#wlrctl
uv sync --managed-python
uv run scripts/m0_headless.py \
  --labwc /nix/store/j5dyasxafxl595i1fkpm0lvmpwx6bzn8-labwc-0.20.2/bin/labwc \
  --foot /nix/store/6nhmbaws8lqd8bvzsx4m0gw36ssyg2iy-foot-1.28.0/bin/foot \
  --wtype /nix/store/cwzg3yii4xv6hk1yn3jjgw14cxzy98qa-wtype-0.4/bin/wtype \
  --wlrctl /nix/store/39lixl7l8bah5wsv5p1xb32w14smw2rz-wlrctl-0.2.2/bin/wlrctl
```

The Unicode run added `--text 'agent café λ 123'`. Core Python metadata contains
no Nix dependency or linker paths. These store paths document this machine's
experiment; they are not portable installation instructions or permanent GC roots.

### Evidence

| Run artifact directory | Result |
| --- | --- |
| `artifacts/m0/20261003-231227/` | Initial ASCII keyboard + screenshot proof; mouse not yet implemented |
| `artifacts/m0/20261003-231417/` | Failed: first character dropped; cleanup used unavailable `os.pidfd_open` |
| `artifacts/m0/20261003-231510/` | Passed: ASCII text, left click, changed screenshot, no owned processes remaining, temporary session removed |
| `artifacts/m0/20261003-231531/` | Passed: `agent café λ 123`, left click, changed screenshot, same cleanup checks |

The screenshots were visually inspected. Both complete runs produced 1280×720
images, showing the received text and click inside the private terminal.
Mouse receipt reported left button `0`, column `67`, row `19` in the terminal.
Full reports retain command arguments and screenshot SHA-256 values.

The failed cleanup left experiment processes running. After discovering that
the uv interpreter lacks `os.pidfd_open`, cleanup was changed to token-scoped
signals; those leftover processes were removed using their exact ownership token.
A final scan confirmed no experiment token processes remained.

Adding a 200 ms input startup delay and 20 ms inter-key delay avoided the observed
first-character loss in the complete runs. This is an experimental workaround;
M1 needs an input-readiness mechanism and repetition under varying load rather
than treating fixed sleeps as a reliability guarantee.

### What is still unverified

- Transient host focus/pointer changes between the two host-state snapshots.
- Other keyboard layouts and broader Unicode coverage.
- General GUI applications, single-instance applications, Xwayland and portals.
- Window metadata, absolute coordinates, drag, scroll and persistent sessions.
- Invalid-session/backend-failure behavior at the future core API boundary.
- Other Linux distributions, actual MCP-client integration and viewer behavior.
- Cleanup for arbitrary applications which alter their environment or daemonize.

No host rebuild/activation, persistent permission changes, personal browser
profiles or unrelated application shutdowns were used.

### Prior art reviewed

- [Cua](https://github.com/trycua/cua): reference for computer-use interfaces and
  environment lifecycle. Its README was reviewed; no source was copied and no
  hands-on compatibility claims are made.
- [wbox backend documentation](https://github.com/quazardous/wbox-mcp/blob/main/docs/backends.md):
  closer reference for labwc, headless operation and compositor-targeted input.
- [Hyprland v0.56.2 startup source](https://github.com/hyprwm/Hyprland/blob/v0.56.2/src/Compositor.cpp):
  checked before choosing the safer headless-only labwc experiment.
- Local wlrctl 0.2.2 man page: verified pointer movement/click syntax.

### Next milestone

M1: convert the experiment into a small persistent session core and CLI. Start with
lifecycle/process ownership and fail-closed session routing, then launch, screenshots,
window metadata and serialized input. Keep one backend until observed failures
justify another. MCP and the optional viewer remain M2.
