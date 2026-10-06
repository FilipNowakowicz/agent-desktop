# Personal-use pilot diary

Plan step 5. Tasks and pass threshold are in
`docs/reviews/2026-10-05-project-review/decisions.md` (decisions 1 and 8):
(a) research in Chromium, (b) a GUI configuration change verified on disk,
(c) data entry in LibreOffice Calc verified in the saved file. The operator is an
interactive coding agent using the documented interfaces. The goal is 20 sessions
with varied tasks and applications, including reuse of a named profile across
sessions. The original 10-working-day requirement was dropped on 2026-10-06
(decisions.md, later decisions): for an agent operator, days add waiting rather
than evidence, and the maintainer's own continued use is tracked separately. Elapsed times are wall-clock, including
the operator's own thinking between calls.

Result after 20 sessions (2026-10-05 and 2026-10-06): **17 of 20 completed
without a developer change or human rescue; the pass bar is 18 (decision 8), so
the pilot has not passed yet.** Session 10 completed only after a developer
change (Firefox profile, #72); session 15 could not be verified on disk (no
settings store for Thunar on this machine); session 20 failed because LibreOffice
handled navigation keys out of order (F006, #76). No input reached the
maintainer's desktop or another window. Within an application, input went to the
wrong place twice: a GTK 3 menu bar opened the wrong menu (15) and Calc cells
(20). Named profiles were reused across sessions twice (`pilot`: 11–12;
`office`: 17, 18, 20) and kept their settings. Sessions 7–20 ran through MCP.

The failures were fixed before more sessions were counted. The next step is a
second batch of 20 on the fixed build, measured against the same bar.

| # | Date | Task | Interface | Result | Elapsed | Obstacles and recovery | Cleanup |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-10-05 | (a) Latest Python release from python.org/downloads | CLI | Completed: 3.14.8 (development: 3.15), read via `ui` | 74 s | gnome-keyring "Choose password for new keyring" dialog over the page; the agent pressed Cancel through `ui-action`. Fixed for later sessions (#56). | No leftovers |
| 2 | 2026-10-05 | (c) Four-row budget in Calc, saved as .ods | CLI | Completed: the file holds exact values and `SUM(B2:B4)` = 1740 | 65 s | First-run "Welcome" dialog; closed it by clicking with an observation token. 21-step `actions` run with no stops. | No leftovers; LibreOffice lock file left next to the document (destroyed without closing) |
| 3 | 2026-10-05 | (b) Chromium "Show Home button" on | CLI | Completed: `browser.show_home_button: true` in Preferences within 12 s | 101 s | `chrome://` URLs passed on the command line open a new tab instead; typed the URL into the address bar. Accessibility was unavailable on that branch (fixed in #52), so the agent worked from screenshots. | No leftovers |
| 4 | 2026-10-05 | (a) Latest stable Linux kernel from kernel.org | MCP | Completed: 7.2.9 (mainline 7.3-rc6, 2026-10-04), read via `desktop_ui` | 13 s | None; no keyring dialog after #56 | No leftovers |
| 5 | 2026-10-05 | (b) LibreOffice user name (Tools > Options > User Data) | MCP | Completed: givenname/sn/initials `Pilot`/`Tester`/`PT` in `registrymodifications.xcu` | 51 s | First-run welcome dialog closed by clicking. A `ui_action` step in `desktop_actions` could not name `set_text` (AttributeError); fell back to single `desktop_ui_action` calls. Fixed in #61. | No leftovers |
| 6 | 2026-10-05 | (c) Temperature table with `AVERAGE`, saved as .xlsx | MCP | Completed: exact values and `AVERAGE(B2:B4)` = 20 in the .xlsx | 51 s | Keep-format dialog answered by clicking. A cropped screenshot taken right after the 23-step sequence showed B5 not yet repainted; a full screenshot moments later was correct. Closed Calc with Ctrl+Q before destroy: no lock file. | No leftovers |
| 7 | 2026-10-06 | (a) Latest Rust release from blog.rust-lang.org | MCP | Completed: Rust 1.99.0 (announced 2026-10-01), read via `desktop_ui` | 61 s | Ran beside a CPU-saturating soak. `desktop_wait` for title "Rust Blog" timed out after 40 s with `no window` and an empty list although Chromium was open: the real title is "The Rust Programming Language Blog". A failed window wait now lists `open_windows`. | No leftovers |
| 8 | 2026-10-06 | (b) LibreOffice AutoRecovery interval 10 → 3 minutes (Tools > Options > Load/Save > General) | MCP | Completed: `Recovery/AutoSave` `TimeIntervall` = 3 in `registrymodifications.xcu` | 64 s | Welcome dialog closed by clicking. Expanding the options tree through `ui_action` worked, but `activate` on the "General" row did not switch pages; clicked it instead. | No leftovers |
| 9 | 2026-10-06 | (c) Product stock table with `MAX`, saved as .ods | MCP | Completed: exact values and `MAX(B2:B5)` = 760 in the .ods | 31 s | Escape closed the welcome dialog. File name set with a `ui_action` step in a sequence (#61). Closed Calc before destroy. | No leftovers |
| 10 | 2026-10-06 | (a) Latest Node.js LTS from nodejs.org in Firefox | MCP | Completed after a developer change: v24.21.0 (LTS), read from a screenshot of the Download page | 281 s | First launch showed "Firefox is already running": the maintainer's home-manager wrapper exports MOZ_APP_DATA pointing at their own profile root. Destroyed without input; fixed (#72, profile shim) and retried. Firefox exposed no accessibility tree; Ctrl+Q did not quit (destroyed instead). | No leftovers; no session process had files open in the personal profile |
| 11 | 2026-10-06 | (b) Chromium default page zoom 125%, named profile `pilot` | MCP | Completed: `partition.default_zoom_level` 1.2239 (= log1.2 1.25) in Preferences | 42 s | Settings search, then a 5-notch wheel scroll to the Page zoom select; typed 125 into the select. | No leftovers |
| 12 | 2026-10-06 | (b) Same profile: zoom persisted; On startup → Continue where you left off | MCP | Completed: zoom still 125% (visible and in Preferences), `session.restore_on_startup` 1 | 35 s | `ui_action press` on the radio button returned delivered but Chromium did not change it; a click did. | No leftovers |
| 13 | 2026-10-06 | (c) Scores table sorted descending by Data > Sort, saved as CSV | MCP | Completed: CSV rows in order Ben 95, Zoe 88, Amir 79, Orla 72, Kai 61 | 68 s | Sort key chosen by clicking the dropdown, direction and OK through `ui_action`; file type chosen from the save dialog's format menu through `ui_action`; keep-format and CSV options dialogs answered by clicking. | No leftovers, no lock file |
| 14 | 2026-10-06 | (a) Wayland's first release date from Wikipedia in Chromium | MCP | Completed: 30 September 2008 (infobox "Release"), read from a screenshot | 91 s | Waits for an element "Initial release" timed out twice: the row is labelled "Release", and Chromium had exposed only the part of the page rendered so far (the tree ended at the visible "Original author" row). After a 4-notch scroll the lower infobox rows were in the tree. | No leftovers (destroyed with Chromium open) |
| 15 | 2026-10-06 | (b) Thunar "Show Hidden Files" on, verified on disk | MCP | **Not completed**: the setting took effect in the window (hidden folders shown) but was never saved. Thunar stores it through xfconfd, which no data directory on this machine provides (also not on the maintainer's desktop), so there was nothing to verify | 50 s | `ui_action click` on the accessible "View" menu opened the File menu instead (GTK 3 menu bar); Escape, then Ctrl+H. Not a product defect, but the in-app wrong target is recorded. | No leftovers; host xfconf untouched (no such directory) |
| 16 | 2026-10-06 | (a) Latest stable GIMP from gimp.org in Firefox | MCP | Completed: 3.2.6 (2026-09-10), seen in the news list via `desktop_ui` and confirmed on the Downloads page | 55 s | Firefox now exposes its tree (#73); navigated with the link's `jump` action. Two waits used `element`/`text` filters that did not match the page wording; a screenshot settled it. | No leftovers |
| 17 | 2026-10-06 | (c) Monthly sales on a sheet renamed "Q1", `SUM`, saved as .xlsx; new profile `office` | MCP | Completed: sheet name Q1, values 1200/1350/980 and `SUM(B2:B4)` = 3530 in the .xlsx | 60 s | Rename dialog opened by double-clicking the sheet tab, then filled through `ui_action`. File type picked from the format menu and the keep-format question answered through `ui_action`; a wait with role "push button" found nothing because LibreOffice reports "button". | No leftovers, no lock file |
| 18 | 2026-10-06 | (b) Same `office` profile: Calc "Press Enter to move selection" Down → Right | MCP | Completed: `Calc/Input` `MoveSelectionDirection` = 1 in the profile's `registrymodifications.xcu`; no welcome dialog (first-run state kept by the profile) | 59 s | The second launch showed "Tip of the Day", which took Alt+F12; the failed wait's `open_windows` named it, Escape closed it. Tree expanded through `ui_action`; page and dropdown chosen by clicking. | No leftovers |
| 19 | 2026-10-06 | (a) Debian's current stable release from debian.org in Firefox | MCP | Completed: Debian 13 "trixie", latest update 13.7 (2026-09-12), read from the paragraph's accessible name via `desktop_ui` | 37 s | A `text="stable"` wait found nothing: Firefox paragraphs listed `text=''` and every Firefox node offered `set_text`. Both were listing defects, fixed afterwards (#75). | No leftovers |
| 20 | 2026-10-06 | (c) Order table with per-row `B*C` formulas and a `SUM`, `office` profile | MCP | **Failed**: data reached the wrong cells; not saved. LibreOffice dropped keys: Home/Down sent right after a typed row, a burst of Down presses after Ctrl+Home, and the second of two consecutive Tabs. With pauses before navigation the rows landed correctly but the Total row's empty Tabs were still lost. Investigated afterwards (F006, see the development log). | 176 s | Also seen: the profile's "Enter moves right" setting from session 18 applied, so rows were navigated with Home/Down instead of Return. | No leftovers; destroyed without saving |

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
- **Personal Firefox profile** (session 10): the maintainer's home-manager
  wrapper names their own profile directory in `MOZ_APP_DATA`. Private sessions
  now drop home-path variables and start Firefox with a profile in the session
  home (#72).
- **Firefox accessibility** (sessions 10, 19): no tree without
  `GNOME_ACCESSIBILITY=1` (#73), then empty paragraph text and `set_text` on
  every node (#75).
- **Calc navigation out of order** (session 20, review F006): typed keys are
  now paced and wait for the screen to settle around navigation keys (#76).
- **Idle CPU** (soak beside the pilot): each idle worker used about 4% of a core
  scanning every process; now 0.2% (#74).
- **Misleading failed window wait** (session 7): `no window` with an empty list
  looked like a missing application when the title was wrong. A failed window
  wait now returns `open_windows` (titles and app ids).

## Notes for the next sessions

- Wait for a settled screen (`stable_ms`) before verifying with a screenshot right after a long sequence.
- Close applications before `destroy` when the saved file matters (lock files).
- Vary the inputs (other sites, settings, data) so the pilot measures general
  use rather than repeating one script.
- Use `text=` for words inside a paragraph and `element=` for a control's name;
  check the real label first (session 14 waited for "Initial release", the row
  said "Release"). Chromium exposes only the part of a page it has rendered.
- Settings tasks need an application whose settings reach disk in the session
  (Thunar's need xfconfd, which this machine does not provide).
