# Development log

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
