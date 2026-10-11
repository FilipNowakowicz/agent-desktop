# E2: effect-first A/B (negative result)

Date: 2026-10-11. Experiment E2 of the [effect-first plan](2026-10-11-effect-first.md),
which tests its thesis: a desktop that reports exactly what each action changed
lets the agent skip most looks. Gate: **turns or looks −30% at equal success**;
otherwise "the thesis is weak; record that and stop". Measured on this machine
with Claude Code 2.1.296 through `claude -p`.

**Result: the gate was not met.** With Opus, turns fell 4.5% and looks 6.5%,
while wall time rose 15% because the new UI report costs time in the tool. With
Haiku nothing changed. The thesis is weak on this suite, and the E2 line (E4
required expectations, E6 skills built on effects) stops here.

## What the treatment arm had

`--effects` (the experimental ledger), extended for this experiment:

- **UI deltas.** Each action's `effects.ui` lists what changed in the focused
  window's accessibility tree (elements added, removed or changed; the page
  only in a browser). The report waits up to 0.8 s for the first change,
  because Chromium updates its tree a few hundred milliseconds after input.
- **Config keys.** INI-style files report `[section] key: old → new`.
- **Effect expectations.** Step lists and `desktop_wait` accept `file` with
  `contains`, or `file` with `key`/`value`, checked from the files without a
  screenshot.
- **Framing.** The server instructions present effects as the normal way to
  work: continue without a screenshot when the effects show what is needed,
  and plan steps with effect expectations.

The baseline arm is the E1 runs (same seeds, same suite, effects off;
[model tiers](2026-10-11-model-tiers.md)). The baseline code lacked the new
`wait` conditions, which belong to the treatment.

## Runs

Three seeds (101–103) × six tasks × two arms × two models = 72 runs.
Effects arm: `20261011-190217-99e6`, `-191157-f411`, `-223746-7f2e` (Opus) and
`-190653-09d5`, `-191707-1e08`, `-224252-4ea7` (Haiku). Two runs hit the
account's usage limit (`429 usage_limit_reached`) and were rerun after the
reset: `20261011-192049-79e0` and `-192232-8e5b`, excluded. The harness now
records such runs as `api_error`, excludes them from scoring and stops the
suite. Aggregates: [`benchmarks/results/2026-10-11-effect-first-ab.json`](../../benchmarks/results/2026-10-11-effect-first-ab.json).

## Results

Pooled per-task ratios against the baseline median (two-sided permutation test,
`AB_ARM=effects scripts/effects_ab_summary.py`):

| Model | Turns | Looks | Wall time | Input tokens | Passed (base → effects) |
| --- | --- | --- | --- | --- | --- |
| Opus 5.5 | 0.955 (p 0.05) | 0.935 (p 0.13) | 1.146 (p 0.04) | 1.075 (p 0.74) | 18/18 → 18/18 |
| Haiku 5.5 | 1.006 (p 0.99) | 1.019 (p 0.69) | 1.123 (p 0.55) | 1.172 (p 0.85) | 18/18 → 17/18 |

Where the time went (sums over 18 runs):

| Arm | Wall | Model API | Tool | Calls | Batched steps | Steps with `expect` (file/key) |
| --- | --- | --- | --- | --- | --- | --- |
| Opus, baseline | 748 s | 554 s | 159 s | 216 | 378 | 1 (0) |
| Opus, effects | 821 s | 503 s | 289 s | 196 | 322 | 19 (4) |
| Haiku, baseline | 766 s | 556 s | 184 s | 480 | 125 | 0 (0) |
| Haiku, effects | 765 s | 512 s | 256 s | 455 | 10 | 0 (0) |

The Haiku failure is a real one: on seed 102's inventory task it found only the
similarly named "Norvika" rows on the first page, did not page on, and asked
instead of acting.

## Interpretation

- **The effects were used, but did not replace many looks.** Opus wrote 19
  expectations (4 on files or config keys) and took 10% fewer calls; its model
  time fell 9%. The tasks still needed most of their looks: pages to read,
  forms to locate, a dialog to notice. Effects confirm outcomes; they do not
  show the agent where things are.
- **The UI report costs more than it saves.** Tool time rose 82% for Opus. Most
  of it is the settle wait (up to 0.8 s when an action changes nothing in the
  tree) and the extra tree reads. Even with that cost removed, Opus's wall time
  would have fallen only about 8%.
- **The weaker model ignored the new tools.** Haiku never used an expectation
  and batched fewer steps than before. Tool descriptions alone do not change
  how a weaker model works.
- **The tasks are short.** Opus needed 8–19 turns per task; little of that is
  verification that effects could replace. Long tasks (the plan's motivating
  case) could behave differently, but this suite gives no evidence for it.

## What stays

The changes are kept, behind the experimental `AGENT_DESKTOP_EFFECTS=1` and off
by default: the `wait` file and config conditions (cheap and useful on their
own), config-key reports, and UI deltas (`AGENT_DESKTOP_UI_DELTA=0` turns them
off). The harness keeps the `api_error` handling and the `AB_ARM=effects`
comparison. No claim that effect reports speed up agents should be made from
this work.

## Limits

- One suite of six short tasks, three seeds; one machine.
- The baseline ran a few hours earlier than the treatment (the usage limit
  split the treatment batch); machine conditions are similar but not
  interleaved.
- Only Chromium and Mousepad expose UI deltas here; terminal (foot) actions
  have none.
