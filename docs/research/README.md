# Research index

One line per dated research document, oldest first. Research files describe the
revision and environment where they were written; they are historical records, not
current promises. Current direction is in the
[project plan](../project/PROJECT_PLAN.md) and the
[directions board](../project/DIRECTIONS.md). Status words:

- **adopted**: the proposal or its feature is in the product or the plan
- **supported**: the measured result favored the idea
- **weakened**: the result was negative or small, and the feature stays experimental
- **rejected**: a stated gate was missed and the line stopped
- **parked**: kept as recorded, with no current work
- **open**: still a live question or an unfinished protocol
- **unclear**: the documents do not say

| Date | Document | Topic | Outcome |
| --- | --- | --- | --- |
| 2026-10-07 | [Next direction](2026-10-07-next-direction.md) | Dependable, reusable desktop work: precise UI queries and checked actions first, procedures later | Adopted as the next focus on 2026-10-08 (plan); the procedure-reuse part is parked (D1/E6 gates missed) |
| 2026-10-07 | [Observation optimisation](2026-10-07-observation-optimisation.md) | Task-directed observation and context retention; literature and recorded benchmarks, no new runs | Unclear. A recommendation; its savings were never measured as proposed |
| 2026-10-08 | [Effect ledger](2026-10-08-effect-ledger.md) | Reporting what an action changed (`AGENT_DESKTOP_EFFECTS=1`) | Supported on five file tasks (input tokens -25%, p = 0.016), later weakened (D3) by the E2 A/B; stays experimental |
| 2026-10-09 | [Speed](2026-10-09-speed.md) | Where wall time goes in host sessions (97-99% outside the tool) | Supported as measurement; its proposals became S1a-S4 |
| 2026-10-09 | [Effect atlas](2026-10-09-effect-atlas.md) | Model-free mapping of controls to settings (`desktop_atlas`, `desktop_set`) | Supported for lookup-and-apply (turns about -31% on 3 of 4 settings tasks), not for lookup alone; experimental |
| 2026-10-09 | [Beyond human speed](2026-10-09-beyond-human-speed.md) | Staged plan S0-S5 for fewer model decisions | Adopted in part (S0, S1a, S2, S3 browser); S2 missed its speed gate; remaining stages unclear |
| 2026-10-09 | [External review of the plan](2026-10-09-astra-review.md) | Read-only review of the speed plan and code | Adopted: it reordered the plan and its code findings were fixed first |
| 2026-10-09 | [Act and observe](2026-10-09-act-and-observe.md) | `screenshot=true` on input (S1a) | Supported and adopted (turns -31%, input tokens -20%) |
| 2026-10-09 | [Guarded steps](2026-10-09-guarded-steps.md) | `expect` and run-time targets (S2) | Weakened: speed gate not met (turns -8%, not significant); kept for reliability |
| 2026-10-09 | [Browser bridge](2026-10-09-browser-bridge.md) | Firefox through WebDriver BiDi (S3) | Supported and adopted (wall time -33%, input tokens -30% with `steps` and `within`); Firefox only |
| 2026-10-11 | [Effect-first plan](2026-10-11-effect-first.md) | Direction and test plan E0-E6 | Weakened: E2 and E3 missed their gates, E4 and E6 stopped; E0 and E1 done |
| 2026-10-11 | [Effect-first A/B (E2)](2026-10-11-effect-first-ab.md) | Does reporting effects cut looks? | Rejected for this suite (turns -4.5%, wall time +15% with Opus); features stay experimental |
| 2026-10-11 | [Model tiers (E0, E1)](2026-10-11-model-tiers.md) | Realistic suite across Opus, Sonnet and Haiku | Supported: the E0 variance gate was met (one task excepted); all tiers complete the suite; turns dominate wall time |
| 2026-10-11 | [Observation discipline (E3)](2026-10-11-observation-discipline.md) | Changed-only screenshots | Rejected: input tokens about -7%, gate -25% missed; stays experimental (`AGENT_DESKTOP_LOOK_DELTA=1`) |
| 2026-10-13 | [D1 scripts](2026-10-13-d1-scripts.md) | The agent writes Python instead of single steps | Rejected: turns -4%, wall time +58%; parked (P2) |
| 2026-10-14 | [E6 skills](2026-10-14-e6-skills.md) | Verified skills for repeated tasks | Rejected: gate (3x faster) missed, though a skill given by path reached 2.8-2.9x; parked (P2) |
| 2026-10-15 | [Completion correctness](2026-10-15-completion-correctness.md) | Completion evidence and correctness gaps at `711f1ca` | Adopted: R1-R6 implemented from it; its repair proposals are superseded. Probes ([JSON](2026-10-15-completion-probes.json), [script](completion_probes.py)) describe old behavior |
| 2026-10-22 | [Procedure validity](2026-10-22-procedure-validity.md) | Learning when reusable procedures stay valid | Parked (P4); the experiment is deferred. Data: [abstraction-experiment.json](abstraction-experiment.json), [script](abstraction_experiment.py) |
| 2026-11-06 | [Evidence protocol](2026-11-06-evidence-protocol.md) | Protocol for atlas on more apps, wlroots stock vs repaired, and tier-separating tasks | Done; results are in `evidence/` (atlas 45 of 50 verified across three apps, wlroots failure rate 1.5% stock vs 0% repaired, tiers separate on some tasks) |
| 2026-11-10 | [Big directions (work in progress)](2026-11-10-big-directions-wip.md) | Larger directions B1-B5 and C1-C3 | Open: accepted items moved to the execution plan; others parked or in Later (see the directions board) |
| 2026-11-11 | [Desktop subagent protocol](2026-11-11-desktop-subagent-protocol.md) | N10 A/B protocol, with a schema-cost measurement | Done as the protocol of the pilot below |
| 2026-11-11 | [Desktop subagent pilot](2026-11-11-desktop-subagent-pilot.md) | Holding the desktop tools in a subagent (B1) | Weakened: main-context tokens fell 93-97% but wall time rose 51-58% (gate not met); direct tools stay the default |

Data kept beside the documents: [effects/](effects/) (aggregates cited by the
October notes), and the scripts named above. Evidence for the 2026-11-06 round is in
[../../evidence/](../../evidence/).
