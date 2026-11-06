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

Median turns 22.5 / 12 / 14.5 (haiku/sonnet/opus; haiku over the 16 runs that reported turns);
median wall 53 / 33 / 43 s; reported cost $0.20 / $2.11 / $5.13 (+$0.015 smoke); total $7.45. The two
haiku runs that timed out reported no cost, so the haiku figure and the total cover 52 of the 54 runs;
the $14.00 stop was not close. Haiku vs opus Fisher p = 0.23: the ordering is suggestive, not
significant. Four of six tasks still saturate.

## Failures (audited from the run records, 2026-11-06)

| Task | Tier, seed | Rows or stock | What happened |
| --- | --- | --- | --- |
| bulk-entry | haiku 101 | 10/12 rows | At the expiry login it called `desktop_request_human`, then waited in `desktop_control` until the 900 s timeout. |
| bulk-entry | haiku 102 | 10/12 rows | The same. |
| bulk-entry | sonnet 101 | 10/12 rows | Stray keystrokes left the form and the ledger reset; it re-entered four rows, then stopped at the login and asked whether to sign in. |
| moving-target | haiku 103 | 2 SKUs wrong | Replied DONE with the uncorrected quantities: the correction was not applied. |

The login details were in the open note in every bulk-entry run, and no person takes part in a
benchmark. Three of the four failures therefore stop at the login, and two of those are handoffs
that could never be answered. They stay scored as failures, as the protocol scores only `api_error`
runs as invalid, but they measure willingness to use a password from a note more than desktop
ability. `scripts/benchmark.py` now disables `desktop_request_human` and `desktop_control` in every
tool profile, so later runs of this suite are not directly comparable on `bulk-entry`.

## Deviations

- Task 5 was redesigned, not only renamed, before any control or model run: `tier-restart-recovery`
  restarted to a login after the third save; `tier-moving-target` corrects the note after the second.
- One prompt wording was changed after the smoke test (above).
- Formatting and variable renames landed after the runs (`df3647d`); task behavior did not change.
