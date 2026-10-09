# Guarded steps: expectations and run-time targets

Date: 2026-10-09. Stage S2 of the [speed plan](2026-10-09-beyond-human-speed.md),
measured on top of S1a ([act and observe](2026-10-09-act-and-observe.md)).

## Change

- Any `desktop_actions` step can carry `expect` (wait conditions that must hold
  after it); an unmet expectation stops the run and is reported as such.
- `ui_action` steps can name their target (element, role, state, exact, window,
  app), looked up when the step runs; it must match exactly one element.
- Waits take `state` (checked, enabled, focused, expanded, ...) and `exact`.
  Listings mark unusable controls `disabled` (GTK 4 sets only SENSITIVE, so
  "disabled" means neither ENABLED nor SENSITIVE). `press` also works on
  Chromium check boxes that offer only `check`.
- `timeout` bounds a whole run.

## Agent A/B

`scripts/benchmark.py --suite hard --only hard-web-admin hard-editor-open-edit
hard-interrupting-modal`, claude-opus-5-5, three runs per arm, arms alternating.
Both arms have `screenshot=true`; the baseline (`--no-guards`) has the same code
without the guarded-step paragraph in the `desktop_actions` description.
Aggregates: [`effects/guards-ab-20261009.json`](effects/guards-ab-20261009.json).

| Task | Turns base → guards | Input tokens | Seconds |
| --- | --- | --- | --- |
| hard-editor-open-edit | 5 → 4 | 78k → 61k | 21.3 → 18.4 |
| hard-interrupting-modal | 6 → 6 | 98k → 100k | 17.0 → 17.5 |
| hard-web-admin | 10 → 10 | 196k → 198k | 28.4 → 27.5 |

All 18 runs passed. Pooled: turns −8% (p = 0.14), input tokens −10% (p = 0.13),
time unchanged (p = 0.92). The stop criterion (≥30% fewer turns) is **not met**.

Why: the agent used `expect` only in the editor task (two steps per run, where
it replaced a check after saving), and never used run-time targets; in the
Chromium tasks it planned with coordinates from the inline screenshot, already
batching 3–12 steps per `desktop_actions` call. After S1a these tasks take 3–9
calls; little round-trip time is left for guards to remove.

## Decision

Guarded steps are kept as reliability features (exact and state checks,
uniqueness instead of a wrong click, expectations that stop on surprise), not
as a speed lever. Further speed work moves to API paths (the browser bridge)
and reuse, where the remaining decisions can be skipped rather than batched.
Untested here: tasks with surprises (where guards should prevent wrong
actions); the hard suite's traps did not trigger expectations.

## Reproduction

```sh
uv run scripts/benchmark.py --suite hard --only hard-web-admin \
  hard-editor-open-edit hard-interrupting-modal --model claude-opus-5-5 [--no-guards]
AB_ARM=guards uv run scripts/effects_ab_summary.py artifacts/benchmark/RUN ...
```
