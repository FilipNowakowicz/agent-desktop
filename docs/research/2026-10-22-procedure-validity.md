# Learning validity conditions for reusable desktop procedures

Date: 2026-10-22. Status: research assessment and proposed experiment, not an
implemented learner, measured improvement or adopted product pivot.

Archival clarification (2026-10-23): this assessment was written in the older
research checkout at `711f1ca`. Remote main was subsequently verified at
`4277ed1`, where R1–R6 are implemented, including scoped checks and durable
operations with documented limits. References below to the older checkout are
historical observations, not current implementation status. Consult the
[current plan](../project/PROJECT_PLAN.md). The maintainer has since chosen
[functionality-first product development](../project/PRODUCT_DIRECTION.md);
this research protocol is retained as a deferred option.

## Decision

There is a tractable **evaluation and contract-inference question**, but the
broad idea is already occupied. Do not build a procedure-learning platform.
First test whether learning executable validity conditions buys anything over
careful hand-written checks and small symbolic learners with the same evidence.
The strongest defensible hypothesis concerns observation coverage, stable
identity and outcome evidence under controlled variation, not script generation.

The opportunity becomes significant only if inferred conditions transfer to
new failure mechanisms or applications, reduce false success without simply
rejecting work, and cost less to acquire and maintain than hand-written checks.
A one-application result can kill this direction; it cannot establish that claim.

## Local evidence and limits

Read CONTRIBUTING, START_HERE, PROJECT_PLAN, the previous completion review,
D1/E6 reports, saved E6 scripts, and the inventory fixture/checker. This checkout
is at `711f1ca` on `research/completion-correctness-2026-10-15`, with pre-existing
uncommitted research changes. No previous benchmark was rerun here.

- [D1](2026-10-13-d1-scripts.md): pooled turns fell 4%, wall time rose 58%; the
  stated gate failed. Writing scripts is not itself an efficiency result.
- [E6](2026-10-14-e6-skills.md): assisted reuse passed 9/9 repeats, as did the
  baseline, but missed its speed gate. Path-based reuse reached 2.8–2.9 times
  speed on two tasks; inventory remained slower. Samples were small and arms
  were not fully interleaved. These are bounded historical results.
- The repaired inventory replay checked 52/60 rows and reported success while
  the separate fixture check rejected it. Its before/after row sets could agree
  because both traversals omitted the same rows. Earlier replay also depended
  on the pointer being over the scrollable page. This separates a missing
  execution assumption from an inadequate completion check.
- [The current inventory checker](../../benchmarks/realistic.py) compares
  reported final stock/status against the original 60-row fixture. It is
  independent of the procedure's partial accessibility view, but assumes row
  order and does not verify every unchanged field. Extend it before testing
  sorting, deletion, identity corruption or broader side effects.
- The user describes scoped checks and durable operations as available runtime
  capabilities. Treat those as the intended experiment platform; this checkout
  is older: its then-uncommitted completion review still
  proposes richer predicates/resumable operations. `script.listing` returns only
  `nodes`, discarding coverage metadata. Pin and verify the actual experiment
  revision before relying on those newer capabilities. This investigation did
  not establish their current implementation elsewhere.

## Prior art: what is already solved, and what is not established

These are primary-source research claims, not replications. A focused literature
search is not an exhaustive novelty clearance. Recent preprints deserve
particular caution; abstract-only coverage is identified below.

