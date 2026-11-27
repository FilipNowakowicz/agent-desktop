# F2 matched trials and kills during agent runs (2026-11-26/27)

Protocol: [docs/research/2026-11-26-f2-trials-protocol.md](../docs/research/2026-11-26-f2-trials-protocol.md),
committed before the first counted run, with an addendum written after the first 12 runs.
Raw records: [f2-trials-records.jsonl](f2-trials-records.jsonl) (one line per model
run, from `uv run scripts/f2_trials.py summary --records ...`). The run log is
[f2-trials.log](f2-trials.log). Run directories are local (`artifacts/benchmark/...`).

Machine: the maintainer's NixOS laptop (12 cores), with labwc, LibreOffice 26.8 and
the desktop tools from nixpkgs through `nix shell`, plus the system's Firefox 160.0.1 and Chromium.
The model runs did not go on the worker: it has no `claude` CLI and no login,
and the earlier F2 runs also ran on the laptop. Model `claude-opus-5-5` (CLI
default), Claude Code 2.1.332, default effort, `--tools full --allow-launch`.
Costs are the CLI's API-equivalent figures, billed to the maintainer's subscription.

## Summary

Each count is runs whose independent check passed out of the runs scored, with an
exact (Clopper-Pearson) 95% interval.

| Task | Baseline | Kill (target@N) | Kill outcomes |
| --- | --- | --- | --- |
| `f2-document-edit` | 3/3 [0.29, 1] | 3/3 [0.29, 1] (`office@2`) | 3 recovered |
| `f2-dataset-edit` (Firefox, bridge) | 3/3 [0.29, 1] | 3/3 [0.29, 1] (`browser@3`) | 3 recovered |
| `f2-mixed-upload` (Firefox, bridge) | 4/4 [0.40, 1] (one unpaired) | 3/3 [0.29, 1] (`office@7`) | 3 recovered |
| All | 10/10 [0.69, 1] | 9/9 [0.66, 1] | 9 recovered, 0 false success |

Extra arms:

| Arm | Result |
| --- | --- |
| Worker kill (`f2-document-edit` seed 22, `worker@2`) | 0/1 passed (as expected): an honest FAILED reply, no leftover processes |
| `f2-mixed-upload` in Chromium (no bridge), seeds 22 and 24 | 1/2. Seed 22 failed: a duplicate upload (an agent mistake), which the agent reported honestly |

Matched pairs (same task, seed, model, profile, machine and tool surface): 9
complete pairs, with 0 discordant pairs (McNemar p = 1.0). The kill made no
difference to the outcome here. With n = 9 that only rules out a large effect.

Median per run, baseline / kill: turns 7 / 17 (document), 10 / 14 (dataset),
19 / 30 (mixed); wall seconds 24.7 / 88.9, 38.1 / 60.5, 66.7 / 116.6; cost
$0.18 / $0.24, $0.28 / $0.31, $0.28 / $0.42. Recovering from a LibreOffice kill
took roughly 3.5 times as long (document) or 1.75 times (mixed), and 10–13 more turns.

Spend: 23 model runs, $6.415 in all (the protocol's stop rule was $9.50 and the
approval $10). That is $6.032 for the 22 scored runs and $0.383 for the invalid
one. Total agent wall time was 1484 s (24.7 min).

## Per run

`surface` is the MCP server's tool count: 29 before #240, 17 after.

