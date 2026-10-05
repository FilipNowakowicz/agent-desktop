# Recommended plan: finish the daily-use alpha

Reviewed at `8632cdedd2d20701230ae7d0b3afc8afbbce4adf`, 2026-10-05. Recommend **O1**, with narrowly scoped safety and evidence work from O3/O2. These are proposed milestones, not authorization to edit, run paid experiments or change the host. Estimates in options.json are planning estimates.

## 1. Establish a truthful contract

**Goal:** users can tell what is implemented, what is tested and what is promised.

**Scope:** resolve F002, F008, F015, F018, F026 and F038 in current-facing documentation. Define cooperative same-user operation; distinguish a session's graphical privacy from credential containment. Document image coordinates with an observation token and desktop coordinates without one. Publish an environment/capability/skip matrix and exact runtime selection.

**Non-goals:** new UI tools, broader accessibility, a security-sandbox claim, benchmark reruns.

**Exit criteria:**

- Current README, CLI help and MCP descriptions agree on coordinates, ownership, retained data and supported runtime versions.
- Every compatibility claim names a test/artifact and whether it is a desktop install or CI container.
- Cost claims describe observed samples without inferring causality.
- Unexplained Chromium/input/Calc symptoms and the MCP fixture race have explicit dispositions. This review opens nothing.

## 2. Repair correctness and operational control

**Goal:** the existing API fails predictably and allows safe interruption.

**Scope:** hold profile lifecycle locks through create/delete/recovery (F003/F025); fix combined/scoped waits and unknown observations (F005/F036); reject unstable captures (F009); version semantic IDs (F016); preserve partial sequence results and define a client mutation lease (F011). Bound AT-SPI work and encoded response size (F004/F017); prevent synchronous MCP waits from blocking unrelated requests (F010). Surface clipboard-clear failures (F024). Fix the atomic fixture publication race (F012).

**Non-goals:** universal UI readiness, automatic retries of non-idempotent actions, general replay, multiple compositor backends.

**Exit criteria:**

- Deterministic tests reproduce each identified failure on the old implementation and verify the intended new contract.
- Simultaneous profile create/delete cannot remove an active or recovering profile.
- A stalled accessibility provider cannot prevent control/status/cancellation acknowledgement within a proposed one-second target.
- A two-client test proves action ownership and cancellation; partial/uncertain execution is reported without inviting blind retries.
- At least 100 loaded repetitions of each recent input/focus regression per relevant environment show exact receipt; any failure remains visible with diagnostics. Zero failures is bounded evidence, not proof of zero failure probability.
- Latest required CI has no unexplained failures or unexpected skips.

## 3. Deliver two reproducible installation paths

**Goal:** a user reaches a working private desktop without reconstructing development experiments.

**Scope:** package the Python entry points and actual runtime separately; publish a pinned NixOS runtime expression/package and one conventional distro recipe. Include optional accessibility and viewer dependencies. Detect the actual compositor, wlroots ABI, capture/input protocols and selected repair through a doctor/preflight command. Track the patch's source, reproducer, supported versions and retirement condition (F007/F019).

**Non-goals:** host activation, a Nix requirement for all users, Windows/macOS installers, distro-wide support claims, silently substituting system libraries.

**Exit criteria:**

- A clean NixOS project-local setup and a fresh ordinary non-Nix desktop installation both complete documented create/launch/observe/input/destroy commands.
- Python uses uv-managed dependencies; runtime provenance and resolved patched library are recorded.
- A reviewer can repeat the NixOS repaired-runtime build from checked-in instructions without searching artifacts or personal configuration.
- Updating an unsupported runtime fails preflight with an actionable message.
- Headless input receipt, profile handling and cleanup pass; graphical viewer behavior is checked separately and only with specific host-window authorization.

## 4. Bound long-running state and diagnose residual failures

**Goal:** a desktop remains usable over a working day.

**Scope:** safe retention/pruning, session/profile accounting and low-disk behavior (F013); bounded action traces for requests, focus and outcome references (F035); crash recovery boundaries and resource measurements. Trace collection must omit/redact sensitive handoff data.

**Non-goals:** unrestricted telemetry, network interception, full recording, deterministic replay or snapshots.

**Exit criteria:**

