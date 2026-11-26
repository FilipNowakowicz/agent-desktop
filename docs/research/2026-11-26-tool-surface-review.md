# MCP tool-surface review, 2026-11-26

The field reports of 2026-11-20 and 2026-11-25 each found that 21 to 22 of the 29
default MCP tools were not called in their window. On 2026-11-26 the maintainer
decided to look at why, decide which are stale or redundant, and remove them. This
note records the evidence, the decision for each tool and the schema cost before
and after. It describes `main` at `c0f991b` and the change that follows it.

## Method

- **Organic use.** `scripts/usage_review.py --since 2026-10-01` over every Claude
  Code transcript still on disk. The oldest is from 2026-11-06, because older ones have
  expired. That gave 905 deduplicated calls in 35 transcripts, from 2026-11-06 to
  2026-11-26. Most came from the NixOS configuration project (Hyprland and shell
  testing, 555 calls), the research project with exchange accounts (201), coursework
  and flashcards (120) and this repository (22). Per-tool counts were split into
  before and after 2026-11-12, when the Hyprland overhaul ended.
- **Worker operations.** `agent-desktop activity --days 60` counts the operations
  that retained sessions ran from 2026-11-07 to 2026-11-26 (977 calls in 75 sessions),
  whichever client made them, including SDK bridges that leave no transcript.
- **Benchmarks.** Tool counts in `benchmarks/results/*.json` from October (tool
  profiles, D1 scripts, E6 skills). These are model runs on fixture tasks, not
  daily use, but they show which tools a model picks when the task needs them.
