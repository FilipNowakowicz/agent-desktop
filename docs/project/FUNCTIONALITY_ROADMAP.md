# Functionality roadmap

Recorded 2026-10-23. Implements the direction in
[PRODUCT_DIRECTION.md](PRODUCT_DIRECTION.md). These are proposed acceptance
criteria and bounded stages; unchecked items are not completed features.

## Starting point

Remote main was checked at `4277ed1` when this plan was recorded. It already
contains R1–R6: coverage-aware targeting, browser target-loss handling, delivery
evidence, script supervision, effect coverage/retention, scoped predicates,
durable private operations and an offline evidence report. See
[PROJECT_PLAN.md](PROJECT_PLAN.md) and [DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md)
for recorded validation. Do not rebuild these features from the older research
checkout or confuse their implementation with universal reliability.

Important existing limits include visible/scoped evidence, no automatic operation
retry/resume/rollback, application work that may finish after cancellation,
detached script descendants outside ordinary-group cleanup, and unmeasured human
benefit from offline review. Audit the current revision before changing any limit.

## Definition of functional quality

The runtime must provide broad control within an explicitly chosen environment,
report what happened accurately, preserve useful state, and behave predictably
when interrupted. "Perfect" means meeting declared contracts on a documented
compatibility surface, not supporting every application without qualification.

| Priority | Contract | Adversarial acceptance evidence |
| --- | --- | --- |
| Correct targets and outcomes | Input reaches the intended session/application/object; incomplete evidence remains unknown | Duplicate labels, missing tabs, focus changes, navigation and truncated trees do not silently select a wrong target or establish universal completion |
| Durable execution | Operations have stable identities/status and per-step effects; cancellation is honest | Disconnect/reconnect and interruption at each meaningful boundary do not cause duplicate non-idempotent actions |
| Broad application control | Browser structure, accessibility, pixels, input and scripts can be combined | Native apps, browsers, file dialogs, clipboard and poor-accessibility interfaces complete representative workflows |
| Persistent state | Selected documents, downloads, profiles and workspace state remain usable | Application/runtime restart preserves declared state; loss or unsupported restoration is explicit |
| Reliable observations | Target, time, freshness, scope and coverage accompany evidence | Virtualization, delayed saves, layout changes and stale observations yield scoped facts or uncertainty |
| Ownership and cleanup | Processes, sockets, inputs and artifacts have defined owners/lifetimes | Repeated lifecycle, crash and takeover trials preserve unrelated resources and report cleanup limits |

These priorities overlap. Reliable observations support targeting from the first
stage; cleanup is required for every experiment, not postponed to the last stage.

## F0: baseline and gap inventory

- [ ] Pin runtime, application, platform and test fixture versions.
- [ ] Inventory each contract as implemented/tested, implemented/untested,
  missing or deliberately unsupported; link source and existing regression tests.
- [ ] Reproduce relevant historical failures against current code. Record fixed
  cases as regressions rather than adding duplicate implementations.
- [ ] Identify the first remaining concrete failure and its smallest reproducer.

Deliverable: a short capability matrix and prioritized failures. Exit when the
next patch has an observable expected behavior and an independent check. This
stage is not another general literature review.

## F1: correctness under interruption — first implementation milestone

- [ ] Exercise queued, running, completed, failed, cancellation-requested and
  uncertain outcomes according to actual API semantics; do not invent states
  that the runtime does not expose.
- [ ] Interrupt before dispatch, after dispatch/before acknowledgement, during
  application work, after a committed effect and during evidence collection.
- [ ] Reconnect using operation identity; recover recorded delivery/check
  information without implicitly replaying actions.
- [ ] Reconcile uncertain effects using app/file evidence before any explicit
  retry. Define idempotence per operation rather than assuming it globally.
- [ ] Exercise takeover, stale observations and controller ownership while a
  command is running; measure control acknowledgement time.
- [ ] Regress wrong-target and partial-coverage cases alongside interruptions.

