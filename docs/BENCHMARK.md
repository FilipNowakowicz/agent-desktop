# GUI task benchmarks

Recorded experiments cover fixture completion, tool usage and cost in specific
environments. They do not establish broad daily-use reliability or a general
performance winner. See [compatibility](COMPATIBILITY.md) for tested versions and
[validation](VALIDATION.md) for non-model smoke tests.

Start with the task and limits sections, then the native/container and tool-profile
comparisons. Committed aggregate metrics are in
[`benchmarks/results`](../benchmarks/results). Detailed local artifacts named by
run ID may not be included in the repository. Model-driven runs use the operator's
configured account; obtain an agreed scope and budget before running them.

`scripts/benchmark.py` runs 20 representative tasks (`benchmarks/tasks.py`) with
Claude Code as the agent. For each task the harness creates a fresh headless
session, launches the application and waits for its window. It then runs
`claude -p` with **only** the private-desktop MCP tools (`--tools ""`, strict MCP
config, $1 cap per task). The outcome is verified independently: window titles set by
the page, files on disk, or a dialog's stdout and exit code. The agent's reply is
not trusted. After each task the session is destroyed and checked for leftover
processes.

```sh
# Runtime tools and the apps must be on PATH; on NixOS, for example:
nix shell nixpkgs#labwc nixpkgs#grim nixpkgs#foot nixpkgs#xwayland nixpkgs#xterm \
  nixpkgs#zenity nixpkgs#kdePackages.kdialog nixpkgs#chromium nixpkgs#mousepad \
  --command uv run scripts/benchmark.py            # all tasks (uses your Claude account)
uv run scripts/benchmark.py --dry-run               # setup + checks, no agent
uv run scripts/benchmark.py --only zenity-scale     # selected tasks
uv run scripts/benchmark.py --suite office --dry-run # two office tasks, no account use
```

`--dry-run` is the negative control: every check must fail when no agent acts.
It did for all 20 tasks (apps launched, windows appeared, cleanup clean).

The office suite adds Writer document creation and Calc formula entry. It checks
the saved ODT paragraphs and the ODS formula, value and preserved inputs using the
same independent verifiers as the real-application smoke tests. Its negative
control failed both checks with no errors or cleanup failures
(`20261004-144149-180e`). The workflows include first-run dialogs for the agent
to handle; successful scripted smoke tests do not establish agent completion.

New runs explicitly disable desktop create, destroy and launch tools: applications
are already loaded by the harness, and tasks must use GUI input to change them.
Earlier recorded runs used the broader MCP tool set, so compare tool access as
well as model, application versions and task definitions when measuring changes.

## Tasks

| Application | Tasks |
| --- | --- |
| Chromium (native Wayland) | code read from a canvas plus drag into a target; form (text, select, radio, checkbox); off-screen button; `confirm()` dialog; code from a second tab; range slider to an exact value; custom context menu; double-click cell edit; Ctrl+K hidden search; drag reordering |
| foot | create a file through the shell |
| xterm (Xwayland) | create a file named after a code shown only in the window title |
| mousepad (GTK 3) | type two lines and save via the save dialog |
| zenity (GTK 4) | radio list, multi-field form, file chooser navigation, calendar date, scale value |
| kdialog (Qt 6) | combobox, checklist |

## Results, 2026-10-04 (NixOS, Claude Code 2.1.288, claude-opus-5-5)

| Run | Passed | Tool calls | Tool errors | Agent seconds | Cost (USD) | Cleanup failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 `20261004-013620-d3f8` | 19/20 | 233 | 0 | 393 | 2.24 | 0 |
| 2 `20261004-021510-4cd6` | 20/20 | 149 | 0 | 348 | 1.78 | 0 |
| 3 `20261004-022211-1f4f` | 20/20 | 154 | 0 | 322 | 1.81 | 0 |

