# Effect-first computer use: direction and test plan

Date: 2026-10-11. This plan was agreed in discussion with the maintainer. It
follows [beyond human speed](2026-10-09-beyond-human-speed.md) (stages S0–S5)
and the results of S1a–S4. Measurements are marked as measured; everything else
is a proposal or an estimate. The next working session should start at §6 and
run the experiments in order.

## 1. Where we are

Measured on 153 benchmark runs (Opus 5.5 through `claude -p`, 2026-10-08/09,
`artifacts/benchmark/`):

| Task type | Wall time | Model turns |
| --- | --- | --- |
| Short (form, slider, save a file) | 10–20 s | 3–10 |
| Harder (edit a row in a 40-row web admin table) | 22–30 s (one run 59 s) | 9–26 |
| Settings (Mousepad, Geany) | 11–30 s | 3–16 |
| Host trial, open-ended browser task | 85 s, 11 min, 11 min | 23–95 calls |

The median benchmark run takes 21 s, at about 3 s per turn. In 21 single-task
runs, the split of wall time was:

- **~78%: model API time** (`duration_api_ms`), meaning reading the context and
  screenshots and writing the next action.
- ~12%: time inside the tool, mostly the settle wait before a screenshot. Pixel
  runs spent about 6 s per task on it; browser-bridge runs about 0.5 s.
- ~10%: other overhead (CLI start-up, MCP initialisation, gaps between calls).

What the stages achieved:

- **S1a** (act and observe): turns −31%, wall time −14%.
- **S2** (guarded steps): turns −8%, not significant; the agent rarely used
  expectations.
- **S3** (browser bridge): wall time −33%, input tokens −30%.

**What has not changed:** the cost of a turn (2–3 s, with 60–200k input tokens
per task) and how the agent works, which is still one action per look. The
benchmark tasks were never slow. The slow case is open-ended work like the host
trial, and that has not been measured again.

Side finding: in run `20261009-222637-3010`, a batched `select` hit the
`set_text` keyboard fallback and failed with `KeyError: 'text'`. It is filed as
issue #107.

## 2. Constraints

- **No API credits, by the maintainer's decision.** All agent runs use the
  subscription through `claude -p`. We control the tools, not the agent loop,
  so we cannot decide which earlier screenshots stay in context, use API
  context editing, or execute steps while a reply is still streaming. These
  ideas stay in §7 until a funded loop exists.
- Within `claude -p`, `--model` selects Opus, Sonnet or Haiku from the same
  allowance. Before E1, check whether effort and fast mode can be set from the
  CLI.
- The local GPU is a GTX 1650 Ti with 4 GB, which cannot fine-tune a vision
  model. Free hosted GPUs (Kaggle T4s, about 30 h/week; Colab) can LoRA-tune a
  2–3B vision model for a narrow task.
- Cloud session credits run Claude Code agents in hosted containers, not on
  GPUs. They might allow parallel benchmark runs if our headless runtime works
  there (unverified, E5).

## 3. Thesis: know what happened instead of looking

Current agents, including the labs' agents and the research systems in §4,
judge progress by **looking**: a screenshot, or an LLM judging one. That is why
they are slow (in the host trial, 53 of 59 screenshots came directly after an
input) and unreliable (what they see is only evidence of what happened). Every
look costs a model turn, and a model turn is about 78% of the time.

A private session can observe **effects** directly: files and configuration
keys written (effect ledger), accessibility state, the DOM and network requests
(browser bridge, WebDriver BiDi network events), D-Bus calls, and windows and
processes. The effect atlas already mapped 105 GUI controls to the
configuration keys they change, without a model.

**Thesis:** a desktop that reports exactly what each action changed lets the
agent skip most looks. Three consequences follow, and the prior-art search in §4
did not find a system that combines them:

1. **Checks by effect, without a model call.** For example: "key X = true",
   "POST /webhooks returned 201", "file contains Y". These are exact and take
   milliseconds, so long runs of steps become safe without a screenshot between
   them. This answers why guarded steps failed: UI expectations were optional
   and not trustworthy enough to rely on. Effect expectations are exact.
2. **App skills tested against real effects.** This is like SkillWeaver's web
   APIs, but each skill is tested by an observed effect instead of an LLM judge,
   and it extends to desktop applications. The atlas is the first instance (for
   settings), and `desktop_set` applies it.
3. **A data engine.** Every run pairs screens and actions with exact, labelled
   effects. This is training data that labs do not have for private Linux
   desktops, and it is the only thing that would justify a small local
   specialist model (§7).

Rollback and commit points become exact as a result: undo the observed effects,
and treat unobservable ones (network writes to third parties) as commit points.

**Limits:**

- Some effects cannot be observed: canvas drawing, purely visual state, and
  servers seen only through the DOM or network. The agent still has to look for
  these.
