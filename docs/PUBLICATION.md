# Publication preparation

This is a preparation checklist, not authorization to publish. The repository
remains private until the maintainer authorizes publication.

## Presentation

Name: **Agent Desktop**; repository and Python package `agent-desktop` (renamed
from `private-agent-desktop` on 2026-10-05); commands `agent-desktop` and
`agent-desktop-mcp`. An unrelated project with the same title exists
([lahfir/agent-desktop](https://github.com/lahfir/agent-desktop), a Rust
accessibility-tree tool); the maintainer chose to keep the name. Say "Linux" and
"separate session" early in descriptions so the two are easy to tell apart.

Repository description:

> Give existing agents a separate Linux desktop: persistent sessions, CLI and MCP control, screenshots, accessibility and human handoff.

Repository topics: `linux`, `wayland`, `desktop-automation`, `computer-use`, `mcp`,
`python`, `accessibility`.

“Private” describes separate graphical sessions, not a filesystem, network or
credential security boundary. The README and user guide must retain that limit.

## Release decisions

- [x] MIT License approved by the maintainer; added [LICENSE](../LICENSE) and
      package license metadata.
- [x] Supported installations: Nix runtime and Ubuntu 24.04
      ([runtime/INSTALL.md](../runtime/INSTALL.md)), both in CI.
- [ ] Complete representative daily-use and longer lifecycle trials; record
      failures as well as passes.
- [x] Threat model decided ([decisions](reviews/2026-10-05-project-review/decisions.md)):
      cooperative same-user operation; takeover is not a confidentiality boundary.
- [x] Disclosure scan (2026-10-05) of tracked files and all Git history: no
      tokens, keys or passwords. The only personal data is local paths
      (`/home/user/...`) and the author email, which the maintainer accepts. One
      reference to the maintainer's private configuration repository
      (`nixos-config#417`) remains in the development log. Repeat the scan just
      before publishing.
- [x] Repository name: `agent-desktop` (clone instructions and integration
      references updated).
- [x] Commit author email stays as is (maintainer decision, 2026-10-05).
- [ ] At publication, move the internal planning records (`DEVELOPMENT_LOG.md`,
      `PROJECT_PLAN.md`, `RESEARCH_FINDINGS.md`, `START_HERE.md`) under
      `docs/project/`, updating links in AGENTS.md, CONTRIBUTING.md, the PR
      template and current docs. Dated reviews keep their original references.
- [ ] Obtain explicit maintainer authorization for the visibility change.

Original prompt files were retired; their useful ideas are consolidated in the
project plan and the original text remains in Git history. Dated research and reviews describe the
revision and context they examined; they should not be presented as current
capability promises or independently refreshed competitor information.
