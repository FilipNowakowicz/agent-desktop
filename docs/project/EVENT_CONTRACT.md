# Event and approval contract (X4, 2026-11-11)

This is the contract between the runtime and anything that shows the person what
agents are doing and lets them answer: a desktop shell (the B3 agent-aware desktop),
a notification daemon or a terminal. The first version is implemented as
`agent-desktop events` (see [USAGE.md](../USAGE.md#events-for-shells-and-notifiers)).

## Why

Both field reports lose the person's time in the same places. They relay commands
that do not run, they wait for a handoff that cannot succeed, they hunt for a host
approval, and they find out late that a run stopped. [USER_EXPERIENCE.md](USER_EXPERIENCE.md)
already asks the backend for "structured events with target, time, scope, delivery
and uncertainty". This document makes that contract concrete for the smallest
consumer: one command whose output a shell widget reads.

## Human moments

Each moment is something the person can see or answer. Every one of them already
exists in the runtime, but today it is scattered across tool replies,
`notify-send` and `agent-desktop list`.

| Moment | Today | Answer, with the existing verb |
| --- | --- | --- |
| An agent asks the person to take a private session, for a login, 2FA or CAPTCHA | `desktop_request_human`; `request` in `session.json` | `take`, `take --paste`, `release` |
| An agent asks to use the person's own screen | `desktop_request_host`; `host-request.json` and a `notify-send` prompt | `host approve`, `host deny` |
| The host session is active, then ends or expires | `notify-send` at start; `host status` | `host stop` |
| The person holds control, then gives it back | `control` in `session.json`, `last` in control state | `release` |
| A durable operation finishes, stops, is cancelled or has an unknown delivery | Operation records under the session | None; the agent reconciles |
| A step's delivery was uncertain, or a batch stopped | `trace.jsonl` outcomes (with N5) | None; information only |
| A session is created, becomes ready, stops or fails | `session.json` `status` | `destroy`, or `view` to watch |

With `AGENT_DESKTOP_HOST_APPROVAL=client`, the MCP client asks the person before a
host request, so there is no request to answer and no `host_requested` event; the
host session's own events still appear.

The contract adds no second approval path. A consumer answers by running the same
CLI verbs a person would type. Those verbs keep their checks: approval is per
request, and takeover is cooperative routing, not a confidentiality boundary.

## Smallest version

```sh
agent-desktop events [--follow] [--session SESSION]
```

It prints one JSON object per line. Without `--follow`, it prints what is live now as
events and exits: running sessions, their open requests and who controls them, and a
pending host request. Ended sessions, answered requests and finished operations are
history and are not repeated. With `--follow`, it then prints changes as they
happen. It reads only what the runtime already writes (`session.json`,
`host-request.json`, operation records, `trace.jsonl`), so there are no new writers
and no daemon. The first version rescans those files twice a second.

```json
{"at": 1794220000.1, "event": "human_requested", "session": "3f2a…",
 "reason": "Sign in to the cloud console", "login": true,
 "take_command": "/…/.venv/bin/agent-desktop take 3f2a…",
 "paste_command": "/…/.venv/bin/agent-desktop take --paste 3f2a…"}
```

| Event | Fields besides `at`, `event` and `session` |
| --- | --- |
| `session_started`, `session_ready`, `session_stopped`, `session_failed` | `mode`, `profile`, and `error` (first line only) for a failure |
| `human_requested`, `human_withdrawn` | `reason`, `login`, `take_command`, `paste_command` |
| `control_taken`, `control_returned` | `how`, and `browser` from a login handoff |
| `host_requested`, `host_answered`, `host_expired` | `request`, `reason`, `minutes`, `answer`, `approve_command`, `deny_command` |
| `operation_finished` | `operation`, `state` (`completed`, `stopped`, `cancelled`, `delivery_unknown`), `completed`, `total` |
| `step_uncertain`, `batch_stopped` | `operation` (the traced operation's name), `reason` as N5's category |

## Rules

- **No content.** The trace's rule applies. No typed text, page text, window
  titles, URLs, selectors or command arguments. Two strings are allowed: an agent's
  `reason`, which is written for the person to read, and an error's first line.
- **Printed commands run as printed.** Command fields use N2's form.
- **The state files decide.** An event describes a change in the persisted state,
  not a guess. A consumer that starts late gets the current state first, so it never
  needs history to be right.
- **Same user only.** The output belongs to the user who runs it. Nothing listens
  on a socket.
- **Stable names.** Event names and fields are versioned as part of the CLI. A new
  field is added freely; a removal or rename gets a log entry.

## Out of scope for the first version

- Approving from the event stream itself. A consumer runs the verbs.
- Widgets. The Quickshell consumer lives in the NixOS configuration repository and
  is proposed there as an unmerged pull request (plan row L1).
- Remote consumers, history storage and a replay of past sessions.

## Acceptance for the implementation

- Each event appears within one second of the state change in a private session.
  This is driven by the existing verbs: create, request_human, take, release,
  withdraw, a durable job to each terminal state, a stopped batch and destroy.
- `host_requested` and `host_answered` are tested with a stand-in host request file,
  never the real screen.
- A planted secret in typed text, page text and a window title never appears in the
  output.
- The printed `take_command` from an event runs as printed, as N2 checks.
- A consumer started after the events still gets the current requests.
