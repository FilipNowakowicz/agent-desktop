# Beyond human speed: research plan

Date: 2026-10-09. Plan and research direction agreed in discussion with the
maintainer. It builds on the [speed note](2026-10-09-speed.md) (where the time
goes), the [effect ledger](2026-10-08-effect-ledger.md) and the
[effect atlas](2026-10-09-effect-atlas.md). Nothing here is measured yet unless
it says so; estimates are labelled.

**Revised the same day after an [external review](2026-10-09-astra-review.md):**
the roadmap (§5) is reordered, three claims are corrected in place (marked
*Corrected*), and the review's code findings are fixed first.

## 1. The problem in one paragraph

In the host trial, time inside the tool was 0.4–2.6% of wall time; the rest was
the agent's side of the loop (median gap 2.1–3.6 s): model inference, but also
its shell work, transport and the person's pauses, which the trace does not
separate. 53 of 59 screenshots came directly after an input, and 33 after
exactly one action. Faster capture or input cannot change much, apart from
task-specific exceptions such as typing long text (paced at 8 ms per key).
Speed is

```text
task time ≈ understanding + (model decisions × 2–4 s) + execution (≈ 0.01–0.3 s per step)
```

A person is fast because perception and correction run without deliberation;
only decisions are deliberate. The plan applies the same split: **the model
decides and predicts; a local loop perceives, acts and checks at screen speed,
and calls the model back only on a surprise.**

## 2. The ideal agent in a new environment

What an agent with no limits on tooling would do, as the target to measure
against:

1. **Read instead of look.** Take in the application's whole structure at once:
   every window, menu, tab, field and state (accessibility tree, DOM), plus what
   lies underneath (configuration files, CLI help, documentation, source).
2. **Explore in a throwaway copy, without the model.** Crawl the UI in a cloned
   session at machine speed and record states, transitions and effects: a map.
3. **Plan once over the map.** Reaching a goal becomes a shortest-path search;
   the model states the goal, checks the plan and adds branches for anticipated
   surprises (a login dialog, a cookie banner).
4. **Skip the GUI where possible.** If the map shows that a control writes a
   configuration key or a form posts one request, do that directly.
5. **Execute at application speed with guards.** The remaining GUI steps run as
   a guarded plan; the model is called only when a guard fails.
6. **Verify by effects.** Check the file, the configuration value, the page
   state: exact, milliseconds, no screenshot.
7. **Parallelise.** Several sessions; race alternative approaches, split
   independent subtasks.
8. **Remember.** Maps and plans that worked are stored; the next run replays.

Illustration (estimate) for the trial's web-app task: read the page (1 s), one
planning call (3–5 s), about ten steps at 0.2 s (2 s), verify (0.5 s): about
10 s, against roughly 30–60 s for a person and 11 minutes in the trial; about
1 s if the application has an API.

## 3. Mechanisms

### 3.1 Predictive, delta-coded observation

Observations should carry *information*, i.e. what the model did not already
know.

- **Damage instead of polling.** wlr-screencopy v2 `copy_with_damage` waits for
  a change and reports the changed rectangles; ext-image-copy-capture-v1
  reports damage as frame metadata. The runtime already speaks Wayland
  directly (`wayland.py`); capture currently uses `grim`, which has no damage.
  *Corrected:* damage means a repaint, not that the application is ready (a
  failed input leaves the screen still; a network reply can arrive after a
  quiet spell). Quiet is a cue to re-check a condition, never a postcondition.
- **Keyframes and deltas.** Send a full frame at the start, after large changes
  or after k deltas; otherwise send only changed crops with their position.
  Image cost is roughly width × height / 750 tokens for Claude models (other
  providers count differently; measure billed usage): a full 1920×1080 frame
  ~1,500–1,800 tokens after downscaling, a 600×400 dialog ~320, a 200×60
  button ~16. With prompt caching, earlier frames are not reprocessed, so an
  appended crop costs about its own tokens.