- Host sessions have far fewer effect hooks than private ones.
- The thesis cuts the number of turns, not the cost of a turn. The literature
  agrees that the number of turns is the lever (§4).
- The novelty claim rests on one hour of searching. Do a proper literature
  check before making it in public.

## 4. Prior art and the labs (searched 2026-10-11)

| Work | What it shows | Relation to us |
| --- | --- | --- |
| [OSWorld-Human](https://arxiv.org/abs/2506.16042) (MLSys 2026) | The best of 16 agents takes 2.7–4.3× more steps than a human path; planning and reflection calls dominate latency; later steps are up to 3× slower | Same finding as ours: the number of turns is the lever |
| [OSWorld 2.0](https://arxiv.org/abs/2606.29537) | 108 long tasks, a median of about 1.6 h for humans and about 318 tool calls | Long tasks are where speed matters; our suite should move toward them |
| [Efficient GUI agents survey](https://arxiv.org/abs/2609.02309) | Read selectively, keep recoverable memory instead of raw history, use hybrid GUI and non-GUI runtimes | Matches our direction |
| [GUIPruner](https://arxiv.org/abs/2602.23235), [history pruning](https://arxiv.org/html/2603.26041v1), [GUI-KV](https://arxiv.org/html/2510.00536) | Older screenshots can be shrunk or dropped while keeping most of the success rate (for example >94% at 3.4× fewer FLOPs) | Needs control of the agent loop (§7); on the tool side, send fewer and smaller images (E3) |
| [AOI](https://arxiv.org/abs/2606.29472) | A perception layer that runs between steps narrates changes as text: +17 to +48 points on dynamic tasks, no retraining | Supports text deltas and change narration (E3) |
| [Speculative interaction agents](https://arxiv.org/abs/2605.13360) | Asynchronous I/O and speculative tool calls: 1.6–2.2× faster (voice and tool agents, not GUI) | A continuous-loop idea for §7 |
| [TClone](https://arxiv.org/pdf/2605.17320), [Crab](https://arxiv.org/html/2604.28138v1) | Fork, rollback and commit of live GUI or agent sandboxes; speculative actions in forks | Rollback alone is not new; we add exact effects |
| [SkillWeaver](https://arxiv.org/abs/2504.07079) | Agents synthesise website skills as APIs, tested by an LLM judge | Pillar 2, but with tests by effect and for desktop applications |
| [Fara-7B](https://www.microsoft.com/en-us/research/blog/fara-7b-an-efficient-agentic-model-for-computer-use/), [OpenCUA](https://huggingface.co/xlangai/OpenCUA-32B), UI-TARS | Small open computer-use models (about 7B) | Candidates for a two-speed loop; we do not train general models |

**Labs.** No 2026 lab announcement about the latency of computer-use models was
found. The leaderboard numbers found conflict and come mostly from vendor
blogs, so they are not recorded here. The labs improve the model, while this
project improves the environment and verification, which looks less explored.

## 5. Measurement rules

These carry over from [beyond human speed §5](2026-10-09-beyond-human-speed.md):

- Use matched arms with several runs per arm.
- Report wall time (p50 and p95, keeping failed attempts), model turns, input
  tokens, looks (screenshots), success and wrong actions.
- Report first-use runs and repeat runs separately.
- Dry-run before spending allowance.
- "Human speed" claims wait for a matched human baseline.

New measures:

- **The time split per run** (model API, tool, other), as computed in §1 from
  `duration_api_ms` in the transcript and `ms` in `trace.jsonl`. Add it to the
  benchmark summary.
- **Looks per completed task.**

## 6. Experiments (next session starts here)

Each experiment is a PR. Fix #107 first or alongside them.

| # | Build | Measure | Continue if |
| --- | --- | --- | --- |
| **E0 Realistic suite** | 5–8 unfamiliar tasks that take a person 2–5 minutes across several applications (local web app + editor + files; settings plus verification; a long form with conditional fields; a table task with a dialog that interrupts). Agents have no task-specific hints. A timed human baseline for each task (the maintainer, or recorded time with a viewer). Add the time split to the benchmark summary. | Agent and human wall time, turns, looks, success | The suite separates arms (variance across 3 runs is below the effect sizes we care about) |
| **E1 Model tiers** | No code: run E0 and the existing hard tasks with `--model` Haiku, Sonnet and Opus, plus effort and fast mode if the CLI exposes them | Seconds per turn, turns, success, wrong actions per tier | Pick the cheapest tier at equal success. Also find which tool features help weaker models most |
| **E2 Effect-first A/B** (tests the thesis) | Every input and batch returns a compact effect summary by default (files, config keys, DOM changes and network requests through BiDi, windows). Step lists accept **effect expectations** (`expect: {file, contains}`, `{config, key, value}`, `{request, method, url, status}`); a mismatch stops the batch and reports it. Tool descriptions present this as the normal way to work | Turns, looks, wall time, success, wrong actions on E0, with Opus and the E1 tier | **Turns or looks −30% at equal success.** If not, the thesis is weak; record that and stop |
| **E3 Observation discipline** (tool side) | Default to text deltas (what changed, in a few lines) and cropped or downscaled images. Send a full frame only when asked or after large changes | Input tokens and turn time | Input tokens −25% at equal success |
| **E4 Plan ahead and predict** | One tool takes a whole plan with **required** effect or UI expectations at each step, instead of optional guards. Variant: the agent states the expected screen or effect, and only the parts that differ are returned | Turns and wall time against E2 | Turns −20% more than E2 |
| **E5 Cloud sessions** | Check whether the headless runtime (labwc, Firefox) runs in a Claude Code cloud session container | Does a private session start, take a screenshot and accept input? | If yes, run E0/E1 arms in parallel there |
| **E6 Verified skills** (after E2) | Turn successful E0 traces into named skills with parameters and effect postconditions. Offer a matching skill at plan time instead of adding tools | Repeat-run time against first run | Repeat runs at least 3× faster at equal success |

## 7. Later (needs funding or a free GPU)

- **Our own agent loop on the API.** It makes these testable: keeping only the
  last k screenshots (context editing), running steps while the reply streams
  (eager tool-input streaming), compaction, and per-turn effort. This needs API
  credits. The maintainer has no credits at the moment.
- **Two-speed agent.** A fast model locates elements and checks results at
  about 1 s per step. Opus decides and handles surprises. Haiku through
  `claude -p` can approximate this with subagents; a local model needs a GPU.
- **Small specialist model.** LoRA-tune a 2–3B vision model on effect-labelled
  data from the data engine (pillar 3) for locating elements, checking changes
  or narrating them. Use Kaggle or Colab. Do this only after E2 and E6 have
  produced data.
- **A continuous agent with true video input** needs a model trained for
  streams. That is lab territory and is not planned.

## 8. End state

The product has three layers.

1. **Engine (core value).** Private sessions, effect observation, checks by
   effect, verified app skills, rollback and commit points. Platform backends
   sit behind one worker interface.
2. **Agent interface.** MCP stays the main channel, with the CLI and an SDK
   alongside. The project stays model-agnostic and does not build its own agent
   (first-release non-goal). Agents improve without our work; the engine makes
   each of them faster and more reliable.
3. **Human app: review, not chat.** It grows from the current read-only viewer:
   - **Effects as a pull request.** The agent works privately, and the person
     reviews "changed 3 files, set 2 keys, sent 1 form to example.com, about to
     send an email". They approve, roll back or take over at commit points.
   - Watch live and take over (exists).
   - A library of learned skills with the date each was last checked.
   - Approvals for host sessions, logins and commit points.

## 9. Windows and macOS

| | Private desktop | Semantic UI | Effect observation | Input without the person's focus |
| --- | --- | --- | --- | --- |
| Linux | Nested compositor (done) | AT-SPI (done) | Files, D-Bus, DOM (done or in progress) | Yes, in private sessions |
| Windows | A hidden desktop breaks capture of GPU-drawn apps; a second login session needs Windows Server or a VM; Windows Sandbox needs Pro | UI Automation | ETW, file watching, and the registry (a natural fit for the atlas) | Partial: window messages work for some applications only |
| macOS | No second session for the same user; VMs work (Apple's licence allows 2 macOS guests per host) | Accessibility API (needs permission) | FSEvents and settings files; Endpoint Security needs an Apple entitlement | Partial: per-process event posting is unreliable |

Path, cheapest first:

1. **A Linux desktop inside Windows and macOS.** On Windows, WSL2 with WSLg
   already runs Wayland applications, so our runtime may work almost unchanged
   (unverified). On macOS, use a small Linux VM. Browser work, which is most
   real work, is covered this way; native Windows and Mac applications are not.
2. **Native host mode** with UI Automation or the Accessibility API plus effect
   watchers. It is approved and expires, like current host sessions.
3. **Native private sessions** through Windows Sandbox or macOS VMs, only when
   native applications need privacy.

Cross-platform support alone does not set the project apart: Cua already runs
macOS VMs and Windows sandboxes. Port only after E2 supports the thesis. Until
then, keep the worker interface free of Linux assumptions where that costs
little. The first-release scope ("native Windows/macOS control" is a non-goal)
is unchanged.

## 10. Open decisions for the maintainer

- Adopt the effect-first thesis as the next focus, with E2 as its gate.
- Make the review app ("effects as a pull request") a stated product goal.
- Record the three-step platform path as the stated direction while native
  ports stay out of scope.
- Decide whether API credits or a free hosted GPU will be used for §7, and when.
