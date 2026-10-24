# Completion evidence, correctness gaps and general expansion directions

Date: 2026-10-15. Source reviewed: `711f1ca` on `main`. Research branch:
`research/completion-correctness-2026-10-15`, based directly on `main`, with no
stacked dependency. This is an investigation and proposed work, not an adopted
pivot or an implementation of the fixes. It preserves general computer use by
existing agents as the product goal.

Archival clarification (2026-10-24): recovered from the unpublished research
stash. Findings and output below describe `711f1ca`, not the current runtime.
The subsequent R1–R6 implementation is recorded in the
[current project plan](../project/PROJECT_PLAN.md); its implemented behavior and
remaining limits supersede this report's proposed repair stages. Current work
follows the [functionality roadmap](../project/FUNCTIONALITY_ROADMAP.md).
The probe script and saved JSON are historical reproductions, not current
regression tests. Run the reproduction commands below only in a separate
checkout of `711f1ca` with the archived probe script copied into it; the script
expects the old APIs and failure behavior and is not compatible with current main.

## Recommendation

The strongest next technical direction is to make the runtime consistently
answer three questions: **what was attempted, what was actually observed, and
what remains unknown?** Fix the places where evidence is lost or overstated,
then build richer checked actions and recovery on that foundation.

This is broader than a particular task or customer. Every application presents
some combination of incomplete observations, asynchronous changes, ambiguous
targets and uncertain delivery. The project already has many of the right
pieces: delivery flags, explicit sessions, takeover epochs, bounded UI trees,
postcondition waits, independent benchmark checks and an experimental ledger.
The immediate opportunity is to join those pieces without promoting local
evidence into a universal claim of completion.

The runtime cannot force an external model to tell the truth in its final reply,
and cannot infer arbitrary user intent from a successful click. It can provide
better evidence, refuse unsupported assertions, and expose contradictions.

## Evidence and scope

- Read the current plan, directions board, E6 results, relevant runtime code,
  existing correctness tests and benchmark outcome checks.
- Ran ten focused observations in [completion_probes.py](completion_probes.py).
  Exact output: [completion-probes.json](2026-10-15-completion-probes.json).
- Probes call production functions with synthetic boundary responses, temporary
  files and one short-lived child process. They use no graphical desktop,
  account, network or paid model. A mocked response establishes the function's
  behaviour for that response; it does not establish real-world frequency.
- Ran five existing correctness tests and five tree-bound tests: all passed.
  No full desktop suite or new model-driven benchmark was run.
- Consulted primary external documentation for design comparisons, linked below.
  No novelty, universal reliability or performance claim follows from this review.

Reproduce from the repository root after the normal locked uv setup:

```sh
uv run python docs/research/completion_probes.py
uv run python -m unittest discover -s tests -p test_correctness.py -v
uv run python -m unittest discover -s tests -p test_tree_bounds.py -v
uv run ruff check docs/research/completion_probes.py
uv run ruff format --check docs/research/completion_probes.py
```

The probe prints observations, not a regression-test pass/fail verdict. Once a
fix lands, convert its counterexample into a test of the corrected behaviour.

## 1. What “done” currently means

These are separate claims and should remain separate in the API:

| Claim | Evidence available | What it does not establish |
| --- | --- | --- |
| Request accepted | Worker transport reply `ok` | Input receipt or task success |
| Action delivered | Input/API returned without a delivery error | Correct target, persistence or intent |
| Script exited successfully | `exit_code == 0` | Assertions were sufficient, children stopped |
| Screen settled | No sufficiently large pixel change in a bounded interval | App idle, background save finished or server commit |
| Predicate satisfied | A named condition observed at a time and scope | All requirements satisfied or unchanged unrelated state |
| Effect observed | Files/windows/processes/UI changed during a time interval | Causation, complete coverage or desired outcome |
| Task verified | Independent checks cover the task requirements | Correctness outside those checks and assumptions |

The existing [E6 result](2026-10-14-e6-skills.md) is a historical example of
the distinction: the script's own assertions passed on a partial view, while
the independent fixture check rejected its result. This review did not rerun
E6. The benchmark already calls `task.check(context)` separately from execution
in [scripts/benchmark.py](../../scripts/benchmark.py); preserve that separation.

