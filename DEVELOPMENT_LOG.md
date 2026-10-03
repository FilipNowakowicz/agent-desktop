# Development log

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
