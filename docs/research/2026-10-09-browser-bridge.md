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

## Decision

Keep the bridge: exact, image-free web work with refusals instead of wrong
clicks. Its speed advantage is not shown; a matched comparison with
`within`/`steps` (three runs per arm, more web tasks) is the next measurement,
outside today's run allowance (48 of ~50 used).