| Area and source | Established method or reported result | Remaining boundary for this question |
| --- | --- | --- |
| [Agent Workflow Memory, 2024](https://arxiv.org/abs/2409.07429) | Induces reusable workflows and retrieves them to guide web agents; reports gains on Mind2Web/WebArena. | Reusing trajectories is prior art. Benchmark improvement does not certify a procedure's applicability or completion monitor. |
| [ReUseIt, 2025, sections 4–5](https://arxiv.org/html/2510.14308v1) | Generates task variations, collects successes/failures, and synthesizes condition checks plus fallback actions. | Very close prior art. Its conditions guide model execution. Evaluation uses an LLM judge with a human audit; it does not establish exact outcome correctness. |
| [Executable Agentic Memory, 2026](https://arxiv.org/abs/2605.12294) | State-aware exploration, executable action groups and graph search; AndroidWorld results. | Abstract reviewed: executable memory and exploration are also occupied territory; no independent replication here. |
| [CoAdapt-GUI, 2026](https://arxiv.org/abs/2608.11588) | Transfers workflow context including failure modes and verification rules, with policy adaptation. | Abstract reviewed: transfer of verification knowledge is not a new claim by itself. |
| [VLAA-GUI, 2026](https://arxiv.org/abs/2604.21375) and [ConflictGuard, 2026](https://arxiv.org/abs/2609.03438) | Respectively address premature completion/loops and infeasible-instruction termination. | Abstracts reviewed: completion checking and abstention already have direct GUI-agent work. UI evidence is not necessarily persisted state or complete task scope. |
| [Ringer, 2016](https://sandcat.cs.washington.edu/web/papers/Bodik-ringer-oopsla-2016.pdf) | Demonstration-based replay with synchronization and robust DOM node matching. | Addresses execution nondeterminism and target changes; matching the demonstrated target does not establish user intent or global completeness. |
| [Helena, 2019 dissertation](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2019/Archive/EECS-2019-139.pdf) and [WebRobot, PLDI 2022](https://arxiv.org/abs/2203.09993) | Generalize demonstrations into higher-level web automation, including repeated work; WebRobot uses speculative rewriting and validation. | Loop/program induction is not new. Helena explicitly discusses ambiguity from a single demonstration. |
| [Dijkstra's weakest-precondition calculus](https://www.cs.utexas.edu/~EWD/transcriptions/EWD04xx/EWD418.html) | Derives sufficient starting conditions relative to program semantics and a specified outcome. | GUI apps are usually only partially observed and lack a complete transition model; intent is not supplied by the calculus. |
| [CEGIS / program sketching](https://people.csail.mit.edu/asolar/papers/thesis.pdf) | Iterates candidate synthesis and counterexamples against a specification. | Test-generated counterexamples support empirical refinement, not the guarantees of a sound verifier. A predicate grammar can make the search modest. |
| [Daikon, 2007](https://homes.cs.washington.edu/~mernst/pubs/daikon-tool-scp2007-abstract.html) | Infers likely invariants from execution observations. | Correlation and finite traces do not prove necessity, sufficiency or inductiveness. This is a strong inexpensive baseline. |
| [ICE, CAV 2014](https://pranav-garg.com/papers/cav14.pdf) | Learns invariants using examples, counterexamples and implications. | For invariants, start/end success labels are inadequate: transition obligations matter. GUI experiments provide sampled transitions, not a complete teacher. |
| [CEGAR, CAV 2000](https://web.stanford.edu/class/cs357/cegar.pdf) | Refines abstractions when abstract counterexamples are spurious relative to the concrete system. | An actual failed GUI run is a concrete failure. Refining its features is CEGAR-inspired; it is not formal CEGAR without an abstraction relation and sound model. |
| [Bauer, Leucker and Schallhart, runtime analysis](https://wwwbroy.in.tum.de/publ/papers/leucker_aswec06.pdf) | Monitors temporal properties with inconclusive outcomes on finite traces. | Unknown is standard. Incomplete spatial/UI coverage adds another source of uncertainty; monitoring cannot recover an unspecified requirement. |
| [Neuro-symbolic skills, CoRL 2022](https://arxiv.org/abs/2206.10680) | Learns skills/operators for planning from demonstrations with supplied predicates. | Preconditions/effects and skill applicability are longstanding planning problems, beyond GUI research. |
| [OSWorld, 2024](https://arxiv.org/abs/2404.07972) | Real desktop tasks with task setup and execution-based evaluation. | Independent outcome evaluators are established evaluation practice, not a novelty claim. |

The literature therefore supplies almost every individual ingredient. A possible
contribution is the controlled comparison of *how conditions are acquired*,
with explicit observation sufficiency and independently measured false success.
Combining established ingredients can be useful, but utility must be measured.

## What a successful trajectory leaves unspecified

Let a fixed procedure be P, its parameters x, the actual state s, and available
observation history h. A useful contract has an entry condition A(h,x), temporal
invariants I, an outcome predicate Q(s,s',x), allowed side effects F, and a
recovery/abstention rule. A positive trace supplies one execution witness. It
does not identify any of these uniquely.

| Missing information | Example | Required evidence or decision |
| --- | --- | --- |
| Intent and quantification | All supplier records versus selected/visible records | Task specification; human clarification if genuinely ambiguous |
| Parameters versus accidental constants | Supplier name is an argument; displayed page count is not a constant | Varied data, counterexamples, explicit binding |
| Target identity and scope | Correct document, account, tab and row despite duplicate labels | Stable identity and scope checks, refreshed after changes |
| Interaction prerequisites | Focus, pointer routing, modal absence, selection, clipboard assumptions | Directly check or explicitly establish state before action |
| Observation sufficiency | Visible rows are a strict subset of filtered/paginated data | Enumeration coverage, unique IDs and snapshot/version evidence |
| Temporal assumptions | Save accepted versus persisted; stale success toast | Bounded waits and durable readback; freshness/provenance |
| Invariants and progress | Same dataset revision; each target handled once; enumeration advances | Per-step checks, transition pairs, repeated-page detection |
| Frame conditions | Non-target records and unrelated fields unchanged | Before/after comparison over declared full scope |
| Recovery semantics | Timeout after commit, partially completed procedure | Reconcile durable effects; never equate timeout with no effect |
| Applicability boundary | Locale, app version, permissions, schema, data shape | Versioned validation envelope and abstention outside it |

Separate **operational validity** (the steps will execute), **semantic validity**
(they accomplish the requested transformation), and **epistemic validity** (the
available evidence warrants saying so). Improving the first can leave the other
two unchanged.

An important limit: if two actual states produce identical observations but P
succeeds in one and fails in the other, no classifier over those observations
can distinguish them. Add a discriminating observation/action, narrow the scope,
or return unknown. A larger model cannot supply missing information reliably.

Entry conditions alone also cannot cover a dataset changing mid-run. Temporal
invariants and completion evidence are separate requirements. A count match
alone is not coverage: duplicates and omissions can cancel. Enumerate identities
against a scoped total under a stable revision, or use a sufficiently complete
authoritative readback. “All observed items are correct” remains a scoped claim.

## Can variation and failure reveal the missing conditions?

Yes, as testable hypotheses. Use interventions rather than merely collecting
more successful traces:

1. Hold data and action code fixed; vary pointer location, focus, starting page,
   filter, modal state, viewport, duplicate labels and commit delay separately.
2. Record entry observations, action/transition history, monitor verdict and
   independent outcome. Distinguish action failure, observation failure, oracle
   failure, unsupported state and real task failure.
3. Minimize a failing case; repeat it and its paired successful control. This
   helps separate causal assumptions from incidental names, coordinates or seeds.
4. Propose the smallest predicate or new observation explaining the pair. Test
   that its removal reintroduces the failure and that it preserves useful cases.
5. Test held-out combinations and entirely withheld mechanisms. Retain unknown
   where no observable discriminator exists.

Failure does not imply a new precondition is the right repair. Pointer placement
is often better normalized deterministically. A selector bug needs a code fix;
incomplete coverage needs a better observer; ambiguous intent needs a person.
Do not let a learner exclude every difficult case and call that correctness.
Active variation should be compared against random variation at equal rollout
budget. Otherwise any gain could simply come from more examples.

## Compare the alternatives

| Approach | What changes | Strength | Main failure mode / cost |
| --- | --- | --- | --- |
| A. Hand-written contract and deterministic normalization | Human writes a small checklist, monitor and safe state-establishing steps | Transparent, cheap, likely to solve many observed failures | Author effort; unanticipated assumptions; app-specific maintenance |
| B. Template-based symbolic learning | Enumerate conjunctions/small decision lists over observable predicates; refine from labeled runs and transitions | Modest CPU cost, executable and auditable; tests whether an LLM is needed | Cannot invent absent features; overfits if examples are narrow |
| C. Model-proposed executable conditions | Model proposes predicates/observation requests; constrained compiler and tests accept/reject them | Can connect semantic failures to new measurable features | Hallucinated checks, evaluator correlation, acquisition expense |
| D. Prose workflow guards | Model interprets learned conditions/fallbacks during execution | Closest conceptual comparison to ReUseIt; flexible | Repeated reasoning cost and ambiguous evidence requirements |
| E. Fresh execution without reuse | Agent solves and verifies each task afresh | Avoids procedure acquisition/maintenance | Repeated inference cost; still needs completion evidence |

Use raw replay as a failure-reproduction control, not the only baseline.
Give A–D the same action body and observations in the first experiment. Freeze
that body; otherwise better code generation confounds better validity learning.
Compare guard acquisition with the same training cases and explicit human/model
time budgets. A can revise its checklist on the training failures too.

Deterministic responsibilities: identity matching, typed parameter validation,
permission/lease checks, freshness bounds, supported coverage tests, exact
structured diffs, invariant evaluation, timeout handling, operation-ID lookup,
and enforcing a three-valued result. Schema/type checking proves only that a
condition is well-formed, not that it expresses the user's intent.

Model responsibilities where useful: infer candidate semantic bindings, propose
discriminating observations/perturbations, explain minimized failures, suggest
predicates or recovery plans. A model need not run on every replay. Human
responsibilities: resolve ambiguous goals, approve the side-effect boundary,
define acceptable risk and decide unsupported/irreversible recovery. These are
not labels to silently infer from a demonstration.

## Smallest useful falsification experiment

**Hypothesis H:** With a fixed procedure and at most 24 labeled training starts,
model-proposed executable conditions detect invalid reuse and false completion
on unseen variations better than equally informed hand-written and template
conditions, while retaining useful successful reuse. Proposed gates below are
engineering decision thresholds, not an assertion of statistical power.

Start with one disposable paginated editing application, derived from the
inventory task. This deliberately targets the known failure mechanism; a pass
only justifies testing another application. No training of a foundation model,
live accounts, procedure registry or general recovery planner is needed.

### Stage 0: cheap feasibility veto

Use the saved procedure and a small fixed set of paired starts. Reproduce the
partial-view false success, establish that the new independent judge catches it,
and implement A's minimal coverage/identity checks. Mutate outcomes deliberately:
omit a hidden target, modify a non-target field, update a wrong ID, duplicate a
record, and acknowledge a save without committing it. The judge must reject each
mutant and accept a correct result, including a legitimate zero-target case.

Stop if the failure cannot be reproduced on the pinned runtime; first explain
the version difference. Stop if the oracle cannot distinguish these outcomes.
If a few generic deterministic rules solve all planned variations, prefer that
engineering result; revise the scientific question before spending on learning.

### Stage 1: frozen comparison

- **Training:** up to 24 initial-state fixtures, including clean cases and
  isolated focus/pointer, starting-page/filter, viewport and delayed-save
  changes. All learners see the same observations and independent labels.
  Freeze monitors, prompt, predicate vocabulary and code before testing.
- **Held out:** 48 new fixtures: 16 new values within known mechanisms, 16
  previously unseen combinations, and 16 cases from withheld mechanisms such
  as duplicate target labels, virtualized rows, or a revision change during
  traversal. The evaluator owns these mechanisms and seeds; no learner sees
  their definitions or labels during acquisition. Include benign controls in
  each group. Freeze an expected-supported subset before evaluating methods.
- **Minimum arms:** raw replay plus A, B and C: 192 held-out executions at most,
  plus training/calibration. Cache observations for offline monitor evaluation
  where valid; actually execute every claimed online success in a reset session.
  A predeclared second repeat of disputed/nondeterministic pairs is diagnostic,
  not a replacement for the first outcome.
- **Optional second stage only if C survives:** add D and E on the same states,
  and compare active versus random training-state selection at equal budget.
  These are required before claiming superiority to prior workflow methods or
  end-to-end agent performance, but not for the cheapest falsification.
- **Resource cap:** two implementation days, 24 training fixtures, no more than
  30 offline model proposal/revision calls, and the held-out execution cap above.
  Set an explicit money/token ceiling before any paid calls. No paid calls are
  authorized or performed by this research note.

Pin application/runtime/model versions, prompts, procedure and checker hashes.
Randomize arm order within fixture blocks; reset state and validate reset. Record
every timeout, failed attempt, rejected case and human intervention. Do not tune
on test failures; any revision needs a new holdout.

### Independent outcome checks and leakage prevention

Keep three different objects: the user-specified goal, the runtime completion
monitor, and the evaluator. The evaluator constructs expected final records by
stable ID from an immutable initial snapshot and checks the actual committed
store. Compare all target fields, all non-target fields, record membership,
duplicates and unrelated writes. Check persistence after reload when persistence
is required. Intermediate event evidence checks prohibited writes and duplicate
commits that a correct-looking final state could hide.

Keep judge code/expected answers out of page source and model context. The
existing fixture's browser reports are insufficient for a new persistence claim;
use a small server-backed store for that variation. A second independently
implemented checker or manual audit of all disagreements checks the oracle.
The monitor may use an ordinary app readback capability available to every arm,
but cannot query the evaluator's expected state.

Private sessions are not a security boundary against same-user arbitrary Python.
For this experiment restrict learned output to a predicate DSL evaluated by a
trusted harness, with only declared observations. If arbitrary agent code is
introduced later, isolate evaluator files/state in a separate process boundary
with actual access controls or container/VM, not merely a hidden pathname.

When a guard rejects, run the unchanged raw procedure on a separate disposable
copy to measure whether it would have succeeded. This estimates false rejection
for the fixed procedure, not whether another strategy could solve the task.
Postcondition rejection still counts any wrong side effect already incurred.

### Metrics and stop criteria

Report per mechanism and overall, using paired fixture outcomes:

- **False success:** monitor says complete but independent outcome is wrong;
  report both count / all cases and count / completion claims.
- **Invalid admission / wrong effects:** procedure starts when it fails in the
  counterfactual raw run, and actual prohibited mutations, separately.
- **Useful reuse:** independently correct, monitor-accepted completions / all
  cases, and / the predeclared supported cases; report false refusals and unknowns.
- **Cost:** acquisition, tests, checks, failed attempts, maintenance, fallback,
  human minutes and wall time, not just replay calls or accepted-case latency.

Advance C only with zero observed false successes and prohibited mutations,
at least 80% accepted correct completions on the supported subset, and at least
four additional independently correct accepted completions out of 48 versus
the stronger of A/B without sacrificing the safety counts. If A/B already have
zero false successes and equivalent coverage, learning has not earned its cost.
Also stop if a useful condition needs evaluator-only information, gains disappear
on held-out mechanisms, or the implementation/call cap is reached. A stopped
result falsifies this bounded hypothesis, not every conceivable future learner.

Zero failures in 48 independent claims would still leave an approximately 6.1%
one-sided 95% upper bound on failure probability; fewer accepted claims weaken
that bound. These fixtures are clustered by mechanism, so do not pretend they
establish a deployment-wide IID rate. Report paired uncertainty and mechanism
counts rather than claiming high reliability from a clean small sample.

If the pilot passes, replicate on a second application and a file/config task
with new semantics, add D/E, and measure amortization. With acquisition cost L,
fresh-run cost F and reuse cost R (including checks/failures/fallbacks), reuse
breaks even only after N > L/(F-R), and never if F <= R. Keep monetary and human
time accounting separate unless an explicit conversion is agreed. Require a
plausible reuse frequency; faster warm runs alone are insufficient.

## Claim discipline

**Established:** workflow induction, demonstration generalization, candidate
invariant learning, counterexample-guided synthesis/refinement, runtime monitors
and independent execution-based evaluation all precede this proposal. The local
E6 result demonstrates a real scope/coverage failure in its historical setting.

**Plausible but unmeasured:** controlled perturbations can reveal missing
conditions; a model can propose useful observables beyond a fixed template set;
explicit evidence coverage can reduce false success at tolerable cost; some
conditions transfer between applications.

**Unsupported:** a new general procedure-learning algorithm, formal soundness
from finite GUI tests, automatic recovery of user intent, broad desktop
generalization, superiority to hand-written automation, or economical reuse.
No such result was obtained here. The defensible next artifact is a small
benchmark and negative-or-positive comparison, with an executable condition
language only as needed to run it.

Validation of this document: local evidence and primary sources inspected;
relative links and whitespace checked. No runtime changes, desktop experiments,
new benchmark results, paid inference or full test-suite execution.
