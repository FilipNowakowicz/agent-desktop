# Exchange research and lecture fetch field report, 2026-11-21 to 11-25

This follows the [VPN token and quota check report](2026-11-20-vpn-token-and-quota-check.md),
which covered use through 2026-11-20. Most use in this window came from a new
project: a research project looking for betting-exchange and market edges. Its agents
used Agent Desktop to read exchange fee and rules pages, to read and change settings in
the person's own exchange accounts, to add free historical data to an account, and,
from subagents, to read regulator and fund documents for citations. The lecture-notes
and flashcard projects fetched lecture captions and course listings, as before.

It was reconstructed with `scripts/usage_review.py --since 2026-11-20` and
`agent-desktop activity --days 5`, following the [usage review workflow](../project/USAGE_REVIEW.md).
The script found 243 calls in 11 transcripts. 16 of them, in one transcript, are from
11-19 and 11-20 and were already covered by the previous report, so this report is about
the other 227 calls in 10 transcripts. Account names, sites' internal identifiers,
balances, course names and cookie values are left out. This is a dated record. The
problems are described as they stood at `40c185b`. All fixes from the previous report
had landed by 11-20 20:43, before the first use in this window.

## What the work was

| When (UTC) | Project | MCP calls | What the agent did |
| --- | --- | ---: | --- |
| 11-21 00:33–00:41 | Exchange research | 26 | Read public fee pages on three exchanges, then, at the person's request, read the account's rewards plan and the developer pages through an imported login |
| 11-21 12:26–14:19 | Exchange research | 68 | Changed the account's rewards plan as the person asked. Asked the person to log in to a second exchange, which they couldn't do in the private browser. Imported that login from their Firefox instead and looked for the account's commission rate. Added free historical data to the first account, after checking that the basket total was zero. Exported the site's cookies for a shell downloader |
| 11-22 01:37 | Exchange research | 5 | Saved a public fee page to a project file in one call |
| 11-22 16:25–16:38 (subagent) | Exchange research | 16 | Searched a national gambling-domain register for 9 operators in two batches, and read broker and bookmaker fee pages |
| 11-22 21:56–22:08 (subagents) | Exchange research | 33 | Read a regulator's handbook section and a 200-page fund prospectus for a desk check. A third subagent gave up on exchange rules pages behind a bot check |
| 11-23 22:55–23:53 | Exchange research | 37 | Asked the person twice to sign in to the historical data portal. Both logins were lost when control came back, so the agent imported the login from their Firefox, added more free data and exported cookies for the downloader |
| 11-24 04:30–04:34 | Exchange research | 16 | Tried the exchange rules pages again. The bot check never cleared |
| 11-24 02:33, 11-25 03:24 | Lecture notes | 11 | `/lecture` runs: found the newest recording and downloaded its captions in one `download` call each |
| 11-24 02:35–02:42 | Flashcards | 15 | Synced course modules, assignments and syllabi through the learning platform's API in 16-step batches. The person re-imported an expired login partway through |

The exchange research use is a new kind: an agent working with the person's own
financial accounts, reading settings and making small changes the person asked for. Its
subagents also used the private browser as a general reader for public sources that
plain HTTP fetching couldn't handle.

## Statistics

| | Value |
| --- | ---: |
| MCP calls (new uses) | 227: `desktop_browser` 175, `create` 15, `destroy` 14, `key` 8, `control` 5, `type` 3, `screenshot` 3, `request_human` 3, `profiles` 1 |
| Private sessions | 15 created in transcripts. `activity` reports 16 sessions and 211 worker operations from 11-21 to 11-25. The extra session is probably a timed `/lecture` run with no transcript |
| Profiles | An exchange profile (7 sessions, holding logins for two exchanges), the learning-platform profile (4 sessions), 4 sessions without a profile |
| Browser batches | 96 in `activity`. 14 stopped early: 7 missing elements, 2 unmet waits, 1 ambiguous match, 1 lost tab, 3 others |
| Waits in batches | 116 fixed and 36 for a condition. That's 76% fixed, down from 82% in the last two reports |
| Screenshots | 8 in `activity`. 2 were scaled and 1 cropped. 5 came with `desktop_key` (`screenshot=true`) while searching a PDF |
| Input calls | 11 (`key`, `type`), all into Firefox's PDF viewer. None used coordinates |
| Tool errors | 4: a 32-step batch, a PDF the browser showed instead of downloading, a page-script error during a `wait`, and a call with the placeholder session id `"pending"` |
| Human handoffs | 3 login requests, and none of them worked (see below). All three logins were done by importing cookies instead |
| Account changes | One rewards-plan switch and three free data orders, all asked for by the person. The agent checked the basket total before confirming and the balance afterwards |