## 2. Concrete findings and fixes

Priority P1 means fix before building stronger completion/reuse claims on the
affected surface. P2 means important experimental hardening. Priorities reflect
failure consequences, not measured incidence.

### F1 — Incomplete UI evidence is accepted or hidden (P1)

Source: `core.resolve_element`, `core.render_tree`, `script.listing`,
`script.one` in [core.py](../../src/agent_desktop/core.py) and
[script.py](../../src/agent_desktop/script.py).

Reproduced:

- `resolve_element` returns the sole observed match even when `truncated=True`
  and `unreadable=1`. Its docstring promises that incomplete listings raise.
- The script layer reduces a UI reply to `nodes`, discarding both coverage
  flags. `one()` then accepts the apparent unique match.
- `render_tree` returns `(no accessible elements)` for zero nodes with an
  unreadable subtree, without exposing the read failure. `desktop_ui` uses
  this renderer.

One observed match does not establish uniqueness across an unread scope.
Neither an empty partial read nor a visible-only listing establishes absence
from the full application. The existing `core.wait(..., gone=True)` does
correctly refuse absence when its tree is truncated or unreadable; reuse that
principle consistently.

Fix: preserve coverage metadata through every layer. Refuse uniqueness-based
actions when the relevant scope is incomplete, or first narrow and reread that
scope. A positive existence check may legitimately succeed on a partial read;
uniqueness and universal/absence claims need more evidence. Render unreadable
counts and reasons explicitly. Document visible scope even for an untruncated
tree: virtualization is not the same as truncation.

Regression: inject a second matching target in an unread/truncated subtree;
verify no action occurs. Also test known presence, unknown absence, and a
complete narrow scope inside an otherwise incomplete application.

### F2 — A disappeared browser target silently selects another tab (P1)

Source: `Browser.target` in [browser.py](../../src/agent_desktop/browser.py).
When the remembered context disappears and no explicit tab is supplied, the
function picks the last remaining context. The probe returns `unrelated-tab`
after supplying a vanished previous target. No browser click was performed.

The first automatic selection can be a useful default. Reselecting after target
loss is different: subsequent work can continue in an unintended tab. Host mode
has an additional ownership check, which limits some mutations; it does not
make this target-selection contract safe in general.

Fix: distinguish initial selection from target disappearance. Expose stable
context IDs alongside display indices; fail with `target_lost` when a bound
context disappears. Require explicit rebinding, and optionally an expected URL
or document generation before consequential actions. Index selection alone is
vulnerable to tab order changes.

Regression: close/reorder tabs between observation and action; assert that the
action refuses rather than switching contexts. Include private and stand-in
host modes and explicitly selected targets.

### F3 — Operation deadlines and transport deadlines disagree (P1)

Source: `core.request`, `Worker.browser_request`, `Worker.browser_steps`.
The request socket normally waits 30 seconds. Browser waits accept 60 seconds,
navigation uses a 60-second command timeout, typing can take longer, and a batch
can contain multiple operations. The probe confirms that a browser wait with
`timeout=60` still configures the outer socket for 30 seconds.

This reproduces the deadline mismatch, not an actual long navigation. Source
inspection shows worker execution is synchronous and not cancelled when the
caller disconnects. The existing `DeliveryUnknown` response correctly warns
against blind retries, but callers lack an operation ID to reconcile later.

Fix: use a coherent total deadline or asynchronous operation handles with
status/cancellation. Separate delivery state from observation timeout. Retain
the completed prefix and uncertain current step. A caller timeout must not be
presented as proof that an operation stopped or did not happen.

Regression: delayed success, lost reply after a mutation, long batches and
timeout after partial delivery. Verify no automatic resubmission. Proving
at-most-once external effects requires application support or reconciliation;
a local request ID alone cannot provide that guarantee.

### F4 — Optional screenshot failure discards known delivery evidence (P1)

Source: `mcp_server.looked` in [mcp_server.py](../../src/agent_desktop/mcp_server.py).
With `screenshot=True`, capture happens after the action result exists. If it
raises, the wrapper raises without returning that result. The probe supplies
`delivered=True` and a capture error, and receives only `capture failed`.

