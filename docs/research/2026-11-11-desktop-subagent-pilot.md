# Desktop subagent pilot (N10), 2026-11-11

The [protocol](2026-11-11-desktop-subagent-protocol.md) planned 42 runs. On the
maintainer's instruction to keep the model budget small and grow it only if early
runs raised questions, a four-run pilot was run first. Its result is clear on the
gate, so the full run was not started.

## Deviations from the protocol

- Two tasks, one seed (1), one run per arm. The protocol asked for seven tasks and
  three seeds.
- The tasks were `hard-web-admin` and `real-inventory-cleanup`. The other E0 tasks need
  Mousepad, which was not installed. Chromium 156 was taken from the Nix store for the
  run without being installed.
- Arms ran one after the other on one machine, direct first.

## How the arm works

The main agent gets only the Task tool and no MCP server (`--strict-mcp-config` with no
`--mcp-config`). The desktop agent, from `benchmarks/agents/desktop.json` on `haiku`,
gets its own copy of the MCP server through the agent definition's `mcpServers` and the
run profile's tool set. A smoke run confirmed this: the main agent's init listed only
`Task` and no MCP server, and the `desktop_list` call came from the subagent
(`parent_tool_use_id` set). Main-context tokens are the plain, cache-read and
cache-created input tokens of the main agent's own messages.

## Results

| Task | Arm | Passed | Wall s | Main-context tokens | Cost USD | Main turns | Tool calls |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| hard-web-admin | direct | yes | 35.8 | 230,338 | 0.269 | 12 | 11 |
| hard-web-admin | subagent | yes | 54.1 | 17,228 | 0.067 | 2 | 27 |
| real-inventory-cleanup | direct | yes | 67.9 | 518,367 | 0.405 | 21 | 20 |
| real-inventory-cleanup | subagent | yes | 107.1 | 17,388 | 0.091 | 2 | 53 |

The four runs cost $0.83, plus $0.08 for the smoke run.

## Against the gate

- Main-context tokens fell 93% and 97%, against a gate of −50%: met.
- Success was equal: met.
- Wall time rose 51% and 58%, against a limit of +10%: **not met.**

So the subagent is not adopted as the default. On `haiku`, the subagent made two to
three times as many tool calls, and that accounts for the extra time. Cost fell by about
75%, because most of the work moved to the cheaper model.

## What this suggests

The context and cost savings are large and consistent. Where wall time matters less
than the main agent's context, as with long coding sessions that use the desktop in
short bursts, the subagent is worth offering as an option rather than as the default.
The obvious next arm is the same subagent on the main agent's model. It would show
whether the extra time comes from the cheaper model or from the delegation itself. That
arm is not run here.

## Same-model arm (2026-11-12)

The maintainer asked for more testing on a small budget, raised only if the first
runs left a question. The arm the pilot suggested was run: the same definition with
`"model": "opus"` (`benchmarks/agents/desktop-same-model.json`, otherwise identical),
on the same two tasks and seed. Because its result was unexpected, the direct arm was
rerun straight after it, to rule out drift since the pilot. Both ran on the same
machine with an idle Fedora VM in the background.

| Task | Arm | Passed | Wall s | Main-context tokens | Cost USD | Tool calls |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| hard-web-admin | direct (rerun) | yes | 36.1 | 230,663 | 0.270 | 11 |
| hard-web-admin | subagent, opus | yes | 76.0 | 17,833 | 0.464 | 18 |
| real-inventory-cleanup | direct (rerun) | yes | 60.1 | 549,154 | 0.369 | 20 |
| real-inventory-cleanup | subagent, opus | yes | 117.9 | 18,215 | 0.592 | 29 |

The four runs cost $1.70. The direct rerun matches the pilot (35.8 s and 67.9 s), so
the comparison holds.

- The same-model subagent was **slower** than the `haiku` one (+111% and +96% wall
  time against direct, where `haiku` was +51% and +58%), and cost 60–72% more than
  direct, where `haiku` saved about 75%. Main-context tokens fell 92–97%, as before.
- So the extra time comes from delegation, not from the cheaper model: `haiku`
  made more calls but answered faster.
- Where the time went, in the `hard-web-admin` run: 66.3 s of model time, 7.8 s in
  tools. The subagent started by rediscovering the setup (`desktop_browser`, which
  does not apply to Chromium, then `desktop_windows` and `desktop_focus`) where the
  direct agent took a screenshot. The main agent's hand-off also asked it to note
  every user's role before editing and check them all after, which the direct agent
  did not do. The delegation itself adds turns.

Conclusion: the `haiku` subagent is the better variant, and neither meets the wall-time
gate. Keep direct tools as the default. The `haiku` subagent stays worth offering as
an opt-in for long sessions where the main context matters more than speed. A
further arm would have to remove the rediscovery and extra verification, for
example by giving the subagent the open applications in its hand-off. That is not
run here.
