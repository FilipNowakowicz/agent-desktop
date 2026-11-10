# Cloud and tailnet setup field report, 2026-11-08

This follows the [Hyprland field report](2026-11-07-hyprland-overhaul.md), which covered
sessions up to 2026-11-07. Since then agents in the maintainer's NixOS configuration
repository used Agent Desktop for a different kind of work: rebuilding a small cloud
setup (a home server, a remote Nix builder and CI access to it) on a new Google Cloud
account, which meant working in the Google Cloud and Tailscale web consoles. Two shorter
Hyprland shell tests also used the CLI.

As before, the agents were not asked to report. This was reconstructed from the Claude
Code transcripts, counted once per tool call, and cross-checked with
`agent-desktop activity` for each session. Account names, addresses, identifiers and
credentials are left out. This is a dated record; problems are listed as they stood at
`5740e9d`. The first session's MCP server may have started before #147–#149 merged,
but none of the problems below concern what those changes touched.

## What the work was

The maintainer asked the agent to "use the agent-desktop … to just navigate the gcp
website and tailscale and everything you will need cause i remember it being annoying",
and to use their own logins "in the background". There was no host session. The agent
offered `import-cookies` first, the maintainer ran it, and every console step ran in a
private Firefox driven through `desktop_browser`.

| When (UTC) | Console | What the agent did |
| --- | --- | --- |
| 11-08 18:36–18:38 | Google | Read billing, credits and projects to find which signed-in account held the new trial |
| 18:38–18:47 | Google | Removed the main account from the profile and got the new account signed in (see below) |
| 18:51–18:53 | Tailscale | Removed three stale machines, matched by exact name; the maintainer's devices were left alone |
| 18:53–18:56 | Google | Created the project, linked it to the trial billing account, enabled Compute Engine, set a budget alert |
| 19:15–19:36 | Tailscale | Generated three tagged, reusable auth keys for the VMs being installed |
| 19:22–19:24 | Tailscale | Pointed tailnet DNS at the reinstalled server, then removed the dead nameserver |
| 21:08–21:09 | Tailscale | Added a fallback public nameserver |
| 22:25–22:27 | Tailscale | Created an OAuth credential limited to one tag, for CI to reach the builder |
| 11-09 01:51–01:53 | Tailscale | Created a second scoped OAuth credential, for the deploy workflow |

Each console step was short and came between stretches of Terraform, `gcloud`, SSH and
Nix work. Once `gcloud` was logged in and the OAuth credentials existed, the agent used
those instead of the console. The browser was the way to *get* API access, and stopped
being needed once it had it.

What it made possible, according to the transcripts: the home server reinstalled on the new
project and back on the tailnet with working DNS, laptop builds offloaded to the builder,
and PR CI moved onto the builder, with full runs of 2–9 minutes against 40–79 minutes on
GitHub's runners.

## Statistics

Configuration-repository sessions from 2026-11-08 to 2026-11-10: 2 used the MCP server,
2 more used the CLI only, and the rest did not use Agent Desktop at all.

| | Cloud setup (MCP) | Shell tests (CLI) |
| --- | ---: | ---: |
| Calls | 138 MCP calls | 23 shell commands |
| Desktops | 4 private, 0 host | 2 private, guarded |
| Tool errors | 1 | 3, one refusal repeated, plus 1 failed create |
| Human handoffs | 1 (failed, see below) | 0 |

| Tool | Calls | | `desktop_browser` step | Count |
| --- | ---: | --- | --- | ---: |
| `desktop_browser` | 97 | | `wait` | 90 |
| `desktop_screenshot` | 10 | | `click` | 55 |
| `desktop_click` | 9 | | `find` | 50 |
| `desktop_create` | 4 | | `text` | 37 |
| `desktop_destroy` | 4 | | `open` | 29 |
| `desktop_profiles` | 3 | | `fill` | 13 |
| `desktop_list` | 3 | | | |
| `desktop_scroll` | 3 | | | |
| `desktop_launch` | 3 | | | |
| `desktop_request_human` | 2 | | | |

