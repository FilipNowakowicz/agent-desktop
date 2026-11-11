# Desktop subagent A/B: protocol (N10, fixed before any counted run)

Date: 2026-11-11. This was committed before any counted run. Nothing below changes
after results are seen, and any deviation is reported as one. The question comes from
big-directions candidate B1: does holding the desktop tools in a subagent keep
screenshots, DOM dumps and tool schemas out of the main agent's context, without
making tasks slower or less successful?

## Side measurement (done, no model)

Character counts of the MCP tool list (`name`, `description`, `inputSchema` as JSON)
and of the server instructions:

| Revision | Tools | Schema characters | Instruction characters |
| --- | ---: | ---: | ---: |
| `6872f38` (before the 2026-11-11 batch) | 29 | 29,290 | 2,886 |
| `9cd873f` (secret sink) | 29 | 30,373 | 3,100 |
| `e5f5883` (after #166–#175) | 29 | 31,436 | 3,158 |

That is about 7,900 tokens at four characters per token. The largest tools are
`desktop_browser` (4,740), `desktop_actions` (2,823) and `desktop_wait` (2,737). The
Hyprland field report used 11 of the 29 tools and the cloud report used 10. Tokens
were estimated, not counted by a tokenizer.

## Arms

- **Direct (control):** the current benchmark command (`scripts/benchmark.py`
  `run_agent`), with the main agent holding the desktop tools.
- **Subagent:** the main agent has no `mcp__agent-desktop__*` tools. It gets a
  `desktop` agent through `--agents`, holding only those tools and the server
  instructions, on `haiku`. The subagent returns a short result and the paths of any
  evidence. The definition is `benchmarks/agents/desktop.json`, committed with this
  protocol and unchanged between runs. Its prompt embeds the server instructions as
  they were at commit time.
- **Same in both arms:** main model (the CLI default), prompts and task code. Both
  arms have the same budget of $1 per run.

## Tasks and runs

- The six E0 realistic tasks (`benchmarks/realistic.py`) and `hard-web-admin`
  (`benchmarks/hard.py`), as the console-style task.
- **n = 3 seeds per task per arm: 42 runs.** The two arms are interleaved per task
  and seed, in a fixed order, so load drift affects both equally.
- No real accounts, no host session; `desktop_request_human` and `desktop_control`
  are disabled as in every benchmark profile.

## Measures

- **Main-context input tokens:** the sum of `usage.input_tokens`,
  `cache_read_input_tokens` and `cache_creation_input_tokens` over the main agent's
  turns. Subagent turns are excluded, identified by their `parent_tool_use_id`.
- **Wall time** and **success**, from the task's own independent judge.
- Also reported: total tokens including the subagent, turns, and subagent calls.

## Gate

Adopt the subagent if median main-context tokens fall at least 50% at equal success
(no more than one fewer task solved over the 21 pairs), with median wall time no
more than 10% worse. Otherwise record the result and keep direct tools. Either way,
the result goes to `docs/research/` and the directions board.

## Status

The protocol and definition are committed, and no counted run has happened. The run
needs about 42 agent sessions on the maintainer's subscription, so it waits for an
agreed budget (FUNCTIONALITY_ROADMAP.md, "agreed model budget").
