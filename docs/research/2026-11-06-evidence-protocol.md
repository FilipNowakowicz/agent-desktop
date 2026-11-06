# Evidence round: protocol (fixed before any experiment)

Date: 2026-11-06. Committed before any counted run. Nothing below is changed
after results are seen; deviations are listed in the report as deviations.
Machine: shared 12-core NixOS host with other jobs running; load average at
start 2 to 8. Runs of different parts may overlap, so absolute timings are
affected by load; comparisons within a part are interleaved or matched.

## 1. Effect atlas on more applications (no model)

- Candidates, tried in this order, all from the nixpkgs revision pinned in
  `runtime/nix/flake.lock`: galculator 2.1.4 (GTK, INI), xed 3.9.0 (GSettings
  with `GSETTINGS_BACKEND=keyfile`), gedit 50.0 (same), Thunar 4.20.10 (xfconf
  XML; tried only if a private xfconf can be made to write a parsable file),
  lxterminal 0.4.1 (INI), featherpad 1.6.4 (Qt, needs `QT_ACCESSIBILITY`).
  LibreOffice 26.8.0.3 is tried last and only if fewer than four of the others
  succeed. Selection is by feasibility, decided before any atlas result.
- Feasibility recon (launch, find menus and preferences dialog through
  accessibility, find where settings are written) is allowed to write the
  application spec. After a spec is fixed, the atlas is run once; the spec may
  be changed only to fix a crash or hang, and the change is reported.
- An application counts as successful if its atlas completes and has at least
  5 verified settings. Every application tried is reported, failures included.
- Method is `scripts/effect_atlas.py` unchanged in its logic: discovery, two
  control runs for each of two probes (noise), one treatment per control in a
  fresh session, then verification in another fresh session (learned key
  written alone into a default profile, the control must show the learned
  state, one more click must return the key to its default).
- Added negative control: the verification is repeated with each learned key
  written at its *default* value. Expected: 0 verified among learned controls.
  Any verified result there means the verifier is too lenient and is reported.
- Reported per app: controls, with effect, verified, errors, noise keys,
  negative-control result, minutes; and totals.
- A suspected application bug is reported as a bug only after (a) reproducing
  it by hand in a fresh profile and (b) confirming against current upstream
  source. Nothing is filed upstream.

## 2. wlroots stock vs repaired

- Arms: stock labwc 0.20.2 / wlroots 0.20.2 (`evidence/stock-runtime/flake.nix`,
  same nixpkgs lock, no patch) and the repaired runtime
  (`runtime/nix/flake.nix`, `runtime/patches/wlroots-map-at-associate.patch`).
- Unit: one fresh private headless session, one plain `xterm -u8 -title
  "X11 fixture"`, under 4 busy CPU processes (the load of `repeat_xwayland.py`).
  One session at a time.
- **n = 1000 sessions per arm (1000 pairs, 2000 sessions)**, order within each
  pair shuffled with seed 20261106 so load drift hits both arms equally.
  Chosen from a 3-pair smoke test (about 0.9 s per session) that is not counted.
- Failure: no toplevel titled "X11 fixture" in the session's window list within
  20 s of launching xterm. Sessions where session creation or launch itself
  raises are "invalid", excluded from both numerators and denominators, and
  counted and reported (no replacement sessions).
- Integrity: each session records the wlroots library mapped by its compositor;
  a session in the wrong arm is invalid.
- Statistic: two-sided Fisher exact test on failures/valid sessions per arm;
  exact (Clopper-Pearson) 95% intervals per arm. Reported whatever the result.
- Upstream MR !5477 was closed unmerged; the repair is called "patched".

## 3. Tier-separating suite

- Six new tasks in `benchmarks/tiers.py` (`--suite tiers`), each longer,
  multi-application, with distractors and state to track, and a mid-task
  interruption in at least three; each has an independent outcome check on
  files or page state, never the agent's reply:
  1. `tier-incident-triage` (foot, Mousepad, Chromium): compute from a large log
     with an exclusion rule found in a note; fill an incident form.
  2. `tier-bulk-entry` (Mousepad, Chromium): enter unfiled expense lines,
     skipping ones already filed; an expiry modal discards a save mid-way.
  3. `tier-config-rollout` (foot, Mousepad, Chromium): change several keys in
     staging configs only, write a rollback note with the old values, resolve.
  4. `tier-meeting-slot` (two Mousepad windows, Chromium): find the only slot
     satisfying all constraints and book it; a policy modal steals focus.
  5. `tier-moving-target` (Mousepad, Chromium; renamed before any control or model run): update stock rows from a
     delivery note; after the second save the note is corrected on disk and a banner
     says so.
  6. `tier-file-triage` (foot, Mousepad): sort files by a rule note, delete only
     byte-identical duplicates (near-duplicates present), write a manifest.
- Controls before any model run: for each task a positive control (a scripted
  or programmatic correct solution must pass the check), several negative
  controls (untouched start, and plausible wrong solutions: distractor taken,
  duplicate entry, wrong environment) must fail. Run for several seeds.
  Also `--dry-run` must fail all six with no agent.
- Models: `haiku`, `sonnet`, `opus` aliases of the `claude` CLI, default
  effort, full tool profile (lifecycle tools plus `request_host` disabled),
  effects, atlas and browser bridge off. Private sessions only.
- Seeds 101, 102, 103, matched across tiers. Order: seed outermost, then task,
  then tier (haiku, sonnet, opus), so a budget stop leaves matched cells.
- Per-task cap `--budget 0.75`. Total stop rule: stop as soon as cumulative
  reported cost, smoke test included, reaches $14.00. One smoke test (task 1,
  haiku, seed 999) first. On a usage limit: stop, no retry loop.
- Primary metric: pass rate per tier (of the cells run). Secondary: turns,
  wall seconds, tool errors, cost. Fisher exact between tiers pooled over
  tasks, reported but low-powered (18 runs per tier at most).
- Task bugs found after model runs are fixed, announced, and the task is rerun
  for all tiers; no other post-hoc changes. Runs ended by the service
  (`api_error`) are not scored.