## What worked

- **Named covers.** A cookie banner blocked a click. The refusal now names the banner's
  role and the start of its text ([#221](https://github.com/FilipNowakowicz/agent-desktop/pull/221)),
  so the agent clicked "Accept All" in the next call, without a screenshot. Last time
  the same refusal cost a screenshot.
- **Session-only logins import.** [#220](https://github.com/FilipNowakowicz/agent-desktop/pull/220)
  was used five times. Twice it brought across a login that was only in Firefox's session
  store (one session cookie each time). Both times it was the route that finally worked
  after a failed handoff.
- **Download receipts.** The two `/lecture` runs took 5 and 6 calls each: create, start,
  wait for the recording's title, `download`, destroy. The receipt gave the file
  path directly, and neither run polled the Downloads folder ([#204](https://github.com/FilipNowakowicz/agent-desktop/pull/204)).
- **`save` for large text.** It was used 51 times: exchange terms, a 57 KB fee page saved
  straight into the project, API JSON through "Raw Data" and `pre`, and pages of a
  prospectus. The agents read the files with `grep` instead of putting long pages in the
  conversation.
- **Careful account actions.** Before each data order, the agent read the basket and
  confirmed only when it showed £0.00. Afterwards it checked that the balance hadn't
  changed. It made the plan switch only after the person said "you can do it if you can".
- **Long batches.** A subagent ran 16 fill/click/wait/text steps per call to check 9
  operator names in a public register. The 30-step limit was hit once, and the
  agent split the batch in its next call.
- **Fewer fixed waits.** 76% of waits were fixed pauses, down from 82%. The lecture
  runs and the subagents mostly waited for text or a selector.

## Problems

### A login handoff loses the login when control comes back

On 11-23 the agent asked the person to sign in to the historical data portal with
`desktop_request_human` (`login=true`). The person ran `take --paste`, signed in, and
released. `desktop_control` reported `browser.restarted: true`, and the page showed
"Login" again. The agent asked a second time, with a note to tick "Remember me". The
person signed in again, and the login was lost again. About 50 minutes after the first
request, the person said they were also signed in in their own Firefox. The agent
destroyed the session and ran `import-cookies`, which brought across the login,
including one session-only cookie. That worked straight away.

When the person releases control, `restore_bridge` in `worker.py` quits the plain
Firefox that the person used and starts it again under WebDriver BiDi. Firefox drops
session-only cookies when it quits. A site whose login is a session cookie, as this
one's is, is signed out by the restart. That is probably what happened, though there
was no screenshot of the signed-in state to confirm it. The "Remember me" advice in the
server instructions can't help where the site has no such box, or where the box doesn't
make the cookie persistent.

On 11-21 the person also couldn't log in to the second exchange in the private browser.
The transcript doesn't say why. The import from their Firefox worked there as well.

This is the most costly finding. The person did a login twice, and the agent waited
almost an hour, for nothing.

### Bot-check pages stop agents, and `wait` can't see them

One exchange's help site showed a bot-protection challenge ("Performing security
verification", with the title "Just a moment...") in five sessions on four days. Agents
waited 15 to 60 seconds, reopened the page and searched for text. None of them noticed
the challenge from the replies alone, and none asked the person for help or offered
their own browser. On 11-24 the agent waited for "Just a moment" with `gone: true`.
The wait was satisfied at once, because that text is only in the page title, which
`find` doesn't search. The page was still the challenge.

### Saved files and downloads stay in the profile

`save`, `send` and `download` resolve a relative `to_file` in the session home. For a
session with a profile, that's the profile's own home, which persists across
sessions. The exchange agent saved 15 pages of account and terms text there, read them
with `grep` and `sed`, and then had to remember to delete them by hand. The lecture
runs moved their captions out of the profile's `~/Downloads`. That caused 30 of the
script's "profile files" and "session state" flags. None of them were the cookie-file
handling that earlier reports warned about. The tool text doesn't say that relative
paths land in a persistent profile.

### PDFs that Firefox displays can't be downloaded

A subagent asked `download` for a fund prospectus. Firefox opened it in its built-in PDF
viewer, and the tool correctly refused ("opened a page instead of a download"). The
agent then read it by opening `#page=N` URLs and saving each one. It also searched
inside the viewer with `ctrl+f`, `type`, Return and `screenshot=true`: about 20 calls in
all. In the end it imported the PDF with its own project tool over plain HTTP. The
refusal doesn't suggest a route, and `download` has no way to save a PDF that Firefox
would display.

### A `wait` with `within` failed while the page loaded

A `/lecture` run called `wait` with `within` straight after `start`. The page script
failed with `document.body is null`, and the call returned an error instead of
waiting. The page script reads `document.body` for `within` before the page has a body.
The agent retried without `within` and went on.

### Exported cookies are kept in the project

For multi-hour historical data downloads, the agent exported the exchange's cookies
with `send` (`source="cookies"`) and moved the file into the project's gitignored
`secrets/` folder (0600). On 11-23 it wrote the file there directly for the next
download. That follows the tool's rules on mode and output, but not "delete the file
when done". A login copy now lives outside the profile for as long as the downloader
needs it. Nothing in the tool covers a long-running shell download.

### Small costs

- **A month picker.** The data portal's date picker accepts no typed dates. Agents
  clicked "Previous Year" up to 16 times per batch, and three batches stopped when
  the button disappeared at the earliest year. That's the page, not the tool.
- **Placeholder session id.** Once, the agent called `desktop_browser` with
  `session: "pending"` in parallel with the `desktop_create` call. The error was clear,
  and it recovered in the next call.
- **Profile held while waiting.** On 11-21 the exchange profile stayed held for 81
  minutes, waiting for a handoff the person never completed, while the agent worked on
  other things. One session was left running at the end of that conversation. The next
  `desktop_create` reported it as abandoned and went on without trouble.
- **One profile for two exchanges.** The agent imported the second exchange's login
  into the first exchange's profile. Nobody set a profile note ([#218](https://github.com/FilipNowakowicz/agent-desktop/pull/218)).

## Since the last report

| Last report's suggestion | Status |
| --- | --- |
| Keep secrets out of `find` and `wait` | **Fixed** ([#221](https://github.com/FilipNowakowicz/agent-desktop/pull/221)). No generated secret was handled in this window, so it wasn't tested in use |
| Make `forget-site` known, no hand edits of cookies | Tool text updated ([#221](https://github.com/FilipNowakowicz/agent-desktop/pull/221)). No agent touched a profile's cookie files in this window |
| Say what's covering an element | **Fixed and confirmed** (above) |
| Point browser `key` attempts to `desktop_key` | Fixed ([#221](https://github.com/FilipNowakowicz/agent-desktop/pull/221)). It didn't come up again, and the agent used `desktop_key` directly |
| Session-only cookies in `import-cookies` | **Fixed and used** ([#220](https://github.com/FilipNowakowicz/agent-desktop/pull/220)) |
| Record a profile's signed-in account | Landed ([#218](https://github.com/FilipNowakowicz/agent-desktop/pull/218)). Not used yet |
| Fixed waits | Better: 76% against 82% |
| Hook result looks like an error | Not exercised: no host requests in this window |
| Tool surface review | Unchanged. 21 tools weren't called in this window |

## What this suggests for development

1. **Keep a handoff's login through the restart.** In `restore_bridge`, after the plain
   Firefox quits cleanly (which writes `sessionstore.jsonlz4`), convert the session's
   own session-only cookies into persistent ones that expire after 24 hours, as
   `import-cookies` already does, before starting the BiDi Firefox. Report how many
   were kept in `desktop_control`'s `last.browser`. This changes how long a login made
   in a handoff lasts in the profile, so it needs a decision, but it matches the policy
   already accepted for imports.
2. **Recognise challenge pages.** When a page's title or body matches a known bot-check
   interstitial, add `challenge: true` and a hint to the `open`, `text`, `find` and
   `wait` replies: the person can solve it in a handoff, or the task can use their own
   browser. Let `gone` waits also check the title, or say in the tool text that `find`
   doesn't search it.
3. **Say where relative files go.** In the `save`, `send` and `download` text, say that
   in a profile session a relative `to_file` is in the profile and stays there, and
   suggest an absolute path in the agent's own scratch folder. Also make
   `usage_review.py` stop flagging reads of paths that a tool reply returned.
4. **Fix the `within` page-script error.** Treat a missing `document.body` as "not
   found yet", so `wait` keeps polling.
5. **PDFs Firefox displays** (needs a design). Let `download` save the original file
   when the URL opens the PDF viewer, or at least have the refusal point to
   `send source="cookies"` with `curl`.
6. **Long-lived cookie exports** (needs a decision). Either accept a gitignored 0600
   file for a long shell download and say so in the tool text, or offer a way for
   `download` to run large files in the background so no cookie file is needed.
