# Big directions, work in progress (2026-11-10)

**Status: work in progress. Thinking notes, not a plan or a promise.** Nothing
here is implemented or tested. Accepted ideas move to the
[directions board](../project/DIRECTIONS.md) with a status, and then into the
[project plan](../project/PROJECT_PLAN.md). The maintainer asked for directions
beyond the open follow-ups: something new or a large improvement, possibly linking
this repository with the NixOS configuration and the laptop's Hyprland workflow.

## What the evidence says so far

- **Value came when the desktop was one step inside a larger job.** In the
  [Hyprland report](../trials/2026-11-07-hyprland-overhaul.md) it was the test rig
  for a shell under development. In the
  [cloud setup report](../trials/2026-11-08-gcp-tailscale-setup.md) "the browser was
  the way to *get* API access, and stopped being needed once it had it".
- **Making the GUI loop faster is mostly used up as a lever.** Per-turn work gave
  14–33% on specific tasks. D1 (scripts), E2 (effect first) and E3 (changed-only
  screenshots) missed their gates, and turns, at about 3 s each and 78% model time,
  dominate wall time ([effect first](2026-10-11-effect-first.md)).
- **The tool surface is wider than its use.** The Hyprland sessions used 11 of 29
  tools; the cloud sessions were 70% `desktop_browser`. E3 found that a fixed prompt
  prefix, which includes the tool schemas, dominates input tokens.
- **The person is a bottleneck, not just the agent.** Both reports spend time on
  handoffs: commands the person had to run, a login that could not succeed, secrets
  passing through the transcript, host approvals.
- **Neighbouring repositories.** The NixOS configuration does not package or
  configure Agent Desktop. Its agent issue loop and `gcp-agent` host were removed on
  2026-11-09 (#492, #493) as unused. In this author's view the agent-workflow
  repository is best frozen apart from the parts still called
  (`agent-issue-readiness`, learning candidates), since Claude Code now provides
  subagents, scheduled agents and review.

## Candidates

Each one names the assumption it drops, what is new about it, a cheapest test and a
gate that would stop it. The order is the suggested order of testing, not of size.

### B1. A desktop subagent (cheap, days)

- **Assumption dropped:** the coding agent operates the desktop in its own context.
- **Idea:** ship a Claude Code agent definition (and later a plugin) that holds only
  the Agent Desktop tools and their instructions, runs on a cheaper tier, and returns
  a short result and evidence paths to the main agent. Screenshots and DOM dumps
  never enter the main context, and the main agent's tool prefix shrinks.
- **Why now:** E1 found Haiku completes the suite at half the time per turn. D9
  already suggested approximating a two-speed agent this way. Both reports show the
  GUI used in short bursts between CLI work, which is the shape a subagent fits.
- **Cheapest test:** E0 tasks and one replayed cloud-console task, main agent with
  direct tools against main agent with the subagent. Measure main-context tokens,
  wall time and success.
- **Gate:** main-context tokens −50% at equal success with wall time no worse than
  +10%. Otherwise record it and keep direct tools.
- **Side task:** measure the token cost of the 29 tool schemas, and what merging the
  rarely used ones would save.

### B2. Use the GUI once, call the API afterwards

- **Assumption dropped:** a repeated GUI task repeats the GUI.
- **Idea:** while an agent completes a web task in a private Firefox, record the
  page's network requests (WebDriver BiDi network events; the bridge would need to
  capture them). Afterwards, an agent turns the requests that caused the effect into
  a small script against the site's own endpoints, using the profile's cookies. The
  next run is HTTP calls, in milliseconds instead of minutes. When the script
  breaks, the GUI route still exists: fall back to it, capture again and regenerate.
- **Why it could be big:** it removes the GUI from repeated work entirely, which
  none of the tested directions did. E6's scripts replayed the GUI and stayed slow.
  It generalises the cloud report's finding into a tool.
- **Prior art:** [Integuru](https://github.com/Integuru-AI/Integuru) (YC W24,
  AGPL-3.0) generates integration code from a HAR file, cookies and a prompt, offline,
  and says its code breaks with no repair. Possible differences here, not yet
  checked: capture happens live in a session we control, effects and scoped checks
  verify the generated call, the GUI path repairs a broken script, and secrets go
  through a sink (cloud follow-up 1) instead of into the script.
