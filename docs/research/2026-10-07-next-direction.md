# Next direction: dependable, reusable desktop work

Research date: 2026-10-07. Local baseline: `328b51f`. Status: recommendation for
review, not an adopted product pivot or an implemented feature. This extends
[observation optimisation](2026-10-07-observation-optimisation.md).

## Recommendation

Keep the private Linux desktop as the foundation. Build toward this promise:

> Give your existing agent desktop work it can check, recover, and repeat while
> you keep using your computer.

The next bounded implementation should be **precise observations and checked
actions**. The longer-term expansion should be **reusable desktop procedures
with explicit outcome checks and interruption handling**. Start with a few
useful workflows, not a universal procedure learner.

The strongest mathematical research direction is **task-dependent state
abstraction with counterexample-driven refinement**. Group theory has a useful,
narrower role in coordinate transformations, equivariance, and tests of workflow
invariance. Most desktop operations are irreversible, partially defined, and
noncommutative; forcing them into a group would obscure their real behaviour.

This is a credible route to usefulness, not evidence of a revolutionary invention
or a forecast of popularity. Private desktops, compressed observations, reusable
skills, verification, and recovery all have prior art. The opportunity is to
deliver a particularly usable combination for existing agents on Linux, and
demonstrate a measurable advantage on work people actually repeat.

## What was investigated, and what was not

- Read the current plan, contribution rules, README, pilot, development log,
  benchmark report, observation research, and relevant observation/action code.
- Checked the Git branch, recent commits, open PR list and recent CI results.
  No open PRs were returned at the start. Recent Lint runs had failed; the log
  records unavailable CI due to account billing/spending limits.
- Reviewed primary competitor documentation and research papers linked below.
  Literature coverage ranges from abstracts to the full HTML of the verified
  tool-call paper; this is not a full reproduction or systematic literature review.
- Ran an exhaustive 128-state illustrative model of abstraction refinement.
  This is new mathematical evidence about that model only.
- Did not run new desktop comparisons, paid model trials, installations, user
  interviews, or security tests. No demand, novelty, or performance claim below
  should be read as the result of those activities.

Evidence labels used here: **observed source** means current code or documentation
was inspected; **recorded experiment** means an existing local report, not a new
rerun; **external claim** means authors' documented capability or result;
**proposal** means our inference or design to test.

## 1. What the project actually has

The foundation is more complete than the October 5 review alone suggests:
persistent sessions, supervision, explicit input routing, screenshot coordinates,
AT-SPI, bounded sequences, controller leases, observation, handoff, profiles,
traces, and supported Nix/Ubuntu installation paths. See
[plan](../project/PROJECT_PLAN.md), [usage](../USAGE.md), and
[compatibility](../COMPATIBILITY.md). These are observed source/documentation;
compatibility results remain limited to the recorded environments.

Three findings should drive the direction:

1. **Completion can conceal fragile execution.** The second
   [pilot batch](../trials/pilot.md) records 20/20 completed tasks, but two
   in-application misdirections. One involved an accessible control reporting
   `delivered` without acting. The diary explicitly says the stricter
   wrong-target interpretation would fail that batch. It also spans builds
   before and after a fix. This is useful experience, not 20 independent trials
   of one fixed production version.
2. **Fewer calls need not mean lower cost.** The
   [benchmark report](../BENCHMARK.md) records substantial call reductions from
   richer tools, but increased cost in matched standard-suite rounds. Large
   retained UI listings are one candidate explanation; causal attribution is
   not established. Optimise cost per verified outcome, not tool-call count alone.
3. **Current guards stop short of task semantics.**
   [`run_actions`](../../src/agent_desktop/core.py) holds a controller lease and
   checks windows/focus/output, but documents that in-window changes are not
   detected. It already preserves uncertain delivery and never blindly retries.
   [`desktop_ui`](../../src/agent_desktop/mcp_server.py) filters applications and
   windows but lacks the proposed exact predicates and field projections.
   The new layer should extend these strengths rather than replace them.

