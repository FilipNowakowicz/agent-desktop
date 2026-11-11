# Agent Desktop project plan

Updated: 2026-11-11. This document records the chosen direction, implemented
stages and remaining release gates. See the [development log](DEVELOPMENT_LOG.md)
for exact validation, failures and historical changes. The runtime is experimental;
implemented features are not a claim of universal compatibility.

## Execution plan (2026-11-11)

This is the single ordered list of work that is planned or proposed. It collects the
field-report follow-ups, the functionality roadmap, the open items from daily use,
the [directions board](DIRECTIONS.md) and the
[big-directions notes](../research/2026-11-10-big-directions-wip.md), and puts each
item in exactly one place. The sections further down remain the sources and the
history; where they give an order, this plan replaces it.

How to use it:

- **Now** items fit in one pull request each and are grouped into three GitHub
  issues: #161 (account-bound web work), #162 (runtime and observation fixes) and
  #163 (foundations). Start them in any
  order unless a dependency is listed, with at most three in flight.
- **Next** items start when Now items finish or their dependency lands. Open the
  issue when the item starts.
- **Later** items need a result from Now or Next, or a maintainer decision.
- **Parked** items stay recorded with the reason. They come back only with new
  evidence or a decision.
- Each pull request branches from `main`, runs the local desktop suite from
  [VALIDATION.md](../VALIDATION.md), adds a development log entry and updates its
  row here. The full Checks matrix runs only for runtime, packaging or CI changes.

### Decisions for the maintainer

On 2026-11-11 the maintainer accepted the proposed defaults.

| # | Question | Proposed default | Affects |
| --- | --- | --- | --- |
| Q1 | Should the F1–F3 roadmap or the field follow-ups be the main line? | **Decided 2026-11-11:** field follow-ups first. The F0 audit runs alongside them and feeds F1, and F1–F3 follow in Next | Order only |
| Q2 | Is testing desktop software in scope? | Yes. The maintainer decided this on 2026-11-10, and section 1 is updated to match | Decided |
| Q3 | Should the personal desktop drive B3 and B5, with the shell widgets kept in the NixOS configuration repository? | **Decided 2026-11-11:** yes. The general contract lives here | L1, L3 |
| Q4 | May B2 generate calls to sites' internal endpoints, on the maintainer's own accounts only? | **Decided 2026-11-11:** not now. B2 stays parked | P1 |
| Q5 | Should the agent-workflow repository be frozen? | **Decided 2026-11-11:** this repository needs no action | None |

### Now

| ID | Item | Source | Scope (one PR) | Depends on | Acceptance | Issue |
| --- | --- | --- | --- | --- | --- | --- |
| N1 | Move secrets without the agent reading them | Cloud report #1 | A browser step and a clipboard source that send an element's text or the session clipboard to a command's stdin or a 0600 file. It returns only the length, a short prefix and a digest | None | A planted secret appears at its destination byte for byte, and nowhere in tool results, action traces, operation journals, effect reports, review output or logs. Missing or ambiguous sources are refused | #161, done in #165 |
| N2 | Commands that run as printed | Cloud report #4 | `take_command`, `paste_command` and the `import-cookies` instruction are built from how the server was started, or the CLI goes on PATH through a documented `uv tool install` | None | With the server started as `uv --directory … run agent-desktop-mcp` and no CLI on PATH, every printed command runs | #161, done 2026-11-11 |
| N3 | Show when a click changes nothing | Cloud report #5 | When a browser click targets a checkbox, switch or radio, or its label, report the checked state before and after | None | In a fixture where a label click does not toggle the control, the step reports it unchanged. An ordinary toggle reports the change | #162, done 2026-11-11 |
| N4 | Session size and sharper crops | Cloud report #6, `--scale` above 1 | A size option for create through the CLI and MCP, possibly with a larger default for browser work, and crop scales up to 2 | None | The Firefox viewport follows the requested size, `status` reports it, and invalid sizes are refused | #162, done 2026-11-11 |
| N5 | Count stopped steps, uncertain steps and fixed waits in `activity` | Cloud report #7, the fixed-sleep habit | Summary counts, plus server-instruction text that prefers waiting for text or a selector after `open` | None | Counts from a fixture trace match the trace exactly | #162, done 2026-11-11 |
| N6 | Account-aware cookie imports and removing a site | Cloud report #3 | Warn when an import brings several signed-in accounts for one site, and add a supported command that drops one site's cookies and storage from a profile | None | The fixture profile's warning fires. Removal leaves other sites untouched and is refused while the profile is in use | #161, done 2026-11-11 |
| N7 | A login route that sites accept | Cloud report #2 | Stage a: documentation, plus an up-front warning for sites known to refuse. Stage b: the human's turn runs the profile's Firefox without the remote agent, and it restarts under BiDi after release | N2 | A fixture sees `navigator.webdriver` false during the human's turn. After release the bridge reconnects with the profile's new cookies | #161, done 2026-11-11 |
| N8 | Nested Hyprland testing in guarded sessions | Cloud report #8, Hyprland report residual | Allow `hyprctl` against a nested instance that the guarded session started, document how to find the matching Mesa, and place letters for a nested compositor's layout | None | `hyprctl` reaches the session's own nested instance and is still refused for the host | #162, hyprctl and Mesa done 2026-11-11; nested layout moved to X11 |
| N9 | F0 baseline and gap inventory | [Roadmap](FUNCTIONALITY_ROADMAP.md) F0, R1–R6 limits | A capability matrix of each contract (implemented and tested, implemented but untested, missing, or unsupported) with links to source and tests | None | The matrix exists, and the first F1 failure is named with its smallest reproducer | #163, done 2026-11-11 |
| N10 | Desktop subagent spike | Big directions B1, tool-schema cost | A Claude Code agent definition holding only the desktop tools, run against direct tools on E0 tasks and one console task. Also measure what the 29 tool schemas cost | None | Gate: main-context tokens fall 50% at equal success, with wall time no more than 10% worse. The result is recorded either way | #163, pilot done 2026-11-11: context −93–97%, cost −75%, wall time +51–58%, so the gate was not met (docs/research/2026-11-11-desktop-subagent-pilot.md) |