| Task | Run 1: pass / calls | Run 2 | Run 3 |
| --- | --- | --- | --- |
| chromium-canvas-code-drag | pass / 7 | pass / 7 | pass / 7 |
| chromium-form | FAIL / 24 | pass / 11 | pass / 11 |
| chromium-scroll | pass / 10 | pass / 10 | pass / 10 |
| chromium-confirm-dialog | pass / 5 | pass / 5 | pass / 5 |
| chromium-second-tab | pass / 9 | pass / 9 | pass / 9 |
| chromium-slider | pass / 14 | pass / 7 | pass / 7 |
| chromium-context-menu | pass / 5 | pass / 5 | pass / 5 |
| chromium-double-click-edit | pass / 8 | pass / 8 | pass / 9 |
| chromium-keyboard-shortcut | pass / 39 | pass / 7 | pass / 7 |
| chromium-drag-reorder | pass / 9 | pass / 7 | pass / 7 |
| foot-shell-file | pass / 3 | pass / 3 | pass / 3 |
| xterm-title-code | pass / 4 | pass / 4 | pass / 4 |
| mousepad-save | pass / 9 | pass / 9 | pass / 12 |
| zenity-radio-list | pass / 7 | pass / 10 | pass / 8 |
| zenity-forms | pass / 10 | pass / 10 | pass / 10 |
| zenity-file-chooser | pass / 10 | pass / 8 | pass / 11 |
| zenity-calendar | pass / 8 | pass / 8 | pass / 8 |
| zenity-scale | pass / 38 | pass / 6 | pass / 7 |
| kdialog-combobox | pass / 7 | pass / 7 | pass / 7 |
| kdialog-checklist | pass / 7 | pass / 8 | pass / 7 |

Between runs 1 and 2:

- **Fixture bug:** the form input had `id=name`, which `window.name` shadows in
  page scripts, so the task was impossible. Fixed in the fixture; this was not
  an agent failure.
- **Runtime bug found by the agent:** in the Ctrl+K task the agent got
  `privatdesktop` and reported "space acts like Backspace". The virtual keyboard
  had put space on evdev code 14 (physical Backspace), which Chromium honours.
  Fixed by the physical US keymap (PR #20); the task went from 39 to 7 calls.
- **Tool gap:** moving a GTK scale took 32 single `Right` key calls. `key` now has
  `repeat`; the task went from 38 to 6 calls.

## Limits

- One model, one machine, three runs. These are measurements of this setup, not
  general reliability claims.
- The suite has saturated (40/40 in the last two runs), so it no longer
  distinguishes improvements by pass rate. Harder, multi-application and
  longer-horizon tasks are needed. Tool calls, time and cost remain useful.
- Applications are launched by the harness. Tasks start from a known state and do
  not test the agent's own launch decisions (`scripts/claude_code_task.py` covers
  create and launch).
- No baseline comparison with other computer-use runtimes has been run yet.

## Hard tasks

Goal: tasks the current suite cannot express, to measure where the agent and
runtime still fail. Agent runs use the user's Claude Pro allowance (`claude -p`
signs in with claude.ai), so each task is first validated with `--dry-run`.

Status checklist (update after each step):

- [x] Task definitions in `benchmarks/hard.py` (10 tasks), selectable with `--suite hard`
- [x] Dry run: all 10 hard checks fail with no agent, apps launch, cleanup clean
  (`20261004-023751-0e0c`); all 17 fixture page scripts pass `node --check`
- [x] Agent run of the hard suite (once), results recorded below
- [x] Failures analysed: none in this run (see below)

`uv run scripts/benchmark.py --suite hard` (`benchmarks/hard.py`):

| Task | What makes it harder |
| --- | --- |
| hard-terminal-to-browser | value read in a terminal window, entered in a browser |
| hard-web-admin | sign-in, navigation, a 40-row table, edit page, confirmation |
| hard-interrupting-modal | an expiry modal interrupts typing and steals focus; "Sign out" fails the task |
| hard-slow-load | result appears only after 7 s |
| hard-chart-reading | answer exists only as bar heights in a canvas |
| hard-editor-open-edit | open a nested file through the GTK open dialog, edit one line, save |
| hard-terminal-rename | batch rename with zero padding in a shell |
| hard-compare-two-windows | compare lists in two editor windows, answer in a third (dialog) |
| hard-focus-steal | a warning dialog grabs focus 6 s into typing a long message |
| hard-validation-fix | read a validation error and correct the order |

