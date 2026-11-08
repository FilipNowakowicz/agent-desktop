# Hyprland overhaul field report, 2026-11-07

Agents used the MCP server while redesigning the maintainer's Hyprland desktop:
reviewing mock-ups, running a new Quickshell shell in private desktops, testing it
on the real screen and demonstrating it live. The agents were not asked to file
reports, so this was reconstructed from the Claude Code transcripts of the
configuration repository, counted once per tool call. Desktop: NixOS, Hyprland
0.57, Dvorak, 1920×1080. Sessions ran on 2026-11-06 and 2026-11-07.

This is a dated record. Problems are listed as they stood at `1fd1b7b`; the
[development log](../project/DEVELOPMENT_LOG.md) records what was later changed.

## How it was used

| Pattern | MCP calls | Desktops | What the agent did |
| --- | ---: | ---: | --- |
| Shell testing in private desktops | 87 | 24 | Create with `guard_host`, launch a harness that starts nested Hyprland or Quickshell, drive it, read the result, destroy. Some lived up to 95 minutes while suites ran |
| Real-screen trial and live demo | 88 | 2 | Approved host sessions: 31 minutes clicking, dragging and typing through the real shell, and a 20-minute grant for a demo on an empty workspace |
| Design mock-up review | 58 | 6 | Open an HTML study in private Firefox, click through options with `desktop_browser`, screenshot, destroy. Each lasted about a minute or less |

The test loop paired each action with an independent check: send a click or key,
wait briefly, read `hyprctl clients -j` or the shell's state file, and screenshot
for appearance. That pairing exposed the keyboard failures below, since the tool
reported every key as delivered.

## Statistics

233 MCP calls in five sessions, 32 desktops (30 private, 2 host), 2 calls returned
an error, and 1 was refused as stale. 11 of the 29 tools were used. A further 64
shell commands called the CLI, mostly to create GPU desktops or run suites.

| Tool | Calls | | `desktop_actions` step | Count |
| --- | ---: | --- | --- | ---: |
| `desktop_launch` | 53 | | `wait` | 70 |
| `desktop_screenshot` | 48 | | `key` | 33 |
| `desktop_actions` | 34 | | `click` | 25 |
| `desktop_destroy` | 32 | | `move` | 11 |
| `desktop_browser` | 22 | | `type` | 9 |
| `desktop_key` | 18 | | | |
| `desktop_create` | 11 | | | |
| `desktop_drag` | 6 | | | |
| `desktop_click` | 5 | | | |
| `desktop_request_host` | 3 | | | |
| `desktop_status` | 1 | | | |

| Habit | Observed |
| --- | --- |
| Input calls with `screenshot=true` | 31 of 63 |
| Input calls passing an `observation` token | 0 of 63 |
| Screenshots using a crop region | 22 of 48 |
| Screen settle after input | median 409 ms, max 865 ms, all 31 quiet |
| `desktop_create` with `guard_host` | 11 of 11 |
| `desktop_actions` batches | 34, averaging 4.4 steps; 47% of steps were fixed waits, 59 s in total |
| `desktop_ui` / `desktop_ui_action` | never used; the shell was driven by coordinates |

## Value delivered

Confirmed on real hardware: the polkit prompt (focus in the password field, Cancel
refuses), Spotlight calculator, app and file search with real typing, grouped
notifications with real icons, dragging a window to another desktop in the
overview, dock minimise and restore, and edge resize and snapping.

Shell problems found: identical zsh rows in the dock menu, late SUPER+Tab previews
on real hardware, a Wi-Fi panel with no searching state, an edge drag grabbing the
neighbouring window, Tab leaving the Control Centre, and an empty-desktop rule that
would have hidden desktops on an external display.

## Problems

### SUPER+letter shortcuts hit the wrong key on non-US layouts

The virtual keyboard's keymap is US, and every key is reported `delivered`. Hyprland
resolves binds through the *configured* layout unless `input:resolve_binds_by_sym`
is set, not through the sending keyboard's keymap. Agents concluded the keyboard
"drops SUPER", and the demo fell back to `hyprctl eval`. In one case the
notification centre opened from `logo+l` and was blamed on a volume key.

Reproduced on 2026-11-08 by connecting the unchanged `VirtualKeyboard` to a nested
Hyprland 0.57.1 configured for Dvorak, in a guarded private session, with a marker
bind on each key:

| Sent | Key code | Bind that fired |
| --- | ---: | --- |
| `logo+1` | 2 | SUPER+1 |
| `logo+Tab` | 15 | SUPER+Tab |
| `logo+l` | 38 | SUPER+n |
| `logo+o` | 24 | SUPER+r |
| `logo+c` | 46 | SUPER+j |
| `logo+d` | 32 | SUPER+e |
| `logo+minus` | 12 | SUPER+bracketleft |
| `XF86AudioRaiseVolume` | pool | none |

### Chords never press the modifier, and keys cannot be held

`VirtualKeyboard.send` set a modifier mask around a tap, so no Super press or release
occurred. Release binds never fired: a SUPER+Tab switcher stuck open, which the agent
first took for a race in the shell, then wrote its own keyboard client to send a real
press and release order. Nothing could express holding a key across other input.

### GPU desktops were unavailable through the MCP

Nested Hyprland needs a GPU renderer, read from the environment at session creation.
`desktop_create` had no option for it. One agent gave up and settled for a QML syntax
check; others dropped to the CLI.

### SUPER binds failed in nested Hyprland

`SUPER+2` failed although digits match on Dvorak, with `wtype`, a `chord.py` style
keyboard and `agent-desktop key`, and keys reached the focused window as plain text.
The reproduction above shows a virtual keyboard connected directly to nested Hyprland
does fire binds, so this is specific to those paths or to that harness.

### Host screenshots failed with a raw timeout off-screen

With the session on a virtual terminal that was not showing, `grim` hung and the agent
received a Python `TimeoutExpired` containing the full command line. `host_unavailable`
checked for a screen locker and displays switched off, but not an inactive terminal.

### Smaller friction

- `"super+o"` worked but `modifiers: ["super"]` was rejected.
- Without an observation token, `screenshot=true` replied at full size, and no call
  passed one.
- An agent's synthetic input from outside the MCP was reported as the person using
  the computer.
- Hyprland blocks capture of the lock screen, so it could not be judged visually.

## Not caused by the runtime

`wtype` dropping leading keys at a load average near 30, a test harness's fake `grim`
producing 1×1 images, and a tty trial that disturbed the first session when Hyprland
exited and cleared the shared user environment.

## Notes from an earlier session

A session on 2026-10-15 kept notes during a login-gated download. Since fixed: browser
`wait` accepts `seconds`, `desktop_request_human` can withdraw, `desktop_request_host`
reports DOM availability up front, and the profile and stale-token messages are clearer.
Still open: working in a running Firefox without restarting it, a host action to open
a URL in it, and workspace awareness on the host (deferred in the project plan).