| Task | Seed | Arm | Inputs | Surface | Verdict | Injection (fired at) | Outcome | Turns | Calls | Tool errors | Wall s | USD | Run |
| --- | ---: | --- | --- | ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| document | 22 | baseline | .odt | 29 | pass | - | - | 7 | 6 | 0 | 22.1 | 0.20 | 20261126-215148-97e9 |
| document | 22 | kill | .odt | 29 | pass | office@2 (6.4 s) | recovered | 17 | 16 | 0 | 79.8 | 0.24 | 20261126-215213-55c0 |
| dataset | 22 | baseline | page 1, modal after save 2 | 29 | pass | - | - | 8 | 7 | 0 | 34.9 | 0.32 | 20261126-215336-4bd9 |
| dataset | 22 | kill | page 1, modal 2 | 29 | pass | browser@3 (13.9 s) | recovered | 9 | 8 | 0 | 44.6 | 0.26 | 20261126-215416-8f20 |
| mixed | 22 | baseline | .odt, lost reply | 29 | pass | - | - | 18 | 17 | 0 | 58.8 | 0.24 | 20261126-215507-565a |
| mixed | 22 | kill | .odt, lost reply | 29 | pass | office@7 (13.9 s) | recovered | 32 | 31 | 1 | 74.1 | 0.42 | 20261126-215618-1a0e |
| document | 24 | baseline | .docx | 29 | pass | - | - | 7 | 6 | 0 | 29.0 | 0.13 | 20261126-215745-963a |
| document | 24 | kill | .docx | 29 | pass | office@2 (8.5 s) | recovered | 19 | 18 | 0 | 97.0 | 0.25 | 20261126-215818-ddcc |
| dataset | 24 | baseline | page 3, modal 1 | 29 | pass | - | - | 10 | 9 | 0 | 43.0 | 0.28 | 20261126-215958-c3d7 |
| dataset | 24 | kill | page 3, modal 1 | 29 | pass | browser@3 (12.5 s) | recovered | 15 | 14 | 1 | 60.5 | 0.31 | 20261126-220047-711c |
| mixed | 24 | baseline | .docx, refused | 29 | pass (unpaired) | - | - | 20 | 19 | 0 | 70.8 | 0.28 | 20261126-220153-691c |
| mixed | 24 | kill | .docx, refused | 29 | **invalid (api error)** | office@7 (19.5 s) | not scored | 26 | 25 | 1 | 74.3 | 0.38 | 20261126-220316-689c |
| mixed | 24 | baseline | .docx, refused | 17 | pass | - | - | 18 | 17 | 0 | 62.5 | 0.35 | 20261127-042221-be19 |
| mixed | 24 | kill | .docx, refused | 17 | pass | office@7 (25.3 s) | recovered | 30 | 29 | 0 | 145.5 | 0.42 | 20261127-042336-658e |
| document | 25 | baseline | .odt | 17 | pass | - | - | 7 | 6 | 0 | 24.7 | 0.18 | 20261127-042614-6f5a |
| document | 25 | kill | .odt | 17 | pass | office@2 (8.7 s) | recovered | 14 | 13 | 0 | 88.9 | 0.20 | 20261127-042642-9433 |
| dataset | 25 | baseline | page 1, modal 1 | 17 | pass | - | - | 10 | 9 | 0 | 38.1 | 0.26 | 20261127-042815-9bc1 |
| dataset | 25 | kill | page 1, modal 1 | 17 | pass | browser@3 (15.4 s) | recovered | 14 | 13 | 0 | 62.8 | 0.31 | 20261127-042859-283f |
| mixed | 25 | baseline | .odt, refused | 17 | pass | - | - | 20 | 19 | 0 | 79.4 | 0.28 | 20261127-043007-5cb6 |
| mixed | 25 | kill | .odt, refused | 17 | pass | office@7 (23.2 s) | recovered | 29 | 28 | 0 | 116.6 | 0.42 | 20261127-043139-7675 |
| document | 22 | worker kill | .odt | 17 | fail (expected) | worker@2 (7.6 s) | honest failure | 7 | 6 | 3 | 14.9 | 0.09 | 20261127-043353-91bb |
| mixed, Chromium | 22 | chromium | .odt, lost reply | 17 | fail | - | - | 22 | 21 | 0 | 90.6 | 0.31 | 20261127-043411-fede |
| mixed, Chromium | 24 | chromium | .docx, refused | 17 | pass | - | - | 19 | 18 | 0 | 71.0 | 0.28 | 20261127-043555-56ae |

## What the kills did

- Every kill fired at its trigger (N completed calls) and killed what it targeted:
  `oosplash` and `soffice.bin`, the Firefox processes, or the worker. No run left a
  session process behind, and the harness destroyed every session cleanly.
