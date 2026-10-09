# Browser bridge: private Firefox through WebDriver BiDi

Date: 2026-10-09. Stage S3 (browser part) of the
[speed plan](2026-10-09-beyond-human-speed.md).

## Change

`desktop_browser` drives Firefox in a private session through WebDriver BiDi:
start (or attach to a Firefox started with `--remote-debugging-port`), open,
tabs, text, find, wait, click, fill, select. Targets are CSS selectors or
visible text, label or placeholder and must match one visible, enabled element;
password values are never returned; input is trusted (`input.performActions`).
After the first comparison, two additions: `within` (the row, item, form or
dialog containing a text) and `steps` (several actions in one call).

## Agent A/B (small)

Both arms run the web task in Firefox (`scripts/benchmark.py --firefox`), with
S1a and S2 available; the treatment adds `desktop_browser` (`--bridge`).
claude-opus-5-5, two runs per arm and task, before `within`/`steps`:

| Task | Bridge: calls / seconds / cost | Pixels: calls / seconds / cost |
| --- | --- | --- |
| hard-web-admin | 25, 21 / 58.7, 31.6 / $0.30, $0.19 | 9, 9 / 29.9, 30.1 / $0.28, $0.21 |
| chromium-form (in Firefox) | 6, 6 / 12.0, 11.9 / $0.076, $0.076 | 3, 5 / 13.0, 17.9 / $0.094, $0.136 |

All 8 runs passed. On the form the bridge was faster and cheaper (no images)
despite more calls; on the admin table it was worse: each DOM action was its
own call, while pixel runs batch steps in `desktop_actions`, and the agent could
not name "Edit in mallory's row" among 40 identical buttons.

One run with `within` and `steps` (artifact `20261009-215014-0c17`, an
anecdote): the agent used both, 10 calls instead of 21–25, 42.6 s, $0.23; still
slower than pixels here, partly a first batch that stopped on an unlinked label.

## Matched A/B with `within` and `steps`

Same setup, three runs per arm and task, arms alternating, all 12 passed.
Aggregates: [`effects/bridge-ab-20261009.json`](effects/bridge-ab-20261009.json).

| Task | Turns pixels → bridge | Input tokens | Seconds | Cost |
| --- | --- | --- | --- | --- |
| chromium-form (in Firefox) | 6 → 4 | 102k → 60k | 18.9 → 10.3 | $0.137 → $0.069 |
| hard-web-admin | 10 → 10 | 196k → 173k | 29.0 → 22.7 | $0.207 → $0.148 |

Pooled, relative to each task's pixel median: wall time −33% (p = 0.0013),
input tokens −30% (p = 0.0013), turns −21% (p = 0.06). Unlike S1a, cost falls
too (no images in replies).

## Decision

Keep the bridge and point agents to it for web pages. Its gain needed `steps`
and `within`: one DOM action per call was slower than batched pixel steps.
Limits: two tasks, one model, Firefox only; visual pages (canvas, charts) still
need screenshots.
