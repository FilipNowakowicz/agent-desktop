# State lifetimes

What each kind of Agent Desktop state is, where it lives, what removes it and
what must be recreated after each event. This is the first F3 item in
[FUNCTIONALITY_ROADMAP.md](FUNCTIONALITY_ROADMAP.md). Rows marked **tested** name
the test that checks them. Rows marked **untested** are this specification's
intent, and the F3 stress tests still have to check them.

Paths use `STATE` for `$AGENT_DESKTOP_STATE_DIR`, or by default
`$XDG_STATE_HOME/agent-desktop` (`~/.local/state/agent-desktop`). `RUNTIME` is
`$XDG_RUNTIME_DIR/agent-desktop`.

## Three lifetimes

There is no separate "workspace" object. The roadmap's workspace is one of two
things: a session's private home, or a named profile's home.

| Lifetime | Begins | Ends | Holds |
| --- | --- | --- | --- |
| **Session runtime** | `create` | `destroy`, or recovery after the session's supervisors die | Compositor, bus, worker and guardian processes, the session's applications, sockets in `RUNTIME/<session>`, the controller lease, take markers |
| **Session record** | `create` | `prune` of a stopped or failed session | `STATE/<session>`: `session.json`, logs, `trace.jsonl`, `screenshots/`, `operations/` |
| **Profile** | First `create --profile NAME` | `delete-profile NAME` only | `STATE/profiles/NAME/home` (a persistent home: browser logins, application settings, downloads), `last-session.json` and a lock file beside it |

A session without a profile gets a private home, `STATE/<session>/home`, and a
`config` directory. Both are deleted when the session ends: anything the agent
saved or downloaded there and still needs must be moved out before `destroy`.
A host session has neither, and works on the person's own screen and files.

## What each event keeps

| Event | Session runtime | Session record | Profile | Status |
| --- | --- | --- | --- | --- |
| `destroy` | Stopped: the session's applications (matched by session token) and its runtime directory are removed | Kept with status `stopped`; `home` and `config` are removed | Kept, and unlocked once the guardian has stopped everything | **tested**: `test_runtime` (runtime removed), `test_profiles` (lock held until cleanup) |
| The worker is killed; the guardian survives | The guardian stops every process carrying the session token and removes the runtime directory | Marked `failed` with the reason; `home` and `config` are removed | Kept; the lock is released only after the guardian has finished | **tested**: `test_runtime` (guardian cleanup), `test_profiles` (lock held) |
| Both supervisors are killed | Left running until recovery: `destroy`, or the next `create` on the same profile, stops leftover applications by token and removes the runtime | Marked `stopped` with `recovered: true` | Kept; a profile whose last session was abandoned is recovered before reuse | **tested**: `test_runtime` (destroy recovers), `test_profiles` (next session recovers) |
| An application exits or crashes | Intended: the session stays up and other applications are unaffected | Kept | Whatever the application saved is kept | untested |
| Firefox restarted in the session | Intended: `browser start` connects to the new Firefox; tab contexts from before are gone, and an action naming one fails with `target_lost` rather than using another tab | Operation records keep their contexts | Logins persist only in a profile | `target_lost` for a closed tab is **tested** (`test_interruptions`); a restart is untested |
| The viewer (`viewer`, `take`) closes | Intended: the session keeps running, and opening the viewer again starts a new one | Kept | Kept | untested |
| Runtime upgrade (new labwc, Firefox, …) | Not supported for a running session: recreate it | Kept | Kept; applications must cope with their own profile versions | untested |
| Machine reboot or logout | Gone with `RUNTIME`; `list` reports such sessions as `unavailable` until they are destroyed (which recovers them) | Kept | Kept | untested |
| `prune [--older-than DAYS]` | Never touches live sessions | Removes stopped or failed records past the cutoff | Never touched | **tested**: `test_retention` |
| `delete-profile NAME` | Refused while a session uses the profile | Not touched | Removed | **tested**: `test_profiles` |

## Bounds inside a session record

| State | Bound | Status |
| --- | --- | --- |
| Screenshots | The newest 200 per session (`AGENT_DESKTOP_KEEP_SCREENSHOTS`) | **tested**: `test_retention` |
| Durable operation records | One active job per session; the newest 32 records, each at most 512 KiB, with the oldest finished ones dropped first | bounded in `operations.py` |
| Action trace | One line per request, without typed text or command arguments; kept until `prune` | `test_trace` |
| Events | Derived from the records above; nothing extra is stored (EVENT_CONTRACT.md) | `test_events` |

## What is never promised

- Whole-system snapshots, or reversing what an application did to files or
  external services.
- Restoring a session's applications, windows or unsaved documents after
  supervisor loss or a reboot. Recovery stops what was left. It does not resume
  it.
- Keeping a non-profile session's home after `destroy`.

## What F3 has to check

Each "untested" row above, plus repeated create/use/destroy cycles
(`scripts/lifecycle_stress.py`). After each event, check files, profiles,
downloads, operation records, owned processes, sockets and leases against this
table, and confirm that unrelated applications were not stopped.
