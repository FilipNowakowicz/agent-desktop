# Start here

Agent Desktop gives existing agents a separate Linux graphical session for
general computer use. The runtime is experimental and Linux-first. Applications
run as the current user; a private desktop is not a security sandbox.

## Using the runtime

Start with the [README](../../README.md) for installation and a first session. Then use
the [desktop guide](../USAGE.md) for input, observation, profiles and human
handoff, or the [integration guide](../INTEGRATIONS.md) for MCP clients.
The [compatibility matrix](../COMPATIBILITY.md) describes tested configurations.

## Continuing development

1. Read [AGENTS.md](../../AGENTS.md) and [CONTRIBUTING.md](../../CONTRIBUTING.md).
2. Read the current [project plan](PROJECT_PLAN.md) and the newest entries in the
   [development log](DEVELOPMENT_LOG.md). Older entries describe earlier revisions.
3. Inspect the checkout, open pull requests and current CI results before editing.
   Use a separate worktree when another contributor is working in parallel.
4. Choose a bounded change from the plan, validate it, and open a reviewable PR.
   Record completed work, exact validation, failures and remaining gaps.

The foundation already includes persistent labwc sessions, private D-Bus,
supervisor/guardian cleanup, virtual input, screenshots, CLI/MCP control,
observation tokens, viewers, cooperative takeover, profiles and AT-SPI access.
Do not restart the original M0 exploration without a concrete regression.

The [2026-10-05 review](../reviews/2026-10-05-project-review/report.md) recommends
finishing a daily-use alpha before adding more features. The plan tracks current
progress; the review remains a dated assessment. Its open questions (threat model,
supported installations, pilot tasks, controller policy) are decided in
[decisions.md](../reviews/2026-10-05-project-review/decisions.md). The alpha gates,
including the maintainer's login handoff, closed on 2026-10-08. Benchmark results include measured tool profiles; consult
the [report](../BENCHMARK.md) rather than older handoff notes.

General computer use remains the product goal. GUI testing and diagnostics can
support it. Windows/macOS frontends and stronger isolation are deferred options.
The current plan supersedes the debugging-first recommendation in the historical
[research notes](RESEARCH_FINDINGS.md). The plan also retains useful ideas from
the retired brainstorming prompts; originals are available in Git history.

Releases, host changes and personal-account access require explicit
authorization; opening a PR does not authorize merging it.
