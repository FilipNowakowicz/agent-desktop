# Capability matrix (F0, 2026-11-11)

Stage F0 of the [functionality roadmap](FUNCTIONALITY_ROADMAP.md): what each
contract covers today, judged from source and tests on `main` at `6872f38`. This
records the state on that date, not a guarantee. The development log has the
validation behind each feature.

**Status values:**

- **tested:** implemented and covered by a regression test.
- **untested:** implemented, but no test exercises the case.
- **missing:** not implemented.
- **unsupported:** deliberately out of scope, with the reason given.

## Pinned environment

| Component | Version |
| --- | --- |
| Host | NixOS 26.11, kernel 6.18.60 |
| Runtime | Repaired Nix runtime (`runtime/nix`, nixpkgs `4975466`): labwc 0.20.2, wlroots 0.20.2 with the X11 mapping repair, Xwayland 24.1.13 |
| Applications | Firefox 159.0.1, foot 1.28.0, wayvnc 0.10.1 |
| Python | uv-managed CPython 3.12.13, `uv.lock` at `6872f38` |
| Fixtures | Local HTML pages and terminal fixtures under `tests/`, `scripts/pointer_fixture.py`, and the web tasks in `benchmarks/hard` (`tests/test_web_fixtures.py`) |
| Suite | 329 tests, 19 skipped for missing optional applications (2026-11-11, with N1 applied) |

## Contracts

### Correct targets and outcomes

| Case | Status | Evidence |
| --- | --- | --- |
| Input goes only to the named session; unknown and invalid sessions fail closed | tested | `test_runtime` (unknown or invalid sessions, two sessions with distinct input) |
| Stale observation tokens refuse input | tested | `test_capture`, `test_correctness`, `test_actions` |
| Ambiguous, missing or disabled browser targets refuse without acting | tested | `test_browser`, `test_completion_targets` |
| Partial accessibility reads never establish absence or uniqueness (R1) | tested | `test_completion_targets`, `test_tree_bounds` |
| Browser target loss requires explicit reselection (R1) | tested | `test_browser`, `test_completion_targets` |
| Delivered clicks that change nothing on a toggle are visible | missing | N3 in the execution plan |
| Tab identity distinguishes document versions | unsupported | Context IDs track tabs, not documents (R1 limit) |

### Durable execution

| Case | Status | Evidence |
| --- | --- | --- |
| Lost replies and interrupted sends are uncertain and never retried (R2) | tested | `test_delivery`, `test_dispatch_evidence` |
| Durable jobs keep per-step delivery evidence, cancellation and reconnectable status (R5b) | tested | `test_operations` |
| A runner crash before or after dispatch is told apart | tested | `test_operations` (crash phases, from saved records) |
| A killed runner releases its controller lease | tested | Fixed 2026-11-11: `test_operations` (dead helper gives back its lease), reproduced below |
| Interruption during application work, after a committed effect, or before evidence collection; cancellation during application work | tested | `test_interruptions` (2026-11-11). The helper is killed or cancelled at each boundary in a real session |
| Interruption during evidence collection itself | untested | Too short a window to hit without a fault-injection hook. The record validator refuses `satisfied` without all checks |
| Takeover while a job runs, and control acknowledgement time | untested | Takeover is tested on its own (`test_takeover`), not during a job |
| Automatic retry, resume or rollback | unsupported | Never implemented; reconcile first instead (R2, R5b) |

### Broad application control

| Case | Status | Evidence |
| --- | --- | --- |
| Native Wayland and Xwayland applications: input, drag, scroll, screenshots | tested | `test_runtime` |
| Browser through the DOM: forms, batches, rows, waits | tested | `test_browser`, `test_ui` (web form) |
| Accessibility actions in GTK and Qt dialogs | tested | `test_ui` |
| Scripts in the session, bounded and supervised (R3) | tested | `test_run`, `test_script_jobs` |
| File dialogs, clipboard between applications, poor-accessibility interfaces in complete workflows | untested | Covered piecemeal; the F2 workflows will cover them end to end |
| Native Windows or macOS applications | unsupported | Linux first (PRODUCT_DIRECTION.md) |

