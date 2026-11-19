# Coursework and shell-testing field report, 2026-11-10 to 2026-11-18

This follows the [cloud setup field report](2026-11-08-gcp-tailscale-setup.md), which
covered sessions up to 2026-11-09, and the
[Canvas collection report](2026-11-12-canvas-materials-crawl.md), which covered one
Codex download run on 2026-11-12. Since then the maintainer kept using Agent Desktop
from Claude Code in four repositories without asking for a report: two study projects
(a flashcard generator and a lecture-notes project), the NixOS configuration repository
and this repository.

This was reconstructed from the Claude Code transcripts, with each tool call counted
once (transcripts continued after compaction repeat earlier calls, and those repeats were
removed). Totals were cross-checked with `agent-desktop activity --days 8`. Course names,
the institution, account identifiers, cookie values and file names are left out. This is a
dated record; problems are listed as they stood at `2a5fa3c`.

## What the work was

| When (UTC) | Project | MCP calls | What the agent did |
| --- | --- | ---: | --- |
| 11-10 23:01–23:15 | NixOS config | 3 | Ran a nested-shell test while fixing a CI failure. The GPU create failed, so the session came from the CLI |
| 11-12 14:20–14:24 | this repo | 22 | One approved host session, to check four features on the real screen: waiting for animations before a screenshot, opening a URL in the person's Firefox, Dvorak key placement and refusing input while the person typed elsewhere. It opened two of its own terminals and closed only those |
| 11-12 15:25 | this repo | 2 | A scripted check of the new hook-based host approval prompt |
| 11-12 20:40–20:44 | flashcards | 20 | Imported the person's university and Microsoft sign-in cookies (on request: "can you just grab my cookies?"), confirmed Canvas loaded signed in, and listed the courses and modules. Then it started the downloads that Codex finished in the same session (see the Canvas report) |
| 11-13 01:01–02:07 | flashcards | 27 | Drove the native Anki app in two private sessions on the person's real Anki profile, as asked ("can you do the anki step on ur own with agent desktop"): turned on a scheduler option, checked the deck list, then tested card delivery end to end. It quit Anki properly both times so the collection saved |
| 11-16 16:25–18:58 | lecture notes | 37 | Started making a new profile for the lecture-recording site, then followed the person's suggestion and reused the `canvas` profile, since the same sign-in covers both sites. It found the lecture list, downloaded 18 caption files through the page, and new course files from Canvas |
| 11-16 21:46 | NixOS config | 1 + CLI | Rendered a PDF in zathura to check a theme change |
| 11-17 10:36–11:55 | NixOS config | 9 + CLI | Five nested Hyprland test runs of bar and overview changes, between rounds of the person's feedback |
| 11-18 00:23–00:28 | NixOS config | 15 | Screenshots of terminal themes and a system monitor, to compare replacements |
| 11-18 01:01 | NixOS config | 3 | Tested kitty remote control in a throwaway terminal before enabling it |
| 11-18 22:56–22:57 | lecture notes | 10 | Fetched the newest lecture's captions and checked which video formats it had |

Two uses stand out, as before: account-bound web work in the background (the study
projects) and throwaway desktops for testing desktop software (the NixOS repository).
The newest kind of use is a third one: **driving a native app on the person's own data**
in a private session (Anki), which had not come up in earlier reports.

## Statistics

