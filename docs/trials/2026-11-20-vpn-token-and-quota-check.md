# VPN token and quota check field report, 2026-11-19 to 11-20

This follows the [coursework and shell-testing report](2026-11-19-coursework-and-shell-tests.md),
which covered use through 2026-11-18. Since then there was one real use, in the NixOS
configuration repository, plus two scripted hook checks. The agent was building a
cloud VM to take CPU-heavy jobs off the laptop. It used Agent Desktop twice: to make a
temporary API token in the VPN provider's admin console, and later to see why a cloud
CPU quota request had been denied.

It was reconstructed with `scripts/usage_review.py --since 2026-11-18` and
`agent-desktop activity --days 3`, following the [usage review workflow](../project/USAGE_REVIEW.md).
The script found 83 calls in 6 transcripts. 28 of those calls, in 3 transcripts, are from
11-18 and were already covered by the previous report, so this report is about the
other 55. Account names, project and network identifiers, and token values are left out.
This is a dated record. The problems are described as they stood at `212defd`.

## What the work was

| When (UTC) | Project | MCP calls | What the agent did |
| --- | --- | ---: | --- |
| 11-19 01:48 | scratch | 2 | Two scripted calls to `desktop_request_host`, to check the client's approval hook |
| 11-19 21:02–21:15 | NixOS config | 40 | Signed in to the VPN admin console through Google, three times with the existing cloud profile and once with a fresh imported profile. Generated a one-day API token and moved it to a file with `send`. Later it revoked the token and deleted the temporary profile |
| 11-20 00:52–00:54 | NixOS config | 13 | Opened the cloud console's quota page. It found that both CPU quota increase requests had been denied with no reason given, looked for a denial email in the same profile, and read the tooltip on the disabled edit button |

The kind of use is the same as in the [cloud setup report](2026-11-08-gcp-tailscale-setup.md):
account setup in web consoles, in the background, with the person's logins. What's new is
that the person asked for it in the middle of infrastructure work, and the agent decided
on its own to use Agent Desktop for it.

## Statistics

| | Value |
| --- | ---: |
| MCP calls (new uses) | 55: `desktop_browser` 40, `create` 5, `destroy` 5, `screenshot` 2, `request_host` 2, `profiles` 1 |
| Private sessions | 5, all destroyed within 15 minutes of creation. None was left running |
| Profiles | The cloud profile in 4 sessions. One temporary profile was imported, used once and deleted |
| Browser batches | 28 in the whole window, 2 stopped early (see below) |
| Waits in batches | 28 fixed and 6 for a condition in the whole window. That's 82% fixed, the same share as the previous report (74 and 16) |
| Screenshots | 2, both scaled to 0.5 and both taken to see what a "covered" refusal meant |
| Tool errors | 1 unknown session id (a stale id from earlier in the conversation), 1 hook result that came back as an error |
| Human handoffs | 0. The person approved a phone sign-in prompt, and the agent asked questions through its client |

`activity` reports 9 sessions and 56 worker operations from 11-18 to 11-20, which
matches the transcripts once the MCP-only calls (create, destroy, profiles,
request_host) are left out.

## What worked