The native/Cua browser comparison is 6/6 on both sides with different
environments. It does not establish a winner. The loaded soak supports runtime
stability under its specific workload, not arbitrary application correctness.

## 2. Competitive map: what is already occupied

All competitor entries are documentation research, not fresh hands-on tests.
Absence from a README is not proof that a capability is absent.

| Alternative | Documented overlap | Implication for this project |
| --- | --- | --- |
| [wbox-mcp](https://github.com/quazardous/wbox-mcp) | Separate compositor, headless apps, input, screenshots, MCP; platform-specific Windows path | A private Linux desktop alone is not a distinct invention. Compete on supported workflows, correctness and installation experience. |
| [kde-mcp](https://github.com/atassis/kde-mcp) | Accessibility-first control, live/virtual modes, structured changes, mutation leases and audit/policy mechanisms | Semantic-first observations and leases are already established ideas. Its advertised savings are not measurements of this project. |
| [Cua](https://cua.ai/docs) | Native background drivers across Linux/Windows/macOS, sandboxes, shared workspaces and evaluation tooling | Comparing only against its older container browser path understates the competitor. Native Driver is a necessary future baseline. |
| [E2B Desktop](https://github.com/e2b-dev/desktop) | Hosted graphical sandbox, screenshot/input SDK and streaming | A cloud fleet or general sandbox pivot enters an established infrastructure category. Local host access and stronger isolation are different products/tradeoffs. |
| [UFO²](https://github.com/microsoft/UFO/blob/main/ufo/README.md) | Windows GUI/API integration, retrieved experience and speculative actions checked against live UI state | Hybrid execution and checked batches are not new. Linux, small runtime scope and integration with existing agents remain useful choices. |
| [CUA-Skill](https://arxiv.org/abs/2601.21123) | Parameterised skill/execution graphs, retrieval and failure recovery | “Teach it once, replay later” is occupied. A contribution needs better scope validation, reuse, authoring cost or portability. |
| [Playwright](https://playwright.dev/docs/locators) | Fresh locator resolution and retryable browser interaction; [actionability checks](https://playwright.dev/docs/actionability) | Borrow these interaction principles. Use browser/API tools when they solve the task well; desktop automation must earn its complexity. |

GitHub HEADs independently checked on the research date: Cua
`5227ad637590a15976413b1a33f8693fac0e9a7e`; wbox
`a2f3eab914e7d1db142f98887a3be623a6821402`; kde-mcp
`eadae9c99feb98431299746d188d1c2d26c1c37f`; E2B Desktop
`1ff98a36306989d155ce5eceab2a2d38c9a8d6d2`. Web pages were read at their live URLs;
these HEADs are revision anchors for later reproduction, not a claim that every
indexed web response exactly matched those revisions.

**Positioning correction:** the current README contrasts local native operation
and background input with alternatives rather broadly. Before publication,
qualify that comparison by named backend and platform. Cua Driver and wbox
already document background/native modes. Do not market a viewer, MCP, semantic
access, or background operation as exclusive features.

## 3. Where the evidence points

Long tasks create more opportunities for lost constraints, hidden state and
incorrect success claims. [OSWorld 2.0](https://arxiv.org/abs/2606.29537) studies
108 longer workflows and identifies these problems. Its reported scores concern
particular tested systems; they are neither current universal model rankings nor
a prediction for this runtime. [OSWorld-Human](https://arxiv.org/abs/2506.16042)
also identifies planning/reflection calls and excessive steps as major latency
sources. This motivates measuring whole workflows before optimising input speed.

Verification is a substantial research area already.
[The Art of Building Verifiers](https://arxiv.org/abs/2604.06240) separates process
and outcome assessment for web trajectories. Its empirical verifier accuracy
does not make a screenshot judge a proof of document correctness.
[Desktop-Delta Bench](https://arxiv.org/abs/2607.26041) targets recognition of
desktop state transitions, reinforcing the distinction between grounding a click
and understanding its effect.

The especially close [Verified Tool Calls](https://arxiv.org/html/2608.02645v1)
paper combines postconditions, verification before retry and idempotency keys.
Its controlled simulated tool environment is relevant prior art, not evidence
that arbitrary GUI applications provide transactional semantics. Its use of
“atomicity” blends response certainty with state-transition atomicity; keep those
concepts separate in our design. A request can apply atomically while its reply
is lost, and a returned reply can describe only partial work.

Observation efficiency also has direct prior art:
[A11y-Compressor](https://arxiv.org/abs/2605.00551) reports reductions from
structured accessibility observations, including modal handling. Replicate a
simple comparable transformation before proposing a novel learned compressor.
Its reported token reductions cannot be transplanted as our savings estimate.

**Inference:** the opportunity is to make execution state and evidence useful to
any connected agent, without requiring a replacement planning system. Whether
people value that enough to switch tools remains untested.

## 4. Expansion options, ranked

These rankings are engineering judgement based on the inspected project, not
market measurements. Effort assumes one maintainer and excludes the unknown
cost of broad application compatibility.

| Direction | User benefit and demonstration | Mathematical leverage | Decision |
| --- | --- | --- | --- |
| Precise observations + checked actions | A save/setting operation reports what changed, what was checked and what remains unknown | Predicate abstraction, contracts, partial observation | **First experiment**; directly addresses recorded failures |
| Reusable checked procedures | Perform the next similar desktop task with fewer model decisions; stop or recover when prerequisites differ | Typed composition, state abstraction, temporal abstraction | **Main expansion** after checks work; pilot a handful of procedures |
| Reviewable task workspaces | Run on copies, inspect output changes, accept selected artifacts | Effect sets, provenance, partial inverses | **Second product experiment** for document-heavy users |
| Scientific/creative workflow packs | Produce a useful map, diagram or analysis artifact with checkable requirements | Domain invariants, geometry, numerical validation | **Audience experiment**, not an immediate restriction of general scope |
| Symmetry and perturbation harness | Show a task still works after movement, rescaling, dialog changes or interrupted execution | Groups, metamorphic relations, state refinement | **Supporting research**, not a testing-product pivot |
| Portable isolated machine | Easier access for users outside Linux; stronger boundary where properly configured | Little need for new algebra | **Defer** until demand justifies provisioning/security maintenance |
| New agent model, multi-device fleet, general workflow marketplace | Broad ambition but large integration/training/distribution burden | Possible, but no local evidence of necessity | **Do not start now** |

### A. Reusable procedures: the most promising expansion

Example: “Import this month's CSV into the workbook, preserve the formulas,
update the chart, export the report and show me the checks.”

The agent plans the first instance. Supported portions become parameterised
procedures with prerequisites, applicability constraints, output checks and stop
conditions. On later instances, software resolves targets and checks each
milestone; the agent handles exceptions. A familiar task should require less
reasoning without suppressing evidence of mistakes.

Start with hand-authored procedures. A recording alone does not say which
coordinates were incidental, which values are parameters, or what must remain
unchanged. Automatic extraction is a later hypothesis. Store application/version,
locale assumptions and known unsupported variants; fail outside scope.

Do not build another agent planner. Expose bounded procedures through the existing
interface. Measure authoring time and reuse count: an elaborate procedure that
saves seconds twice is a bad investment. CUA-Skill and conventional automation
are baselines, not evidence that this exact Linux offering has product fit.

A simple break-even calculation helps: if a procedure costs H minutes to author
and maintain and saves Δ minutes per successful use, it needs more than H/Δ uses
to repay that time, before accounting for failures. Compare with a direct script
or application API as well as repeated model control. A procedure library becomes
valuable through recurring demand and low maintenance, not its number of entries.

### B. Reviewable task workspaces: a tangible user feature

An agent works on a project-local copy of selected files. The person receives
changed artifacts, before/after views and relevant checks before accepting them.
This could make office, design and configuration tasks easier to trust.

Begin with files, not arbitrary live desktops. Use content hashes and explicit
conflict detection when the original changes during the task. An ODS file needs
a cell/formula comparison; binary byte diffs alone are unhelpful. Reopening an
application is not restoring its process state. Network writes and remote
messages cannot be reverted by replacing local files.

A checkpoint/review feature fits the general computer-use goal. “Git for every
desktop action” would overpromise: live state, undo history, external services,
and credentials do not admit universal branching and merging.

### C. Scientific workflows: promising audience, unproven demand

Researchers and technical users have desktop tasks with meaningful output
invariants: units, formulas, geometric constraints, exported layers and file
structure. Consider QGIS map exports, Inkscape figure preparation, or a
LibreOffice-based analysis workflow. These are candidate examples, not verified
application support for this project.

[OSWorld-Science](https://arxiv.org/abs/2609.39903) already studies scientific
software and artifact evaluation; [DeskCraft](https://arxiv.org/abs/2606.03103)
studies long creative workflows with human interaction. Consequently, neither
“science agents” nor collaborative desktop work is a new category. Their value
here is to suggest tasks and evaluators, not to establish paying users.

Start with the already tested office/browser applications and one real recurring
task. Expand application coverage when an interested user brings a concrete need.

## 5. Concrete design for the first implementation

### Precise, bounded observation

Extend the existing UI query with exact predicates and field projections:
session, app identity, window identity, ancestry/modal scope, role, exact name,
required state, and requested fields. Resolve all predicates in the same scope.
Return zero/one/multiple matches, traversal completeness and observation provenance.

Use three-valued results: **true, false, unknown**. A missing node in an incomplete
tree means unknown. A duplicate label means ambiguous, not “choose the first”.
Version/revision metadata must state what it covers; an AT-SPI event counter is
not an atomic snapshot of the application. Keep visual fallback for canvases,
poor accessibility, spatial requirements and unexpected dialogs.

### Checked actions, not blanket retries

Illustrative future interface, **not implemented syntax**:

```yaml
session: explicit-session-id
scope:
  application: identified-process
  window: resolved-window-id
require:
  - unique_target: {role: check_box, name_exact: Show grid}
  - modal: absent
operation:
  ensure_checked: true
verify:
  - target_checked: true
on_unknown: stop_and_return_evidence
```

Separate at least these outcomes: precondition not established; dispatch
acknowledged; effect observed; postcondition contradicted; effect unknown.
Record attempted actions separately from satisfied goals. If the property already
holds, `ensure` may finish without dispatch; that does not establish that a prior
action caused it. Polling after dispatch may be safe when repeating dispatch is not.

Checks can reduce time-of-check/time-of-use errors but cannot make arbitrary GUI
interaction atomic. The exclusive controller lease does not freeze the app,
timers, external processes or remote services. Re-resolve before dispatch and
check afterwards; stop when identity or applicability is uncertain.

Prefer simple predicates local to the runtime. Durable output verifiers should
be explicit, bounded adapters for a selected artifact/task, with trusted parsing
code and task-scoped paths. Do not let UI text supply executable verifier code.
Output checks can use files/APIs even when the task's interaction policy restricts
the agent to GUI actions; keep this independent evaluator access out of the agent.

### Evidence and boundaries

Return a compact receipt: scope, required predicates, observed effect, verifier
identity/version, evidence references, uncertainty and next permitted options.
“Verified” always means a specified property under stated assumptions, not all
possible user requirements. Preserve unrelated required content in the verifier.

Current traces deliberately omit typed text and command arguments. Procedure
recording would change that privacy boundary: make it explicitly enabled for
selected task data with retention controls. Never silently turn existing traces
into a dataset containing credentials or personal work.

No claim of a security sandbox follows from these checks. Same-user applications
and unrestricted agent tools remain outside the proposed controller's enforcement
boundary. Input from a document/webpage is data, not authority to change a contract.

## 6. Mathematics that earns its place

The equations below are proposed models/derivations. They do not assert that the
real desktop satisfies their assumptions.

### 6.1 Task-dependent quotients and behavioural equivalence

Let S be concrete states, A the supported actions, F_a:S→S a deterministic
transition, and q:S→{0,1} the required outcome. An abstraction φ:S→Z supports
well-defined abstract actions when

\[
\phi(F_a(s))=\bar F_a(\phi(s)),\qquad q(s)=\bar q(\phi(s)).
\]

Equivalently, states merged by φ must agree on q and their successors must remain
merged under every supported action. This is a congruence for the action system.
It is far stronger than a summary that sounds sufficient for the next click.
For partial actions, equivalent states must also agree on enabledness, or explicit
failure states must be represented.

For a finite stochastic model, preserve reward and aggregate transitions into
each abstract class:

\[
\sum_{u:\phi(u)=z'}P(u\mid s,a)
=\bar P(z'\mid\phi(s),a).
\]

More general MDP homomorphisms also map actions. See
[MDP Homomorphic Networks](https://arxiv.org/abs/2006.16908) for symmetry-based
policy structure. Desktop screenshots are partial observations, so current UI
state alone generally cannot meet a Markov-state assumption. Relevant history,
pending operations and uncertainty may have to be retained.

**Practical research question:** can a compact representation retain enough
information for both task completion and failure detection on held-out workflows?
Begin with explicit features and refine on counterexamples. Do not train an
embedding and assume nearby vectors mean safely interchangeable states.

### 6.2 A small exhaustive experiment, actually run

[abstraction_experiment.py](abstraction_experiment.py) enumerates 128 states:
document identity, focused cell, modal presence, two live binary cell values,
and two persisted values. Actions focus either cell, write one, save, or close a
modal. The outcome is that the target document has persisted values `(1, 0)`.
The deliberately simple model makes writes/save no-ops while a modal is open.

The summary `(document, modal, dirty)` creates eight classes. Enumeration finds
both a goal contradiction and a transition contradiction inside those classes:
two clean documents with different content look identical under the summary,
but disagree on success; writing one also changes their dirty states differently.

Splitting first by goal and then by successor-class signatures yields class
counts **12 → 20 → 50 → 82 → 93 → 94**. At the fixed point, all 60 distinct pairs
remaining within classes agree on the goal and all **300** action comparisons
preserve the equivalence. See [recorded output](abstraction-experiment.json).

This computes the coarsest stable refinement of that initial partition for this
model. It does **not** discover a universally minimal desktop representation.
The modest reduction from 128 to 94 is instructive: preserving behaviour may
require most of the distinctions that an attractive short summary removed.
No token savings, real UI robustness or novel algorithm was demonstrated.

### 6.3 Abstract interpretation: make uncertainty explicit

Let an abstract observation z describe a set γ(z) of possible concrete states.
A sound approximate transition should contain every possible successor:

\[
F_a(\gamma(z))\subseteq\gamma(\widehat F_a(z)).
\]

An outcome q is established only if all states in γ(z) satisfy q; contradicted
if all violate it; otherwise unknown. This is a useful foundation for incomplete
accessibility trees, uncertain delivery and lost events. See
[Cousot and Cousot](https://www.di.ens.fr/~cousot/COUSOTpapers/POPL77.shtml).

In practice we do not enumerate all desktop states. Implement a restricted
predicate domain and conservative unknowns. A learned detector has empirical
error; its confidence must not be silently substituted for a sound abstraction.
Refining merged states after failures is inspired by
[counterexample-guided abstraction refinement](https://www.cs.cmu.edu/~emc/papers/Conference%20Papers/Counterexample-guided%20Abstraction%20Refinement.pdf),
but collecting examples alone is not a formal CEGAR proof of the real application.

### 6.4 Group actions: transport geometry, test invariance

Translations and positive uniform scales form a group with

\[
g(p)=sp+b,\quad
(s_2,b_2)(s_1,b_1)=(s_2s_1,s_2b_1+b_2),\quad
(s,b)^{-1}=(1/s,-b/s).
\]

If targets transform with the image, a detector should obey
`f(g·I)=g·f(I)`. A semantic decision might instead remain invariant. The existing
crop mapping `p=q/s+c` already implements a useful instance of this geometry.

Stronger policy transfer requires transition compatibility,
`F_(g·a)(g·s)=g·F_a(s)`, and a task outcome that transforms consistently. Moving a
window can approximate this under controlled conditions. Resizing an application
can reflow its layout; a crop can remove the target; resampling loses detail.
These are not automatically invertible actions on desktop state.

Use this mathematics first for **metamorphic tests**: move an otherwise unchanged
window and require the same document outcome; crop/scale a screenshot and require
the same underlying target after inverse mapping. Verify each transformation's
assumptions. Treat locale, theme, popups and layout reflow as broader perturbations,
not members of a convenient group by assertion.

[WorldGUI](https://arxiv.org/abs/2502.08047) already evaluates varied starting
states, and [RealGUINoise](https://arxiv.org/abs/2609.38184) studies interface
perturbations. Our candidate contribution is using failures to refine a runtime
representation or procedure applicability, not merely adding noisy screenshots.

### 6.5 Monoids, typed composition and why undo is not an inverse

Action strings form the free monoid A*: concatenation is associative and the
empty sequence is its identity. Their execution maps into partial state
transformations, which generally neither commute nor have inverses.

Give procedures contracts `{P} a {Q}`. Composition `{P} a;b {R}` requires the
first postcondition to establish the second precondition, and compatible effect
and interruption assumptions. This is the practical content of a typed
composition view, grounded in [Hoare's logic](https://doi.org/10.1145/363235.363259).
Runtime checks monitor these obligations; they do not prove the implementation.

Idempotence `a∘a=a` supports retries only for the state and side effects actually
modelled. Setting a field may be idempotent in the field value while firing a
webhook twice. An operation ID in our trace cannot deduplicate an external app
that never receives or honours it. Preserve uncertain delivery and verify before
considering a repeat.

An inverse requires `a⁻¹∘a=id` on a stated domain. Most GUI “undo” commands depend
on hidden history and omit remote effects. A **groupoid** fits only supported
invertible mappings between explicitly defined states/contexts. It does not make
all GUI operations reversible. [Sagas](https://www.cs.princeton.edu/techreports/1987/070.pdf)
offer the more appropriate precedent for compensating steps: compensation is
an application-defined repair, not mathematical erasure of history.

### 6.6 Partial commutativity and concurrency

Two actions can be reordered only when both orders are valid and equivalent for
the relevant observations/outcomes. Disjoint read/write sets can be a sufficient
condition in a specified deterministic model. In a desktop, apparently different
windows may share clipboard, focus, files, login state or network side effects.

Model resource effects before parallelism. Keep the current exclusive controller
for one session. Independent sessions are safer candidates, but still may share
host resources. Partial-order reduction and systematic schedule testing, such as
[CHESS](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/tr-2007-149.pdf),
are useful testing precedents; not a reason to allow concurrent arbitrary clicks.

### 6.7 Information gathering as a decision problem

Let b be beliefs about the current state, L(a,s) the loss from acting, and an
observation o cost c(o). A one-step value-of-information rule compares

\[
\min_a\mathbb E_b[L(a,s)]
\quad\text{with}\quad
c(o)+\mathbb E_y\left[\min_a\mathbb E_{b\mid y,o}[L(a,s)]\right].
\]

This derived decision rule explains why a tiny exact predicate can be preferable
to another screenshot, and why an expensive observation is worthwhile before an
irreversible action. It assumes an adequate belief/loss model; the runtime does
not have calibrated ones today. Use measured fallback/error rates to begin with
a simple observation ladder, not fictitious probabilities.

Finite-horizon reusable procedures also resemble options in hierarchical control:
initiation conditions, an internal policy and a termination condition. See
[Sutton, Precup and Singh](https://www.ece.uvic.ca/~bctill/papers/learning/Sutton_etal_1999.pdf).
Their duration matters to cost and latency. Learning an option library is a later
research project; explicit procedures are enough for the first product test.

## 7. What would count as being better?

First choose a target user: a Linux user who already runs an agent and repeatedly
needs desktop-only portions of document, configuration or project work. This is
a proposed initial audience, not a confirmed market segment.

Compare on separate axes:

- First successful task from a clean supported installation, including help needed.
- Independently checked completion and preservation of unrelated required state.
- Wrong-target actions, false success, duplicated side effects and recovery burden.
- Total cost per verified success, p50/p95 time, and human intervention minutes.
- Idle/active resources and session startup, clearly separating app launch/model time.
- Procedure authoring/maintenance effort and repeated use by people other than us.

Do not collapse security, breadth, reliability and speed into a single score.
Native host applications and a VM have different boundaries; report that tradeoff.

### A fair experiment sequence

**Stage 0: no paid calls.** Add fixture fault cases and independent verifiers.
Seed wrong-cell edits, a disabled/no-op button, duplicate labels, wrong documents,
truncated trees, delayed completion, a modal, stale targets, and a reply lost
after dispatch. Ensure the verifier rejects a no-action run and deliberately
corrupted outputs. Use disposable task data and explicit private sessions.

**Stage 1: internal ablation, budget agreed separately.** Use 12 workflow instances
across browser, GTK/Qt and office tasks, two repetitions per condition, with
fixed model/settings and independently restored starting data. Compare current
tools, exact queries only, queries plus checks, and checks plus hand-authored
procedures: 96 runs. Treat this as a screening pilot, not a precise reliability
estimate. Include supported tasks with poor accessibility and visual outcomes.

Counterbalance run order. Pin application/runtime/model versions, tool schemas,
cache policy, account configuration and output verifiers. Record all attempted
runs, timeouts, token billing categories and setup failures. Keep runtime-only
timings separate from model time. Predefine task timeout and retry allowance.

**Stage 2: external baselines only after a useful internal gain.** Compare with
Cua Native Driver and the closest Linux alternative that supports each task;
include a browser/API baseline when applicable. Use a common-tool track to isolate
runtime effects and a best-available-tools track to compare complete user value.
Do not disable a competitor's stronger interfaces and call the result superiority.
Report unsupported configurations separately from failed supported tasks.

**Stage 3: held-out transfer.** Test new input files and separately test new
layouts, versions and applications. These are different generalisation claims.
Include resumption after human correction; never reuse the exact training traces
as the sole evidence of procedure reuse. Compare with the existing observation
compression strategy before claiming a novel abstraction win.

Primary cost measure:

\[
\frac{\text{total cost of all attempts}}{\text{number of independently verified successes}}.
\]

If no tasks succeed, this ratio is undefined/infinite, not zero. Also report raw
completion and total cost. Report paired differences and uncertainty; bootstrap
by workflow/task cluster when repeated trials share structure. Treat model and
application failures as observations rather than silently discarding them.
With zero failures in n independent comparable trials, the approximate 95% upper
failure bound is 3/n; even 100 clean trials do not establish 99.9% reliability.
Correlated fixtures and changing builds make that approximation less applicable.

### Proposed stop/go rules

These are decision thresholds to choose before trials, not predicted results:

- Exact queries: materially smaller observations (target 30% median reduction)
  with no known omission that causes false success in the fault suite.
- Checked actions: detect the seeded no-op/wrong-target failures; preserve unknown
  when completion cannot be established; never automatically repeat uncertain
  non-idempotent operations. Repeated clean tasks should not become impractically slow.
- Procedures: target at least 20% lower cost per verified success on the selected
  repeated-task workload, without worse completion or additional false success.
  Include authoring and maintenance effort in the adoption decision.
- User value: recruit five target users after appropriate release/access approval;
  aim for at least three to repeat a useful task without developer help. A tiny
  convenience sample is discovery, not population-level demand evidence.
- Stop or narrow if gains occur only on one exact fixture, verifiers are too
  expensive to author, users prefer scripts/APIs, or procedures break on routine
  variations. Improving packaging and a small observation API remains a useful
  outcome even if the larger reuse hypothesis fails.

## 8. Suggested stages and distribution

| Stage | Reviewable output | Rough effort, not a deadline |
| --- | --- | --- |
| 1 | Exact UI predicates/projections and ambiguity/completeness tests | Several days to one week |
| 2 | Checked action contract, compact evidence and fault fixtures | One to two weeks |
| 3 | Three recurring workflows with bounded procedures and durable verifiers | One to two weeks, strongly app-dependent |
| 4 | Held-out/competitor pilot and user feedback | One to two weeks plus user availability |

Keep daily-use hardening and the outstanding real login/Dvorak handoff checks
alongside this work. Do not label these stages a production release gate passed
by the existing pilot.

For attention and adoption, lead with an outcome people recognise: update a
spreadsheet/report, preserve its formulas, survive an unexpected dialog, and show
the resulting files and checks while the user's desktop stays usable. Show an
unedited run or disclose every cut, with total elapsed time and interventions.
Provide one supported installation path per demonstrated platform, a short
reproducible example and a clear failure report. The code should be easy to try
without reading a research paper.

Publish a small compatibility/procedure pack before a marketplace. Measure repeat
use, setup abandonment, support burden and external contributions; GitHub stars
are an attention signal, not utility. Distribution through existing agent clients
is a hypothesis worth testing because the project already integrates there.
No outreach was sent and no publication is authorised by this research request.

## 9. Research contribution worth pursuing if the product experiment works

A defensible question is:

> Can counterexample-refined, task-dependent observations and contracts reduce
> reasoning/observation cost while preserving outcome discrimination under
> controlled GUI variation?

The contribution would need an explicit representation, refinement algorithm,
held-out applications/variations, realistic verifiers, and ablations against
ordinary predicates, compressed accessibility trees and reusable skill systems.
Measure representation size, false merges, action/outcome disagreement,
verification errors, refinement cost and total task cost. A theorem can establish
properties of a specified finite transition model; real-world performance still
requires experiments and documented assumptions.

This is a more promising mathematical ambition than adding group-theoretic
terminology to a screenshot controller. The experiment here shows both the
opportunity and the obstacle: some distinctions can be discarded, but much of
what looks like redundant desktop detail may be essential to judging success.

## 10. Limits and next decision

The strongest evidence is the project's own recorded execution failures and the
current gap between delivery checks and task outcomes. The weakest part is
market demand: no interviews or external use were measured. Literature and
competitor documentation establish overlap, not how satisfied their users are.
This search cannot certify novelty, patentability or the absence of another tool.

**Recommended next decision:** authorise one bounded implementation stage for
precise UI predicates/projections, then checked actions on two known workflows.
Keep reusable procedures as the product hypothesis and abstraction refinement as
the research hypothesis. Reconsider after evidence, before investing in a new
model, platform fleet, or broad compatibility layer.

## Reproduction and source navigation

Run the finite experiment from the repository root:

```sh
uv run python docs/research/abstraction_experiment.py
```

The JSON alongside this report records its deterministic output. This script
performs no desktop, network or paid-model operations.

Sources are linked at the claims they support. Foundational sources: Hoare
(contracts), Cousot/Cousot (sound abstraction), Clarke et al. (refinement),
MDP Homomorphic Networks (symmetries), Sutton et al. (options), Sagas
(compensation), and CHESS (schedule testing). Current application sources:
wbox, kde-mcp, Cua, E2B, UFO, CUA-Skill, Playwright, A11y-Compressor,
Verified Tool Calls, verifier research, OSWorld-Human/2.0/Science,
Desktop-Delta Bench, WorldGUI, RealGUINoise and DeskCraft. Consult the linked
version history rather than search-result publication-age labels for paper dates.
