# Evidence round status (2026-11-06)

Done: protocol (docs/research/2026-11-06-evidence-protocol.md), stock runtime flake,
wlroots A/B script (scripts/wlroots_ab.py), effect_atlas.py extended (precreate dirs,
toggle-button switches, list-style preference pages; galculator and xed specs).
In progress at commit time: wlroots A/B run (raw rows in evidence/wlroots-20261106.jsonl,
planned 1000 pairs; row count shows how far it got), tier task code and controls
(benchmarks/tiers.py, tests/test_tier_tasks.py; controls NOT yet confirmed passing).
Recon only (not the final atlas): galculator --limit 8, xed --limit 40.
Not done: full atlas runs, negative-control verification mode, gedit/Thunar/others,
any model run (no model cost spent). Task 5 was renamed tier-moving-target (protocol
said tier-restart-recovery) before any control or model run.