Fix: return the original action result plus a distinct observation error and
instructions to observe/reconcile before retrying. Apply the same contract to
post-action browser reads and optional effect collection; those paths need
their own failure-injection tests. `core.run_steps` already preserves delivery
when its subsequent observation fails, with an existing regression test.

Regression: input delivered, capture fails; result must retain delivery, avoid
a success claim about the screenshot, and never repeat input automatically.

### F5 — Script timeout leaves child execution alive (P1)

Source: `desktop_run`. It uses `subprocess.run(..., timeout=...)` without a
dedicated process group or descendant supervision for the script.

Reproduced with a temporary-file-only script: the parent times out at one
second; a child writes its marker after the tool returns. Output descriptors
were redirected so this reproduction tests surviving execution rather than
pipe lifetime. The child exits after writing; no desktop input is involved.

Fix: define and supervise a script job. At minimum, terminate and reap its
ordinary process group on timeout/cancellation; account for detached descendants
explicitly if stronger lifecycle claims are desired. Direct script children are
different from applications deliberately launched through the session worker;
do not kill all session applications just to cancel one job. Report whether
cleanup completed, and track already-delivered operations separately.

Regression: child with redirected output, child holding inherited pipes,
cancelled script while a worker operation runs, and session-launched app that
must survive script cancellation. This is lifecycle correctness, not a claim
that arbitrary Python becomes sandboxed.

### F6 — Reading an effect report can destroy its baseline (P2)

Source: `FileRecorder.summarize`, `record`, `before` in
[effects.py](../../src/agent_desktop/effects.py).
Every report appends a version; each path retains six versions. Repeatedly
reporting one unchanged observation interval evicts its pre-action state.
`before` then interprets unavailable history as `(False, None)`.

Reproduced without watcher timing: the first report says `modified` with
`-old/+new`; the eighth says `created` with `+new` for the same existing file.
This conflicts with the function's repeated-report consistency contract.

Fix: make reporting observational, pin the baseline needed by live records,
and return `baseline_unknown` when retention prevents a comparison. Preserve
the distinction between known absence and unavailable history. Bound memory
with explicit expiry, rather than fabricating a creation event.

Regression: repeated reads, writes between reads, expired action IDs, history
eviction and monotonic metadata. The underlying state may change between
queries; the provenance of the baseline must not silently change.

### F7 — Effect collection has additional unreported coverage limits (P2)

Two bounded observations:

- `FileRecorder.add_watch` silently accepts a negative `inotify_add_watch`
  result. The mocked failure leaves no watch and returns normally. Reports
  expose queue overflow, but not this registration failure.
- `odf_lines` caps repeated rows/columns at 1,000 and total output near 20,000
  cells without returning truncation metadata. A valid synthetic document with
  1,001 repeated populated rows produces only 1,000 lines. The caller cannot
  distinguish that partial extraction from a full one.

Fix: track watch failures and unreadable roots; propagate document extraction
coverage and parser limits. Do not classify omitted content as unchanged.
Check decompressed XML size as well as archive size, and bound parsing work.
Review unsupported formats: `.fods` is routed to the ZIP reader even though
flat XML requires a different reader. That format mismatch is source-inspected,
not separately exercised here.

Also source-inspected: action records are capped, but file event history and
the set of versioned paths can grow over a session. Add bounded event retention
with explicit expired evidence. Measure long-session memory before choosing
limits; no soak or memory profile was run in this review.

## 3. Design limitations that should not be mislabelled as bugs

- **Settling is a heuristic.** `Worker.settle` already documents this well.
  Keep it for responsive observation; add explicit predicates for persistence
  and meaningful completion.
- **Observation tokens protect layout/control state, not all content.** The
  current token includes session, output, window identity/state and takeover
  epoch, but not every in-window change. A row can change without changing the
  token. Add target/document-specific revisions where available; do not imply
  a screenshot hash solves the observation-to-action race.
- **Effects are temporal observations.** `since(effect_id)` includes later
  activity, potentially from other actions or application background work.
  Keep time intervals and observer scope visible. Correlation is not causal
  attribution, and no observed effect is not proof of no effect.
