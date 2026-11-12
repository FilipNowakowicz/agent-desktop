# Zero-touch delegation: design proposal

Proposed 2026-11-12 for the maintainer's review. **Nothing in this document is
implemented.** It is a design, a critique and a staged roadmap; it changes no
code. [PROJECT_PLAN.md](PROJECT_PLAN.md) stays the status authority until the
maintainer adopts, edits or rejects this. Ideas that go past the roadmap, with
their prior-art status, are in [DELEGATION_BEYOND.md](DELEGATION_BEYOND.md).

Statements are marked by what supports them:

- **proven**: covered by a test or a dated record in this repository, linked;
- **reported**: taken from outside documentation read on 2026-11-12, linked;
- **proposed**: this document's design, untested.

## Summary

- **Goal:** the person states a task and is needed for nothing else. The measure
  is touches per task, reported beside independently checked outcomes.
- **Tasks above sessions:** a record with prompt, attached context, status,
  touches and result. A task whose runner dies is `unknown` and is never rerun.
- **`agent-desktop delegate`:** what the shell hotkey calls. The first runner is
  headless Claude Code (`claude -p`) behind a client-agnostic runner contract.
- **Task events** extend [EVENT_CONTRACT.md](EVENT_CONTRACT.md). Widgets live in the
  NixOS configuration repository; the contract and verbs live here.
- **Context** is only what the person attaches after the hotkey. The runtime never
  captures the real screen for it.
- **Identity:** the model never sees a secret. Reuse a signed-in profile, check
  logins at delegation, refresh under a standing grant, then fill passwords and
  codes from the person's own store, bound to the site. First sign-ins, passkeys,
  CAPTCHAs and payments stay with the person.
- **Approvals:** standing rules in a file the person owns, plus a short fixed list
  that always asks. #196 stays unmerged.
- **Roadmap:** Z0 (measured baseline of touches on 3–5 real tasks, no code) first,
  then tasks and `delegate`, the touch ledger, the shell panel, approvals,
  identity, results, concurrency, unattended runs, the phone and a second field
  report. No code is cut before Z0.

## The goal

The maintainer decided the north star on 2026-11-12: **zero-touch delegation on the
person's own Linux computer, built into their Hyprland and Quickshell desktop.** The
person states what they want and is needed for nothing else. The measure is the
number of times the person is needed per task. This document calls each one a
**touch**.

The two field reports are the evidence that this is worth building, and where it
falls short today:

- In the [cloud setup report](../trials/2026-11-08-gcp-tailscale-setup.md) an agent
  did Google Cloud and Tailscale console work in a private Firefox with the
  maintainer's logins, between stretches of Terraform, `gcloud`, SSH and Nix work.
  The person's screen was never used. The person was still needed for at least
  eight separate actions, all for identity: running `import-cookies` (after two "command not found"
  attempts), a login handoff that Google refused, two attempts at a throwaway
  Firefox profile, a manual sign-in there, a second import and a clean-up. This
  count is reconstructed from the report, not measured.
- In the [Hyprland report](../trials/2026-11-07-hyprland-overhaul.md) agents tested
  a new shell in 24 private desktops and on the real screen. The person approved
  two host sessions (three request calls) and otherwise watched.