- **Risks:** terms of service and computer-misuse law (keep to the person's own
  accounts and an explicit opt-in); CSRF tokens, request signing and anti-bot
  measures; state-changing endpoints replayed by mistake; a duplicate of Integuru if
  the differences do not hold.
- **Cheapest test:** three read-only or reversible tasks on sites the maintainer
  uses (for example listing Tailscale machines, reading GCP billing, one GitHub
  settings page). Capture once, generate, rerun five times.
- **Gate:** a rerun at least 10× faster than the agent's GUI run, with correct
  results on two of three sites and no unintended writes.

### B3. An agent-aware desktop

- **Assumption dropped:** the human side of the loop is a terminal and chat.
- **Idea:** the laptop's Quickshell shell becomes where the person sees and answers
  agents:
  - a panel or overview item for live private sessions (thumbnail, current activity,
    one click to watch or take over);
  - approvals and handoffs as shell prompts with buttons: host session,
    `request_human` with take control and paste password, secret-sink confirmations;
  - a hotkey to hand off a task: select a window or region, describe the task, and
    a background Claude takes it in a private session, with a notification when it
    needs the person or is done.
- **Split of work:** this repository provides a general event stream (sessions,
  needs-human, finished, uncertain steps) and a small approve/deny/take API, plus a
  flake and Home Manager module, so Nix stays optional. The Quickshell widgets live
  in the NixOS configuration. A start exists: host requests already appear as
  `notify-send` notifications (`src/agent_desktop/hostprompt.py`), and `view` and
  `take` already exist.
- **Why it could be big:** it removes the person's waiting and relaying, which the
  reports show, without needing GUI-agent speed. It is a first real version of the
  deferred [human interface](../project/USER_EXPERIENCE.md), built for one real user.
- **Risks:** much of it is personal setup, so the general contract must stay in this
  repository and the widgets outside it. Notifications that ask for approval must not
  become a way to approve by reflex.
- **Cheapest test:** the event stream plus one notification-based handoff
  (`request_human` with take and paste actions) used for a week of real tasks.
- **Gate:** the maintainer's time spent relaying commands goes to near zero in a
  second field report, with no approval given by mistake.

### B4. Reproducible, forkable sessions on Nix

- **Assumption dropped:** the session's applications and state are whatever the
  host has, and actions cannot be undone.
- **Idea, three parts:**
  1. any nixpkgs application on demand in a session, pinned by store path;
  2. atlases and skills keyed by that store path, which addresses D5's re-checking
     problem: a skill states exactly which build it was verified against;
  3. file-level fork and rollback of the session home (overlay or reflink copies),
     so an agent can try a risky configuration step, check it and discard it, or run
     two strategies side by side and keep the one whose checks pass.
