# Observation and context optimisation research

Date: 2026-10-07. Research note based on a read-only examination of the runtime,
recorded benchmarks and primary literature. No implementation changes or new
benchmark experiments were performed. Proposals below are not measured savings.

## Recommendation

Build a task-directed observation layer around the existing runtime, then test
client-side context retention. Supply the information needed for correct action
and outcome verification; retain full evidence outside active model context for
selective retrieval.

Prioritise precise semantic queries and projected fields over custom image codecs
or learned visual compression. Existing evidence identifies verbose observations,
but does not establish which billing component dominates total cost.

## Existing capabilities and gaps

| Mechanism | Existing capability | Remaining opportunity |
| --- | --- | --- |
| Crops and scaling | Screenshot regions, scaling and inverse coordinate mapping through observation tokens | Adaptive selection and easier retrieval of detail |
| Semantic UI | Application/window filters, node limits, compact rendering and semantic actions | Exact predicates and field-level projections |
| Short element IDs | Worker maps AT-SPI object addresses to short IDs without deliberately reusing old IDs | Revisions and stronger validation of changed or recycled application objects |
| Compact verification | Waits return at most five matching elements; disappearance is not inferred from a truncated tree | Explicit ambiguity and precise value-comparison semantics |
| Action batching | Up to 50 steps with window/focus/output checks | Verified preconditions and postconditions; changes inside windows remain a limitation |
| Image storage | Local artifact paths and bounded retention | Screenshot tool currently also embeds the image; selective artifact retrieval needs client support |
| Observation policy | MCP instructions favour screenshot, action, screenshot | Prefer a compact predicate when it establishes the required outcome |

Source entry points:

- [MCP tools](../../src/agent_desktop/mcp_server.py): `desktop_ui`,
  `desktop_screenshot`, `desktop_wait` and server instructions.
- [Worker](../../src/agent_desktop/worker.py): element registry and screenshot
  coordinate conversion.
- [Core](../../src/agent_desktop/core.py): wait matching, result limits and
  incomplete-tree handling.
- [Usage guide](../USAGE.md): current capabilities and boundaries.

## What the evidence supports