| | Web (study projects) | Native app (Anki) | Shell and app tests | Host and hook checks |
| --- | ---: | ---: | ---: | ---: |
| MCP calls | 67 | 27 | 31 | 24 |
| Private sessions created | 9 | 2 | 4 (+ 7 from the CLI) | 0 |
| Host sessions | 0 | 0 | 0 | 1 |
| Tool errors | 2 | 0 | 3 failed GPU creates | 1 (a hook's answer, see below) |
| Human handoffs | 1 requested, withdrawn after 1 min | 0 | 0 | 0 |

In total that is 149 MCP calls across 10 transcripts. `agent-desktop activity` reports
25 sessions and 293 calls between 11-11 and 11-18. The difference is the Codex crawl,
whose 173 calls were made through the Python SDK and are not in any Claude Code transcript.

| Tool | Calls | | `desktop_browser` step | Count |
| --- | ---: | --- | --- | ---: |
| `desktop_browser` | 46 | | `open` | 83 |
| `desktop_create` | 17 | | `wait` | 90 |
| `desktop_launch` | 16 | | `send` | 13 |
| `desktop_destroy` | 15 | | `click` | 14 |
| `desktop_wait` | 12 | | `find` | 10 |
| `desktop_screenshot` | 11 | | `start` | 10 |
| `desktop_click` | 6 | | `text` | 8 |
| `desktop_key` | 5 | | | |
| other (11 tools) | 21 | | | |

| Habit | Observed |
| --- | --- |
| Browser calls that were `steps` batches | 32 of 46, averaging 6.7 steps; one hit the 30-step limit and was refused |
| Batches stopped early | 6: 4 unmet waits, 1 missing element, 1 `send` into a folder that did not exist |
| Waits in batches | 74 fixed, 16 for text or a selector. The cloud report found 81 and 17 |
| Coordinate input | 9 calls (6 clicks, 3 scrolls), all in Anki, 2 with an observation token, 9 with `screenshot=true` |
| Screenshots | 11, of which 8 were scaled to 0.5–0.6 |
| Session reuse across agents | Codex picked up the Canvas session Claude left running when its context ran out, and used it for two hours |
| Longest idle session | 2 h 5 min with the `canvas` profile held, while a video download in the shell failed on a DNS outage |

## What worked

- **Cookie import for a single sign-on site, done by the agent.** The person asked the
  agent to "grab my cookies". It ran `import-cookies` for the university's domain, saw
  that Canvas still redirected to Microsoft, added the Microsoft sign-in domain and was
  signed in. The import has lasted a week: a new session on 11-18 still got through
  sign-in without the person.
- **One profile for several sites behind the same sign-in.** The person pointed out that
  the `canvas` profile would also open the lecture-recording site. The agent withdrew the
  login request it had just made, deleted the empty `panopto` profile and saved a memory
  note so later sessions use `canvas`.
- **`send` kept listings out of the conversation.** Course lists and file indexes went
  straight to files (11 `send` steps in the first session), and the agent parsed them in
  the shell.
- **Native app work stayed in the background.** Anki ran on the person's real profile in a
  private session. The agent changed one setting, checked the result with a second dry
  run, and quit with Ctrl+Q so nothing was lost. The person kept working meanwhile.
- **Throwaway desktops for shell feedback loops.** In the NixOS repository each round of
  the person's feedback ("timer i would make it collapse with the waybar…") was followed
  by a new nested test run and screenshots, five times in one morning.
- **The host check was careful.** It listed windows first, worked on its own workspace,
  closed only the terminals it opened, and returned focus to the person's terminal.

## Problems

### The agent copied cookies out of the profile to use them in the shell

On 11-16 the lecture videos were too large for the browser route, so the agent wrote
its own exporter. It copied the profile's `cookies.sqlite`, then decoded Firefox's
session-restore file, because one sign-in cookie lives only there. It wrote a
Netscape `cookies.txt` for `yt-dlp` to the scratchpad, made it 0600 and deleted it
afterwards. On 11-18 it repeated this three times, with `sleep 5` and `sleep 15`
between attempts, because the session-restore file had not been written yet.

No cookie value reached the transcript, and the person's request ("fetch the lectures")
covered the result. But this is the route the cloud report warned about: agents editing
or reading Firefox databases by hand because no supported route exists, with credentials
in a file that Agent Desktop does not know about. The exporter now lives in the notes
project as a tool, so it will be reused.

### Profile Downloads used as a transfer folder

Caption files, PDFs and JSON listings landed in the profile's `Downloads` and home
folders. The agent then found them by polling with `ls -t` and `find -newer`, and moved
them away. It worked because only one download ran at a time. The Canvas report had the
same problem and proposed download receipts.

### GPU sessions still fail first

Three `desktop_create` calls asked for `renderer: gles2` and failed with
`EGL_EXT_platform_base not supported`, on 11-10, 11-17 and 11-18. The cause is the Mesa
mismatch that [USAGE.md](../USAGE.md) already describes. Each agent then retried without
the GPU or used the CLI, and went on. The `desktop_create` description tells agents
that "a compositor or shell under test usually needs gles2", without mentioning the
Mesa setup, so every new agent testing the shell tries it first.

### Small refusals that each cost a call

- `view-source:` URLs are refused as an unsupported navigation. The agent wanted raw JSON
  and moved to the JSON viewer's Raw Data tab, like Codex.
- `send` with `to_file` into a subfolder that did not exist stopped the batch. It does
  not create the folder.
- One batch of 31 downloads was refused by the 30-step limit before anything ran.
- After `desktop_destroy`, the agent called the old session id once more. The error was
  clear.
- A new session sometimes stopped on the sign-in page until the agent clicked "Sign in"
  (no password needed). Batches that waited for the page's text then timed out.

### A session held a profile while idle

On 11-16 the agent left the browser session open for two hours while the shell download
ran and failed, although it no longer needed the browser. Nothing else wanted the profile
that afternoon, but a second agent would have been refused. The lease expires after 60
seconds, so the session itself is the thing that lingers.

### A hook's answer reads like a tool error

The 11-12 scripted check tested the Claude Code hook from
[#196](https://github.com/FilipNowakowicz/agent-desktop/pull/196), which lets the
client's own prompt approve a host request. In that non-interactive run the hook
answered both calls: `desktop_status` returned a stub ("done"), and
`desktop_request_host` came back as an error whose text was the prompt itself ("An
agent asks to use your screen for 5 min: test"). The agent read this as "not granted"
and did not retry, which is safe. But it could not tell an unanswered prompt from a
refusal. This belongs to #196's hook, not the server.

### Tools nobody called

Across every Claude Code transcript still on disk (2026-10-23 to 2026-11-18, 520
deduplicated calls, so this includes the Hyprland and cloud reports' sessions), 10 of the
29 tools exposed by default were never called: `desktop_ui`, `desktop_ui_action`,
`desktop_atlas`, `desktop_effects`, `desktop_check`, `desktop_set`, `desktop_operation`,
`desktop_move`, `desktop_control` and `desktop_logs`. The opt-in `desktop_run` was not
enabled. Four tools (`desktop_browser`,
`launch`, `screenshot`, `destroy`) made up 69% of calls.

This is organic use by one person, so it is not grounds for removing anything. Benchmarks
call the accessibility tools, and `desktop_control` is needed after a handoff. But every
schema costs every agent context. The accessibility tools in particular were never chosen
for real work, even in Anki, where the agent clicked by coordinates instead.

### Transcripts expire

The oldest Claude Code transcript left on disk is from 2026-10-23. Earlier sessions,
including the pilot and the first host trial, survive only in their reports. Anything not
summarised within about 30 days is lost.

## What this suggests for development

1. **A supported way to give a shell command the profile's cookies.** For example,
   `desktop_browser send` with a `cookies` source for one site, written to a 0600 file or
   a command's stdin in Netscape format, returning only a count and a digest. It would
   replace the hand-written exporter and the `sleep` loops.
2. **Download receipts** (already proposed in the Canvas report): return each finished
   download's path, size and hash, so agents stop polling `Downloads`.
3. **Say up front when a GPU session will fail.** Check the EGL vendor setup in
   `desktop_create` and return the fix from USAGE.md, and qualify the "usually needs
   gles2" advice in the tool text.
4. **Release a profile from an idle session.** For example, an idle timeout for sessions
   with a profile, or a warning in `desktop_profiles` showing how long the holder has
   been idle.
5. **Smaller fixes:** create the folder for `send to_file`, and say in the 30-step error
   how many steps were sent. In #196, give an unanswered host prompt a result the
   agent can tell apart from a refusal.
6. **Review the tool surface with this data:** see whether the accessibility tools fail
   in Anki-like apps or are simply not discovered, and whether rarely used tools could
   be folded into others.
7. **Native apps on real data** deserve a sentence in USAGE.md: what a private session
   protects (the screen) and what it does not (the app's data folder), as the Anki run
   showed.

Across the three reports the pattern is stable: the browser bridge and private sessions
are reliable enough for daily use. The open problems are about moving data and
credentials between the browser and the shell.