Since those reports, the follow-ups N1–N7 removed several causes: secrets move
without the agent reading them, printed commands run as printed, the login handoff
swaps in an ordinary browser, and imports warn about several accounts
([execution plan](PROJECT_PLAN.md#execution-plan-2026-11-11)). What remains is
structural: there is no object for "a thing I asked for", no way to hand one off
from the desktop, no count of touches, and every login still starts with the
person.

## 1. Architecture

```text
Person                                   Agent client (headless)
  │ hotkey, prompt, context chips            ▲        │ MCP tools
  ▼                                          │        ▼
Shell (config repo) ──► agent-desktop delegate ──► task supervisor ──► sessions
  ▲   banners, panel,        │                        │  (private; host only if
  │   result cards           ▼                        │   allowed for this task)
  └──── agent-desktop events --follow ◄── STATE/tasks/<task>/ + STATE/<session>/
              answers: take, release, tasks answer, host approve
```

The runtime stays what it is: explicit sessions, one controller per session,
state in files, no daemon and no listening socket. Delegation adds one layer above
sessions and reuses the event stream below it.

### 1.1 Task model

A **task** is one thing the person asked for. Sessions, operations and handoffs
belong to it. Today the nearest things are a client conversation, which the runtime
cannot see, and a session, which is too small: the cloud setup used four sessions
and one conversation for one request.

Proposed layout, beside the existing session records
([LIFETIMES.md](LIFETIMES.md) would gain a fourth lifetime):

```text
STATE/tasks/<task>/
  task.json      identity and status (0600)
  prompt.md      what the person wrote (0600, never in events)
  context/       the items the person attached (0600)
  touches.jsonl  one line per touch
  result.json    what the agent reported and what the runtime checked
  runner.log     the client's output, bounded
```

| Field in `task.json` | Meaning |
| --- | --- |
| `id`, `created_at` | A 12-character identifier, like a session's |
| `title` | The first line of the prompt, at most 80 characters. Written by the person |
| `status` | `queued`, `running`, `needs_you`, `done`, `failed`, `cancelled` or `unknown` |
| `status_line` | One sentence from the agent for the person, like a request's `reason` |
| `runner` | Which client runs it, its process and start time, and the client's own session identifier for resuming |
| `sessions`, `profiles` | Desktop sessions created for the task and the identities it may use |
| `allow` | What the person allowed at delegation: host screen (minutes), unattended, a time limit |
| `open_request` | The one thing currently waiting for the person, if any |
| `touches` | Counts by kind, derived from `touches.jsonl` |
| `result` | Summary, artifacts, checks and unknowns (section 1.5) |

`unknown` is deliberate. If the supervisor or the client dies without a result, the
task is not `failed` and is never rerun automatically: it may have submitted
something. This is the project's existing delivery rule
([decisions.md](../reviews/2026-10-05-project-review/decisions.md), decision 8)
applied one level up.

Files touched: a new `src/agent_desktop/tasks.py` (records, status, touches) and
`src/agent_desktop/taskrunner.py` (the supervisor); `core.create` records a `task`
in `session.json`; `mcp_server.py` reads `AGENT_DESKTOP_TASK` from its environment,
as it already reads `AGENT_DESKTOP_CONTROLLER`, and passes it on; `core.prune`
learns about task records.

### 1.2 The `delegate` entry point

```sh
agent-desktop delegate [--context-file FILE] [--cwd DIR] [--profile NAME]...
                       [--host MINUTES] [--runner NAME] [--limit MINUTES] PROMPT
```

It writes the task record, starts a detached supervisor
(`python -m agent_desktop.taskrunner`, started the way `core.request_host` starts
`hostprompt.py`) and prints the task as JSON, without waiting for the client. The
shell hotkey calls exactly this. So does a terminal, a script or a phone.

The supervisor starts the client with `AGENT_DESKTOP_TASK` set, watches it, enforces
the limit, records the result, and at the end destroys every session that carries
the task, except one parked for the person. It holds no approval logic.

Companion verbs: `tasks` (list), `tasks show TASK`, `tasks cancel TASK`,
`tasks answer TASK REQUEST ANSWER`, `tasks result TASK [--html]`, and
`tasks prune`. Files touched: `cli.py`, `printed.py` (answer commands that run as
printed).

For the agent, one new MCP tool, `desktop_task`, with three actions: `update` (a
status line), `ask` (a question or an approval, the only permitted way to need the
person outside a login handoff) and `finish` (summary, artifacts, checks). It is one
tool so that it adds little to the schema prefix (section 3.3).

### 1.3 Task events

[EVENT_CONTRACT.md](EVENT_CONTRACT.md) stays as it is, and `events.py` gains task
state as one more thing it derives from files. Proposed additions:

| Event | Fields besides `at`, `event` and `task` |
| --- | --- |
| `task_started`, `task_queued` | `title`, `runner`, `allow` |
| `task_progress` | `status_line`, `sessions`, and `thumbnail` (a path, see 1.4) |
| `task_needs_you` | `request`, `kind`, `reason`, `session`, and the answer commands that apply: `take_command`, `paste_command`, `answer_commands` |
| `task_answered` | `request`, `kind`, `answer`, `by` (`person`, `rule` or `expired`) |
| `task_finished` | `status`, `touches`, `minutes`, `result_command`, `checks` as counts of satisfied, violated and unknown |
| `touch_recorded` | `kind`, `request` |

`kind` is one of `login`, `code`, `captcha`, `unlock`, `approval`, `question`,
`host` or `relay`. Every existing session event gains a `task` field when its
session belongs to one, so `human_requested` and `host_requested` keep working for
consumers that predate tasks.

Changes to the contract's rules, each needing the maintainer's agreement:

- **No content** stays. Two more strings written for the person are allowed: the
  task `title`, which the person wrote, and the agent's `status_line`. The prompt
  and the context never appear.
- **A late consumer is right without history** stays: the first look reports
  running and waiting tasks, and tasks finished since the person last dismissed
  their result.
- **Approving from the stream** stays out. A consumer runs verbs.
- **Stable names** stays. The contract gets a version field in `task_started`.

### 1.4 Shell integration contract

The 2026-11-11 decision Q3 stands: the general contract lives here, the widgets
live in the NixOS configuration repository.

| Lives here (general, tested without any shell) | Lives in the configuration repository |
| --- | --- |
| `delegate`, `tasks …`, `events --follow`, `thumbnail` | The `delegate` global shortcut and the prompt surface (a Spotlight mode) |
| The context file format (section 2.2) and its validation | Capturing context after the hotkey: selection, focused window, a region, files |
| Event names and fields, answer commands that run as printed | The bar item, the agents panel, banners, result cards |
| A reference consumer for tests: a script that follows events and answers | Putting `agent-desktop` on `PATH`, and any systemd user unit |
| Touch records and the summary command | Phone notification wiring (section 2.9) |

Three rules for the boundary:

1. The shell holds no state the runtime does not have. After a shell restart,
   `events` rebuilds every banner and card, as
   [nixos-config#498](https://github.com/FilipNowakowicz/nixos-config/pull/498)
   already does for sign-in requests.
2. The shell never answers on its own. Every answer is a click that runs a printed
   verb. #498's acceptance test already checks "nothing is approved without a
   click".
3. Banners are for `task_needs_you` only. Progress goes to the bar item and the
   panel. Results go to a card that waits to be opened.

**Live thumbnails** need one new verb here: `agent-desktop thumbnail SESSION`. It
writes a small, scaled capture of a private session to a 0600 file under `RUNTIME`
and prints its path. It is the person's observer path, like `view`: it does not
take the controller lease or change observation tokens. It is refused for a host
session, which is the person's screen already. Events carry the path, never the
image. Files touched: `worker.py` (capture without the lease), `cli.py`.

### 1.5 Results and evidence

`desktop_task finish` records what the agent says it did. The runtime then adds
what it can establish itself, and keeps the two apart, as
[USER_EXPERIENCE.md](USER_EXPERIENCE.md) asks ("no universal green badge based on
exit 0"):

- **Artifacts**: each path the agent names, whether it exists, its size and digest.
- **Checks**: `desktop_check` predicates the agent supplies, evaluated by the
  runtime at finish (`checks.py`): satisfied, violated or unknown.
- **Unknowns**: uncertain deliveries and stopped batches from the sessions' traces,
  counted as `core.activity` counts them.
- **Touches**: from `touches.jsonl`.
- **A last frame** of each session, kept under the task.

`tasks result --html` can reuse `review.py`, whose offline report already separates
requested actions, delivery, observations and checks. Its benefit to a person is
unmeasured (R6); the result card would be its first real use.

### 1.6 Delegated identity

An **identity** is a named profile plus what the person has decided about it: which
sites it holds, where its logins may be refreshed from, and which stored
credentials may be filled into which sites. Profiles, cookie import and
`forget-site` exist (`cookies.py`, `core.create`). The decisions do not: today each
one is a command the person runs each time. Section 2.3 gives the design.

## 2. Open questions

Each answer is a recommendation with reasons. None is decided.

### 2.1 Which agent client runs delegated tasks?

**Recommendation: a small, client-agnostic runner contract, with Claude Code as
the first two runners. Do not adopt the Agent SDK or cloud sessions now.**

The runner contract is deliberately thin: a command template, the environment
variable `AGENT_DESKTOP_TASK`, the prompt on standard input, and an exit status.
Anything that can run headless with an MCP server fits. The project's own rule is
that the runtime "does not require a particular model or cloud service"
([README](../../README.md)), and the task records and the touch ledger should
outlive any one client.

| Option | For | Against | Verdict |
| --- | --- | --- | --- |
| `claude -p --output-format stream-json` | Already used by `scripts/benchmark.py` and `scripts/claude_code_task.py`. The stream gives turns, cost, session identifier and `permission_denials`, so runs are measurable. `--permission-prompt-tool` can send the client's own prompts to an MCP tool. `--resume` continues a task | Reported: `--bare` "will become the default for `-p` in a future release" and bare mode "doesn't use your subscription login" ([headless docs](https://code.claude.com/docs/en/headless)). A process the supervisor must keep alive itself | **First runner.** Use it for the baseline and for acceptance tests |
| `claude --bg` background sessions | Reported: a supervisor keeps sessions alive without a terminal and across sleep; `claude agents --json` gives `state` and `waitingFor` (`permission prompt`, `input needed`); `claude attach`, `logs`, `stop` and `respawn` exist ([agent view docs](https://code.claude.com/docs/en/agent-view), [CLI reference](https://code.claude.com/docs/en/cli-reference)) | Reported: "research preview"; `--bg` cannot be combined with `-p`, so there is no result stream; sessions stop at reboot; in a git repository a session moves itself into a worktree before editing | **Second runner**, for daily use once the first is proven. Its `waitingFor` becomes a `task_needs_you` |
| Claude Code cloud sessions (`--cloud`) | Parallel, no local load. E5 showed the private desktop runs there (development log, 2026-10-13) | The cloud machine has none of the person's logins, shell credentials, local network or desktop, which are what this project exists to use | **No**, except for tasks that need none of those |
| Agent SDK (Python or TypeScript) | Tool-approval callbacks and structured messages in-process | A second harness to maintain and a new dependency, for control the CLI already exposes through hooks and `--permission-prompt-tool` | **Not now.** Revisit if the CLI route cannot carry approvals |
| Another vendor's headless client | Keeps the contract honest | No field evidence here | **Allowed by the contract**, untested |

**Is a Claude subscription enough?** Reported, as read on 2026-11-12: yes. The help
centre says that when signed in with a plan, "the Claude Agent SDK and `claude -p`
still draw from your subscription limits", and that a planned move of this usage to
a separate credit was paused on 2026-06-15
([help centre](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-plan)).
Background sessions use "the same stored credentials as your interactive sessions"
and Remote Control needs a subscription and does not accept API keys.

**Limits to plan for:**

- Delegated tasks share the plan's usage limits with interactive work. Reported:
  "each session uses your subscription quota independently". How much of a week's
  limit a typical delegated task uses is unknown here; the baseline (stage Z0)
  should record cost and tokens per task so that it can be estimated.
- A change to this policy was announced in 2026 and then paused, so it may change
  again. The runner contract is the hedge: an API key or another client is a configuration change.
- If `-p` becomes bare by default, the first runner needs an API key or an explicit
  non-bare invocation. Check at each Claude Code update.
- The N10 pilot found a `haiku` desktop subagent cut cost about 75% at equal
  success, with wall time up 51–58%
  ([pilot](../research/2026-11-11-desktop-subagent-pilot.md)). Its gate was wall
  time. For background delegation the scarce things are the person's attention and
  the plan's limit, not seconds. The subagent is worth re-judging on those terms.

### 2.2 How does a task receive context without observing the screen?

**Recommendation: context is only ever what the person attaches by a deliberate
act, captured once by the shell at that moment, shown before sending, and passed as
a file. The runtime never captures the person's screen for context.**

AGENTS.md says never to silently route input to the physical desktop, and every
operation targets an explicit session. Observation deserves the same rule. A host
session's screenshots go to the model provider
([USAGE.md](../USAGE.md#your-own-screen-host-session-experimental)), so "the agent
looked at my focused window to understand the task" must not happen as a side
effect.

The proposed flow:

1. The person presses the delegate hotkey. Nothing is captured before this.
2. The shell gathers candidates from its own side: the primary selection, the
   focused window's application and title, the working directory of a focused
   terminal, and files or a region the person picks with the shell's existing
   capture tools.
3. Each appears as a removable chip under the prompt. Enter sends what is shown;
   Escape sends nothing.
4. The shell writes a context file and calls `delegate --context-file`.

```json
{"items": [
  {"kind": "text", "label": "selection", "text": "…"},
  {"kind": "file", "path": "/home/…/report.odt"},
  {"kind": "folder", "path": "/home/…/project"},
  {"kind": "window", "app_id": "firefox", "title": "…"},
  {"kind": "image", "path": "…/region.png", "label": "region"}
]}
```

Rules the runtime enforces (`tasks.py`): unknown kinds are refused; paths must
exist and are passed by reference, not copied; images must be files the shell
wrote, never a capture the runtime makes; the context is stored 0600 under the
task and removed by `tasks prune`. A `window` item is a description only. If a task
needs to act on that window, that is a host session, with its own approval.

What this does not give: the URL of the focused browser tab, or the content of a
window the person did not select from. Those need either a host session or the
WebExtension idea (plan row L9), and are left out on purpose.

### 2.3 Delegated identity

**Recommendation: keep the model away from every secret, and move each identity
decision from "a command each time" to "a rule decided once". Build it as a ladder,
cheapest rung first, and stop where the baseline says the touches stop.**

**Threat model (proposed, extends decision 3).** The existing model is cooperative
operation as the same user: the project prevents accidents and does not contain an
agent that has a shell. Delegation adds three risks that are not accidents of
routing:

| Risk | Example | Defence in this design |
| --- | --- | --- |
| Web content steers an agent that holds logins | A page tells the agent to create an API key and paste it somewhere | Secrets never reach the model (N1's `send`, proven on fixtures). Credential fill is bound to the site it was saved for. Irreversible steps need a rule or the person (2.4). Real isolation for unattended runs (2.5) |
| Over-reach | The cloud report's import copied every Google account; the default was the wrong one | Imports warn (N6, proven on a fixture). An identity names its sites; anything else asks |
| Standing access outlives its purpose | A profile that stays signed in to a console for months | Identities list what they hold; `forget-site` and `delete-profile` exist; a stale-login check doubles as an inventory |

Out of scope, as today: a hostile local process running as the same user.

**The ladder.**

1. **Reuse a signed-in profile.** Proven: the `gcp` profile stayed signed in to both
   consoles across sessions and days. Nothing to build.
2. **Check before starting, not in the middle.** Proposed: `delegate` checks each
   named identity's logins first (a page and a marker the person configured once
   per site). A stale login becomes a `task_needs_you` at delegation, while the
   person's attention is already on the task. This does not remove the touch. It
   moves it out of the middle of the night.
3. **Refresh logins from the person's Firefox under a standing grant.** Today
   `import-cookies` is "CLI-only on purpose: you choose what leaves your browser,
   not the agent" (USAGE.md). Keep that principle and change its tense: the person
   grants once, per identity and site, and the runtime may then repeat that exact
   import when the check in rung 2 fails. The multi-account warning blocks the
   automatic path. Files: `cookies.py`, a person-owned grants file (2.4).
4. **Fill stored credentials without showing them.** Proposed: a browser action that
   is the mirror of `send`. The worker, on the host side, looks a credential up in
   the person's secret store and types it into the single matching field. The reply
   has a digest and nothing else. It is refused unless the page's origin equals the
   origin stored with the credential.
   - **Where secrets live:** in the store the person already uses, never in this
     project's files. The Secret Service API (GNOME Keyring, KeePassXC's
     integration) is the first target, because one interface covers both. Private
     sessions deliberately hide the Secret Service from applications
     (`worker.mask_secret_service`). That stays: the lookup happens outside the
     session, in the runtime.
   - **Unlocking** the store is the person's. A locked store is a `task_needs_you`
     of kind `unlock`.
5. **One-time codes generated in the runtime.** TOTP is a hash over a seed and the
   time, which Python's standard library can compute. The seed lives in the same
   store. This collapses two factors onto one machine, and the document says so:
   offer it per account, off by default, and never for the person's primary email,
   bank or the password manager itself.
6. **Codes that arrive elsewhere** (SMS, email, an app's push prompt) stay touches.
   The phone path (2.9) makes them cheaper. Reading codes from the person's mail is
   possible in principle and is not proposed.

**Passkeys.** Reported: a passkey ceremony asserts that a human was present, and
the consistent advice is that agents should not complete one
([MojoAuth](https://mojoauth.com/blog/can-an-ai-agent-complete-a-passkey-ceremony),
vendor source). So a passkey prompt is a touch. Two things are worth a cheap test
because they are specific to running on the person's machine: whether a hardware
key touched by the person satisfies a prompt in a private session's Firefox without
a takeover, and whether sites offer a password-plus-TOTP route beside the passkey.
Neither is verified here.

**Keeping sessions alive.** "Remember me" and profiles do most of it (proven for
two consoles). Rung 2's check, run on a timer when nothing is delegated, turns an
expired login into a notice at a convenient time.

**Sites that refuse automation.** Proven on a fixture, not on Google: during the
person's turn the browser runs without the remote agent
(`navigator.webdriver` false) and returns to the bridge afterwards. Reported from
the field: with imported cookies, both consoles accepted being driven through the
bridge afterwards. Where a site still refuses, the order is: pixels in an
unbridged Firefox in the private session, then the person's own Firefox through a
host session, then the person. This project should not build evasion of bot
detection. A site's refusal is recorded as a reason and counted.

**What must still involve the person**, by design: the first sign-in to an account
(or saving its credential), unlocking the secret store, passkeys and hardware keys,
CAPTCHAs, payment and purchase confirmations, account recovery and new-device
confirmations, accepting terms, and any irreversible step no rule covers.

**Grounding in the field failures:**

| Field failure (2026-11-08) | Today | With this design |
| --- | --- | --- |
| The person ran `import-cookies` by hand, twice failing | Printed commands run (N2) | Rung 3: no command after the first grant |
| Google refused the handoff sign-in | Login swap (N7), fixture only | Rung 2 asks at delegation; a real Google sign-in through the swap is an acceptance test |
| The import copied every account | Warning and `forget-site` (N6) | An identity names its account's site; the warning blocks automatic refresh |
| Keys passed through the transcript | `send` (N1) | Unchanged, and the same rule for credentials going in |
| A new account needed a first sign-in | Handoff | Still a touch, counted as `login` |

### 2.4 Approvals

**Recommendation: decide rules once, in a file the person owns; prompt per action
only for a short fixed list; send every prompt, including the client's own, through
one path; and do not merge #196 as it stands.**

**Standing rules.** A person-owned file, `$XDG_CONFIG_HOME/agent-desktop/grants.toml`,
holds what has been decided: which sites an identity may refresh from the person's
browser, which stored credentials may be filled where, which runner may run
unattended, and which task kinds may use the host screen when delegated with
`--host`. The runtime reads it and never writes it. A rule that matches answers a
request with `by: rule`, which is recorded but is not a touch.

**Per-action prompts** remain for: the person's screen, unless allowed at
delegation; first use of a credential or a site by an identity; and a short
enforced list of irreversible outside effects (send, submit, pay, delete). The
[prior-art scan](../research/2026-11-12-ambitious-directions-scan.md) describes
holding such a step "at the brink" with the session live. That is a candidate
feature (stage Z7 mentions it); the rule here is only that such a step asks.

**One path.** [EVENT_CONTRACT.md](EVENT_CONTRACT.md) says "the contract adds no
second approval path". The client has its own permission prompts, which are a
second path today. Proposed: route them into the runtime's. With `claude -p`,
`--permission-prompt-tool` names an MCP tool that receives each prompt; with a
background session, `waitingFor: permission prompt` is visible in
`claude agents --json`. Either becomes a `task_needs_you` of kind `approval`,
answered with `tasks answer`. Reported, not tested here.

**What to do with [#196](https://github.com/FilipNowakowicz/agent-desktop/pull/196).**
It goes the other way: with `AGENT_DESKTOP_HOST_APPROVAL=client`, the host request
is answered by Claude Code's prompt and the runtime's own request disappears, "so
there is also no `host_requested` event". For delegation that has three costs:

- the shell and the touch ledger never see the most sensitive approval there is;
- the safety of the person's screen then rests on one client's hook configuration
  (the pull request says so itself: "the variable without the hook lets an agent
  use the screen without asking");
- a delegated task has no terminal, so the client's prompt is the least visible
  place to ask.

Recommendation: **leave #196 unmerged and close it when stage Z4 lands**, because Z4
gives the same benefit (one question, answerable wherever the task is followed) in
the opposite direction. If the maintainer wants it for interactive sessions before
then, merge it only with a change that still writes a record and an event
(`host_answered` with `answer: approved`, `by: client`), so nothing sensitive
happens unrecorded.

**Avoiding approval by reflex.** Reported: users approve 93% of manual prompts
([Anthropic engineering](https://www.anthropic.com/engineering/claude-code-auto-mode)),
and across 16,895 reviews approval rose while review effort fell
([arXiv 2606.22721](https://arxiv.org/html/2606.22721v1); both from the scan).
Design responses:

- **Fewer prompts is the main defence.** Every prompt that a rule could have
  answered is a defect to fix, not a button to click.
- A prompt says what will happen and where, in the runtime's words, not only the
  agent's `reason`.
- No default button, and Enter does not approve. #498 already requires a click.
- Banners do not take focus, so a keystroke meant for something else cannot answer.
- The ledger records how long each decision took. Many sub-second approvals are
  reported in the summary as a warning sign.
- An answer is bound to its request. An answer to a stale or changed request is
  refused.
- The approval is drawn by the shell on the person's compositor, which a private
  session cannot capture or click. This is real for the graphical path. It is not
  yet a boundary: an agent with a shell can run `agent-desktop host approve`
  itself, as #196's description notes for `host start`. Section 2.5 is where that
  closes.

### 2.5 Do unattended runs need real isolation first?

**Recommendation: no for the roadmap's first stages and for one narrow class of
task; yes before unattended tasks that combine logged-in browsing with an
unrestricted shell.**

The README is plain that a private session is not a security sandbox. But the
session is not where the risk is. The risk is the agent client's shell, which
already runs as the person for hours in ordinary use. Unattended running changes
two things: nobody notices a run going wrong, and a task that browses with real
logins is exposed to web content for longer.

| Class | Example | Requirement |
| --- | --- | --- |
| Attended background | Anything delegated while the person is at the machine | Today's cooperative model. Stages Z1–Z7 |
| Unattended, narrow | Read-only checks, tests in guarded private sessions, work with no identity | `guard_host`, no `--host`, no credential fill, a time limit, and an irreversible step parks the task instead of asking |
| Unattended, with identity | Console work overnight with a signed-in profile | **Real isolation first** (stage Z9): the client runs in a sandbox that cannot read the person's home beyond the task's folders, has no SSH or GPG agent, and cannot run the answer verbs |

The third row is also what turns the approval path of 2.4 from a convention into a
boundary. Bubblewrap is the first candidate; it contained a misbehaving nested
compositor in the [first shell trial](../trials/2026-10-05-desktop-shell.md).
Claude Code's own sandbox is a second candidate and has not been examined here.
Plan row P10 ("strong isolation … needs a threat-model decision") is this
decision.

### 2.6 What counts as a touch, and how is it measured?

**Recommendation: a touch is one episode in which the person must give attention to
a task after delegating it. Measure it from state the runtime already writes, plus
the client's record, and check the count against a diary during the baseline.**

Counted, each with a kind:

| Kind | The person … | Source |
| --- | --- | --- |
| `login`, `code`, `captcha`, `unlock` | takes a session, or pastes, or unlocks | `control` in `session.json`: request, take, release |
| `approval`, `host` | answers a request | `host-request.json`; `tasks answer` |
| `question` | answers a `desktop_task ask` | `tasks answer` |
| `relay` | runs a command for the agent (`import-cookies`, `forget-site`, `host start`) | The CLI records it when a running task uses that profile |
| `follow_up` | sends the client another message | The client's stream or session record |
| `rescue` | takes over without being asked, or cancels and redoes | `take` with no open request; `tasks cancel`; a second task marked as a redo |

Not counted: delegating; opening a result; watching. A request answered by a rule or
by expiry is recorded with `by` and is not a touch.

Rules that make the number comparable:

- Interactions on the same request within two minutes are one touch.
- Two durations are kept beside the count: **blocked time** (request to answer) and
  **hands-on time** (take to release).
- The agent may need the person only through `request_human`, `request_host` or
  `desktop_task ask`. A question asked in prose is invisible to the runtime, so
  the runner's instructions forbid it and the baseline checks transcripts for it.
- Touches outside the machine's sight (the person fixes something by hand in their
  own terminal) cannot be measured automatically. During baseline and field
  periods, the result card asks one question: "anything else you had to do?"

**The number must not be optimised alone.** An agent that never asks has zero
touches. Reported: agents "guess instead of asking" on long tasks
([OSWorld 2.0](https://arxiv.org/abs/2606.29537), from the scan). Every report
therefore pairs touches with outcomes checked independently of the agent, and with
a count of irreversible steps taken without a rule or an answer, which must be
zero.

Related measures exist: task completion under a budget of *k* interventions
([arXiv 2602.11416](https://arxiv.org/pdf/2602.11416)) and attention cost under an
interruption budget
([arXiv 2610.24411](https://www.opentrain.ai/papers/ask-less-ask-better-allocating-user-attention-in-proactive-llm-agents-with-inter--arxiv-2610.24411/)).
Both were found in one search and read only as summaries.

### 2.7 Concurrency

**Recommendation: three running tasks by default, a queue beyond that, one task at
a time per identity and for the host screen, and a time limit on every task.**

What is known:

- Proven: sessions are independent, and one controller per session is enforced by
  a lease (`test_lease`). One session per profile is enforced by a lock
  (`test_profiles`). One host session at a time (`core.create`).
- Recorded: an idle session with Chromium added about 227 MB; rendering is
  software, so CPU is the limit; three benchmark runs at once on 4 vCPUs did not
  slow each other (development log, 2026-10-13, a cloud machine, one measurement).
- Reported: each background client session uses plan quota independently. This,
  not memory, is probably the first limit reached.

So: a cap of three (configurable), tasks that need the same identity queue behind
each other and say so in `task_queued`, and a task that needs the screen waits for
the host session. Every task has a time limit (60 minutes unless set).

**Cleanup.** The supervisor destroys the task's sessions at the end. If the
supervisor dies, the sessions' own guardians already stop their processes
(`test_runtime`), and the next `tasks` call marks the task `unknown`. After a
reboot, tasks are `unknown`; nothing resumes by itself
([LIFETIMES.md](LIFETIMES.md): recovery "stops what was left. It does not resume
it"). A person can restart one knowingly.

### 2.8 When must an agent use the real screen?

**Recommendation: only when the thing the task needs exists only there. Otherwise a
private session, and the task says why when it asks.**

Reasons that qualify:

1. **The real desktop is the subject**: the shell on real hardware, the polkit
   prompt, displays, drag between real workspaces (the Hyprland report's 88 calls).
2. **State that cannot be copied**: a login held only by the running browser
   (session-only cookies, device-bound sessions), an unsaved document, a
   single-instance application bound to this device.
3. **The person asked to be shown** something on their screen.
4. **A site accepts their browser and refuses the private one.**

For signed-in web work the order follows what the maintainer asked for in the
field ("in the background") and their stated preference for their own Firefox over
a fresh sign-in: a signed-in profile; then a refresh under a grant (2.3, rung 3);
then their own Firefox through a host session, where a new tab can be opened
without their pointer or keyboard (X10, seen on the maintainer's screen
2026-11-12, though such a tab cannot be read without a bridge); and only then a
sign-in handoff.

A host session is always a touch unless the person allowed it when delegating.
`delegate --host MINUTES` is that allowance: explicit, for one task, expiring, and
given at the one moment the person is certainly attending. It satisfies AGENTS.md
("the person approves … and which expires") without a second question. A task
delegated without it must ask.

### 2.9 Answering from a phone

**Recommendation: build it last, after the ledger shows that touches happen away
from the desk. Start with notifications only; then allow three kinds of answer over
the person's private network.**

- **Notify.** A consumer of `events --follow` forwards `task_needs_you` and
  `task_finished` to a push service. The maintainer's configuration already
  subscribes the desktop to a private ntfy topic; the same topic reaches a phone.
  The event's no-content rule means the notification holds a reason and nothing
  else. This needs nothing new here.
- **Answer.** Three kinds are worth supporting: allow or deny; a code typed into a
  one-field page, which the runtime types into the session so the model never sees
  it; and "later", which parks the request. This needs a small listener, reachable
  only on the private network, with a one-time token per request. That contradicts
  the contract's "nothing listens on a socket" rule, so it is a deliberate,
  separately reviewed change, and it belongs in the consumer where possible.
- **The client's own surface.** Reported: Claude Code's Remote Control shows a
  session running on the machine in the phone app, with push notifications, on a
  subscription
  ([docs](https://code.claude.com/docs/en/remote-control)). User reports describe
  phone approvals that did not reach the local process
  ([issue tracker mirror](https://claudeissues.com/issue/62553-remote-control-phone-app-approval-dismisses-popup-but-never-reaches-local-proces)).
  Useful for steering a task from the phone; not a replacement for the runtime's
  path, since it cannot take a desktop session or see runtime requests.
- **Not from a phone:** password sign-ins through a remote view of the session, and
  approving use of the person's screen while they are not at it.

## 3. Critique of the repository against this goal

Proposals only. Nothing here is deleted or moved by this document.

### 3.1 What serves the goal

| Part | Why it matters for delegation | Evidence |
| --- | --- | --- |
| Sessions, supervision, guardian cleanup (`core.py`, `worker.py`) | Tasks can be abandoned safely | `test_runtime`, `test_process_identity` |
| Profiles, `import-cookies`, `forget-site` (`cookies.py`) | The identity layer's base | `test_profiles`; cloud report |
| Browser bridge (`browser.py`, `desktop_browser`) | 70% of calls in the cloud report | `test_browser`, `test_dataset_workflow` |
| `send` for secrets | The model-never-sees-it rule, already built once | `test_browser` (planted key) |
| `request_human` with the login swap, `take --paste` | The touch that will always exist, done well | `test_login_handoff`, `test_takeover` |
| Host sessions with expiry, user-comes-first and lock refusal | The explicit, expiring exception | `test_host`, `test_host_screen` |
| `events`, `printed` | The shell contract's first half | `test_events`, `test_printed` |
| Traces and `activity` | The touch ledger's raw material | `test_trace`, `test_activity` |
| Controller lease, profile lock | Concurrency without interleaving | `test_lease`, `test_profiles` |
| `guard_host`, GPU sessions | Delegating work on the desktop itself | Hyprland report; N8 |
| Scoped checks (`checks.py`) | Result evidence that is not the agent's claim | `test_checks` |

### 3.2 What is dead weight or left over

| Part | Origin | Status | Proposal |
| --- | --- | --- | --- |
| `desktop_run`, `script.py`, the script half of `script_jobs.py` | D1 | Gate missed 2026-10-13; off by default | Move to an experiments area or remove from the server. `script_jobs.py` serves only this tool (R3's supervised scripts), so it moves with it |
| `effects.py` (998 lines), `desktop_effects`, the effects instructions | D3 | Gates missed 2026-10-11; "weakened" | Stop offering it to the model. Keep the recorder only if stage Z7 uses file changes as result evidence; decide then |
| `atlas.py`, `desktop_atlas`, `desktop_set`, `scripts/effect_atlas.py`, `settings_map.py` | Effect atlas | Research on a few applications | Move out of the default server. Note that `desktop_atlas`, `desktop_set` and `desktop_effects` are registered even when their features are off, so every client pays for their schemas |
| `AGENT_DESKTOP_LOOK`, `LOOK_DELTA`, `GUARDS` switches in `mcp_server.py` | S1a, E3, S2 baselines | Experiments finished | Remove the switches; keep the adopted behaviour |
| `desktop_operation` (`operations.py`, 791 lines) | R5b | Tested (`test_operations`, `test_interruptions`); never called in either field report | Keep in the CLI and for tests; leave out of the default tool set. For delegation the durable unit is the task and the client's resumable session |
| `review.py` and the `review` verb | R6 | Presentation tested; human benefit unmeasured | Give it its first real job as `tasks result --html` (Z7), or retire it if the result card does not use it |
| `hostprompt.py` (`notify-send` prompt) | Host sessions | Works; duplicates a shell banner | Keep as the fallback when no consumer is following events |
| One-off scripts in `scripts/` (`effects_*`, `effect_induction_demo.py`, `wlroots_*`, `tier_*`, `cua_*`, `m0_*`, `repeat_xwayland.py`) | Past experiments | Historical | Move under one experiments folder so that `scripts/` shows what is current: `benchmark.py`, `claude_code_task.py`, `soak.py`, `lifecycle_stress.py`, the smoke tests |
| Direction documents: `PRODUCT_DIRECTION.md`, `USER_EXPERIENCE.md`, `FUNCTIONALITY_ROADMAP.md`, `DIRECTIONS.md`, `RESEARCH_FINDINGS.md`, plan sections 2–10 | 2026-10 | Overlapping | Left to the parallel cleanup. If this proposal is adopted, it replaces `USER_EXPERIENCE.md`'s viewer-application sketch (the shell is the interface) and plan row L7 |

Plan rows, judged against the goal:

- **Serve it directly:** X4 and L1 (events and shell banners) are stages Z1–Z3
  here. P6 (direction D6, "the person does not wait") is this direction and should leave
  Parked. X8 (add a profile to a running session) removes a restart when a login
  turns out to be needed.
- **Serve it later:** L3 (preview a NixOS rebuild before switching) is the
  safe-delegation form of the Hyprland "magic moment". L9 (WebExtension) is the
  strongest answer to logins the private browser cannot hold. F3 (lifetimes under
  stress) matters once tasks run unattended.
- **Orthogonal, keep parked:** L2, L4, L8, P7–P9.
- **Re-judge:** N10's subagent, on attention and plan limits instead of wall time
  (2.1).

### 3.3 The MCP tool surface

Measured (development log, 2026-11-11): 29 tools, 31,436 schema characters, about
7,900 tokens of fixed prefix. The Hyprland sessions used 11 tools and the cloud
sessions 10; together 15.

| Group | Tools | Field calls (both reports) |
| --- | --- | ---: |
| Used heavily | `browser` 119, `screenshot` 58, `launch` 56, `destroy` 36, `actions` 34 | 303 |
| Used | `key` 18, `create` 15, `click` 14, `drag` 6 | 53 |
| Used rarely | `request_host` 3, `profiles` 3, `list` 3, `scroll` 3, `request_human` 2, `status` 1 | 15 |
| Never used | `type`, `move`, `focus`, `wait`, `windows`, `ui`, `ui_action`, `check`, `control`, `logs`, `operation`, `atlas`, `set`, `effects` | 0 |

"Never used in two reports" is not "useless": `ui` and `ui_action` drive the
LibreOffice dialogs in `test_document_workflow`, and `control` is how an agent
waits for a handoff. The proposal is a default set and named additions, not
deletion:

- **Core (about 10 tools):** `create`, `destroy`, `launch`, `screenshot`, `actions`
  (which already takes every input step, waits and UI actions), `browser`,
  `request_human` (absorbing `control`'s wait), `request_host`, `task`, and one
  `info` tool merging `list`, `status`, `profiles`, `windows` and `logs`.
- **Input singles** (`click`, `key`, `type`, `drag`, `scroll`, `move`, `focus`,
  `wait`): either kept, because agents reach for them, or folded into `actions`.
  This is the one cut that could cost success, so test it.
- **Native applications:** `ui`, `ui_action`, `check`.
- **Experimental:** `operation`, `atlas`, `set`, `effects`, `run`.

Selected with one variable (for example `AGENT_DESKTOP_TOOLS=core,native`).
Acceptance for making the core set the default: on the F2 tasks and one replayed
console task, equal success against the full set, with the prefix measured before
and after. Stage Z8 carries it. The merge of the input singles is run as its own
arm.

### 3.4 What to merge or cut now

- **nixos-config#498** is the natural base of the shell work, and stage Z3 extends
  it. Whether to merge it is the maintainer's decision in that repository.
- **#196**: do not merge as it stands (2.4).
- **No code cuts before Z0.** The baseline may show that a "never used" tool is
  exactly what a delegated task reaches for.

## 4. Staged roadmap

Stages are numbered Z0–Z11 (Z for zero-touch), so that they cannot be confused
with the directions board's D1–D10 or the plan's N, X, L and P rows. Each stage is
one reviewable pull request, in this repository unless marked **config**. Stages follow the existing rules: branch from `main`, run the local
desktop suite, add a development log entry. Acceptance tests use private sessions
and stand-ins: never the real screen, the real keyring or a real account, unless a
row says the maintainer runs it.

The order after Z4 should follow Z0's result. If logins dominate the baseline, as
the field reports suggest, Z5 and Z6 come before Z7. If follow-up questions and
rescues dominate, Z7 comes first.

| Stage | What | Depends on |
| --- | --- | --- |
| Z0 | Measured baseline of touches on 3–5 real tasks | None |
| Z1 | Task records, `delegate`, the supervisor, task events | None (Z0 informs it) |
| Z2 | Touch ledger | Z1 |
| Z3 | **config:** delegate hotkey, bar item and panel; `thumbnail` verb here | Z1; nixos-config#498 |
| Z4 | One approval path and standing rules | Z1, Z2 |
| Z5 | Identity I: login check at delegation, refresh under a grant | Z1, Z4 |
| Z6 | Identity II: credential fill and one-time codes | Z4, Z5 |
| Z7 | Results and evidence; **config:** result cards | Z1, Z2 |
| Z8 | Concurrency, limits, cleanup, and the default tool set | Z1 |
| Z9 | Unattended tasks and the isolation they need | Z4, Z8 |
| Z10 | **config and here:** phone notifications, then answers | Z4; only if Z2's data asks for it |
| Z11 | Second field report against Z0 | Z3–Z7 in daily use for a week |

### Z0. Baseline (first; no runtime code)

Run 3–5 real tasks the way a delegated task would run today: one prompt to
`claude -p --output-format stream-json` with the MCP server, started from a
terminal as a stand-in for the hotkey, with `agent-desktop events --follow` logged
beside it. The maintainer chooses the tasks and agrees the accounts and the model
budget first (CONTRIBUTING.md). Suggested mix, to cover the kinds of touch:

1. console work with an identity that is already signed in (for example create a
   scoped key and store it as a repository secret, never shown);
2. a signed-in task on a site that is not yet in any profile, so a first sign-in is
   needed;
3. a change to the desktop configuration, checked in a guarded private session;
4. a native document task ending in an exported file;
5. a web task that ends at an irreversible step, where the agent must stop and ask.

Record per task: every touch with its kind, blocked time and hands-on time; the
outcome, checked by the maintainer independently of the agent's reply; cost,
tokens and wall time. Count touches twice, from a diary the maintainer keeps and
from the logs, and explain every difference: that difference is the specification
for Z2.

**Acceptance:** a dated report in `docs/trials/`, linked from the README table,
with the per-task table, the two counts reconciled, at least one task with a
sign-in, any question asked in prose listed as a measurement gap, and the proposed
order of Z5–Z7 confirmed or changed. A small script that derives candidate touches
from the event log and the client stream may accompany it.

### Z1. Tasks, `delegate` and task events

**Acceptance**, with a fake runner (a script that uses the real CLI) and real
private sessions:

- `delegate` returns the task within one second and before the runner's first
  action. The runner creates a session, types into a terminal fixture that records
  what it received, calls `request_human`, and finishes.
- A separate process following `events` sees `task_started`, the session's events
  carrying the task, `task_needs_you`, then (after the test runs `take` and
  `release`) `task_finished`, each within one second of the state change.
- A string planted in the prompt, the context and the typed text never appears in
  the event output.
- A consumer started halfway sees the running task and its open request.
- **Failure:** the runner is killed. The task becomes `unknown`, not `failed`; its
  sessions are destroyed; no process carrying their tokens remains; the profile
  lock is released; nothing is rerun.
- **Failure:** the supervisor is killed. The sessions' guardians clean up, and the
  next `tasks` call reports `unknown`.
- `tasks cancel` stops the runner and the sessions and reports `cancelled`.
- A task with `--host` absent whose runner calls `request_host` produces an
  ordinary request (tested with a stand-in host, as `test_host` does).
- One real-agent smoke run, in the style of `scripts/claude_code_task.py`: a
  delegated fixture task completes and the harness verifies the page state itself.

### Z2. Touch ledger

**Acceptance:**

- A take and release on a request yields one `login` touch whose hands-on time is
  within one second of the measured interval.
- Two interactions on one request inside two minutes are one touch; two requests
  are two.
- A request answered by expiry is recorded with `by: expired` and is not a touch.
- `import-cookies` run while a task uses that profile is recorded as `relay` for
  that task.
- A follow-up message to the client is recorded as `follow_up`.
- Replaying Z0's logs gives Z0's diary counts, or each difference is listed.
- `agent-desktop touches --days N` prints counts by kind, median per task and the
  two durations, with no content.

### Z3. Hotkey, bar item and panel (config), `thumbnail` (here)

**Acceptance for `thumbnail`**, in a real session: the file changes after typed
input; the call works while another controller holds the lease and leaves that
controller's observation token valid; a host session is refused.

**Acceptance for the shell**, in a nested Hyprland inside a GPU session with real
input, as #498's `acceptance.py` does, against faked commands:

- the hotkey opens the prompt; typed text and Enter run `delegate` with exactly
  that text and the chips shown; Escape runs nothing;
- the capture fakes log zero calls before the hotkey, and a removed chip is not in
  the context file;
- the bar item counts running and waiting tasks from a faked event stream; the
  panel shows title, status line and thumbnail path;
- a banner appears for `task_needs_you` and for nothing else; a result waits as a
  card and raises no banner;
- restarting the stream neither loses an open request nor repeats an answered one.

### Z4. One approval path and standing rules

**Acceptance:**

- A real `claude -p` run whose tool needs permission produces `task_needs_you`
  with kind `approval`. `tasks answer … allow` lets it continue; `deny` is reported
  to the agent; no answer before the limit is a denial.
- A matching rule answers with `by: rule`, no banner and no touch.
- An answer to a request that has been replaced is refused.
- The grants file is never written by the runtime (checked by digest across the
  whole suite).
- The event stream still approves nothing: a consumer that only reads cannot
  change any state.
- #196 is closed or amended as the maintainer decides.

### Z5. Identity I: check and refresh

**Acceptance**, with a local site that signs in by cookie and a stand-in "person's
Firefox profile" directory:

- A profile with a valid login: the check passes and the task starts with no
  event.
- An expired login with a grant: the import repeats, the check passes, the task
  runs, and the ledger shows zero touches and one `by: rule` record.
- An expired login without a grant: `task_needs_you` at delegation, before any
  session work, with a command that runs as printed.
- Two accounts for the site in the source: the automatic path stops and asks.
- A grant for one site does not import another (checked in the profile's cookie
  store).
- **Maintainer-run:** Z0's signed-in task again; its login touches fall to zero on
  the second run. A real Google sign-in through the handoff swap is attempted
  once and the result recorded either way.

### Z6. Identity II: credential fill and codes

**Acceptance**, with a local sign-in page (name, password, one-time code) and a
stand-in Secret Service on the test's own bus:

- The sign-in succeeds, and the fixture confirms the values it received.
- The planted password and seed appear nowhere in tool results, traces, operation
  records, effect reports, review output, logs or retained screenshots.
- The same form served from another origin: refused, nothing typed, and the
  fixture confirms it received nothing.
- A locked store: `task_needs_you` with kind `unlock`; after unlocking, the fill
  proceeds once.
- More than one matching field: refused without listing values, as `send` does.
- One-time codes are off unless the account's entry allows them.

### Z7. Results and evidence

**Acceptance:**

- A fixture task where the agent reports success but a supplied check is violated:
  `task_finished` carries the violated count, and the result never shows as
  verified.
- A named artifact that does not exist is listed as missing.
- An uncertain step in a session's trace appears in the result's unknowns.
- `tasks result --html` renders with no network access and mode 0600.
- **config:** the card opens the artifact and shows touches and unknowns; a failed
  check is visible without expanding anything.
- Optional, as a separate arm: a task that reaches an enforced irreversible step
  parks with its session alive and resumes on an answer. The scan's five gates for
  that feature apply if it is built.

### Z8. Concurrency, limits, cleanup, tool set

**Acceptance:**

- Four tasks with a cap of three: the fourth is `task_queued` and starts when one
  ends.
- Two tasks naming one identity run one after the other; the second's queue reason
  names the profile.
- A task over its time limit is stopped and reported `failed` with the reason; its
  sessions are gone.
- `scripts/lifecycle_stress.py` extended to tasks: 20 cycles under load leave no
  processes, sockets or locks.
- After a simulated reboot (runtime directory removed), tasks read `unknown`.
- Three real delegated fixture tasks at once: memory and CPU recorded in the log.
- The tool-set comparison of section 3.3, recorded either way.

### Z9. Unattended tasks

**Acceptance:**

- In the sandboxed runner, a canary file in the real home is unreadable, the SSH
  agent socket is absent, and `agent-desktop host approve` and `tasks answer` fail.
- The same fixture task still completes inside the sandbox.
- An unattended task that calls `request_host` is refused; one that reaches an
  irreversible step parks.
- An unattended task with an identity is refused unless the runner is sandboxed.

### Z10. Phone

**Acceptance:** a notification carries the reason and no content; a one-time
answer link works once and only for its request; the listener is unreachable from
outside the private network (checked from a second network namespace); a code
entered on the page reaches the fixture and appears in no record.

### Z11. Second field report

A week of the maintainer's real tasks through the hotkey.

**Gate:** median touches per task at most half of Z0's on comparable tasks, no
approval given by mistake, no irreversible step taken without a rule or an answer,
and outcomes verified at Z0's rate or better. If the gate is missed, the report
says which kind of touch remained, and the direction is reconsidered before more
is built.
