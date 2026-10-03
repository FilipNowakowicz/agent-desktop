# Start development in a new chat

Development update, 2026-10-03: M0 passed and M1's initial persistent runtime is implemented. Read
`DEVELOPMENT_LOG.md` and the current `PROJECT_PLAN.md` before using the original
starter prompt below. Continue from the current status rather than repeating completed work.

Open `/home/user/temp/gui` as the workspace and paste the following:

---

I want to start implementing the private Linux desktop for AI agents that we planned.

Read `PROJECT_PLAN.md` first. Then read `prompt1.txt` and `prompt2.txt` for the full original brainstorm, and `RESEARCH_FINDINGS.md` for earlier competitor research. The newer direction in `PROJECT_PLAN.md` supersedes the older debugging-first recommendation.

The chosen goal is general computer use by existing agents, starting with a private headless Linux desktop that does not interfere with my physical desktop. Develop on Linux and test on my NixOS + Hyprland machine; keep the core usable on other Linux distributions. Do not pivot this into a standalone debugging/testing product or attempt the future Windows/macOS platform now.

Start with milestone M0, then implement the smallest end-to-end version that works:

1. Inspect the workspace, applicable instructions and available system tools/versions.
2. Briefly examine the closest existing implementation and choose a compositor experiment. Reuse Linux infrastructure; do not begin with an elaborate backend framework.
3. Create a separate invisible session, launch a disposable GUI app, capture a screenshot, send input only to that session, and capture the resulting change.
4. Verify that my real workspace/focus/pointer were not disturbed and clean up only the session's own resources.
5. Turn the working experiment into a small CLI/core, then expose it to the agent through MCP. Add an optional viewer after the headless loop works.

Proceed with project-local implementation and reversible experiments. Do not activate/rebuild my host, alter persistent system permissions, close unrelated apps or use personal browser profiles without specific authorization. If a host change is genuinely necessary, explain the exact change and why after completing the independent work.

Use `uv` if choosing Python and follow my development instructions. No language or compositor has already been selected. Record actual decisions, commands, versions, validation results and remaining failures in the project documents. Keep the original two prompt files unchanged.

The immediate success criterion is: my agent can launch and operate an application in an invisible private desktop while I continue using my normal desktop, then tear its session down cleanly.

---
