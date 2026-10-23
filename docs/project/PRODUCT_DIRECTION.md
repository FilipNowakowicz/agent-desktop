# Product direction: a complete desktop environment for existing agents

Recorded 2026-10-23 from the product, functionality and usability discussion.
This is an implementation handoff, not evidence that the proposed product is
finished. [PROJECT_PLAN.md](PROJECT_PLAN.md) remains the current status authority.

## Decisions and their status

| Topic | Direction | Status |
| --- | --- | --- |
| Product | Give existing agents a dependable Linux computer for general work across applications, browser, files and scripts | Maintainer's stated objective |
| Immediate priority | Perfect underlying functionality before spending effort on installation polish or user-interface implementation | Maintainer's explicit sequencing choice |
| Research | Learned procedures are optional; the product does not depend on a novel learning algorithm | Consequence of the product discussion; research stays deferred |
| Interfaces | Keep MCP, CLI and Python access; a future human interface controls the same runtime | Proposed architecture to guide implementation |
| Human interface | A desktop viewer with workspace management, takeover, access and results | Saved design proposal, not an approved implementation stack |
| Scope | Linux first, explicit private/host sessions and existing agent clients | Consistent with repository direction |

The initial suggestion to move main effort elsewhere or first recruit users was
advice about an uncertain research investment. The maintainer clarified the
broader product ambition and chose functionality first. Do not treat that earlier
advice as an instruction to abandon the runtime or start onboarding work now.
Likewise, asking about an ideal interface preserved a future design; it did not
reverse the functionality-first priority.

## What the product should accomplish

> Give your agent its own computer: let it launch applications, browse, run code,
> manipulate files and finish work while you can watch or take over.

Comprehensive desktop access is a capability goal. Success on every possible
task is not a promise: outcomes still depend on the agent, application,
credentials, observations and task specification. The runtime should remove
execution obstacles, retain evidence and make uncertainty explicit.

The long-term ambition is to become a preferred general desktop environment for
agents. That adoption is unproven. Differentiation should come from dependable
execution, useful persistent state, broad application compatibility, recovery,
human control and straightforward integration. Screenshots and clicks alone
are not the complete product.

The negative D1/E6 results constrain specific scripting/reuse strategies; they
do not establish that a desktop runtime has no value. Keep the useful runtime
even if a research hypothesis fails. Do not add new layers merely to justify
past investment.

## One runtime, several interfaces

```text
Existing agent -- MCP server --+
                              |
Scripts ------- Python / CLI -+--> Runtime --> Explicit desktop session
                              |                 applications / browser / files
Person -------- Desktop UI ---+
```

- Runtime: session identity, process ownership, action execution, observations,
  operation records, access enforcement and input ownership.
- MCP: an adapter exposing runtime capabilities to compatible clients. It is
  still a supported deployment and may run entirely headlessly.
- Python/CLI: direct integration, scripting and diagnostics, without requiring
  MCP for every caller.
- Future desktop UI: watch, manage workspaces/access, take over and retrieve
  results. It uses the same state and controls as the other interfaces.

The product is a desktop runtime with MCP support. A human UI does not replace
MCP, and MCP does not need to become the internal protocol for every component.
Do not duplicate lifecycle or ownership logic in the UI. A takeover must affect
actions arriving through every interface. Keep conversation in the existing
agent client initially; a second chat application needs a separate justification.

## Implementation order

1. Audit current capabilities and limits on a pinned current revision.
2. Follow [FUNCTIONALITY_ROADMAP.md](FUNCTIONALITY_ROADMAP.md): correctness under
   interruption, then broad application workflows, persistent state and lifecycle
   stress. Fix concrete failures in small reviewable stages.
3. Preserve backend contracts required by [USER_EXPERIENCE.md](USER_EXPERIENCE.md)
   while postponing its installer and UI implementation.
4. Once functional acceptance is credible, implement the first-install and
   human-control experience, then assess use without developer assistance.
5. Revisit learned procedures only if a measured need warrants the
   [bounded research protocol](../research/2026-10-22-procedure-validity.md).

The suggested two-day research pilot is a cap on optional exploration, not a
deadline for the product. The proposed three-person usability trial is a future
adoption test, not the next development gate.

## Boundaries and deferred work

- No new general agent, model-training programme or required orchestration stack.
- No procedure registry, automatic replay, broad recovery planner or learned
  workflow system without independent evidence of value.
- No native Windows/macOS control, platform fleet or managed VM commitment yet.
  Portable Linux environments remain a later option.
- Private graphical sessions do not establish a security sandbox. Shell access
  with the same user can exceed graphical boundaries. Strong isolation requires
  a concrete threat model and actual enforcement.
- Host desktop access remains explicit, approved and expiring. Synthetic tests
  use private stand-ins; no silent fallback to the physical desktop.
- Human control, persistent state and credential handling must retain clear
  boundaries. Restarting a session does not reverse external effects.

## What would establish value later

Technical evidence comes first now: reproducible workflows, correct targeting,
honest outcome evidence and documented failure/recovery behavior. Later, test
whether people can connect their own agents, complete work they wanted done and
return without prompting. A suggested initial study is three people attempting
several genuine tasks each. Observe setup failures separately from lack of
ongoing usefulness; neither is solved by simply adding more tools.

## Open decisions

The runtime/UI transport, frontend toolkit, installer packaging, exact supported
application set, workspace storage/retention model and stronger isolation design
remain open. Select them from actual requirements and experiments. The documents
save the intended behavior; they do not authorize unrelated host changes,
releases, paid experiments or real-account access.
