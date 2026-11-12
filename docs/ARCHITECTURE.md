# Architecture

How Agent Desktop is put together, from `src/agent_desktop/`. This describes the
code as of its date; the [desktop guide](USAGE.md) covers behavior and the
[project plan](project/PROJECT_PLAN.md) covers direction. The runtime is
experimental. Applications run as the current user, and a private desktop is not a
security sandbox.

## Shape

```
 MCP client ──stdio──> mcp_server.py ─┐
 person / script ───> cli.py ─────────┤
                                      v
                                   core.py  ──(JSON line over a Unix socket)──>  worker.py
                                   (library)         control.sock              (one per session)
                                                                                  │
                          compositor (labwc), private D-Bus, AT-SPI, Xwayland, Firefox, applications
```

The CLI and the MCP server are thin adapters over one library, `core.py`. Neither
holds session state. Every session is its own process tree with its own compositor,
D-Bus and home directory, and `core.py` talks to it over a Unix socket.

## Components

| Module | Role |
| --- | --- |
| `cli.py` | The `agent-desktop` command: create, list, destroy, doctor, wait, ui, browser, jobs, lease, host, profiles, import-cookies, events, review, prune and more. Calls `core`. |
| `mcp_server.py` | The `agent-desktop-mcp` stdio server (FastMCP). One `desktop_*` tool per operation, each run in a worker thread so a long wait does not block other sessions. Holds one controller id for its lifetime. |
| `core.py` | Session lifecycle and the client side of the protocol: `create`, `request`, `destroy`, `recover`, profiles, host requests, `run_actions`, `wait`, activity and trace reports, state-directory paths. |
| `worker.py` | The per-session supervisor and worker. Starts the compositor and services, serves the control socket and implements every operation (input, screenshots, windows, UI, browser, leases, takeover, host guard, cleanup). Much the largest module. |
| `wayland.py` | A small pure-Python Wayland client: virtual pointer (`zwlr_virtual_pointer`), virtual keyboard (`zwp_virtual_keyboard`) with layout-aware key placement, toplevel list (`zwlr_foreign_toplevel`), clipboard via data-control, output size, and input-activity detection on a host display. |
| `atspi.py` | Reads and acts on application UIs through the session's own AT-SPI bus (jeepney). Used by `desktop_ui`, `desktop_ui_action` and element waits. |
| `browser.py` | The Firefox bridge client: a WebDriver BiDi connection with the page-side scripts for DOM reads, finds and trusted input. The worker owns the connection and its leases. |
| `operations.py` | Durable private-session jobs: a detached helper process sends guarded steps, with per-step delivery evidence, cooperative cancel and optional scoped checks. No retry or resume. |
| `checks.py` | Scoped read-only predicates (file, config, UI, browser state). Unknown evidence never counts as satisfied. |
| `effects.py` | The effect ledger: what an action changed (files via inotify, windows, processes, optionally UI). |
| `events.py` | Derives a stream of events for shells and notifiers from state files already on disk (see [EVENT_CONTRACT](project/EVENT_CONTRACT.md)). |
| `viewer.py` | Optional observer and human takeover over private Unix VNC sockets (wayvnc). |
| `hostprompt.py` | Shows a host-session request as a notification and records the answer. |
| `cookies.py` | `import-cookies`: copies chosen sites' cookies from the person's Firefox files into a named profile. Run by the person, not by agents. |
| `doctor.py` | Preflight checks and the `smoke` session. |
| `printed.py` | Builds commands printed for the person so that they run as printed. |
| `script.py`, `script_jobs.py` | `desktop_run` scripts: the library scripts import, and the bounded process-group runner. Experimental. |
| `atlas.py` | Lookup in effect-atlas files (which control changes which setting). Experimental. |
| `review.py` | Renders saved run, operation and check JSON as an offline HTML timeline. Experimental. |

## A session

`core.create` makes a 12-hex-character id, writes `session.json`, and starts
`python -m agent_desktop.worker` detached. That process takes the profile lock if
there is one and forks into two, both child subreapers:

- the **guardian** waits for the worker; if the worker dies abnormally it stops
  every process carrying the session token and marks the session failed;
- the **worker** starts the session and serves requests.