- **Text deltas first.** Where structure is available, describe the change:
  "dialog 'Add webhook' opened; fields URL, Secret; Save disabled" (~20 tokens).
  The effect ledger already does this for files (−25% input tokens, p = 0.016).
- **Noise filtering.** Ignore regions that always change (clocks, cursors,
  spinners, video) by learned masks and perceptual similarity thresholds.
- **Surprise only.** When the model predicted a result (3.2), a matching result
  is reported in a few tokens and needs no image; only the part that differed
  is sent. This is prediction-error coding: the model's expectations act as the
  codec.
- **Limit.** The server cannot remove images already in the client's context;
  it can only stop adding them. Text by default, crops when useful, keyframes
  when needed keeps context growth roughly linear in surprises rather than in
  steps.

Estimate from the trial: 59 full frames ≈ 95K image tokens; keyframes plus
deltas or text could be ≈ 10K, with about a third of the calls.

### 3.2 Guarded plans

`desktop_actions` already runs up to 50 steps, holds the controller lease,
checks window, focus and output between steps, and its `wait` steps accept a
window title, element name or text and stop the run when unsatisfied. Missing:

- **Targets resolved at run time**: `click {name: "Add webhook"}` resolved
  through accessibility in private sessions, or local OCR/template matching of
  the settled frame on the host. A missing or ambiguous target is a surprise.
- **An expectation on every step** (`expect`): window or dialog appears/closes,
  text appears/disappears, element state (enabled, checked, value), region
  changes or stays unchanged, file or configuration effect. Each has a deadline;
  a timeout is a surprise.
- **In-window change detection** through damage, so a popup or an unexpected
  in-page change is noticed, not only window and focus changes.
- **Conditional branches** for anticipated variations: `if dialog "Sign in" →
  stop for handoff; if banner "cookies" → click "Reject"`.
- **Commit points.** Plans end before irreversible actions (send, delete, pay,
  submit to a third party); the model confirms from a fresh observation and
  sends that step alone.
- **Compact report.** Success: "n steps ok" plus a text summary of changes.
  Surprise: the step, expected vs. found, the delta (text or crop), a keyframe
  only if the change is large. Later steps are not run.

How much to queue depends on predictability: familiar UI 5–20 steps; new or
content-driven UI 1–2 steps.

Prior art: *Adaptive Anticipatory Policy Trees* (Dong et al., arXiv 2607.28399,
July 2026) builds bounded conditional trees with observable guards and
pre-authorised actions during idle time, executed by a lightweight observer;
success in a contested decision window rose from 0.50 to 0.79, and branch
routing, not observer speed, was the bottleneck. That supports guards on
semantic facts (names, text, structure) rather than raw frame matching.

### 3.3 Application maps from model-free exploration

The effect atlas crawls settings dialogs, clicks each control once in a fresh
session and verifies the configuration key it changes (Mousepad 30, Geany 75
verified, no model calls). Generalise from settings to **navigation**:

- States are identified by a structural fingerprint (window set, focused
  element, accessibility subtree hash); transitions are the actions between them.
- Exploration is breadth-first and bounded, in a disposable session with a
  copied profile, skipping actions marked destructive by name or role
  ("Delete", "Quit", "Send").
- Planning is a shortest-path search over the map; the model only names the goal
  state and checks the plan. The map supplies expectations for free: each edge
  knows the state it should reach.
- Maps go stale with application updates: store the application version and
  re-verify edges on first use (a failed edge is a surprise, then re-explore
  locally).

### 3.4 Skipping the GUI

- **Settings**: `desktop_set` (halved the cost of three of four settings tasks).
- **Browsers in private sessions**: drive pages through WebDriver BiDi (DOM,
  scripts, background tabs) instead of pixels.
- **Other applications**: D-Bus interfaces, CLI remote options, files.

### 3.5 Verified procedures

A guarded plan that finished without surprises, or a trace that ended in a
verified effect, becomes a named procedure with its expectations as guards.
Replay calls the model only on deviation. Prior art (Speculative Macro Commit,
arXiv 2609.03236) reports that exposing mined macros as tools is unreliable
because models rarely choose them; prefer *offering* a matching procedure at
plan time ("a verified procedure exists for this goal; run it?") over a long tool
list.