- **Cookies for the shell, the day after the feature landed.** The agent used
  `send` with `source="cookies"` ([#205](https://github.com/FilipNowakowicz/agent-desktop/pull/205))
  to see which VPN cookies the profile held. It printed only their names, paths and
  expiries, and deleted the file straight after. That's the use the previous report asked for.
- **`send` for the generated token.** The token went to a 0600 scratchpad file with
  `reveal: 0`, and the shell read it from there. (This didn't keep it out of the
  transcript, though. See the first problem below.)
- **Disposable profile for a borrowed login.** When the existing profile couldn't keep
  the VPN login, the agent asked the person before importing their Google login into a
  new profile. It used that profile for one session and deleted it straight away.
- **Sessions were short and cleaned up.** Every session was destroyed before the agent
  went back to the shell. No profile was held while idle, which had been a problem in
  the last report.
- **No GPU attempts.** The reworded `desktop_create` advice ([#203](https://github.com/FilipNowakowicz/agent-desktop/pull/203))
  wasn't tested this time, since no shell tests ran.

## Problems

### A `find` step returned the generated token

To get a selector for the token's element before `send`, the agent ran
`find` with `[role=dialog] input, [role=dialog] code, [role=dialog] button`. Each
matched element comes back with its text, so the token was in the reply in full. The
`send` that followed was correct, but by then the secret was already in the transcript.
The agent later reused the token from the transcript once, when a shell step failed after it
had already deleted the file.

The tool text says never to use `text` for secrets, but it doesn't mention `find`
or `wait`, and an agent needs one of them to find the element to `send`. This is the
most serious finding: a generated credential reached the conversation even though the agent
followed the documented route. The token was valid for one day and the agent revoked it
within 20 minutes.

### The agent edited a profile's cookie database by hand

The first sign-in with the cloud profile reached the VPN console's login page. When the
person approved the phone prompt five minutes later, the VPN site's half-finished login
had expired, and later attempts kept landing on a "session expired" page. The agent
then inspected `cookies.sqlite` and the Firefox prefs with `sqlite3`, and deleted the
VPN site's cookie rows from the database while no session was running. It told the person
straight away, but it is the hand route the last two reports warned about.

`agent-desktop forget-site` already does this safely, but no tool description mentions
it, so agents don't know it exists. There's also no supported way to see which cookies
a profile holds for a site, or when they expire, without writing them out with `send`.

### Session-only logins can't be imported

The person's own Firefox was signed in to the VPN console, but only with a
session-only cookie, and `import-cookies` doesn't copy those (they live in the session
store, not `cookies.sqlite`). The import reported success, but the private browser was
still signed out. The agent worked around it by importing the Google sign-in instead.
The lecture-notes project's hand-written exporter (previous report) exists for the same reason.

### The agent signed in to the wrong Google account

The cloud profile holds a second Google account. In the account chooser, the agent
clicked the only account offered without asking which one the VPN account belonged to.
It got as far as the VPN provider's new-user survey, which may have created an empty
account for that address. The person later corrected it. `import-cookies` already
warns about multi-account sites. But nothing records which account a profile signs in
as, so a later agent can't tell.

### Small refusals that each cost a call

- **"covered: the element is under div".** The agent couldn't tell from the message what
  was covering the button. It took a screenshot, saw a "Remind me later" prompt and
  dismissed it. If the message included the cover's role and some of its text, the
  screenshot wouldn't have been needed.
- **`key` inside `steps`.** The agent tried to press Escape inside a browser batch. The
  refusal lists the valid actions but doesn't say that `desktop_key` sends keys.
- **A stale session id.** The agent used a session id from earlier in the conversation
  once. The error was clear, and it recovered with the next call. This is the same as last time.

### The hook result still looks like a tool error

The 11-19 scripted check of the host-approval hook ([#196](https://github.com/FilipNowakowicz/agent-desktop/pull/196))
got the same result as on 11-12: an unanswered prompt comes back as an error whose text
is the prompt itself. This hasn't changed.

### Fixed waits

82% of batch waits were still fixed pauses (8 to 12 seconds after `open` on console
pages), even though the tool text recommends waiting for text. This hasn't changed
since the cloud report.

## Since the last report

| Last report's suggestion | Status |
| --- | --- |
| Supported cookies for shell tools | **Fixed** ([#205](https://github.com/FilipNowakowicz/agent-desktop/pull/205)), and used once already. Hand edits to the profile came back for a different reason (above) |
| Download receipts | Landed ([#204](https://github.com/FilipNowakowicz/agent-desktop/pull/204)). No downloads happened in this window, so it wasn't tested |
| GPU failure up front | Tool text reworded ([#203](https://github.com/FilipNowakowicz/agent-desktop/pull/203)). No GPU creates in this window |
| Idle profile held | A busy profile's refusal now names its holder and how long it's been idle ([#203](https://github.com/FilipNowakowicz/agent-desktop/pull/203)). Not seen in this window |
| `send` folder, 30-step message, `view-source:` | Fixed ([#203](https://github.com/FilipNowakowicz/agent-desktop/pull/203)). None came up again |
| Hook result | Unchanged |
| Tool surface review | Unchanged. 22 tools weren't called in this window |

## What this suggests for development

1. **Keep secrets out of `find` and `wait` replies.** Hide element text that looks like a
   generated credential (known token prefixes, or a long string with no spaces and
   high entropy) and mark it as hidden. Say in the tool text that `find` returns
   text, and that `send` can take the selector directly (for example
   `[role=dialog] code`).
2. **Make `forget-site` known, and give a read-only view of a site's cookies.** Name
   `forget-site` in the `send`/cookies hint ("never copy a profile's cookie files by
   hand"). Consider letting `desktop_profiles` list one site's cookie names and expiries,
   without values, for a profile that isn't in use.
3. **Say what's covering an element.** Add the cover's role and the start of its text
   to the `covered:` message.
4. **Point browser `key` attempts to `desktop_key`** in the unknown-action refusal.
5. **Session-only cookies in `import-cookies`** (needs a decision). Copying them from
   Firefox's session store would let more logins transfer. But that means reading a
   compressed file the person's browser is still writing, and the copied login wouldn't
   survive the private browser restarting.
6. **Record a profile's signed-in account** (needs a decision). For example, a
   note the person or agent sets on a profile ("signs in as the project account"),
   shown in `desktop_profiles`. It would stop agents from guessing in account choosers.
