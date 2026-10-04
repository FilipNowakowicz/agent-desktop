# GUI task benchmark

`scripts/benchmark.py` runs 20 representative tasks (`benchmarks/tasks.py`) with
Claude Code as the agent. For each task the harness creates a fresh headless
session, launches the application and waits for its window. It then runs
`claude -p` with **only** the private-desktop MCP tools (`--tools ""`, strict MCP
config, $1 cap per task). The outcome is verified independently: window titles set by
the page, files on disk, or a dialog's stdout and exit code. The agent's reply is
not trusted. After each task the session is destroyed and checked for leftover
processes.

```sh
# Runtime tools and the apps must be on PATH; on NixOS, for example:
nix shell nixpkgs#labwc nixpkgs#grim nixpkgs#foot nixpkgs#xwayland nixpkgs#xterm \
  nixpkgs#zenity nixpkgs#kdePackages.kdialog nixpkgs#chromium nixpkgs#mousepad \
  --command uv run scripts/benchmark.py            # all tasks (uses your Claude account)
uv run scripts/benchmark.py --dry-run               # setup + checks, no agent
uv run scripts/benchmark.py --only zenity-scale     # selected tasks
```

`--dry-run` is the negative control: every check must fail when no agent acts.
It did for all 20 tasks (apps launched, windows appeared, cleanup clean).

## Tasks

| Application | Tasks |
| --- | --- |
| Chromium (native Wayland) | code read from a canvas plus drag into a target; form (text, select, radio, checkbox); off-screen button; `confirm()` dialog; code from a second tab; range slider to an exact value; custom context menu; double-click cell edit; Ctrl+K hidden search; drag reordering |
| foot | create a file through the shell |
| xterm (Xwayland) | create a file named after a code shown only in the window title |
| mousepad (GTK 3) | type two lines and save via the save dialog |
| zenity (GTK 4) | radio list, multi-field form, file chooser navigation, calendar date, scale value |
| kdialog (Qt 6) | combobox, checklist |

## Results, 2026-10-04 (NixOS, Claude Code 2.1.288, claude-opus-5-5)

| Run | Passed | Tool calls | Tool errors | Agent seconds | Cost (USD) | Cleanup failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 `20261004-013620-d3f8` | 19/20 | 233 | 0 | 393 | 2.24 | 0 |
| 2 `20261004-021510-4cd6` | 20/20 | 149 | 0 | 348 | 1.78 | 0 |
| 3 `20261004-022211-1f4f` | 20/20 | 154 | 0 | 322 | 1.81 | 0 |

| Task | Run 1: pass / calls | Run 2 | Run 3 |
| --- | --- | --- | --- |
| chromium-canvas-code-drag | pass / 7 | pass / 7 | pass / 7 |
| chromium-form | FAIL / 24 | pass / 11 | pass / 11 |
| chromium-scroll | pass / 10 | pass / 10 | pass / 10 |
| chromium-confirm-dialog | pass / 5 | pass / 5 | pass / 5 |
| chromium-second-tab | pass / 9 | pass / 9 | pass / 9 |
| chromium-slider | pass / 14 | pass / 7 | pass / 7 |
| chromium-context-menu | pass / 5 | pass / 5 | pass / 5 |
| chromium-double-click-edit | pass / 8 | pass / 8 | pass / 9 |
| chromium-keyboard-shortcut | pass / 39 | pass / 7 | pass / 7 |
| chromium-drag-reorder | pass / 9 | pass / 7 | pass / 7 |
| foot-shell-file | pass / 3 | pass / 3 | pass / 3 |
| xterm-title-code | pass / 4 | pass / 4 | pass / 4 |
| mousepad-save | pass / 9 | pass / 9 | pass / 12 |
| zenity-radio-list | pass / 7 | pass / 10 | pass / 8 |
| zenity-forms | pass / 10 | pass / 10 | pass / 10 |
| zenity-file-chooser | pass / 10 | pass / 8 | pass / 11 |
| zenity-calendar | pass / 8 | pass / 8 | pass / 8 |
| zenity-scale | pass / 38 | pass / 6 | pass / 7 |
| kdialog-combobox | pass / 7 | pass / 7 | pass / 7 |
| kdialog-checklist | pass / 7 | pass / 8 | pass / 7 |

Between runs 1 and 2:

- **Fixture bug:** the form input had `id=name`, which `window.name` shadows in
  page scripts, so the task was impossible. Fixed in the fixture; this was not
  an agent failure.
- **Runtime bug found by the agent:** in the Ctrl+K task the agent got
  `privatdesktop` and reported "space acts like Backspace". The virtual keyboard
  had put space on evdev code 14 (physical Backspace), which Chromium honours.
  Fixed by the physical US keymap (PR #20); the task went from 39 to 7 calls.
- **Tool gap:** moving a GTK scale took 32 single `Right` key calls. `key` now has
  `repeat`; the task went from 38 to 6 calls.

## Limits

- One model, one machine, three runs. These are measurements of this setup, not
  general reliability claims.
- The suite has saturated (40/40 in the last two runs), so it no longer
  distinguishes improvements by pass rate. Harder, multi-application and
  longer-horizon tasks are needed. Tool calls, time and cost remain useful.
- Applications are launched by the harness. Tasks start from a known state and do
  not test the agent's own launch decisions (`scripts/claude_code_task.py` covers
  create and launch).
- No baseline comparison with other computer-use runtimes has been run yet.