### 3.6 Parallel and speculative execution

- Independent subtasks in separate private sessions.
- Racing: two candidate plans in two sessions, keep the first that verifies.
- Speculation while the model thinks (Speculative Actions, arXiv 2510.04371,
  up to 20% lower latency): pre-compute the next observation (OCR, element map)
  so it is ready when asked; pre-executing actions is safe only in disposable
  sessions. *Corrected:* a disposable session is not a disposable world;
  applications still write the person's files and reach the network, so
  speculation stays read-only unless every effect is known to be local and
  thrown away.

### 3.7 Live applications without taking the person's screen

Wayland has one keyboard focus and one pointer per seat and deliberately does not
let a client inject input into an unfocused window, so "the agent uses my real
windows in the background while I use others" cannot work through the screen.
It can work through the application:

- *Corrected:* private sessions do **not** share the person's configuration;
  each gets its own home (`worker.py`, `HOME`/`XDG_*`). They share the user,
  files and network. Using the person's configuration means copying selected
  files into a profile, or the bridge below.
- **Browser bridge.** Firefox started with `--remote-debugging-port` exposes
  WebDriver BiDi: background tabs, DOM, scripts, `webExtension.install`
  (temporary unless signed and `moz:permanent`). Costs: a restart with the flag,
  automation indicators in the browser UI, possible `navigator.webdriver`
  detection by sites (to verify), and the local port must be protected. A
  companion extension using native messaging avoids the automation flag but
  must be built and signed (free unlisted signing by Mozilla).
- **Hidden monitor.** `hyprctl output create headless` adds an invisible
  output; windows moved there can be captured, but input still moves the shared
  pointer and keyboard focus. `sendshortcut` sends key chords to a named window
  without focus (not clicks or text). Useful only when the person is idle.
- **Hybrid workflow.** Do the long work in a private session; use a short host
  session or the bridge only for the final change to live state. The trial's
  11-minute host sessions would shrink to a minute or two (estimate).

## 4. How close we can get

| Ideal | Today | Reachability |
| --- | --- | --- |
| Read the whole structure | AT-SPI tree in private sessions; compact listings | Close; needs projections (Chromium listings reached 10–13K characters) |
| Explore in a copy | Effect atlas for settings | Medium: navigation maps; copies are fresh sessions with copied profiles; live forking is unreliable |
| Plan over a map | — | Medium: search is easy, map coverage is the work |
| Skip the GUI | `desktop_set` | Close for settings; browsers via BiDi |
| Guarded plans | Sequences with window/focus checks and wait-steps | Close: run-time targets, `expect`, damage, report |
| Delta observation | Region screenshots, observation tokens | Close: damage capture, keyframe policy, text deltas |
| Verify by effects | Effect ledger (files, windows, processes) | Close: add DOM and application state |
| Parallel sessions | Multiple sessions work | Easy technically; orchestration and cost are the limits |
| Remember | Atlas files | Medium: procedure store, staleness checks |

Where the ideal does not apply: the person's own screen (no reliable structure,
no copies, real consequences), effects on remote services (exploration must be
read-only, plans stop before commits), applications without structure (games,
canvases; fall back to pixels and OCR), and the first decision (at least one
model call).

Realistic targets (estimates to test): private sessions with structured
applications 3–10× human speed on routine work; the host screen about human
speed.

## 5. Roadmap and experiments

Each stage is a PR with tests; agent comparisons use matched arms with several
runs per arm (the effect-ledger study showed 14 vs 6 tool calls on identical
runs), report wall time (p50 and p95, failed attempts kept), model turns, input
tokens, success and wrong actions, and dry-run before spending the maintainer's
allowance. First-use and repeat runs are reported separately. "Human speed"
claims wait for a matched human baseline.

Revised order after the review: trustworthy checks before longer plans, the
existing capture path before a new one, a few hand-written procedures before
general maps.

