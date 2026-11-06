# wlroots stock vs repaired: results (2026-11-06)

Protocol: docs/research/2026-11-06-evidence-protocol.md section 2. Raw rows:
evidence/wlroots-20261106.jsonl. Summary: `uv run scripts/wlroots_summary.py FILE`.
Plain xterm, one fresh private session at a time, 4 busy CPU processes, 1000
shuffled pairs, failure = no toplevel within 20 s.

| Arm | Sessions | Failed to map | Rate (exact 95% CI) |
| --- | ---: | ---: | --- |
| stock wlroots 0.20.2 | 972 (integrity rule) | 15 | 1.5% (0.9 to 2.5%) |
| repaired | 1000 | 0 | 0% (0 to 0.37%) |

Fisher exact two-sided p = 2.3e-5. Without the integrity exclusion (all 1000
stock sessions): 17/1000 vs 0/1000, p = 1.4e-5.

The integrity rule excluded 28 stock sessions (2 of them failures) whose
compositor-process scan found both wlroots libraries. Cause (inferred, not
separately tested): effect-atlas runs using the repaired runtime were creating
sessions on the same machine, and the scan for new labwc processes picked up
their compositors too. The session's PATH, and so its own compositor, was the
stock runtime; the exclusion is conservative. Both counts are reported above.

Limits: one machine, one NixOS build, xterm only; other jobs and atlas runs
shared the machine, so the absolute failure rate (about 1.5%, near the 1 in
30 to 60 in UPSTREAM.md) depends on load. Arms were interleaved so both saw it.
Upstream MR !5477 was closed unmerged: the repair is "patched", not upstreamed.