- An eight-hour workload has measured p50/p95 control latency, CPU/RSS, screenshot/log bytes and process counts.
- Configured storage bounds hold and pruning never deletes a live session or named profile without explicit selection.
- Worker, compositor, viewer and client failures produce understandable status and no unexplained leftovers within the declared failure model.
- A known induced wrong-target/readiness failure can be reconstructed from the trace without exposing typed secrets.

## 5. Prove actual personal usefulness

**Goal:** satisfy M3 with normal work, not just a larger fixture suite.

**Scope:** the user chooses two or three recurring workflows, including a real application configuration task and, if needed, a deliberately authorized login/handoff. Use normal shell/API access where appropriate. Collect a diary of at least 20 sessions over at least 10 working days with task outcome, intervention, elapsed time, recovery and cleanup (F001/F020/F023).

**Non-goals:** broad autonomy claims, a public launch, sensitive accounts chosen by the implementer, paid model runs without a separately agreed budget.

**Exit criteria:**

- At least 18/20 tasks finish without developer changes or unplanned rescue; ordinary approved human login is logged separately.
- No unexplained wrong-target or host-input action occurs; every failure has a disposition.
- The user's actual keyboard, selected login flow and profile reuse work if included in scope.
- The user chooses to reuse the tool for a subsequent task. If not, investigate O5 before adding features.

## 6. Choose the next investment from failures

**Goal:** decide among O2–O5 using the pilot's evidence.

**Scope:** rank recurring blockers and evaluate one relevant comparator. For tool-efficiency claims, pin code/model/prompts/schemas/apps/resources, pair task seeds, randomize order and preserve all aborted/failed attempts plus raw cache counters. Start with a small paired pilot; size further runs from observed variance and the minimum useful improvement.

**Non-goals:** another saturated suite merely to obtain perfect scores, general superiority claims, automatic expansion to portable VMs.

**Exit criteria:**

- A short decision identifies the dominant bottleneck, the option that addresses it and the evidence against competing options.
- If benchmarks are authorized, report completion, harmful/wrong actions, interventions, primitive actions, calls, latency and actual usage with uncertainty.
- An extension ships only when it improves the chosen real workflow or closes a specified safety/reliability gap.

## Proposed current status for START_HERE.md

START_HERE.md currently has a priority block, not a Development status table; the existing table is in PROJECT_PLAN.md. Add the following concise table to START_HERE and use the same states in PROJECT_PLAN, replacing their inconsistent completion narrative.

| Stage | Proposed state | Release gate still open |
| --- | --- | --- |
| M0: private desktop loop | Demonstrated on initial NixOS machine | Preserve regression coverage; do not repeat reconnaissance |
| M1: runtime | Implemented and repeatedly tested; hardening remains | Profile races, bounded control/observations, unresolved input symptoms, retention |
| M2: integration/viewer/handoff | MCP and viewer tested; cooperative takeover/profiles implemented | Real user login/resume, privacy wording, MCP responsiveness, keyboard layout |
| M3: daily use and portability | Partial: application fixtures and three CI distributions | Reproducible supported-runtime installs, ordinary non-Nix desktop, sustained real work |
| M4: measurement | Exploratory suites and restricted comparisons | Representative workflows, matched paired trials, provenance and uncertainty |
| Extensions A/B | Waits, sequences, crops, semantic UI, takeover and profiles implemented | Validate utility and failure behavior before expanding |
| Portable machine / strong isolation | Deferred options | Explicit product/threat-model decision and targeted feasibility evidence |

## Proposed replacement “Next priorities”

1. Fix the current contract and correctness gaps from this review: profile lifecycle, waits, observation stability, semantic IDs, bounded responsiveness, partial action results and clipboard failure handling.
2. Package one supported runtime for NixOS and one non-Nix desktop, including explicit selection of the X11 repair where required.
3. Add bounded retention and focused diagnostics; complete the working-day soak.
4. Use the tool on the user's selected recurring work and validate a specifically authorized real handoff if needed.
5. Let those failures decide whether deeper semantic tools, stronger containment, reuse of another runtime or a portable machine is worth pursuing.

Retain the original immediate success criterion and explicit host-change boundaries. Do not reopen M0, imply complete M3, or prioritize action timelines/LibreOffice/Electron expansion independently of an observed pilot need.