The [tool-profile comparison](../BENCHMARK.md#tool-profile-comparison-2026-10-04-claude-opus-5-5-accessibility-on-in-both)
reduced calls by about 37% on the hard suite and 15–18% on the standard suite.
Standard-suite costs nevertheless increased 5–9% in matched rounds. The report
records Chromium UI listings of 10–13K characters retained in context.

A later compact-listing run improved results, but lacked a contemporaneous matched
baseline. This supports investigating verbosity; it does not demonstrate a net
cost advantage from a particular new policy.

The restricted native/Cua browser comparison completed 6/6 trials on each runtime:
native 46 calls, 104.7 seconds and $0.5183458; Cua 49 calls, 84.0 seconds and
$0.5291320. These are model-usage figures for a small comparison with different
environments, not general performance rankings.

The [recorded comparison JSON](../../benchmarks/results/2026-10-04-browser-comparison.json)
contains input, cache-write, cache-read and output counters. Billing-category
attribution may be reconstructed using the historical pricing assumptions.
Image-versus-text attribution requires additional instrumentation or controlled
counterfactual counts. Do not claim that screenshots or accumulated input are
proven to dominate cost.

## Cost model

An accounting model is:

\[
C=\sum_t(p_uU_t+p_wW_t+p_rR_t+p_oO_t)+C_{\mathrm{local}},
\]

where U, W, R and O are uncached input, cache writes, cache reads and output
tokens, respectively, with their corresponding prices. Images and text contribute
to input; aggregate token totals obscure differences in billing rates.

If each of T turns appends b tokens and retains all preceding content, cumulative
presented input is approximately:

\[
b(1+2+\cdots+T)=bT(T+1)/2.
\]

This illustrates repeated context exposure, not dollar growth at an uncached rate.
Prefix caching, compaction and actual client behaviour change the accounting.
Removing early observations can avoid many later exposures, but rewriting history
can invalidate useful cache prefixes. Measure the actual billing categories.

The primary objective should be:

\[
\frac{\text{cost of all attempts, including failures}}
{\text{independently verified successful tasks}}.
\]

Track completion, wrong actions, false success claims and latency alongside it.

## Algebra: task-preserving quotient states

Let S be complete environment state and let a representation map be:

\[
\phi:S\to Z.
\]

Define an equivalence relation by:

\[
s\sim t\iff\phi(s)=\phi(t).
\]

A partition alone is insufficient: mapping every state to one class is extreme
compression that preserves nothing useful. For a deterministic action a, a stronger
condition is:

\[
\phi(F_a(s))=\bar F_a(\phi(s)).
\]

Acting and then compressing should agree with applying an abstract action to the
compressed state. Equivalently, equivalent states should remain equivalent under
the relevant operation. Success and failure conditions must also be constant
within classes. This is compatibility with operations, or a congruence, rather
than an arbitrary equivalence relation.

For stochastic transitions, an analogous abstraction preserves probabilities of
moving into abstract classes and task rewards. This connects to MDP homomorphisms
and bisimulation. Real desktop observations are partial and applications may have
hidden state; these conditions are design goals, not established runtime properties.

Example representation:

```text
document: Budget.ods
unsaved_changes: true
save_dialog: absent
```

This may support deciding to save, but cannot establish that the intended cells
were edited. Two spreadsheets with different incorrect contents would collapse to
the same representation. Preserving the next action is weaker than preserving the
information required to complete and verify the task.

Use counterexample-driven refinement:

1. Propose a small task-dependent representation.
2. Find states it merges that require different actions or outcome judgements.
3. Add the missing distinction.
4. Evaluate on held-out workflows.

A small finite UI simulator could make the equivalence classes and compatibility
conditions explicit before testing approximate abstractions on real applications.

## Groups: coordinate transforms and equivariance

Positive uniform scaling and translation form a group:

\[
g(p)=sp+b,\qquad s>0.
\]

Composition and inversion are:

\[
(s_2,b_2)\circ(s_1,b_1)=(s_2s_1,s_2b_1+b_2),
\]

\[
(s,b)^{-1}=(s^{-1},-b/s).
\]

For a crop beginning at desktop position c with scale s, image position q and
desktop position p satisfy q=s(p-c), hence p=q/s+c. The runtime already implements
this essential mapping.

A target detector should ideally be equivariant:

\[
f(g\cdot I)=g\cdot f(I).
\]

Transforming an observation should transform the predicted target consistently.
Semantic choices such as selecting Save may instead be invariant.

Useful applications: canonical coordinate frames, transform metadata on crops and
tests that different views produce the same desktop target. Limits: cropping loses
information, resampling loses detail and application resizing can cause layout
reflow. Coordinate groups do not justify unrestricted reuse of old clicks.

## Monoids: action sequences and verified procedures

Finite action sequences form a free monoid under concatenation: composition is
associative and the empty sequence is an identity. Typical desktop actions have no
general inverse and need not commute. Focus-then-type differs from type-then-focus.

Give reusable procedures a precondition, ordered sequence, postcondition and
interruption/recovery rule. Prefer these to long unobserved action chains.

Idempotence, f composed with f equals f, helps reason about retries. Setting a
field to an exact value is a candidate; toggling a checkbox is not. Even set-text
may trigger external handlers, so interface-level idempotence does not establish
side-effect idempotence.

## Information theory and observation selection

The information-bottleneck perspective suggests preserving information predictive
of task-relevant outcomes rather than all pixels. We do not know the required
distribution or possess a universally sufficient desktop representation, so this
is a design lens rather than a ready-made algorithm.

A practical observation ladder is:

1. Query a precise property.
2. Retrieve a small semantic neighbourhood if ambiguous.
3. Retrieve a detailed crop.
4. Retrieve a full screenshot when broader visual context matters.

Proposed API example, not currently implemented:

```text
query:
  window: Budget.ods
  role: push button
  name_exact: Save
  fields: [enabled, visible]
  limit: 3

result:
  matches: 1
  node: n42
  enabled: true
  visible: true
  observed_at: ...
  coverage: complete
  revision: 42
```

Missing results must remain unknown when traversal failed or was truncated.
Ambiguous matches must remain ambiguous. Exact and substring comparisons need
explicit semantics. Include sufficient window/modal context, and distinguish
observed facts from inferred success.

## Implementation boundaries

| Layer | Appropriate work |
| --- | --- |
| Runtime/MCP | Precise queries, projections, revisions, crops, compact evidence, artifact retrieval, local predicates and event subscriptions |
| Client | Observation selection, history removal/compaction, retrieval decisions, cache layout and model routing |
| Model/provider | Vision tokenisation, KV caching, visual-token pruning, architecture and training |

MCP resource links can identify retrievable artifacts. Savings depend on whether
the client fetches or embeds them. The server cannot generally erase images already
in the client's conversation.

PNG/JPEG byte compression is not a reliable image-token optimisation. Processed
dimensions and model-specific processing matter. An artifact reference or embedding
does not let a model see an image without retrieving relevant content.

Cache freshness and representation sufficiency are separate: a fresh cache may
contain an inadequate summary, and a sufficient summary may become stale.

## Prioritised extensions

1. Precise semantic predicates and projected fields, preserving completeness and
   ambiguity information.
2. Observation policy using existing compact waits when they prove the required
   property, with visual fallback for genuinely visual outcomes.
3. Client-side bounded history: goals, completed commitments, unresolved
   uncertainties, recent evidence and retrievable artifact references.
4. Adaptive crops, measuring extra retrieval turns and lost surrounding context.
5. Revisioned deltas applied in software to produce a compact current view. Require
   baseline validation and full resynchronisation; do not make the model reconstruct
   long delta chains. Short IDs alone do not prove semantic identity.
6. Event-driven local waiting with periodic reconciliation. Events prompt
   rechecking; they do not prove the absence of other changes.
7. Reusable verified procedures with explicit preconditions and recovery.
8. Model routing or learned visual compression after simpler savings are measured.

## Bounded evaluation plan

| Experiment | Comparison | Failure cases |
| --- | --- | --- |
| Accounting | Reconstruct category costs from existing counters | Historical rates, discarded attempts, cumulative versus per-call counters |
| Query projection | Full listings versus targeted queries | Duplicate labels, truncation, absent accessibility and stale controls |
| Verification policy | Screenshot-after-action versus explicit predicates with fallback | Wrong document, false success and transient indicators |
| Crops | Full-resolution versus coarse-to-fine observation | Tiny text, unexpected dialogs, moved windows and extra retrievals |
| History | Current retention versus milestone compaction | Forgotten requirements, lost failures and cache invalidation |
| Deltas | Full semantic snapshots versus revisioned changes | Lost events, baseline mismatch, object replacement and app restart |

Use paired starting states, alternate execution order and fix model/settings/app
versions. Independently inspect durable outputs. Include ordinary workflows and
adversarial cases. Report cost per verified success, completion, wrong actions,
false success, latency and fallback frequency. Small pilots can reject bad designs;
they cannot establish narrow reliability guarantees. New paid experiments require
an agreed scope and budget.

First implementation experiment: targeted UI predicates/projections compared with
existing listings. Test context retention separately to distinguish observation
savings from cache effects.

## Primary sources

These sources were consulted on 2026-10-07. Documentation can change; research
results do not establish savings for this runtime.

- [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching):
  prefix reuse and cache billing categories.
- [Vision](https://platform.claude.com/docs/en/build-with-claude/vision):
  image processing and token accounting.
- [Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents):
  selective retrieval, compaction and removal of old tool results.
- [MCP tools and resource links](https://modelcontextprotocol.io/specification/2025-06-18/server/tools):
  artifact references and client retrieval.
- [AT-SPI event listeners](https://docs.gtk.org/atspi2/class.EventListener.html):
  UI-change notifications.
- [Reusable MDP homomorphisms](https://cdn.aaai.org/AAAI/2006/AAAI06-085.pdf):
  abstractions compatible with task dynamics.
- [The information bottleneck method](https://arxiv.org/abs/physics/0004057):
  compression preserving target-relevant information.
- [A11y-Compressor](https://arxiv.org/abs/2605.00551):
  accessibility observation redundancy and visual context.
- [AQuaUI](https://arxiv.org/abs/2605.19260):
  adaptive spatial visual-token reduction requiring model-level integration.

The central research question is: **How small can a task-dependent observation be
while preserving correct actions and correct outcome verification?**
