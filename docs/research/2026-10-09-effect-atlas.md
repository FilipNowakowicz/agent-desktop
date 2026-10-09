# Effect atlas: learning what every control does, without a model

Research date: 2026-10-09. Follows the
[effect ledger report](2026-10-08-effect-ledger.md). Status: research scripts
and experimental tools (`desktop_atlas`, `desktop_set`, behind
`AGENT_DESKTOP_ATLAS`), two application atlases and two agent A/B tests.
Numbers are from this machine and these tasks.

## Question

The ledger reports what an action changed. Disposable private sessions make
experiments cheap. Can the runtime learn, automatically and without a language
model, what each control of an application changes, verify it, and let agents
use that knowledge instead of navigating the GUI?

## Summary

- **It works at application scale.** `scripts/effect_atlas.py` found every
  toggle in the chosen menus and every check box of the preferences dialog
  (including nested tabs), clicked each once in a fresh session, and compared
  the parsed configuration with control runs. Mousepad 0.7.0: 37 controls,
  32 with a profile effect, **30 verified** (7.7 min). Geany 2.1: 93 controls,
  76 with a profile effect, **75 verified** (23 min). No model calls.
- **Verification is independent of the exploration.** Each learned key/value
  is written alone into a fresh default profile; the application must show the
  control in the learned state (check boxes), and one more click must return
  the key to its default.
- **It found a real defect.** In Geany (2.1.0 and current master,
  `src/search.c` lines 197–200), "Always wrap search" is stored as
  `pref_search_hide_find_dialog` and "Hide the Find dialog" as
  `pref_search_always_wrap`. Anyone editing `geany.conf` by key name gets the
  opposite setting. The atlas records what controls do, not what keys claim.
- **Knowing where a setting is did not help agents.** With only a lookup tool,
  Claude Code found the right control every time but used 20% *more* input
  tokens (p = 0.0005): the expensive part is the GUI navigation, not the
  search, and a small application's preferences are easy to find.
- **Applying the learned effect did.** With `desktop_set` (write the verified
  key into the private session; Mousepad applies it live), three of four tasks
  went from 10–13 turns to 3–4 and cost about half ($0.10–0.13 → $0.05–0.07).
  The fourth stayed expensive in two of three runs because the agent then
  checked through the GUI. Pooled input tokens: 26% lower (p = 0.053, 12 vs 12
  runs). Every run in every arm succeeded.

## Prior art (checked 2026-10-09)

