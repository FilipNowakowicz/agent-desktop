# Continue development in a new chat

Updated: 2026-10-04 (takeover, profiles, waiting, paste, action sequences and screenshot regions #29–#36; #17 closed). The hardened runtime, MCP tools and read-only
observer are implemented. Continue from the current status rather than repeating completed work.

Open `/home/user/private-agent-desktop` as the workspace and paste the following:

---

Continue development of the private Linux desktop for existing agents.

Read `AGENTS.md`, `PROJECT_PLAN.md`, `DEVELOPMENT_LOG.md`, `README.md` and `docs/COMPATIBILITY.md`. Inspect git status, source, GitHub issues and latest checks. The repository is `FilipNowakowicz/private-agent-desktop` and must remain private. `prompt1.txt` and `prompt2.txt` preserve the original brainstorm. The current plan supersedes the older debugging-first recommendation in `RESEARCH_FINDINGS.md`.

The chosen goal is general computer use by existing agents, starting with a private headless Linux desktop that does not interfere with my physical desktop. Develop on Linux and test on my NixOS + Hyprland machine; keep the core usable on other Linux distributions. Do not pivot this into a standalone debugging/testing product or attempt the future Windows/macOS platform now.

The working foundation uses Python/uv and private labwc sessions. Runtime dependencies are labwc, grim and dbus-daemon (optional: xwayland, wayvnc). The worker owns its process tree as a child subreaper with a guardian and a private bus. Input, window listing and focus use small built-in Wayland clients (virtual pointer/keyboard, foreign-toplevel). Screenshots return observation tokens that protect input against stale screenshots. M1 hardening (#5) is closed. CI runs on Ubuntu, Fedora and Arch. Chromium, xterm/Xwayland and GTK/Qt dialogs pass. Do not restart M0 unless a concrete failure justifies it.

Next priorities:

0. Agent-facing features added 2026-10-04 (all with real-compositor tests, no agent runs yet): human takeover for logins (`desktop_request_human`, `take [--paste]`, clipboard cleared on release), persistent named profiles, MCP server instructions, `desktop_wait` (window / settled screen), `desktop_actions` (bounded sequences that stop on layout changes), partial/scaled screenshots, AT-SPI semantic UI (`desktop_ui`, `desktop_ui_action`). Pending user tests: a real login handoff with a profile. Not yet measured: whether wait/actions/crops reduce agent calls or tokens; do that with a small benchmark once usage allows. Candidate next work: semantic UI coverage for Qt/Chromium/LibreOffice, verified outcomes, action timelines (extension C). Stacked PRs: retarget the dependent PR to `main` before merging and deleting its base branch, or GitHub closes it.
1. Benchmarks (M4): standard suite 20/20 (twice) and hard suite 10/10 (once) with Claude Code; see docs/BENCHMARK.md. Pass rate no longer separates results for this model. Office suite passed 2/2. Native/Cua GUI-only comparisons passed 6/6 each across two sets of three browser tasks, using 46/49 calls and $0.518/$0.529 API-equivalent usage ($1.047 of the user-authorized $5 total). Environments and caching differ, so this establishes no performance winner. Metrics are committed under `benchmarks/results`. `scripts/cua_benchmark.py` uses fresh local containers and a fixed-target GUI adapter. Next: repeated comparisons with matched environments, other models. The user's Claude Pro usage is limited: validate with `--dry-run` first, run agents sparingly and commit after each run. Human takeover (request/take/release) and persistent named login profiles are implemented.
   Later (user request): compare cost, tool design and approach with public projects such as Cua, and adopt what they do better.
2. Compatibility (#6): Mousepad Unicode file dialogs/private clipboards and Writer/Calc saved-file checks pass on all three CI distributions (#25–26). Remaining: broader applications, clipboard retention/images, widget readiness, desktop installs beyond CI containers. Stock labwc/wlroots 0.20.2 failed X11 mapping again in #28 CI 37211305391. Protocol tracing identified a buffer committed before X11 association; a project-local wlroots patch passed 150 loaded sessions, including one recovery. See runtime/README.md and DEVELOPMENT_LOG.md; source CI 37214448862 passed on all three distributions, including 100 loaded Arch X11 repetitions. Stock Fedora wlroots 0.19.3 subsequently failed in 37214999497; its matching repair now passes CI 37215643286: all three distributions green, with 100 loaded X11 repetitions each on Fedora and Arch. Stock 0.19.3/0.20.2 remain affected; use the optional repaired runtime explicitly. Human takeover is implemented.
Known visible-mode property: a focused nested window also receives host keyboard input.

Continue autonomously with project-local implementation and testing. Use stage branches and PRs, integrate successful stages after required checks, and keep the repo private. Update the plan and development log with completed work, validation, failures and next work. Notify me when my input is needed.

Proceed with project-local implementation and reversible experiments. Do not activate/rebuild my host, alter persistent system permissions, close unrelated apps or use personal browser profiles without specific authorization. If a host change is genuinely necessary, explain the exact change and why after completing the independent work.

Use uv-managed Python, `uv sync` and `uv run`; follow `AGENTS.md` for commit/PR conventions. Desktop separation is not a filesystem/network security sandbox. Keep the original two prompt files unchanged.

The immediate success criterion is: my agent can launch and operate an application in an invisible private desktop while I continue using my normal desktop, then tear its session down cleanly.

---
