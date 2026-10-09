# Repository instructions

- Build a private Linux desktop for general computer use by existing agents.
  Read `CONTRIBUTING.md`, `docs/project/START_HERE.md` and
  `docs/project/PROJECT_PLAN.md` for workflow and current direction. Record
  decisions, exact validation and remaining failures in
  `docs/project/DEVELOPMENT_LOG.md`.
- Keep current product direction and deferred ideas in `docs/project/PROJECT_PLAN.md`.
- CI minutes are limited: PRs run only the Lint workflow. Run the desktop suite
  locally; trigger the full Checks matrix manually only for runtime, packaging or
  CI changes and milestones (see docs/VALIDATION.md).
- Use a branch and pull request for each development stage. Keep changes small
  enough to review. Report dependencies between stacked pull requests explicitly.
- Commit messages and pull request titles/bodies must not mention agent tooling
  or include tool attribution, session identifiers or Co-Authored-By trailers.
  Use the configured human author.
- Use uv-managed Python, `uv sync` and `uv run`. Keep Python dependency metadata
  portable and `.venv/` ignored. Do not add Nix files solely for Python dependencies.
- Diagnose native-wheel library failures before changing centralized workstation
  compatibility; do not embed machine-specific linker paths in this project.
- Keep runtime desktop dependencies distinct from Python dependencies. Nix can
  optionally provide the actual Linux runtime without becoming a core requirement.
- Never silently route input to the physical desktop. Every operation must target
  an explicit session. The only exception is a host session, which the person
  approves (`desktop_request_host` / `agent-desktop host`) and which expires.
  Tests use a private session as a stand-in host and never the real screen.
  Visible testing may use a nested desktop window.
- Reversible project-local experiments are allowed. Host activation/rebuilds,
  persistent permission changes, unrelated app shutdowns and personal browser
  profiles require specific authorization.
- Test lifecycle, actual input receipt, screenshots, cleanup and failure behavior
  as appropriate. Distinguish experimental proof from production reliability.

## Documentation and collaboration

- Keep `README.md` focused on installation, a first session and navigation.
  Detailed behavior belongs in `docs/USAGE.md`; MCP setup belongs in
  `docs/INTEGRATIONS.md`; validation commands belong in `docs/VALIDATION.md`.
- Keep technical claims consistent with source and recorded evidence. Dated
  logs, research, reviews and trials are historical records, not current promises.
- Use portable paths in instructions. Preserve exact paths in historical evidence
  when they explain a result. Do not copy credentials or personal account data
  into public-facing examples.
- When contributors work in parallel, use a separate worktree. Do not edit, stage
  or commit another contributor's changes. State the PR base and dependencies.
- The repository is public. Releases, package publishing and visibility or
  license changes need a maintainer decision. A request to open a PR does not
  authorize merging it.
