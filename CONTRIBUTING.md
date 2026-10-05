# Contributing

Agent Desktop is an experimental Linux runtime for general computer use by
existing agents. Improvements should follow observed failures and the
[project plan](PROJECT_PLAN.md), with evidence in the
[development log](DEVELOPMENT_LOG.md).

## Development setup

Install uv and the desktop dependencies listed in the [README](README.md), then:

```sh
uv sync --managed-python --locked
uv run agent-desktop doctor
```

Use `uv run` for Python commands; no manual virtual environment activation is
needed. Python dependencies are portable; desktop runtime packages are supplied
by the operating system. See [validation](docs/VALIDATION.md) for checks, smoke
tests and lifecycle experiments.

## Changes and review

- Use a branch and PR for each bounded development stage. When work overlaps,
  use a separate worktree and keep unrelated changes out of the PR.
- Explain the problem, resulting behavior, validation and remaining limits.
  Identify dependencies between stacked PRs explicitly.
- Use the configured human author. Omit tool attribution, session identifiers
  and co-author trailers from commits and PRs.
- Update documentation alongside behavior changes. Record exact validation and
  failures; distinguish unit checks, real desktop tests and model-driven trials.
- Keep product direction and deferred ideas in the project plan. Dated research,
  review and trial records describe their original revision and environment.

## Testing boundaries

Always target an explicit private session. Use disposable application data and
project-local runtime experiments. Visible sessions can receive physical keyboard
input while focused; prefer headless mode for isolated input tests.

Host activation or rebuilds, persistent permission changes, unrelated application
shutdowns and personal browser profiles require specific authorization. Paid
model runs and real-account handoffs need an agreed scope and budget. Validate
benchmark fixtures with `--dry-run` before account-using runs.

Graphical separation, the host guard and cooperative takeover are not security
sandboxes. Report limitations accurately and verify task outcomes independently
of tool delivery responses.

## Before publication

The project is licensed under the [MIT License](LICENSE). Keep repository
visibility private until publication is explicitly authorized.
The [publication checklist](docs/PUBLICATION.md) tracks remaining decisions.
