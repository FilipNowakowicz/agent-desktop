# Publication preparation

Checklist used to prepare the repository for public visibility (2026-10-05 to
2026-10-09).

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
- [x] Daily-use trials: the pilot met its bar (20/20 on the fixed build) and
      the alpha gates closed on 2026-10-08; the maintainer's own use continues
      as feedback, not a gate (decisions.md).
- [x] Threat model decided ([decisions](reviews/2026-10-05-project-review/decisions.md)):
      cooperative same-user operation; takeover is not a confidentiality boundary.
- [x] Disclosure scan (2026-10-05) of tracked files and all Git history: no
      tokens, keys or passwords. The only personal data is local paths
      (`/home/user/...`) and the author email, which the maintainer accepts. One
      reference to the maintainer's private configuration repository
      (`nixos-config#417`) remains in the development log. Repeated on 2026-10-09
      over all history: still no secrets. History is published as is; it also
      contains the retired project prompts and the 2026-10-05 review command
      log (maintainer decision, 2026-10-09).
- [x] Repository name: `agent-desktop` (clone instructions and integration
      references updated).
- [x] Commit author email stays as is (maintainer decision, 2026-10-05).
- [x] Planning records moved under [docs/project/](project) (2026-10-09);
      Markdown links were updated everywhere, while plain-text file names in
      dated records keep their original form.
- [x] [SECURITY.md](../SECURITY.md) with private reporting.
- [x] Maintainer authorized the visibility change (2026-10-09).
- [x] Made public on 2026-10-09. Private vulnerability reporting and
      Dependabot alerts are on, `main` requires the Lint check and refuses force
      pushes, and Actions runs again: the full Checks matrix passed on all four
      jobs (run 37870749337).

Original prompt files were retired; their useful ideas are consolidated in the
project plan and the original text remains in Git history. Dated research and reviews describe the
revision and context they examined; they should not be presented as current
capability promises or independently refreshed competitor information.
