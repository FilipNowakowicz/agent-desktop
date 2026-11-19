# Canvas materials crawl: MCP field report

2026-11-12. A real authenticated, read-only collection task using the current
local Agent Desktop MCP server. No runtime implementation changed. This report
contains aggregate measurements and generic routes, not account identifiers,
course titles, filenames, signed URLs, cookies or course content.

## Task and verified outcome

Collect study materials for four specified mathematics courses, including their
past papers, while keeping the person's screen undisturbed. A Claude Code agent
had imported the person's sign-in cookies into a named profile about twenty minutes
earlier. It had started this download in a headless session and stopped when its
context ran out, leaving the session running (see the
[coursework report](2026-11-19-coursework-and-shell-tests.md)). Codex found that
session idle with its controller lease free, opened a fresh browser context in it
and carried on. The person later explicitly allowed closing it and discarding its
old tabs.

Downloaded **66 PDFs, 52,200,194 bytes**: 38 current-course resources and 28 exam
PDFs, seven years per subject. The publisher labels exam files as combined
questions and solutions; some also include comments. An assignment description
contained one lecture-note attachment that module File items alone would miss.

Each downloaded copy and library snapshot was reread and SHA-256 checked, matched
the API's expected byte count, and parsed to a positive page count. Four PDFs
produced producer/xref warnings; their original bytes were retained with warnings
in the private manifest. This verifies local receipt integrity, not mathematical
correctness or equality to an unavailable remote cryptographic hash.

Coverage is **66/66 discovered file IDs**, not a claim that unpublished or unlinked
materials do not exist. Subject file indexes denied listing; page indexes were
disabled. Published modules, assignment descriptions, referenced pages and the
four exact matching folders in a separate exam repository supplied the scope.
All 21 subject modules had complete item arrays; each matched exam folder's
reported count equalled its returned seven files and the download receipts.
Videos/transcripts were outside this collection's initial scope.

The session was destroyed after completion. `desktop_profiles` then showed its
saved profile no longer in use. No host input, cookie export, password access,
login takeover, assignment submission or site-content mutation was used. There
were no requested human handoffs; one unsolicited clarification permitted cleanup.
Login validity after a later session restart was not separately tested.

## How the MCP was used

The local server was not registered in this agent client's directly exposed tool
set. The official Python MCP SDK connected over stdio with:

```sh
uv --directory /path/to/agent-desktop run agent-desktop-mcp
```

A persistent SDK connection retained the controller identity across calls. A
private filesystem request queue let the client invoke tools incrementally and
record each result. This adapter was host-side task glue, not a new server feature.
The server's initialization instructions and all tool schemas were read. No
unsupported evaluation API or second browser automation connection was used.

The browser workflow used only the public `desktop_browser` surface:

1. Inspect saved profiles, sessions, status and tabs; verify the session is headless
   and its lease is available before acting.
2. Navigate the existing authenticated Firefox context to an authorized JSON
   endpoint. Wait for Firefox's JSON viewer, select Raw Data, then `send` its
   `pre.data` text to a new private file with `reveal=0`.
3. Batch those four steps in one `desktop_browser(action="steps")` request. Parse
   the saved JSON locally and follow only the requested course/resource links.
4. Read individual metadata for published files. Navigate their canonical
   authenticated download URLs, then independently observe the profile's Downloads
   directory until an unambiguous complete file matches the expected byte count.
5. Copy and hash the files, validate PDF structure, register immutable local
   library snapshots and compare discovered IDs with final receipt IDs.
6. Destroy the explicitly authorized session; verify the profile is released.

No cookies were copied into a shell HTTP client. Canvas requests and redirects
used the signed-in browser. PDF bytes were not embedded in MCP responses.
Private API snapshots can contain signed file URLs and were kept outside Git.

## Measurements from this run

These are measurements from the client-side MCP call ledger, scoped to this task.
The existing session's older activity was excluded. Initialization and list-tools
protocol requests are not counted as tool calls. Latencies run from call dispatch
to tool response; they exclude model reasoning, filesystem polling, PDF validation
and adapter startup. This is one task, not a comparative benchmark.

| Measurement | Observed |
| --- | ---: |
| MCP tool calls | 173 |
| Distinct tools used / exposed | 5 / 29 |
| `desktop_browser` | 168 |
| `desktop_profiles` | 2 |
| `desktop_list` / `desktop_status` / `desktop_destroy` | 1 / 1 / 1 |
| Browser batches | 96 |
| Primitive batch steps requested / completed | 384 / 382 |
| Standalone browser opens | 67 |
| Standalone find / click / send / tabs | 2 / 1 / 1 / 1 |
| Selector waits inside batches | 96 |
| Fixed-duration browser waits | 0 |
| Screenshot / coordinate / accessibility calls | 0 / 0 / 0 |
| MCP error replies | 0 |
| Semantically stopped batches | 2 |
| Reported uncertain-delivery / observation-error fields | 0 / 0 |
| Summed MCP call time | 111.847 seconds |
| Median / p95 / maximum call latency | 0.428 / 1.170 / 1.814 seconds |
| Serialized tool response bytes | 190,597 |
| Serialized tool-list JSON bytes | 33,842 |