- **Browser discovery has scope.** `find` reports a total match count while
  returning at most 30 descriptions; this is already better than an unmarked
  list. It still searches the current document, not arbitrary iframe/shadow
  trees or records absent from the DOM. `text` correctly marks its character
  truncation. Extend coverage explicitly rather than treating these existing
  bounds as proof of complete application state.
- **File predicates can already be true before input.** `file_condition`
  checks current content, not that this action produced it. State predicates
  are useful, but a transition assertion needs an explicit before state.
- **An atlas's historical `verified` flag is not present compatibility.**
  `atlas.apply` checks expected key values, which is useful protection. It does
  not establish that the running version interprets them identically or has
  loaded the change. Multiple writes can also fail partway through; preflight
  validation is not a transaction. Version metadata, partial-write reporting
  and readback are improvements, not a reason to expand the atlas immediately.

## 4. General capabilities worth expanding

### A. Evidence-aware observations and checked actions — first expansion

Introduce a small common evidence envelope: session and target identity,
observation time, scope, completeness status/reasons and evidence references.
Expose delivery, predicate results and observation failures independently.
Avoid one overloaded `success` boolean.

A useful predicate result has three values: `satisfied`, `violated`, `unknown`.
For a universal assertion over domain D, observing P(x) for every x in a subset
O establishes the full claim only when coverage establishes O = D. Conversely,
one reliable counterexample can refute it even with incomplete coverage.
Existence needs a witness, while absence needs coverage. This distinction can
guide APIs without pretending arbitrary GUI state is formally verified.

Prototype a small predicate set: exact file/config state, element value/state,
stable target identity, and collection coverage where an adapter can supply
it. Each result names the predicate and its scope. Independent reading is
stronger when it avoids the executor's failure mode; a second model consuming
the same incomplete observation is not an independent oracle.

Gate: seeded truncation, unavailable data and delayed persistence produce
`unknown` or a precise failure, never an unsupported successful verification.
Also measure false refusals on complete, valid cases and added latency.

### B. Resumable operations with explicit uncertainty — second expansion

Give long operations IDs and states such as queued, running, completed,
failed, cancellation-requested and delivery-unknown. Preserve a per-step
record and support status lookup after a caller disconnects. Reconcile known
effects before deciding whether to retry.

The synchronous worker currently serves one request at a time, and browser
batches call `browser_request` directly for their inner steps. Long requests
therefore deserve a separate cancellation/control responsiveness investigation.
Do not solve this by allowing concurrent input indiscriminately: keep ordered
mutation and explicit control gates. Start with private sessions and a
stand-in host in tests.

Gate: interrupt at each operation boundary, reconnect, and correctly identify
completed, not-started and uncertain work; no duplicate non-idempotent actions.
Measure time to acknowledge human control and cancellation under long waits.
These capabilities support general use even when they do not reduce task time.

### C. Reusable procedures with declared assumptions — after A and B

Retain code reuse, but give each procedure a manifest: parameters, supported
app/version, starting-state assumptions, required observation coverage,
postconditions, side-effect scope and recovery policy. Store observed validation
runs separately from those declarations. Run stored code by reference instead
of asking the model to reproduce it each time.

Validate across changed data, window sizes, locales, pagination, asynchronous
updates and fresh sessions. Shrink a failing case to the smallest fixture that
reproduces it. Existing seeded fixtures and independent checks are a base.
This supports both reusable work and useful bug reports; it does not require
repositioning the project as a testing-only product.

Gate: independently verified repeat completion, false-success rate and total
wall time improve on held-out variations. Count repair and failed attempts.
Stop if procedure maintenance costs more than fresh execution. The negative E6
result remains evidence against assuming that generated scripts automatically
generalise or save wall time.

### D. Focused observation adapters — expand when they improve evidence

Browser, accessibility, application APIs and document parsers should declare
what they can observe: visible content, persisted artifact, loaded document,
remote acknowledgement, or complete enumeration. Choose the cheapest source
that supports the requested claim, with visual fallback when necessary.

First improve existing adapters: stable browser contexts, scoped completeness,
document extraction status, actionability/readback and explicit frame support.
Only then evaluate another toolkit or application API. A universal adapter
architecture without demonstrated consumers would add maintenance burden.

