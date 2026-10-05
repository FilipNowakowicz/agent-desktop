# Personal-use pilot diary

Plan step 5. Tasks and pass threshold are in
`docs/reviews/2026-10-05-project-review/decisions.md` (decisions 1 and 8):
(a) research in Chromium, (b) a GUI configuration change verified on disk,
(c) data entry in LibreOffice Calc verified in the saved file. The operator is an
interactive coding agent using the documented interfaces. The goal is at least
20 sessions over at least 10 working days. Elapsed times are wall-clock, including
the operator's own thinking between calls.

Count: **6 sessions, 6 completed, 0 developer changes needed mid-task, 0 human
rescues, 0 wrong-target or host-input actions.**

| # | Date | Task | Interface | Result | Elapsed | Obstacles and recovery | Cleanup |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-10-05 | (a) Latest Python release from python.org/downloads | CLI | Completed: 3.14.8 (development: 3.15), read via `ui` | 74 s | gnome-keyring "Choose password for new keyring" dialog over the page; the agent pressed Cancel through `ui-action`. Fixed for later sessions (#56). | No leftovers |
| 2 | 2026-10-05 | (c) Four-row budget in Calc, saved as .ods | CLI | Completed: the file holds exact values and `SUM(B2:B4)` = 1740 | 65 s | First-run "Welcome" dialog; closed it by clicking with an observation token. 21-step `actions` run with no stops. | No leftovers; LibreOffice lock file left next to the document (destroyed without closing) |
| 3 | 2026-10-05 | (b) Chromium "Show Home button" on | CLI | Completed: `browser.show_home_button: true` in Preferences within 12 s | 101 s | `chrome://` URLs passed on the command line open a new tab instead; typed the URL into the address bar. Accessibility was unavailable on that branch (fixed in #52), so the agent worked from screenshots. | No leftovers |
| 4 | 2026-10-05 | (a) Latest stable Linux kernel from kernel.org | MCP | Completed: 7.2.9 (mainline 7.3-rc6, 2026-10-04), read via `desktop_ui` | 13 s | None; no keyring dialog after #56 | No leftovers |
| 5 | 2026-10-05 | (b) LibreOffice user name (Tools > Options > User Data) | MCP | Completed: givenname/sn/initials `Pilot`/`Tester`/`PT` in `registrymodifications.xcu` | 51 s | First-run welcome dialog closed by clicking. A `ui_action` step in `desktop_actions` could not name `set_text` (AttributeError); fell back to single `desktop_ui_action` calls. Fixed in #61. | No leftovers |
| 6 | 2026-10-05 | (c) Temperature table with `AVERAGE`, saved as .xlsx | MCP | Completed: exact values and `AVERAGE(B2:B4)` = 20 in the .xlsx | 51 s | Keep-format dialog answered by clicking. A cropped screenshot taken right after the 23-step sequence showed B5 not yet repainted; a full screenshot moments later was correct. Closed Calc with Ctrl+Q before destroy: no lock file. | No leftovers |

## Findings that changed the product

- **MCP server could not find the runtime** (before session 1): this repository's
  `.mcp.json` inherits the client's PATH, so `desktop_create` failed with
  `Missing executable: labwc`. Fixed by runtime selection (#52).
- **Keyring prompt** (session 1): the private bus activated the host's
  gnome-keyring. Fixed by masking secret-service activation (#56).
- **Takeover typed QWERTY on a Dvorak host** (user check, outside the task count):
  wayvnc used its default layout for the viewer's key positions. Fixed by
  detecting the host layout (#60); the user confirmed it.
- **`ui_action` steps in sequences** (session 5): no way to name the UI action.
  Fixed by the step's `name` field (#61).

## Notes for the next sessions

- Wait for a settled screen (`stable_ms`) before verifying with a screenshot right after a long sequence.
- Close applications before `destroy` when the saved file matters (lock files).
- Vary the inputs (other sites, settings, data) so the pilot measures general
  use rather than repeating one script.