### Persistent state

| Case | Status | Evidence |
| --- | --- | --- |
| Profiles keep a home across sessions; one session at a time | tested | `test_profiles` |
| Browser logins survive sessions, including imported cookies | tested | `test_profiles` |
| A profile whose supervisors died is recovered by the next session | tested | `test_profiles` |
| Workspace, session and profile lifetimes written down as one specification | missing | The F3 first item |
| Application restart or runtime upgrade with declared state preserved | untested | F3 |
| Whole-system snapshots or reversing external effects | unsupported | Out of scope (roadmap F3 exit) |

### Reliable observations

| Case | Status | Evidence |
| --- | --- | --- |
| Screenshots carry layout tokens, regions and scales | tested | `test_capture` |
| Settled-screen waits and frame changes | tested | `test_wait` |
| Effect reports with coverage and unknown baselines (R4) | tested | `test_effects` |
| Scoped predicates give satisfied, violated or unknown (R5a) | tested | `test_checks` |
| Offline evidence review keeps unknowns visible (R6) | tested | `test_review` |
| Observations under virtualised lists, delayed saves and layout changes, as F2 varies them | untested | F2 |
| Effect reports as proof of causation | unsupported | Temporal evidence only (R4 limit) |

### Ownership and cleanup

| Case | Status | Evidence |
| --- | --- | --- |
| Process ownership by token and start time; reaping; guardian cleanup | tested | `test_process_identity`, `test_runtime`, `test_profiles` |
| Script groups stopped and reaped on timeout and cancel (R3) | tested | `test_script_jobs` |
| Bounded retention of sessions, screenshots and traces | tested | `test_retention`, `test_trace` |
| Controller lease: exclusivity, expiry, sequences not interleaved | tested | `test_lease` |
| Repeated create/use/destroy under load | tested | `scripts/lifecycle_stress.py`, `scripts/soak.py` (manual runs in the log) |
| Detached descendants that clear their environment | unsupported | Accepted limit (review decisions, 2026-10-08); needs cgroups or a container |
| A crashed job's lease | tested | Fixed with the durable-execution case above |

## First F1 failure

**A killed durable job keeps its controller lease for up to an hour.**
`operations.run_job` takes a 3600-second lease so that long waits keep it exclusive
(`operations.py`, the `seconds=3600` request). The runner releases the lease, or
restores the client's own lease, only when it finishes. If the runner is killed,
`status` correctly reports `delivery_unknown`, but the lease stays with
`op-<id>`. Every other controller is then refused (`LeaseHeld … 3597 s left`) for
the rest of the hour.

Smallest reproducer, run 2026-11-11 against `6872f38` plus N1 on the managed runtime:

```python
session = core.create()["session"]
record = operations.start(session, [{"action": "wait", "seconds": 30}], timeout=120)
time.sleep(2)                         # state: running
os.kill(record["pid"], signal.SIGKILL)
operations.status(session, record["operation_id"])["state"]   # delivery_unknown
core.request(session, "key", "other-client", key="Return")    # LeaseHeld, 3597 s left
```

Expected behaviour: once `status` finds the runner gone, a temporary lease that the
job took for itself (`release_lease: true`) is released, and a client's lease that
the job extended goes back to its normal length. Nothing is replayed, and the step
stays `uncertain`. The independent check is that another controller's request is
accepted right after `status` reports the dead runner, while a live runner still
holds the lease. This is the first X1 (F1) patch, done on 2026-11-11.

## Order for F1

1. Release or restore the lease when a job's runner dies (done 2026-11-11).
2. (Done 2026-11-11, apart from during evidence collection) Interrupt at each F1 boundary: before dispatch, after dispatch and before the
   acknowledgement, during application work, after a committed effect, and during
   evidence collection. Use the existing operation fixtures and a real session.
3. Run takeover while a job is running, and measure how long control takes to be
   acknowledged.
4. Rerun the wrong-target and partial-coverage cases alongside interruptions.