| Habit | Observed |
| --- | --- |
| Browser calls that were `steps` batches | 53 of 97, averaging 5.2 steps |
| Batches stopped before the end | 11 of 53: 6 ambiguous targets, 3 missing elements, 1 disabled button, and 1 click outside the viewport, reported uncertain |
| Waits | 81 fixed (358 s in total), 17 waiting for text or a selector |
| Coordinate input | 12 calls (9 clicks, 3 scrolls), 9 with an observation token, 5 with `screenshot=true`. In the Hyprland report no call passed a token (0 of 63) |
| Screenshots | 10, all scaled to 0.5–0.6, none cropped |
| Longest session | 3 h 40 min with the `gcp` profile, 96 traced calls, idle for up to 1 h 30 min between uses; the browser was still on its page each time |
| Profile reuse | The next night, a new session with the same profile was still signed in to both consoles |

`agent-desktop activity` agreed with the transcript counts. It reported no errors for the
long session, though, because stopped batch steps are not tool errors.

## What worked

- **Background use of the maintainer's logins.** `import-cookies` gave a private session
  the maintainer's Tailscale login without touching their screen, and the login lasted
  across sessions and days. This was exactly what the maintainer asked for.
- **The DOM bridge did most of the work.** 70% of calls were `desktop_browser`.
  Coordinates were needed only for one kind of widget and for scrolling.
- **Refusing ambiguous targets.** The 6 ambiguous-target stops and the one ambiguous-target
  error clicked nothing, listed the matches, and cost one more call with `within`, `exact` or a tighter
  selector. On pages that list destructive actions (a menu with Remove next to Share), this
  is the behaviour to keep.
- **Uncertain delivery was reported, not retried.** The agent then used another route to
  the same action and did not repeat the click.
- **Withdrawing a handoff** that could not succeed was clean: the viewer disconnected, the
  clipboard was cleared and the agent got control back.

## Problems

### Credentials passed through the agent's transcript

Generating a Tailscale auth key or OAuth client shows the secret once in a dialog. On
2026-11-08 the agent read it with `desktop_browser text` and stored it from there, so three
auth keys and one OAuth client secret ended up in the conversation transcript. They were
then stored correctly (encrypted, or as GitHub secrets), but the transcript copy remains.

The next night the agent worked around this on its own: it clicked the dialog's copy
buttons, used `desktop_launch` to run `wl-paste` into owner-only files in the profile's
home, checked only their length and prefix, piped them into `gh secret set` and deleted
them. It took a probe launch, two ambiguous-selector attempts and knowing where the
profile home lives on disk. The tools have nothing for "move this value to a destination
without showing it to me".

### Google refuses sign-in in the automated browser

The new account had to be signed in. `desktop_request_human` worked as designed, but
Google answered the maintainer's login with "this browser or app may not be secure",
because Firefox under WebDriver BiDi reports itself as remote-controlled. The
documented fallback for a login is a handoff, and for Google it cannot succeed.

The workaround took two more attempts at the maintainer's terminal: a throwaway Firefox
profile (`firefox --no-remote --profile …` silently opened in the running Firefox instead,
and `MOZ_NO_REMOTE=1 firefox --new-instance` worked), a manual login there,
`import-cookies --from` that profile, and deleting it afterwards.

### Importing a site copies every account on it

The first import copied all of the maintainer's Google sessions. Google's default account
in the session was their main one, and the new trial account was second. Before acting,
the agent edited the profile's `cookies.sqlite`, web storage and history directly to remove
the main account, then checked that nothing referred to it. That was the right instinct,
but the tool did not warn that several accounts were signed in, and there is no supported
way to remove a site's cookies from a profile.

### Commands given to the person did not run