Gate: better verified outcomes or lower all-attempt cost on representative
cross-application tasks, with coverage gaps still reported. Structured access
must not conceal visual or persistence errors.

### E. An evidence review interface — useful visual work

If improving appearance, build a view that explains an actual run: requested
action, delivered steps, observed changes, checked predicates, unknowns and
recovery choices. Link concise summaries to detailed artifacts. Make incomplete
and stale evidence visible instead of showing a generic green check mark.

Do not imply that a preview is transactional or that local rollback reverses
remote side effects. Replay must be an explicit action with assumptions.
Measure whether people can locate a planted failure and decide the next step
faster than from raw traces. Start with a static report before a new dashboard.

## 5. Evaluation and bounded stages

Measure both successful work and trustworthy stopping. Reporting `unknown` for
everything must not count as an improvement.

Record false-success count/rate, independently verified completion, coverage of
verification, unnecessary refusals, wrong-target actions, repeated effects,
cleanup failures, recovery time and all-attempt latency/cost. Define false
success as a declared task/verification success contradicted by the independent
oracle, not merely a tool's accurately reported input delivery.

Use controlled failure injection before model trials: incomplete trees,
virtualized content, vanished targets, overlays, delayed saves, stale files,
lost acknowledgements, child processes, watcher failures and evidence expiry.
Verify the checkers with deliberately wrong outputs and cases they cannot
observe. Publish denominators and uncertainty; zero failures in a finite test
set is not zero failure probability. Pair/randomize later comparisons and keep
held-out variants to discourage fixture-specific fixes.

| Stage | Scope | Acceptance evidence |
| --- | --- | --- |
| R1 | F1 completeness propagation and F2 target identity | Deterministic counterexamples refuse; valid scoped actions still work; private-browser disappearance test |
| R2 | F3/F4 deadline and partial-result contracts | Delayed/lost replies preserve known delivery; capture failure cannot erase it; no blind retry |
| R3 | F5 script job supervision | Ordinary children reaped; in-flight worker actions reconciled; intended session apps survive |
| R4 | F6/F7 ledger coverage and retention | Repeated reads preserve baselines; expired/missing coverage explicit; bounded-session stress evidence |
| R5 | Small evidence/predicate API and adversarial fixtures | Useful verified outcomes plus correct unknowns; false-refusal and overhead measurements |
| R6 | One bounded reuse or review-interface experiment | Held-out benefit over the repaired baseline; independent checks retained |

Each stage should be its own reviewable implementation PR with exact validation
and remaining limitations. R1 can start now. R2–R4 need not wait for a universal
schema; R5 should learn from their concrete contracts. R6 depends on that
foundation. These are proposed priorities, not authorisation to execute all
stages or reopen stopped model experiments.

Defer a skill marketplace, broad model training, a universal app protocol,
platform ports solely for reach, and further screenshot compression without a
new measured bottleneck. The current evidence supports improving correctness
and information quality before adding those surfaces.

## 6. External references and their limits

- [Playwright actionability](https://playwright.dev/docs/actionability): checks
  uniqueness, visibility, stability, event reception and enabled state before
  relevant actions; assertions are separate. This is a useful engineering
  reference, not evidence that delivery proves task completion.
- [Playwright locators](https://playwright.dev/docs/locators): reference for
  scoped target resolution and strictness. Its browser mechanisms do not
  transfer automatically to every desktop toolkit.
- [AWS: making retries safe with idempotent APIs](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/):
  reference for operation identity and retry semantics. Arbitrary GUI clicks
  lack server-enforced idempotency, so the proposed runtime must preserve
  uncertainty and reconcile rather than promise exactly-once effects.
- [OSWorld](https://github.com/xlang-ai/OSWorld): existing execution-based
  evaluation and the Verified revision reinforce that outcome checking is
  established practice. No novelty claim is made for assertions, replay,
  counterexamples or general agent evaluation.

The plausible contribution is a consistent implementation of scoped evidence,
uncertain delivery and recoverable actions across this project's desktop,
browser and script surfaces. Whether that improves real use remains an
experimental question; the concrete defects above are a justified place to
start.