| Stage | Build | Measure | Stop / continue |
| --- | --- | --- | --- |
| S0 Foundations | `desktop_set` through the worker (lease, takeover) and refusing changed starting values; element waits scoped to the app's windows; partial accessibility reads never count as absence; file waits ignore deletions; doc corrections | Tests | Done before S1 |
| S1a Act and observe | Inputs and sequences can return a final observation (screenshot or region) after a bounded settle that reports *why* it returned (quiet, condition met, deadline), using the existing capture | Model turns, wall time, success on matched tasks | Continue if turns drop ≥20% at equal success |
| S2 Exact checks and guarded plans | Exact, scoped selectors (name, role, app/window, enabled/checked); yes/no/unknown results; per-step `expect`; run-time targets; one deadline per plan; per-step outcomes (dispatched, observed, contradicted, unknown) | Turns, wrong-action rate, trap tasks (unexpected dialog, disabled button, duplicate labels) | Continue if turns drop ≥30% without lower success or more wrong actions |
| S3 Private browser and procedures | BiDi adapter for private Firefox (DOM targets, background tabs); three hand-written procedures with parameters, preconditions and independent output checks | Turns and time vs. pixels; procedure warm runs vs. first runs | Keep each if faster at equal success |
| S4 Host hardening | Lock and overlay refusal, fresh screenshot after the person's activity, then the maintainer's Firefox via BiDi with explicit approval | Refusal tests in a private stand-in host | Required before long plans on the host |
| S5 Later, if justified | Damage-based capture; OCR targets on the host (measure precision when accepted and abstention, not one accuracy figure); task-scoped route memory from successful traces instead of general crawling; parallel sessions for independent tasks | As before | Only when a measured task shows it is the bottleneck |

Cut from the near-term plan: generic breadth-first navigation crawling,
speculative mutations, racing two sessions on the same external write,
learned noise masks, and automatic procedure induction.

## 6. Unattended work and authorisation

The maintainer intends to leave the laptop running for testing.

- **Allowed without further approval:** private sessions, the desktop test suite,
  scripts and benchmark harnesses, reversible project-local experiments, PRs
  and merging green PRs (existing delegation), agent runs within the
  maintainer's allowance (dry-run first).
- **Needs a specific, recorded approval:** host sessions on the real screen,
  restarting the maintainer's Firefox with remote debugging or installing
  anything into personal profiles, host configuration changes. A host session
  can be pre-approved from a terminal (`agent-desktop host start --minutes N`,
  at most 240) but should not be used unattended for tasks touching personal
  accounts.
- **Power:** the keep-awake hook prevents idle suspend while a turn runs; lid
  close still suspends, so keep the lid open and the charger connected.
- **Load:** the machine is free while the maintainer is away, so longer test
  runs are acceptable; check `ps` first in case something else is running.

## 7. Risks

- Guarded plans make wrong actions faster too: commit points, trap-task tests
  and "never retry an uncertain step" stay mandatory.
- Text deltas can omit what mattered; keep keyframes on large or unexpected
  change and let the model request a full frame.
- Exploration clicks things: only in disposable sessions, skip destructive
  controls, never against remote accounts without approval.
- Browser remote control exposes a powerful local endpoint; bind it to the
  loopback interface, protect it, and enable it only for an approved session.

## Sources

- Dong et al., *Why Are GUI Agents Correct but Late?* arXiv 2607.28399 (2026).
- Liu, Kundu, Beerel, *Speculative Macro Commit for Faster Tool-Using Agents*,
  arXiv 2609.03236 (2026).
- *Speculative Actions: A Lossless Framework for Faster Agentic Systems*,
  arXiv 2510.04371.
- wlr-screencopy-unstable-v1 (`copy_with_damage`, `damage`), wayland.app;
  ext-image-copy-capture-v1 frame damage.
- Firefox WebDriver BiDi: firefox-source-docs `remote/webdriver-bidi/Extensions`;
  MDN *Create a WebDriver BiDi connection*.
- Hyprland wiki: `hyprctl output create headless`; `sendshortcut` dispatcher.
