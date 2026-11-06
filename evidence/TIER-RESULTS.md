# Tier suite results (2026-11-06)

6 tasks x 3 seeds (101-103) x haiku/sonnet/opus = 54 runs, all valid (no API errors), no task
changed after model runs. Raw: evidence/tier-runs.log (artifact dirs local, artifacts/benchmark).
Smoke test (seed 999, haiku) used to fix one prompt wording ("Prepare" -> "File") before runs.
Controls: tests/test_tier_tasks.py, 6 tasks x 5 seeds x (right, nothing, 1-4 wrong variants), pass;
`--dry-run` fails all six with no agent and clean cleanup. Two page bugs (fields read after the
page was cleared) were found by the controls and fixed before any counted run.

| Task | haiku | sonnet | opus |
| --- | --- | --- | --- |
| bulk-entry | 1/3 | 2/3 | 3/3 |
| moving-target | 2/3 | 3/3 | 3/3 |
| other four | 12/12 | 12/12 | 12/12 |
| Total | 15/18 | 17/18 | 18/18 |

Median turns 22 / 12 / 14.5 (haiku/sonnet/opus); median wall 53 / 33 / 43 s; reported cost
$0.20 / $2.11 / $5.13 (+$0.015 smoke); total $7.45. Haiku vs opus Fisher p about 0.24: the ordering is
suggestive, not significant. Failure causes were not individually audited. Four of six tasks still saturate.