- **Prior art:** [TClone](https://arxiv.org/abs/2605.17320) (2026) forks live GUI
  desktops copy-on-write for tree search and reports 1.9× and 1.5× lower task latency
  than KVM and CRIU on OSWorld; BranchFS and DeltaCR work on copy-on-write and
  checkpoint workspaces. Live forking is therefore not new. What might be new is the
  combination of pinned applications, verified skills and file-level forks without
  memory checkpoints, which is cheaper and covers configuration and document tasks.
- **Risks:** application memory state is lost on a file-level fork; it needs Nix,
  which must stay optional; overlay support differs between distributions.
- **Cheapest test:** fork-and-discard on a configuration task in the E0 suite
  (Mousepad or Geany settings) and a planted wrong step that is rolled back.
- **Gate:** rollback leaves the scoped checks identical to the fork point, and a
  two-branch run beats a single run's success rate on a task with a known trap.

### B5. Preview a NixOS rebuild before switching

- **Assumption dropped:** a desktop configuration change is seen only after
  switching to it.
- **Idea:** build the laptop configuration as a VM (`nixos-rebuild build-vm`), have
  Agent Desktop drive its display, and run checks on the shell (bar, launcher,
  notifications, keybinds) before the maintainer switches. This joins the
  configuration repository's KVM suite to this project's input and checks. This idea
  has not been searched for prior art.
- **Risks:** GPU-dependent Hyprland in a VM (virtio-gpu or software rendering); the
  VM differs from the real hardware (displays, DisplayLink); build cost, which the
  remote builder may absorb.
- **Cheapest test:** a planted regression in a branch (a broken Quickshell import or
  a missing bind) caught in the VM by an agent-driven check.
- **Gate:** the planted regression is caught, and a clean branch passes, in under
  10 minutes on the builder.

## Product angles and the market (searched 2026-11-10)

Quick web searches, mostly vendor blogs and comparison sites; not verified in depth.

| Area | State | Implication |
| --- | --- | --- |
| Hosted agent sandboxes and cloud desktops | Crowded and funded: E2B, Daytona, Cua (YC X25), OpenComputer, machine0 and others; Scrapybara reportedly shut down in October 2025 ([comparison](https://www.simular.ai/alternatives/cloud-computers-for-ai-agents)) | Do not compete as hosted infrastructure |
| Acting on the person's own screen | Model vendors ship it themselves (Claude computer use in the desktop app, Claude in Chrome) | A local tool wins only where they do not go: Linux, background private desktops, open source |
| Record once, replay without the model (browser) | Common: [Stagehand caching](https://docs.stagehand.dev/v3/best-practices/deterministic-agent), Workflow Use, Lightfeed, Intuned, Anchor | B2's replay half is not new. Only API generation with GUI repair might be, and Integuru covers part of that |
| Keeping credentials away from the model | Active for API calls: Infisical Agent Vault, WorkOS Relay, an IETF credential broker draft ([overview](https://agentgateway.dev/blog/2026-07-27-credential-injection-ai-agent-egress-cb4a/)) | The gap left is secrets that appear in a GUI (one-time key dialogs) and logins. Make that a feature, not a product |

Angles that still look open (not searched in depth):

1. **The Linux desktop's agent layer.** Model vendors build agents and clouds build
   sandboxes; nobody visible owns how a Linux desktop (Wayland compositors, portals,
   shells) exposes sessions, approvals, handoffs and application actions to agents.
   This is B3 combined with D7. Scale here means adoption and becoming a de facto
   interface (a portal-style protocol, Hyprland/KDE/GNOME integrations), not revenue.
2. **Agents that maintain a machine safely, via Nix.** Agents lack reversibility and
   reviewability; NixOS supplies both: declarative diffs, VM previews (B5),
   generations to roll back to, and pinned applications (B4). "An agent that keeps
   your Linux machine configured, every change previewed and reversible" combines this
   project with the configuration repository's practice. Prior art not yet searched.
3. **Agent testing of desktop applications and shells** was the strongest use in the
   Hyprland report, and is less crowded than web testing. It conflicts with this
   project's stated scope (general computer use, not a GUI testing framework), so it is
   a maintainer decision, perhaps as a separate project built on this runtime.

## Maintainer notes (2026-11-10)

- The "not a GUI testing framework" restriction in the project plan's first section
  is stale and no longer binding. Testing desktop applications and shells is in scope.
- Concern: few people use Nix and not many use Linux day to day. The ideas are still
  worth trying and recording; done very well, a Nix-community tool could get attention.
- Wanted: ways for people who do not use Linux directly to benefit (Linux as a
  backend or VM), and an agent that works below the operating system (installation,
  firmware settings, surviving reboots).

## C1. A system for developing and maintaining NixOS with Claude

- **Gap:** NixOS MCP servers found so far, such as
  [mcp-nixos](https://github.com/utensils/mcp-nixos) (about 450 stars by 2026-02),
  look up packages and options. None found edits, builds, previews, switches and rolls
  back a configuration as one loop.
- **Idea:** a flake plus a Claude Code plugin that gives any NixOS user the
  maintainer's configuration-repository practice:
  - tiered validation (evaluate, build, NixOS VM test, an Agent Desktop check of the
    desktop in a VM (B5), switch, post-switch health check, automatic rollback to the
    previous generation if the health check fails);
  - a NixOS module for a narrow passwordless command allowlist for agent rebuilds;
  - generation diffs (packages and options changed) summarised for review;
  - skills for reading evaluation and build errors and for option lookup.
- **Why Nix:** reversibility and reviewability are what agents lack, and Nix provides
  both. The audience is small but concentrated, technical and vocal.
- **Cheapest test:** extract the existing allowlist, validation tiers and rollback
  into a template; have a fresh agent make three real changes on a test VM, one of
  them a planted breakage, and check that the broken one is rolled back without help.

## C2. Linux as the agent's computer, not the person's

- **Idea:** the person keeps macOS or Windows; the agent gets a Linux desktop in a VM
  (Lima on macOS, WSL2 on Windows) or in the cloud (E5 already ran private desktops in
  a Claude Code cloud session). Nix builds the VM image, out of the person's sight.
  Logins come from the person's browser through `import-cookies`, extended to their
  Firefox or Chrome on the host system.
- **Competition:** [Cua](https://github.com/trycua/cua) already targets macOS,
  Windows and Linux sandboxes with a local QEMU provider. The difference would need to
  be the coexistence features (handoff, takeover, host-browser logins, effects and
  checks), not the VM.
- **Limits:** only Linux applications; most value is web work. Chrome cookies on
  macOS and Windows are encrypted with the system keychain or DPAPI. Headless
  compositors in WSL2 and Lima are untested here.
- **Cheapest test:** the existing E0 suite inside WSL2 on a Windows machine and in Lima
  on a Mac, unchanged.

## C3. Below the operating system

- **Two routes:**
  1. **Virtual machines (no hardware):** a session type that drives a QEMU VM through
     its display and QMP input, so the agent sees firmware (OVMF), boot loaders and
     installers, and survives the guest's reboots because it runs outside. This also
     serves B5 and C1's VM previews.
  2. **Physical machines:** an IP-KVM device (PiKVM, JetKVM, NanoKVM) emulates USB
     keyboard and mouse and captures HDMI, so the agent can enter BIOS setup and
     install a system. Servers expose Redfish/IPMI, where firmware settings are an API.
- **Prior art:** several early projects already put an MCP server or LLM in front of
  IP-KVM devices (jetkvm-mcp, kvm-pilot, HandsOn, Semantic Remote Control), and
  NanoKVM-Go advertises built-in MCP. Self-reported and early.
- **Note:** for NixOS installation, `nixos-anywhere` and kexec already avoid the
  firmware screen; the remaining need is firmware settings (boot order, Secure Boot,
  virtualisation) and machines with no network yet.
- **Risks:** firmware changes can make a machine unbootable; every such session needs
  explicit approval and a stated undo. A laptop cannot drive its own firmware; a second
  device must hold the agent.
- **Device choice (2026-11-10, prices from review sites, check before buying):**

  | Device | Price seen | For an agent |
  | --- | --- | --- |
  | PiKVM V4 Mini / Plus | about $270 / $385 | Fully GPLv3, documented HTTP and WebSocket API (screenshots, HID, mounting an ISO as a USB drive, ATX power on V4 Plus). Best interface, most expensive |
  | DIY PiKVM (Raspberry Pi 4 plus an HDMI-to-CSI bridge) | about the price of the parts | Same software and API, if a Pi is at hand |
  | JetKVM | about $89–130 | Open source, low latency, virtual media; WebRTC-based, so less simple to script; a community MCP server exists |
  | NanoKVM Lite / Full / Pro | about $40–87 / $155 | Cheapest, partly open source; earlier reports of weak default security and activation downloads; keep it on an isolated network |

  Laptops are a poor target: many do not show firmware screens on an external port,
  and power cannot be controlled. A desktop, mini PC or server suits it.
- **Cheapest test:** route 1. Change the boot order in an OVMF setup screen, reboot,
  and check that the guest booted from the chosen device.

## Where a deeper model fits

A deeper pass is worth it once one candidate is chosen. Suggested brief for B3:
"Design the event and approval contract between Agent Desktop and a desktop shell.
Inputs: the two field reports, `USER_EXPERIENCE.md` and the MCP tool list. Which human
moments must exist, which existing tools collapse into them, and what is the smallest
first version?" For B2: "Given BiDi network capture in a controlled Firefox, design
the capture, generation, verification and repair loop, and say where it must refuse."

## Open questions for the maintainer

- Is the personal desktop (B3, B5) in scope as a driver of this public project, with
  the widgets kept in the configuration repository?
- Is generating calls against sites' internal endpoints (B2) acceptable for the
  maintainer's own accounts?
- Should agent-workflow be frozen or archived?
