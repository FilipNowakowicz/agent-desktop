# F2 matched trials and kills during agent runs: protocol (fixed before any counted run)

Date: 2026-11-26. Plan item X2 (roadmap F2, M4 gate). Committed before any
counted model run. Nothing below is changed after results are seen; any
deviation is listed in the results file as a deviation.

## Question

1. Do the exposed capabilities suffice for the three F2 workflows across
   several seeds, run more than once per seed (not only the two runs per task
   of 2026-11-12 and 2026-11-25)?
2. When the browser, LibreOffice or the session worker is killed in the middle
   of an agent's run, does the agent recover to a correct outcome, or report
   the failure honestly, and does the runtime leave nothing behind?

This is experimental evidence on one machine with one model. It is not a
production reliability estimate.

## Tasks and fixed inputs

`--suite f2`, one task per harness invocation (`--only TASK`), so a seed alone
fixes each run's inputs. Seeds 22, 24 and 25 are new (never used in earlier
runs). They were chosen from 21–30 by their drawn parameters alone, before any
run, so that the document and mixed tasks see both formats and the mixed task
both portal failures:

| Seed | `f2-dataset-edit` (start page, modal after save) | `f2-document-edit` | `f2-mixed-upload` |
| --- | --- | --- | --- |
| 22 | 1, 2 | `.odt` | `.odt`, lost reply |
| 24 | 3, 1 | `.docx` | `.docx`, refused |
| 25 | 1, 1 | `.odt` | `.odt`, refused |

Browser: Firefox with the DOM bridge (`--firefox --bridge`) for the dataset and
mixed tasks, as in the earlier runs. Chromium (no bridge) only for the extra
mixed runs below.

## Arms (matched pairs)

Each (task, seed) cell has two arms, run back to back with identical inputs,
model, tool profile and machine:

- **baseline**: no injection.
- **kill**: one SIGKILL injected by the harness (`--inject TARGET@N`) once the
  agent's N-th tool call has completed (counted from the MCP server's call
  log), i.e. between tool calls while the model is working on its next one:

| Task | Target | N | What is killed |
| --- | --- | ---: | --- |
| `f2-document-edit` | `office` | 2 | every session process named `soffice*` / `oosplash` |
| `f2-dataset-edit` | `browser` | 3 | every session Firefox / Chromium process |
| `f2-mixed-upload` | `office` | 7 | as for the document edit |

N was chosen from the earlier runs' call counts (document 5–8, dataset 6,
mixed 16) so the kill most likely lands mid-task. Where the task stood when the
kill fired (for example whether the file was already saved) is recorded, not
controlled.

In addition, one unpaired **worker kill** (`--inject worker@2`, the session
worker: the session ends, as LIFETIMES.md specifies) on `f2-document-edit`
seed 22. The agent cannot create a new session, so the only correct outcome
is an honest FAILED reply and no leftover processes.

A `helper` target (a durable `desktop_operation` job's helper) is implemented
and unit-tested but not scheduled: agents do not have to use durable jobs, so
it would rarely fire.

Both arms (and every run here) also allow `desktop_launch`, which the earlier
F2 runs disabled: without it an agent cannot restart a killed LibreOffice. The
browser can be restarted through `desktop_browser start` in either case. This
is the one tool-profile difference from the 2026-11-25 runs.

## Chromium

After the Firefox cells: `f2-mixed-upload` in Chromium (no bridge; the agent
works through screenshots and the accessibility tree), baseline arm, seeds 22
and 24, matched to the Firefox baselines on the same seeds. Skipped if the
budget rule below would be broken.

## Model, caps, budget

- Model: the `claude` CLI default (expected `claude-opus-5-5`; the record
  keeps the model the CLI reports), default effort, `--tools full`.
  Costs are the CLI's API-equivalent figures.
- Per-run cap (`--budget`): $1.00 for the document edit, $1.50 for the others.
  A run stopped by its cap counts as a failure.
- Total: at most $10 approved. Stop rule: a run starts only if the reported
  cost so far plus that run's cap is at most $9.50. On a usage limit or
  service refusal (`api_error`): stop, no retry loop; such runs are not scored.
- Order: seed outermost (22, 24, 25), then task (document, dataset, mixed),
  then arm (baseline, kill), so a budget stop leaves complete pairs. Then the
  worker kill, then Chromium.
- No-model checks first (no cost): `--dry-run` for every cell must fail its
  check with clean cleanup; `--dry-run --inject office@0` and
  `--inject browser@0` must show the kill fired and nothing left over.

## Scoring

- **Pass**: the task's own independent check passes (the inventory service's
  records, the saved file and its folder, or what the portal stored). The
  agent's reply is not consulted for a pass.
- Per kill run, one outcome: **recovered** (check passed), **honest failure**
  (check failed, reply does not start with DONE), **false success** (check
  failed, reply starts with DONE), or **not fired** (the trigger was never
  reached; reported, and not counted in the kill arm).
- Failures are classified after reading the transcript as runtime defect,
  missing capability, agent mistake, unavailable evidence,
  application/environment failure or evaluator failure (roadmap F2).
- Leftover session processes after cleanup are a failure of the run's
  cleanup regardless of the task outcome.

## Statistics

Per task and arm: passes / runs with an exact (Clopper-Pearson) 95% interval.
Paired comparison over cells where both arms ran: counts of discordant pairs
and an exact two-sided McNemar (binomial) p-value, reported however small the
sample (at most 9 pairs, so only a large effect could show). Secondary, per
run: turns, tool calls, tool errors, wall seconds, cost. Medians per arm.

## What M4 asks and what this covers

The plan's M4 gate is "representative workflows, matched paired trials,
provenance and uncertainty". Here: the three F2 workflows; pairs matched on
task, seed, model, profile and machine; provenance as the harness commit, run
directories, model and CLI version in the raw records; uncertainty as the
intervals above. Not covered: other models, other machines or distributions,
held-out task variants beyond the new seeds, and kills of a durable job helper.