| Work | Relation |
| --- | --- |
| [PrefFinder](https://cse.unl.edu/~myra/papers/prefFinder.pdf) (FSE 2014) | Natural-language search over preference names using documentation and an application plugin; identifies GUI→configuration traceability as the hard part. Static; the atlas measures it dynamically. |
| [DroidTool](https://arxiv.org/abs/2609.06792) (Android) | A model proposes, implements and tests state-access tools (databases, SharedPreferences); not learned from GUI exploration. |
| [Declarative Model Interface](https://arxiv.org/abs/2510.04607) | Declarative access/state primitives over accessibility; navigation, not learned effects. |
| [PreAct](https://arxiv.org/abs/2606.17929), [AppAgent-Claw](https://pith.science/paper/2606.05171), [SkillDroid](https://arxiv.org/pdf/2604.14872), [EchoPath](https://arxiv.org/pdf/2609.16635) | Compile or replay demonstrated action sequences (PreAct reports 8.5–13× faster repeats). Actions, not state effects; "compile once, run free" is therefore not pursued here. |
| [VS Code agent review](https://code.visualstudio.com/docs/agents/run/review-code-edits) | Per-edit keep/undo for code agents; a desktop equivalent is a later product idea, not research novelty. |

No work found learns application settings by differential GUI exploration in
disposable sessions with independent verification. Absence from these searches
is not proof of novelty.

## Method

`scripts/effect_atlas.py APP` with an application spec (launch command, menus,
preferences dialog, quit key):

1. **Discover** controls through accessibility: menu items of the listed menus
   (skipping ones that open, save, print, close or quit) and named check boxes
   on every preferences tab and sub-tab, with their default state.
2. **Control runs**: start, open the same menus and dialog without clicking,
   quit; twice. Keys that differ between them are noise (none for Mousepad, one
   for Geany).
3. **Treatment** per control, in a fresh session: start, click it, quit, parse
   the configuration (GLib keyfiles/INI, LibreOffice `registrymodifications.xcu`,
   Firefox `prefs.js`, JSON) into key/value pairs, and diff against the control.
   Keys changed by most treatments are interaction noise and are removed.
4. **Verify** each effect in another fresh session as above.

Runtime work this needed, all in this branch:

- `ui_action(..., action="select")` selects a tab or list item through its
  parent's accessibility Selection. GTK notebook tabs offer no action, and
  GTK 3 menu bars open the first menu for any menu's click (as in pilot
  session 15); the explorer opens the first menu and moves right.
- Two effect-ledger bugs found while building this. (1) Diffs used one moving
  baseline per file, so asking about an action twice (its reply, then
  `desktop_effects`) under-reported the second time; files now keep a short
  version history and every report diffs against the state before its action.
  (2) Files an application wrote between reports were not versioned, so a later
  change read as "created"; the watcher now versions each file once its events
  go quiet. Files created inside a new directory before its watch existed are
  also recorded. These could only make the 2026-10-08 ledger arm's later
  queries show *less* than happened, so its measured savings are not inflated.

## Results

Atlases: [`effects/atlas-mousepad-20261009.json`](effects/atlas-mousepad-20261009.json),
[`effects/atlas-geany-20261009.json`](effects/atlas-geany-20261009.json).

| | Mousepad 0.7.0 | Geany 2.1 |
| --- | --- | --- |
| Controls explored | 37 (11 menu, 26 check boxes, 5 tabs) | 93 (24 menu, 69 check boxes, 11 tab groups) |
| With a profile effect | 32 | 76 |
| Verified by applying alone | 30 | 75 |
| No profile effect | 2 (Viewer Mode, document switch) | 14 (document actions, per-document toggles) |
| Errors | 3 (disabled items; quit blocked) | 3 (quit blocked, including "Confirm exit") |
| Time | 7.7 min | 23 min |

Examples: Mousepad "Show full filename in title bar" → `path-in-title=false`;
"Make a copy with '~' suffix" → `make-backup=true`; plugin check boxes →
entries of `enabled-plugins`. Geany's five auto-close check boxes map to
`autoclose_chars` values 1, 2, 4, 8 and 16 (a bit field), and the View menu and
the preferences dialog were found to share keys (`show_white_space`,
`show_linenumber_margin`).

Unverified cases are informative: Mousepad's "Menubar" hides the menu bar, so
the verification could not click it again (the hidden menu bar itself shows the
value applied); "Remember window position" also learned incidental window
coordinates. Errors where quitting was blocked include Geany's "Confirm exit",
whose effect is exactly to make Ctrl+Q ask.

## Agent A/B

Four Mousepad tasks phrased in everyday words ("highlight the line the cursor
is on", "make spaces and tabs visible as symbols", "emphasise the partner of a
bracket next to the cursor", "stop using the system-wide monospace font"),
checked in `~/.config/Mousepad/settings.conf`. Claude Code (claude-opus-5-5),
agent-desktop MCP tools only, ledger off in both arms, 3 runs per task and arm.
Aggregates: [`effects/atlas-ab-20261009.json`](effects/atlas-ab-20261009.json).

**Lookup only** (`desktop_atlas`; task text asked to work through the GUI):
the agent called the atlas once per task and found the right control, then
navigated the GUI as before. Turns were equal (10–12) and input tokens 20%
higher (ratio 1.20 vs 0.97, p = 0.0005). The lookup added a step without
removing any.

**Lookup and apply** (`desktop_atlas` + `desktop_set`; neutral task text, the
baseline rerun with it):

| Task | Turns off → on | Input tokens off → on | Cost off → on |
| --- | --- | --- | --- |
| Highlight current line | 13 → 4 | 115k → 53k | $0.125 → $0.065 |
| Visible whitespace | 11 → 4 | 97k → 53k | $0.107 → $0.066 |
| Matching brackets | 10 → 3 | 83k → 38k | $0.102 → $0.054 |
| Monospace font | 11 → 9 | 84k → 112k | $0.107 → $0.103 |

Pooled input-token ratio 1.03 vs 0.74 (26% lower), p = 0.053. The typical
atlas run was three calls: look up, set, one screenshot. In the monospace task
one run did exactly that; the other two opened Preferences afterwards to check,
because `desktop_set` only says what it wrote, not whether the running
application took it.

## What this means

The atlas turns a GUI application's settings into a verified configuration
interface that the application never published, built by machine time instead
of model calls or documentation. The value to an agent is in *applying* an
effect, not in finding a control: a setting task became a three-call job. A
person benefits too: "make the editor do X" can be answered and applied
without knowing where the setting lives.

Limits: two GTK text editors with INI configuration; check boxes and menu
toggles only (no combo boxes, spin buttons, text fields); one application
version each; `desktop_set` writes a private session's home only and relies on
the application reading the file (Mousepad applies it live; others may need a
restart); writing configuration skips whatever validation the GUI performs, so
it is limited to verified entries.

## Next steps

1. **Report live application.** Record during exploration whether writing the
   key while the application runs changes the control's state, so
   `desktop_set` can answer "applied and visible" or "applies after restart";
   that removes the agent's need to check (the monospace runs).
2. **More control types.** Combo boxes, radio groups and spin buttons (values,
   not just on/off), and LibreOffice/Firefox option pages.
3. **Breadth.** GNOME applications with `GSETTINGS_BACKEND=keyfile` (text
   instead of dconf), Qt applications, and a second version of an application
   to measure how much of an atlas survives an update.
4. **Desired-state use.** A list of wanted settings applied and verified in
   one call, for profiles shared between sessions.
5. **Upstream.** The Geany key swap was reported on 2026-10-09 as
   [geany/geany#4677](https://github.com/geany/geany/issues/4677). It dates
   from the 2011 commit that split the combined preference (4ffbd8f9).

## Reproduction

```sh
uv run python -m unittest discover -s tests -p 'test_atlas.py'
uv run python -m unittest discover -s tests -p 'test_effects.py'
uv run scripts/effect_atlas.py mousepad --output docs/research/effects/atlas-mousepad-20261009.json
uv run scripts/effect_atlas.py geany --output docs/research/effects/atlas-geany-20261009.json
# Agent runs use the operator's Claude account; dry-run first.
uv run scripts/benchmark.py --suite atlas --dry-run --atlas DIR
uv run scripts/benchmark.py --suite atlas [--atlas DIR]
uv run scripts/effects_ab_summary.py artifacts/benchmark/RUN ...
```

Mousepad 0.7.0 and Geany 2.1 came from nixpkgs (`nix shell`) with the repaired
runtime on `PATH`. Agent runs on 2026-10-09: 48 runs, $5.09 reported by the CLI.
