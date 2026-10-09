# Host-session browser trial, 2026-10-09

First real task in host mode on the maintainer's own screen: install a userscript
manager and a userscript in the running Firefox, test it live in open tabs,
create a webhook in a web app's settings, and reinstall and reload several times.
The operator was an interactive coding agent driving the **CLI** from a shell
(the MCP server was not loaded; see finding 6). Desktop: NixOS, Hyprland,
1920×1080 at scale 1, mako, hypridle. Build: `a34e06e`. The maintainer watched
and sometimes used the computer during the sessions.

## Results

| Session | Length | Traced actions | Screenshots | Notes |
| --- | --- | --- | --- | --- |
| `ae6efba8cd7e` | 1.4 min | 23 | 8 | install; no problems |
| `3ea87a689fd3` | 11 min | 46 (3 refused, `UserActive`) | 19 | test; idle screensaver started mid-session |
| `97d9ba6d2be3` | 11 min | 95 | 32 | web-app settings, two reinstall rounds, verification |

The task was completed. Clicks landed where intended. No input reached an
application other than the intended one, but see finding 2: one shortcut was
reported `delivered` and had no effect.

Worked well:

- `host request` blocked until the notification was clicked and then returned a
  ready session; the start and end notifications were clear; `host stop` cleaned
  up at once.
- Input was refused with `UserActive` three times while the maintainer was using
  the machine, and nothing was sent.
- A CLI call took about 0.08 s, screenshots 80–160 ms. Region screenshots were
  the cheapest way to check a tab bar or a dialog.
- `trace.jsonl` exposed finding 2, and it records refusals.

## Findings, by severity

### 1. Host sessions ignore idle, screensaver and lock state (high)

The idle screensaver started during session `3ea87a689fd3`. A region screenshot
came back flat grey, and `key t --modifier ctrl` returned `"delivered": true`
without effect. Had it been a lock screen, typed text could have gone into the
password field. `src/` has no handling for idle inhibition or locking.

- Keep the machine awake for the whole host session, as the maintainer asked:
  hold an idle and sleep inhibitor from start until expiry or destroy, for
  example with `systemd-inhibit --what=idle:sleep`, logind `Inhibit()`,
  `org.freedesktop.ScreenSaver.Inhibit` or Wayland `idle-inhibit`. A manual
  `systemd-inhibit --what=idle:sleep --mode=block` was respected by hypridle,
  and the screen did not blank again for the rest of the session. Release the
  inhibitor on `host stop` and on expiry, so a crashed agent cannot keep the
  laptop awake indefinitely.
- Refuse input while the screen is locked or blanked (logind `LockedHint`, or a
  mapped `ext-session-lock` or lock layer), with a specific error such as
  `ScreenLocked` instead of `delivered`.

### 2. `delivered` and the focus fields ignore layer-shell surfaces (high)

At 17:03:25 a Ctrl+T was traced as delivered, with `focus_before` and
`focus_after` both on the Firefox toplevel `w6`. No tab opened: a layer-shell
surface (a quick-settings panel, then the screensaver) had keyboard focus, and
toplevel tracking cannot see it.

- Include layers with exclusive or on-demand keyboard interactivity in the focus
  report and the observation token (`hyprctl layers -j` showed them on Hyprland),
  or refuse keyboard input with an error such as `OverlayHasFocus`.
- Document that `delivered` means "sent to the compositor", not "handled by the
  target application".

### 3. The observation token does not change during browser work (medium)

All 8 screenshots in session 1, and the first ones in session 2, returned the
same token, `d06ed9da04af7371`, across new tabs, extension permission popups,
reloads and a change of site. This is by design (`worker.py`, `observation()`
hashes the window layout only), but in a browser it leaves guarded input
(`--observation`) with almost nothing to detect. The token also omits the
session id, so a token from one session validates in another. Popups such as
Firefox's extension prompt are xdg-popups, not toplevels, so they are not
covered either.

- Include the session id.
- In host mode, optionally add a coarse content hash (for example of a heavily
  downscaled frame).
- At least document that, in browsers, the token covers window-level changes only.

### 4. `windows` cannot tell apart windows with identical titles (medium)

Two Firefox windows had the same title (`w4`, `w6`); only `hyprctl clients -j`
showed that they were on workspaces 1 and 4. It mattered: the userscript running
in both would have acted twice. Window ids were also renumbered between sessions
(`w4`/`w6` became `w5`/`w6`).

- Add `workspace`, `x`, `y`, `width`, `height` and a visible/mapped flag to each
  window.
- Keep ids stable for the lifetime of a toplevel, if possible.
- `focus` on a window on another workspace switched the visible workspace. That
  is expected, but it could be reported (`"switched_workspace": "1"`).

### 5. A `UserActive` refusal does not require a fresh screenshot (medium)

The error says to wait a few seconds and try again. Meanwhile the maintainer had
moved focus to a terminal (`focus_before: kitty` on the refused entries), and the
agent retried the same coordinates without a new screenshot. Nothing prevented
that.

- Treat user activity like a takeover: set `needs_screenshot` or bump the control
  epoch, so the next input needs a fresh observation, and mention the screenshot
  in the error.

### 6. The MCP server loads only inside the repository (medium, documentation)

The project-scoped `.mcp.json` applies only to clients started in the repository.
A session started in another directory had no desktop tools, and asking it to
"use the agent desktop" first produced "not available". The CLI worked as a
fallback.

- Show the user-scope setup in `docs/INTEGRATIONS.md`:
  `claude mcp add --scope user agent-desktop -- uv --directory /path/to/agent-desktop run agent-desktop-mcp`.

### 7. Smaller CLI issues (low)

- `key SESSION ctrl+t` fails with `ValueError: Invalid key name` and no hint.
  Either accept chord syntax (`ctrl+t`) or mention `--modifier` in the error.
- `scroll` acts at the pointer, so every scroll needed a `move` first. Optional
  `--x/--y` arguments would save a call.
- `host request` and `host status` do not report the expiry. The notification
  showed it and `session.json` has `expires_at`, but `host status` printed only
  the session id. Add `expires_at` and the seconds remaining.
- `session.json` holds the control `token` and was created with mode `0644`.
  `0600` would be safer, even though the socket lives in `/run/user`.
- The trace records Ctrl+T as `"key": "<character>"`. Hiding typed text is
  right, but for keys sent with Ctrl or Alt the key name would make traces
  easier to read.
- The persistent "An agent is using your screen" notification covered the
  top-right corner, where applications put search fields and close buttons.

## Operator mistakes the tool could guard against

- Keys were sent with their output discarded, so the swallowed Ctrl+T (finding 2)
  was noticed only afterwards. A stderr warning when focus did not change after a
  shortcut that normally changes it would have caught it.
- A stray tab was first blamed on a keyboard-navigation browser extension; the
  real cause was the userscript manager opening its installer in a separate tab.
  Without DOM or AT-SPI access (unavailable in host mode), screenshots invite such
  misreadings.
- Following a link in one window moved it onto the page being watched, so the
  userscript briefly ran twice. This was a planning error.
- Copying a URL through a web app's "Copy" button overwrote the clipboard. The
  agent saved and restored it (it held an image), but a clipboard save/restore
  helper in host mode would make this safe by default.

## Suggested order

1. A keep-awake inhibitor for host sessions, and refusing input while locked (finding 1).
2. Layer and lock awareness in focus reporting and delivery (finding 2).
3. Workspace and geometry in `windows` (finding 4).
4. A fresh screenshot after `UserActive` (finding 5), and the session id in tokens (finding 3).
5. Documentation and CLI polish (findings 6 and 7).
