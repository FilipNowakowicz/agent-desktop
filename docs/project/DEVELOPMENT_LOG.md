# Development log

Entries are newest first. This file holds November 2026. Earlier months are kept
verbatim in [log/2026-10.md](log/2026-10.md). The older narrative of the
[project plan](PROJECT_PLAN.md) is in
[archive/PROJECT_PLAN-history.md](archive/PROJECT_PLAN-history.md).

## 2026-11-26 — MCP tool surface: 29 default tools become 17

PR #240. This closes the plan's open item "22 tools were unused". The maintainer decided on
2026-11-26 to find out why, then remove the stale or redundant tools. The analysis
is in [research/2026-11-26-tool-surface-review.md](../research/2026-11-26-tool-surface-review.md).
It draws on `scripts/usage_review.py --since 2026-10-01` (905 calls in 35 transcripts,
from 2026-11-06 to 11-26), `agent-desktop activity --days 60` (977 worker calls) and
the October benchmark results. The "22" came from a two-day window. Across the long
window, 21 tools were called and 8 never were.

Changes, a breaking change for MCP clients (the CLI is unchanged):

- `desktop_list` and `desktop_logs` fold into `desktop_status`: called without a
  session it lists sessions, and `logs=true` adds the log tails, also for a stopped
  session.
- `desktop_move`, `desktop_drag`, `desktop_scroll`, `desktop_focus` and
  `desktop_ui_action` are removed, because they were already `desktop_actions`
  steps. The `desktop_actions` description now gives each step's arguments.
- `desktop_check` and `desktop_operation` are removed from MCP. The CLI's `check`
  and `operation` stay.
- `desktop_atlas`, `desktop_set` and `desktop_effects` are registered only when
  `AGENT_DESKTOP_ATLAS` or `AGENT_DESKTOP_EFFECTS=1` is set, as `desktop_run` already is.
- The `desktop_ui` and `desktop_windows` descriptions and the server instructions now
  say when to use accessibility and the step forms.
- The benchmark tool profiles drop the removed names. The usage review's "tools not
  called" now lists only tools registered by default, and pointer steps in
  `desktop_actions` count as coordinate input.

Schema cost, measured as in the 2026-11-11 protocol (characters of name,
description and input schema, plus instructions, divided by 4): 29 tools, 36,963
+ 3,191 characters, about 10,040 tokens, before; 17 tools, 28,819 + 3,480
characters, about 8,075 tokens, after. That is 20% less. No model runs were made.

Validation: `ruff check` and `ruff format --check` on src, scripts, tests and
benchmarks; locally `uv run python -m unittest discover -s tests` (no runtime: OK,
197 skipped); locally with the labwc/foot/grim/wtype/wlrctl/dbus nix shell,
`tests.test_mcp tests.test_usage_review tests.test_benchmark_timing` (16 tests,
OK). That includes the stdio round trip with `desktop_status` listing and
`logs=true` before and after destroy, and the new `ToolSurfaceTests`. Full desktop
suite on the worker (`on-worker run -n tool-surface-suite -- nix shell … --command
uv run python -m unittest discover -s tests -p 'test*.py'`): 538 tests in 746 s, OK
(37 skipped). That run was on the commit before the rebase onto #239, which
changes only docs and `test_mixed_workflow.py`.

## 2026-11-26 — F2 mixed workflow in Chromium (X2)

`tests/test_mixed_workflow.py` now runs the mixed workflow (download, edit in Writer, upload through the file chooser, with a refused upload and a lost reply) in Chromium as well: `ChromiumMixedWorkflowTests` reuses the Firefox class's two trials (`.odt` refused once and retried, `.docx` reply lost and reconciled) with a `ChromiumDriver`. Chromium has no DOM bridge, so the driver reads and operates the portal through the accessibility tree (`desktop_ui`: press the "Supply agreement (current)" link, the "Choose file" and "Upload" buttons, read the Received table cells and the result message). The edit, save and quit steps and the evaluator are the Firefox driver's. The class is skipped when Chromium, LibreOffice, the desktop tools or at-spi2-core are missing.

Runtime gaps: none found. The download landed in the session's `~/Downloads` (Chromium 158 writes `.crdownload`, then renames), the chooser appeared as an "Open File" GTK dialog that takes the same ctrl+L and typed path as Firefox's, and a11y `press` on the file button opened it (so it counts as a user gesture). `--force-renderer-accessibility` is required, as for the other Chromium UI tests. `Driver.upload` and `Driver.choose` were split (`send`, `choose_in_dialog`) so the two drivers share the flow.

Validation (nix shell with labwc, foot, grim, wtype, wlrctl, wayvnc, tigervnc, dbus, firefox 160.0.1, chromium 158.0.8127.36, libreoffice 26.8.3.1, at-spi2-core; `uv run python -m unittest discover -s tests -p test_mixed_workflow.py`):
- all of `test_mixed_workflow.py` (Firefox and Chromium): 9 tests OK in 111 s.
- Chromium classes only (`-k Chromium`, 2 tests, about 52 s each run), 5 runs in a row: 5 of 5 OK.
- Full desktop suite on the worker (`on-worker run -n f2-chromium-suite`, the nix shell above, `uv run python -m unittest discover -s tests -p 'test*.py'`): 528 tests in 1095 s, OK (skipped=19, expected failures=1); no failures.

Not done: an agent run of `f2-mixed-upload` in Chromium (no paid runs here); kills during agent runs.

## 2026-11-26 — AltGr-level characters for a nested Hyprland's layout (X11)

Follows #233, which left level-3 (AltGr) characters unplaced. PR #237.

Reproduced first, on main (38acb02). Guarded private session (`create --guard-host
--renderer gles2 --render-device /dev/dri/renderD129`, `__EGL_VENDOR_LIBRARY_FILENAMES`
unset), nested Hyprland 0.57.2 started inside it with `AQ_BACKEND=wayland`, a short
`XDG_RUNTIME_DIR=/run/user/<uid>/q.XXXX`, a Lua config with `input = { kb_layout = "de" }`
and a foot running `stty -echo; cat > received.txt`. `agent-desktop type SESSION
'az@€{[]}\~|µ<>²³ end'` then `key Return` arrived as `az2<ü<ü<++#<>=. end` with the
warning `12 characters have no key in the nested Hyprland's layout`.

Fix (`BindLayout(typing=True)`, used only for the nested layout; host shortcut placement
is unchanged):

- The layout's level-3 key is the key whose first level is `ISO_Level3_Shift`, Right Alt
  (code 100) when the layout puts it there. The layout's own `xkb_state` is run with that
  key held, alone and with Shift, and every key's symbol under it is placed as
  `(code, shifted, level-3 code)`. Levels one and two keep their keys. A level-3 place
  replaces an earlier one only when that key is past X11's 255 (`EuroSign` sits at level
  one of evdev code 435; `€` now goes to AltGr+e on German).
- Typed text arrives as Unicode keysyms (U+20AC, U+0105) while layouts name them
  (`EuroSign`, `aogonek`), so every place is also stored under its Unicode keysym
  (`xkb_keysym_to_utf32`). Without this, Polish `ą` and `€` stayed unplaced.
- `type` presses the level-3 key (and Shift where needed) around the character as real
  key events; `key` does the same inside the chord. The parent's modifier mask is not
  changed (labwc sees code 100 as Alt_R without a modifier mapping). A held level-3 key
  is not pressed again. `key_down` of a level-3 character is refused with a message
  (holding it would need AltGr held too); `key_down ISO_Level3_Shift` is unchanged.

Decision (default chosen without a maintainer question): characters reached only through
dead keys (for example `é` on German) or a level-5 key are still sent as US keys with the
existing warning; composing dead-key sequences is left out.