- **Schema cost.** This uses the method of the
  [2026-11-11 protocol](2026-11-11-desktop-subagent-protocol.md#side-measurement-done-no-model):
  the characters of each listed tool's `name`, `description` and `inputSchema` as
  JSON, plus the server instructions, with no experiment variables set, divided
  by four for an estimate of tokens. Tokens were estimated, not counted with a
  tokenizer.

The "22 unused" in the 2026-11-20 report covers only that report's two days, 55
calls and 6 tools. Across the longer window, most of those 22 were used: 21 of the 29
default tools were called at least once, and 8 were never called. A tool that is
unused in a short window can still be needed, so each tool is judged on the long
window, the benchmarks and whether another tool already does its job.

## Usage

| Tool | Transcript calls 11-06 to 11-26 | Since 11-12 | Last call | Worker ops (activity) | October benchmarks |
| --- | ---: | ---: | --- | --- | ---: |
| `desktop_browser` | 402 | 283 | 11-26 | browser 552 | (bridge off) |
| `desktop_screenshot` | 85 | 27 | 11-26 | 112 | 576 |
| `desktop_launch` | 78 | 21 | 11-26 | 55 | harness |
| `desktop_destroy` | 75 | 38 | 11-26 | n/a | harness |
| `desktop_actions` | 74 | 40 | 11-26 | (as steps) | 211 |
| `desktop_create` | 57 | 41 | 11-26 | n/a | harness |
| `desktop_key` | 31 | 13 | 11-22 | 66 | 57 |
| `desktop_click` | 28 | 14 | 11-26 | 73 | 308 |
| `desktop_wait` | 12 | 12 | 11-18 | (client side) | 23 |
| `desktop_request_host` | 10 | 7 | 11-25 | n/a | disabled |
| `desktop_type` | 7 | 7 | 11-26 | 36 | 81 |
| `desktop_request_human` | 7 | 5 | 11-23 | 7 | disabled |
| `desktop_profiles` | 6 | 3 | 11-23 | n/a | 0 |
| `desktop_scroll` | 6 | 3 | 11-13 | 10 (with steps) | 14 |
| `desktop_drag` | 6 | 0 | 11-07 | 0 | 14 |
| `desktop_move` | 5 | 5 | 11-26 (one shell test) | 5 | 1 |
| `desktop_control` | 5 | 5 | 11-23 | n/a | disabled |
| `desktop_windows` | 3 | 3 | 11-12 (this repo) | n/a | 40 |
| `desktop_status` | 3 | 2 | 11-13 | n/a | 1 |
| `desktop_list` | 3 | 0 | 11-09 | n/a | 0 |
| `desktop_focus` | 2 | 2 | 11-12 (this repo) | 4 (with steps) | 27 |
| `desktop_ui` | 0 | 0 | never | 0 | 95 |
| `desktop_ui_action` | 0 | 0 | never | 0 | 70 |
| `desktop_check` | 0 | 0 | never | 0 | 0 |
| `desktop_operation` | 0 | 0 | never | 0 | 0 |
| `desktop_logs` | 0 | 0 | never | n/a | 1 |
| `desktop_effects` | 0 | 0 | never | 0 | (effects runs) |
| `desktop_atlas` | 0 | 0 | never | n/a | (atlas runs) |
| `desktop_set` | 0 | 0 | never | 0 | (atlas runs) |

"n/a": the operation runs in the client and is not a worker operation. "harness":
the benchmark harness does it and disables the tool. `desktop_run` (opt-in with
`AGENT_DESKTOP_RUN=1`) was not enabled in any transcript.

Why the never-called tools were not chosen:

- **Accessibility (`ui`, `ui_action`).** Nearly all daily use was web pages, which
  `desktop_browser` handles better. The one native-app task (Anki, 2026-11-13)
  clicked by coordinates. The server instructions never mentioned accessibility,
  so an agent had no reason to try it. In the benchmarks, where tasks are native
  dialogs, models used both often. So this is a discovery problem, not a useless tool.
- **Checks and durable operations (`check`, `operation`).** These were built for F1
  correctness work: predicates with satisfied, violated or unknown, and jobs that
  outlive a lost reply. No daily task needed a job that outlives the call. Waits
  and `expect` on a step already cover the file, config and element checks that
  agents need.
- **Experiments (`atlas`, `set`, `effects`).** These only work when the server has
  `AGENT_DESKTOP_ATLAS` or `AGENT_DESKTOP_EFFECTS=1`, and daily use never sets them.
  Without the variable they could only fail, but their schemas were sent anyway. The
  directions board records that these experiments missed their gates.
- **Logs.** Three session starts failed with a GPU renderer (11-10, 11-17,
  11-18). The create error already names `session.log` and quotes its first
  error, and the agents read the file with the shell or retried without a
  renderer. They never needed `desktop_logs`. The logs are still the only view of
  a failure inside a session, so they are kept, as part of `desktop_status`.

## Decisions

Categories: (a) redundant, folded into a kept tool; (b) stale or experimental,
removed from the default list; (c) useful but hard to discover, kept with better
text; (d) kept as is.

| Tool | Decision | Reason | Where its behaviour lives now |
| --- | --- | --- | --- |
| `desktop_list` | (a) fold | 3 calls, last 11-09; a one-line listing | `desktop_status` without `session` returns `{"sessions": [...]}` |
| `desktop_logs` | (a) fold | Never called, but the only view of why a session failed | `desktop_status(session, logs=true)`; works for a stopped or failed session (adds `status_error`) |
| `desktop_move` | (a) fold | 5 calls, all in one shell-hover test; already a step | `{"action": "move", "x", "y"}` in `desktop_actions` |
| `desktop_drag` | (a) fold | 6 calls, none since 11-07; already a step | `{"action": "drag", "x", "y", "to_x", "to_y", "button"}` |
| `desktop_scroll` | (a) fold | 6 calls, none since 11-13; already a step | `{"action": "scroll", "dy", "dx", "x", "y"}` |
| `desktop_focus` | (a) fold | 2 calls, both in this repository; already a step | `{"action": "focus", "window"}` |
| `desktop_ui_action` | (a) fold | Never called in daily use. The step form also targets by name, so it needs no listing first | `ui_action` step in `desktop_actions` (by `node`, or by `element`/`role`/`state`/`window`/`app`) |
| `desktop_check` | (a)/(b) remove | Never called. File, config and element checks are `desktop_wait` conditions and `expect`. Only `claim: all/unique` and `browser_context` predicates are lost from MCP | CLI `agent-desktop check`; script `check()`; `desktop_wait` |
| `desktop_operation` | (b) remove | Never called; an F1 durability experiment. Its job records and recovery stay | CLI `agent-desktop operation` |
| `desktop_atlas` | (b) opt-in | Experiment that only works with `AGENT_DESKTOP_ATLAS` | Offered only when the server has that variable |
| `desktop_set` | (b) opt-in | Same | Same |
| `desktop_effects` | (b) opt-in | Works only for sessions made with `AGENT_DESKTOP_EFFECTS=1` | Offered only when the server has `AGENT_DESKTOP_EFFECTS=1`, as its instructions already assume |
| `desktop_ui` | (c) keep, improve | The only MCP read of the accessibility tree; used 95 times in benchmarks; never discovered in daily use | Description now says when to use it and how to act with a `ui_action` step; the server instructions name it for non-web applications |
| `desktop_windows` | (c) keep, improve | Window ids for focus steps, and workspaces on a Hyprland host session (X5) | Description now gives the focus step |
| `desktop_status` | (c) keep, extended | Health, profile, lease; now also the session list and logs | Server instructions mention both uses |
| `desktop_wait` | (d) keep | 12 calls; the host-session instructions rely on waiting for a window title; native apps and files need it; `expect` uses its conditions | Unchanged |
| `desktop_control` | (d) keep | Safety model: the only way to wait for a person to hand control back | Unchanged |
| `desktop_request_human` | (d) keep | Safety model: handoffs and logins | Unchanged |
| `desktop_request_host` | (d) keep | Safety model: the person's approval for their own screen | Unchanged |
| `desktop_destroy` | (d) keep | Safety model and cleanup | Unchanged |
| `desktop_create`, `desktop_profiles`, `desktop_launch` | (d) keep | Lifecycle; used in every window | Unchanged |
| `desktop_screenshot`, `desktop_click`, `desktop_type`, `desktop_key` | (d) keep | Used in daily use (28-85 calls each) and with `screenshot=true` they are one-call observe steps. Folding them into `desktop_actions` was the one cut the 2026-11-12 delegation note said could cost success | Unchanged |
| `desktop_actions`, `desktop_browser` | (d) keep | The two most used ways to act | `desktop_actions` now describes each step's arguments, since five of them no longer have a tool of their own |

Nothing the safety model depends on was removed: host approval, handoff, control and
destroy are unchanged. All removed behaviour is still in the CLI. The only loss is
that MCP clients can no longer use `desktop_check`'s universal and uniqueness claims
or `desktop_operation`'s jobs. Neither was ever called.

## Schema cost

| Revision | Tools | Schema characters | Instruction characters | Estimated tokens |
| --- | ---: | ---: | ---: | ---: |
| `e5f5883` (2026-11-11, from the protocol) | 29 | 31,436 | 3,158 | about 8,650 |
| `c0f991b` (main before this change) | 29 | 36,963 | 3,191 | about 10,040 |
| this change | 17 | 28,819 | 3,480 | about 8,075 |

The fixed prefix falls by 7,855 characters, about 1,960 tokens or 20%, for every
agent that loads the server. The removed tools cost 9,515 characters:
`operation` 1,903, `check` 1,334, `ui_action` 973, `scroll` 935, `drag` 824,
`effects` 818, `set` 686, `atlas` 588, `focus` 515, `move` 474, `logs` 282 and
`list` 183. The longer `actions`, `ui`, `status` and `windows` descriptions and
the instruction text add 1,660.

`desktop_browser` alone is now 8,464 characters, 29% of the prefix. It grew from
4,740 on 2026-11-11 as field-report fixes added text. It is the biggest remaining
cost, but it is also the most used tool, so shortening it needs care that this
change does not take.

## What was not done

- **No model A/B.** The [delegation note](../project/DELEGATION.md#33-the-mcp-tool-surface)
  proposed testing a core set against the full set on the F2 tasks before
  changing the default. Delegation was not adopted (2026-11-25), and the
  maintainer decided on removal directly, so no paid runs were made. The cut most
  likely to cost success, folding `click`, `type` and `key` into `desktop_actions`,
  was not made.
- **Benchmark comparability.** The October tool-profile runs had separate
  `ui_action`, `move`, `drag`, `scroll` and `focus` tools. Rerunning them now tests a
  different surface. `--tools basic`, which has no `desktop_actions`, no longer
  has any way to send those inputs.
- **Watch at the next usage review.** Check that agents find the `move`, `drag`, `scroll`
  and `focus` steps (a failed attempt to call a removed tool shows up as a tool
  error), and whether `desktop_ui` is now chosen for native applications.