- **LibreOffice, document edit (3 runs):** each kill landed before the first edit
  was saved. The agent saw Writer gone (`desktop_status` showed exit code 137),
  started `libreoffice` again with `desktop_launch` and got past the "Document in
  use" prompt for the killed instance's stale lock by choosing Open (or Edit).
  The relaunch used a fresh default profile, so where a first-run dialog
  appeared the agent closed it. It then redid the edit,
  saved and quit. The lock was gone when LibreOffice closed, and the evaluator
  found no stray files.
- **Browser, dataset edit (3 runs):** each kill landed before any save. The
  agent restarted Firefox with `desktop_browser start`, reopened the page and
  edited the four targets once each. The service saw exactly 4 saves and no
  bystander changed.
- **LibreOffice, mixed workflow (3 runs):** the kill landed after the download
  and before the edit. The agent relaunched Writer on the downloaded file, edited
  and saved it in its format, and handled the portal's refused upload (503, so it
  uploaded again) or lost reply (it checked Received and did not upload again).
  The portal stored exactly one correct upload each time.
- **Worker:** the session ended as LIFETIMES.md specifies (marked `failed`). The
  agent's next calls failed with "Session unavailable" (3 tool errors), and it
  replied `FAILED: desktop session ... stopped (status "failed") right after I
  opened Find and Replace, so the agreement wasn't edited or saved. I wasn't
  allowed to start a new session`. That is the correct report: the protocol
  forbids creating a session, and the file was unchanged.

There was no false success: no run claimed DONE while its check failed.

## Failures and their classes

| Run | Class | What happened |
| --- | --- | --- |
| mixed, Chromium, seed 22 | agent mistake | The agent pressed Ctrl+S right after closing Find and Replace and went to the portal without checking that the save had gone through. It uploaded the unedited file (1428 bytes), saw that, saved again and uploaded the edited file. The portal stored both, so the check found a duplicate and an unedited first upload. The agent's reply said exactly that. Nothing points to the runtime: every step was delivered, there were no tool errors, and the file chooser worked both times |
| mixed, seed 24, kill (29 tools) | invalid (api error) | The service ended the run with HTTP 429 ("You've hit your 5-hour limit", `api_error: usage_limit_reached`). It was not scored, the protocol's API-error stop applied, and the cell was rerun later in both arms on 17 tools |
| worker kill | expected failure | See above |

## Deviations from the protocol

- **The tool surface changed mid-run.** #240 merged between the 11th and 13th
  runs and cut the MCP server from 29 tools to 17 (move, drag, scroll, focus and
  ui_action became `desktop_actions` steps; list and logs moved into status; check
  and operation became CLI-only). Seeds 22 and 24 ran on 29 tools, except the
  mixed task on seed 24. Seed 25, the rerun mixed cell on seed 24 (both arms),
  the worker kill and Chromium ran on 17. Pairs are matched within one surface
  only. The 29-tool mixed baseline on seed 24 is an extra, unpaired run. The
  other 29-tool cells were not rerun on 17 tools: that would have cost about
  $2.7 and pushed spend near the stop rule. So pass rates pooled across
  surfaces mix two tool surfaces.
- **One invalid run** (the 429 above). The harness now labels such runs `invalid
  (api error)` instead of giving them a pass, a failure or an injection outcome
  (`scripts/benchmark.py` `api_error`/`verdict`, `benchmarks/inject.py`
  `outcome`, tested in `tests/test_benchmark_inject.py`). The first driver loop
  stopped there, as the protocol requires. It was resumed after the limit reset.
- **Where each kill landed** was recorded, not controlled, as planned. In all nine
  kill runs it landed before any committed effect (no save, no upload). So these
  runs test restarting and redoing work. They do not test reconciling a partly
  done edit (for example a browser killed after two of four saves).

## What this does and does not show

Experimental proof, not production reliability. On one machine, with one model
and three new seeds per task, the exposed capabilities were enough to complete all
three F2 workflows, and to recover from a killed LibreOffice or Firefox, every
time (19 of 19 scored Firefox/Writer runs). These samples are small. The 95%
intervals still allow a true per-run failure rate of up to 18% over all 19 runs,
34% for the 9 kill runs, and 71% for any single 3-run arm. Not covered: kills after a committed effect, durable-job
helper kills (implemented, not scheduled, since agents need not use durable jobs),
Chromium kill runs, other models, other machines and distributions. Chromium had
only two runs (1/2).
