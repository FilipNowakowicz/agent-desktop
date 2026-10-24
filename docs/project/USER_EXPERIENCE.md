# Future installation and human interface

Recorded 2026-10-23. A saved design proposal for later implementation. The
maintainer's current priority is [underlying functionality](FUNCTIONALITY_ROADMAP.md),
not building this interface now. Toolkit, packaging and UI transport are undecided.

## Experience goal

The person gives an existing agent a computer, knows which environment it
controls, can watch or intervene, and can retrieve its work without learning
runtime internals. The main surface is a desktop viewer with a small control bar.
Management, access and diagnostics surround the work rather than replacing it.

## First-install journey

| Step | User experience | Required implementation behavior |
| --- | --- | --- |
| Install and open | Progress and a concrete fix if a requirement is missing | Check supported environment/dependencies; show actionable errors and retry paths; request system changes explicitly when needed |
| Choose environment | Private desktop by default; explicit existing-desktop alternative | Explain actual access and persistence, identify the session; never imply graphical separation is a security sandbox |
| Connect an agent | Select a supported client, configure connection, test it | Show/configure supported integration without clobbering unrelated settings; retain manual configuration; verify a real tool round trip |
| Choose access | Select shared folders and whether to retain the workspace | Enforce and explain the actual boundary; avoid a long questionnaire; obtain further access when the task needs it |
| Complete a demonstration | Watch an app open, a file be created and its result appear | Use a disposable private environment; independently verify the saved artifact and make it easy to open/export |

Completion of installation means a working connection and verified demonstration,
not just a successful package install. Reopening after interruption should
discover completed setup work and provide a safe recovery path. Avoid requiring
a new agent subscription or a second chat interface merely to use the runtime.

The private-desktop default is a proposed general first-run experience. It does
not override the earlier preference to use existing host logins for login-gated
work with explicit approval. Do not import personal profiles automatically.

## Main interface sketch

```text
+-------------------+-----------------------------------------------+
| Workspaces        | Research desktop   Working  Pause  Take over  |
|                   +-----------------------------------------------+
| Research          |                                               |
| Documents         |                 Live desktop                  |
| Website work      |                                               |
| + New workspace   |                                               |
|                   +-----------------------------------------------+
|                   | Activity | Files | Access                     |
+-------------------+-----------------------------------------------+
```

This is a navigation concept, not a fixed visual design. Keep conversation in
the existing agent client initially. The runtime UI supplies the computer,
access controls, live view and results. Multiple workspaces are a future
management surface, not a requirement for the first frontend increment.

## Essential interactions

- **Watch:** connect/disconnect the viewer without ending a headless session.
  Distinguish this from nested visible testing, whose window closure may end it.
- **Pause:** stop issuing further agent input and show any in-flight command or
  uncertain effect. Do not present a paused queue as proof the application stopped.
- **Take over:** revoke further agent input and give the person control promptly.
  Enforce ownership in the runtime for MCP, API and CLI alike. Acknowledge residual
  in-flight effects; resume requires fresh observations after human changes.
- **Provide a login:** let the person interact with the actual application,
  then return control. Never imply takeover alone protects credentials from
  observation; show recording/observation behavior and actual access boundaries.
- **Retrieve results:** list generated artifacts with preview/open/export actions,
  their workspace and verification status. Missing/moved files must be explicit.
- **Understand stops:** distinguish needs-input, app failure, connection loss,
  cancellation, unknown outcome and completion. Offer a concrete next action.
- **Reconnect:** recover the existing workspace and recorded operation state;
  do not rerun a possibly completed submission automatically.

Activity should describe useful events such as opening a document, saving a
report or waiting for login. Keep low-level traces expandable. Completion should
link to the result and say what was actually checked. Partial verification or
contradictory evidence remains visible; no universal green badge based on exit 0.

## Backend contracts to preserve now

| UI need | Backend dependency |
| --- | --- |
| Return to the same work | Stable workspace/session IDs and declared persistence |
| Reconnect after an error | Durable operation status and per-step evidence |
| Take over across all clients | Shared input ownership/control epoch and fresh-observation rules |
| Explain progress/failures | Structured events with target, time, scope, delivery and uncertainty |
| Open a result | Artifact identity/location/lifetime, provenance and check results |
| Understand access | Explicit environment identity, actual access enforcement and expiry |

A folder selector does not create confinement for arbitrary scripts. Either
enforce the promised restriction with an appropriate boundary or explain the
broader access. Do not let attractive controls overstate security guarantees.

## Later implementation slices and acceptance

1. Read-only viewer plus session/status reconnect. Closing/reopening it preserves
   work and reflects the actual state. Reuse the runtime's existing viewer path.
2. Pause/takeover/resume and needs-input flows. Test races with queued and running
   actions and conflicting clients using private stand-ins, never the real screen.
3. Artifact browsing and activity/evidence. Show missing artifacts, unknowns and
   failed checks faithfully; protect sensitive stored evidence appropriately.
4. Setup/client connection and environment/access choices. Exercise missing
   dependencies, failed integration, interrupted installation and retry.
5. Workspace management and visual refinement after the preceding slices work.

When usability work is scheduled, observe a few people using their own agents
without developer operation: can they connect, identify the controlled computer,
intervene and retrieve a verified result? Later repeated voluntary use is a
product-value signal. These are deferred evaluations, not replacements for the
current functional acceptance suite.

See [PRODUCT_DIRECTION.md](PRODUCT_DIRECTION.md) for the MCP/runtime/UI separation
and [PROJECT_PLAN.md](PROJECT_PLAN.md) for implemented status. None of this
document means a new installer, live management UI or security sandbox exists.