Exit: every tested boundary has the correct observed or unknown state; no silent
retargeting or duplicate effects; takeover behavior and residual in-flight work
are explicit. Do not claim immediate cancellation of already-issued app work or
automatic recovery beyond the implemented contract.

## F2: three end-to-end acceptance workflows

| Workflow | Required behavior | Independent check |
| --- | --- | --- |
| Browser dataset edit | Traverse paginated/virtualized records, target the intended IDs, survive a modal or interruption | Compare final authoritative records with initial snapshot by ID; all targets correct, non-target fields/membership preserved |
| Native document edit | Open, edit, save, close and reopen through a supported application | Parse saved artifact or independently reopen/read it; validate content and destination, not only a save toast |
| Mixed workflow | Download a file, process through an app or script, upload the resulting artifact | Verify output contents and actual destination state; detect duplicate or incomplete submission |

Use local disposable services and application profiles. These workflows represent
interaction classes, not a customer-specific product pivot. Choose concrete apps
from the compatibility matrix and record unsupported cases.

For each workflow vary starting page/filter, focus, viewport, duplicate labels,
file contents, modal state and timing as applicable. Add crash, disconnect,
timeout and incomplete-observation injections. Hold out some combinations to
avoid tuning only to the original fixture. Restore and verify initial state for
every trial. Broad claims need more apps/platforms than these three workflows.

Run deterministic drivers first to isolate runtime failures. Agent-driven runs
then test whether the exposed capabilities are sufficient for actual work, with
an agreed model budget. A model mistake is not automatically a runtime defect.
Classify failures as runtime defect, missing capability, agent mistake,
unavailable evidence, application/environment failure or evaluator failure.

The evaluator must not use the same partial view as the procedure. Check all
relevant fields and side effects; validate the checker with intentionally wrong
outcomes. Keep expected answers out of page source and model context. Private
sessions alone cannot protect judge files from same-user arbitrary scripts.

## F3: persistence and lifecycle stress

- [ ] Specify workspace versus session versus profile lifetimes. Document which
  state persists and which processes must be recreated.
- [ ] Test application restart, runtime restart, supervisor loss, viewer closure
  and repeated create/use/destroy cycles independently.
- [ ] Check files, profiles, downloads and operation records after each event.
- [ ] Check owned processes/sockets/input leases and retained artifacts against
  declared retention rules; do not kill unrelated applications.
- [ ] Test supported distributions and applications using the repository's
  validation policy; quantify duration/repetition counts and remaining gaps.

Exit: persistence and cleanup meet the declared lifetimes on the tested surface.
Session recovery is not a whole-system snapshot or reversal of external effects.

## Evidence and development discipline

Record source revision, environment, seeds, commands, actual input receipt,
artifacts, independent outcomes, cleanup and failures. Keep request acceptance,
delivery, script exit, scoped predicate results and task verification separate.
Measure wrong targets, false completion, unknowns, recovery, duplicate effects,
latency and resource leakage; successful process exits are insufficient.

Each bounded stage uses a branch/PR, source-appropriate local tests and a log
entry. Run desktop tests locally; use the full CI matrix only for runtime,
packaging/CI changes or milestones under [VALIDATION.md](../VALIDATION.md).
Do not expand testing after checks pass without a new failure or concern.

Backend requirements for the future UI are stable IDs, reconnectable status,
input ownership, meaningful structured events, artifact references and access
boundaries. Define them while building functionality; defer frontend polish.

## Optional research after the foundation

The [procedure-validity assessment](../research/2026-10-22-procedure-validity.md)
preserves the literature comparison and small falsification experiment. Begin
with a hand-written baseline; compare symbolic inference and model-proposed
conditions only if useful failures remain. Keep independent outcome checks,
held-out variations, useful reuse and acquisition costs. Stop if simpler checks
match the learner. This is not a prerequisite for any F0–F3 acceptance criterion.