The server's instructions tell the agent to have the person run `agent-desktop
import-cookies …`, and `take_command` and `paste_command` use the same form. With the MCP
server started as `uv --directory … run agent-desktop-mcp`, `agent-desktop` is not on
the PATH. The maintainer got "command not found" twice before the agent worked out the
`uv --directory ~/agent-desktop run agent-desktop …` form.

### A control the clicks could not change

Tailscale's key dialog uses switches whose labels can be clicked. Clicking the labels
was reported `delivered` with an empty `now`, but the switches did not change. The agent
noticed only by reading the dialog text, then took a screenshot and clicked the switches
by coordinates. It did this for all three keys.

### The screen is too small for admin consoles

Sessions are 1280×720, which leaves a 1280×635 viewport in Firefox. A machine's action
menu opened below the fold, the Remove item could not be clicked ("move target out of
bounds"), and the agent went to the machine's own page instead. `scrollIntoView` cannot
help with a menu fixed in place at the bottom of the page. There is no option to make a
session larger.

### Shell testing in nested desktops (CLI, 11-08)

- The GPU desktop was created with environment variables, because `renderer` was not yet in
  the CLI. The first attempt used the system's Mesa and failed with
  `EGL_EXT_platform_base not supported`. The agent then found the Mesa the runtime links
  by running `ldd` on the runtime's compositor. The `renderer` option has since landed;
  supplying the matching Mesa is still left to the person setting up the session.
- In a guarded session the nested test harness's own `hyprctl` calls hit the guard shim
  ("hyprctl is blocked in a guarded session"), although they were aimed at the nested
  instance. The agent recorded a learning note in that repository, and a later session
  tested in a NixOS VM instead of a nested desktop.
- `screenshot --scale 2` was refused ("Scale must be between 0.1 and 1"). The agent
  wanted a sharper look at a small card.

## Mistakes by the agent

- It gave commands that do not run as given (`agent-desktop` off the PATH, then
  `--no-remote`), before checking them.
- It read freshly generated secrets as page text on the first day.
- A `wait` for `input[value^="tskey-auth"]` never matched, because the key was in a
  `<pre>`. That cost 15 s, and the next read was the text read above.
- 81 of 98 waits were fixed sleeps, mostly 4–9 s after each `open`. Waiting for a
  heading or button would have been faster on most pages.

## Not caused by the runtime

Firefox's `--no-remote` reusing the running instance, Tailscale's description field
accepting only letters and numbers (which kept Continue disabled), Google Cloud zone
capacity errors later in the night, and Claude Code moving long MCP calls to the
background when a message arrived (the results still arrived as notifications).

## What this suggests for development

This use case is different from the Hyprland one. There the desktop under test *was*
the product. Here the agent needed a browser holding the person's logins for about
twenty minutes in total, spread over an evening. It used the browser to create the
credentials that let it switch to APIs, and it handled secrets throughout. The person's
request was specific: do the annoying web-console setup for me, with my logins, without
taking my screen. The suggestions, most valuable first:

1. **A way to move secrets without the agent reading them.** For example, a browser step
   that sends an element's text or the session clipboard to a command's stdin or a 0600
   file, and returns only length, prefix and digest. The second night shows agents will
   use it, and the first night shows what happens without it.
2. **A login route that sites accept.** For the human's turn, start the profile's Firefox
   without the remote agent, then restart it under BiDi with the same profile once they
   release control. Until then, document the clean-profile `import-cookies --from` route
   for Google and similar sites, and say up front that the handoff will be refused there.
3. **Account-aware imports.** Warn when an import brings several accounts on one site,
   and offer a supported way to drop a site's cookies from a profile, so agents do not
   edit Firefox databases by hand.
4. **Commands that run as printed.** Build `take_command`, `paste_command` and the
   instruction text from how the server was actually started, or document installing the
   CLI on the PATH (for example with `uv tool install`).
5. **Report clicks that change nothing.** When a click targets a switch, checkbox or
   its label, report the control's checked state before and after, so "delivered" does not
   hide "no effect".
6. **A session size option** for create, with a larger default worth considering for
   browser work.
7. **Count stopped and uncertain batch steps in `activity`,** so the summary shows what
   this report had to find in transcripts.
8. **For shell testing:** let a guarded session allow `hyprctl` against a nested instance
   it started, and say how to find the matching Mesa on NixOS. Otherwise agents move to VM
   tests, as one did here.

Taken together with the Hyprland report, two uses stand out: testing desktop software in
throwaway desktops, and doing account-bound web work in the background. For the second
use the main open questions are about logins and secrets, not input reliability.