After the fix, same harness, each in a new session, received byte for byte:
`de` `az@€{[]}\~|µ<>²³ end`; `de` variant `nodeadkeys` `Grüße @ {x} € ~ end`; `pl`
`Zażółć gęślą jaźń ĄĘŁÓŚŻŹĆŃ €5 @#{} end`; `fr` `azerty @#{[|\^]}€ end`; `us` and
`us`/`dvorak` lines with capitals and punctuation (the #233 strings, plus `{y} @`).
`key` under `de` with `at EuroSign braceleft backslash bar asciitilde q shift+q` gave
`@€{\|~qQ`. Every session was destroyed and its short runtime removed; no nested
Hyprland process remained.

Unit tests (`tests/test_keyboard.py`, real libxkbcommon): German and Polish level-3
places, the euro sign on AltGr+e, shortcut layouts without AltGr places, event order for
AltGr and Shift+AltGr in `type` and `key`, and the `key_down` refusal. With the source
change reverted they fail (1 failure, 9 errors). Not covered by an automated test: the
live nested run (needs a GPU renderer and Hyprland, as for #233).

Validation:

- `uv run ruff check src tests` and `uv run ruff format --check src tests` pass.
- Locally, `nix shell nixpkgs#labwc --command uv run python -m unittest tests.test_keyboard`:
  16 tests OK.
- Worker (commit f082051, shared with another suite), `on-worker run -n altgr-suite -- nix
  shell nixpkgs#labwc nixpkgs#foot nixpkgs#grim nixpkgs#wtype nixpkgs#wlrctl
  nixpkgs#wayvnc nixpkgs#tigervnc nixpkgs#dbus nixpkgs#firefox nixpkgs#at-spi2-core
  --command uv run python -m unittest discover -s tests -p 'test*.py'`: Ran 532 tests in
  747 s, OK (skipped=37, expected failures=1).

Remaining: dead-key compositions and level-5 keys are not placed; nested compositors
other than Hyprland are still not detected.

## 2026-11-26 — Env-cleared children found without a systemd scope (X3)

Problem: with `AGENT_DESKTOP_SYSTEMD_SCOPE` off, a session child that cleared its environment (`setsid env -i …`) carries no token, and recovery after both supervisors die found processes by token only. Such children survived `destroy` and the next `create` on the profile.

Reproduction (commit 38acb02 plus the test without its `expectedFailure`, labwc/foot/grim from nixpkgs): `test_lifecycle` `test_env_cleared_daemon_is_stopped_by_recovery` failed, `[19497] != []`: the daemon still ran after `destroy` reported `recovered`.

Mechanism: both supervisors were already child subreapers, so while either lives every descendant stays in its subtree, however it detached. The guardian now keeps a record of that subtree, `STATE/<session>/processes.json` (0600, written atomically): each process's number and start time, plus the boot id. A thread rewrites it within 0.5 s of a change. Recovery (`core.recover`, so `destroy` and the next `create` on the profile) reads it and stops:
- recorded processes still running with the same number, start time and boot;
- their current descendants;
- other members of their process groups and Unix sessions. While a live member keeps a group or session number, the kernel cannot reuse it, and a process can join a group only in its own session. That covers a child forked after the record whose parent has exited.

Processes found are added to the set during the cleanup scans, so a group stays vouched for after its first member is stopped. The caller's own group and session, and those of init and the kernel, never count. A record from another boot, or one that is malformed, is ignored, and a reused number (another start time) stops nothing. The guardian and recovery delete the record when they finish.

Other options were weighed. A process-group or session id alone misses `setsid`. A subreaper alone does nothing once both supervisors are dead. A pidfd dies with its holder. cgroups are what the opt-in scope already provides. The record extends the existing subreaper design with no new dependency.

Cost: the tracker (`SubtreeWatch`) reads `/proc/<pid>/stat` only for process numbers it has not classified yet, plus its members. This is possible because under a subreaper, membership changes only by birth and death. Measured on the laptop (381 processes, a 124-process subtree): 3.4 ms per scan, compared with 34 ms for a walk through `/proc/*/task/*/children` and 11.6 ms for a full scan.

The scope stays opt-in (no maintainer decision changed). `LIFETIMES.md`, `USAGE.md`, `ARCHITECTURE.md`, `CAPABILITY_MATRIX.md`, `FUNCTIONALITY_ROADMAP.md` and the X3 row were updated.

Tests (`tests/test_lifecycle.py`, scope off):
- `test_env_cleared_daemon_is_stopped_by_recovery`: no longer an expected failure.
- `test_double_forked_daemon_is_stopped_by_the_next_session`: fork, `setsid`, fork, `env -i`; recovered by the next `create` on the profile.
- `test_child_forked_after_the_record_shares_a_recorded_session`: a child born 2 s after both supervisors died, whose parent exited, is neither recorded nor a descendant of a recorded process; it is found through the Unix session. With group and session anchoring disabled, this test fails.
- `LineageRecordTests`: another boot id, no boot id, malformed records and a reused number stop nothing; the caller's own group is never vouched for.

Validation:
- Laptop (12 cores, nix shell with labwc, foot, grim, wtype, wlrctl, wayvnc, tigervnc, dbus, firefox and at-spi2-core): `uv run python -m unittest discover -s tests -p test_lifecycle.py`, 26 tests OK (three runs, the last on the final code).
- Laptop: `SupervisorLossTests`, `LineageRecordTests` and `SystemdScopeTests` five times in a row, 11 tests OK each time.
- Worker (gcp-builder, commit 4c28aba, with another contributor's suite running at the same time): the full desktop suite, `Ran 530 tests in 753.451s`, `OK (skipped=37)`.
- After 4c28aba, the only change was that a failed write of the record is logged and retried; `test_lifecycle` was run again locally, 26 OK.

Still not covered without the scope:
- A process started in the last 0.5 s before both supervisors die.
- A process started after they die whose parent exits, when it shares no group or session with a recorded process that still runs. For example, a recorded process forks, the child calls `setsid` and the recorded process exits.
- The guardian killed long before the worker: the record stops at the guardian's death.
- Nothing escapes the scope this way, except a process that moves itself to another unit.


## 2026-11-25 — Refresh the project plan; cookie files may stay for a long job

Docs and tool text only; no tests were run.

- Decision (maintainer, 2026-11-25): a 0600 cookie export from `desktop_browser send source="cookies"` may stay on disk for the length of a long job (for example a multi-hour shell download), outside the repository or in a gitignored path, and must be deleted when the job ends. `docs/USAGE.md` and the `desktop_browser` description (one sentence) say so instead of "delete when done".
- Decision (maintainer, 2026-11-25): zero-touch delegation is not the main line now. Recent field reports show agents rarely need the person (at most one withdrawn handoff per window from 11-12 to 11-25), so Z0, Z2 and Z4-Z6 lack evidence; the shell-facing parts are deferred to the maintainer's own Hyprland and desktop-shell work in the NixOS configuration repository. `DELEGATION.md` has a note at the top and stays a design record; its advice not to merge #196 is superseded because #196 merged.
- `PROJECT_PLAN.md`: dated 2026-11-25. The former Now table (N1-N10, all done) is kept under "Completed 2026-11-11 to 11-20". A new Now section lists the open pull requests (#222-#235) with dependencies and a suggested merge order, the X1-X3 and X11 rows point to their open PRs without claiming they merged, and the remaining open items are listed.
- Validation: `ruff` and the Lint workflow only; the docstring change is text.

## 2026-11-25 — Flaky `test_during_application_work`: the kill raced the next step's dispatch

`tests/test_interruptions.py` `test_during_application_work` failed now and then on
`main` (2 of 6 local runs, 1 of 4 on another branch, once in a full worker suite).

Reproduction (commit 40c185b, 12 cores, in the nix desktop shell, the test run 20
times in a row with `uv run python -m unittest discover -s tests -p
test_interruptions.py -k test_during_application_work`): idle, 0 failing runs of 20;
beside 12 busy-loop processes (load average about 15), 6 failing runs of 20. Every
failure was the same: `'stopped' != 'delivery_unknown'`, with step 0 (`click
#slow`) `acknowledged`, step 1 (`wait`) still `pending`, `current_step` 0 and the
reason "Operation process exited with no step in flight; delivery is as recorded".

Root cause: the test, not the runtime. It killed the helper as soon as step 0 was
`acknowledged`. Under load the helper had often not yet saved step 1 as
`dispatching` (each save is an fsync'd rename), so the kill landed between steps.
Since #211 the reader reports that case as a known `stopped`, which is correct:
no input was in flight, and `test_during_a_steps_expectation` checks the same
boundary. The test still expected `delivery_unknown`, which is right only when the
kill lands inside the wait. Both outcomes left the record and the page correct: the
click stayed acknowledged, `completed` was 1 and the page counted to 1 once.

Change: the test now kills when step 1 is `dispatching`, the boundary it names
(the job is inside its wait while the page's 1.5 s timer runs), and also checks
that step 1 becomes `uncertain`. No sleep or timeout was changed; the state
assertion prints the record when it fails. Runtime code is unchanged.

Validation, same command and machine, with the change: under the same load 0 failing
runs of 20 (load average 15.8 to 16.8); idle 0 failing runs of 20; the whole
`test_interruptions.py` file 11 tests OK. `uv run ruff check src tests` and
`uv run ruff format --check src tests` pass. The load was stopped by its process
group and no sessions remain. The full suite was not rerun, since only the test
changed.

Open: a kill during a read-only browser step such as `wait` is reported as
`delivery_unknown` (the reader cannot tell which action was in flight), while a
kill just before it is a known `stopped`. That is conservative, not wrong. It is
noted here and not changed.

## 2026-11-25 — Letters for a nested Hyprland's layout (X11)

Reproduced first. Guarded private session (`create --guard-host --renderer gles2
--render-device /dev/dri/renderD129`, the NVIDIA node, with the Mesa variables unset),
nested Hyprland 0.57.2 started with `AQ_BACKEND=wayland` and a short
`XDG_RUNTIME_DIR=/run/user/<uid>/q.XXXX`, set to `us` / `dvorak` with
`hyprctl eval 'hl.config({input={kb_variant="dvorak"}})'`, and a foot running
`stty -echo; cat > received.txt` inside it. `agent-desktop type SESSION 'hello world,
Quick Test 123'` then `key Return` arrived as `d.nnr ,rpnew 'gcjt y.oy 123`: the
parent labwc forwards key codes, which the nested Hyprland reads through Dvorak, and
capitals lost their Shift because a modifier mask is not seen by the nested compositor.

Fix: while the session's focused toplevel is the nested Hyprland's window (app id
`aquamarine`), the worker finds the Hyprland the session started (descendant whose
`comm` contains `Hyprland`, its own `XDG_RUNTIME_DIR`, the `hyprland.lock` naming its
pid), reads `hyprctl -j devices` (main keyboard rules, model, layout, variant, options,
active layout index) and `input:kb_rules`/`kb_file`, and builds a `BindLayout`. `type`
sends each character to the code that layout reads as it, with a real Shift press
around shifted ones; `key`/`key_down`/`key_up` use the same layout (and `key` now
presses a real Shift for an implicitly shifted placed key). Cached for 10 s. Chosen over
uploading a different keymap because the nested compositor ignores the parent's
keymap and reads codes through its own configuration. Host sessions, other focus and
`input:kb_file` layouts are unchanged (a `warning` says when the layout could not be
read).

After the fix, the same text arrived intact under Dvorak, and a line with
capitals and punctuation (`Hello, World! (a-z) "x" {y} ~ ; : / ? @#$ <> |\ zZ`) arrived
intact under Dvorak and under US. Under `de` it arrived except `{ ~ @ | \`, which need
AltGr (level 3), so the reply carried the warning `6 characters have no key in the
nested Hyprland's layout`. Placing level-3 characters is not done. Unit tests in
`tests/test_keyboard.py` cover the typed placement, the missing count and the real Shift.
Not covered by an automated test: the live nested run above (needs a GPU renderer and
Hyprland, as in the log of 2026-11-11). All sessions I started were destroyed and no
Hyprland process remained.

Full desktop suite on gcp-worker (`on-worker run -n nested2 -- nix shell ... --command uv run
python -m unittest discover -s tests -p 'test*.py'`): 471 tests, OK, 35 skipped, 1 expected
failure. The first run (`nested`) had one failure, `test_partial_typing_preserves_uncertainty`,
because `type` was now called with an extra argument; fixed by keeping the one-argument call
when no nested layout applies. `ruff check` passes; `ruff format --check` flags only
docs/project/CAPABILITY_MATRIX.md, which this change does not touch.

## 2026-11-25 — download saves a PDF that Firefox's viewer shows

Follows the field report in PR #222 ("PDFs that Firefox displays can't be
downloaded", suggestion 5); the maintainer decided on 2026-11-25 to save the
original bytes. `download` refused a PDF that opened in pdf.js, and an agent then
spent about 20 calls paging through the viewer.

- Approach: copy the bytes pdf.js already holds. In Firefox's viewer
  (`document.contentType` is `application/pdf` and `PDFViewerApplication` exists),
  `PDFViewerApplication.pdfDocument.getData()` returns the file the viewer was given,
  not a re-rendering. The `Uint8Array` is kept as a BiDi handle (`resultOwnership:
  root`) and read in 6 MiB slices as base64 (8 MiB per message, under the 16 MiB
  socket limit), then released with `script.disown`. Rejected: `fetch(location.href,
  {credentials: "include"})` in the viewer fails (`NetworkError`; the viewer's origin
  is `resource://pdf.js`), and it would request the file again, which a form post or
  a blob cannot repeat. Setting `pdfjs.disabled` in the session profile would change
  how every PDF displays and cannot be toggled per call over BiDi.
- Behavior: `download` with a `url` that opens the viewer (detected as soon as a new
  document realm shows it, without the 5 s page wait) saves the PDF and returns the
  usual receipt plus `content_type: "application/pdf"` and `from_viewer: true`.
  `download` without `url` saves the PDF the tab shows (form posts, `blob:` URLs) and
  refuses on a tab without one. The file is written 0600 to a temporary name beside
  the destination and renamed; in `~/Downloads` it takes the server's
  Content-Disposition name (else the URL's last segment, else `document.pdf`) and
  gains `(1)`, `(2)` instead of replacing a file; `to_file`/`overwrite` follow the
  existing rules. Limit 256 MiB (`PDF_BYTES`). The tab is left showing the PDF. The
  remaining "opened a page instead" refusal now points to `send source="cookies"`
  with curl. Not covered: a PDF in a frame of an HTML page, or a site's own pdf.js
  (an HTML page); download their own URL.
- Text: `desktop_browser` description, CLI `--url` help, `docs/USAGE.md`
  ("Downloading files").
- Tests (`tests/test_download.py`): a fixture PDF (every byte value in a stream and
  bytes after `%%EOF`) served inline behind a cookie; real Firefox: refused without
  the cookie and on a non-PDF tab, saved from `download url=...` with sha256 equal to
  the fixture's, mode 0600, the signed query not echoed, `(1)` naming, `to_file` and
  `overwrite`; a form POST and a `blob:` URL saved without `url`; a 13 MiB PDF in
  three chunks. Unit: no-url refusal with a fake bridge, `pdf_name`.
- Validation: `uv run ruff check src tests` and `uv run ruff format --check src tests`
  pass. Locally (no labwc on `PATH`) `uv run python -m unittest discover -s tests -p
  'test*.py'` OK (skipped=178). Under `nix shell nixpkgs#labwc nixpkgs#foot
  nixpkgs#grim nixpkgs#wtype nixpkgs#wlrctl nixpkgs#dbus nixpkgs#at-spi2-core
  --command uv run python -m unittest discover -s tests -p test_download.py -k
  RealFirefox` the four real-Firefox tests pass (about 22 s). On the worker (commit 83f21a6, shared with two other suites), `on-worker run -n pdf -- nix shell nixpkgs#labwc nixpkgs#foot nixpkgs#grim nixpkgs#wtype nixpkgs#wlrctl nixpkgs#wayvnc nixpkgs#tigervnc nixpkgs#dbus nixpkgs#firefox nixpkgs#at-spi2-core --command uv run python -m unittest discover -s tests -p 'test*.py'`: Ran 474 tests in 655 s, OK (skipped=35, expected failures=1).
- Review fix (before merge): the viewer file name was cut at 200 characters,
  not bytes, so a server name of 120 CJK characters (360 bytes in UTF-8) made
  the hidden `.part` file fail with "File name too long" and nothing was saved.
  `pdf_name` now keeps at most 200 bytes with the suffix, cut at a character
  boundary. New `test_a_long_name_fits_with_its_part_file` failed before.
  Local: `test_download.py` 13 OK (real Firefox included); ruff passes.

## 2026-11-25 — A login handoff keeps session-only cookies for 24 hours

Follows the field report in PR #222
(`docs/trials/2026-11-25-exchange-research-and-lecture-fetch.md`): on 11-23 the
person signed in twice with `take --paste`, and both logins were gone after
release. The plain Firefox of the person's turn (N7) is quit and restarted under
BiDi, which does not restore the session store, so session-only cookies were
lost. The maintainer decided on 2026-11-25 to keep them for 24 h.

- `cookies.keep_session_cookies` reuses `read_session_cookies` (now `sites=None`
  for all hosts and `since` to skip stores written before the login's Firefox
  started) and `session_row`. It writes the cookies into the same profile's
  `cookies.sqlite` with a 24-hour expiry, in seconds or milliseconds as the
  database uses. Private-browsing cookies are skipped. Problems are returned,
  never raised, and values are never included.
- `restore_bridge` calls it between the quit and the BiDi restart, on the
  session's own `$HOME/.mozilla/agent-desktop` only. `stop_firefox` returns
  whether Firefox exited with status 0, and `open_login_browser` records
  `started`. `last.browser` gains `kept_session_cookies`, plus
  `session_cookies_expire` and `session_cookies_from` when cookies were kept.
  `session_cookies_note` covers an unclean quit, Firefox still running, no fresh
  store, Firefox not pinned, or an unreadable file. The release never fails
  because of these.
- Where the cookies were: a temporary probe (not committed) in a real session
  showed that after the window-close quit the session-only cookie was only in
  `sessionstore.jsonlz4` (1 cookie, written about 3 s after the plain Firefox
  started). `sessionstore-backups/recovery.jsonlz4` had been removed,
  `previous.jsonlz4` (the bridged Firefox's earlier store) held 0 cookies, and
  `cookies.sqlite` held no session rows. After a kill, a fresh
  `recovery.jsonlz4` is used instead.
- Validation: `uv run ruff check .` passes. `uv run ruff format --check src
  tests` passes; `ruff format --check .` also flags the existing
  `docs/project/CAPABILITY_MATRIX.md` snippet, which this change does not touch.
  Locally, `uv run python -m unittest discover -s tests -p
  'test_keep_session_cookies.py'` ran 6 tests, OK. `-p test_profiles.py` ran 26,
  OK (skipped=11). `-p test_events.py` ran 8, OK (skipped=1). `nix shell ...
  --command uv run python -m unittest discover -s tests -p
  'test_login_handoff.py'` ran 1 test, OK in 5.5 s (a real private session: the
  reply had `kept_session_cookies: 1` from `sessionstore.jsonlz4`, the bridged
  page saw `session_login=yes`, and the row expired about 24 h after release).
  Full desktop suite on the worker at b82f052: `on-worker run -n handoff -- nix
  shell nixpkgs#labwc nixpkgs#foot nixpkgs#grim nixpkgs#wtype nixpkgs#wlrctl
  nixpkgs#wayvnc nixpkgs#tigervnc nixpkgs#dbus nixpkgs#firefox
  nixpkgs#at-spi2-core --command uv run python -m unittest discover -s tests -p
  'test*.py'` ran 475 tests in 622 s, OK (skipped=35, expected failures=1),
  exit status 0. It shared the VM with another job (`f3-scope`).
- Limits: the cookies last 24 h and the site may end the login sooner, so
  "Remember me" is still the durable route. After an unclean quit only the last
  periodic save (every 15 s by default) is available. The `control_returned`
  event does not carry the count.

## 2026-11-25 — F3: opt-in systemd scope for children that clear their environment

The 2026-10-08 review decision accepted, as a limit, that a child started with `setsid env -i` survives recovery after both supervisors die. It named a cgroup as the only fix, and declined to require one for a distribution-neutral install. I looked at the alternatives again:

- pidfds and process groups need a live holder, or can be left with `setsid`.
- Inherited process attributes (timer slack, `no_new_privs`) are not unique, and could lead to killing an unrelated process.
- A cgroup is kernel-tracked and an unprivileged process cannot leave its delegated subtree except into another unit. On this laptop and the worker VM, `systemd-run --user --scope` provides one cheaply.

Decision (conservative; the maintainer decides the default):

- **Opt-in.** With `AGENT_DESKTOP_SYSTEMD_SCOPE=1`, `create` runs the supervisors under `systemd-run --user --scope --quiet --collect --unit=agent-desktop-SESSION.scope`. The supervisor records its cgroup in the manifest (`record_scope`).
- `cleanup_processes` and `recover` add the scope's `cgroup.procs` to the token carriers. Each process is still signalled only if its PID and start time match.
- `recover` refuses a cgroup that is not the session's own scope.
- Default unchanged. If the variable is set and `systemd-run` or a user manager is missing, `create` fails; there is no fallback.

Not on by default because that would move every session under `user@UID.service/app.slice`. The session would then outlive an ssh login scope, and systemd-oomd could treat it as one unit.

Tests:

- `SystemdScopeTests` (skipped without a user manager): an env-cleared daemon is stopped by `destroy` recovery, and also by the next `create` on the profile. A normal `destroy` empties the scope and systemd removes it.
- `ScopeRecordTests`: a tampered cgroup (`/`, `/user.slice`, a path with `..`, a non-string) is refused and the home is left alone; a scope that is already gone is handled.
- The expected-failure test keeps documenting the default. `LifecycleCase` now sets `AGENT_DESKTOP_SYSTEMD_SCOPE=0` unless a class asks for a scope.
- `systemd-run` finds the manager through `XDG_RUNTIME_DIR`, so the tests link their private runtime's `systemd` entry to the real one. Without that link, `create` failed with "Failed to connect to user scope bus via local transport".
- One test race was found and fixed. After SIGKILL, a supervisor's `/proc/PID/environ` empties before its files close, so the profile lock can still be held for an instant after `supervisor_alive` turns false. The profile test now waits for the lock. A real abandoned profile is unaffected.

Validation:

- `uv run ruff check src tests` and `uv run ruff format --check src tests` pass.
- Laptop: `-k Scope -k SupervisorLoss` ran 9 tests, OK (skipped=1, expected failures=1), three runs in a row. No `agent-desktop-*` units or test `sleep` processes were left (`systemctl --user list-units --all 'agent-desktop-*'`).
- Worker, one job: `on-worker run -n f3-scope -- nix shell nixpkgs#labwc nixpkgs#foot nixpkgs#grim nixpkgs#wtype nixpkgs#wlrctl nixpkgs#wayvnc nixpkgs#tigervnc nixpkgs#dbus nixpkgs#firefox nixpkgs#at-spi2-core --command sh -c '... uv run python -m unittest discover -s tests -p "test*.py"; ... uv run python scripts/lifecycle_stress.py --cycles 20 --load 4'`.
  - `systemd-run --user --scope` worked there.
  - Suite: 481 tests in 640 s, OK (skipped=35, expected failures=1). The skip count matches the earlier run, so the scope tests ran. It shared the VM with another contributor's job.
  - Stress: 20/20 cycles passed, 10 with a profile, 20 pruned, cycle median 1.66 s (max 1.77 s), 12 descriptors at the first and last cycle, `ok: true`.
- Checks matrix, triggered once on this branch (`gh workflow run checks.yml --ref f3-scope`, run 45558503727, commit 53d76f8). Ubuntu `runtime`, `runtime (fedora)` and `runtime (arch)` passed. `nix` failed: 481 tests, errors=1, skipped=19, expected failures=1. The one error is the upgrade test's missing D-Bus configuration, a test-only bug fixed in the previous entry's PR. `SystemdScopeTests` passed on the Ubuntu and Nix runners, which have a user manager, and skipped in the Fedora and Arch containers. The matrix was not re-run.

## 2026-11-25 — F3: runtime upgrade and reboot rows

X3 continues from the first stage (#216). These rows of [LIFETIMES.md](LIFETIMES.md) were untested: a runtime upgrade under a running session, and a machine reboot or logout. Both are now tested in `tests/test_lifecycle.py`. Neither the machine nor the real runtime directory is touched.

- `UpgradeTests`:
  - A session's worker is started from a copy of the package, which is then deleted, standing in for an installation that an upgrade removes. Then `status`, `screenshot`, a browser request, `list` and `destroy` are checked, and a new session on the profile reads the old file.
  - The session's `labwc`, `grim` and `dbus-daemon` are wrappers in a directory, which is then deleted, standing in for a garbage-collected store path. A screenshot then fails, saying the runtime changed; `status` and `destroy` still work. A new session records the new tools and keeps the profile.
- `OlderRecordTests`: manifests with only the 2026-10-05 keys (stopped, failed, and `ready` with dead supervisors) are listed, counted, recovered and pruned. A profile whose last session is such a record shows as `abandoned` and is recovered. An operation record with `schema_version` 2 fails closed.
- `RebootTests`: two sessions, one with a profile, the profile session running a job. The test then:
  - kills every token process at once;
  - removes `RUNTIME` and moves `XDG_RUNTIME_DIR` to a new path;
  - points recorded supervisor PIDs at live unrelated processes, and gives the job record an unrelated PID with its real start time and another boot id.

  Checked: `list` shows `unavailable`, the profile is unlocked and `abandoned`, the job settles as `delivery_unknown` with its step `uncertain`, and `prune` removes nothing. The next `create` on the profile recovers the old session and keeps its file, `destroy` recovers the other one, the record is kept, `prune` then removes everything, and the unrelated process keeps running.

Bugs found and fixed:

1. **A job record across a reboot.** `process_alive` trusted PID plus start time, but start times count from boot. A new process with the same pair after a reboot kept a dead job `running` forever. Records now carry `boot_id`, and a different boot id means the process is not alive. Older records without the field are judged as before (`BootIdentityTests`).
2. **Recovery refused after the runtime directory moved.** `recover` refused a recorded runtime outside the current `XDG_RUNTIME_DIR`, even when that runtime was already gone, for example a session created under the `/tmp` fallback and recovered from a login shell after a reboot. Both `destroy` and `create` on the profile were then stuck. The check now applies only when the directory exists.
3. **Mixed versions in a running worker.** The worker imported `browser`, `atlas`, `core` and `websockets` on first use. After the installation was removed, a browser request replied `ImportError: cannot import name 'browser'`. After an in-place upgrade it would have loaded the new version's module into the old worker. `load_request_modules()` now imports them at worker start, which costs about 80 ms (measured with `-X importtime`).
4. A tool removed under a running session now raises "the desktop runtime changed ... Destroy the session and create a new one" instead of `FileNotFoundError`.

Without fixes 1 and 2, `RebootTests` fails: the job never settles ("Timed out waiting"), and recovery reports "Refusing to remove an unexpected runtime directory".

Validation:

- `uv run ruff check src tests` and `uv run ruff format --check src tests` pass.
- Laptop, with `nix shell nixpkgs#labwc nixpkgs#foot nixpkgs#grim nixpkgs#wtype nixpkgs#wlrctl nixpkgs#wayvnc nixpkgs#tigervnc nixpkgs#dbus nixpkgs#firefox nixpkgs#at-spi2-core --command uv run python -m unittest discover -s tests -p test_lifecycle.py`: 17 tests OK (expected failures=1) in 47.5 s.
- Worker, `on-worker run -n f3 -- nix shell ... --command uv run python -m unittest discover -s tests -p 'test*.py'`: 476 tests in 650 s, FAILED (failures=1, skipped=35, expected failures=1). The failure is `test_interruptions.InterruptionTests.test_during_application_work` (`'stopped' != 'delivery_unknown'`), which is flaky on `main` as well. On the laptop it failed 2 of 6 runs on `origin/main` and 1 of 4 on this branch. The kill sometimes lands between the two steps, which correctly reads `stopped`. This change does not touch it; it is left open.

The Checks matrix, run once on the stacked branch (run 45558503727), found a test bug: on the Nix job, `test_desktop_runtime_replaced_under_a_running_session` failed with `Failed to open "/etc/dbus-1/session.conf"`. Its wrapper runtime had no `share/dbus-1` beside the daemon, and Nix's dbus-daemon has no `/etc` default to fall back on. The wrapper prefix now links the real `share/dbus-1`, as a runtime prefix ships it. This passed on the laptop; CI was not run again.

Remaining for X3: other distributions (the Checks matrix), a real reboot or logout, and env-cleared children after both supervisors die. An opt-in systemd scope for the last one is in a stacked PR.

## 2026-11-25 — Agent-driven F2 document edit and mixed workflow (X2)

`--suite f2` gains two tasks. Both use the deterministic drivers' fixtures and
evaluators, and LibreOffice starts with its first-run dialogs answered, as in the
drivers (`benchmarks/office.py` `command(..., first_run_done=True)`; the office
suite is unchanged).

- `f2-document-edit` (`benchmarks/f2_document.py`): the agreement is open in
  Writer. The agent changes the payment term, saves to the same file in its
  format and closes LibreOffice. The format (`.odt` or `.docx`) and clause order
  follow `--seed`. The check is the document evaluator on the file and its
  folder, so a lock file left by an open document fails it.
- `f2-mixed-upload` (`benchmarks/f2_mixed.py`): Writer is open with no
  document, and the browser shows the contract portal. The agent downloads the
  current agreement, edits it and uploads it once. The format and the injected
  failure (`refused` or `lost reply`) follow `--seed`. The check waits 7 s, then
  runs the portal evaluator on what the portal stored. The prompt does not
  mention the failure.

`AgentTaskTests` in both test files check setup and the judge without a model:
no edit fails, the right outcome passes, and a lock file, a refused upload or a
duplicate fails.

Dry runs (negative control, no account use) for both tasks with seeds 1, 2, 4 and
7, all with `--firefox` (some also with `--bridge`): every check failed (the payment clause
unchanged with a lock file, or nothing uploaded), and there were no errors or
cleanup failures.

```sh
nix shell nixpkgs#labwc nixpkgs#foot nixpkgs#grim nixpkgs#wtype nixpkgs#wlrctl \
  nixpkgs#dbus nixpkgs#at-spi2-core nixpkgs#libreoffice --command \
  uv run scripts/benchmark.py --suite f2 --only f2-document-edit --seed 1
# likewise --seed 4; and for the mixed workflow:
#   --only f2-mixed-upload --firefox --bridge --budget 2 --seed 2   (and --seed 7)
```

The agreed budget was at most two model runs per new task. The model was the
CLI default, as in the 2026-11-12 dataset runs (`claude-opus-5-5`, Claude Code
2.1.332). Costs are API-equivalent, billed to the maintainer's subscription. The
per-task cap was the default $1 for the document edit and $2 for the mixed
workflow. All four runs passed:

| Task | Seed | Trial | Passed | Turns | Tool calls | Wall s | Cost USD |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| f2-document-edit | 1 | 948735, `.odt` | yes | 6 | 5 | 24.1 | 0.20 |
| f2-document-edit | 4 | 859847, `.docx` | yes | 9 | 8 | 27.0 | 0.14 |
| f2-mixed-upload | 2 | 376639, `.odt`, lost reply | yes | 17 | 16 | 61.4 | 0.36 |
| f2-mixed-upload | 7 | 507885, `.docx`, refused | yes | 17 | 16 | 68.9 | 0.28 |

Total $0.98. There were no tool errors and no leftover processes. In the
lost-reply run, the page said "No reply". The agent read Received, found the file
there once and did not upload again, and the portal saw one attempt. In the
refused run, the agent uploaded again after the 503, and the portal stored
`[False, True]`. The document-edit agents worked through `desktop_actions` and
screenshots. Neither agent reopened the file (the first said so), so the reopen
step rests on the evaluator, which parses the file. The mixed agents used
`desktop_browser` for the portal and its download, and `desktop_actions` (keys
and clicks) for Writer and the file chooser. Chromium was not tried for the
mixed task. Two runs per task show the capabilities are
sufficient on these seeds. They are not a reliability estimate.

## 2026-11-25 — F2 mixed workflow, deterministic driver (X2)

The third F2 workflow: download a file, process it in an application, upload the
result. `benchmarks/f2_mixed.py` runs a loopback contract portal. It lists the
current agreement and a superseded one (the same clauses in another order), serves
each as an attachment, takes uploads through a file input and lists what it
stored under "Received". The documents and the expected edit are the native
document edit's (`benchmarks/f2_document.py`). Two injections:

- `refused`: the first upload gets a 503 and nothing is stored. The page says so.
- `lost reply`: the first upload is stored, but the portal answers after 6 s and
  the page stops waiting after 3 s. The page cannot tell whether the upload
  arrived and says to check Received before uploading again.

The evaluator reads only what the portal stored. It requires exactly one stored
upload (a second one is reported as a duplicate submission), in the downloaded
file's format, and runs the document evaluator on a copy of exactly the bytes
received, so every paragraph is compared with the expected text. Its own tests
check known-wrong outcomes: nothing uploaded, a duplicate, the unedited file,
the superseded agreement edited correctly, every "30 days" changed, a truncated
upload, an empty upload and the other format. A refused attempt does not count;
a stored attempt with a lost reply does. The page holds neither the new term nor
the expected paragraphs.

`tests/test_mixed_workflow.py` drives a real private session with Firefox and
LibreOffice Writer. It finds the current agreement's link on the page, downloads
it with the bridge's `download`, opens it in Writer and makes the same edit as
the document driver (Find, type, Ctrl+S, the Word button for `.docx`, Ctrl+Q). It
then uploads the saved file through Firefox's own file chooser. A bridge click on
the file input opens "File Upload" (`xdg-desktop-portal-gtk`, parented to the
Firefox window). The driver focuses it, presses Ctrl+L, types the path and
presses Return, and waits until the input holds the file. Before every attempt
it reads Received and submits only if the file (name and size) is not there.
Two trials:

- `.odt` with `refused`: the first attempt fails, the driver retries, and the
  portal records attempts stored `[False, True]`.
- `.docx` with `lost reply`: the page reports no reply, Received shows the
  file, and the driver does not resubmit. The portal saw one attempt.

Both wait 7 s after the driver finishes, so a late upload would be counted.
Clipboard and poor-accessibility interfaces are still not covered end to end,
and nothing kills Firefox or LibreOffice mid-workflow here (the document trial
already kills LibreOffice before a save).

Validation on NixOS (labwc 0.20.2, LibreOffice 26.8.3.1 and the runtime tools
from nixpkgs through `nix shell`, Firefox 160.0.1):

```sh
nix shell nixpkgs#labwc nixpkgs#foot nixpkgs#grim nixpkgs#wtype nixpkgs#wlrctl \
  nixpkgs#dbus nixpkgs#at-spi2-core nixpkgs#libreoffice \
  --command uv run python -m unittest discover -s tests -p test_mixed_workflow.py
```

It ran 6 tests (4 evaluator, 2 desktop trials) and passed 4 times in a row, in 57–59 s
each. `test_document_workflow` (6 tests) also passed here for the first time, in
51 s; before, it had only run on the Fedora VM and in CI. `uv run ruff check` and
`uv run ruff format --check` pass.

Full desktop suite on the worker (`gcp-worker`, 14 vCPUs shared with another job;
the packages above plus wayvnc, tigervnc and firefox from nixpkgs), at `115e21e`:

```sh
on-worker run -n f2 -- nix shell nixpkgs#labwc nixpkgs#foot nixpkgs#grim nixpkgs#wtype \
  nixpkgs#wlrctl nixpkgs#wayvnc nixpkgs#tigervnc nixpkgs#dbus nixpkgs#firefox \
  nixpkgs#at-spi2-core nixpkgs#libreoffice \
  --command uv run python -m unittest discover -s tests -p 'test*.py'
```

It ran 475 tests in 786 s: OK (skipped=28, expected failures=1). A verbose run of
`-p 'test_*_workflow.py'` there (job `f2-wf`) ran all 19 dataset, document and
mixed tests in 151 s with none skipped, so the 28 skips are outside the F2
workflows.

## 2026-11-25 — bot-check pages are flagged; text waits match the title

Follows the [exchange research and lecture fetch field report](../trials/2026-11-25-exchange-research-and-lecture-fetch.md):
a bot-check interstitial (title "Just a moment...", body "Performing security
verification") stopped agents in 5 sessions on 4 days and none handed off. A
`wait` for "Just a moment" with `gone: true` was satisfied falsely: the text is
only in the title, and `find` matches elements, never the title. Stacks on #226
(it changes the same open and wait replies).

Change:

- `browser.challenge_reason` (pure, unit-tested) flags a page when its title
  starts with "Just a moment", or it has `#challenge-form`, `#challenge-running`,
  `#challenge-stage` or `#cf-challenge-running`, or its whole visible text is at
  most 800 characters and holds "Performing security verification", "Checking
  your browser before", "Verify you are human" or "Verifying you are human".
  Conservative on purpose: a Turnstile iframe alone is not a marker (login
  forms carry it), and a long page that says "just a moment" is not flagged.
- `open`, `text`, `find` and `wait` add `challenge: true` and `challenge_hint`
  (wait a few seconds; else `desktop_request_human`, or the person's Firefox via
  `desktop_request_host`; never solve or bypass). Detection is best effort: a
  page that is navigating reports nothing.
- A text `wait` (no selector) also matches the document title and reports
  `title_matches: true`; with `gone` it is unmet while the title holds the text.
- One sentence in the `desktop_browser` docstring; note in docs/USAGE.md.

Validation:

- `tests/test_browser_settle.py`: detector unit tests (markers, and ordinary
  pages not flagged); real Firefox: a fixture titled "Just a moment..." that
  navigates to "Welcome" after 4 s is flagged by open, text and find; a text
  wait sees the title, `gone` is unmet until it clears and then satisfied, and
  the cleared page is not flagged; a long ordinary page that says "just a moment"
  is not flagged. `tests/test_delivery.py`: the mock bridge returns no challenge.
- Local (labwc etc. from `nix shell`, system Firefox): `test_browser*.py`
  25 tests OK in 123.7 s. `ruff check` and `ruff format --check` pass.
- Full desktop suite on gcp-worker (`on-worker run -n botcheck`, nix shell from
  docs/VALIDATION.md, shared with another job): first run 478 tests in 686.8 s,
  FAILED (errors=1): `test_delivery` lost-ack test, whose Mock bridge returned a
  Mock from `challenge()`. Fixed in the test double. Second run: `on-worker run -n botcheck2`, 478 tests in 686.2 s, OK (skipped=35, expected failures=1).
- Review fix (before merge): a text wait with `within` also matched the title,
  which lies in no row or dialog, so `wait text=X within=Y` was met by the title
  alone and `gone` never was. The title now counts only without `within`.
  New `test_delivery` test failed before. Rebased onto the reviewed
  waits-and-hook; local `test_browser_settle.py` 12 OK, `test_browser.py` 16 OK,
  `test_delivery.py` 22 OK.

Limits: only the listed wording and ids are detected (other vendors' challenge
pages are missed); not tested against a live Cloudflare page, only fixtures.
The title match is substring, case-sensitive like `find`.

## 2026-11-25 — open waits for the page to settle; a bare wait does the same

Follows "Fixed waits" in the [VPN token and quota check field report](../trials/2026-11-20-vpn-token-and-quota-check.md)
(82% of batch waits were fixed pauses, the same as before N5). N5 only counted
them and asked for text waits in the tool description.

Why agents still paused. In the maintainer's transcripts from 11-01 to 11-25
(the usage review script, read-only), 133 fixed pauses inside browser batches
came right after `click` (62) or `open` (54), and were followed by `text` (58),
`find` (33) or `save` (13). The agent paused so it could read a page it had not
seen yet, so it had no text to wait for. And waiting was needed: `open` returned
at the `load` event, and the consoles in those reports (single-page apps) fetch
and render their content after it, so a `text` right after `open` read
"Loading". Nothing waited after a click at all.

Change:

- `Browser.settle` (browser.py) waits until the document has loaded and, for
  0.5 s, its tab has had no network event and no request open, and its DOM has
  not changed. Requests come from BiDi network events: the bridge subscribes
  once when it connects, so requests started before `load` are known, and
  `command` records them while it waits for replies (they were dropped before).
  Timestamps are the events' own. A request open longer than 5 s (a long poll)
  is ignored. The DOM is watched by a `MutationObserver` in a BiDi sandbox, so
  the page sees no globals.
- `open`, and `start` with a url, settle after navigating, up to `timeout`
  (default 10 s, 0 to skip), and return `settled` and `settle_ms`.
  `settled: false` is not an error.
- `{"action": "wait"}` with no selector, text or seconds waits until the page
  settles (up to `timeout`) and is unmet if it doesn't. Before, it was refused.
  Activity counts it as a wait for a condition.
- In `steps`, a plain `seconds` pause right after `open`, `start` or `click`
  gets a one-line `hint`. The tool description says what to do instead.

Decisions: settling is on by default for `open`, because the cost on a static
page is 0.5 s and that page loads anyway. Clicks don't settle by default, since
most don't load anything and each would cost 0.5 s. Fixed pauses still work as before.

Validation:

- New `tests/test_browser_settle.py`: a fixture "console" served over local HTTP
  shows "Loading", makes an API call the server delays 1.5 s, and renders 0.2 s
  later. `open` returns `settled` after at least 1.5 s, and `text` straight away
  reads "Quota: 42". `click` + `{"action": "wait"}` + `text` reads the next page
  with no pause. `open` with `timeout=0` skips settling. A fixed pause after a
  click carries the hint. A page that changes its DOM every 100 ms returns
  `settled: false` after the 2 s timeout, and a bare wait on it stops the batch
  as unmet. Unit tests cover the hint and the trace. The first version
  subscribed to network events only once settling began, so it missed the
  page's own fetch and settled after 655 ms. The test caught this.
- `test_browser.py`: the assertion that a bare wait is refused now expects it
  to settle.
- Local (labwc, grim, dbus and at-spi from `nix shell`, Firefox 160.0.1):
  `test_browser_settle.py` 5 tests OK. `test_browser.py` 16 OK (after the
  update above). `test_secret_text.py` 14, `test_completion_targets.py` 8,
  `test_activity.py` 6, `test_trace.py` 4, `test_download.py` 7 and
  `test_operations.py` 21 are all OK. `ruff check` and `ruff format --check`
  pass.
- Full desktop suite on gcp-worker (`on-worker run -n waits`, the nix shell from
  docs/VALIDATION.md, sharing the VM with two other jobs): 474 tests in 691.8 s,
  OK (skipped=35, expected failures=1).

Review fixes (before merge):

- A bare wait (up to 60 s) and the settle after `open` did not give way to a
  person taking control: `settle` slept with `time.sleep`, not the worker's
  `pause`. `settle` now takes `interrupt` (the worker passes `take_requested`);
  a bare wait then raises HumanControl like other waits, and `open` returns
  `interrupted: true`. New `SettleTakeTests`: without the fix the bare wait
  ran its whole 30 s timeout.
- A page whose script animates a spinner through its `style` every frame never
  settled, so each `open` cost the full 10 s. Mutations of only the `style`
  attribute no longer count; content changes, other attributes and the network
  still do. New `test_a_style_animation_does_not_hold_the_page_open` failed
  before (`settled: false` after the 5 s limit).
- Local: `test_browser_settle.py` 8 OK, `test_browser.py` 16 OK,
  `test_delivery.py` 21 OK; ruff check and format pass.

Not yet shown: whether agents stop pausing. The next usage review should
compare fixed waits after `open` and `click` with this report.

## 2026-11-25 — An unanswered host prompt explains itself

Follows "The hook result still looks like a tool error" in the
[VPN token and quota check field report](../trials/2026-11-20-vpn-token-and-quota-check.md)
and the 11-19 report. The cause is Claude Code's documented behavior, not the
server. The [hooks reference](https://code.claude.com/docs/en/hooks) says that
for `"ask"`, `permissionDecisionReason` is shown to the user in the prompt, and
that when Claude Code denies the call in a `-p` run where no one can answer, the
agent reads that reason in the tool result. The server is never called, so it
can't reply. No `PreToolUse` field makes the refusal a normal result. A
`PermissionRequest` hook could deny with its own `message`, but it can't tell an
unattended run from an interactive one, so it would refuse people too.

Change: the documented hook's reason now works for both readers: "Agent Desktop
asks to use your screen. Nothing runs on it until you approve; no answer means
no, and the agent should ask you in chat before trying again." INTEGRATIONS.md
describes both paths exactly. The `desktop_request_host` description says that
a call refused before it runs started nothing, and that the agent should ask
the user before calling again. A test runs the hook command from
INTEGRATIONS.md and checks its JSON and reason.

Validation:

- Non-interactive check with Claude Code 2.1.332 and `--model haiku`. The run
  used a temporary `--settings` file, `--setting-sources project` from an empty
  temporary folder, `--strict-mcp-config` with only this server
  (`AGENT_DESKTOP_HOST_APPROVAL=client`, `AGENT_DESKTOP_HOST_NOTIFY=0`), and a
  temporary state directory. A private labwc session stood in as the host
  display (`WAYLAND_DISPLAY`). The maintainer's settings and screen were not used.
  - Old reason, default mode: `is_error: true`, text "An agent asks to use
    your screen". The agent said it would wait for the person to answer the
    prompt, which was already gone.
  - New reason, default mode, and new reason in `bypassPermissions`: both
    `is_error: true` with the new text, and the call is listed in
    `permission_denials`. The agent said it would ask in chat and not retry.
  - The temporary state held only the stand-in session, so the server was
    never called. Cost $0.006 over 3 runs. The temporary directory and the
    stand-in were removed.
- Not checked: an interactive decline, which needs a person. The hooks
  reference says the reason is shown in the prompt there.
- `test_host_hook.py` 1 test OK. With labwc, grim, dbus and at-spi from
  `nix shell`: `test_host.py` 11 OK and `test_mcp.py` 2 OK. `ruff check` and
  `ruff format --check` pass. Docs and tool text only, plus one test, so the
  full suite was not run for this change.

## 2026-11-25 — site-cookies: list a site's cookies in a profile, never values

Follows the 2026-11-20 field report (`docs/trials/2026-11-20-vpn-token-and-quota-check.md`,
suggestion 2): an agent edited a profile's `cookies.sqlite` by hand to see which
logins it held.

- Interface: `cookies.site_cookies(profile, sites)`; `agent-desktop site-cookies
  PROFILE --site SITE`; `desktop_profiles(profile=..., cookies=SITE)`. Each cookie
  gives `host`, `name`, `path`, `expires` (UTC ISO time, or `session` when the
  stored expiry is 0) and `secure` / `http_only`; the reply also lists the
  site's `storage/default` directories (same `storage_host`/`matches` rules as
  `forget-site`). Values are never read into the reply.
- Safety: the profile lock is taken without blocking, and a profile in use is
  refused with `core.profile_busy` (names the holder session). The database
  and its `-wal` are copied to a temporary directory and read there
  (`read_cookies`), so the profile's file is never opened for writing.
- `desktop_profiles` combinations: `cookies` needs `profile` and no `note`,
  `session` or `attach`; the other combinations are unchanged. The
  `desktop_browser` cookies hint and the `desktop_profiles` description point
  here instead of leaving only `forget-site`.
- Decision: the read-only view is a copy rather than `mode=ro` on the original,
  because a read-only WAL database cannot be opened without its `-shm` file and
  the copy matches how `import-cookies` already reads the person's Firefox.
- Tests (`tests/test_profiles.py`, `CookieImportTests` and `ProfileNoteTests`):
  planted values absent from the JSON and CLI output, subdomains matched, a
  look-alike domain and other sites excluded, session cookie shown as `session`,
  seconds and milliseconds expiry, flags, storage names, file unchanged and no
  copy left, in-use refusal, missing profile, bad site, profile without a
  cookie file, MCP argument combinations.
- Validation: `uv run ruff check src scripts tests` and `uv run ruff format
  --check src scripts tests` pass. `uv run python -m unittest discover -s tests
  -p test_profiles.py`: 31 tests, OK (skipped=11). `uv run python -m unittest
  discover -s tests`: 474 tests, OK (skipped=175). This is a unit-level run on
  the laptop without labwc, grim or a Firefox session, so the desktop tests
  skipped; no real-desktop run was made. The change reads only files and takes
  no session, so a desktop run would not exercise it.

## 2026-11-25 — Small fixes from the exchange research field report

Follows suggestions 3 and 4 of the 2026-11-25 field report (#222).

- `desktop_browser` text: a relative `to_file` for `send`/`save` is in the session
  home, which in a profile session is the profile's and stays after destroy, so the
  text suggests an absolute path in the agent's own scratch folder. `download` says
  that a profile's `~/Downloads` is kept.
- The page script's `within` scope no longer reads `document.body` before the page
  has one. It finds nothing yet, so `wait` keeps polling instead of failing with
  "Page script failed: ... document.body is null".
- `scripts/usage_review.py` counts a shell command that reads a file a tool reply
  named (`to_file` or `file`, by full path or by folder and name) as
  "tool output", not as a "profile files" or "session state" flag.
- Validation: `uv run python -m unittest tests.test_usage_review` OK (3 new
  `ReturnedFileTest` tests). `discover -p test_browser.py` ran 16 tests, all skipped
  (no labwc here), so the page-script change was checked only by running `FIND`
  under node with a null `document.body`: main throws, this branch returns
  `{"count":0,"items":[]}`. A rerun of the review over 2026-11-20 to 11-25 left 2 of
  the 30 profile and session-state flags, both real leads. ruff check and format
  pass. The full desktop suite wasn't run.

## 2026-11-25 — Usage review: exchange research and lecture fetch

Ran `scripts/usage_review.py --since 2026-11-20` (243 calls, 11 transcripts, 76 flags)
and `agent-desktop activity --days 5` (16 sessions, 211 operations). 16 calls in one
transcript were already in the 11-20 report. The rest (227 calls) are a new exchange
research project (201, including three subagents), two `/lecture` caption fetches and
one flashcard-project course sync. Report:
docs/trials/2026-11-25-exchange-research-and-lecture-fetch.md.

Main findings: all three login handoffs failed. Twice the person signed in with
`take --paste` and the login was gone after release, probably because `restore_bridge`
restarts Firefox and session-only cookies don't survive the restart. `import-cookies`
with session-only cookies (#220) recovered both times. A bot-check page stopped agents
in five sessions, and a `gone` wait on its title text was satisfied falsely. Relative
`save`/`download` paths land in the persistent profile home (30 of the flags).
`download` can't save a PDF that Firefox displays. A `wait` with `within` failed on a
page with no body yet. Named covers (#221) and download receipts (#204) were confirmed
in use. Fixed waits dropped from 82% to 76%. No tests were run.

## 2026-11-20 — Profile notes: record which account a profile signs in as

Follows the field report in PR #217 ("The agent signed in to the wrong Google
account", suggestion 6; the maintainer approved it). An agent clicked the only
account in a Google chooser without knowing which account the profile was for.

- Interface: `profiles/NAME/note` (0600, one line, at most 200 characters,
  beside `home` so sessions cannot read it and `delete-profile` removes it).
  `agent-desktop profile-note PROFILE [TEXT]` (no TEXT or `--clear` clears);
  `desktop_profiles(profile=..., note=...)` sets it (empty note clears), and the
  listing gains `note` when set. A note combined with `session` or `attach`, or
  `profile` without `note`, is refused. Session and attach behavior is unchanged.
- The `desktop_profiles` description tells agents to check the note before
  choosing an account, and to ask the person and record the answer when several
  accounts are offered and no note says which. The `import-cookies` multi-account
  warning points at `profile-note`.
- Tests: `ProfileNoteTests` in `tests/test_profiles.py` (set, show, replace, clear,
  mode 0600, single line, length limit, unknown profile, delete removes the note,
  MCP tool validation) on a temporary `AGENT_DESKTOP_STATE_DIR`.
- Validation: `uv run python -m unittest discover -s tests -p test_profiles.py` ran 21 tests, OK (skipped=10: the desktop-session `ProfileTests` need labwc/grim/dbus-daemon, absent here; the 5 new `ProfileNoteTests` run). `-p test_release_profiles.py` 3 tests OK; `-p test_mcp.py` 2 skipped (no desktop tools). `uv run ruff check src tests` and `uv run ruff format --check src tests` pass. CLI smoke on a temporary `AGENT_DESKTOP_STATE_DIR`: set, list, `--clear`, TEXT with `--clear` refused, 201 characters refused. The full suite was not run on this machine; the session-based profile tests are unchanged and were not exercised, so a real-desktop run of `test_profiles.py` is still open.

## 2026-11-20 — import-cookies copies session-only cookies

Follows the [VPN token and quota check field report](../trials/2026-11-20-vpn-token-and-quota-check.md)
(#217), "Session-only logins can't be imported" and suggestion 5, which the
maintainer approved. The person's Firefox was signed in to a console with only
a session cookie, `import-cookies` reported success, and the private browser
was still signed out.

`import-cookies` now also reads Firefox's session store,
`sessionstore-backups/recovery.jsonlz4` (written while Firefox runs) or
`sessionstore.jsonlz4` (after a clean shutdown). It uses the newer file and
falls back to the other one. Each file is copied to the same private temporary
directory as `cookies.sqlite` and decoded there. Cookies whose host is a named
site or a subdomain, using the same matching as before, are written into the
profile's `cookies.sqlite`, and a session cookie replaces a persistent row with
the same name, host, path and origin attributes. Private-browsing cookies are
skipped. Container and partition attributes are turned into Firefox's
`originAttributes` text. The reply now gives `persistent_cookies`,
`session_cookies` and `session_cookies_expire`, and `cookies` stays the total.
`detail` names the store it used and any file it skipped and why (not mozLz4,
truncated, decoded size too large, not JSON), never what the file contained. If
no store can be read, the persistent cookies are still copied. The
multi-account warning is unchanged.

Decisions:

- **Pure-Python LZ4 block decoder, no dependency.** The decoder (`lz4_block`)
  is about 50 lines. The `lz4` package is a C extension, so every platform
  needs a wheel, and on NixOS that is the kind of native-wheel loading problem
  the project instructions ask us to avoid. Only decoding is needed, and only
  once per import. On a synthetic 9.6 MB store with mostly random data it took
  0.58 s on the laptop. A decoded size over 256 MB is treated as corrupt.
- **24-hour expiry.** Firefox reads only persistent rows from `cookies.sqlite`,
  so each session cookie is given an expiry 24 hours after the import. That is
  long enough for a task and survives the private Firefox restarting. It is
  short enough that a login the person did not ask to remember does not stay
  in the profile for weeks. The import cannot use the session's lifetime,
  because it runs before the session exists.
- **Expiry units.** Firefox 160 (cookie schema 17) stores `expiry` in
  milliseconds. This was seen in a headless Firefox 160 run with a temporary
  profile and a local page, `expiry` 1795204456379 for `Max-Age=3600`. The
  unit is taken from the source database's stored values (any value over 10^11
  is milliseconds). With no rows it is taken from `user_version >= 17`.

Validation (worktree `import-session-cookies`):

- A headless Firefox 160 with a temporary profile, not the person's profile,
  loaded a local page that set a session-only and a persistent cookie. Its
  `recovery.jsonlz4` decoded to the declared size and listed the session
  cookie. `AGENT_DESKTOP_STATE_DIR=<temporary> uv run agent-desktop
  import-cookies exp --site 127.0.0.1 --from <that profile>` reported
  `persistent_cookies: 1, session_cookies: 1`. A second headless Firefox on the
  imported profile then sent both cookies to the local server.
- `uv run ruff check src scripts tests` and `uv run ruff format --check src scripts tests`: clean.
- Laptop: `nix shell nixpkgs#labwc nixpkgs#foot nixpkgs#grim nixpkgs#wtype nixpkgs#wlrctl nixpkgs#wayvnc nixpkgs#tigervnc nixpkgs#dbus nixpkgs#firefox nixpkgs#at-spi2-core --command uv run python -m unittest discover -s tests -p 'test_profiles.py' -v`:
  21 tests OK in 36.8 s. The new tests are:
  - `test_lz4_block_decoder`: round trips through a small LZ4 compressor in
    the test, a block assembled by hand, and corrupt blocks.
  - `test_session_cookies_are_imported`: through the CLI. Only the matching
    session cookies are copied (a container cookie is kept, and a
    private-browsing cookie, another host and a malformed entry are not). No
    value appears in stdout or stderr, and the expiry is 24 hours.
  - `test_millisecond_expiry_and_origin_attributes`.
  - `test_newest_session_store_and_corrupt_ones`.
  - `test_imported_session_cookie_is_sent`: a real Firefox in a private
    session gets a session cookie, the store is imported, and a second session
    on the profile sends it.
- `uv run python -m unittest discover -s tests`: 449 tests OK (174 skipped,
  desktop tests without the runtime on PATH).

Remaining: the session store is saved every 15 seconds by default, so a login
made just before the import may be missing. Origin-attribute encoding is checked
against Firefox's format for containers and partition keys in unit tests only,
not with a real partitioned cookie. The expiry is fixed at 24 hours. There is no
option to change it or to skip session cookies.

## 2026-11-20 — Secret-looking text hidden in browser replies; named covers; key hint

Follows suggestions 1 to 4 of the
[VPN token and quota check field report](../trials/2026-11-20-vpn-token-and-quota-check.md)
(#217). In that use, a `find` over a token dialog returned a freshly generated
API token in an item's `text` before the agent moved it with `send`.

- **Hidden text** (`src/agent_desktop/secret_text.py`). `Browser.find` passes
  every item's `text`, `label`, `value` and `options` through `hide()`, so
  `find`, `wait`, the `element` of click/fill/select, the matches listed for an
  ambiguous target and `steps` results all carry it. The page script now returns
  up to 400 characters per field; hiding runs first and the 120/200-character
  cut after it, so a cut never leaves an unrecognised part of a token, and never
  splits a marker. The `now` value after click/fill/select is hidden too. A run
  of token characters (`[A-Za-z0-9+/=_.~-]`) is replaced in place by
  `<hidden: looks like a secret, N chars; use send>` and the field is listed in
  `hidden`. Rules: a known prefix (Tailscale, GitHub, GitLab, OpenAI/Anthropic
  `sk-`, Stripe, Slack, AWS key ids, Google API key/OAuth tokens, npm, PyPI,
  Hugging Face, DigitalOcean, SendGrid, JWT), a `PRIVATE KEY` block, or a part
  between `-_.~` of 20+ characters with 3+ letter/digit switches and 3.5+ bits
  per character of Shannon entropy.
- **Threshold decision.** Measured on 2000 random strings each: base62 misses
  17% at 20 chars, 10% at 24, 3% at 32, 0.6% at 40; base36 5%, 0.8%, 0.1%, 0%.
  A sample of names (camel case, CSS classes, Debian package names, cloud
  resource paths, dates, version strings, long words) stays visible. Pure hex,
  UUIDs and absolute paths are shown on purpose: commit ids, checksums, request
  ids and `/nix/store` hashes are far more common on pages than hex or UUID
  secrets, and hiding them would break reading checksums. IPFS-style random
  content ids are hidden. `text` and `save` are left unchanged: they read pages
  and are documented as never for secrets; the tool text now says to give `send`
  the selector directly instead of finding the element first.
- **Named covers.** `uncovered()` returns a JSON description: the dialog
  (`dialog`, `role=dialog/alertdialog`, `aria-modal`) holding the hit element, or
  the hit element, with tag, id or two classes, role, label and the first 40
  characters of its text (hidden first); for a backdrop, also another open
  dialog on the page. Real Firefox: `covered: the element is under div.backdrop;
  a dialog is open: div[role=dialog] ("Security check") "Turn on two-step
  verification? Your key …"`.
- **Key attempts.** Unknown browser actions are refused before any bridge is
  attached; `key`, `keys`, `press`, `keypress`, `hotkey`, `shortcut` and `type`
  add that keys go through `desktop_key`, text through `fill` or `desktop_type`.
  An unknown action in `steps` is now refused before any step runs.
- **`forget-site` named.** The `desktop_browser` cookies hint says never to
  copy or edit a profile's cookie files and names
  `agent-desktop forget-site PROFILE --site SITE`. Tool descriptions now get the
  same printed CLI prefix as the server instructions.
- Skipped: a read-only cookie listing in `desktop_profiles` (suggestion 2's
  optional part). Other work is changing `desktop_profiles` and `cookies.py`, so
  it is left for a separate change.

Validation (worktree `browser-secret-hints`):

- `uv run ruff check src scripts tests`, `uv run ruff format --check src scripts tests`: clean.
- `uv run python -m unittest discover -s tests` (laptop, desktop tools not on PATH): 459 tests OK, 174 skipped.
- `uv run python -m unittest discover -s tests -p test_secret_text.py`: 14 tests OK.
- Laptop, real Firefox: `nix shell nixpkgs#labwc nixpkgs#foot nixpkgs#grim nixpkgs#dbus nixpkgs#firefox --command uv run python -m unittest discover -s tests -p test_browser.py -v`:
  16 tests OK in 83 s, including `test_find_and_wait_hide_a_generated_token`.
- gcp-worker, full suite: not run. `on-worker run -n browser-secret-hints -- nix shell <packages> --command uv run python -m unittest discover -s tests -p 'test*.py'`
  could not start the VM (`Quota 'CPUS_ALL_REGIONS' exceeded. Limit: 16.0`, another
  VM held the CPUs). Instead, on the laptop, the browser-facing desktop files one at a
  time with `nix shell nixpkgs#labwc nixpkgs#foot nixpkgs#grim nixpkgs#wtype nixpkgs#wlrctl nixpkgs#wayvnc nixpkgs#tigervnc nixpkgs#dbus nixpkgs#firefox nixpkgs#at-spi2-core --command uv run python -m unittest discover -s tests -p test_NAME.py`:
  dataset_workflow 7, web_fixtures 4, completion_targets 8, delivery 21,
  send_cookies 5, save 3, download 7, interruptions 11, login_handoff 1,
  takeover_jobs 2, all OK with none skipped. The full desktop suite remains to be run.

Limits: this is a heuristic. A secret that is short, hex-only, UUID-shaped or
split by separators into short parts is shown. URLs with a random query value
lose that value to the marker. `send` remains the route for any value shown once.

## 2026-11-20 — hyprctl for a nested Hyprland with a short runtime (N8 follow-up)

The 2026-11-11 shim only passed `hyprctl` through when `XDG_RUNTIME_DIR` was the
session's own runtime directory. A real Hyprland cannot live there: with a 12-character
session id and a 62-character instance signature, `<runtime>/hypr/<sig>/.socket2.sock`
is about 123 bytes, past the Unix socket limit, so harnesses such as the nix repo's
`tests/quiet-shell/nested.sh` use a short `/run/user/<uid>/q.XXXX` and were refused.
The shim now accepts any `XDG_RUNTIME_DIR` whose `hypr` directory, with symlinks
resolved, is not the host's and holds the named instance's socket. Signatures with `/`
are refused, since they could walk back into the host's directory. The guard test adds
a short runtime (allowed), the host runtime with and without a signature, a runtime
whose `hypr` links to the host's, and a `../` signature (all refused); it fails on the
old shim.

Review found two more ways out. `hyprctl --instance`/`-i` joins its value to the socket
path unchecked, so `-i ../…/hypr/<host sig>` reached the host while the shim only
looked at the environment (the 11-11 shim had this too). And when the server runs
without `XDG_RUNTIME_DIR`, sessions live under `/tmp/agent-desktop-<uid>`, so the shim's
idea of the host's `hypr` was wrong and `XDG_RUNTIME_DIR=/run/user/<uid>` passed. The
shim now takes the instance from `-i`/`--instance` as well as the environment, refuses
the login runtime's `hypr` too, and refuses an instance directory or socket that is a
link out of the private runtime (numeric `-i` indexes check every instance there).
The test adds `-i` and `--instance` traversals, a linked instance with and without a
signature, and an allowed `-i 0`; it fails on the first version of this change. The
`/run/user/<uid>` case is not tested, since it would aim at the real host. Validated
with `nix shell nixpkgs#labwc nixpkgs#foot nixpkgs#grim nixpkgs#dbus --command uv run
python -m unittest discover -s tests -p test_guard.py`: 10 passed.

## 2026-11-20 — Usage review: VPN token and quota check

Ran `scripts/usage_review.py --since 2026-11-18` (83 calls, 6 transcripts, 24 flags)
and `agent-desktop activity --days 3` (9 sessions, 56 operations). 28 calls were already
in the 11-19 report. The rest is one NixOS-repo use (53 calls) and two scripted hook
checks. Report: docs/trials/2026-11-20-vpn-token-and-quota-check.md.

Main findings: a `desktop_browser` `find` step returned a generated API token in its
element text before `send` moved it to a file. The agent deleted a site's rows from a
profile's `cookies.sqlite` by hand, because it didn't know about `forget-site`.
Session-only logins can't be imported. A `covered:` refusal named only `div`. The
cookies `send` source (#205) was used successfully a day after it landed. No idle
profile holds or GPU failures were seen. No tests were run.

## 2026-11-20 — F3 first stage: lifecycle events checked against LIFETIMES.md

Roadmap F3 / plan X3. Before this, `test_runtime`, `test_profiles`,
`test_viewer` and `test_takeover` covered the core of supervisor loss,
compositor loss and viewer disconnect (processes, runtime directory, profile
lock, control handback). Nothing checked what each event leaves in the session
record, profile, downloads, operation records and lease. Nothing covered an
application or Firefox restart inside a session, or repeated viewer closures.
`tests/test_lifecycle.py` adds one test per event. Each test keeps a process
outside the session running `sleep D`, the same command line as a process
inside it, and asserts it still runs afterwards. That checks cleanup goes by
session ownership, not by name.

- **Application restart** (`test_application_killed_and_restarted_in_its_session`):
  SIGKILL a foot terminal fixture, which takes its child too. The session stays
  `ready`, a named controller's lease and a sibling daemon are untouched, a file
  saved in the home is kept, and a new terminal receives typed text and reads
  the file. After `destroy`: no token processes, no runtime directory, home and
  config removed, both terminals' logs, trace and screenshot kept.
- **Firefox restart** (`test_firefox_restart_keeps_profile_files_and_drops_old_tabs`,
  profile session): a cookie set by a local page, a `download` receipt and a
  completed browser job naming the tab context. SIGTERM Firefox, then wait for
  its whole process tree to exit. Until `start`, actions fail with "No bridged
  Firefox". After `start`, the context is new, the old one fails with
  `target_lost`, the cookie is still sent, the download is byte-identical and
  the job record keeps the old context. After `destroy`, the download stays in
  the profile and the profile is unlocked.
- **Runtime (compositor) loss**
  (`test_compositor_loss_then_a_new_session_on_the_profile`): SIGKILL labwc
  while a job's 5 s wait runs, with an env-cleared daemon. The session is marked
  `failed` 0.66–0.76 s later, and everything it owned is gone (daemon included,
  since the guardian lives). The record keeps manifest, log, trace, screenshot,
  a completed job and the interrupted one (`delivery_unknown` or `stopped`,
  never `observed`). The profile keeps its file and reports `failed`. A new
  session on it gets `previous_session: failed`, no lease, no operation records,
  and reads the file. `test_compositor_loss_during_typing_is_uncertain`: a
  3,000-character `type` in progress replies `DeliveryUnknown` within 0.01 s.
- **Supervisor loss**: `test_worker_killed_and_the_guardian_cleans_up`
  (profile; the job reads `delivery_unknown`, step `uncertain`, `lease_cleanup:
  unknown`; a stale `take-requested` marker goes with the runtime; the next
  session on the profile has no lease and agent control).
  `test_both_supervisors_killed_until_destroy_recovers`: until recovery, the app
  and the private home stay. The job ends on its own as `stopped`, with the
  reason "step 0 was delivered, then observation failed: Session unavailable".
  `destroy` recovers: app stopped, home and config removed, `recovered: true`,
  record and job state kept. `test_worker_killed_during_a_takeover`: the
  takeover server and its socket go with the session, and the profile is
  released.
- **Viewer closure** (`test_repeated_viewer_closure_keeps_the_session`): 5
  read-only connect/close cycles, the CLI `viewer.view` path once, and 5
  `viewer.take` cycles, all through a stand-in viewer that does the RFB
  handshake and closes. One read-only wayvnc stays and is reused. Each takeover
  server exits and `takeover.sock` is removed. The epoch rises by 2 per take,
  and a screenshot is needed afterwards. A 300 s lease held by `f3-client`
  survives every closure, and typed text reaches the terminal afterwards.
- **Repeated cycles**: `scripts/lifecycle_stress.py` now checks every destroy
  against LIFETIMES.md. Every second cycle uses the profile `stress` and appends
  to `$HOME/cycles.log`, so the profile must hold one line per profile cycle.
  Each cycle has a lease taken by a named launch, a screenshot and a completed
  job. The session's `sleep D` daemon matches an outside sentinel's command
  line. The check also covers the client's open descriptors, and at the end
  `prune` must remove every record and no profile. `test_repeated_create_use_destroy_cycles`
  runs 4 cycles; the CI invocation (`--cycles 5 --load 2`) is unchanged.

Bugs: none found in the tested paths. Known gap, confirmed and recorded as an
`expectedFailure` (`test_env_cleared_daemon_is_stopped_by_recovery`): after
*both* supervisors die, a `setsid env -i` child carries no token and recovery
leaves it running. While a supervisor lives, it is stopped (subtree). This is
the accepted "detached descendants that clear their environment" limit in
CAPABILITY_MATRIX. A fix needs cgroups, or a persisted descendant list with
start times, so it is left for a follow-up.

Decisions: Firefox is restarted with SIGTERM, not SIGKILL, because Firefox
itself may lose cookies on SIGKILL. That would test Firefox, not this project.
Lease survival across a person's take is asserted as the current behavior.
Runtime upgrade and reboot rows remain untested.

Validation (worktree `f3-lifecycle-stress` at 138f453 plus docs):

- Laptop, single file: `nix shell nixpkgs#labwc nixpkgs#foot nixpkgs#grim nixpkgs#wtype nixpkgs#wlrctl nixpkgs#wayvnc nixpkgs#tigervnc nixpkgs#dbus nixpkgs#firefox nixpkgs#at-spi2-core --command uv run python -m unittest discover -s tests -p 'test_lifecycle.py' -v`:
  10 tests OK (1 expected failure) in 36 s.
- gcp-worker, full suite: `on-worker run -n f3-suite -- nix shell <same packages> --command uv run python -m unittest discover -s tests -p 'test*.py'`:
  444 tests OK in 600 s (35 skipped, 1 expected failure).
- gcp-worker, stress: `uv run scripts/lifecycle_stress.py --cycles 50` passed 50/50
  (25 on the profile) in 76.9 s, 1.521–1.530 s per cycle, descriptors 4 → 4,
  50 pruned. `--cycles 50 --load 8` passed 50/50 in 83.8 s, 1.523–1.812 s
  (median 1.66 s), descriptors 20 → 20, 50 pruned.
- `ps -eo pid,ppid,args` on the laptop and the worker afterwards: no session,
  fixture, stress or load processes left.

## 2026-11-19 — Take while send writes a large value, and during an accessibility read (#213)

The two limits left from #181 (F1), both reported honestly before but loose:

- **`send` to a command, value over the pipe buffer.** Since #207 a take kills
  the command's process group, but `communicate` wrote stdin, so the reply could
  not say how much of a value larger than the 64 KiB pipe buffer had been
  written. The worker now writes stdin itself (non-blocking, waiting at most
  0.1 s for room) and counts the bytes. Every `to_command` reply carries
  `bytes_written`; when a take (or the 60 s timeout) stops the command, the
  message says "after N of M bytes of the value were written to its stdin (the
  rest was not sent)" or "after the whole value (M bytes)", and always "may have
  partly run": the command was started, so it is never reported as not run.
  `bytes_written` counts bytes accepted by the pipe, not bytes the command read.
  A command that closes its input early also shows fewer bytes than `bytes`.
- **Take during an accessibility read.** The worker serves one request at a
  time, and a `ui` read ran to its node limit or 3 s budget before `take` was
  served (#211 measured 0.11–2.79 s). `Accessibility.tree` now takes an
  `interrupt` callable, checked before each element (the take marker is a
  `stat`); the `ui` operation passes `take_requested` and turns the stop into
  `HumanControl`. A partial tree is never returned: an `absent` or `unique`
  claim over it could read as `violated`. `checks.evaluate` maps that refusal to
  `unknown` with "human_control: observation interrupted". The read is
  observation only, so nothing sent before it is affected; the job keeps
  `completed`. One D-Bus call can still block up to its 2 s timeout on an
  unresponsive application; the check is between calls, not inside one.

Decisions: one PR, since both are small and share the docs rows. No bound was
added to a single D-Bus call; checking between elements met the 1 s bound on
the crowded page. Target lookups and `wait` element reads now also give way to a
take with a `HumanControl` refusal, as any request after the take would be.

Tests:

- `tests/test_takeover_long_steps.py`:
  `test_take_while_send_writes_a_value_over_the_pipe_buffer` (40 cookies of
  3,000 characters from a local page, `send source="cookies"` to
  `sh -c 'head -c 1000 > got; touch started; sleep 6; touch finished'`; take once
  `started` exists; asserts 1000 <= `bytes_written` < `bytes`, the counts in the
  error, "may have partly run", that `finished` never appears and the value is not
  in the reply) and `test_take_during_a_jobs_accessibility_check` (a one-click job
  on the `CROWDED_PAGE` of `test_interruptions` with an `absent` check on "Row"
  and nine `exists` checks; take 0.3 s into the first read; asserts the 1 s
  bound, `completed`, the click `acknowledged`, verification `unknown`, the first
  check "observation interrupted", no `violated` check, count 1).
  `test_take_during_a_send_to_a_slow_command` also checks `bytes_written`.
- `tests/test_interruptions.py`: `test_takeover_during_evidence_collection` bound
  tightened from 5 s to 1 s, and it prints the latency.
- Unit: `test_delivery` (whole 200 KB value counted; a command that never reads
  stopped by a take within 1 s with 0 < `bytes_written` < 200,000; a command that
  exits at once; `tree(interrupt=...)` raises rather than returning a partial
  tree) and `test_checks` (an interrupted read is `unknown`, never `violated`).

Validation (worktree from `main` at 7519069, same nix shell as #207 with the
managed runtime first on `PATH`; host load average 8–11 from unrelated work):

- `uv run ruff check src scripts tests` and `ruff format --check`: pass.
- `-p 'test_takeover_long_steps.py'`: 6 OK (77 s). Take acknowledged in 0.21 s
  (open in a job), 0.26 s (accessibility check), 0.22 s (send to a slow command),
  0.25 s (open), 0.19 s (long type), 0.25 s (send over the pipe buffer, stopped
  after 65,536 of 121,258 bytes). An earlier run: 0.23 s for the accessibility
  check, 0.24 s for the pipe-buffer send (also 65,536 of 121,258).
- The two new tests with `src` from `main`: both fail, the accessibility check
  with "2.95 not less than 1.0" and the send with `KeyError: 'bytes_written'`.
- `-p 'test_interruptions.py' -k evidence -k partial`: 6 OK (82 s);
  `-k takeover` again after the latency print: 1 OK, take in 0.18 s.
- `-p 'test_browser.py' -k test_send`: 2 OK.
- Without the desktop: `test_delivery` 21 OK, `test_checks` 10 OK (1 skipped),
  `test_operations` 21 OK (6 skipped).
- Not run: the full desktop suite and the Checks matrix.

## 2026-11-20 — The crowded test page is partial on an idle machine too

The two partial-coverage interruption tests from #212 failed on the Ubuntu and Nix
Checks jobs (run 44620522297, on #214's branch) and locally on `main` at load 1–2:
a `unique` check was `satisfied` and a retried accessibility press found no match
instead of refusing as incomplete. The page's 2,500 extra buttons are off-screen, so
they do not count towards the 2,000 listed nodes, and an idle machine visits all of
them within the 3 s budget: the read was complete, not partial. The tests had passed
only under a load average of 90–110, where the time budget ran out.

The page now has 21,000 off-screen rows, past the 20,000-node visit limit of a
2,000-node read, so every read is partial by construction. Validation: the two
tests passed four times in a row at load 1–2 with the managed runtime, and
`test_interruptions.py` passed in full (11 OK) with stock nixpkgs labwc, Firefox and
`at-spi2-core`. `ruff check` and `ruff format --check` pass.

## 2026-11-19 — Partial accessibility coverage under interruption (F1-c, #181)

The last F1-c case: the R1 partial-coverage regressions (`test_completion_targets`,
`test_tree_bounds`, unit level) rerun in a real session alongside the F1-a kills.
The page has an "Add" button, 2,500 more buttons and a second "Add" past them, so
every tree read is partial (the 2,000-node limit, or the 3 s budget; on this host
it was the budget) and a unique match in a read is not unique. Two new tests in
`tests/test_interruptions.py`:

- `test_partial_coverage_checks_interrupted`: a one-click browser job with twelve
  checks (`unique` and plain `exists` on "Add", `absent` on a missing name) is
  killed after two to eleven are recorded. The job keeps `completed` with
  verification `unknown`. Every recorded `unique` and `absent` check is `unknown`,
  an `exists` check is `satisfied` or `unknown` and never `violated`, and every
  recorded tree coverage is partial. The click landed once and the second button
  was not touched.
- `test_partial_coverage_target_after_an_interrupted_job`: an actions job that
  pauses before an accessibility `press` on "Add" (exact) is killed during the
  pause (`delivery_unknown`, the press still `pending`). The press submitted again
  stops before any input (`failed`, "The UI listing was incomplete; uniqueness is
  unknown"), and neither button is pressed: no silent retargeting.

Both already behaved correctly; no source change.

Validation (worktree on the F1-a branch, same nix shell and managed runtime as
that entry, host at load average 90–110 from unrelated processes):

- `uv run ruff check src scripts tests` and `ruff format --check`: pass.
- `-p 'test_interruptions.py' -k partial_coverage`: 2 OK (73 s).
- Full desktop suite on this branch (F1-a and F1-c together): 426 tests in
  52 min, 22 skipped, 4 failures and 6 errors, all in `test_run` (2),
  `test_runtime` (3) and `test_script_jobs` (5), none of which drives durable jobs:
  timing bounds and cleanup timeouts under the host load ("3.33 not less than 2",
  "Session cleanup timed out"). Rerun alone once the load fell to about 16,
  `-p 'test_run*.py'` (`test_run` and `test_runtime`): 33 OK, 11 skipped.
  `test_script_jobs` is known to be load-sensitive on `main` and is being fixed
  separately; it was not rerun.
- Not run: the Checks matrix.

## 2026-11-19 — Interruptions during evidence collection (F1-a, #181)

The last F1-a gap: a durable job interrupted after its effect, while its evidence
is read. #193 covered a kill between the job's checks. Three more interruptions
now have tests in `tests/test_interruptions.py`:

- **Killed while a step's expectation is read.** An actions job types `once`
  into a page, then waits up to 10 s for an `expect` title that never appears; the
  helper is killed once the step is `acknowledged`. This found a wrong state: the
  reader that found the helper dead reported `delivery_unknown`, "reconcile its
  recorded delivery before retrying", although no input was in flight and the step
  was acknowledged. Now a helper killed with no step `dispatching` or `uncertain`
  ends `stopped`, delivery as recorded, with a reason that says the last delivered
  step's expectation and observation are unknown. The step after it stays
  `pending`, and the page holds `once`, typed once. A job with a `key_down` step
  stays `delivery_unknown`, because its keys are released after the last step
  without a step record of their own. Without the fix the test fails with
  `'delivery_unknown' != 'stopped'`.
- **Cancel during the checks.** A one-click browser job with twenty checks is
  cancelled after the first check is recorded. It stays `completed` with
  `cancel_requested: true`; the click is not reported as cancelled, all twenty
  read-only checks still run, and the page count is 1. Already correct.
- **Takeover during the checks.** The same job, with `take` sent after the first
  check. It stays `completed` with verification `unknown`; later checks are
  `human_control: observation refused`, the lease is released and the count stays
  1 after the person hands back. Already correct. Take was acknowledged in 0.11 s
  and 0.27 s in two unloaded probe runs and in 2.79 s on a host at load average
  about 100 (see below): an accessibility read does not check for a take, so a
  take waits for the read in progress, which stops at its 3 s budget. The test
  bound is 5 s.

A smaller window had the same wrong state: a helper killed during its lease
cleanup after its steps, in a job without checks, read as `delivery_unknown`
because `outcome` was only saved for jobs with checks. It is now saved for every
job, and the restored record keeps `verification: not_requested`. Two unit tests
in `test_operations` cover both readings from saved records.

The kill during a check still lands by timing (twenty checks of about 0.1–3 s
each), not through a fault-injection hook; the record cannot tell a kill inside a
check from one between two checks, and both read the same.

Validation (worktree on `12fe69b`, nix shell with labwc, foot, grim, wtype,
wlrctl, wayvnc, tigervnc, dbus, firefox, plus the managed runtime's `bin` first on
PATH for accessibility):

- `uv run ruff check src scripts tests` and `ruff format --check`: pass.
- `-p 'test_operations.py' -k OperationTests`: 15 OK (two new; both fail without
  the fix).
- `-p 'test_interruptions.py'`: 9 OK (three new). `-p 'test_operations.py'`:
  21 OK (desktop and unit).
- The host ran at load average 90–110 throughout, from unrelated processes
  outside this project. A first run of `test_interruptions` under it had two
  errors from Firefox refusing a new BiDi session ("Maximum number of active
  sessions") in `setUp`-started browsers and the 2.79 s take above against a 1 s
  bound; the rerun after the bound change passed.
- The full desktop suite was run on the stacked F1-c branch, which contains this
  change; its result is in that entry.

## 2026-11-19 — Flaky script job tests: the timeout counted interpreter startup

`tests/test_script_jobs.py` passed alone (13 OK) but, under the load of the full unit
suite, a changing three or so of its timing tests failed. Reproduced by running the file
repeatedly beside 24 busy-loop processes on 12 cores (the pattern of
`scripts/lifecycle_stress.py --load`): on unmodified `main`, 10 of 10 runs failed, 3 to 6
tests each, a different set every run.

Root cause. `script_jobs.run` started its timeout clock at `Popen` of the supervisor, so
the deadline also paid for the supervisor's interpreter, the script interpreter and
`from agent_desktop.script import *`. A trivial job takes about 0.45 s idle and more
under load. The tests used a 0.5 s timeout and then needed the script to have written a
pid file, printed, journalled a call or had a child interpreter running, so under load
the job was timed out before the script had run. Two further races sat in the tests:
the pid file was read while the child might still be writing it, and a script that returned
immediately was still reported `timed_out` when the supervisor's own cleanup (a fixed 0.3 s
plus a reaping wait) overlapped the deadline. The latter is a small real defect:
`timed_out` with `exit_code` null for a script that had already exited.

Changes.

- `src/agent_desktop/script_jobs.py`: the script's bootstrap imports the helpers and then
  creates a `ready` marker; the timeout counts from that marker (from launch plus
  `START_ALLOWANCE` of 10 s if it never appears). The supervisor creates an `exited`
  marker when the script returns, and after that only a cleanup stalled for
  `SUPERVISOR_GRACE` is timed out. The prefix import line left `code.py`, so traceback
  line numbers of the user's code are now exact instead of one too high. The cancel
  path is unchanged. `docs/USAGE.md` says the timeout counts from the script start.
- Tests wait on conditions. Tests that need a child process to be running no longer race
  a deadline: they wait for its (atomically written) pid file, then stop the job through
  the same cleanup path (`run_until_child`; these were `timeout_*` tests and are now
  `stopping_*`, with the real `timed_out` path still covered by the stopped-supervisor
  and output tests). Children sleep 60 s so survival is judged only through `/proc`, and
  the dead late-marker file check is gone. Scripts that return wait for their child first.
  Whole-job bounds are 20 s rather than 2 to 7 s: they distinguish returning from
  blocking (the scripts would run 30 s). Tests that only use the timeout as a stop use 1 s,
  which is measured from the script start.
- New `test_timeout_does_not_count_slow_startup` delays the supervisor 3 s with a 2 s
  timeout and checks that a script finishing at once is not timed out. It fails on the
  previous `script_jobs.py` (checked).

Validation. Before and after: `test_script_jobs` run 10 times in a row beside 24 busy
processes (the shared machine also had a load average of 85 to 113 from other work).
`main`: 10 failing runs of 10. This change: 0 failing runs of 10. Alone: 14 OK. Under
the nix desktop shell: `test_script_jobs.py` 14 OK, `test_run.py` 5 OK. `ruff check` and
`ruff format --check` pass. Earlier iterations of this change failed 2 of 10 under the
same load, from a 0.5 s timeout in the new test and a child that needed more than the
timeout to start under load 90; both were removed by the changes above. The Checks matrix
was not run.

## 2026-11-19 — Attach-profile follow-ups: shared refusal, guardian holds the lock

Two follow-ups to the attach-profile change.

- The "profile held by another session" refusal in `core.attach_profile` now raises
  `profile_busy(name, path)`, the same message as `create` (holder session and idle
  time, with the advice to destroy a finished session or use another profile).
- The guardian now receives the lock descriptor the worker sends over the socketpair.
  Before, nothing read it: the lock survived a killed worker only because Linux keeps
  an in-flight `SCM_RIGHTS` descriptor open while it sits unread in the receiving
  socket's queue, an accident of the kernel. A daemon thread in the guardian
  (`receive_profile_locks`) now calls `recv_fds` and keeps each descriptor, which shares
  the worker's open file description and so its `flock`, until the guardian exits.
  Decision: a thread rather than polling in `guard`, because `guard` blocks in
  `waitpid` and the thread leaves that and its signal forwarding untouched. The lock
  is still released only when both processes have exited, as at create.

Validation (nix shell with the desktop tools): `tests/test_profiles.py` 16 OK. The
guardian-lock test now also waits until the guardian's `/proc/PID/fd` lists the lock
file, which fails (timeout) on the previous worker.py and passes now; it then stops the
guardian, kills the worker and checks the profile stays in use. `test_field_findings.py`
6 OK. `ruff check` and `ruff format --check` pass. The Checks matrix was not run.

## 2026-11-19 — A site's cookies for shell tools

Added `send` source `cookies` (with `site`). In the coursework field report, an agent
needed `yt-dlp` for hour-long lecture videos. It wrote its own exporter that copied a
profile's `cookies.sqlite` and decoded Firefox's session-restore file (a session cookie
lived only there), with `sleep` loops until that file was written. The new source reads
live cookies with BiDi `storage.getCookies`, keeps those for the site, its subdomains
and its parent domains, and writes a Netscape `cookies.txt` (HttpOnly marked as curl and
yt-dlp expect) to a 0600 `to_file` or a command's stdin. The reply has only the count,
bytes and digest. It is refused on host sessions, so the person's own cookies are never
exported. This is a credential-handling change for the maintainer to accept: it makes
supported something agents already did by hand.

Validation: `tests/test_send_cookies.py`. Four unit tests cover site matching
(including a lookalike domain), the format, refusals, the private file and no values in
the reply. A desktop test with real Firefox 160 and a local server exported an HttpOnly
session cookie that the server had set.

## 2026-11-19 — Add a profile to a running session (X8)

A session created without a profile can now be given one: `agent-desktop
attach-profile SESSION PROFILE`, MCP `desktop_profiles(session, attach)` (a field
on the existing tool, so the schema count stays 29).

Design:

- The worker takes the profile lock (`flock`, as at create), switches `HOME` and the
  XDG variables of its environment, records `profile`, `home` and `profile_lock` in
  the manifest and writes the profile's `last-session.json`. Applications started
  afterwards, Firefox included (its shim reads `$HOME` at start), use the profile.
- The lock is also sent to the guardian over a socketpair (`SCM_RIGHTS`), so a worker
  that dies abnormally cannot free the profile while the guardian is still stopping
  the session's applications, the same guarantee as at create.
- Refused with nothing changed: invalid name (before any directory is made), host
  session, a session that already has a profile, a profile held by another session
  (named), and any application of the session still running. A running browser is
  not restarted: it keeps the old home, so the caller closes it first. A refusal
  does not leave a new empty profile behind. An abandoned profile is recovered as at
  create. `destroy` releases the profile as before.
- Not done: files in the old home are not copied; the session's private bus keeps
  the old home for services it starts on demand; the experimental effect ledger keeps
  watching the old home; the `create` refusal text is unchanged (#203 adds the holder
  and idle time there; the attach refusal names the holder session only).
  `core.attach_profile` repeats a few lines of `create`'s profile preparation rather
  than refactoring them, to keep the later rebase onto #203 small.

Validation (worktree on `0b99793`, nix shell with labwc, foot, grim, wtype, wlrctl,
wayvnc, tigervnc, dbus, firefox):

- `uv run ruff check src scripts tests` and `ruff format --check`: pass.
- `... unittest discover -s tests -p 'test_profiles.py'`: 16 tests OK (four new:
  attach to a running session, refusals, lock held by the guardian after the worker
  is killed, Firefox started after attach sends the cookie to the next session).
- `-p 'test_browser.py'`: 15 OK. `-p 'test_release_profiles.py'`: 3 OK.
- Full unit suite (no desktop tools on PATH): 390 tests, 149 skipped, 3 timing failures in `test_script_jobs` (two runs, same three). They pass alone (13 OK), and a full run on unmodified `main` also fails three other `test_script_jobs` tests (386 tests, 145 skipped), so the suite is load-sensitive there; unrelated to profiles.
Not run: the Checks matrix (a worker change, but no packaging or CI change; a manual
run is optional).

## 2026-11-19 — Take during a long open, send or type

Remaining F1-b gap in #181. The worker serves one request at a time, so `take`
queued behind the request in progress. #185 made browser waits give way; a slow
`open` (waiting for the page to load, up to 60 s), a `send` to a command (up to
60 s) and a long `type` (about 8.5 ms per character, so up to about 85 s for
10,000 characters) still held it back.

Each now checks the `take-requested` marker about every 0.1 s:

- `open`: the BiDi navigate reply is awaited in 0.1 s slices. On a take the step
  returns `uncertain` and `interrupted`; the navigation was sent and may still
  finish loading. A durable job records it as `uncertain`, ends
  `delivery_unknown` and sends no later step.
- `send` to a command: the command runs in its own process group and is polled.
  On a take its group is killed; the reply keeps `sent`, `bytes` and the digest,
  with `exit_status: null`, `uncertain` and `interrupted`, since it may have
  partly run. The timeout path also kills the group now.
- `type`: sent in chunks of 10 characters with a check before each, and the
  screen settle between Tab/Return runs stops early on a take. A take before the
  first chunk is a known `HumanControl` refusal; afterwards the reply is an
  uncertain `TakenOver` error saying how many characters were sent.

Bound: 1 s in the test. It allows one 0.1 s check interval, one chunk (about
0.1 s) and the take itself, which starts the takeover VNC server (about 0.1 s),
with room for a loaded machine. Measured on NixOS, take acknowledgement:

| Step in progress | Before | After (range over the runs) |
| --- | --- | --- |
| `open` of a page that answers after 6 s | 6.24 s | 0.14–0.24 s |
| `open` as a step of a durable browser job | not measured | 0.21–0.64 s |
| `send` to `sh -c 'cat >got; sleep 6; touch finished'` | 6.19 s | 0.19–0.66 s |
| `type` of 1,500 characters, taken 2 s in | 10.82 s | 0.10–0.46 s |

Validation: new `tests/test_takeover_long_steps.py` (4 tests) checks each bound,
that the page received exactly the reported characters and nothing more, that the
command's later work never ran, and that the job's later click never landed. Run
in `nix shell nixpkgs#labwc nixpkgs#foot nixpkgs#grim nixpkgs#wtype
nixpkgs#wlrctl nixpkgs#wayvnc nixpkgs#tigervnc nixpkgs#dbus nixpkgs#firefox
--command uv run python -m unittest discover -s tests -p 'PATTERN' -v`:
`test_takeover_long_steps` 4 tests OK (three runs; the slowest was the last,
in the sequence below), `test_takeover_jobs` 2 OK, `test_takeover` 6 OK,
`test_operations` 19 OK, `test_interruptions` 6 OK, `test_browser` 15 OK,
`test_delivery` 17 OK, `test_runtime` 28 OK (11 skipped). `ruff check`,
`ruff format --check` and the unit suite (390 tests, 149 skipped) pass.

Not covered: a take while `send` is still writing a value larger than the pipe
buffer (the reply cannot tell how much was written), and the Checks matrix was
not run.

## 2026-11-19 — Save large page text to a file

Added `desktop_browser` action `save` (CLI `browser SESSION save`). The Canvas
report's export stopped twice on `send`'s 64 KiB secret limit and was worked around
with smaller pages. Agents used `send`, a secret transport, as a data export.
`save` writes the page's visible text, or one element's, to a 0600 `to_file`, up to
8 MiB (under the 16 MiB BiDi message limit). It is the whole text or nothing,
written to a temporary file and renamed, and the reply has only bytes, characters,
SHA-256 and the page's url and title. `send` keeps its limit and minimal reply for
secrets.

Validation: `tests/test_save.py`. Two unit tests cover a listing larger than 64 KiB,
the overwrite rule, ambiguous targets, the size limit with no partial file, and the
missing `to_file`. A desktop test saved a 193 KB `<pre>` from real Firefox 160 whole.

## 2026-11-19 — Browser downloads with a receipt

Added `desktop_browser` action `download` (CLI `browser SESSION download`). Both the
Canvas and coursework field reports found agents opening download links, then
polling the profile's `Downloads` with `ls -t`, `find -newer` and size checks to see
whether a file had arrived. `download` navigates the tab (which keeps its page),
waits for the one new file without a `.part` beside it to reach a stable size, and
returns its name, path, bytes and SHA-256. It can move the file to a private
`to_file`. It reports a page loaded instead (login redirect, inline viewer) without
saving anything, and a timeout mid-transfer as still running, not failed. The URL is
not echoed. `desktop_browser`'s `timeout` now defaults per action (wait 10 s,
download 120 s). `private_path` is now shared by `send` and `download`.

Validation: `tests/test_download.py`. Six unit tests use a fake Firefox that writes
`NAME` and `NAME.part` like the real one. A desktop test uses real Firefox 160 and a
local HTTP server: an attachment download whose receipt matched the served bytes,
the tab staying on its page, and an HTML URL refused as a page. With the runtime on
`PATH`, `test_browser` (15) passed after the default-timeout change. Not tested:
redirects through a real login, duplicate filenames from Firefox's `name(1).ext`
renaming, and downloads over 600 s.

## 2026-11-19 — Small fixes from the coursework field report

Fixes for problems agents hit between 11-10 and 11-18 (see the coursework field
report):

- `desktop_create` no longer says a shell under test "usually needs gles2" without the
  Mesa condition. A startup failure with `EGL_EXT_platform_base`, GBM or renderer
  errors now says the server needs the runtime's Mesa and to retry without a renderer.
  Three agents had tried gles2 first and failed.
- A refused `create` on a busy profile names the holding session and how long it has
  been idle. `profiles` adds `held_by`. One session had held a profile for two hours
  after its last call.
- `send to_file` creates missing folders inside the session home (0700). Paths outside
  it are still refused.
- More than 30 browser steps: the error says how many were sent and that nothing ran.
- `open` refuses `view-source:` URLs before navigating, instead of an uncertain
  delivery, and suggests `text` (or Raw Data for JSON).
- USAGE.md: a GPU rendering heading, and a note that a private session protects the
  screen but not an application's own data folder.

Validation: `tests/test_field_findings.py` (6 tests). The unit suite ran 391 tests with
144 desktop tests skipped. With the runtime on `PATH`, the desktop tests `test_browser`
(15) and `test_profiles`/`test_release_profiles` (15) passed. `ruff check` and
`ruff format --check` pass. Not run: the Checks matrix (no runtime or packaging change).

## 2026-11-19 — Usage review workflow

Added `scripts/usage_review.py`, [USAGE_REVIEW.md](USAGE_REVIEW.md) and a
`usage-review` skill, so a field report no longer starts with ad-hoc transcript
searches. The script reads Claude Code and Codex transcripts, counts each Agent
Desktop call once, and flags shell workarounds, errors, batch stops, session leaks and
idle sessions, the person's remarks near calls and tools nobody called. It writes a
private 0700 folder outside the repository. On 2026-11-10 to 11-18 it reproduced the
coursework report's 149 calls in 10 transcripts and corrected two of its hand counts
(5 batch stops, not 6; 3 coordinate calls with an observation, not 2). Validation:
`tests/test_usage_review.py` (4 tests) with synthetic transcripts in both formats, plus
`ruff`. Transcripts expire after about 30 days, so the workflow asks for a review
every two to three weeks.

## 2026-11-19 — Coursework and shell-testing field report

Reconstructed unrequested MCP use from 2026-11-10 to 2026-11-18 in
[the coursework field report](../trials/2026-11-19-coursework-and-shell-tests.md):
149 deduplicated Claude Code calls in 10 transcripts across four repositories,
cross-checked against `agent-desktop activity --days 8` (293 calls, 25 sessions,
including the Codex crawl's 173). The main findings are that an agent hand-exported profile
cookies to a 0600 scratch file for `yt-dlp`, that downloads were found by polling the
profile's `Downloads`, and that three GPU creates failed with the documented EGL error
after the create tool's text recommended gles2. No runtime code changed. No tests were
run, since this is a documentation record.

Added [USE_CASES.md](../USE_CASES.md), a public list of real use cases with the
period each report covers, and replaced the README's per-report rows with one link
to it. Revised the Canvas report: the session Codex reused had been left running by
a Claude Code agent whose context ran out.

## 2026-11-12 — Canvas collection field report

Recorded a real authenticated read-only browser task in
[the Canvas MCP field report](../trials/2026-11-12-canvas-materials-crawl.md).
The scoped result was 66 verified PDFs (52,200,194 bytes), using 173 MCP calls
across five tools in one existing headless session; no host input or login
handoff. The session was closed and the profile's release verified. Private
materials, account identifiers and raw traces remain outside this public repo.

Two 64 KiB export-limit stops were recovered with smaller pagination. Nine API
permission-denial bodies and disabled indexes required following published links
rather than assuming a complete file index. The report proposes download receipts,
a bounded data-export operation and scoped task metrics; no runtime code or
product-direction change was made. Validation was the real task's ID/size/hash,
PDF-page and source-coverage audit, not the desktop test suite. Hidden/unlinked
files, optional recordings, crash/login recovery and physical input remain untested.

## 2026-11-12 — Host requests the client has already asked

`desktop_request_host` can now rely on the MCP client's own prompt. With
`AGENT_DESKTOP_HOST_APPROVAL=client` in the server's environment, the call starts
the host session at once: no notification, no request file, no wait. The intended
client is Claude Code with a `PreToolUse` hook that answers `ask` for that one
tool, which it honours even with permission prompts bypassed, so the question can
be answered wherever the session is followed. Without the variable nothing changes.
The CLI ignores it (`host start` already allows directly).

The variable is only as safe as the client's prompt: set without one, an agent gets
the screen without asking. INTEGRATIONS.md keeps the hook and the variable
together and suggests a matching hook on `agent-desktop host start` for shells.

Validation: `test_host.test_client_approval_starts_without_a_request` starts a host
session on a private stand-in desktop with no request file; the full `test_host`
suite passed in a `nix shell` with labwc, foot, grim, wtype, wlrctl, wayvnc,
tigervnc and dbus (11 tests). `ruff check`, `ruff format --check` and the unit
suite (376 tests, desktop tests skipped) pass.

## 2026-11-12 — Zero-touch delegation design proposed

The maintainer set a north star: delegation on their own Linux desktop where they
are needed for nothing but stating the task, measured by touches per task.
[DELEGATION.md](DELEGATION.md) proposes the design: a task record above sessions, a
`delegate` entry point for the shell hotkey, task events on top of
EVENT_CONTRACT.md, a touch ledger, delegated identity, one approval path, and a
roadmap of stages Z0–Z11 that starts with a measured baseline on 3–5 real tasks. It
also reviews the repository against the goal, including the MCP tool surface (15 of
29 tools were called in the two field reports), and recommends leaving #196
unmerged. [DELEGATION_BEYOND.md](DELEGATION_BEYOND.md) lists further ideas, each
labelled checked or unchecked against prior art.

The same day's market and prior-art scan is added as
docs/research/2026-11-12-ambitious-directions-scan.md. It recommended a different
flagship (the desktop pull request), which the proposal keeps as a candidate
feature.

No code changed and nothing was run: this is a documentation-only proposal. Facts
about Claude Code (headless mode, background sessions, Remote Control, plan
limits) come from its documentation as read on 2026-11-12 and were not tested
here. PROJECT_PLAN.md gains one note pointing to the proposal and is otherwise
unchanged.

## 2026-11-12 — Documentation reorganised, architecture overview added

Docs only; no source, test or benchmark file changed, so the desktop suite was not
run. Added [docs/ARCHITECTURE.md](../ARCHITECTURE.md), written from the modules in
`src/agent_desktop/`, and linked it from the README and START_HERE. Moved the
project plan's historical sections (alpha work, the October research progression,
the field-report follow-ups and the original sections 1-10) verbatim to
[archive/PROJECT_PLAN-history.md](archive/PROJECT_PLAN-history.md), leaving the
header, execution plan, current priority and development status. Moved the October
2026 log entries verbatim to [log/2026-10.md](log/2026-10.md); only relative link
paths changed in moved text. Added [docs/research/README.md](../research/README.md),
a dated index of the research notes with their outcomes; research files did not
move. Line counts: PROJECT_PLAN.md 665 to 203, DEVELOPMENT_LOG.md 4396 to
718 (the October entries are 3,700 lines in the archive).

## 2026-11-12 — F2 native document edit, deterministic driver (X2)

The second F2 workflow. `benchmarks/f2_document.py` writes a short agreement as
`.odt` or `.docx` (title and six numbered clauses, their order after the first
following a seed) and evaluates the result. The task changes the payment term in
the payment clause from 30 to 14 days; the delivery and notice clauses also say
"30 days". The evaluator reads only the saved file and its folder: every
paragraph against the expected text (a wrong target or bystander is named), the
paragraph count, and no other file beside the document, so a save in another
format or name, or a lock left by an unclosed LibreOffice, fails. Its own tests
check known-wrong outcomes (untouched, every "30 days" changed, a lost paragraph,
a stray copy, a lock file, a missing file).

`tests/test_document_workflow.py` drives LibreOffice Writer through the session:
Find selects the payment sentence, typing replaces it, Ctrl+S saves, Ctrl+Q
quits, and the file is opened again in a fresh LibreOffice. Three trials:

- `.odt`, a clean run.
- `.docx`: saving brings up "Non-standard file format", an untitled dialog. The
  driver presses "Use Word 2007 Format" by name through the accessibility tree
  (its role is `button`), so the Word format is kept.
- LibreOffice is killed after the edit and before saving. The file is unchanged;
  the reopen finds a stale `.~lock` file. LibreOffice 26 on Fedora 44 reopened
  over its own stale lock (same user and host) without a "Document in Use"
  dialog; the driver repeats the edit once and saves.

Two driver timing faults were found and fixed while writing it: typing into a
reopened document before LibreOffice was ready (the reopen now uses
`office_smoke.launch`, which waits for a focused document), and Ctrl+Q sent while
the format dialog was still the active window (quit now waits for the document
to be active again).

Validation on the Fedora 44 VM (SELinux permissive, as CI runs it; LibreOffice
from Fedora's packages): all six tests passed 8 times in a row, 3 of them under
`stress-ng --cpu 4`. This machine has no LibreOffice, so they skip here. In the
Checks matrix the `.docx` trial first failed on Ubuntu 24.04, whose older
LibreOffice did not show the untitled dialog the driver waited for. The driver
now presses any button starting "Use Word" wherever it is, or accepts a save that
asks nothing (the evaluator still requires the `.docx` and no `.odt` beside it).
Run 43262022719 then passed all three trials on Ubuntu, Fedora and Arch. Not
covered yet: an agent-driven run of this task and the mixed workflow.

## 2026-11-12 — Agent-driven F2 dataset edit (X2)

The inventory service, its page and the evaluator moved from
`tests/test_dataset_workflow.py` to `benchmarks/f2.py`, shared by the deterministic
driver and a new benchmark task, `f2-dataset-edit` (`--suite f2`). The agent gets
only the goal: retire supplier Norvik's products, change nothing else. The start
page (1–4) and the save after which the session-expiry modal opens (1–3) follow
`--seed`. The check is the same service-side evaluator as the driver's: the agent's
replies and the page are not consulted. The harness gains `context.closers`, so a
task's service stops when the run ends, and `browser_command` launches the
benchmark browser on a URL rather than a page file. `AgentTaskTests` checks the
task's setup and judge without a model: no edits fail, the right edits pass, and a
changed bystander fails.

The maintainer set a low model budget, to be raised only if the first runs went
wrong. Two runs, seed 1 (seed 948735, start page 2, modal after the first save):

| Browser | Passed | Wall s | Cost USD | Tool calls | Saves |
| --- | --- | ---: | ---: | ---: | ---: |
| Firefox, `--firefox --bridge` | yes | 41.2 | 0.29 | 6 | 4 |
| Chromium | yes | 75.9 | 0.41 | 24 | 4 |

Both edited exactly the four targets once each and left "Norvika" alone. The
Chromium agent reported dismissing the modal with "Stay signed in". The runs went
as planned, so no more were spent ($0.70). Not covered by these runs: helper kills
and disconnects (the agent does not have to use durable jobs), virtualised lists
and viewport changes.

## 2026-11-12 — Accessibility on SELinux-enforcing Fedora (X13)

The worker now starts `at-spi-bus-launcher --launch-immediately` itself, from the
registry's directory, and waits up to 5 s for it to own `org.a11y.Bus` before it
starts the registry. Started by the worker, the launcher keeps the worker's
context instead of the `gnome_atspi_t` transition that the policy refuses when the
private bus executes it. If there is no launcher beside the registry, or it does
not take the name, the private bus activates `org.a11y.Bus` as before, and if that
fails the session starts without accessibility and says why. The launcher is
tracked with the session's processes and stopped at cleanup; `session.json`
records `accessibility_bus: launched`.

On the Fedora 44 VM with SELinux enforcing, a session reported accessibility on,
and `test_ui` passed (15 tests, 2 skipped). On NixOS, `test_ui` passed and the new
`AccessibilityBusLauncherTests` confirms the launcher is started directly.
`BrokenAccessibilityBusTests` still covers the fallback: its registry wrapper has no
launcher beside it.

## 2026-11-12 — Fedora with SELinux: sessions start without accessibility (X12, X13)

The maintainer allowed a Fedora VM for X12. It runs the Fedora 44 Cloud image
(1.7, checksum verified) under QEMU/KVM with 4 vCPUs and 6 GiB, the size of a GitHub
runner, with CI's Fedora packages (Chromium 156.0.8078.79, labwc 0.9.6) and the
private Xwayland runtime built by `scripts/build_xwayland_runtime.sh`. The VM files
live in the ignored `artifacts/fedora-vm/`.

**Every private session failed to start** with "not enough values to unpack
(expected 2, got 1)". The private bus could not activate `org.a11y.Bus` ("Failed to
execute program org.a11y.Bus: Permission denied"); `GetAddress` returned that error,
and the worker parsed its text as a bus address. The cause is SELinux, which CI's
containers do not run: with `setenforce 0` the session started and the bus came up.
Under enforcing, with the policy's `dontaudit` rules disabled (`semodule -DB`),
`/var/log/audit/audit.log` shows `SELINUX_ERR op=security_compute_sid
invalid_context="unconfined_u:unconfined_r:gnome_atspi_t"` for
`scontext=unconfined_dbusd_t` executing `gnome_atspi_exec_t`. The private
`dbus-daemon` runs as `unconfined_dbusd_t`, the policy's transition for the
launcher gives `gnome_atspi_t`, and that type is not valid with the user's role,
so the exec is refused and the launcher never starts. Under permissive mode the
launcher then also meets file denials in the session's runtime directory
(`user_tmp_t`), which enforcing never reaches. This applies to any
SELinux-enforcing Fedora where the bus is started this way. Started directly from
a shell (`unconfined_t`), the launcher stayed `unconfined_t` under enforcing and
`GetAddress` returned an address, which is the route for X13.

Fix: an error reply, or an address without `=`, is an `AccessibilityError` naming the
bus error, and a registry that fails to start no longer fails the session. The
session starts with `accessibility: false` and an `accessibility_error` in `status`.
It mentions SELinux when `/sys/fs/selinux/enforce` is 1, and the UI tools refuse
with the same reason. New `BrokenAccessibilityBusTests` reproduces the failure on any
machine: a registry wrapper whose prefix offers an `org.a11y.Bus` service that
runs `false`. Without the fix it fails with "Session startup failed". On the
enforcing VM, with the fix, a session started, took a 1280-wide screenshot and
reported the reason; `test_chromium_receives_every_character` passed 5 of 5 and
`test_runtime` passed (one skip), so the desktop works without accessibility. Restoring accessibility under SELinux is plan row X13.

**X12 does not reproduce on Fedora either.** With SELinux permissive, to match CI,
`test_chromium_receives_every_character` passed 60 of 60 as an ordinary user with
Chromium's sandbox (10 idle, then 50 under `stress-ng --cpu 4`), and 20 of 20 as root
with `--no-sandbox`, as CI runs it, under the same load. Differences from CI remain:
a VM rather than a container on a GitHub runner, and the test run alone rather than
in the middle of the full suite. The CI drop stays a rare flake seen once (Checks
run 43089078794).

## 2026-11-12 — A job killed during its checks keeps its outcome (F1-a, #181)

The last untested F1-a boundary was an interruption while a durable job collects
its evidence, after its steps. New `test_during_evidence_collection` gives a
one-click browser job twenty checks (a browser context and nineteen
accessibility-tree queries, which take long enough to land between) and kills the
helper once at least one check is recorded.

It found a wrong state. The helper sets the record back to `running` while it
checks, so the lease cannot be raced, and a reader that found the helper dead
treated it like any job that died mid-step: `delivery_unknown`, "reconcile its
recorded delivery before retrying". Every step had finished, so that sent a caller
to reconcile a delivery that was known. The helper now saves the steps' terminal
state as `outcome` before the first check. A reader that finds the helper dead with
an `outcome` restores that state, keeps verification `unknown` and the checks that
did run, says how many were recorded, and gives back the lease as before. A job
with no checks saves nothing extra. Without the fix the test fails with
`'delivery_unknown' != 'completed'`.

## 2026-11-12 — Desktop subagent on the main model (N10)

The arm the pilot suggested: the subagent on `opus`, the main agent's model
(`benchmarks/agents/desktop-same-model.json`). Two runs (same tasks and seed as the
pilot), then the direct arm again to check for drift: direct 36.1 s and 60.1 s,
matching the pilot. The same-model subagent took 76.0 s and 117.9 s (+111% and +96%)
and cost $0.46 and $0.59, more than direct, at equal success and with main-context
tokens down 92–97%. The delay comes from delegation (rediscovering the setup and the
extra verification the hand-off asked for), not from `haiku`. Details are in
docs/research/2026-11-11-desktop-subagent-pilot.md. Today's runs cost $1.70.

## 2026-11-12 — Checks on the maintainer's screen (X5, X6, X9, X10)

The maintainer approved a 20-minute host session on their own screen (Hyprland
0.57.1 with a Lua configuration, US Dvorak, one 1920x1080 output). All agent input
went to an empty workspace (4) and two kitty windows the session launched there;
the person's own windows were only listed and never given input.

- **Launches (Lua `exec_cmd` retry, 2026-11-11):** both `desktop_launch` calls
  reported `launched_via: hyprctl` and the windows appeared on workspace 4.
- **X6, settling after input:** `logo+4` with `screenshot=true` returned a complete
  frame of the new workspace (`settled: quiet`, 737 ms), not a frame mid-animation.
  Later captures settled in 467–1012 ms.
- **X9, layout-aware placement on a real host:** typing `echo 'The quick brown fox
  jumps over the lazy dog; [x]-=/?,.<>'` in kitty echoed exactly. `ctrl+l` cleared
  the screen; a US-position placement would have sent Dvorak `ctrl+p` and recalled
  the line. The compositor bind `logo+h` moved focus from the right kitty to the
  left one (`desktop_windows` showed the activated state move).
- **X10, opening a URL without a bridge:** the person's Firefox had no BiDi port.
  `open` with `new_tab` on `https://example.com/` replied `delivered` and the tab
  became the active tab of one of their two Firefox windows, the one on workspace 1
  (Firefox chose it; one observation does not show its rule). That window did not
  come forward; the screen stayed on workspace 4. The reply note,
  tool description and USAGE now say the window may stay in the background. The
  tab was left open for the person to close.
- **X5, focus on another workspace:** `desktop_focus` of the kitty on workspace 3
  from workspace 4 switched there and reported it activated.

Not checked: the off-screen refusal on a real inactive terminal. It needs the
person to switch virtual terminals. They were asked in the conversation to press
Ctrl+Alt+F2 and come back, as an optional step; no switch happened within the
2-minute wait, so the check was skipped and stays open. Both test windows exited through `exit`, and the session
was destroyed.

Validation: the session's tool replies and screenshots above, plus
`uv run python -m unittest tests.test_host_screen` for the note change.

## 2026-11-11 — F2 browser dataset edit, and clicks under a modal

**Clicks under a modal hit the modal.** The browser bridge clicked at the
element's centre, so whatever lay on top took the click, and the reply still
reported the intended element as clicked. Found in the first F2 trial: an Edit
click behind the session-expiry modal landed on its "Sign out" button. A probe
reproduced it (a click on `#under` ran `#over`'s handler). `click` and `fill` now
hit-test the element's centre after scrolling it into view, and refuse with
`covered: …` before any input when something else is there. A label for the
element, or the control a label is for, counts as the element; both custom-control
layouts (a styled span over a hidden checkbox, an input stretched over its label)
are tested. Regression tests in `test_browser`.

**F2 browser dataset edit (`test_dataset_workflow`).** A loopback service owns 44
records and serves 12 per page. The page source contains no records. The driver
reads only the page: it surveys every page from the first and edits the four
"Norvik" records by SKU through durable browser jobs. A near-duplicate supplier
("Norvika") and a duplicated product name are in the data. The evaluator reads
only the service: every field of every record against the initial snapshot by
ID, membership, and the submissions it received, so a duplicate or a bystander
submission fails. It is itself tested against known-wrong outcomes, from a
missed target to a sign-out.

- Trial 1: start on page 3, and the modal opens as the second save returns.
- Trial 2: a slow save, with the helper killed after the Save click was
  acknowledged. The record says `delivery_unknown`; the driver reconciles from
  the page and does not resubmit; the service received one submission.
- Trial 3 was held out: it first ran after the driver was written against
  trials 1 and 2, and passed. Its kill injection and the driver's
  reconciliation were then refined, so it is now a regular regression trial:
  start on page 4, the modal after the first save, delayed saves, and the helper
  killed with the dialog filled but not saved. The driver retries once, because
  nothing was submitted. Its second planned kill did not happen: that edit's
  first step was refused as `covered` by the modal, which the driver dismissed
  ("Stay signed in") before retrying.
- A job that completes is still reconciled from the page (waiting for the
  reload after the save) before any retry, so a slow re-render cannot cause
  a second submission.

Not covered yet: virtualised lists, viewport changes, disconnects and
agent-driven runs. The native document and mixed workflows remain.

## 2026-11-11 — Host launches on Lua Hyprland, and a stale take marker

**Host launches on Hyprland 0.57 with a Lua configuration.** `launch_on_host` sent
`hyprctl dispatch exec CMD`. A Hyprland that reads its configuration from Lua parses
dispatches as Lua and refuses that form ("')' expected near …"). Its exit status can
still be 0, so the launch was reported as done. This was found in a nested Hyprland
0.57.1 stand-in, the version on the maintainer's machine. The worker now retries as
`hl.dsp.exec_cmd("…")` when Hyprland asks for Lua (nothing ran the first time), and
treats any answer other than `ok` as a failure. Checked in the nested stand-in,
including a path with a space, and in unit tests. Host launches, and X10's URL
fallback, depend on this.

**A stale `take-requested` marker** (from #185) made every later browser wait stop
with `HumanControl`. A `take` refused for a bad keyboard name left it behind, and so
would a client that died after writing it. This was reproduced. The worker now
clears the marker as soon as it receives `take`, ignores a marker older than 10 s, and
removes it when it starts. Regression test in `test_takeover_jobs`.

**Takeover still waits for other long commands.** Only browser waits give way at once.
An `open` (navigation up to 60 s), a `send` to a command (up to 60 s) or a long `type`
still holds `take` back until it finishes. The capability matrix says so.

**Fedora flake.** In Checks run 43089078794, Fedora's
`test_chromium_receives_every_character` dropped the first character ("rowser café…")
and passed on rerun. This is the first-character drop the pilot once saw on Fedora.
Plan row X12 is to loop it locally under load with the store's Chromium.

## 2026-11-11 — Takeover during a running job (F1-b, #181)

New `tests/test_takeover_jobs.py`: a person takes control while a durable browser job
is in a 3 s pause. Before the fix, `take` was acknowledged after 3.1 s. The worker
serves one request at a time, so `take` waited for the pause to end, and it could wait
up to a minute behind a browser `wait`. Now `core.request` writes `take-requested` in
the session's runtime directory before sending `take`, and browser waits in the worker
check it every 0.1 s and raise `HumanControl`, which `take` clears. A durable job
records that step as `failed` with the reason, rather than `uncertain`, because
`HumanControl` is always raised before any input. Other worker errors after dispatch
stay uncertain, as R2 requires. A browser batch now stops with its completed prefix on
`HumanControl`, instead of failing as a whole. In the test, the click before the
takeover lands, nothing after it does, and the lease is released. Full desktop suite:
358 tests, 19 skipped. Waits in `desktop_actions` already poll from the client, so
`take` could get in between them before.

## 2026-11-11 — Wrong targets under interruption (F1-c, #181)

New test: a durable job bound to one tab is killed mid-wait, that tab is closed, and a
later job for the same context refuses with `target_lost`. It never acts on the tab
that is left, whose counter stays at 0. That R1 behaviour held already. The test showed
the refusal recorded as `uncertain`, and the job as `delivery_unknown`, although the
target lookup fails before any input. The worker's browser handler already turns every
error raised after it begins to act into an uncertain reply. So for browser jobs a plain
refusal (lost target, missing or ambiguous element, a person taking control) is now
recorded as a known `failed` step, and the job as `stopped`. GUI action jobs keep the R2
rule that a generic error after dispatch is uncertain, because their input can partly
run before the error.

## 2026-11-11 — Host screenshots settle, and URLs open without a bridge (X6, X10)

These were built without the person's screen. The maintainer was away and said to
use it if possible, but approving a host session on their behalf was not an option,
so stand-ins were used. Two changes:
- A host screenshot taken within 1 s of the agent's own input now waits up to 1 s for
  the screen to go quiet, as `settle` does. In the daily-use notes, one capture
  caught a workspace switch halfway.
- On a host session whose Firefox has no BiDi port, `desktop_browser open` with
  `new_tab` opens an `http(s)` URL as a new tab of the running Firefox, through
  `firefox --new-tab`, started outside the session like other host launches. The
  reply says the tab cannot be read or driven.

Validated with stand-in workers in `test_host_screen` (no host session, no real
screen): settling turns on only after recent input, and the fallback runs only for
web URLs in a new tab. Not yet seen on the real screen: how long Hyprland's
animations take to settle, and whether Firefox brings its window forward.

X5, focusing a window on another workspace, needs no change. In a nested Hyprland
0.57.1, in a GPU private session standing in for the person's screen, the runtime's
foreign-toplevel activation of a window on workspace 1, sent from workspace 2,
switched to workspace 1 and activated the window. The nested instance used the test
harness's minimal configuration, not the full desktop configuration.

## 2026-11-11 — Desktop subagent pilot (N10)

`scripts/benchmark.py` gains a subagent arm (`AGENT_DESKTOP_BENCH_SUBAGENT=benchmarks/agents/desktop.json`).
The main agent gets only the Task tool and no MCP server, and the desktop agent gets
its own MCP server and the profile's tools. Records now carry `main_context_tokens`
and `subagent_calls`. A four-run pilot on `hard-web-admin` and `real-inventory-cleanup`,
seed 1, cut main-context tokens 93–97% and cost about 75% at equal success, but
wall time rose 51–58%, so the gate was not met. Results and deviations are in
docs/research/2026-11-11-desktop-subagent-pilot.md. The full 42-run protocol was not
run.

## 2026-11-11 — F1 interruption boundaries (F1-a, #181)

New `tests/test_interruptions.py` kills a durable browser job's helper at each
boundary, using real private sessions with Firefox, and compares the record with the
page:
- **During application work:** a click whose page handler finishes 1.5 s later.
- **After a committed effect.**
- **Before evidence collection:** the checks never ran, so `verification` stays
  `unknown` with no checks.

A further test cancels during application work. All four pass on current `main`:
acknowledged steps stay acknowledged, the page's own work lands exactly once,
nothing is replayed, and reading the record again sends nothing. One observation, not
a defect: a cancel that arrives during a job's last step, a pause, ends `completed`
with `cancel_requested` set, because cancellation is checked between steps. The
test therefore has a step after the pause, and checks that it stays `pending`.
Interrupting during evidence collection itself is still untested; the window is too
short to hit without a fault-injection hook.

## 2026-11-11 — Events report live state only

Running `agent-desktop events` against the real state directory printed 16 events from
history, 13 `session_stopped` and 3 `session_failed`. A shell would have raised a
failure banner for each on every start, and a session destroyed with a request pending
kept that request in its record. The first look now reports only live state: running
sessions, their open requests and control, and a pending, unanswered host request.
Requests and control are ignored in ended sessions. A follower reads each ended
session once and then skips it. Following uses 0.14 s of CPU over 20 s against that
directory, mostly startup. `control_returned` no longer carries the login page's URL,
only whether the bridge restarted and the error's first line.

Also recorded: on 2026-11-11 the Ubuntu job of Checks run 43067317711 failed once on
`test_effects.RecorderTests.test_new_directories_are_watched`, the inotify
watch-count assertion. That code was unchanged in the stack under test, and the job
passed on rerun. The test is timing-sensitive on CI runners.

## 2026-11-11 — Secret sink hardening

Two gaps in `send` (N1), found in review. A `send` to a command used the default 30 s
transport budget, although the command may run for 60 s, so a slow command's reply
could be lost and reported uncertain. It now gets 90 s. If a second match appeared
between `send`'s count and its element lookup, the lookup's error listed the matches'
text. That error is now replaced by one that lists nothing. Also checked: destroying a
session during a login takeover does not go through `release`, so it never tries to
restart Firefox. Closing the viewer still releases control and restarts it. Unit tests
cover both fixes.

## 2026-11-11 — Events for shells and notifiers (X4, first version)

`agent-desktop events [--follow] [--session]` implements the contract in
docs/project/EVENT_CONTRACT.md. Without `--follow`, it prints the current state as
events and exits. With `--follow`, it then prints changes. It covers session
lifecycle, `human_requested` and `human_withdrawn` with N2's take and paste commands,
`control_taken` and `control_returned` (including a login's browser restart),
`host_requested`, `host_answered` and `host_expired` with approve and deny commands,
`operation_finished`, and `batch_stopped` and `step_uncertain` from new trace lines.
It reads `session.json`, the host request file, operation records and traces. The
worker now also persists `control.last`, so how control came back survives in the
manifest. The first version polls twice a second; it does not use inotify.

Validated with the full desktop suite on the managed runtime: 352 tests, 19 skipped.
Unit tests derive each event from fixture state. A real-session test follows the stream
as a separate process through create, a launched terminal titled with a planted string,
typing that string, request and withdraw, a durable job and destroy. The planted string
never appears in the output. The non-blocking wait for control from the 2026-10-15 list
is covered by following `control_returned`. The Quickshell consumer (L1) is next.

## 2026-11-11 — Desktop subagent: schema cost and protocol (N10, part one)

Measured the MCP tool list and server instructions. They come to 29 tools and 31,436
schema characters on `main` after #166–#175, against 29,290 before this batch. That is
about 7,900 tokens of fixed prefix by a four-characters-per-token estimate.
`desktop_browser`, `desktop_actions` and `desktop_wait` are the largest. The field
reports used 10–11 of the 29 tools. The A/B protocol
(docs/research/2026-11-11-desktop-subagent-protocol.md) and the subagent definition
(`benchmarks/agents/desktop.json`) are committed before any counted run. The run itself,
42 sessions, waits for the maintainer to agree a model budget.

## 2026-11-11 — Event and approval contract (X4, design)

Added docs/project/EVENT_CONTRACT.md. It lists the human moments that both field
reports lost time on, and where each one already exists in the runtime. It proposes
the smallest consumer contract: `agent-desktop events [--follow]`, printing JSON lines
derived only from state the runtime already writes, with N2's printed commands and the
trace's rule of no content. Answers keep using the existing `take`, `release` and
`host approve`/`deny` verbs. Design only; nothing is implemented yet.

## 2026-11-11 — A killed operation helper gives back its lease (X1, first F1 patch)

The status read that finds a durable job's helper dead now undoes that job's lease,
as its own cleanup would have. A temporary lease is released, and a named caller's
lease goes back to the duration it had, which the helper now saves when it starts.
This happens only while the job's controller still holds the lease. The record's
`lease_cleanup` is `complete`, `not_held` or `unknown`. Nothing is replayed, and the
interrupted step stays `uncertain`. The existing helper-death test did not catch the
bug, because it read the page as the dead job's own controller.

Validated with a new real-session test, run with and without a named controller. The
helper is killed during a 30 s wait, another controller is refused before the kill,
and its input is accepted right after `status`. The named caller gets its 45 s lease
back. All 19 operation tests pass. Full desktop suite results are in the pull request.

## 2026-11-11 — F0 capability matrix (N9)

Added docs/project/CAPABILITY_MATRIX.md. It pins the environment, lists the cases
of each roadmap contract as tested, untested, missing or unsupported with their
tests, and names the first remaining F1 failure. That failure was reproduced: when a
durable job's helper is killed, `status` correctly reports `delivery_unknown`, but
the helper's 3600-second lease stays, and another controller is refused with
`LeaseHeld … 3597 s left`. The matching F0 items in the roadmap are ticked. One F0
item stays open: re-running each historical failure against current code. Documentation
only.

## 2026-11-11 — Account-aware cookie imports and forget-site (N6)

`import-cookies` now warns when it copies a site that keeps several accounts signed
in at once (Google, YouTube, Microsoft and GitHub domains), since the default account
in the session may be the wrong one. The warning points to the clean-profile
`--from` route. A heuristic count of accounts from the cookies was not attempted:
those cookie formats are not documented. The new `forget-site PROFILE --site SITE`
removes a site's cookies and its `storage/default` directories, for subdomains too,
and is refused while the profile is in use. History and the session store are left
alone.

Validated with fixture profiles: the warning appears only for a listed site, and
removal leaves other sites' cookies and storage, including a look-alike domain,
intact. Full desktop suite results are in the pull request.

## 2026-11-11 — hyprctl for a guarded session's nested Hyprland, and GPU Mesa (N8)

The guard's `hyprctl` shim now passes a call through when `XDG_RUNTIME_DIR` is the
session's own runtime directory and the target instance's sockets are there. A
Hyprland started inside the session keeps its sockets there; the host's does not.
Calls with another `XDG_RUNTIME_DIR`, or with a signature that is not under that
directory, are refused and logged as before. The test uses a stand-in `hyprctl` and a
fake instance socket, so no real Hyprland is contacted.

GPU sessions on NixOS: on this machine `test_renderer`'s gles2 case had been
skipping, because no node could start a GLES2 compositor. The full session log showed
`EGL_EXT_platform_base not supported`. The host profile sets
`__EGL_VENDOR_LIBRARY_FILENAMES` to the system Mesa (26.2.6), and the runtime's
libglvnd loaded it next to its own `mesa-libgbm` 26.1.3. With the variable unset, the
NVIDIA node (renderD129) started and the Intel node (renderD128) failed with `Failed to
create GBM device`. Pointing `__EGL_VENDOR_LIBRARY_FILENAMES` and `GBM_BACKENDS_PATH`
at the runtime pin's `mesa` (26.2.3) started the Intel node, and its screenshot
worked. The labwc binary also starts with gles2 when run directly under `env -i`.
USAGE.md now gives this recipe. Moving it into the runtime flake, for example as a
wrapper, is left for a later packaging change. Placing letters for a nested
Hyprland's layout through the parent labwc is still open (plan row X11).

## 2026-11-11 — Desktop size and enlarged crops (N4)

`create --size WIDTHxHEIGHT` and `desktop_create(size=...)` set a headless desktop's
size, from 640×480 to 3840×2400. The worker gives the single headless output a
custom mode through `wlr-output-management` before the pointer and applications
start, and `status` reports the size. Firefox otherwise opened 1280 wide on a
1920×1080 output, so a sized desktop also gets a labwc window rule that maximises
Firefox. The default stays 1280×720: a larger default would make every screenshot
bigger for tasks that do not need it. Cropped screenshots may now be enlarged up to
twice their size, and observation tokens map those coordinates back.

Validated on the managed runtime: a 1920×1080 session reports that size, whole
screenshots are 1920×1080, a 200×50 crop at scale 2 is 400×100, and Firefox's
viewport is wider than 1280. Full desktop suite results are in the pull request.

## 2026-11-11 — A login route that sites accept (N7)

`desktop_request_human(login=true)` changes what a takeover does with the bridged
Firefox. When the person takes control, the worker closes it through BiDi and
reopens the same profile at the same page without `--remote-debugging-port`, so
`navigator.webdriver` is false and sites such as Google do not refuse the sign-in.
On release, it closes that Firefox by its window, which saves its cookies (in the
first try, SIGTERM lost the newest cookie), and starts it again under the bridge.
`last.browser` reports the restart or the error. A request without `login=true`
while a bridged Firefox is open now carries a hint. The clean-profile
`import-cookies --from` route stays documented as the fallback.

Validated with a local HTTP page that reports `navigator.webdriver` on every load:
`true` under the bridge, `false` during the person's turn, and `true` again after
release. A cookie set during the turn is still present after the restart. A real
Google sign-in was not attempted. Full desktop suite results are in the pull request.

## 2026-11-11 — Commands that run as printed (N2)

Commands printed for the person (`take_command`, `paste_command`, `host approve` in
the approval notification, `host stop`, and the `import-cookies` instruction) now use
`agent-desktop` only when PATH outside the server's own virtual environment finds it.
Otherwise they use the installed script's absolute path. `uv run` puts that
environment on the server's PATH but not on the person's, which is why the cloud
report's maintainer got "command not found" twice. `AGENT_DESKTOP_CLI` overrides the
form, and INTEGRATIONS.md describes `uv tool install --editable` for the short form.

Validated with the full desktop suite on the managed runtime: 330 tests, 19 skipped.
`test_printed` runs the printed command with this environment's `bin` removed from
PATH, on a machine where `agent-desktop` is not otherwise installed, and it exits 0.

## 2026-11-11 — Richer browser find items (X7)

`find` items now carry up to four CSS classes and a `selector` that matches only that
element at that moment: its id if unique, otherwise a short child path from the
nearest ancestor with a unique id, checked with `querySelectorAll`. This was on the
2026-10-15 daily-use list ("richer `find` items for buttons"). The selector depends on
position, so it can change after the page changes. Validated with a real-Firefox fixture
of two identical Edit buttons: each gets its own `#admin > …` selector, and clicking
one of them works.

## 2026-11-11 — Activity counts stopped steps and fixed waits (N5)

Browser traces now record each batch step's action, and for waits their pause and
whether they wait for a condition. They never record selectors, text or URLs. Outcomes
record a batch stop as a category (`ambiguous`, `missing`, `disabled`, `wait_unmet`,
`deadline`, `target_lost`, `uncertain` or `other`). `activity` reports browser batches,
stopped batches by reason, uncertain deliveries, fixed and condition waits, and the
seconds spent in fixed waits. In the cloud report, the long session showed no errors
although 11 of its 53 batches stopped. The `desktop_browser` description now prefers
waiting for expected text after `open`. Batches of `desktop_actions` run on the client,
so they are not counted as batches.

Validated with a fixture trace and a real-Firefox batch stopped by an ambiguous click.
Full desktop suite results are in the pull request.

## 2026-11-11 — Clicks that change nothing on a toggle (N3)

A browser click on a checkbox, radio, `role=switch` or other `aria-checked` or
`aria-pressed` control, or on a label that controls one, now returns `toggle` with the
state `before` and `after` and whether it `changed`. In the cloud report, label clicks
on Tailscale's switches were reported delivered while the switches stayed off. The cost
is one more page-script call per click.

Validated with a real-Firefox fixture: a label click that the page cancels reports
`changed: false`, a switch reports `false` to `true`, and a plain button has no
`toggle`. A pre-click read that fails no longer stops the click (the optional before-state is then missing). Full desktop suite results are in the pull request.

## 2026-11-11 — Moving secrets without reading them (N1)

`desktop_browser` action `send` (CLI `browser SESSION send`) moves a value to a new 0600
file (`to_file`) or to a command's stdin (`to_command`) and replies with only its byte
count, SHA-256 and an optional prefix of up to 8 characters (`reveal`, default 4). The
source is one visible element's text, or a field's value, or with `source="clipboard"`
the session clipboard, which the runtime reads itself through data-control. Command
output is discarded, because a command could echo its input. Ambiguous matches are
refused without listing them, since the usual list shows the matches' text. With the
effect ledger on, the file is reported with `"content": "hidden"`, and the recorder
never reads or keeps its text. The server instructions now say to use `send` for
generated credentials. Clipboard and command destinations are for private sessions only.

Validated with the full desktop suite on the managed runtime: 329 tests, 19 skipped for
missing optional applications. The new real-Firefox test plants a key in a `<pre>`, sends
it to a file, to `tee` and, through a page Copy button, from the clipboard. It then
checks every file under the test's state and runtime directories, except the session
home and the page itself, and finds no copy of the key. A second session with effects on
reports the file as hidden. The CLI's browser command also kept dropping `0` values
(`--tab 0`); it now keeps them, since `--reveal 0` needs that. Limit: this keeps the
value out of the transcript and the runtime's records; it is not confinement from a
same-user shell.

## 2026-11-11 — Execution plan

Gathered everything planned or proposed into one execution plan at the top of
PROJECT_PLAN.md, in four tiers (Now, Next, Later, Parked) plus maintenance. The
sources were the cloud report's eight follow-ups and its scale and fixed-wait notes,
the residuals from the Hyprland report, the open items from the 2026-10-15 daily-use
list and the Hyprland report's note on opening URLs in the person's Firefox, roadmap stages F0–F3 with the R1–R6 limits, the M4 gate, directions D1–D10,
big-directions candidates B1–B5 and C1–C3, the human-interface slices and open product
decisions, the effect-ledger next steps, the remaining section 7 ideas, and the
wlroots and Fedora upkeep. Each item appears once, with its source, dependencies and
acceptance check or gate. The plan works on field follow-ups first, with the F0 audit running alongside them.

Status was checked in the source before items were called open. For example,
windows report their Hyprland workspace (#149), but focusing a window on another
workspace is still missing. Section 1 now follows the 2026-11-10 decision that
testing desktop software is in scope. On the directions board, D3 is marked
weakened (E2 and E3 missed their gates), and B1–B5 and C1–C3 are added as ideas.
The ten Now items (N1–N10) are grouped into three GitHub issues, #161–#163,
since the maintainer preferred a few issues to one per item. The maintainer accepted
the proposed defaults for all five questions.

Documentation only; no runtime tests were needed. Validation: a local check of
Markdown links and anchors in the changed files, and `git diff --check`.

## 2026-11-10 — Cloud setup field report

Reconstructed from transcripts how an agent used the MCP to set up a Google Cloud project
and Tailscale through their web consoles with imported logins:
docs/trials/2026-11-08-gcp-tailscale-setup.md (138 calls, 4 private desktops, 1 tool
error, 11 of 53 browser batches stopped early, one with uncertain delivery). Main
findings: generated credentials were read into the agent's transcript until it built its
own clipboard-to-file route, Google refuses sign-in in the BiDi-controlled browser so the
login handoff cannot succeed there, `import-cookies` copies every account on a site,
printed `agent-desktop` commands do not run when the CLI is not on PATH, label clicks
on switches were reported delivered with no effect, and 1280×720 is too small for some
console menus. No code was changed; the ranked follow-ups are in the project plan.

## 2026-11-08 — Activity summaries and field-report follow-ups

`agent-desktop activity` summarises action traces as counts only, so a report like the
Hyprland one no longer needs transcripts. Windows on a Hyprland host report their
workspace, matched by app id and title since toplevels and clients share no identifier.
With `screenshot=true`, a batch's held keys are released after the image.

The Checks matrix for #147 failed on Fedora while building the runtime, before any test
ran: `fedora:latest` no longer provides the wlroots 0.19 development package the repair
needs. Pinned the job to Fedora 44, the release the compatibility matrix records.

## 2026-11-08 — GPU desktops through the MCP and clearer host errors

`desktop_create` and `create` take `renderer` and `render_device`. A host desktop on a
terminal that is not showing now refuses input and screenshots with the reason, using
`XDG_VTNR` of the instance from its lock file against `/sys/class/tty/tty0/active`
(checked read-only against the live session; refusal itself is unit tested). Tool timeouts
no longer expose the command line. Screenshots with a locker or display off carry a
warning, `screenshot=true` without a token reuses the session's last whole-screen scale,
and activity refusals mention input from programs outside these tools.

Validated with the desktop suite on the managed runtime: 321 tests, 19 skipped for missing
optional applications. A real `create --renderer gles2 --render-device /dev/dri/renderD128`
reported that renderer in `status` and a bad renderer was refused. No real host session
was used; the off-screen refusal has not been seen on a real inactive terminal.

## 2026-11-08 — Real key sequences and layout-aware shortcuts

Chords now press and release real modifier keys, `desktop_actions` gains `key_down` and
`key_up`, and `modifiers` accepts the same aliases as chord syntax. Held keys are released
when a run ends, when a person takes control, at cleanup and after 30 s without a client.
On a Hyprland host, keys are placed for the configured layout, read through `hyprctl`.

Validated against nested Hyprland 0.57.1 set to Dvorak in a guarded private session.
Directly connected: `logo+l/n/o/r/c/j/d/e/minus/bracketleft/1/Tab` and
XF86AudioRaiseVolume each fired their own bind, and a SUPER tap fired a release bind.
Through `agent-desktop key` and the parent labwc: `logo+1` and `logo+Tab` now fire, which
was the nested failure in the field report; letters there still use US positions, since
private sessions do not detect a nested compositor. A held SUPER with Tab fired through
`agent-desktop actions`. No real host session was used; layout placement on a host was
tested by pointing the worker's option reader at the nested instance.

## 2026-11-08 — Hyprland overhaul field report

Reconstructed how agents used the MCP during the Hyprland overhaul from transcripts:
docs/trials/2026-11-07-hyprland-overhaul.md (233 calls, 32 desktops, 2 errors). The
main failure, shortcuts landing on the wrong key under a non-US layout, was reproduced
with the unchanged `VirtualKeyboard` against a nested Hyprland 0.57.1 set to Dvorak in
a guarded private session: `logo+l` fired SUPER+n, `logo+o` fired SUPER+r. No host
session was used for that test.

## 2026-11-06 — Evidence round

Protocol committed before the runs: docs/research/2026-11-06-evidence-protocol.md.

- wlroots stock vs repaired, 1000 shuffled pairs under load: 15/972 failed on
  stock against 0/1000 repaired (Fisher p = 2.3e-5), or 17/1000 against 0/1000
  without the integrity exclusion (p = 1.4e-5). See evidence/WLROOTS-RESULTS.md.
- Effect atlas: galculator, xed and pluma added, with negative controls writing
  nothing: 47 run, 0 false passes (docs/research/effects/atlas-*-20261106.json).
- Tier suite: six harder tasks over three seeds and three model tiers gave 15/18,
  17/18 and 18/18 (not significant). See evidence/TIER-RESULTS.md.

Also recorded that wlroots!5477 was closed unmerged.

Post-merge review of #142 recomputed the wlroots, atlas and tier figures from the
raw records; they hold, with these corrections. The tier p-value is 0.23, not
about 0.24, and haiku's median is 22.5 turns over the 16 runs that reported turns.
Two of haiku's three failures were `desktop_request_human` handoffs that waited
for the 900 s timeout with no cost reported, so bulk-entry separates willingness
to use a noted password as much as ability (evidence/TIER-RESULTS.md). Every
benchmark tool profile now disables `desktop_request_human` and `desktop_control`.
Unreported protocol deviations are now listed in evidence/ATLAS-RESULTS.md and
evidence/TIER-RESULTS.md. Validated the merged PR head with 305 tests on the
managed runtime: 286 passed, 19 skipped for missing optional applications, tier
controls included. Also updated certifi for GHSA-6q48-6c7w-9gw2 (#143).
