# Effect atlas results (2026-11-06)

Protocol: docs/research/2026-11-06-evidence-protocol.md section 1. Raw results:
docs/research/effects/atlas-*-20261106.json. Xed recon before its spec was fixed:
evidence/recon-xed-limit40.json.

| App | Controls | With effect | Verified | Errors | Noise keys | Negative controls (false passes) | Minutes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| galculator | 13 | 12 | 8 | 0 | 0 | 10 (0) | 3.7 |
| xed | 40 | 19 | 18 | 10 | 1 | 18 (0) | 10.1 |
| pluma | 29 | 19 | 19 | 6 | 0 | 19 (0) | 8.3 |
| Total | 82 | 50 | 45 | 16 | 1 | 47 (0) | 22.1 |

All three meet the protocol's bar of a completed atlas with at least 5 verified
settings. Xed stopped at exactly 40 controls, the same number as its recon limit,
so its count may be capped rather than complete. Three controls with an effect
have a `verify_error` and so no negative control. The other errors include
controls with no click action and an application that did not quit; each is
recorded per control in the raw files.

## Deviations

- The negative control writes nothing, instead of writing each learned key at its
  default value, so it also covers keys that are absent by default (`d72c9b2`).
  The expected result is unchanged: the control must not show the learned state.
- Pluma was not a protocol candidate. It was added after galculator and xed.
- gedit, Thunar, lxterminal, featherpad and LibreOffice have no recorded attempt or
  outcome. The protocol listed them in order and asked for every application
  tried to be reported; they are not failures, and nothing is known about them.
- The galculator and xed atlases were run a second time to add negative controls,
  although the protocol allows one run per fixed spec. Their counts did not
  change; the recorded minutes are from the second run.
- `effect_atlas.py` gained list-style preference pages and toggle switches, which
  xed needed. The method is unchanged; this is new widget support.
