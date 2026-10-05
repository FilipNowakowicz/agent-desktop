# Publication preparation

This is a preparation checklist, not authorization to publish. The repository
remains private and documentation changes are reviewed through an unmerged PR.

## Presentation

Reader-facing title: **Agent Desktop**. Keep the repository and Python package
name `private-agent-desktop` during ongoing development so clone URLs, integrations
and package identity stay consistent. A future rename needs coordinated URL and
installation updates.

Repository description:

> Give existing agents a separate Linux desktop: persistent sessions, CLI and MCP control, screenshots, accessibility and human handoff.

Repository topics: `linux`, `wayland`, `desktop-automation`, `computer-use`, `mcp`,
`python`, `accessibility`.

“Private” describes separate graphical sessions, not a filesystem, network or
credential security boundary. The README and user guide must retain that limit.

## Release decisions

- [ ] Choose a license and add the corresponding file and package metadata.
- [ ] Select supported runtime versions and document reproducible installation
      on NixOS and at least one chosen non-Nix desktop.
- [ ] Complete representative daily-use and longer lifecycle trials; record
      failures as well as passes.
- [ ] Decide the supported threat model for profiles and human takeover.
- [ ] Review historical prompts, logs, trials, benchmark artifacts and Git history
      for personal information, local paths and account-specific material before
      publication. Historical evidence has been retained during this cleanup;
      this pass is not a full disclosure audit.
- [ ] Decide whether the current repository name should change and update clone
      instructions and integration references together if it does.
- [ ] Obtain explicit maintainer authorization for the visibility change.

Original prompt files were retired; their useful ideas are consolidated in the
project plan and the original text remains in Git history. Dated research and reviews describe the
revision and context they examined; they should not be presented as current
capability promises or independently refreshed competitor information.
