# Agent Desktop project plan

Updated: 2026-10-05. This document records the chosen direction, implemented
stages and remaining release gates. See the [development log](DEVELOPMENT_LOG.md)
for exact validation, failures and historical changes. The runtime is experimental;
implemented features are not a claim of universal compatibility.

## Development status

Repository: `FilipNowakowicz/agent-desktop` (private). Development stages use
pull requests; successful stages may be integrated after checks. Every stage must
update this status and the development log with completed work and remaining gaps.

| Stage | State (after the 2026-10-05 review) | Release gate still open |
| --- | --- | --- |
| M0 | Demonstrated on the initial NixOS machine | Keep regression coverage; do not repeat reconnaissance |
| M1 | Implemented and repeatedly tested; hardening continues | Eight-hour soak (running), loaded repetitions of the unexplained typing symptoms (F006), remaining lifecycle edges (both supervisors dead, profile recovery state) |
| M2 | MCP and viewer tested; cooperative takeover, profiles and one exclusive controller per session (lease) implemented | Real login/resume by the user; takeover with the user's US Dvorak layout; takeover is not a confidentiality boundary |
| M3 | Two supported installs: Nix runtime with the X11 repair (CI `nix` job) and Ubuntu 24.04 apt recipe (CI, plus a fresh-VM check); runtime selected automatically; pilot started (3/3 sessions, docs/trials/pilot.md) | Pilot to at least 20 sessions over 10 working days, including runs through MCP; a graphical Ubuntu desktop install |
| M4 | Exploratory suites and restricted comparisons | Representative workflows, matched paired trials, provenance and uncertainty |
| Extensions A/B | Waits, sequences, crops, semantic UI, takeover, profiles, host guard implemented | Validate usefulness and failure behaviour in real work before expanding |
| Portable machine / strong isolation | Deferred options | Explicit product and threat-model decision, then targeted feasibility evidence |

Next work follows the [review plan](docs/reviews/2026-10-05-project-review/plan.md),
with the review's open questions decided in
[decisions.md](docs/reviews/2026-10-05-project-review/decisions.md). Implemented:
correctness fixes (#42–#44), preflight (#46–#47), bounded retention (#48), environment
hygiene (#49), the two installation paths with automatic runtime selection (#52), the
controller lease (#55), no keyring prompts (#56) and the action trace (#58). Remaining:
the pilot ([diary](docs/trials/pilot.md)), the eight-hour soak and loaded typing
repetitions, a user-run login handoff, and submitting the wlroots fix upstream
([runtime/UPSTREAM.md](runtime/UPSTREAM.md), which needs the maintainer's account).
Extensions should follow observed pilot needs.

Visible mode is an explicitly requested testing option: a nested labwc window on
the host Wayland desktop, with its own application environment and targeted input.
Opening it can take host focus; closing it ends that session. It is separate from
the implemented read-only viewer, whose disconnection preserves a headless session.

## 1. Read this first

The project is Linux-first, with initial local validation on NixOS + Hyprland and headless CI on Ubuntu, Fedora and Arch. Other desktop installations need separate validation.

The objective is **general computer use by existing agents**, beginning with a private desktop. Do not redirect the project into a specialized bug investigator or GUI testing framework. Testing and diagnostics can support general computer use; the project should retain that broader scope.

Working product description:

> Give your coding agent a Linux desktop. Let it work across applications while you keep using your computer.

Build a small working foundation, use it, and improve it from observed failures. Reuse existing Linux infrastructure. Recreating a small integration layer is acceptable for learning and ownership; there is no requirement to invent a new compositor or train a model.

### Files and authority

- `PROJECT_PLAN.md` — current direction, proposed architecture, milestones, extensions and handoff.
- `START_HERE.md` — portable orientation and continuation workflow.
- `RESEARCH_FINDINGS.md` — initial research and dated popularity snapshot. Its debugging-first recommendation was subsequently superseded by the broader direction in this plan.

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

The physical host compositor need not match the agent's compositor. The M0 experiment selected a private labwc/wlroots-based session and verified headless screenshots plus keyboard/mouse delivery. It is the implemented runtime backend; general application compatibility and production reliability are not established. See `DEVELOPMENT_LOG.md`.

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

- The planning conversation created no implementation or running desktop. Development subsequently completed the M0 experiment; temporary runtime packages were fetched without host activation. See `DEVELOPMENT_LOG.md`.
- Development is underway; `START_HERE.md` provides contributor orientation for the implemented stages and remaining issues.
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
