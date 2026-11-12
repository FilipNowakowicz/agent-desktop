# Development log

Entries are newest first. This file holds November 2026. Earlier months are kept
verbatim in [log/2026-10.md](log/2026-10.md). The older narrative of the
[project plan](PROJECT_PLAN.md) is in
[archive/PROJECT_PLAN-history.md](archive/PROJECT_PLAN-history.md).

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