For a headless or visible session the worker writes a minimal labwc configuration
(window bindings only, so the defaults cannot act on the host), then starts, in
order: labwc (`WLR_BACKENDS=headless`, or `wayland` nested in the host for visible
mode), the optional host guard (`guard_host`, which keeps the host's display out of
activated services), a private `dbus-daemon`, the AT-SPI registry when at-spi2-core is
installed (otherwise the session starts without accessibility and says why), the
virtual pointer and keyboard, the toplevel tracker, and the optional effect ledger.
Applications get a private `HOME`; labwc starts Xwayland lazily for X11 clients.
Firefox is started on request with a remote-debugging port and the worker connects
to it for the bridge. The wayvnc viewer is started only on request.

A **host session** attaches to the person's own Wayland display instead of starting
a compositor. It exists only after the person approves a request
(`request_host` / `agent-desktop host`), expires, refuses input while the person is
active or the screen is locked or off, and does not offer takeover, AT-SPI access or durable jobs.

## A request

An MCP tool call such as `desktop_click` travels like this:

1. `mcp_server.py` receives it and calls `core.request(session, "click", controller, ...)`.
2. `core.request` reads the session's `session.json`, picks a time budget, and
   sends one JSON line (with a deadline and the controller id) to `control.sock`.
3. The worker's `serve` loop accepts it and traces it. `handle` checks the deadline,
   then the guards in order: the host-session refusals, the controller **lease**
   (one controller at a time, 60 s default, mutating requests from others refused
   with nothing sent), and, for pointer input, the **observation token**. The token
   is a hash of the output and the window layout, focus and states plus a control
   epoch. If it changed since the screenshot, the input is refused as stale.
4. Coordinates are mapped through the screenshot token's crop and scale, bounds
   checked, and sent through the Wayland virtual pointer. Typing and keys go through
   the virtual keyboard. `ui_action` presses or sets text through AT-SPI instead of
   by position, and browser operations go through the BiDi bridge.
5. The reply is a JSON line (`ok`/`result` or `error`, with `uncertain` for results
   that may have partly run). `core.request` raises `DeliveryUnknown` rather than
   retrying when a sent request has no reliable reply.
6. With `screenshot=true`, `mcp_server.looked` then asks the worker for a screenshot
   once the screen has been still for 0.3 s (3 s at most) and returns it with a new
   token. Screenshots are taken with `grim` and saved as PNGs under the session.

Batches (`desktop_actions` / `run_steps`) send many such steps in order, with
guards on targets and expectations, and stop at the first failure. A **job**
(`desktop_operation`) does the same from a separate helper process that records
every step to disk, so its status survives the caller and is readable while the
worker is busy.

A person can take control (`take`): the worker starts an interactive VNC server,
agent input is refused, and observation tokens go stale when control returns.

## Where state lives

| Location | Contents |
| --- | --- |
| `$XDG_STATE_HOME/agent-desktop/` (default `~/.local/state/agent-desktop/`; override `AGENT_DESKTOP_STATE_DIR`) | One directory per session: `session.json` (the manifest, including a secret token and status), `session.log`, `dbus.log`, `trace.jsonl` (action trace), `screenshots/`, `operations/` (job records), `config/` (labwc) and `home/` (the private home, unless a profile is used). Also `profiles/<name>/home` (persistent logins and app data, with a lock and `last-session.json`) and `host-request.json`. |
| `$XDG_RUNTIME_DIR/agent-desktop/<session>/` (a private `/tmp/agent-desktop-<uid>` when unset) | Sockets and markers that must not outlive a boot: `control.sock`, the Wayland socket, the D-Bus socket, `vnc.sock`, `x-display`, `take-requested`. |
| `$XDG_DATA_HOME/agent-desktop/runtime` (or `AGENT_DESKTOP_RUNTIME`) | An optional installed desktop runtime (labwc, wlroots and tools) that is put first on `PATH`; otherwise tools come from `PATH`. |

The state root is the contract between the processes: `events`, `activity`, `usage`,
`prune` and `review` read these files rather than asking a live worker.

## Experimental parts

Not marked experimental: sessions, profiles, input, screenshots,
observation tokens, AT-SPI access, the Firefox bridge, leases, takeover and the
cleanup guardian.

Marked experimental in the code and [guide](USAGE.md): host sessions, durable
operations and scoped checks, the effect ledger (`AGENT_DESKTOP_EFFECTS=1`), the
effect atlas (`AGENT_DESKTOP_ATLAS`, `desktop_atlas`, `desktop_set`), scripts
(`AGENT_DESKTOP_RUN=1`, `desktop_run`), changed-only screenshots
(`AGENT_DESKTOP_LOOK_DELTA=1`) and the offline review. The gated experiments behind
the last four missed their gates; see the [directions board](project/DIRECTIONS.md).
