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
| Q2 | Is testing desktop software in scope? | Yes. The maintainer decided this on 2026-11-10, and section 1 of the [archived plan](archive/PROJECT_PLAN-history.md#1-read-this-first) is updated to match | Decided |
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
| N10 | Desktop subagent spike | Big directions B1, tool-schema cost | A Claude Code agent definition holding only the desktop tools, run against direct tools on E0 tasks and one console task. Also measure what the 29 tool schemas cost | None | Gate: main-context tokens fall 50% at equal success, with wall time no more than 10% worse. The result is recorded either way | #163, pilot done 2026-11-11: context −93–97%, cost −75%, wall time +51–58%, so the gate was not met (docs/research/2026-11-11-desktop-subagent-pilot.md); same-model arm 2026-11-12: wall time +96–111% and cost above direct, so the delay is delegation itself |

Suggested order: N1 first, as the maintainer's accepted follow-up order has it. N2 and
N5 are small and can go alongside it. Then N3 and N4, then N6 and N7. Accepted
follow-ups 2 and 3 move later because N7 needs N2, and the small fixes clear faster. N9 and N10 can
run in parallel at any point. N8 waits until shell testing resumes.

### Next

| ID | Item | Source | Depends on |
| --- | --- | --- | --- |
| X1 | F1: correctness under interruption | Roadmap F1 | N9; first patch (killed helper's lease) done 2026-11-11; interruption during checks fixed 2026-11-12; remaining steps in #181 |
| X2 | F2: three end-to-end acceptance workflows. This also carries the M4 gate of matched trials on representative workflows. The browser dataset edit has a deterministic driver (`test_dataset_workflow`) and an agent task (`--suite f2`; two runs on one seed passed on 2026-11-12, without injected failures); the native document edit has a deterministic driver (`test_document_workflow`, 2026-11-12); more agent-driven runs, an agent task for the document edit and the mixed workflow remain | Roadmap F2, M4 | X1 |
| X3 | F3: persistence and lifecycle stress | Roadmap F3 | X1 |
| X4 | Event stream and an approve/deny/take API. This is the "structured events" contract in USER_EXPERIENCE.md and the start of B3. It includes a non-blocking wait for control to return | Big directions B3, USER_EXPERIENCE.md, 2026-10-15 list | N2, N5; contract proposed 2026-11-11 (EVENT_CONTRACT.md); first version done 2026-11-11 (agent-desktop events) |
| X5 | Focus a window on another Hyprland workspace (windows have reported their workspace since #149) | 2026-10-15 list | None; works: activation switches workspace in Hyprland 0.57.1 (nested stand-in 2026-11-11, the maintainer's screen 2026-11-12) |
| X6 | Host screenshots that wait for compositor animations | 2026-10-15 list | None; done 2026-11-11; seen on the maintainer's screen 2026-11-12 (a workspace switch captured whole after 737 ms) |
| X7 | Richer `find` items for buttons, with a class and a usable selector | 2026-10-15 list | None; done 2026-11-11 |
| X8 | Add a profile to a running session | 2026-10-15 list | None |
| X9 | Two checks on the maintainer's machine, with no code: the off-screen host refusal on a real inactive terminal, and layout-aware key placement on a real host session | Hyprland report residuals, development log 2026-11-08 | None; layout placement confirmed on the maintainer's screen 2026-11-12 (text, `ctrl+l`, `logo+h` under US Dvorak). The off-screen refusal still needs the person to switch terminals |
| X10 | A host action that opens a URL in the person's running Firefox | Hyprland report, notes from 2026-10-15 | None; done 2026-11-11; seen on the maintainer's screen 2026-11-12: the tab opened in an existing Firefox window, which stayed in the background |
| X11 | Place letters for a nested Hyprland's layout when keys go through the parent labwc (split from N8) | Development log 2026-11-08, N8 | None |
| X12 | Fedora drops the first typed character in Chromium, now and then (Checks run 43089078794). Loop `test_chromium_receives_every_character` locally under load with the store's Chromium. Local loop on 2026-11-11: 20 of 20 passed under load on NixOS with Chromium 156, so it does not reproduce here; it needs a Fedora machine. Fedora 44 VM on 2026-11-12: 60 of 60 as a user (50 under 4-CPU load) and 20 of 20 as root with `--no-sandbox` under load, run alone rather than mid-suite, so it does not reproduce there either | Development log 2026-11-11 | None |
| X13 | Accessibility on SELinux-enforcing Fedora. When the session's private `dbus-daemon` (`unconfined_dbusd_t`) activates `org.a11y.Bus`, the policy computes `gnome_atspi_t` for `at-spi-bus-launcher`, which is not valid for the user's role (`SELINUX_ERR invalid_context`), so the exec is refused. Sessions now start without accessibility and say why (2026-11-12). Done 2026-11-12: the worker starts the launcher itself (keeping its own context) and waits for `org.a11y.Bus` before the registry; on the enforcing Fedora VM `test_ui` passed with accessibility on | Fedora 44 VM, development log 2026-11-12 | None |

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
| P10 | Strong isolation and the portable machine (sections 7D and 7E of the [archived plan](archive/PROJECT_PLAN-history.md#7-extensions-discussed--preserve-do-not-implement-all-now)) | Needs a threat-model decision |
| P11 | Effect-ledger and atlas follow-ups: making the ledger default-on, dconf and SQLite decoders, an ignore list, settings maps at scale, and document review with revert ([effect ledger](../research/2026-10-08-effect-ledger.md) next steps) | They belong to D3, which is weakened. Effect contracts were done as R4/R5a. Document revert overlaps L5. The speed plan's leftover S3 procedures fall under P4, and its S4 host hardening (lock and display-off refusal) has mostly shipped, though it was not rechecked in detail for this plan |
| P12 | Section 7B–7C ideas of the [archived plan](archive/PROJECT_PLAN-history.md#7-extensions-discussed--preserve-do-not-implement-all-now) not listed above: replay and GUI tests from traces, base and patched comparisons, and task-bound worktrees | Testing desktop software is now in scope (Q2), so revive these as rows when a testing task needs them |

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

## History

The earlier narrative (alpha work, the research progression of October 2026, the
field-report follow-ups, and the original sections 1–10 with milestones, extensions
and technical references) is kept verbatim in
[archive/PROJECT_PLAN-history.md](archive/PROJECT_PLAN-history.md). It is a historical record, not current
direction.