Run `20261004-023853-8b72` (2026-10-04, Claude Code 2.1.288, claude-opus-5-5):
**10/10 passed**, 121 tool calls, 0 tool errors, 219 s, $1.24 (API-equivalent;
billed against the user's Claude Pro allowance), no cleanup failures.

| Task | Result | Tool calls | Seconds | Cost (USD) |
| --- | --- | ---: | ---: | ---: |
| hard-terminal-to-browser | pass | 12 | 19.3 | 0.126 |
| hard-web-admin | pass | 23 | 29.0 | 0.215 |
| hard-interrupting-modal | pass | 16 | 40.6 | 0.148 |
| hard-slow-load | pass | 10 | 22.4 | 0.128 |
| hard-chart-reading | pass | 5 | 11.6 | 0.06 |
| hard-editor-open-edit | pass | 18 | 23.5 | 0.161 |
| hard-terminal-rename | pass | 5 | 11.8 | 0.076 |
| hard-compare-two-windows | pass | 9 | 16.9 | 0.1 |
| hard-focus-steal | pass | 13 | 29.4 | 0.136 |
| hard-validation-fix | pass | 10 | 14.3 | 0.091 |

These tasks also did not separate pass from fail for this model. Future
benchmark work should measure efficiency (calls, time, cost) and compare
baselines or weaker models, rather than only adding difficulty. One run per task;
no repeatability claim.

## Office tasks

Run `20261004-144403-9eec` (LibreOffice 26.8.0.3, claude-opus-5-5): 2/2 passed,
20 tool calls, no tool errors, 37.5 agent seconds and $0.264 API-equivalent usage
against the existing Pro allowance. No cleanup failures. This run explicitly
disabled desktop create/destroy/launch tools and used a $1 cap per task.

| Task | Result | Tool calls | Seconds | API-equivalent USD |
| --- | --- | ---: | ---: | ---: |
| office-writer-document | pass | 13 | 22.8 | 0.181 |
| office-calc-budget | pass | 7 | 14.7 | 0.083 |

The agent handled the first-run UI and saved files that passed independent checks.
This is one run of two small tasks, not a broad office-application reliability
claim or a comparison with another runtime.

## Local container baseline

`scripts/cua_benchmark.py` reuses the canvas-code/drag, form and confirmation
fixtures in fresh local Cua containers. Install Cua and provide an already
configured Docker-compatible local Unix socket. The harness does not install a
runtime, alter host configuration, open a viewer or use a cloud account. It
pins the Linux image digest in source; a rootless Podman pilot used CLI 0.3.1.
See [Cua local runtimes](https://cua.ai/docs/cua-sdk/guides/local-runtimes).

```sh
# DOCKER_HOST must identify the intended local engine's Unix socket.
# --engine must connect to that same engine/storage; it copies fixtures and verifies titles.
uv run scripts/cua_benchmark.py --cua /path/to/cua --engine podman \
  --state-dir artifacts/cua-state --only chromium-canvas-code-drag --seed 41027 --dry-run
uv run scripts/benchmark.py --only chromium-canvas-code-drag --seed 41027 --dry-run
```

Replace `--dry-run` with an explicit `--model` and `--budget` for account-using
runs. The native and container pilot negative controls both failed their check
with no setup/cleanup errors: `20261004-151706-01ca` and `20261004-151705-1f13`.
Their generated page hashes match. Native summary records the randomized seed.

The container's model interface passes through `scripts/cua_gui_mcp.py`, which
allows only 18 GUI tools and forces an explicit `local:<name>` target. Shell,
file operations, launch, accessibility and session management are absent;
caller-supplied target overrides are rejected. Tool content/errors pass through.
This is a restricted Cua interface, not its full capability set. The harness
checks task-set titles directly through the guest's X11 properties, independently
of model replies and MCP window metadata, then verifies container deletion.

The environments differ: native labwc/Wayland with Chromium 153.0.8010.52;
Cua's Ubuntu 24.04.5/XFCE/Xvfb container has Chromium 154.0.8037.92. Its screenshot
is capped at a 1200 px long edge; the native image is 1280x720. The container is
limited to 2 CPUs/2 GB and runs its browser as guest root with `--no-sandbox`
inside rootless host Podman. The native runtime has no matching resource cap.
A small pilot can compare observed outcomes and tool usage; these differences
and model variability prevent attributing timing or cost to tool design alone.

Paired pilot, 2026-10-04, seed 41027, claude-opus-5-5, $1/task cap:

| Interface | Run | Verified | Calls / errors | Agent time | API-equivalent usage |
| --- | --- | --- | --- | --- | --- |
| Native private desktop | `20261004-151912-01e9` | 1/1 | 7 / 0 | 13.0 s | $0.0803638 |
| GUI-only Cua | `20261004-151945-3d34` | 1/1 | 7 / 0 | 12.2 s | $0.1037486 |

Both used three screenshots, two clicks, one type and one drag. Saved transcripts
show the intended GUI actions; final screenshots and independent title checks
agree. Generated pages are identical, and both sessions/containers were removed.
Container startup took 16.2 s with a cached image and VFS storage; native startup
was not timed. Agent time excludes fixture startup and final harness checks.

Transcript token counters (input / cache creation / cache read / output) were
native `8 / 7495 / 30659 / 712` and Cua `8 / 11080 / 24183 / 512`. Future records
retain raw usage and per-model accounting. Differences in caching, schemas,
images, desktop environment and one stochastic run prevent attributing the
cost difference to any single component. This sample establishes comparable
completion and equal tool calls; it does not establish a performance winner.

## Repeated three-task comparison

The user authorized up to $5 API-equivalent total, including the first pair.
Two sets cover code-and-drag, form filling and confirmation on each runtime;
the second code uses seed 41028 (first: 41027). The ten additional task runs
used $0.40 caps. Actual total was **$1.0474778**. All six native/container page
pairs match byte for byte. Three-task negative controls failed every check
without setup/cleanup errors (`20261004-153446-bedd`, `20261004-153700-9597`).

| Interface | Verified trials | Calls / tool errors | Agent time total | API-equivalent usage |
| --- | --- | --- | --- | --- |
| Native private desktop | 6/6 | 46 / 0 | 104.7 s | $0.5183458 |
| GUI-only Cua | 6/6 | 49 / 0 | 84.0 s | $0.5291320 |

[Committed metrics](../benchmarks/results/2026-10-04-browser-comparison.json)
retain per-trial outcomes, tool counts, usage counters, screenshot dimensions,
page hashes, seeds, caps and source artifact IDs. The later batches are native
`20261004-153647-ba09`, Cua `20261004-153931-af37`, native
`20261004-154125-494e` and Cua `20261004-154321-3049`. All trials cleaned up.
Source preparation and each batch's results were committed separately.

Code-and-drag uses 7 calls and form filling 11 on both interfaces in both sets.
Confirmation uses 5 calls natively and 6/7 in Cua. Both perform the intended
single confirmation; Cua takes extra screenshots while the dialog and completed
page render. In the second Cua trial, observation 2 is dimmed with no drawn
prompt, observation 3 shows the prompt, and a later observation confirms the
completed title. The original images were inspected. Extra observations are
not tool API errors or repeated deletion actions.

Observed costs are nearly equal. Tool counts match except for confirmation
observations; timing varies even at identical call counts. Only three fixtures,
two trials each, different environments and cache counters are covered. Native's
first form/confirmation batch also overlapped container dry setup. These results
support neither a general performance winner nor a decision to replace the
runtime. Widget/frame readiness and broader daily-use tasks need measurements
before choosing further interaction extensions.

## Tool profile comparison, 2026-10-04 (claude-opus-5-5, accessibility on in both)

`--tools basic` disables wait, actions and semantic UI; `--tools full` allows them.
Two rounds, seeds 7 and 8. Results: `benchmarks/results/2026-10-04-tool-profiles.json`.

| Suite / profile | Passed | Tool calls | Cost (USD) | Total tokens |
| --- | --- | --- | --- | --- |
| hard basic | 10, 10 | 126, 125 | 1.13, 1.13 | 0.78 M, 0.78 M |
| hard full | 10, 10 | 79, 80 | 1.09, 1.06 | 0.91 M, 0.88 M |
| standard basic | 20, 19 | 157, 143 | 1.50, 1.48 | 0.94 M, 0.85 M |
| standard full | 19, 20 | 128, 120 | 1.62, 1.58 | 1.29 M, 1.25 M |

Full tools cut calls by ~37% (hard) and 15-18% (standard). Standard cost rose 5-9%:
Chromium UI listings were 10-13 K characters and stayed in context. Fixes after
round 1/2: registry readiness before `ready` (an app launched immediately was
invisible), coordinates follow scaled/cropped screenshot tokens (the round-1
full failure clicked image coordinates on a half-scale screenshot), `wait`
accepts `seconds`, and listings became compact text with short ids (3176 -> 1419
characters for a form page).

Round 3 (seed 9, full tools only, after the fixes and compact listings; the
first attempt hit the Claude session limit and was discarded):

| Suite | Passed | Tool calls | Cost (USD) | Total tokens | Run |
| --- | --- | --- | --- | --- | --- |
| standard full | 20/20 | 129 | 1.41 | 1.19 M | `20261005-000847-8fe7` |
| hard full | 10/10 | 81 | 0.89 | 0.78 M | `20261005-001522-1b6f` |

Fewer tool calls with full tools held in every round. Cost was higher with full
tools in the matched seeds 7/8; the single post-fix full-only round (seed 9) cost
less than the older basic rounds, but there is no contemporaneous basic seed-9
run, code and listings changed in between, and differences of a few percent are
within the variation seen between rounds. A net cost advantage is unconfirmed.