The 67 standalone opens include 66 attachment-download navigations and the initial
course-list navigation. The 96 batched opens were JSON navigations. Those counts
are browser actions, not network-request counts: redirects and subresources were
not measured. Response/schema byte counts are not token counts.

`isError=false` did not mean the study task succeeded. Two batches stopped during
export, and nine saved API responses contained unauthorized JSON. Six index
responses said the page was disabled; five front-page responses said no front
page was set. The client checked those bodies and final file receipts separately.

## Friction and concrete follow-ups

### 1. A download needs its own completion contract

For an attachment, `open` reported `delivered=true` while returning the prior
JSON document's URL/title. The download had started correctly, but the DOM had
not navigated. Treating the returned URL as proof of failure would cause needless
retries; treating `delivered=true` as proof of completion would be false success.

The workaround took a before/after filesystem inventory, excluded `.part` files,
waited for stable size, matched the expected byte count, and hashed the complete
file. These host-side checks succeeded but required knowing the session download
location and writing a task adapter. The MCP offered no supported download receipt.

Proposed generic capability: an authenticated browser download to an explicit
private destination, with operation ID, started/pending/complete/failed state,
final name, MIME, byte count and SHA-256. Keep temporary output separate and publish
it atomically. Interrupted or cancelled transfers must not return complete. Redact
signed URLs/query credentials in replies. Tests should include a slow stream,
redirect, duplicate filename, HTML login response and interrupted transfer.

### 2. Large data export should be distinct from secret transfer

`send` was useful: it saved full JSON without sending metadata bodies through the
model. However, two 100-item listings stopped with “The value is longer than 65536
bytes.” The top-level MCP reply was not an error; the batch's `stopped` field was
the important signal. Retrying the same large request would not solve it.

The workaround requested 20 items per page and traversed only the relevant folder
subtree. It preserved complete results without bypassing the bound. Proposed
follow-up: a separate, bounded save/export operation with clear byte limits,
truncation/completeness metadata and large output kept in a file. Keep the secret
transport's existing protection and minimal disclosure. Test Unicode byte lengths,
limit refusal without partial publication, and datasets larger than 64 KiB.

### 3. A read-only authenticated GET could remove viewer-specific glue

A JSON read needed navigation, a selector wait, a Raw Data click and an export.
This worked through existing tools, including disabled-index/permission-error
responses, but depended on Firefox JSON-viewer selectors. The browser surface did
not expose HTTP status, response headers or pagination Link headers, so coverage
was checked against item arrays and known folder counts instead.

A proposed origin-scoped read-only GET, executed within the authorized browser
identity, could save response bytes and expose status, content type, byte count
and safe pagination metadata. It must retain normal server authorization, avoid
exporting cookies/tokens, preserve clear target identity, and explicitly flag a
login redirect or non-JSON response. This is a proposed maintainer decision, not
an implementation or an automatic change to the parked internal-endpoint work.

### 4. Make aggregate task evidence available without copying private traces

The CLI's activity summary covers the session, which already contained earlier
work. A task/run boundary would make this run's action counts and latency easier
to obtain without a custom SDK ledger. Include business-level stopped batches and
unknown outcomes, not just protocol exceptions. Associate transfer receipts with
the run. Export only counts and sanitized error categories by default.

### 5. Integration and tool-surface observations

The SDK route worked, and the existing named profile removed the login handoff.
But discovering and bridging a server absent from the client's registered tools
added setup work. A documented incremental SDK client or client-specific setup
check would reduce that friction. Only five of 29 tools were used here; that is
call coverage, not evidence that other desktop tools should be removed. A
browser-task tool subset may be worth measuring on more tasks before changing the
interface. No token, cost or model-performance comparison was run.

## Reproduction and remaining limits

The private task directory in the study project contains source metadata,
provenance, per-file hashes, completeness checks, call request/results and a
sanitized aggregate usage summary. Raw traces and saved helpers are intentionally
not copied into this public repository. The saved helpers include run-specific
paths/context IDs and require adaptation before reuse.

The browser completed the authorized task without visible desktop interaction.
That does not test physical input, compositor rendering, accessibility actions,
login recovery or browser crash recovery. API denials were respected; no hidden
file IDs were guessed. An initial host-side category heuristic misread a mixed
problems/solutions module; an independent filename audit corrected four metadata
records, preserving source bytes and stable IDs. A host-script import-path mistake
was also corrected. Neither is counted as an MCP failure.

No runtime patches, source-material publication or changes to the project
direction were made as part of this report.

## Follow-up status (2026-11-19)

The [coursework report](2026-11-19-coursework-and-shell-tests.md) saw the same
download and export friction in two more projects. Download receipts (1), a
separate data export (2) and a supported cookie route for shell downloads were
taken up as follow-up pull requests. The authenticated GET (3) is still a
maintainer decision.
