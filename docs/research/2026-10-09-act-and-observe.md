# Act and observe: input that returns the settled screen

Date: 2026-10-09. Stage S1a of the [speed plan](2026-10-09-beyond-human-speed.md).

## Change

Input tools and `desktop_actions` accept `screenshot=true`. After the input the
worker waits until the screen has been still for 0.3 s (changes up to 400 px²,
such as a caret, ignored), at most 3 s, then captures. The reply carries the
image, its observation token and `settled` (`quiet` or `changing`). It uses the
existing grim capture and frame diff; no new capture backend. A still screen is
reported as such, not as "the application is done".

## Agent A/B

`scripts/benchmark.py --only chromium-form chromium-slider mousepad-save`,
Claude Code (`claude -p`, claude-opus-5-5) with only the desktop MCP tools,
three runs per arm, arms alternating. The baseline (`--no-look`) runs the same
code with the option and its descriptions removed (`AGENT_DESKTOP_LOOK=0`).
Outcomes are checked by the harness. Aggregates:
[`effects/look-ab-20261009.json`](effects/look-ab-20261009.json).

| Task | Turns base → look | Screenshots (separate + inline) | Input tokens | Seconds | Cost |
| --- | --- | --- | --- | --- | --- |
| chromium-form | 12 → 10 | 2 → 0 + 2 | 142k → 104k | 22.3 → 19.1 | $0.118 → $0.126 |
| chromium-slider | 6 → 4 | 3 → 1 + 2 | 64k → 57k | 12.4 → 10.8 | $0.075 → $0.083 |
| mousepad-save | 6 → 4 | 3 → 1 + 2 | 79k → 57k | 19.4 → 17.4 | $0.083 → $0.088 |

Medians per task. All 18 runs passed. Pooled, each run relative to its task's
baseline median, two-sided permutation test:

- model turns 0.98 → 0.68 (−31%), p = 0.0002
- input tokens 0.95 → 0.76 (−20%), p = 0.04
- agent wall time 0.98 → 0.84 (−14%), p = 0.04

The agent used the option without prompting beyond the tool descriptions: two
inline screenshots per task, replacing most separate screenshot calls. Wall time
falls less than turns because each saved turn is a short one (a look, not a
decision) and settling adds 0.3 s or more per inline screenshot.

Median cost did not fall (+5–10%, within run-to-run spread). The saved tokens are
mostly cached prefix reads, which are cheap; the images themselves are still
sent. Cost is not the objective of this stage.

## Limits

One model, three short tasks the agent already passes, three runs per arm on
one machine. The tasks are visual verification after a few inputs; tasks
dominated by decisions will gain less. The 30% stop criterion of the plan is
met for turns, so the stage is kept; S2 (guarded plans) is compared against it.

## Reproduction

```sh
uv run scripts/benchmark.py --only chromium-form chromium-slider mousepad-save \
  --model claude-opus-5-5 [--no-look]
uv run scripts/effects_ab_summary.py artifacts/benchmark/RUN ...
```

Applications: Chromium from the system profile, Mousepad and at-spi2-core from
`nix shell`, the repaired runtime on `PATH`.
