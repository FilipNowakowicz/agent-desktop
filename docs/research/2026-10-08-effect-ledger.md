# Effect ledger and effect induction: research notes

Research date: 2026-10-08. Baseline: `main` at `78c3de1` (#88). Status: an
experimental prototype behind `AGENT_DESKTOP_EFFECTS=1`, scripted scenarios,
an effect-induction demonstration and a small agent A/B. Not a supported
feature; numbers below are from this machine and these tasks only.

## Question

Agents verify their desktop work by looking at screenshots. The runtime owns
each private session: its home directory, process tree and windows. Can it
report what an action actually changed, so an agent checks facts instead of
interpreting pictures, and does that make agents more reliable or cheaper?

## Summary

- **The ledger works on real applications.** Six scripted scenarios with
  foot/zsh, Mousepad, Thunar, LibreOffice Calc and Firefox behaved as written
  down beforehand, including the two pilot failure types: a setting that was
  shown but never saved (pilot session 15: nothing written) and a save that did
  not finish (Calc's "Keep current format" dialog: dialog opened, no file).
- **Spreadsheet changes become exact.** OpenDocument files are unpacked into
  canonical lines, so editing one cell and saving reports
  `-Sheet1!B2: 3`, `+Sheet1!B2: 7`, `-Sheet1!D2: 12 [formula]`,
  `+Sheet1!D2: 28 [formula]`: the cell, the recalculated formula and nothing
  else, in about 60 tokens.
- **It is cheap.** Median report about 9 tokens (90th percentile 161) against
  about 1,229 for a full 1280×720 screenshot; +28 ms median per action
  (227 → 255 ms over 80 actions).
- **It found a real bug in a minute.** A typed shell command wrote an empty
  file and the history said `cho hello`: zsh's first-run menu took the first
  key in every fresh session. Fixed in #89; the pilot had never used a terminal.
- **Effect induction worked.** Turning Calc's AutoInput off once through the
  menu produced one configuration line; writing only that line into a fresh
  profile made Calc's own menu show AutoInput unchecked, while a control
  profile showed it checked. A GUI demonstration became a direct, checkable
  state change.
- **It made a real agent cheaper.** Claude Code on five file-producing tasks
  used 25% fewer input tokens with the ledger (permutation test p = 0.016,
  15 vs 15 runs), with large drops where the outcome is a file (Calc formula:
  13 → 4 turns, $0.141 → $0.072) and none where the work is visual navigation
  (CSV export dialogs). Every run succeeded in both arms, so reliability was
  not tested by these tasks.
- **A generated settings map works on a small scale.** Toggling Calc's View
  menu items in disposable profiles and diffing against controls mapped all
  four items that have profile settings to their configuration entries, each
  verified by applying it alone; the other four were correctly found to be
  per-document settings.

## Prior art (checked 2026-10-08)

| Work | What it does | Difference from this prototype |
| --- | --- | --- |
| [VisCritic](https://arxiv.org/pdf/2606.24525), [action-induced visual differences](https://arxiv.org/pdf/2608.24015), [Don't Act Blindly](https://arxiv.org/pdf/2604.05477) | Compare screenshots before/after an action, or predict and check an expected visual effect | Visual evidence only |
| [Effect contracts proposal](https://github.com/Unjuno/agent-interface/issues/34) | Each action declares a postcondition; runtime reports VERIFIED/CONTRADICTED/UNKNOWN | Open proposal, unimplemented; evidence sources unspecified. The ledger is an evidence source such contracts need |
| [Agent-Warden](https://arxiv.org/abs/2609.38245), [AgentSight](https://arxiv.org/html/2508.02736v2) | eBPF process/file provenance for LLM agents | Monitoring of command-line agents; not fed back to a GUI agent per action |
| [AgentTrace](https://arxiv.org/html/2603.28551) | Post-hoc trace views (files, permissions) for people | Mock-up for users after the task, not the agent during it |
| [YOLO-files filesystem](https://dl.acm.org/doi/pdf/10.1145/3830418.3843858), [DeltaBox](https://arxiv.org/html/2605.22781v1), [TClone](https://arxiv.org/pdf/2605.17320) | Staging, snapshots, rollback, forking | Isolation and undo rather than per-action reporting |
| [Agent-Diff](https://arxiv.org/pdf/2602.11224), [OpenComputer](https://arxiv.org/html/2605.19769), [LegacyWorld](https://arxiv.org/pdf/2608.14131) | State diffs and direct state inspection to *score* runs | Evaluation after the run, task-specific verifiers |
| [Observation interfaces (AOI)](https://arxiv.org/abs/2606.29472) | Continuous keyframes and narration between steps (browser) | Visual stream, not OS effects |
| [PrefFinder](https://cse.unl.edu/~myra/papers/prefFinder.pdf) (FSE 2014) | Natural-language search for preference names via documentation | Static, application plugin; names GUI→`registrymodifications.xcu` traceability as the hard part, which effect induction measures dynamically |
| [EchoPath](https://arxiv.org/pdf/2609.16635), [UI-Mate](https://arxiv.org/pdf/2608.15930), [UFO hybrid API](https://arxiv.org/pdf/2503.11069) | Replay trajectories, demonstrations as guidance, hand-written API shortcuts | Actions or curated APIs, not effects learned from a demonstration |

Searches did not find per-action, OS-level effect reports returned to a GUI
agent, nor learning a GUI step's state effect and applying it directly. That is
absence from the searched literature, not proof of novelty.

## Design of the prototype

`src/agent_desktop/effects.py`, enabled per session with
`AGENT_DESKTOP_EFFECTS=1` (optionally `AGENT_DESKTOP_EFFECT_DIRS` for more
directories):

- **Files.** inotify on the session home (and extra directories); events are
  timestamped. Small UTF-8 files are kept (32 MB budget) so a change is a line
  diff; OpenDocument files become `Sheet!Cell: value [formula]` or paragraph
  lines. Paths created and removed within the window, caches, locks and
  journals are counted as `noise_files`.
- **Documents vs application state.** Paths with a dot-directory component are
  `app_state`, shortened to two diff lines, and collapsed to per-directory
  counts beyond eight files (a browser profile starting).
- **Windows and processes.** Window lists and the session's process set are
  compared before and after each input, launch, focus and `ui_action`.
- **Late effects.** A reply waits until file events have been quiet for 0.15 s
  (at most 0.6 s). Later writes are read with the `effects` operation
  (`effect_id`), and `wait_effect` / `desktop_effects(wait_for_file=...)` waits
  for a matching file to be written and go quiet, instead of polling with
  screenshots.

## Scripted scenarios

`scripts/effects_experiment.py`; results in
[`effects/scenarios-20261008.json`](effects/scenarios-20261008.json). Each
expectation was written before running.

| Scenario | Expectation | Result |
| --- | --- | --- |
| terminal-write | Command writes a file; append shows the line | Shown. Also exposed the zsh first-run bug |
| editor-save (Mousepad) | Save dialog opens; file created with its text; typing writes no document | Shown; the file arrived about 1–2 s after Return, via `wait_effect` |
| file-manager-hidden-files (Thunar, pilot 15) | Ctrl+H saves nothing without xfconfd | Shown: no settings file in 3 s |
| calc-save-and-format-dialog | `.ods` created; `.csv` opens "Keep current format", no file | Shown |
| calc-cell-diff (pilot 20 shape) | Cells listed after save; one edit shows that cell and the formula | Shown, exact diff |
| browser-start-noise (Firefox) | Startup noise stays a count or a short list | 513 noise files counted; application state list was long (fixed by per-directory collapse after this run) |

### Findings from the scenarios

1. **Applications write state continuously.** Mousepad saves session state on
   every keystroke; LibreOffice writes Java settings at launch and its whole
   configuration on the first change. "Nothing written" must mean "no document
   written", with application state reported separately.
2. **Effects are asynchronous.** Saves landed 0.4–2 s after the key that caused
   them, and dialogs sometimes opened after the reply. A fixed observation
   window is wrong either way (too short misses effects; too long slows every
   action). Waiting on a named effect is the right primitive.
3. **Delivered is not received.** The terminal case shows input reported as
   delivered while the application consumed it differently. The ledger exposed
   it as a 0-byte file without any screenshot.
4. **Temporal attribution is not causal attribution.** Calc created its 25 KB
   configuration at the first change, so the click's "effect" was a whole file.
   Isolating the AutoInput line needed a name match. A general method needs a
   counterfactual: identical steps with and without the change, then a diff of
   the two end states.
5. **Binary state stores hide effects.** dconf (`~/.config/dconf/user`) and
   SQLite databases show as size changes only. Decoders (dconf dump, row diffs)
   would be needed for GNOME settings and browser data.

## Effect induction

`scripts/effect_induction_demo.py` (run once on 2026-10-08, LibreOffice
26.8.0.3 from nixpkgs):

1. Profile A: Tools > AutoInput was `checked`; clicked through accessibility;
   Ctrl+Q flushed the configuration.
2. Learned line:
   `<item oor:path="/org.openoffice.Office.Calc/Input"><prop oor:name="AutoInput" oor:op="fuse"><value>false</value></prop></item>`
3. Profile B: default configuration created, that line inserted, Calc opened:
   AutoInput **not checked**. Profile C (control, no change): **checked**.

Why it matters: action replay breaks when menus move, dialogs appear or
coordinates change; the effect (one configuration item) does not. The ledger
verifies the replayed effect the same way it observed the demonstration. A
person's takeover demonstration could become such a procedure.

Limits: the application must be closed when its configuration is written (it
overwrites on exit); formats and keys change between versions; effects outside
files (memory, dconf binary, remote services) are not captured; and replaying
a state change skips whatever else the GUI would have done (validation,
migrations), which is unsafe for anything beyond simple settings.

### A generated settings map (first test)

Disposable sessions make differential exploration cheap. `scripts/settings_map.py`
toggles each checkable item of Calc's View menu in a fresh profile, compares
the configuration after quitting with two untouched controls (lines differing
between the controls would be noise), and verifies each learned effect by
writing only those lines into another fresh profile and reading the menu
state. Results: [`effects/settings-map-calc-20261008.json`](effects/settings-map-calc-20261008.json),
8 items in 5.8 minutes.

| Item | Learned | Verified by applying alone |
| --- | --- | --- |
| Formula Bar | window-state item for the formula bar | yes (unchecked) |
| Status Bar | status bar visibility item | yes (unchecked) |
| Column/Row Highlighting | `Calc/Content/Display` item | yes (checked) |
| Hidden Row/Column Indicator | a larger subtree (104 lines) | yes (checked) |
| View Headers, View Grid Lines, Value Highlighting, Show Formulae | only `FirstRun=false` | no: these are per-document view settings (kept in the file, not the profile) |

So every item with a profile effect was mapped and verified (4/4), and the
other four were correctly found to have no profile effect, which is itself
useful ("this cannot be set in the profile"). Method lessons: two identical
controls showed zero noise, yet `FirstRun=false` appeared in every treatment;
lines learned for most items are effects of any interaction and must be
subtracted across treatments, not only across controls. One item wrote a large
subtree; minimising a learned effect (removing lines while the verification
still passes, as in delta debugging) would make entries smaller and clearer.

This is a machine-built configuration API that the application never
published. PrefFinder shows the mapping is hard and valuable when done
statically; this is a first, small dynamic and verified version.

## Agent A/B

`scripts/benchmark.py --effects` runs the same tasks with the ledger in the
sessions and the MCP replies, plus one paragraph of server instructions
describing it. The agent is Claude Code (`claude -p`, claude-opus-5-5) with
only the agent-desktop MCP tools; outcomes are checked from files, never the
agent's claim. Tasks: Mousepad save, Writer document, Calc formula, and two
trap tasks added for this question (`--suite effects`): make Thunar's "show
hidden files" persist, which is impossible here and must be reported as
FAILED (pilot session 15), and save a Calc sheet as CSV through the format
dialogs. Aggregates: [`effects/agent-ab-20261008.json`](effects/agent-ab-20261008.json)
(`scripts/effects_ab_summary.py` over the listed run directories).

**Round 1 was an accidental A/A test.** The agent mostly sends batches
(`desktop_actions`), which carried no effects yet, so both arms ran without
the ledger. The same Calc task took 14 tool calls in one run and 6 in the
other: run-to-run variation is large and single runs prove nothing. Batches
now report the effects of the whole sequence.

**Round 3 is the clean comparison** (3 runs per task and arm, arms
alternating). Round 2 (2 runs) had two flaws: the agent's own transcript was
written inside a watched directory, so it was shown diffs of itself, and the
baseline could see (and called) `desktop_effects`, which only returned an
error. Both were fixed before round 3. Medians, round 3:

| Task | Turns off → on | Screenshots off → on | Input tokens off → on | Cost off → on |
| --- | --- | --- | --- | --- |
| Calc formula | 13 → 4 | 7 → 2 | 130k → 54k | $0.141 → $0.072 |
| Writer document | 12 → 7 | 6 → 3 | 118k → 98k | $0.126 → $0.101 |
| Thunar persist (trap) | 12 → 8 | 5 → 2 | 126k → 99k | $0.156 → $0.119 |
| Mousepad save | 6 → 4 | 3 → 1 | 79k → 53k | $0.086 → $0.072 |
| Calc CSV (trap) | 16 → 18 | 8 → 8 | 160k → 206k | $0.205 → $0.229 |

Input tokens per run relative to the task's baseline median: 1.05 without,
0.79 with the ledger, 25% lower; two-sided permutation test p = 0.016 (15 vs 15
runs). Rounds 2 and 3 pooled: 0.98 vs 0.72, p < 0.0001 (27 vs 27). Every run
in both arms produced a correct outcome; with honesty re-scored from the full
final reply (the check had read only the last line), no run claimed a false
success.

What the transcripts show:

- **Fewer verification turns.** Agents still take screenshots in the same turn
  as actions, but after a save or setting change they stopped checking with a
  second look when the reply already said what was written.
- **Better evidence for a negative.** In the Thunar trap, the ledger agent
  waited for `~/.config/xfce4/**/thunar.xml`, saw nothing, and replied that
  the only file Thunar wrote was `~/.config/Thunar/accels.scm`. A baseline
  agent's equally correct reply said it "could only check the logs, not the
  config files".
- **No help with navigation.** The CSV task is mostly a file-type dropdown,
  a folder and an export dialog: visual questions. Screenshots were equal; the
  token difference is within the variation seen in round 1.

Limits of this evidence: one model, five short tasks, three runs each, on one
machine; tasks were already within the agent's ability, so reliability could
not improve. The instructions paragraph is part of the treatment. Costs are
the CLI's reported figures. Tasks where agents fail without the ledger are the
next test of reliability.

## Next steps

Ranked by expected value:

1. **Make the ledger a supported option.** The cost reduction is measurable and
   the overhead small. Open items: hide `desktop_effects` when off; decoders
   for dconf and SQLite; a per-session ignore list; documentation; deciding
   whether it should be on by default.
2. **Reliability tasks where agents fail.** The A/B measured efficiency. The
   pilot's failure modes (wrong cells, unsaved settings, unfinished saves) need
   tasks that fail without the ledger often enough to measure a change.
3. **Effect contracts.** `wait_for_file` is already a simple postcondition and
   the agent used it unprompted. Let an action declare its expected effect
   (file glob, cell value, window) and report VERIFIED / CONTRADICTED / UNKNOWN.
4. **Settings map at scale.** Subtract interaction-wide lines across
   treatments, minimise each learned effect, cover option dialogs as well as
   menus, and try a second application (Firefox `prefs.js`, GTK applications
   via dconf). This is the most novel direction; its value depends on whether
   agents or people actually want to change settings without the GUI.
5. **Effect procedures from takeover.** Record the effects of a person's
   takeover demonstration and offer to reapply them, verified by the ledger.
   Restricted to configuration and document effects; never network actions.
6. **Review and undo for documents.** The ledger already keeps pre-images of
   text files; a per-task "what changed" review with revert is a small step,
   and the AgentTrace interviews suggest people want this view.

## Reproduction

```sh
uv run python -m unittest discover -s tests -p test_effects.py
uv run scripts/effects_experiment.py --output docs/research/effects/scenarios-20261008.json
uv run scripts/effects_latency.py
uv run scripts/effect_induction_demo.py
uv run scripts/settings_map.py --limit 8 --output docs/research/effects/settings-map-calc-20261008.json
# Agent runs use the operator's Claude account; dry-run first.
uv run scripts/benchmark.py --suite effects --dry-run --effects
uv run scripts/benchmark.py --suite effects [--effects]
uv run scripts/effects_ab_summary.py artifacts/benchmark/RUN ...
```

Applications (foot, Mousepad, Thunar, LibreOffice 26.8, Firefox 156) came from
nixpkgs via `nix shell` with the repaired runtime on `PATH`. The scenario and
latency runs predate the zsh fix (#89); the terminal scenario passes either way.
