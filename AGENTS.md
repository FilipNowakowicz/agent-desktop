# Development conventions

- Build a private Linux desktop for existing agents. Follow `PROJECT_PLAN.md` and
  record decisions, exact validation and remaining failures in `DEVELOPMENT_LOG.md`.
- Keep `prompt1.txt` and `prompt2.txt` unchanged as historical brainstorming inputs.
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
  an explicit private session. Visible testing may use a nested desktop window.
- Reversible project-local experiments are allowed. Host activation/rebuilds,
  persistent permission changes, unrelated app shutdowns and personal browser
  profiles require specific authorization.
- Test lifecycle, actual input receipt, screenshots, cleanup and failure behavior
  as appropriate. Distinguish experimental proof from production reliability.
