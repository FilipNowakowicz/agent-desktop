# Usage review

How real use of Agent Desktop becomes a public record and a list of improvements. The
maintainer's own agents use the MCP server in other projects without being asked to
report. Their transcripts are the best evidence of what people delegate, where the tools
get in the way and what agents do instead. Claude Code deletes transcripts after about
30 days, so a review should run at least every two to three weeks.

The output is:

1. a dated field report in [`docs/trials/`](../trials/) (counts, what worked, problems,
   suggestions);
2. updated rows and coverage in [`docs/USE_CASES.md`](../USE_CASES.md);
3. issues or pull requests for the improvements the maintainer agrees to;
4. a development log entry.

Agents can follow the `usage-review` skill in `.claude/skills/`, which follows this page.

## 1. Collect

Start from the "Reviewed through" date in USE_CASES.md:

```sh
uv run python scripts/usage_review.py --since 2026-11-18
uv run agent-desktop activity --days 21
```

The script writes a private folder (default
`~/.local/state/agent-desktop/usage-review/<today>/`, mode 0700, refused inside the
repository) with `summary.md`, `summary.json` and one timeline per transcript. Each call
is counted once, even when compaction or a forked transcript repeats it. Check the
total against `activity`. Calls made through an SDK bridge appear in `activity` but in no
transcript (the shell flag `mcp bridge` points at them).

## 2. Read the flags

`summary.md` lists moments to read in the timelines and, where needed, the transcript
itself:

| Flag | What to look for |
| --- | --- |
| `shell: profile internals`, `profile files` | The agent read or copied a profile's cookies, session files or downloads by hand. Usually a missing feature, and a credential-handling problem |
| `shell: cli`, `mcp bridge` | Work done beside the MCP tools. Why was the tool not enough? |
| `tool error`, `batch stopped` | Was the message clear? Did the agent recover in one call? Is the limit right? |
| `repeated after error` | An identical retry: the error did not say what to change |
| `call after destroy`, `left running`, `idle session` | Session lifetime: leaks, profiles held while idle, sessions handed between agents |
| `person's remark` | The person's words near a desktop call. Corrections, complaints and redirections are the strongest signal |
| `tools not called` | Tools nobody chose. Is a tool unknown, unhelpful or unneeded? Check benchmarks before suggesting removal |

The totals also show habits worth tracking between reports: fixed waits against
waits for a condition, coordinate input with and without an observation token,
unscaled screenshots and failed GPU creates. Compare them with the previous report, so a
fix shows up as a change in behaviour, and a problem that comes back is called out.

## 3. Write

- **Field report:** follow the existing reports. Include the period, the method (as above),
  a table of what the work was, statistics, what worked, problems and suggestions,
  most valuable first. Say which problems from earlier reports are fixed, unchanged or
  back.
- **USE_CASES.md:** add a row for a new kind of use, update "How well it works" and the
  report links for existing ones, add the coverage row and move "Reviewed through".
- **Development log:** the counts, the main findings and that no tests were run, if none were.

Privacy, since the repository is public: no account names, addresses, course or company
names, file names, URLs with identifiers, cookie names or values, tokens, or quotes that
identify someone else. Quote the person only when it explains a finding, and keep it short.
Paths in reports use `~` or a generic form. Raw output from the review folder is never
committed.

## 4. Turn findings into work

For each suggestion, check open issues, pull requests and earlier reports first. Then:

- small, clear fixes (wrong text, a missing hint, a limit's message) go into one pull
  request;
- features get their own pull request, or an issue if they need a maintainer decision;
- removing or merging tools, and anything touching safety rules, needs the maintainer's
  decision.

Opening issues and pull requests is public, so propose the list to the maintainer before
filing it. Link the report's suggestions to the resulting pull requests in a follow-up
note in the report.
