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
| `destroy` | Stopped: the session's applications (matched by session token) and its runtime directory are removed | Kept with status `stopped`; `home` and `config` are removed | Kept, and unlocked once the guardian has stopped everything | **tested**: `test_runtime` (runtime removed), `test_profiles` (lock held until cleanup), `test_lifecycle` (repeated cycles, below) |
| The worker is killed; the guardian survives | The guardian stops every process carrying the session token (a running operation job and a takeover server included) and removes the runtime directory | Marked `failed` with the reason; `home` and `config` are removed; trace, screenshots and operation records are kept, and a job that was running reads `delivery_unknown` with its step `uncertain` | Kept; the lock is released only after the guardian has finished | **tested**: `test_runtime` (guardian cleanup), `test_profiles` (lock held), `test_lifecycle` (records, profile files, during a takeover) |
| Both supervisors are killed | Left running until recovery: `destroy`, or the next `create` on the same profile, stops leftover applications by token and removes the runtime. A child that left the session with `setsid env -i` carries no token and is not found (known limit), unless the session was created with `AGENT_DESKTOP_SYSTEMD_SCOPE=1`: then recovery also stops every process in the session's systemd scope | Marked `stopped` with `recovered: true`; `home` and `config` are removed by the recovery, not before | Kept; a profile whose last session was abandoned is recovered before reuse | **tested**: `test_runtime` (destroy recovers), `test_profiles` (next session recovers), `test_lifecycle` (records, home kept until recovery; the env-cleared child is an expected failure without a scope; `SystemdScopeTests` stops it with one) |
| An application exits or crashes | The session stays up, other applications and the controller lease are unaffected, and the application can be started again and receives input | Kept, with each run's log | Whatever the application saved is kept (in a non-profile home until `destroy`) | **tested**: `test_lifecycle` (a killed terminal restarted) |
| Firefox restarted in the session | Until `browser start`, actions fail with "No bridged Firefox"; `start` launches and connects to a new Firefox; tab contexts from before are gone, and an action naming one fails with `target_lost` rather than using another tab | Operation records keep their contexts | A cookie and a download in the home survive the restart; across sessions only in a profile | **tested**: `test_lifecycle` (clean exit and restart, profile session), `test_interruptions` (`target_lost` for a closed tab) |
| The viewer (`viewer`, `take`) closes | The session keeps running with its lease. The read-only server stays and is reused by the next viewer; a takeover server exits with its viewer, control returns to the agent (a new screenshot is needed) and `take` starts a new one | Kept (`viewer.log`, `takeover.log`) | Kept | **tested**: `test_lifecycle` (5 read-only and 5 takeover closures), `test_viewer`, `test_takeover` |
| The compositor exits or is killed | The worker notices (0.7–0.8 s when idle; a `type` in progress replies `DeliveryUnknown` at once) and the session ends: processes stopped by token, runtime removed | Marked `failed` with an error naming the compositor; records kept | Kept and unlocked; the next session on it reports the failed end | **tested**: `test_runtime`, `test_lifecycle` |
| Runtime upgrade (new labwc, Firefox, …) | Not supported for a running session: recreate it. A tool the session started with that has since been removed fails with an error saying the runtime changed; `status` and `destroy` still work. A new session uses the new tools | Kept | Kept; applications must cope with their own profile versions | **tested**: `test_lifecycle` (tools removed under a running session, a new session on the profile) |
| Agent Desktop upgraded or removed (a pulled checkout, a reinstalled tool) | A running worker keeps the code it started with: the modules its requests use are loaded at start. The new version can list, recover and destroy it, but other requests across versions are not promised: recreate the session to use the new code | Records from earlier versions are listed, recovered and pruned; an operation record of another schema version is refused as evidence, not guessed at | Kept; an abandoned session in an older record is recovered before reuse | **tested**: `test_lifecycle` (installation removed under a running session; 2026-10-05 manifests) |
| Machine reboot or logout | Gone with `RUNTIME`; `list` reports such sessions as `unavailable` until they are destroyed (which recovers them), also when `RUNTIME` is at another path after the reboot. Process numbers in the record that now belong to other processes are never signalled: recovery finds processes by session token | Kept, including `home` until recovery. A job that was running reads `delivery_unknown`: a job's process is identified by number, start time and boot id, so a new process with the same number and start time is not taken for it. `prune` keeps such records until recovery | Kept, and unlocked; the next session on it recovers the old one first | **tested**: `test_lifecycle` (simulated in private directories: processes killed at once, `RUNTIME` removed, numbers reused, another boot id) |
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

`tests/test_lifecycle.py` does this for application restart, Firefox restart,
compositor loss, worker loss, loss of both supervisors, viewer closure,
repeated cycles, runtime and Agent Desktop upgrades, and a reboot. Each test
keeps a process outside the session with the same command line (`sleep D`) as
one inside it and checks that it still runs. The reboot is simulated without
touching the machine: every session process is killed at once, the private
`RUNTIME` is removed and replaced at another path, recorded process numbers are
pointed at live unrelated processes and a job record gets another boot id. A
real reboot or logout has not been tested.
