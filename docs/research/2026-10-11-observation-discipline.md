# E3: changed-only screenshots (negative result)

Date: 2026-10-11. Experiment E3 of the [effect-first plan](2026-10-11-effect-first.md):
send less to look at. Gate: **input tokens −25% at equal success**. Measured
on this machine with Claude Code 2.1.296 through `claude -p`.

**Result: the gate was not met.** Input tokens fell about 7% for Opus (not
significant) and not at all for Haiku. The reason is structural: screenshots
are a small share of what an agent reads. A fixed prefix of about 12.8k tokens
(Claude Code's prompt, this server's instructions and tool definitions) is
re-sent every turn and makes up 34–68% of all input tokens.

## Treatment

`--look-delta` (`AGENT_DESKTOP_LOOK_DELTA=1`, experimental, off by default):
a screenshot returned with input (`screenshot=true`) shows only what changed
since the last frame the agent was shown:

- the changed box plus a 48 px margin, at full resolution, with the usual
  region token so coordinates in the crop map to the desktop;
- the whole frame when the box covers more than 40% of the screen or no frame
  was shown before;
- no image and `unchanged: true` when nothing changed (no token: the previous
  image's token still applies).

`desktop_screenshot` without a region still returns the whole screen and
becomes the new reference. The instructions explain this in one paragraph.
UI deltas and effects were off; the baseline is again the E1 runs (same seeds).

## Runs

Three seeds × six realistic tasks × Opus and Haiku = 36 treatment runs:
`artifacts/benchmark/20261011-230233-599d` to `20261011-232702-0cfe`
(Opus 101–103: `-230233-599d`, `-231154-9347`, `-232042-285e`; Haiku:
`-230646-03c3`, `-231631-bfa7`, `-232702-0cfe`). A single functional trial,
`20261011-230129-1121`, is not counted. Aggregates:
[`benchmarks/results/2026-10-11-observation-discipline.json`](../../benchmarks/results/2026-10-11-observation-discipline.json).

## Results

Pooled ratios against each task's baseline median (the baseline arm's own mean
ratio is not exactly 1 because medians, not means, are the reference):

| Model | Input tokens | Turns | Looks | Wall time | Passed (base → delta) |
| --- | --- | --- | --- | --- | --- |
| Opus 5.5 | 1.055 → 0.982 (p 0.15) | 1.030 → 1.088 (p 0.36) | 1.017 → 0.932 (p 0.18) | 1.041 → 1.109 (p 0.69) | 18/18 → 17/18 |
| Haiku 5.5 | 1.138 → 1.133 (p 0.98) | 1.007 → 1.075 (p 0.34) | 1.072 → 1.088 (p 0.92) | 1.060 → 1.131 (p 0.51) | 18/18 → 18/18 |

The Opus failure (inventory, seed 103): the agent batched "Save, then click
Edit on the next row" without looking. The session-expiry dialog appeared
during the batch, and a planned click landed on "Sign out". The dialog is
inside the page, so the window and focus guard cannot see it. The same hazard
exists without crops; whether crops encourage longer blind batches is not
established by one run.

Where input tokens go (examples from baseline runs):

| Run | Turns | First turn (fixed prefix) | Last turn | Sum | Prefix × turns / sum |
| --- | --- | --- | --- | --- | --- |
| Opus, release notes | 11 | 12,841 | 26,305 | 207,547 | 0.68 |
| Opus, inventory | 16 | 12,847 | 39,410 | 423,278 | 0.49 |
| Haiku, inventory | 28 | 13,626 | 62,598 | 1,114,891 | 0.34 |

This server's instructions and 27 tool definitions are about 6k of the
prefix (about 22k characters; `desktop_browser`, `desktop_actions` and
`desktop_wait` are the longest); the rest is Claude Code's own prompt. A
1280×720 screenshot is about 1.2k tokens.

## Interpretation

- **Images are not the cost.** The prefix and the growing text history
  (tool replies, UI listings) dominate. Cropping screenshots saves at most a
  few thousand tokens per task.
- **Input tokens are mostly cached.** The prefix is read from the prompt
  cache, so it affects cost more than time. Model time per turn did not change.
- **Turns did not fall.** Neither E2 nor E3 changed how many turns a task
  takes, which is what dominates wall time.

## What stays

`--look-delta` stays as an experimental option, off by default. The worker's
`changed_only` and `track` screenshot options are kept for it. The finding
about the prefix suggests a cheaper experiment than E3 if cost matters:
shorter tool descriptions, or fewer tools offered per task. It is not
expected to change speed.

## Limits

- One suite of six short tasks, three seeds, one machine.
- The treatment ran a few hours after the baseline.
- Token counts are the transcript's usage fields (uncached + cache reads +
  cache writes), as in earlier reports.
