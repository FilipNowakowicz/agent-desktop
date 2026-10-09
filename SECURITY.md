# Security

## Scope

Agent Desktop separates graphical sessions; it is not a security sandbox.
Applications in a session run as your user with your filesystem and network
access. The host guard and cooperative takeover reduce accidents and are not
confidentiality boundaries (see the [threat model decision](docs/reviews/2026-10-05-project-review/decisions.md)).

Reports in scope include, for example:

- input, screenshots or clipboard contents reaching a session other than the
  one an operation names, or reaching the physical desktop without an approved
  host session;
- a host session that does not expire or that can be started without approval;
- the MCP server or CLI exposing a session to another local user or remotely;
- secrets written to logs, traces or screenshots retained beyond their limits.

Applications escaping a session through the shared filesystem, network or
D-Bus services of the same user are known limits, not vulnerabilities.

## Reporting

Report vulnerabilities privately through GitHub's
[security advisory form](https://github.com/FilipNowakowicz/agent-desktop/security/advisories/new),
not in public issues. Include the version or commit, the runtime
(`uv run agent-desktop doctor` output) and steps to reproduce. You should get a
reply within two weeks. This is a small experimental project without a bug
bounty.