Suggested order: N1 first, as the maintainer's accepted follow-up order has it. N2 and
N5 are small and can go alongside it. Then N3 and N4, then N6 and N7. Accepted
follow-ups 2 and 3 move later because N7 needs N2, and the small fixes clear faster. N9 and N10 can
run in parallel at any point. N8 waits until shell testing resumes.

### Next

| ID | Item | Source | Depends on |
| --- | --- | --- | --- |
| X1 | F1: correctness under interruption | Roadmap F1 | N9; first patch (killed helper's lease) done 2026-11-11; remaining steps in #181 |
| X2 | F2: three end-to-end acceptance workflows. This also carries the M4 gate of matched trials on representative workflows | Roadmap F2, M4 | X1 |
| X3 | F3: persistence and lifecycle stress | Roadmap F3 | X1 |
| X4 | Event stream and an approve/deny/take API. This is the "structured events" contract in USER_EXPERIENCE.md and the start of B3. It includes a non-blocking wait for control to return | Big directions B3, USER_EXPERIENCE.md, 2026-10-15 list | N2, N5; contract proposed 2026-11-11 (EVENT_CONTRACT.md); first version done 2026-11-11 (agent-desktop events) |
| X5 | Focus a window on another Hyprland workspace (windows have reported their workspace since #149) | 2026-10-15 list | None; works already: activation switches workspace in Hyprland 0.57.1 (nested stand-in, 2026-11-11) |
| X6 | Host screenshots that wait for compositor animations | 2026-10-15 list | None; done 2026-11-11 with stand-ins; not yet seen on the real screen |
| X7 | Richer `find` items for buttons, with a class and a usable selector | 2026-10-15 list | None; done 2026-11-11 |
| X8 | Add a profile to a running session | 2026-10-15 list | None |
| X9 | Two checks on the maintainer's machine, with no code: the off-screen host refusal on a real inactive terminal, and layout-aware key placement on a real host session | Hyprland report residuals, development log 2026-11-08 | None |
| X10 | A host action that opens a URL in the person's running Firefox | Hyprland report, notes from 2026-10-15 | None; done 2026-11-11 with stand-ins; not yet seen on the real screen |
| X11 | Place letters for a nested Hyprland's layout when keys go through the parent labwc (split from N8) | Development log 2026-11-08, N8 | None |
| X12 | Fedora drops the first typed character in Chromium, now and then (Checks run 43089078794). Loop `test_chromium_receives_every_character` locally under load with the store's Chromium | Development log 2026-11-11 | None |

### Later

| ID | Item | Source | Needs |
| --- | --- | --- | --- |
| L1 | Agent-aware desktop: a notification-based handoff used for a week, then a second field report | B3 | X4, Q3; shell banners proposed in nixos-config#498 (open, for the maintainer's review) |
| L2 | QEMU VM session type driven through its display and QMP input. Cheapest test: change the boot order in OVMF setup, then reboot | C3 route 1 | None. Comes before L3 |
| L3 | Preview a NixOS rebuild in a VM before switching | B5 | L2, Q3 |
| L4 | A system for developing and maintaining NixOS with Claude | C1 | L3 |
| L5 | Forkable sessions pinned with Nix. Cheapest test: fork and discard on a settings task | B4 | None |
| L6 | Structured access for Electron apps through the DevTools protocol: one app, A/B tested against pixels | D2 | None |
| L7 | Human interface slices 1–5, along with [PRODUCT_DIRECTION.md](PRODUCT_DIRECTION.md)'s open decisions on transport, toolkit, installer, supported application set and workspace retention | [USER_EXPERIENCE.md](USER_EXPERIENCE.md) | X1–X3 credible, X4 |
| L8 | Linux as the agent's computer on Windows or macOS (WSL2 or Lima) | C2 | A Windows or Mac machine |
| L9 | WebExtension that acts in the person's own Firefox | D10 | Weigh after N7 |

### Parked

| ID | Item | Reason |
| --- | --- | --- |
| P1 | B2: use the GUI once, then call the API | Waits on Q4 and N1 |
| P2 | D1 scripts and E6 skills | Gates missed (2026-10-13, 2026-10-14) |
| P3 | D3 effect first, E3 changed-only screenshots | Gates missed (2026-10-11). The features stay experimental |
| P4 | D4 learning from the person, and the procedure-validity research | Optional research and not a product prerequisite |
| P5 | D5 shared registry of app knowledge | Needs users and a publishing decision |
| P6 | D6 many desktops working in parallel | A product framing to revisit with L7 |
| P7 | D7 an intents layer for Linux applications | Long-term, and depends on application developers adopting it |
| P8 | D8 continuous agent, D9 small specialist model | Need API credits or a GPU |
| P9 | C3 route 2: physical machines through an IP-KVM device | Needs a hardware purchase; comes after L2 |
| P10 | Strong isolation and the portable machine (sections 7D and 7E) | Needs a threat-model decision |
| P11 | Effect-ledger and atlas follow-ups: making the ledger default-on, dconf and SQLite decoders, an ignore list, settings maps at scale, and document review with revert ([effect ledger](../research/2026-10-08-effect-ledger.md) next steps) | They belong to D3, which is weakened. Effect contracts were done as R4/R5a. Document revert overlaps L5. The speed plan's leftover S3 procedures fall under P4, and its S4 host hardening (lock and display-off refusal) has mostly shipped, though it was not rechecked in detail for this plan |
| P12 | Section 7B–7C ideas not listed above: replay and GUI tests from traces, base and patched comparisons, and task-bound worktrees | Testing desktop software is now in scope (Q2), so revive these as rows when a testing task needs them |

### Maintenance

- **wlroots patch:** check each new wlroots release's `xwayland_surface_associate` and
  retire the local patch once a release fixes it
  ([runtime/UPSTREAM.md](../../runtime/UPSTREAM.md)).
- **Fedora pin:** the Checks job is pinned to Fedora 44. Move it once a newer
  release ships the wlroots 0.19 development package the repair needs.
- **Security updates:** Dependabot and security updates are applied as they arrive.

## Current priority — functionality first (2026-10-23)

The maintainer reaffirmed a complete Linux desktop environment for existing
agents as the product goal and explicitly prioritised underlying functionality
over installation polish and user-interface implementation. The negative script
and reuse experiments do not invalidate that product; learned procedures remain
optional research rather than its foundation.

The saved conversation handoff is split into:

- [Product direction and architecture](PRODUCT_DIRECTION.md): decisions,
  MCP/API/CLI/UI responsibilities, sequencing, deferred ideas and open choices.
- [Functionality roadmap](FUNCTIONALITY_ROADMAP.md): audit current guarantees,
  test correctness under interruption, validate browser/native/mixed workflows,
  then persistence and lifecycle stress. Build on R1–R6 rather than repeat them.
- [Future first-install and human interface](USER_EXPERIENCE.md): installation,
  connection, viewer, takeover, login, artifacts, access and reconnect behavior.
  Preserve required backend contracts now; defer frontend implementation.
- [Procedure-validity research](../research/2026-10-22-procedure-validity.md):
  literature, competing baselines, independent checks, held-out variations and
  stop criteria. The bounded experiment is deferred, not the next product gate.

This priority supersedes older "next work" research recommendations below. The
[execution plan](#execution-plan-2026-11-11) orders it alongside the field follow-ups.
The handoff documents are plans, not new implemented capabilities. MCP remains
a supported headless interface to the same runtime used by direct integrations
and a future human UI. No new general agent or separate chat product is required.

## Development status

The current correctness stack implements these bounded stages:

| Stage | Implemented behavior | Remaining limits |
| --- | --- | --- |
| R1 | Incomplete UI reads refuse unique-target actions; stable browser context IDs and explicit recovery after target loss | Visible accessibility scope; tab identity is not document identity |
| R2 | Shared request/command budgets; completed prefixes and known delivery survive optional observation/effect failures; mutation-stage errors retain uncertainty | Already-issued application work may finish after disconnect; uncertain replies require reconciliation |
| R3 | Ordinary script groups stopped/reaped; bounded output and helper journals; deliberate session launches survive | Detached descendants are outside the cleanup contract; no sandbox or rollback |
| R4 | Observational effect reports; unknown baselines; bounded retention; watcher/document coverage and FODS support | Temporal evidence is not causal attribution or complete filesystem coverage |
| R5a | Experimental scoped file/config/UI/browser state predicates with satisfied, violated and unknown results | Checks describe current state, not task completion or action causality |
| R5b | Durable private GUI/browser jobs with per-step delivery evidence, reconnectable status, cooperative cancellation and optional scoped checks | No retry/resume/rollback; in-flight worker commands finish or remain uncertain. A crashed job's lease is given back by the next status read that finds it dead (2026-11-11) |
| R6 | Experimental offline evidence report separating requested actions, delivery, observations, scoped checks and recovery choices | Saved evidence is not newly verified; human review benefit is unmeasured |

The [original correctness review](../research/2026-10-15-completion-correctness.md)
and its probe output are retained as historical evidence from `711f1ca`.
Its repair proposals are superseded by the implemented stages above; its old
probe script is not a current regression suite. Procedure reuse remains deferred.

All planned correctness stages are implemented. Cumulative validation passed
285 local tests (19 skipped) and the Ubuntu/Nix/Fedora/Arch matrix;
see the development log for exact evidence. Each stage has a separate PR.
Legacy file waits and expectations use bounded regular-file reads, strict UTF-8
and read/path stability checks. The full matrix validates the combined stack before
integration; individual stages retain their focused and local desktop evidence.

A bounded R6 evidence-review experiment is available: saved run/operation/check
JSON becomes an offline HTML timeline that distinguishes delivery from checks,
keeps unknowns visible and exposes redacted evidence. The synthetic planted-
failure fixture and private-Firefox visual smoke validate presentation only;
human review benefit remains unmeasured. Reusable procedures, automatic replay,
a live review service and wider UI product work remain deferred.

Repository: `FilipNowakowicz/agent-desktop` (public since 2026-10-09). Development stages use
pull requests; successful stages may be integrated after checks. Every stage must
update this status and the development log with completed work and remaining gaps.

| Stage | State (after the 2026-10-05 review) | Release gate still open |
| --- | --- | --- |
| M0 | Demonstrated on the initial NixOS machine | Keep regression coverage; do not repeat reconnaissance |
| M1 | Complete. F006 explained and fixed (#76); the Fedora Chromium typing failure is not reproduced (20 of 20 under load); profiles record how their last session ended and recover one whose supervisors both died | None. Accepted limit: after both supervisors are killed, processes that cleared their environment escape token recovery (decisions.md, 2026-10-08) |
| M2 | Complete. MCP and viewer tested; cooperative takeover, profiles and the controller lease implemented; the maintainer's real login handoff persisted across sessions and their US Dvorak typing arrived exactly during takeover (2026-10-08) | None. Takeover is not a confidentiality boundary (decision 3) |
| M3 | Two supported installs: Nix runtime with the X11 repair (CI `nix` job) and Ubuntu 24.04 apt recipe (CI, a fresh-VM check and a GNOME desktop VM check); runtime selected automatically; pilot: first batch 17/20, second batch 20/20 on the fixed build, which meets the bar of 18 (docs/trials/pilot.md) | None. The maintainer's own use continues as feedback, not a gate (decisions.md, 2026-10-08) |
| M4 | Exploratory suites and restricted comparisons | Representative workflows, matched paired trials, provenance and uncertainty |
| Extensions A/B | Waits, sequences, crops, semantic UI, takeover, profiles, host guard implemented | Validate usefulness and failure behaviour in real work before expanding |
| Portable machine / strong isolation | Deferred options | Explicit product and threat-model decision, then targeted feasibility evidence |

Earlier alpha work followed the [review plan](../reviews/2026-10-05-project-review/plan.md),
with the review's open questions decided in
[decisions.md](../reviews/2026-10-05-project-review/decisions.md). Implemented:
correctness fixes (#42–#44), preflight (#46–#47), bounded retention (#48), environment
hygiene (#49), the two installation paths with automatic runtime selection (#52), the
controller lease (#55), no keyring prompts (#56), the action trace (#58), and the
two pilot batches with their fixes (#72–#79, [diary](../trials/pilot.md)).
The daily-use alpha gates are closed (2026-10-08). The wlroots fix was
proposed upstream as wlroots!5477 ([runtime/UPSTREAM.md](../../runtime/UPSTREAM.md)),
which was closed unmerged; the local patch stays until a release contains an
equivalent fix. The research progression below
is historical; current work follows the functionality-first priority above.

Research for the next direction: the
[2026-10-07 recommendation](../research/2026-10-07-next-direction.md) proposes
precise UI queries and checked actions as a bounded next experiment, followed by
reusable procedures if they improve verified outcomes. It compares alternatives,
develops the algebraic research options and specifies evaluation/stop criteria.
The maintainer adopted it as the next focus on 2026-10-08, once the alpha gates
closed. Broad platform fleets and model training remain
deferred; task-workspace review and scientific workflows are candidate later
experiments.

First result (2026-10-08, [effect ledger](../research/2026-10-08-effect-ledger.md)):
an experimental per-action report of files, windows and processes changed
(`AGENT_DESKTOP_EFFECTS=1`) cut Claude Code's input tokens by 25% on five
file-producing tasks (p = 0.016) without changing success, and showed that a
GUI setting's effect can be learned once and applied directly (a small,
verified settings map for Calc). Ranked next steps are in that report; the
ledger stays experimental until the open items there are done.

Second result (2026-10-09, [effect atlas](../research/2026-10-09-effect-atlas.md)):
model-free differential exploration mapped and verified 30 of Mousepad's and
75 of Geany's settings to configuration keys (and found swapped key names in
Geany). Applying a learned setting directly (`desktop_set`) halved the cost of
three of four settings tasks; a lookup without applying did not help.

Speed (2026-10-09, [research note](../research/2026-10-09-speed.md)): in the
host trial, 97–99% of wall time was outside the tool (model round trips), and 53
of 59 screenshots directly followed an input. Proposed next experiment: input
that returns the settled result (act and see), then guarded action plans with
targets resolved at run time and expectations, measured against matched arms.
The full plan, [beyond human speed](../research/2026-10-09-beyond-human-speed.md),
adds delta-coded observation (damage, keyframes, text deltas, surprise only),
navigation maps from model-free exploration, a browser bridge and verified
procedures, with staged stop criteria. An
[external review](../research/2026-10-09-astra-review.md) reordered it: S0
foundations (control gates and exact waits, done first), S1a act and observe
with existing capture, S2 exact checks and guarded plans, S3 private-browser
adapter and three checked procedures, S4 host hardening; damage capture, host
OCR and route memory only when a measured task needs them. General crawling and
speculative mutations are cut. S1a is done: input with `screenshot=true` cut
model turns 31% and input tokens 20% in a matched A/B
([act and observe](../research/2026-10-09-act-and-observe.md)). S2 guarded steps did not
meet their speed gate (turns −8%, not significant) and are kept for
reliability ([guarded steps](../research/2026-10-09-guarded-steps.md)). The private-Firefox
[browser bridge](../research/2026-10-09-browser-bridge.md), with batched
steps and row scoping, cut wall time 33% and input tokens 30% against pixels in
Firefox; host sessions can use the person's own Firefox in background tabs.

Next direction (proposed 2026-10-11, [effect first](../research/2026-10-11-effect-first.md)):
per-turn cost is unchanged (about 3 s; model API time is about 78% of wall time),
so the plan is to report exact effects (files, configuration, DOM and network)
so agents look less, and to test that with realistic unfamiliar tasks, cheaper
model tiers and an effect-first A/B gate (E0–E6). It also records the end state
(engine, MCP, a review app) and a Windows/macOS path. It needs no API credits;
an API agent loop and model tuning stay deferred.
Progress: E0's realistic suite is in place (#110) and its repeat runs meet the
variance gate except one task; E1 found every tier completes it, with Haiku
taking twice the turns at half the time per turn
([model tiers](../research/2026-10-11-model-tiers.md)). E2 did not meet its
gate: with Opus, turns −4.5% and looks −6.5% but wall time +15%; Haiku
unchanged ([effect-first A/B](../research/2026-10-11-effect-first-ab.md)). The
effect-first thesis is weak on this suite: E4 and E6 stop, the features stay
experimental. E3 (changed-only screenshots) did not meet its gate either:
input tokens about −7% for Opus, because a fixed prompt prefix, not images,
dominates them ([observation discipline](../research/2026-10-11-observation-discipline.md)).
Neither experiment reduced the number of turns, which is what dominates wall
time. A partial human baseline (three tasks, guided, 39–90 s against the
agents' 20–50 s) is in the benchmark guide. E5 is met: the private desktop runs
in a Claude Code cloud session, and three benchmark arms ran there in parallel
without slowing each other (development log, 2026-10-13). A new lever
for turns is a decision for the maintainer (see the directions board).

D1, the leading new direction, had its cheapest test on 2026-10-13
([D1 scripts](../research/2026-10-13-d1-scripts.md)): with Python scripts as
the only way to act, turns fell 4% and wall time rose 58%, so its gate
(turns −50%) is not met. E6, reopened as D1's reuse case, did not meet its gate
either ([E6 skills](../research/2026-10-14-e6-skills.md)): an agent given a
verified skill took 62–77% fewer turns but was only 1.3× faster on two tasks
and 2× slower on the paged table, where the skill itself was slow and, run
alone, wrong. Given the skill's path instead of its code, the agent reached
2.8–2.9× in two turns: the remaining time is the script's own.

Daily-use feedback (2026-10-15, a login-gated download moved to the host
session): the maintainer wants login-gated work to default to their own desktop
and existing Firefox logins, in the background and without restarting Firefox.
Done: browser `wait` takes `seconds`, a human request can be withdrawn, host
requests report up front whether the person's Firefox has a BiDi port, settled
screenshots keep the observation's scale, and the instructions offer the host
first for sites the user is signed into. Open, in rough order of value:
- the person's logins in the background. The BiDi port is ruled out for daily
  use (striped URL bar and robot icon; Cloudflare sometimes blocks it). Done:
  `import-cookies` copies chosen sites' cookies from their Firefox files into a
  named profile (copies go stale; session-only cookies and `localStorage` are
  not copied). Future option: a WebExtension with native messaging in their
  own Firefox, acting in background tabs with their live logins and no
  remote-control marks; it needs signing, a per-site permission model, and its
  synthetic events are untrusted (a few sites reject them);
- workspace awareness on the host: focusing a window on another Hyprland workspace
  (windows now report their workspace);
- host screenshots that wait for compositor animations (one caught a workspace
  switch halfway);
- richer `find` items for buttons (class, a usable selector);
- a non-blocking wait for control to return, and adding a profile to a running
  session.

The items still open in this list are tracked as X4–X8, X10 and L9 in the execution plan.

Field feedback (2026-11-08, [cloud setup report](../trials/2026-11-08-gcp-tailscale-setup.md)):
the maintainer had an agent do Google Cloud and Tailscale console setup in the
background with imported logins. Accepted for follow-up, in order (now tracked, with
some items merged, as N1–N8 in the execution plan above):
1. moving secrets without the agent reading them: a browser step that sends an
   element's text or the session clipboard to a command's stdin or a 0600 file and
   returns only length, prefix and digest (generated keys otherwise reach the
   transcript through `text`);
2. a login route sites accept: start the profile's Firefox without the remote agent
   for the human's turn, then restart it under BiDi (Google refuses sign-in in the
   controlled browser); until then, document `import-cookies --from` a clean profile
   and warn that the handoff fails there;
3. account-aware imports: warn when a site has several signed-in accounts, and a
   supported way to drop a site's cookies from a profile;
4. person-facing commands (`take_command`, `paste_command`, instruction text) that run
   as printed when the CLI is not on PATH;
5. reporting a switch or checkbox's checked state before and after a click, so a
   delivered click with no effect is visible;
6. a session size option for create (1280×720 left a console menu off-screen);
7. stopped and uncertain batch steps counted in `activity`;
8. for shell testing: allowing `hyprctl` against a nested instance a guarded session
   started, and guidance for the matching Mesa on NixOS.

Longer-range directions (writing programs instead of clicking, structured access to
every app, learning from the person, a shared skill registry and others) are
collected, untested, on the [directions board](DIRECTIONS.md). They are input
for later decisions, not current work.

Visible mode is an explicitly requested testing option: a nested labwc window on
the host Wayland desktop, with its own application environment and targeted input.
Opening it can take host focus; closing it ends that session. It is separate from
the implemented read-only viewer, whose disconnection preserves a headless session.

## 1. Read this first

The project is Linux-first, with initial local validation on NixOS + Hyprland and headless CI on Ubuntu, Fedora and Arch. Other desktop installations need separate validation.

The objective is **general computer use by existing agents**, beginning with a private desktop. Testing desktop applications and shells is in scope: the maintainer lifted the earlier "not a GUI testing framework" restriction on 2026-11-10 ([big-directions notes](../research/2026-11-10-big-directions-wip.md)). The project keeps the broader general-computer-use scope; do not narrow it into a specialized bug investigator.

Working product description:

> Give your coding agent a Linux desktop. Let it work across applications while you keep using your computer.

Build a small working foundation, use it, and improve it from observed failures. Reuse existing Linux infrastructure. Recreating a small integration layer is acceptable for learning and ownership; there is no requirement to invent a new compositor or train a model.

### Files and authority

- `docs/project/PROJECT_PLAN.md` — current direction, proposed architecture, milestones, extensions and handoff.
- `docs/project/START_HERE.md` — portable orientation and continuation workflow.
- `docs/project/RESEARCH_FINDINGS.md` — initial research and dated popularity snapshot. Its debugging-first recommendation was subsequently superseded by the broader direction in this plan.

The original brainstorming prompts were retired during documentation cleanup.
Their useful direction is preserved here, especially in sections 7A–7E; these
options are not commitments. The originals remain in Git history at
`1e9b20f21188b981b1a398e79aee10ccf924afc0` as `prompt1.txt` and `prompt2.txt`.
Current explicit user instructions take precedence over this plan. Technical
choices below distinguish the implemented foundation from recommendations to validate.

## 2. What the discussion established

### Motivation

An agent with shell access can already edit files, build software, inspect processes and run commands. Adding screenshots, semantic UI access and input lets it operate applications that need graphical interaction. A task can move naturally between shell, files, browsers and desktop applications.

Example intended experience:

> Set up this project, launch it, configure it through its settings window, and show me the working result.

The private desktop avoids stealing the user's focus, mouse, keyboard or visible workspace. An optional viewer allows observation, and `take` lets the user control a session (e.g. for logins).

### Important corrections to preserve

- Screenshots plus mouse/keyboard tools exposed to a capable agent already enable computer use. Calling the same thing a “complete computer agent” does not create a novel capability.
- Existing projects already cover much of the proposed functionality. The reproduce → diagnose → edit → verify workflow is not itself an established differentiator.
- No research performed here proves a revolutionary invention, an unserved market, commercial demand, or superiority over competitors.
- Conversely, documentation overlap does not prove that existing tools reliably satisfy the user's needs on this machine.
- The user hopes to create something useful and potentially attract thousands of GitHub stars. Stars are an ambition, not an acceptance criterion or forecast.
- The user did not connect with proposed pivots into a Linux failure investigator, automatic minimal bug-report generator, or runtime patch-diff tool. Do not revive these as the main project without a new user decision.
- OpenAI's work on computer use can both improve the models this tool uses and compete with it. Do not rely on providers neglecting Linux. Build an environment people might still want with excellent built-in agent computer control.

## 3. Competitive context

This is documentation research, not a hands-on comparison. None of these tools has been installed or benchmarked in this workspace.

| Project | Documented overlap and platform scope |
| --- | --- |
| [wbox-mcp](https://github.com/quazardous/wbox-mcp) | Private Linux compositor, headless operation, input, screenshots, MCP and logs. Also advertises native Windows control. Its README advertises Windows Sandbox support, but the Windows guide reviewed conflicted with that description; verify a pinned revision before relying on isolation claims. |
| [kde-mcp](https://github.com/atassis/kde-mcp) | KDE Plasma/Wayland control using AT-SPI, KWin and libei; headless KWin mode and viewer support. No native Windows backend was documented in this review. |
| [Cua](https://github.com/trycua/cua) | Broad computer-use stack: desktop driver, environments, SDK/CLI and evaluation tooling. Driver advertises Linux, Windows and macOS, with platform-dependent behavior. The README also describes shared desktops/handoff, so a viewer or human takeover alone is not a novel feature. |
| [E2B Desktop](https://github.com/e2b-dev/desktop) | Linux desktop sandbox with screenshots, input, windows and streaming. Using its SDK from Windows does not mean controlling native Windows applications. |

Check component licenses before reuse; a repository's headline license may not cover every component. Cua's reviewed documentation distinguished MIT components from source-available Spaces components.

### Public interest as of 2026-10-03

Counts were fetched from `https://api.github.com/repos/<owner>/<repo>` during the discussion.

| Repository | Stars | Forks |
| --- | ---: | ---: |
| trycua/cua | 27,931 | 1,974 |
| e2b-dev/desktop | 1,506 | 185 |
| quazardous/wbox-mcp | 10 | 2 |
| atassis/kde-mcp | 8 | 0 |

These are historical counts, not active-user or reliability measurements. Broad platform interest does not establish adoption of this particular workflow.

[OpenAI computer-use documentation](https://developers.openai.com/api/docs/guides/tools-computer-use) describes models operating desktop/browser interfaces through supplied environments and tools. It establishes existing capability, not a promise about future product support or a specific account's access.

## 4. Scope of the first release

### In scope

- Linux-first, tested initially on the user's NixOS + Hyprland machine.
- A separate, invisible graphical session with an explicit session identity.
- Launching supported ordinary GUI applications in that session.
- Screenshots while no viewer is connected.
- Window metadata where the selected compositor supports it.
- Session-targeted mouse, keyboard, text, scroll and drag operations.
- Reliable lifecycle, process ownership, logs and cleanup.
- A small CLI/core API, then a thin MCP adapter for an existing agent.
- Basic documented boundaries: graphical separation is not automatically a security sandbox.

### Deferred

- A new general agent, chat product, model or orchestration framework.
- Native Windows/macOS control, managed VMs or WSL provisioning.
- Multiple compositor implementations before one works well.
- Complete accessibility coverage, advanced automatic UI recovery or learned workflows.
- Full process snapshots, general deterministic replay or universal application support.
- Deep kernel telemetry, network interception or comprehensive host administration.

No GUI is needed for tasks that are better handled through an existing shell/API. The agent chooses the appropriate tool; do not force every operation through clicks.

## 5. Proposed architecture

```text
Existing agent
   │
   ├── CLI / local API
   └── MCP adapter
           │
      Session manager
           ├── launch + process lifecycle + bounded logs
           ├── observe: windows / screenshots / later AT-SPI
           ├── act: session-specific input
           ├── artifacts + action results
           └── one desktop backend
                  └── private headless compositor + optional Xwayland
                         └── task applications

Optional viewer connects to the session; closing it does not end the session.
```

### Choose the backend experimentally

The physical host compositor need not match the agent's compositor. The M0 experiment selected a private labwc/wlroots-based session and verified headless screenshots plus keyboard/mouse delivery. It is the implemented runtime backend; general application compatibility and production reliability are not established. See `docs/project/DEVELOPMENT_LOG.md`.

| Candidate | Reason to consider | What must be validated |
| --- | --- | --- |
| Headless labwc/wlroots-based session | Existing virtual input and capture tooling; close prior art | Headless startup, protocol availability, window enumeration, Xwayland and packaging |
| Headless Weston | Established compositor with documented headless backend | Actual rendering/capture/input path; do not assume wlroots tools work with it |
| Headless KWin | Prior art combining semantic control and private sessions | Dependency footprint, private-interface/version stability, session services |
| Separate headless Hyprland | Familiar environment and compositor IPC | Headless independence, startup requirements and input routing |
| Xvfb + lightweight window manager | Useful X11 baseline or fallback for an experiment | Does not establish native Wayland compatibility |

Select the simplest backend that passes the complete capture/input/isolation experiment. Keep its specifics behind a small module; do not build a universal backend framework upfront.

### Session design

- Every operation identifies its target session. No silent fallback to the host display.
- Deliberately configure display sockets and relevant environment variables; avoid inheriting host display/IPC addresses accidentally.
- Use separate task application profiles/configuration where needed. Test single-instance apps: a launch request may otherwise go to an existing host process.
- Investigate private session D-Bus, accessibility bus, portals and Xwayland together. A different `WAYLAND_DISPLAY` alone does not settle these concerns.
- Prefer input delivered directly to the private compositor. Host-global `uinput`/`ydotool` access is not proof of isolated input.
- Track owned processes and descendants. Destroy only resources belonging to that session; avoid broad process-name kills.
- Capture application stdout/stderr and compositor errors from the start, with bounded retention.
- Keep screenshot coordinate space explicit, including dimensions and scaling. Reject invalid coordinates and unknown sessions.
- Serialize input per session. Human takeover revokes agent input ownership and makes earlier observations stale.
- Bind any viewer/control endpoint locally by default; do not introduce remote access merely for the MVP.

### Illustrative interface, not a frozen specification

```text
desktop create
desktop launch SESSION -- application arguments...
desktop windows SESSION
desktop screenshot SESSION
desktop click SESSION X Y
desktop type SESSION TEXT
desktop key SESSION CHORD
desktop scroll SESSION ...
desktop drag SESSION ...
desktop logs SESSION
desktop view SESSION
desktop destroy SESSION
```

Return structured results/errors suitable for agents. Distinguish input delivered, expected state observed, timeout, application exit and unavailable capability. Initially, do not claim semantic success merely because a key event was sent.

## 6. Milestones and acceptance checks

### M0 — Short reconnaissance and one technical experiment

Read local instructions, inspect available tools and versions, and establish the current workspace state. Review only enough prior art to select an experiment; research must not become an indefinite prerequisite.

Run one separate compositor, launch a disposable test application, capture it invisibly, send isolated input, capture the visible change and tear it down. Record exact commands, versions, errors and the outcome.

**Exit:** evidence that the fundamental loop works on this machine, or a concrete failure that justifies trying the next backend.

### M1 — Small usable runtime

Turn the successful experiment into session lifecycle, launch, windows, screenshots, input and logs. Add a CLI and meaningful lifecycle/routing checks. Build only the abstractions needed for this backend.

**Acceptance:**

1. Applications appear only inside the private session.
2. Screenshots show the application without a viewer or physical output.
3. Typing/clicking changes only the intended session's application.
4. Host focus, workspace and pointer remain unaffected during ordinary use.
5. Native Wayland and, if supported, Xwayland behavior are recorded separately.
6. Text entry is checked with representative non-ASCII input and the user's keyboard layout; unsupported cases are explicit.
7. Repeated create/launch/interact/destroy runs clean up owned processes and sockets.
8. Invalid sessions and backend failure fail closed rather than reaching the host desktop.
9. An application crash yields a useful error and accessible logs.

### M2 — Agent integration and observation

Expose the working core through MCP, returning images and structured results in a form the chosen client can consume. Test the actual agent-client integration rather than assuming any MCP client has identical image/tool support.

Add a simple optional viewer when practical. Begin with observation; explicit pause/takeover can follow as a separate increment.

**Exit:** an existing agent completes a small real GUI task and checks its result while the user continues working. Viewer disconnection does not stop or alter the desktop.

### M3 — Daily use and broader Linux compatibility

Choose a small application set and publish tested versions/capabilities. Log failures encountered in actual work. Test at least one non-NixOS Linux distribution before describing the runtime as broadly compatible.

**Exit:** a documented install/launch path and repeatable tasks on the declared supported configurations. Packaging should make the same runtime convenient on NixOS without imposing NixOS on everyone else.

### M4 — Measured improvements

Build an initial suite of approximately 20 realistic tasks. Compare the same model, representative applications, starting state and comparable budgets across the implementation and relevant baselines. Record successes, failures, retries, user interventions, elapsed time and model usage.

Use the measured failure distribution to choose extensions. Do not interpret a larger feature list as a performance result.

## 7. Extensions discussed — preserve, do not implement all now

### A. Better interaction and observation

| Extension | Concrete behavior | How to establish value |
| --- | --- | --- |
| Stale-observation protection | Associate actions with observations; check target/layout changes and request a fresh observation when necessary | Fewer wrong actions under delayed dialogs, moving windows and loading states; acknowledge unavoidable races |
| Bounded action sequences (implemented, stops on layout changes) | Fill fields, click, then wait for an explicit condition; stop on surprises | Lower latency/model calls without a lower completion rate; no blind retries of non-idempotent actions |
| Adaptive observation (crops and scaled images implemented) | Filtered accessibility state, changed elements, crops and full images on demand | Lower actual model usage without missing task-critical changes |
| Semantic UI (AT-SPI tree and press/focus/set_text implemented) | AT-SPI names, roles, states and actions, with visual fallback | Better supported-app completion rate; no claims that semantic success proves visual correctness |
| Event-aware waiting (window and settled-screen waits implemented) | Wait for relevant window, UI or process changes with deadlines | Less unnecessary polling and fewer premature actions |
| Verified outcomes (window, UI element and settled-screen waits) | Separate action delivery from an observed postcondition | Fewer false success reports |

### B. Shared desktop experience

- Live viewer that is independent of session lifecycle.
- Explicit observe/agent/human/paused modes, with clean handoff and queued-action handling.
- Human demonstrates a correction; capture semantic targets, actions and results for the agent to resume.
- Later, propose parameterized reusable procedures and validate them from fresh state. Generalization beyond one screen is a research task, not guaranteed learning from a single demonstration.
- Multiple task desktops with separate profiles and a simple overview, after one session is dependable.

### C. State, reproducibility and debugging

- Worktree, shell, services and desktop associated with one task.
- Persistent environments for issues/branches and explicit reset to known initial state.
- Action timelines combining UI observations, application logs and process events.
- Later opt-in journal, network, filesystem, resource and D-Bus observations. Timestamp proximity is not proof of causation.
- Traces containing source revision, launch command, environment, actions, UI state and selected screenshots.
- Replay using selectors, fixtures, waits and assertions; an action log is not by itself reliable replay.
- Convert supported workflows into repeatable GUI tests.
- Compare base and patched revisions in separate fresh environments.
- Snapshot application data/files/services first. Full live process/VM snapshots are a separate, harder milestone.
- Restoring local state cannot reverse external transactions, messages or remote changes.
- Parallel experiments or independent verification environments later; no need for multi-agent orchestration in the first version.

### D. Permissions and isolation

- Optional observe-only, app-control, desktop-control and broader debugging capabilities.
- Explicit shared directories, credentials, network access and application launch permissions.
- Stronger process/filesystem isolation using appropriate existing container/VM primitives when justified.
- Action auditing and appropriate handling of sensitive screenshots/logs.
- Do not treat an app allowlist or private compositor as protection against an unrestricted shell with the same host permissions.

### E. Portable agent machine

The portable-machine proposal remains a deferred research direction. Possible
future architecture:

```text
Linux host → native runtime
Windows host → managed Linux environment → same runtime
macOS host → managed Linux environment → same runtime
```

- Evaluate WSL2 versus a managed VM later; neither is chosen. Test whether the
  headless desktop works independently of visible WSLg routing, and whether
  NixOS or Nix on another WSL distribution is practical.
- NixOS or Nix may pin/provision the environment without becoming a user-facing prerequisite.
- Native frontend could manage installation, updates, lifecycle, viewing, networking and repository access.
- Research host mounts versus guest-local repositories/worktree synchronization, file watching, credentials, GPU acceleration, image size, boot/resume and snapshot costs.
- A host bridge should expose selected capabilities rather than unrestricted host access.
- Measure environment update/rollback behavior, host/guest networking and
  isolation between task machines. Declarative packages do not make live state
  deterministic.
- Consider per-task, issue, branch or PR machines only after one dependable
  workflow. A frontend could manage provisioning and recovery without asking
  users to operate a VM manually. Keep natural core/backend boundaries; avoid
  abstractions introduced solely for hypothetical platform support.
- Linux application tests on a Windows host do not verify native Windows behavior. Native host control would require another backend.

## 8. Development conventions and boundaries

- The planning conversation created no implementation or running desktop. Development subsequently completed the M0 experiment; temporary runtime packages were fetched without host activation. See `docs/project/DEVELOPMENT_LOG.md`.
- Development is underway; `docs/project/START_HERE.md` provides contributor orientation for the implemented stages and remaining issues.
- The packaged persistent runtime uses uv-managed Python and headless labwc. Subreaper-based process ownership and persistent session-local input devices and supervisor-crash recovery are implemented; keep improvements grounded in experiments.
- Use `uv`, a uv-managed interpreter, `uv sync` and `uv run`; ignore `.venv`. Keep portable Python metadata. Do not add project Nix files solely to supply Python dependencies.
- Nix packaging or a NixOS test environment for the actual Linux runtime is a separate legitimate design choice. Follow current user/local instructions.
- For native wheel loading failures on NixOS, diagnose shared-library requirements and consider centralized workstation configuration rather than embedding machine-specific linker paths in the project.
- Do not activate/rebuild the host, close unrelated applications, or change persistent host permissions merely because they are convenient for a prototype. A project-local experiment should stay within its task resources; discuss any necessary broader host change concretely.
- Do not access personal browser profiles or credentials just to demonstrate GUI control; start with disposable app state.
- No agent/tool attribution trailers in commits or PR text.
- Update this plan with actual decisions and evidence as development proceeds; preserve original brainstorming files.

## 9. Open decisions for implementation

- Which compositor passes the full headless capture/input experiment most simply?
- Which tools/protocols provide capture, input and window metadata at pinned versions?
- Which session services need to be private for the chosen apps and future AT-SPI support?
- Which language and packaging approach makes lifecycle management and agent integration easiest to maintain?
- Which two or three applications are the initial compatibility targets?
- What viewer transport can be added without becoming a dependency of headless operation?
- What exact host access remains in the first version, and how is that documented?
- Is reuse of an existing project's component worthwhile after checking behavior and license?

## 10. Useful technical references

- [Weston backends and running Weston](https://wayland.pages.freedesktop.org/weston/toc/running-weston.html)
- [AT-SPI accessible objects and interfaces](https://docs.gtk.org/atspi2/class.Accessible.html)
- [AT-SPI session/accessibility bus details](https://github.com/GNOME/at-spi2-core/blob/main/bus/README.md)
- [Linux input userspace API](https://kernel.org/doc/html/latest/input/input_uapi.html)
- [wbox compositor/backend documentation](https://github.com/quazardous/wbox-mcp/blob/main/docs/backends.md)
- [wbox reported test matrix](https://github.com/quazardous/wbox-mcp/blob/main/docs/matrix.md)
- [Playwright Trace Viewer, an interaction-evidence reference](https://playwright.dev/docs/trace-viewer)

External documentation changes. Pin relevant versions during implementation and record observed results separately from advertised support.
