# E0 and E1: realistic suite and model tiers

Date: 2026-10-11. Experiments E0 and E1 of the
[effect-first plan](2026-10-11-effect-first.md). All numbers are measured on
this machine (NixOS, Claude Code 2.1.296 through `claude -p`, private headless
sessions, Chromium, Mousepad, foot), unless marked otherwise.

## Setup

- Suite: `--suite realistic`, six multi-application tasks
  ([benchmark guide](../BENCHMARK.md#realistic-suite-e0-2026-10-11)).
- Arms: `--model opus`, `sonnet` and `haiku` (Opus 5.5, Sonnet 5.5, Haiku 5.5),
  default effort, full tool profile, effects off.
- Matching: three seeds (101, 102, 103). Each seed fixes the random task inputs
  and was run by all three models back to back, interleaved by seed, so the
  models saw identical tasks under similar machine conditions.
- 54 runs, 18 per model: `artifacts/benchmark/20261011-181907-d5e9` to
  `20261011-185629-55cb` (local artifacts; aggregates in
  [`benchmarks/results/2026-10-11-model-tiers.json`](../../benchmarks/results/2026-10-11-model-tiers.json)).
- Fast mode is not exposed by the CLI; `--effort` is, and the harness now
  passes it through (`--effort low|medium|high|xhigh|max`). Effort was not
  varied in this batch.

## Results

All 54 runs passed the independent checks.

| Model | Passed | Wall p50 / p95 | Turns (median) | s per turn | Looks (median) | Tool errors (sum) | Input tokens (median) | Cost (sum, as reported) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Opus 5.5 | 18/18 | 35.4 / 82.1 s | 11.5 | 3.1 | 6.5 | 2 | 181k | $4.61 |
| Sonnet 5.5 | 18/18 | 28.1 / 188.9 s | 13.5 | 2.5 | 6.0 | 7 | 169k | $2.63 |
| Haiku 5.5 | 18/18 | 37.0 / 145.4 s | 22.5 | 1.5 | 7.5 | 8 | 372k | $0.33 |

Share of wall time: Opus 74% model API, 21% tool, 5% other; Sonnet 66 / 30 / 4;
Haiku 72 / 24 / 4.

Per task, median wall time in seconds (Opus / Sonnet / Haiku): release notes
33 / 22 / 20, ticket config 22 / 25 / 21, expense claim 50 / 47 / 39,
inventory 68 / 142 / 73, editor indentation 35 / 38 / 49, attach invoice
32 / 28 / 30.

## What this shows

- **E0 gate: met, with one exception.** The median coefficient of variation of
  wall time across the three seeds is 0.11 (Opus), 0.15 (Sonnet) and 0.10
  (Haiku), below the −30% effect E2 must show. The inventory task varies much
  more (CV 0.41 for Haiku, 0.45 for Sonnet: Sonnet took 51 s, 142 s and 189 s),
  so it needs more runs or should be read separately.
- **Success does not separate the tiers on this suite.** Every model completed
  every task. These tasks take the agent under about a minute; they are
  realistic in shape but not yet long. The human baseline is still missing,
  so how long they take a person is unknown.
- **Weaker models take more, cheaper turns.** Haiku took twice the turns of
  Opus at half the time per turn, so its wall time was about the same as Opus's.
  Sonnet was the fastest at the median, but its inventory runs were the
  slowest of all. Haiku and Sonnet made more tool errors (8 and 7 against 2),
  which they recovered from.
- **The number of turns still dominates.** For every tier, model API time is
  66–74% of wall time. A cheaper tier changes the cost of a turn, not how many
  turns the agent needs, which is what E2 targets.
- **E1 choice: Haiku**, the cheapest tier at equal success (the plan's rule).
  Its reported cost was $0.33 for 18 runs against $4.61 for Opus; the cost is
  the CLI's figure, and the subscription allowance is what is actually spent.
  E2 runs Opus and Haiku.

## Limits

- One machine, one suite of six tasks, three runs per task and model.
- 54/54 passes give no information on which tier fails first; harder or longer
  tasks are needed for that (see the plan's open items).
- Time of day and load drift between models are reduced by interleaving, not
  removed.
- Cost figures are what `claude -p` reports for each run; they were not
  checked against billing.
