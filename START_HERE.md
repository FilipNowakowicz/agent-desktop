# Continue development in a new chat

Updated: 2026-10-04 (after PR #16). The hardened runtime, MCP tools and read-only
observer are implemented. Continue from the current status rather than repeating completed work.

Open `/home/user/private-agent-desktop` as the workspace and paste the following:

---

Continue development of the private Linux desktop for existing agents.

Read `AGENTS.md`, `PROJECT_PLAN.md`, `DEVELOPMENT_LOG.md`, `README.md` and `docs/COMPATIBILITY.md`. Inspect git status, source, GitHub issues and latest checks. The repository is `FilipNowakowicz/private-agent-desktop` and must remain private. `prompt1.txt` and `prompt2.txt` preserve the original brainstorm. The current plan supersedes the older debugging-first recommendation in `RESEARCH_FINDINGS.md`.

The chosen goal is general computer use by existing agents, starting with a private headless Linux desktop that does not interfere with my physical desktop. Develop on Linux and test on my NixOS + Hyprland machine; keep the core usable on other Linux distributions. Do not pivot this into a standalone debugging/testing product or attempt the future Windows/macOS platform now.

The working foundation uses Python/uv and private labwc sessions. Runtime dependencies are labwc, grim and dbus-daemon (optional: xwayland, wayvnc). The worker owns its process tree as a child subreaper with a guardian and a private bus. Input, window listing and focus use small built-in Wayland clients (virtual pointer/keyboard, foreign-toplevel). Screenshots return observation tokens that protect input against stale screenshots. M1 hardening (#5) is closed. CI runs on Ubuntu, Fedora and Arch. Chromium, xterm/Xwayland and GTK/Qt dialogs pass. Do not restart M0 unless a concrete failure justifies it.

Next priorities:

1. Benchmarks (M4): standard suite 20/20 (twice) and hard suite 10/10 (once) with Claude Code; see docs/BENCHMARK.md. Pass rate no longer separates results for this model. Next: efficiency comparisons, other models, and baselines. The user's Claude Pro usage is limited: validate with `--dry-run` first, run agents sparingly and commit after each run. Human takeover/action ownership is not implemented.
   Later (user request): compare cost, tool design and approach with public projects such as Cua, and adopt what they do better.
2. Compatibility (#6): larger daily-use applications (editors, file choosers/portals, clipboard), desktop installs beyond CI containers. Investigate #17 with the uploaded CI artifacts when it recurs.
Known visible-mode property: a focused nested window also receives host keyboard input.

Continue autonomously with project-local implementation and testing. Use stage branches and PRs, integrate successful stages after required checks, and keep the repo private. Update the plan and development log with completed work, validation, failures and next work. Notify me when my input is needed.

Proceed with project-local implementation and reversible experiments. Do not activate/rebuild my host, alter persistent system permissions, close unrelated apps or use personal browser profiles without specific authorization. If a host change is genuinely necessary, explain the exact change and why after completing the independent work.

Use uv-managed Python, `uv sync` and `uv run`; follow `AGENTS.md` for commit/PR conventions. Desktop separation is not a filesystem/network security sandbox. Keep the original two prompt files unchanged.

The immediate success criterion is: my agent can launch and operate an application in an invisible private desktop while I continue using my normal desktop, then tear its session down cleanly.

---
