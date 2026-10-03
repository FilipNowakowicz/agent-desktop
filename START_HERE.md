# Continue development in a new chat

Updated: 2026-10-04. The persistent runtime, MCP tools and read-only observer are
implemented. Continue from the current status rather than repeating completed work.

Open `/home/user/private-agent-desktop` as the workspace and paste the following:

---

Continue development of the private Linux desktop for existing agents.

Read `AGENTS.md`, `PROJECT_PLAN.md`, `DEVELOPMENT_LOG.md`, `README.md` and `docs/COMPATIBILITY.md`. Inspect git status, source, GitHub issues and latest checks. The repository is `FilipNowakowicz/private-agent-desktop` and must remain private. `prompt1.txt` and `prompt2.txt` preserve the original brainstorm. The current plan supersedes the older debugging-first recommendation in `RESEARCH_FINDINGS.md`.

The chosen goal is general computer use by existing agents, starting with a private headless Linux desktop that does not interfere with my physical desktop. Develop on Linux and test on my NixOS + Hyprland machine; keep the core usable on other Linux distributions. Do not pivot this into a standalone debugging/testing product or attempt the future Windows/macOS platform now.

The working foundation uses Python/uv and private labwc sessions. Persistent lifecycle, CLI input/screenshots/logs, stdio MCP image blocks, visible nested testing and a read-only viewer exist. Five stage PRs (#1, #2, #3, #4, #8) are merged. Ubuntu CI and a disposable native Wayland Chromium form task passed. Do not restart M0 unless a concrete failure justifies it.

Next priorities:

1. Runtime hardening (#5): input readiness, stronger ownership/cleanup for daemonizing applications, drag and repeated sessions under load. Visible mode has received an extra input character; its cause is unproven.
2. Interactive client integration (#7): MCP transport works, but no actual interactive client is configured. Determine the intended client before changing its persistent configuration; validate images and a real GUI task. Human takeover/action ownership is not implemented.
3. Compatibility (#6): more applications, Xwayland, keyboard layouts, resizing/scaling and Linux setup coverage. Terminal and Chromium fixture results do not establish universal support.
4. Benchmarks (M4): measure real task completion, cleanup failures and required human intervention once the core is dependable.

Continue autonomously with project-local implementation and testing. Use stage branches and PRs, integrate successful stages after required checks, and keep the repo private. Update the plan and development log with completed work, validation, failures and next work. Notify me when my input is needed.

Proceed with project-local implementation and reversible experiments. Do not activate/rebuild my host, alter persistent system permissions, close unrelated apps or use personal browser profiles without specific authorization. If a host change is genuinely necessary, explain the exact change and why after completing the independent work.

Use uv-managed Python, `uv sync` and `uv run`; follow `AGENTS.md` for commit/PR conventions. Desktop separation is not a filesystem/network security sandbox. Keep the original two prompt files unchanged.

The immediate success criterion is: my agent can launch and operate an application in an invisible private desktop while I continue using my normal desktop, then tear its session down cleanly.

---
