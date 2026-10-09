# Development log

## 2026-10-09 — S3: browser bridge for private Firefox

New worker operation `browser` (MCP `desktop_browser`, CLI `browser`): `start`
launches Firefox in the private session with `--remote-debugging-port=0`, reads
the port from its log and opens a WebDriver BiDi session (new dependency:
`websockets`). Actions: open, tabs, text, find, wait, click, fill, select.
Targets are CSS selectors or visible text/label/placeholder and must match one
visible element; disabled targets are refused; password values are never
returned. Clicks and keys are BiDi `input.performActions` (trusted events). It
is mutating for the lease, refused during takeover and on host sessions, and
recorded by the effect ledger. The person's own Firefox is not touched.

Validation: tests/test_browser.py (Firefox 156): form fill with Unicode,
password redaction, select, check box, ambiguous and disabled refusals, page
text, new tab; full suite (see PR).
## 2026-10-09 — S2: guarded steps (kept for reliability, not speed)

`desktop_actions` steps take `expect`; `ui_action` steps can name a target found
at run time (one exact match or nothing is sent); waits take `state` and
`exact`; listings mark `disabled` controls (neither ENABLED nor SENSITIVE: GTK 4
sets only SENSITIVE); `press` works on check-only Chromium check boxes; a run
`timeout`. `AGENT_DESKTOP_GUARDS=0` hides the description (benchmark
`--no-guards`).

Agent A/B on three hard tasks with S1a in both arms
(docs/research/2026-10-09-guarded-steps.md, 18 runs, all passed): turns −8%
(p = 0.14), time unchanged. The 30% gate is not met; the agent rarely used
expectations and never run-time targets. Kept as reliability features; speed
work moves to the browser bridge and reuse. Agent runs used today: 36.

Validation: ruff check and format; full desktop suite with zenity, kdialog and
at-spi2-core from `nix shell`: 148 tests OK (10 skipped).

## 2026-10-09 — S1a: input returns the settled screen

Input tools, `desktop_actions` and the CLI (`--screenshot`) accept
`screenshot=true`: the reply carries a screenshot taken once the screen has been
still for 0.3 s (at most 3 s) and says whether it went quiet. Worker `settle`
now returns that outcome; `screenshot` accepts `settle_ms`/`settle_timeout_ms`.
`AGENT_DESKTOP_LOOK=0` hides the option (experiment baseline); the benchmark has
`--no-look`, records inline screenshots, and the A/B summary also tests turns
and seconds.

Agent A/B (docs/research/2026-10-09-act-and-observe.md, 18 runs, all passed):
turns −31% (p = 0.0002), input tokens −20% (p = 0.04), wall time −14%
(p = 0.04); median cost unchanged within noise. Kept. Side finding: `press`
failed on Chromium check boxes that offer only `check` (fixed in S2).

Validation: ruff check and format; full desktop suite with zenity, kdialog and
at-spi2-core from `nix shell`: 146 tests OK (10 skipped).

## 2026-10-09 — External review; S0 foundations

An external research review (docs/research/2026-10-09-astra-review.md, written
read-only against 4b44101) checked the beyond-human-speed plan against the
code. Its static findings were verified by reading the source; these were fixed:

- `desktop_set` wrote into the session home from the MCP process, bypassing the
  worker's lease and takeover checks. It is now a worker operation `set`
  (mutating, effect-ledger recorded, refused on the host). `atlas.apply` writes
  nothing unless every key still holds its learned starting value (or already
  the target), and refuses ambiguous control names. Two Mousepad plugin
  toggles that write the same list can no longer overwrite each other.
- Element waits with `app_id` (and no title) searched every application; they
  now search the matched windows only.
- `atspi.tree` skipped unreadable nodes silently, so a `gone` element wait could
  succeed on a partial read. The tree now reports `unreadable`, and gone waits
  return "element unknown" while it is nonzero.
- File waits (`wait_for_file`) matched deletions; deleted or missing files no
  longer match.
- Docs: host waits cannot use elements (USAGE, MCP instructions); typing is
  paced at 8 ms per key; README notes the approved-host exception.
- Plan: corrected three claims (private sessions do not share the person's
  configuration; damage is not readiness; a disposable session is not a
  disposable world) and reordered the roadmap: S0 foundations, S1a act and
  observe, S2 exact checks and guarded plans, S3 private browser and procedures,
  S4 host hardening, later stages only when measured tasks need them.

Not changed: the review's suggestions about delivery-state vocabulary and plan
deadlines belong to S2.

Validation: ruff check and format; `PATH=<runtime>/bin:$PATH uv run python -m
unittest discover -s tests -v` (full suite), and test_ui.py with zenity,
kdialog and at-spi2-core from `nix shell`.

## 2026-10-09 — Plan: beyond human speed

docs/research/2026-10-09-beyond-human-speed.md records the plan agreed with the
maintainer: the ideal agent in a new environment, mechanisms (delta-coded
observation, guarded plans, navigation maps, GUI bypass, procedures,
parallelism, live applications without the person's screen), reachability, a
staged roadmap S1–S6 with measurements and stop criteria, and the authorisation
rules for unattended testing. Prior art checked: anticipatory policy trees
(arXiv 2607.28399), speculative actions and macro commit, wlr-screencopy damage,
Firefox WebDriver BiDi, Hyprland headless outputs. Correction to the speed note:
`desktop_actions` wait steps already accept title, element and text conditions.
No implementation yet.

## 2026-10-09 — Speed: where the time goes

Research note docs/research/2026-10-09-speed.md. From the host trial traces
(164 calls, three sessions): time inside the tool was 0.4–2.6% of wall time,
median gap between calls 2.1–3.6 s, and 53 of 59 screenshots came directly after
an input. Proposals ranked: act-and-see input results with damage-based
settling, guarded plans (run-time targets and expectations), replayed
procedures, a fast grounding model, API paths, shorter round trips. No
implementation or agent runs yet.

## 2026-10-09 — Host-session browser trial; host sessions keep the computer awake

The maintainer ran the first real host-mode task (userscript install and
web-app settings in their Firefox, three sessions, 164 traced calls) and
recorded it in docs/trials/2026-10-09-host-browser-task.md. The idle
screensaver started mid-session and a Ctrl+T was traced `delivered` without
effect (findings 1–2).

Host sessions now hold a logind idle inhibitor (`systemd-inhibit --what=idle
--mode=block`) from start until stop or expiry. It watches the worker's PID, so
it also ends if the worker is killed; `AGENT_DESKTOP_HOST_KEEP_AWAKE=0` turns it
off. The trial showed hypridle honours such an inhibitor. INTEGRATIONS.md shows
user-scope MCP registration (finding 6).

Validation: ruff check and format; `PATH=<nix runtime>/bin:$PATH uv run python
-m unittest discover -s tests -p test_host.py -v` — 8 tests OK, including the
new `test_keeps_the_computer_awake_until_it_ends` (inhibitor listed during the
session, gone after `stop_host`); full suite with the Nix runtime only: 144 OK,
17 skipped (optional applications absent: LibreOffice, zenity, kdialog, mousepad,
xterm, xev, wlr-randr; visible mode).

Still open from the trial: refusing input while locked or blanked, layer-shell
focus in `delivered` (finding 2), window geometry/workspace, a fresh screenshot
after `UserActive`, the session id in tokens, and CLI polish.

## 2026-10-09 — Prepare for public visibility

The maintainer approved making the repository public. Planning records
(development log, project plan, research findings, start here) moved to
`docs/project/`; Markdown links were rewritten repo-wide and checked (none
broken), while plain-text file names in dated records stay as written. Added
SECURITY.md with private advisory reporting; README status now reflects the
closed alpha gates and summarizes the effect ledger and atlas research;
AGENTS.md, CONTRIBUTING.md, START_HERE and the PR template no longer require
private visibility. Disclosure scan repeated over all history: no tokens, keys
or passwords; history is published as is (maintainer decision). The Geany key
swap was reported as geany/geany#4677. Issue #6 (M3) closed as complete.

## 2026-10-09 — Effect atlas: model-free settings discovery, lookup and apply

Research (docs/research/2026-10-09-effect-atlas.md). Prior art for "compile
once, run free" (PreAct, AppAgent-Claw), declarative settings (DroidTool, DMI)
and agent change review was checked first; differential settings discovery was
the open direction.

`scripts/effect_atlas.py` discovers menu toggles and preferences check boxes
through accessibility, clicks each once in a fresh session, parses the
configuration into keys (INI/keyfile, xcu, prefs.js, JSON), subtracts control
and interaction noise, and verifies each effect by applying it alone. Mousepad
0.7.0: 37 controls, 32 with effect, 30 verified, 7.7 min. Geany 2.1: 93
controls, 76 with effect, 75 verified, 23 min. Geany stores "Always wrap
search" and "Hide the Find dialog" under each other's key names (src/search.c
197-200, still in master).

Runtime: `ui_action` `select` (tab or list item through the parent's
Selection); the effect ledger keeps per-file versions (repeatable reports; the
watcher versions files when their events go quiet) and records files created in
a new directory before its watch existed. Experimental `atlas` module with MCP
`desktop_atlas` and `desktop_set` behind `AGENT_DESKTOP_ATLAS`; `desktop_set`
refuses host sessions and unverified entries. Mousepad applies an externally
written key live.

Agent A/B (claude-opus-5-5, four Mousepad settings tasks, 3 runs per arm):
lookup only, input tokens +20% (p = 0.0005), turns unchanged; lookup and
apply, three tasks 10-13 → 3-4 turns at about half the cost, pooled -26%
(p = 0.053). All runs succeeded. Harness: `--suite atlas`, `--atlas DIR`.

Validation: ruff check and format, compileall; tests/test_atlas.py (10) and
tests/test_effects.py (13) passed; full suite with the repaired Nix runtime and
optional applications: 143 OK, 1 skipped (visible mode). Agent runs: 48,
$5.09.

## 2026-10-08 — Effect ledger research prototype and agent A/B

Prototype `src/agent_desktop/effects.py` behind `AGENT_DESKTOP_EFFECTS=1`:
inotify on the session home (plus `AGENT_DESKTOP_EFFECT_DIRS`), line diffs of
small text files, OpenDocument cells and paragraphs as lines, window and
process changes per input/launch/focus/ui_action and per action sequence,
`effects` / `wait_effect` for late writes, MCP `desktop_effects`. Findings,
prior art and next steps: docs/research/2026-10-08-effect-ledger.md.

Results: six scripted scenarios (foot, Mousepad, Thunar, Calc ×2, Firefox)
matched their written expectations, including pilot sessions 15 and 20 shapes;
median report 9 tokens (max 262) vs about 1,229 for a full screenshot; +28 ms
median per action (227 → 255 ms, 80 actions each). The terminal scenario found
the zsh first-run bug (#89). Effect induction: Calc AutoInput learned from one
GUI change, applied alone to a fresh profile, verified against a control. A
settings-map explorer mapped and verified all 4 of 8 View-menu items that have
profile settings (5.8 min) and found the other 4 to be per-document. Agent A/B
(claude-opus-5-5, five tasks, round 3: 3 runs per arm): input tokens 25% lower
with the ledger (p = 0.016); all runs correct in both arms. Round 1 was an
accidental A/A test (batches carried no effects); round 2 had two harness
flaws, fixed before round 3 and described in the report.

Harness: `--effects`, `--suite effects` (two trap tasks), transcripts moved to
`RUN/agents/TASK/`, `context.reply` and `context.home` for checks, office
profile now `~/.office-profile`. New unit tests `tests/test_effects.py`.

Validation: ruff check and format (64 files), compileall; `test_effects` 3 of 3
runs; full suite with the repaired Nix runtime and the optional applications:
130 OK, 1 skipped (visible mode). Agent runs: 63 today (three A/B rounds, dry-run checks
excluded, one probe), $7.59 reported by the CLI against the operator's allowance.

## 2026-10-08 — wlroots fix submitted upstream (!5477)

freedesktop's bot approved account verification (#4178). The fork
`filip.nowakowicz/wlroots` received one commit on master `c5c57cd3` through
GitLab's file replace (no credentials or keys added); `git diff` of the fork
branch against upstream master showed only `xwayland/xwm.c` +6. The merge
request uses the prepared text from runtime/UPSTREAM.md plus a test plan, as
wlroots' CONTRIBUTING.md asks. The subject is 73 characters against a
guideline of 50; 27 of the last 50 upstream subjects exceed 50 (maximum 76).
The commit author address is the maintainer's GitLab email (approved). During
form filling, typed tab characters moved focus and triggered a GitLab search;
the API showed no resulting MR, branch or setting change.

## 2026-10-08 — zsh first-run menu took the first typed key

Found by the effect-ledger research prototype: a command typed into a terminal
in a fresh session wrote an empty file, and the shell history read
`cho hello > notes.txt`. Input delivery was not at fault (`zsh -f` and bash got
the whole line). With no zsh startup files in the private home, interactive zsh
shows `zsh-newuser-install`, which consumed the first key. It happened even
5 s after the window appeared, so waiting did not help. Sessions now get a
one-line `~/.zshrc` when the home has no zsh startup file; existing profile
files are left alone. The pilot did not use terminals, so it had not shown up.

Validation: before, 0 of 4 typed commands arrived whole in default zsh (two
scenario runs and two probes); after, 3 of 3 wrote `hello`. New test
`test_zsh_first_run_menu_is_answered`; guard tests 8 OK; ruff check and format
passed.

## 2026-10-08 — Login handoff and Dvorak takeover by the maintainer; alpha gates closed

One headless session with the profile `freedesktop` showed a keyboard-check
terminal (a shell `read` into a file) above Chromium on
`gitlab.freedesktop.org/users/sign_in`. The agent opened the takeover viewer
on the maintainer's screen (`agent-desktop take`, run by the agent) after
`desktop_request_human`.

- **Dvorak.** The host layout was detected (`keyboard: us-dvorak`). The
  maintainer typed `Dvorak check: Hello, World! 42 ;:"<>?`; the received file
  matched byte for byte. The first attempt was interrupted (the terminal got
  Ctrl+C), and agent launches were refused while the maintainer held control,
  as designed; the agent relaunched the terminal after release.
- **Login.** The site's anti-bot page ("type apple") and the sign-in were done
  by the maintainer (with Google). Paste did not work: the viewer had been opened
  without `--paste`, so the host clipboard was not sent, by design. Control
  returned with the clipboard cleared.
- **Persistence.** A new session on the profile reached GitLab signed out. Cookie
  metadata (names, expiry; no values read) showed every persistent cookie kept,
  including Google's login and the anti-bot pass, but GitLab's own login had been
  a session cookie. Ticking the password form's "Remember me" and clicking
  "Google" (no credentials; Google was still signed in) again did not persist.
  The page has a second "Remember me" for its "sign in with" buttons; with that
  one ticked, the next new session was signed in. Profile persistence works; the
  site decides whether its login outlives the browser.
- **Upstream.** Forking wlroots was refused for the new account ("Limit reached");
  freedesktop requires new accounts to request fork permission. Nothing was
  submitted. The commit is prepared locally, and the patch still applies to master
  `c5c57cd3` (offset 110 lines).

Changes from this: `desktop_request_human`/`desktop_control` also return
`paste_command` (`agent-desktop take --paste SESSION`), and the MCP instructions
tell agents to offer it for logins and to suggest "Remember me". The usage guide
records the session-cookie behaviour.

Decisions (decisions.md): M2 and M3 gates closed; the maintainer's continued use is
feedback, not a gate; upstreaming is not a gate. Next focus: the research direction.

## 2026-10-08 — Profile recovery state; M1 closed

The last F025 gap for profiles: when both supervisors were killed, the profile
lock was released while the old session's applications kept running, so a new
session could share the profile with them. A profile now records the session
that last started on it (`last-session.json` beside, not inside, its home).
`profiles` reports that session's end (`ready`, `stopped`, `failed` with its
error, `recovered`, `abandoned` when neither supervisor is alive but nothing
marked it ended, or `pruned`), and `create` returns it as `previous_session`.
A `create` on a profile whose last session is abandoned first runs the same
token recovery as `destroy`.

Found while testing: a killed supervisor's environment becomes unreadable
before the kernel closes its files, so for a moment a session can read as
abandoned while the lock is still held; `create` then refuses with "in use",
which is the safe direction. The test waits for the lock instead.

New tests: SIGKILL of both supervisors with an application (`sleep`) still
running; the profile is free and reads `abandoned`, the next `create` stops the
application, reports `{status: stopped, recovered: true}`, and no token process
remains. SIGKILL of the worker only; the next session reports `failed` with the
guardian's error. Profile tests passed 3 of 3 runs. Full suite with the
repaired Nix runtime and the optional applications (`nix shell` xterm,
wlr-randr, at-spi2-core, zenity, mousepad, xev, kdialog, LibreOffice,
wl-clipboard): 119 OK, 1 skipped (visible mode), 233 s. Ruff check/format and
compileall passed. CI remains unavailable; validated locally.

Decision: escape of environment-clearing processes after double-supervisor loss
is an accepted, documented limit (decisions.md), so M1 has no open gate.

## 2026-10-07 — Next-direction research and finite abstraction experiment

Reviewed the current source, pilot and benchmark records at `328b51f`, plus
primary competitor documentation and mathematical/computer-use literature.
Saved the recommendation in
`docs/research/2026-10-07-next-direction.md`: precise observations and checked
actions first, reusable procedures as the longer-term product hypothesis, and
counterexample-refined task abstractions as the mathematical research hypothesis.
The plan links this as a proposal, not a committed product pivot.

The new finite model enumerates 128 states and five actions. Its eight-class
summary fails goal and transition preservation. Refinement gives 94 classes;
all 60 remaining equivalent state pairs and 300 action comparisons preserve the
specified goal/transition relation. This establishes only the toy-model result,
not desktop reliability, token savings or novelty. Script and deterministic JSON
are alongside the report. No new desktop comparisons, paid model calls, host
changes, personal-profile access or outreach were performed.

Validation: `uv run python docs/research/abstraction_experiment.py` passed; a
second execution parsed equal to the saved JSON. All report-relative links
resolved. `uv run ruff check src scripts tests benchmarks
docs/research/abstraction_experiment.py`, `uv run ruff format --check` on the
same paths (57 files), and `uv run python -m compileall -q` on the same paths
passed. `git diff --check` passed. Runtime tests were not rerun for this
documentation and standalone finite-model change; no desktop behaviour changed.
Remaining gaps: measured gains on real tasks, external user demand, competitor
execution comparisons and maintainer selection of a next stage.

## 2026-10-06 — CI unavailable; merges validated locally

GitHub Actions stopped starting jobs ("recent account payments have failed or
your spending limit needs to be increased"), so the required Lint check could
not run on #79–#81. At the maintainer's instruction ("verify them locally"),
each was checked locally and merged with an administrator override of the
required check: ruff check, ruff format --check, compileall and the unit
tests on every branch; the full desktop suite with the optional applications
(117 OK, 1 skipped: visible mode) on #79 and on #81 rebased onto it, and again
on main after all three merges. #79 and #81 had also passed the full Checks
matrix on all four platforms before the outage (runs 37504822099 and
37506015397). Until CI is restored, this local procedure replaces Lint.

## 2026-10-06 — Graphical Ubuntu desktop check; keyring mask under umask 002

A disposable QEMU/KVM VM from the official Ubuntu 24.04 cloud image (SHA-256
verified) got `ubuntu-desktop-minimal` with GDM autologin into GNOME Shell 46
on Wayland. The checkout arrived as a git bundle; only the documented apt
install and uv steps were used (packages: labwc 0.7.1, wlroots 0.17.1, wayvnc
0.7.2, grim 1.4.0, Xwayland 23.2.6, TigerVNC 1.13.1). Screens were captured
through QEMU's QMP `screendump`. Results: doctor and its smoke check passed;
a headless session received `hello café λ 123` exactly; visible mode opened a
nested labwc window on the GNOME desktop, received the same text exactly, and
closing it ended the session with nothing left; `view` worked with Xwayland's
`DISPLAY` and failed with a clear error without one (documented); `take`
refused agent screenshots and input while the person had control, `release`
returned control, and input before a new screenshot was refused as stale.

The suite (with `DESKTOP_TEST_VISIBLE=1`) first had two failures:

- test_keyring_is_not_activated: the private bus started the real
  gnome-keyring. dbus-daemon 1.14.10 logged `Unable to set up transient service
  directory: ... "dbus-1" can be written by others (mode 040775)`: Ubuntu's
  default umask 002 made the mask directory group-writable, so it was ignored.
  The worker now sets 0700 on `dbus-1` and `dbus-1/services`. The test now
  creates its session under umask 002; it failed on the old code on NixOS too,
  and passes now, also in the VM.
- test_firefox_exposes_its_page: `/usr/bin/firefox` is a wrapper for the snap,
  which opened no window in a private session (snap confinement keeps it out
  of hidden directories such as the session home under ~/.local/state; not
  investigated further). The test skips the snap.

With both changes the suite in the VM: 116 OK, 9 skipped (Chromium,
LibreOffice, kdialog and the snap Firefox are not installed or not usable
there). Part of this check was run by a helper agent that stopped on the
account's usage limit before writing its report; its logs and screenshots were
read and the failures diagnosed afterwards. Evidence stayed on the local
machine (VM image, logs and screenshots under a temporary directory).
## 2026-10-06 — Settle before text that follows a key

Pilot session 29: after closing Calc's Welcome dialog, Ctrl+Shift+F5 (Name
Box) was followed at once by `type "D1\n"`; the text went into A1 and the next
rows overwrote column A. The settle wait added in #76 ran only before a key that
follows text. It now runs at every switch between `type` and `key` within a
second (`settle_after`), in both directions; consecutive keys or consecutive
texts are not delayed. Reproduction (close Welcome, shortcut, type at once):
old code 3 of 3 wrong (text in A1), new code 3 of 3 right (D6). New test
test_calc_text_after_a_shortcut_reaches_its_target uses a new profile so the
Welcome dialog appears; it fails on the old code (A1 = "D6marker") and passed
3 of 3. Full suite with the optional applications: 117 OK, 1 skipped (visible
mode). The 30-minute soak of #76 with 12 busy processes (before this change):
2,076 lines exact, 207 short sessions, 0 failures; type p50 195 ms for about 25
characters, key p50 225 ms (settle), worker CPU about 26% of a core while
typing continuously. Worker RSS stayed at 32–37 MB and the process count at 8
throughout; screenshot p95 94 ms, create p50 302 ms, destroy p50 626 ms.

First Checks run (37482451325): Nix, Fedora and Arch passed; Ubuntu (LibreOffice
24.2) failed the new test with "marker" in A1, so on that runner the settle wait
did not cover the shortcut. The test now runs only when the Welcome dialog
appears (the reproduced condition) and skips otherwise. The second run
(37504822099, all four passed) skipped it on Ubuntu: no Welcome dialog appeared
there, so the first failure happened without one. On that runner the settle
wait did not cover the shortcut; it is a heuristic, not a guarantee, and a
short explicit wait after a focus-moving shortcut remains advisable.

Idle soak (`soak.py --minutes 240 --interval 600`, started before #74): 24
checks over 4 hours, 24 lines received exactly, 2 short sessions, 0 failures;
worker RSS 28–37 MB with no upward trend, 8 processes throughout; worker CPU
2.0–2.7 s per idle minute, the cost #74 removed.

## 2026-10-06 — Profile lock held until the guardian has cleaned up (F025)

The worker took a named profile's lock itself, so when it died abnormally the
kernel released the lock at once, while the guardian was still stopping the
session's applications. A new session could then open the profile while old
processes were still writing to it. The guardian now takes the lock before it
forks the worker; both share the open file, so the lock lasts until both have
exited. If the guardian cannot take it, the worker refuses as before ("Profile
is in use"). Test: with the guardian stopped (SIGSTOP), SIGKILL of the worker
leaves the profile `in_use` and a new session on it is refused; after SIGCONT
the session is marked failed, the profile frees, and a new session starts. On
the old code the profile was free while the guardian was stopped. Full suite
with the optional applications: 115 OK, 1 skipped (visible mode).

Still open from F025: if both supervisors are killed, processes that cleared
their environment escape recovery; only a cgroup would close that, and it stays
deferred for portability.

## 2026-10-06 — Firefox text in UI listings

Pilot session 19 waited for `text="stable"` on debian.org in Firefox and found
nothing: Firefox paragraphs listed `text=''`, and every Firefox web node offered
`set_text`. Text was read with `GetText(0, 500)`; GTK clamps the end offset, but
Firefox returns an empty string when it is past the text. The listing now
clamps to `CharacterCount`. Firefox also gives every web node the EditableText
interface, so `set_text` is now offered only for nodes in the `editable` state
(GTK, Qt, Chromium and LibreOffice fields all report it). FirefoxUITests now
waits for a paragraph's text and checks that an entry, but not a paragraph,
offers `set_text`; it failed before the change. Full suite with the optional
applications: 112 OK, 1 skipped (visible mode).
## 2026-10-06 — Calc "rapid navigation" failures explained and fixed (F006)

Pilot session 20 typed an order table in Calc with `desktop_actions`: a `type`
step per row and Home, Down between rows. Every row landed in row 1 and the
cursor ended at C5. Experiments (scripts outside the repository, one Calc
session each, LibreOffice 26.8.0.3, labwc 0.20.2):

- With 1.5 s between steps every step was right; with no pause the text of all
  rows went to row 1 and the Home/Down pairs took effect after it (J1 → A3).
  LibreOffice applied navigation keys sent right after typed text only after
  the text that followed them. The earlier Fedora CI failure (formula in A2
  instead of B4, 2026-10-04) fits the same pattern.
- Idle and empty, Calc received every key: 20 Downs (`repeat`, separate calls
  or spaced), 20 Tabs and alternating Down/Right, 5 of 5 each.
- A pause after a 20-character `type` fixed it from about 100 ms (3 of 3 at 0.1,
  0.2 and 0.4 s; 0 of 3 at 0.02 and 0.05 s). Typing one character per request
  (1–2 ms apart) also fixed it. A Wayland roundtrip per key did not, nor did
  pacing at 1–2 ms (0 of 4); 4 ms gave 3 of 4, 8 ms and 12 ms 8 of 8.
- With 12 busy processes on 12 CPUs, 8 ms pacing failed again (rows 1–2 in row
  10), and Tabs inside one text ("Total\t\t\t=SUM(…)") were overtaken by the
  formula after them.

The mechanism inside LibreOffice is not established. Changes: keys are paced at
8 ms (xdotool's default is 12 ms; `AGENT_DESKTOP_KEY_INTERVAL_MS`), and in
private sessions a `key` within 1 s of `type`, and each switch between
characters and Tab/Return runs inside a `type` text, first waits until the
screen has not changed for 150 ms (at most 1 s; caret-sized changes ignored).
Host sessions skip the wait. The client's timeout for `type` grows with its
length. Results with the change: 8 of 8 idle and 10 of 10 under the 12-process
load for the full sequence. A new test (test_calc_rows_typed_with_navigation_keys,
office_smoke.calc_rows) types the rows in one `run_actions` sequence and checks
the saved cells. It fails with `AGENT_DESKTOP_KEY_INTERVAL_MS=0` and the settle
wait removed. Under load the fixture's 3 s window for late Welcome dialogs was
too short; its profile is now seeded with the first-run settings (FirstRun,
ShowTipOfTheDay, ooSetupLastVersion). Pacing costs time: about 8 ms per
character, plus up to 1 s at each type/key transition. Full suite: 113 OK,
1 skipped (visible mode).
## 2026-10-06 — Idle worker CPU

The idle-session soak (`soak.py --minutes 240 --interval 600`) showed the
persistent session's worker using about 2.3 s of CPU per idle minute (22 s per
10 minutes, about 4% of a core) at a steady RSS of 31–37 MB. Cause: the serve
loop wakes every 0.5 s and `reap_orphans` read `/proc/PID/stat` of every process
on the machine (`process_table`, 11 ms per call with 370 processes), so the cost
grows with the machine's process count and the number of sessions. It now reads
the worker's own children from `/proc/self/task/*/children` and checks only
those, falling back to the full scan where the kernel does not provide the
list. An empty session's worker then used 0.10 s of CPU in 60 s (10 ticks),
against 2.3 s before. Tests: an untracked zombie child is reaped and a tracked
one is left for its Popen object, on both paths. Full suite with the optional
applications: 114 OK, 1 skipped (visible mode).

## 2026-10-06 — Firefox accessibility; observed AT-SPI exceptions

Firefox 156 exposed no accessibility tree in sessions (pilot session 10). It
enables accessibility only with `GNOME_ACCESSIBILITY=1`, which sessions now set
next to `ACCESSIBILITY_ENABLED` (Chromium). With it, Firefox listed its tabs,
toolbar and page. New test FirefoxUITests waits for a button on a local page.

Other exceptions seen in pilot sessions 12, 14 and 15, now in USAGE: in Thunar's
GTK 3 menu bar, an AT-SPI `click` on any menu ("View", "Help") opened the first
menu (File); the node resolved to the right element, and GTK logged "no trigger
event for menu popup". Chromium accepted `press` on a settings radio button but
did not change it. Chromium exposes only the part of a page it has rendered, so
a wait for an element further down needs a scroll first.

## 2026-10-06 — Private sessions no longer reach the person's Firefox profile

Pilot session 10 launched `firefox` in a private session and got "Firefox is
already running, but is not responding". The maintainer's home-manager wrapper
exports `MOZ_APP_DATA=/home/user/.config/mozilla/firefox`, an absolute path to
their own profile root, so the private `HOME` did not matter: Firefox found the
personal profile locked by the maintainer's running browser. Had that browser been
closed, the agent would have opened the personal profile. No input reached it;
the session was destroyed. (The new `open_windows` field showed the dialog's
title in the failed wait.)

Two changes. (1) Every private session drops inherited variables whose value is a
single path inside the person's home (HOME and the password database entry,
resolved), keeping colon-separated search paths, HOME itself and
`AGENT_DESKTOP_*`; `status` lists them as `home_removed_variables`. On this
machine that removed GNUPGHOME, ZDOTDIR, STARSHIP_CONFIG, VIRTUAL_ENV, PWD and
npm settings, among others. It does not fix the wrapper case, because the wrapper
sets the variable itself. (2) A `firefox` shim (also firefox-esr, -devedition,
-nightly) first on the session PATH adds `--profile ~/.mozilla/agent-desktop`
in the session home unless the arguments choose a profile; `status` reports
`pinned_browsers`. The shim also covers applications that open links through
PATH, but not those that use an absolute path. Of the maintainer's wrappers
only firefox (and two unrelated scripts) contain their home path.

Tests: home_variables classification (unit); guard tests check that a home path
variable is removed in an unguarded session and that a stand-in wrapper gets
`--profile` in the session home, while `--profile X` and `-P NAME` pass
unchanged. Real Firefox 156: the page opened in 4 s with a profile under the
session home, and no session process had files open in the personal profile.
Firefox exposed no accessibility tree in that session; not investigated yet.

## 2026-10-06 — Pilot day 2; loaded repetitions; failed window waits list windows

Pilot sessions 7–9 (all MCP, all completed, see docs/trials/pilot.md): Rust
release from the Rust blog in Chromium, LibreOffice AutoRecovery interval
verified in `registrymodifications.xcu`, and a Calc table with `MAX` verified in
the saved .ods. Session 7 found a misleading result: `desktop_wait` for the title
"Rust Blog" timed out with `no window` and an empty `windows` list while Chromium
was open as "The Rust Programming Language Blog". `windows` lists only matches,
so a wrong title looked like a missing application. A window wait that fails
with `no window` now also returns `open_windows` (title and app id of every
window). test_wait checks it.

`scripts/soak.py` gains `--load N` (busy CPU processes, as in lifecycle_stress)
and `--interval S` (idle seconds between iterations, for an idle-session soak),
selects the installed runtime like the CLI does, and writes its report on
interruption too. Loaded run (`--minutes 20 --load 12`, 12 CPUs): stopped by
interrupt after about 6 minutes because the maintainer's own interactive
workload was running and the load would degrade it. Its report covers 5.1
minutes: 681 mixed-script lines typed and received exactly, 68 short sessions,
0 failures. Each busy process got only about 35% of a core, so this was
contention but not saturation. Latencies rose modestly (screenshot p95 87 ms,
type p95 23 ms, create p50 302 ms, destroy p50 521 ms). The persistent session
reported 8 processes at the 5-minute sample against 4 in the unloaded runs;
not investigated. During the same load, `scripts/browser_smoke.py` (Chromium
Unicode typing, submit, drag) passed 20 of 20 runs. These are F006-style typing
repetitions under contention on this machine; they do not explain the earlier
Fedora Chromium failure.

Full suite inside `nix shell` xterm, wlr-randr, at-spi2-core, zenity, mousepad,
xev, kdialog, plus the installed runtime and LibreOffice 26.8: 109 OK,
1 skipped (visible mode). An idle-session soak (`--minutes 240 --interval 600`)
is running.

## 2026-10-06 — Eight-hour soak

`scripts/soak.py --minutes 480` (local Nix labwc 0.20.2, 2026-10-05 18:00 to
2026-10-06 02:00) passed with 0 failures. The persistent session typed 74,200
numbered mixed-script lines, all received exactly, and 7,420 short sessions were
created, captured and destroyed with no leftover processes. Worker RSS stayed
between 27 and 34 MB with no upward trend, the process count stayed at 4, and
latencies matched the 60-minute run throughout (screenshot p95 65 ms, type/key
p95 18 ms, wait p95 243 ms, create p50 202 ms, destroy p50 415 ms; maxima 168,
75, 309, 515 and 739 ms). Worker CPU averaged about 34% of one core. Session state
grew from 22.9 MB to 67.1 MB: the persistent session's screenshots, which are
capped at 200 (13 MB), plus the state of the destroyed short sessions, which is
kept until `prune`. The script left its temporary fixture directory in `/tmp`;
it now removes it on exit. An idle-session soak remains.

## 2026-10-05 — Host trial through MCP; wheel-notch scrolling

After `/mcp` reconnect, `desktop_request_host` was approved by notification
click and returned the session directly. Firefox opened the repository in a new
window (window wait 0.7 s), and the start notification was visible in the screenshot.
Two findings. (1) `stable_ms` waits never settled on the live desktop (a
terminal spinner was animating), both standalone and as a sequence step. The docs and server
instructions now say to wait for windows or elements on host sessions. (2) `scroll
dy=10` had no visible effect: scroll used the finger source, whose values are
pixels (copied from wlrctl in M0), so 10 meant 10 px. Page_Down worked. Scroll
amounts are now wheel notches (wheel source, axis_discrete 15 units per notch,
±100), documented in the MCP tool and CLI help. The runtime scroll test sends 3
notches and still sees a wheel event in the terminal fixture. Re-checked on
Hyprland in a second approved MCP host session: 5 notches scrolled the Firefox
repository page from the file list down to the README.

## 2026-10-05 — Real-screen trial; non-blocking host requests

With the keysym fallback, the maintainer approved a host request (through the
CLI, since the MCP connection had dropped). On their Hyprland screen,
the agent launched Firefox through `hyprctl dispatch exec`. Firefox was already
running, so a new window appeared. The first `focus` was refused with
UserActive while the maintainer was still using the computer, and it succeeded
on the sixth retry about 12 s later. A sequence (Ctrl+L, `about:preferences`,
Return, wait for the title) completed, and a screenshot showed the Settings page.
`host stop` ended the session with Firefox left open. No wrong-target input.

The MCP disconnect: `desktop_request_host` blocked for up to 2 minutes. The
interrupted first call got a "Request cancelled" response that Claude Code
did not expect ("unknown message ID"). The tool's thread kept running (a
second, failed host session came from it), and the client then closed the
connection. Requests no longer block: a detached helper
(`agent_desktop.hostprompt`) owns the notification and records the answer. The
tool waits at most 50 s and otherwise returns `pending`, to be called again.
Requests lapse after 120 s, and the CLI `host request` loops. The session worker
also no longer inherits the caller's stdin, which for an MCP server is the
protocol pipe. Tests: pending/approve/expire through the request file, and the
helper with a fake notify-send for click and dismiss. Full suite 109 OK,
6 skipped.

## 2026-10-05 — First host session on the real screen: keysym fallback

The maintainer approved the first real host request, and both attempts failed
at startup with `Cannot locate the compositor's libxkbcommon`. The keysym
resolver read the compositor's /proc maps, but Hyprland runs with CAP_SYS_NICE
(CapEff 0x800000), so it is not dumpable and its maps are unreadable. Keysym
names resolve the same in any libxkbcommon, so the resolver now falls back to
`ctypes.util.find_library` and then to the library labwc/foot/wayvnc link.
Test: `Keysyms(1)` (init, also unreadable) resolves Return. Host tests pass.

## 2026-10-05 — Host sessions: an agent on the person's own screen (experimental)

Maintainer request: let the agent act on their screen. Their Hyprland 0.56.2
offers virtual pointer/keyboard, wlr foreign-toplevel, screencopy and
ext-idle-notify v2 (checked with wayland-info, read-only); one 1920×1080 output.
A host session reuses the worker's input, screenshot, window, lease and trace
code but attaches to the person's Wayland socket instead of starting labwc
(`HostCompositor`: the compositor pid comes from SO_PEERCRED and is never
signalled). Consent: `request_host`/`desktop_request_host` shows a
notify-send notification with Allow (click) / Decline actions, or the person
answers with `agent-desktop host approve|deny`; `host start` allows directly.
`create("host")` without that path is refused. One host session at a time; it
expires (15 min default, ≤240) and notifies on start and end.

The person's activity pauses the agent. An ext-idle-notify listener (300 ms
idle) timestamps each idle→active transition in its own thread. Experiment:
labwc reports our own virtual input as activity within 1 ms, so transitions
during or within 0.5 s after the worker's own input are ours. Anything else
refuses input and focus for 3 s (`UserActive`, nothing sent). The first version
used a 1 s idle threshold and missed the person's input right after the agent's;
the test caught it. Limitation: the person's input during an agent burst without
a 300 ms pause is noticed only after the burst. Launches go through
`hyprctl dispatch exec` or `systemd-run --user`, so applications outlive the
session. Cleanup closes only our virtual devices, never windows (private
sessions close all windows). Take/view/request_human/ui are refused on a host
session.

Tests (tests/test_host.py) use a private headless session as the stand-in host,
with notifications disabled, so no test touches the real screen:
refusal without approval, decline, timeout, typing into the stand-in's terminal,
person's input pausing the agent then resuming after 4.5 s, expiry, the stand-in's
window surviving `host stop`, unsupported operations, and launch command
construction. Full suite 107 OK, 6 skipped. Not yet tried on the real Hyprland
screen; that needs the maintainer.
## 2026-10-05 — Full CI on demand only

The maintainer reported GitHub Actions minutes running low. The full desktop
matrix (Ubuntu, Nix, Fedora and Arch, about 30 runner-minutes per run, with the
Arch/Fedora wlroots builds and 100-repetition loops) ran on every PR push and every
merge. `checks.yml` now runs only on `workflow_dispatch` and `v*` tags, with
cancel-in-progress. A new `lint.yml` (ruff, format, compileall, unit tests with
desktop tests skipped; 62 skip without a runtime) runs on PRs and main pushes,
and is now the required status check instead of `runtime`. Desktop tests run
locally before merging, and their results go in the PR.

## 2026-10-05 — Rename to agent-desktop; public presentation

Maintainer decision: the repository and Python package become `agent-desktop`
(from `private-agent-desktop`). The reader-facing title stays "Agent Desktop",
although an unrelated Rust project uses the same title (lahfir/agent-desktop,
an accessibility-tree computer-use tool). The project MCP server is now registered
as `agent-desktop`, so its tools are `mcp__agent-desktop__*`; harness scripts and
docs are updated. Clients must approve the renamed project server once. Dated
logs, reviews and benchmark results keep the old names as historical evidence.

README: a real headless-session screenshot (LibreOffice Calc with a table and a
chart, made through the MCP tools), a "use it from an agent" MCP snippet, and a
short comparison (host sessions instead of VMs/containers; never the physical
desktop; built-in handoff). Disclosure scan of tracked files and the full
history: no secrets; local paths and the author email (accepted by the
maintainer). Publication checklist updated.

## 2026-10-05 — Pilot through MCP; UI actions in sequences

After `/mcp` reconnect the MCP tools work with the auto-selected runtime. Pilot
session 4 (kernel.org stable version, Chromium, MCP) completed with no keyring
dialog. Session 5 (LibreOffice user name in Tools > Options, MCP) completed,
with the name verified in `registrymodifications.xcu`, but it found a
sequence defect: `desktop_actions` strips each step's `action` key (the step
type), so a `ui_action` step could not name `set_text`/`press`. The worker then
failed with `AttributeError: 'NoneType' object has no attribute 'lower'`.
A `ui_action` step now passes its UI action as `name`, the worker rejects a
missing name with a clear message, and the MCP and USAGE docs show the form.
test_ui's element-wait test now sets the field through a sequence step and
checks the unnamed-step error.

## 2026-10-05 — Takeover follows the person's keyboard layout

The user's first real takeover (US Dvorak on Hyprland) typed QWERTY: the line
"the quick brown fox..." arrived as `asdfasdferewqasdfasdf`. TigerVNC sends key
positions (QEMU extended key events) and wayvnc maps them with its own default
layout. `take` now detects the host layout (`AGENT_DESKTOP_KEYBOARD`, Hyprland
`kb_layout`/`kb_variant`, `XKB_DEFAULT_*`, then `localectl`; first entry of
multi-layout lists) and starts wayvnc with `--keyboard=<layout>[-<variant>]`;
`--keyboard` overrides it. The value is validated and reported in the control
state. Detected here: `us-dvorak`. Test
`test_key_positions_follow_the_person_layout` sends QEMU key events for the
QWERTY positions a s d f + Return: `asdf` without a layout (the reported bug),
`aoeu` with `us-dvorak`. A unit test covers the detection order.
User confirmation (real TigerVNC viewer on the user's Dvorak Hyprland host,
session from this branch): the saved line was `aoeu134AOEU`. That is the Dvorak home row
plus digits and shifted letters, so the user's layout came through correctly; the user reported "works good".

## 2026-10-05 — Action trace

Review F035 (and the diagnostics F006 asks for). Every session writes
`trace.jsonl`: one record per input, launch, focus, ui_action, screenshot, lease,
take and release request, with time, controller, control owner, redacted
arguments (coordinates, keysym names, observation tokens, window/node ids), the
activated window before and after, duration, and the outcome (delivered,
observation, pid) or error. Typed and set_text values are kept only as lengths,
single-character keys as `<character>`, and launches as program name plus
argument count. The file is capped at 1 MB (trimmed to the newer half at a
record boundary) and stays readable after destroy or a crash
(`agent-desktop trace`). `AGENT_DESKTOP_TRACE=0` disables it. Tests:
tests/test_trace.py: redaction unit test; a real terminal fixture receives
"private words" while the trace holds only `text_chars: 14` with matching
focus and token; a failed focus records its error; bounding; disabling.

## 2026-10-05 — Controller lease, harness cleanup, PID start times

Review F011 (decisions 7 and 8). Each session has at most one controller. A
mutating request (input, launch, focus, ui_action, request_human) from a named
controller takes the worker's lease when none is active; any request from the
holder renews it; it expires after `AGENT_DESKTOP_LEASE_SECONDS` (default 60)
without requests, or is released with the `lease` operation (`--force` lets a
person break it). Other or anonymous mutations are refused with `LeaseHeld`,
nothing sent. Anonymous requests run lease-free when no lease is held, so
single-client CLI use is unchanged. Reads, destroy, take and release are never
refused; another client's screenshot no longer clears the post-takeover
screenshot requirement. CLI: `--controller` or `AGENT_DESKTOP_CONTROLLER`, and
`lease SESSION [--seconds N] [--release] [--force]`; the MCP server uses one
id for its lifetime; session applications do not inherit the variable.
`run_actions` holds the lease for the whole sequence (a temporary one when
anonymous). A request sent without a reply raises `DeliveryUnknown`; the
sequence reports that step with `"uncertain": true` and never retries it.

F037: `claude_code_task.py` runs the client in its own process group (killed
on timeout), records transcript and verification failures in `errors`, and
always destroys every session in its state directory, reporting leftovers.

F025 (partial): teardown records each process's start time (/proc stat field
22) and signals only if it still matches; a pidfd pins the process where
`os.pidfd_open` exists. The uv CPython 3.12.13 here lacks it, so a short
check-to-kill window remains there.

Tests: tests/test_lease.py (real compositor: B and anonymous refused while A
holds, B succeeds after release, A succeeds after a 1 s lease expires, B cannot
type into or start a sequence during A's four-step `run_actions`; typed text
exactly "alpha omega"; 5 repeats OK), test_mcp checks the MCP lease holder,
test_correctness an uncertain step sent once, test_process_identity,
test_harness_cleanup (fake hanging client, no model: timeout, malformed
transcript, created session destroyed with no owned processes). CLI checked by
hand. Full suite under `nix shell` labwc, foot, grim, dbus, wl-clipboard,
wayvnc, xterm, wlr-randr, at-spi2-core, xwayland, zenity, mousepad: 92 OK,
11 skipped (LibreOffice, xev, kdialog, Chromium/zenity UI, visible mode).
Remaining: no MCP tool releases a lease early (expiry or destroy); leases are
cooperative ids, not authentication; profile recovery state and
double-supervisor loss (rest of F025) are not addressed.
## 2026-10-05 — No keyring password prompt in sessions

Pilot task A (Chromium research) hit a "Choose password for new keyring"
dialog: the private bus activated the host's gnome-keyring service files,
which started a fresh keyring in the session home and asked for a password an
agent cannot answer. The agent dismissed it through `ui-action` (Cancel) and
finished, but this would block most browser tasks. Sessions now place
failing service files for org.freedesktop.secrets, org.gnome.keyring and the
secret portal in the session's `$XDG_RUNTIME_DIR/dbus-1/services`, which takes
precedence over host directories, so applications fall back (Chromium to its
basic store). `AGENT_DESKTOP_SECRET_SERVICE=1` restores the host behaviour;
`status` reports `secret_service`. Test `test_keyring_is_not_activated`: with
the opt-out, StartServiceByName returns 1 (started) on this host; without it,
activation fails. Chromium then loaded python.org with only its own window.

## 2026-10-05 — Runtime selection without PATH setup

First pilot attempt: this repository's `.mcp.json` starts `uv run
agent-desktop-mcp`, which inherits the client's PATH, and `desktop_create`
failed with `Missing executable: labwc`. An MCP client should not need a
hand-built PATH. The CLI and MCP server now put a selected runtime's `bin/`
first on PATH for themselves and their sessions: `AGENT_DESKTOP_RUNTIME`, or
else `~/.local/share/agent-desktop/runtime` if it exists (the Nix install is
`nix build ./runtime/nix --out-link` to that path, which is also a GC root),
else PATH. `doctor` reports the selection. Installed that link locally; with
the user's ordinary PATH, `doctor --smoke` is all ok, finding the repaired
runtime and the libexec registryd. Full suite 86 OK, 6 skipped. Test
`test_selected_runtime_goes_first_on_path`.

## 2026-10-05 — Two installation paths

Plan step 3 / F007/F019. `runtime/nix/flake.nix` (nixpkgs pinned at `4975466`)
builds labwc 0.20.2 against wlroots 0.20.2 with the mapping patch, plus grim,
dbus, Xwayland, wayvnc, TigerVNC, wl-clipboard, at-spi2-core and foot. It writes
the repair marker, so `doctor` recognises it. The build took 27 s locally (most
inputs cached), with no profile install and no host change. `runtime/install-ubuntu.sh`
is the Ubuntu 24.04 apt recipe; the Ubuntu CI job now installs through it, so
the documented recipe is what CI tests. `runtime/INSTALL.md` documents both.
at-spi2-registryd is now also looked up in `libexec/` beside each `bin/` entry on
PATH (Nix keeps it out of `bin`).

Ubuntu's wlroots 0.17 association code lacks the same existing-buffer check,
so the Ubuntu job now also runs 100 loaded Xwayland repetitions on stock packages
(`scripts/repeat_xwayland.py`, shared with Fedora/Arch). A new `nix` CI job
builds the flake, requires `doctor` to report the repaired runtime, and runs
the full suite.

The first `nix` CI run (37346098614) failed every desktop test: Nix's
dbus-daemon defaults to `/etc/dbus-1/session.conf`, which exists only on NixOS.
The worker now passes the `share/dbus-1/session.conf` shipped beside the daemon
when there is one (identical to the default on conventional distributions).

Local (Nix runtime + xterm/mousepad/zenity/xprop): `doctor --smoke` all ok, smoke
0.67 s; full suite 85 tests OK, 6 skipped. Fresh Ubuntu 24.04 check: a QEMU/KVM VM from the
official noble cloud image (SHA-256 verified), with an ssh login session, a
checkout, and only the documented steps. uv 0.12.23; `install-ubuntu.sh` took
2m02s and installed 186 packages (labwc 0.7.1, libwlroots12t64 0.17.1, grim 1.4.0,
xwayland 23.2.6, wayvnc 0.7.2). `doctor --smoke` passed its smoke check (0.56 s capture). A CLI
session typed `hello café λ 123` into foot, read back exactly from a file
and the screenshot, then was destroyed with no leftover processes. Suite: 86 tests OK,
19 skipped with documented packages only; 8 skipped after adding
xterm/zenity/mousepad/x11-utils/wlr-randr (the remaining skips: Chromium, LibreOffice, kdialog,
visible). X11 tests passed on stock wlroots 0.17. A cloud image with an ssh
session, not a graphical Ubuntu desktop; view/take were not tested.

The VM run found that `doctor` warned "could not determine the wlroots
version": Ubuntu's labwc omits it, and the library is `libwlroots.so.12`. Pre-0.18
sonames now map to versions (10/11/12 → 0.15/0.16/0.17); the old unit test
had encoded exactly this case as unknown. INSTALL.md now covers uv, the clone,
`--managed-python`, the expected doctor result, retained stopped sessions and test-only
packages. The apt step runs noninteractively. README still needs a link to
INSTALL.md (left for the documentation rewrite, #54).

## 2026-10-05 — MIT licensing

The maintainer approved MIT licensing. Added the standard MIT text from GitHub's
license template with copyright 2026 Filip Nowakowicz, declared the MIT SPDX
identifier and license file in package metadata, and updated the README,
contributor guide and publication checklist. This supersedes the undecided
licensing note in the earlier documentation entry. Repository visibility remains
private; PR #54 remains unmerged.

Validation: locked uv sync, distribution build and inspection confirmed the MIT
identifier and license file in the wheel and source distribution.
`git diff --check` passed. No runtime behavior or dependencies changed.

## 2026-10-05 — Documentation and publication preparation

Prepared in the separate `docs/public-facing` worktree from main revision
`1e9b20f`; no runtime, tests, dependency metadata or workflow code changed.
The README now introduces Agent Desktop, separates installation from the first
session, and routes detailed behavior to user, integration and validation guides.
Contributor instructions and the continuation guide use portable paths and
clarify parallel-worktree, publication and PR boundaries. Corrected stale claims
about accessibility, the viewer, retention and unmeasured tool profiles.

Reviewed both original brainstorming prompts at the maintainer's request. Their
core direction and most deferred ideas already exist in the plan; retained WSLg,
provisioning/update, networking and per-task-machine questions in section 7E.
Deleted `prompt1.txt` and `prompt2.txt`, removed preservation instructions, and
annotated the historical review with their retained Git revision. Dated review
data and prior validation records remain historical evidence.

Updated the GitHub description and added `computer-use` and `accessibility`
topics; verified visibility remains private. Kept the repository/package name
`private-agent-desktop` and left licensing undecided. The publication checklist
records those decisions and remaining release gates. This pass is documentation
preparation, not a full disclosure audit or a public release.

Validation: `uv sync --managed-python --locked` succeeded. Documentation checks
validated local Markdown links and anchors, balanced fences, JSON configuration
syntax and shell example syntax without execution. All 27 documented CLI
subcommand help checks passed; `git diff --check` passed. No desktop experiment
or paid model run was needed for this documentation-only change. Open the PR
against `main`, with no stacked dependency, and leave it unmerged.

## 2026-10-05 — Decisions on the review questions

The user delegated the review's open questions; decisions are in
docs/reviews/2026-10-05-project-review/decisions.md. In short: cooperative
same-user threat model; NixOS (project-local repaired runtime) plus Ubuntu 24.04
as the supported installations; one exclusive controller per session; no
automatic retries of non-idempotent actions; three account-free pilot tasks run
through MCP; no new paid comparisons. wlroots master (`c5c57cd3`) still lacks the
existing-buffer check at association, so runtime/UPSTREAM.md holds a proposed
merge request for the user to submit. The user's layout is US Dvorak, and
takeover still needs the user to confirm it works with that layout.

## 2026-10-05 — Session environment: credentials and working directory

Review F014. Applications now start in the session's private home instead of
the creator's working directory (previously often this checkout). Guarded
sessions also remove credential variables (SSH/GPG agents, Kerberos, netrc and
askpass helpers, GNOME keyring, cloud prefixes, names containing TOKEN, SECRET,
PASSWORD, API_KEY or CREDENTIAL), exempting AGENT_DESKTOP_* so the session
token that ownership depends on survives; `status` lists removed names, never
values. Tests: fake SSH/API/AWS variables absent in guarded and present in
unguarded sessions, PWD equals HOME, a classification unit test.

CI then failed `lifecycle_stress.py` on all three distributions (0/5): it passed
a relative fixture path, which now resolved from the session home. Relative
paths are a real interface question, so `launch` takes an optional absolute
`cwd`; the CLI sends the caller's directory (shell semantics), MCP and core
default to the session home, and the stress script uses absolute paths. Full
suite 84 OK, 5 skipped; stress 3/3 locally.
## 2026-10-05 — Bounded retention

Review F013 / plan step 4. Screenshots are pruned to the newest 200 per session
on each capture (`AGENT_DESKTOP_KEEP_SCREENSHOTS`). `usage` reports sessions by
status, session and screenshot bytes and profile bytes; `prune [--older-than
DAYS] [--dry-run]` removes only stopped/failed sessions whose supervisors are
gone, never live sessions or profiles. Tests: tests/test_retention.py (synthetic
state plus a real session keeping 3 of 6 screenshots). A working-day soak is
still to do.

Soak (`scripts/soak.py --minutes 60`, local Nix labwc 0.20.2): one persistent
session typed 8,913 numbered mixed-script lines through a terminal fixture with
screenshot tokens and 200 ms settle waits, all received exactly; 891 short
sessions were created, captured and destroyed with no leftover processes.
Worker RSS stayed at 36.9 MB from minute 5 to 60, process count at 4, and
latencies were flat (screenshot p95 55 ms, type/key p95 13 ms, wait p95 267 ms,
create p50 202 ms, destroy p50 414 ms). State grew about 70 KB per 5 minutes,
all from stopped short sessions (prunable). Worker CPU was a steady ~29% of one
core under this continuous load. Eight hours and an idle-session soak remain.

## 2026-10-05 — Preflight doctor

First step of the review's packaging milestone, independent of the choice of
distribution: `agent-desktop doctor [--smoke]` checks required and optional
tools, the runtime directory and socket-path length, accessibility, and the
wlroots version labwc loads, warning for stock 0.19.3/0.20.2 unless the repair
marker written by `scripts/build_xwayland_runtime.sh` sits beside the library.
`--smoke` creates, captures and destroys a session. CI runs it on all three
distributions. Locally (Nix labwc 0.20.2): warn for stock wlroots, missing
viewer tools and registry; smoke 1280x720 in 0.69 s; empty PATH fails with hints.

## 2026-10-05 — Review fixes: bounded listings, responsive MCP

F004/F017/F010. AT-SPI listings are bounded by listed nodes (application rows
included), visited nodes, depth (200) and a 3 s budget, reported as
`truncated_by`; the walk is iterative with cycle detection (a 5000-deep
synthetic tree raised RecursionError before). UI replies are trimmed below
200 KB and any reply over the 256 KB protocol limit becomes an explicit error.
MCP tools run in worker threads; the MCP test fails with synchronous tools
(`desktop_list` took 1.85 s behind a 2 s wait) and passes now.

## 2026-10-05 — Review fixes: profile lock, clipboard release, fixture race

F003: the profile lock is `profiles/.NAME.lock`, outside the deleted directory
and never removed; `delete_profile` holds it for the whole deletion, and a
worker that obtains it after a deletion fails instead of using a missing home.
F024: release clears the clipboard first; on failure control stays with the
person and the error is recorded (`release --force` overrides; automatic
release on viewer exit then waits for the person). F012: the terminal fixture
publishes typed.txt/mouse.json by rename. Tests: tests/test_release_profiles.py;
full suite 62 OK, 5 skipped.

## 2026-10-05 — Review fixes: waits, captures, sequences, UI ids

From reviews/2026-10-05-project-review (F005, F009, F011, F016, F036): `wait`
evaluates window, element and stability conditions together in one loop, scopes
element searches to the matched window, re-checks after the screen settles,
treats a truncated tree as unknown rather than gone, and validates the session
even for a plain pause (the timeout now explicitly counts after the pause). An
unstable capture raises instead of returning a token and keeps the post-takeover
screenshot gate. A sequence step that was delivered before observation failed
is reported as completed. UI ids are never reused after the map is cleared, and
unknown or expired ids are rejected. Tests: tests/test_correctness.py (no
desktop) and a two-dialog combined-wait test that the previous code fails.
## 2026-10-05 — Host guard and software GTK from the shell trial

Findings for the user's configuration were filed as nixos-config#417. Two
project changes follow from the trial: sessions set `GSK_RENDERER=cairo` (GTK 4
layer surfaces were blank with Vulkan in software sessions), and an opt-in
`guard_host` blocks the system bus and puts refusing, logging shims for common
host-affecting commands first on PATH. The trial showed why: panel buttons run
`systemctl poweroff`, `nmcli`, `pkill wlsunset` (which would match host
processes) and `systemd-inhibit`. Opt-in because blocking the system bus may
degrade some applications; not a security boundary. `tests/test_guard.py` uses
only harmless probes (`systemctl --version`, `pkill -0` on a missing name). Full
suite: 61 OK, 5 skipped (Nix runtime incl. mousepad, zenity, kdialog, Chromium).
## 2026-10-05 — First real-use trial: the user's desktop shell

Independent review saved in `docs/reviews/2026-10-05-project-review/`;
it recommends daily-use hardening before more features. As the first real task
the user chose their waybar, control panel and launcher. Harness:
`scripts/shell_trial/` (fake Hyprland IPC, logging stand-ins, trial copies under
git-ignored artifacts). Results and findings: `docs/trials/2026-10-05-desktop-shell.md`.
Project lessons: nested Hyprland is not usable inside labwc (aquamarine commits
before ack_configure) and probes real input/DRM devices unless contained; GTK 4
layer surfaces need `GSK_RENDERER=cairo` in software sessions; command audits
must parse code, not grep it; one unexplained hidden-bar observation remains.

## 2026-10-04 — Tool profile comparison

See docs/BENCHMARK.md (tool profile comparison). Fixes found by it are on branch
`m4/tool-comparison`. Round 3 was first cut off by the Claude usage limit and
re-run on 2026-10-05: standard 20/20 at $1.41 and hard 10/10 at $0.89 with full
tools, cheaper than the basic profile on both suites. CI for the branch passed on
all three distributions. A later docs-only push failed Fedora
`test_actions.test_steps_run_in_order` (CI `37243415314`): text '' but Return
delivered, the same symptom as closed #17. Likely cause: typing began before the
new foot window had keyboard focus (keys before `wl_keyboard.enter` are dropped)
because the fixture waited only for its process plus 0.4 s. The fixture now waits
for the window's `activated` state; 5/5 local runs. Agents are less exposed since
they act from screenshot tokens, which include activation state.

## 2026-10-04 — Waiting for UI elements (verified outcomes)

Plan extension A ("verified outcomes"): `wait` / `desktop_wait` accept `element`
(accessible-name substring), `role` (exact) and `text` (substring of text or
value), polling `ui` every 0.2 s after any window condition and before
`stable_ms`; `gone` applies to the element when no window condition is given.
Results include up to five matching elements. Usable as a `wait` step in action
sequences. Test: a zenity entry set via `set_text` is found by role and text,
an absent element times out with `no element`, and after pressing OK the button
is reported gone. The race this exposed (tree read during window close) is fixed
in the semantic UI branch. During this work a local `git checkout --theirs .`
discarded uncommitted changes; they were restored from the dangling stash commit.

## 2026-10-04 — Semantic UI through a private AT-SPI registry

Plan extension A ("semantic UI"). Spike first (scratch script, jeepney): the
session's private D-Bus activated `at-spi-bus-launcher`, giving an a11y bus inside
the session runtime directory, but (1) applications registered nothing because the
host sets `NO_AT_BRIDGE=1` and `GTK_A11Y=none`, inherited by sessions; and (2)
activating `org.a11y.atspi.Registry` failed (`unit failed`) without a systemd user
session. With the variables removed and `at-spi2-registryd` started by the
session, zenity (GTK 4) and Mousepad (GTK 3) trees were readable. Extents are
window-relative on Wayland, so actions use AT-SPI rather than coordinates.

Implementation: `atspi.py` (pure-Python `jeepney`, new dependency) reads the tree
(roles, names, selected states, text up to 500 characters, values, actions;
hidden subtrees and unnamed containers skipped; max 2000 nodes) and performs
press (case-insensitive click/press/activate/toggle/jump), focus (GrabFocus) and
set_text (EditableText). The worker finds `at-spi2-registryd` (libexec paths or
`AGENT_DESKTOP_AT_SPI_REGISTRYD`), removes the two variables and sets
`QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1` in the session only, adds the matching
`share` directory to `XDG_DATA_DIRS` so the private bus can activate the bus
launcher (needed for Nix), and owns the registry process. GTK 4 differences found
while testing: object paths outside `/org/a11y/atspi/accessible`, capitalised
action names, empty "generic" containers and many `clipboard.*` widget actions
(hidden from listings, still callable).

### Validation

Nix at-spi2-core 2.60.6 via `AGENT_DESKTOP_AT_SPI_REGISTRYD`, zenity 4.2.2:
`tests/test_ui.py` 3/3 runs — fill a zenity entry with `set_text` (Unicode),
observe the text in the tree, press OK, and zenity prints the value and exits 0;
label without press action and malformed ids are refused; filters and the node
limit; a session without a registry reports the missing runtime. Full suite with
accessibility on: 53 tests OK, 7 skipped. CI installs `at-spi2-core`.

Chromium (153, Nix) registered nothing with `--force-renderer-accessibility`
alone; it also needs `ACCESSIBILITY_ENABLED=1`, now set in accessible sessions.
Its localized action names are empty, so names come from `GetName`; every node
offers `showContextMenu` (hidden) and `doDefault` (does not keep a container).
It lacks `SetTextContents`, so `set_text` falls back to GrabFocus, waiting for
the `focused` state, Ctrl+A and typing with the session keyboard (reported as
`method: keyboard`). A local form: 29 nodes listed in 338 ms; the Email field was
filled, "Sign in" pressed and the page title confirmed the value.
`tests/test_ui.py` now includes that Chromium flow; 3/3 runs.

Qt 6 kdialog 26.08.1 (Wayland): input dialog tree read, `set_text` and OK press
worked natively; added as a test.

Reading the tree while a window closed failed with `No such interface ... Accessible`
(found by an element-wait test); vanished elements and applications are now
skipped instead of failing the whole listing.

CI `37232451508` (commit adding `ACCESSIBILITY_ENABLED`): Fedora failed
`test_chromium_receives_every_character` once (title never showed the typed
text); the next two runs passed on all distributions and 10/10 local runs with
accessibility on passed. Cause unknown; the test now reports the window titles
and saves diagnostics on failure.

Not verified: LibreOffice, Electron apps, latency of large trees.

## 2026-10-04 — Partial and scaled screenshots

First step of plan extension A ("adaptive observation": crops and full images on
demand). `screenshot` accepts `region` [x, y, w, h] (validated against the current
output) and `scale` 0.1–1, passed to grim as `-g` and `-s`; results include both.
The observation token is unchanged by cropping. `tests/test_capture.py` checks
image sizes for region, scale, both and a 1×1 corner, identical tokens, and nine
invalid arguments. Token savings for agents are not measured yet.

## 2026-10-04 — Bounded action sequences

Plan extension A ("bounded action sequences"). `core.run_actions` /
`desktop_actions` / `agent-desktop actions` run up to 50 click, move, drag, scroll,
type, key, focus and wait steps. A new worker `observe` operation returns the
layout token without capturing an image; each input step is sent with the token
observed right after the previous step (the caller's screenshot token for the
first), so the worker refuses it if windows, focus or output changed. `wait` and
`focus` re-baseline. The run stops at the first failure and reports
`{completed, total, stopped: {step, reason}}`. No token is returned, so agents
still need a screenshot before acting on new state. Remaining race: a change
between the check and delivery of one step; popups (not toplevels) and in-window
changes are invisible to the check.

### Validation

`tests/test_actions.py` 3 tests: ordered typing with Unicode; a wait step for a
window launched just before the call, then typing into it; stale first token,
failing wait and unknown focus target all stop before input (no text reached
either fixture); argument validation. Agent call savings not measured yet.

## 2026-10-04 — Paste into a takeover; clear the clipboard on release

`agent-desktop take --paste` starts TigerVNC with `-SendClipboard=1` (primary
selection still off; the session clipboard is never accepted by the host). On
every release the worker clears the clipboard and primary selection through
`ext_data_control_manager_v1` or `zwlr_data_control_manager_v1`
(`set_selection(null)`), logging rather than failing if unavailable.

The first test passed even with clearing disabled: the pasted text is owned by
wayvnc's data-control source and vanishes when the takeover server exits anyway.
Clearing matters when an application copied the text again. The test now has a
`wl-copy --foreground` owner during takeover, checks `wl-paste` before and after
release, and fails with clearing disabled (`'copied-secret' != ''`). A separate
test sends RFB ClientCutText and pastes with Ctrl+Shift+V into the foot fixture.
CI installs `wl-clipboard` on all three distributions.

## 2026-10-04 — Event-aware waiting

Plan extension A ("event-aware waiting"). New worker operation `frame` captures
raw RGB through `grim -t ppm -` (no file) and returns the bounding box changed
since an earlier frame (four kept in memory). `core.wait` / `desktop_wait` /
`agent-desktop wait` wait for a window by title substring and/or exact app_id (or
for none, `gone`), then optionally for `stable_ms` without changes larger than
400 px², so a blinking caret does not prevent settling. Timeout at most 120 s;
it returns `satisfied: false` with a reason rather than failing. Waiting runs in
the client, so the single-threaded worker stays responsive (e.g. to `take`), and
it is refused while a person has control.

### Validation

- `tests/test_wait.py`: changed-box unit cases; window appear/settle/`gone` after
  Alt-F4; a continuously printing terminal never settles (returns within the
  timeout); frame regions; argument validation; Chromium focused input with a
  blinking caret settles (observed caret box 1×33 px). Frame capture took about
  62 ms at 1280×720 locally.
- Full suite: 44 tests OK, 8 skipped (Nix labwc/foot/wayvnc/dbus/xwayland/xterm).

Not measured: whether agents use fewer calls or less time with it (needs model
runs; deferred to save the user's usage).

## 2026-10-04 — Takeover and profiles integrated; agent instructions

#29 (takeover) passed CI `37222504707` on Ubuntu, Fedora (wayvnc 0.9.1) and Arch
(wayvnc 0.10.2), including `test_takeover`, and was merged. #30 (profiles) passed
CI `37223010959` on all three and was merged. Graceful teardown lengthened the full
suite by about 20–25 s on Ubuntu and Arch (applications that do not close within
3 s now wait up to 2 s more after SIGTERM); Arch's 100 loaded X11 repetitions took
6 min versus 4 min in the previous run, within earlier variation (272–367 s).

Issue #17 was closed: no Ubuntu recurrence in 18 `runtime` jobs since #23, each
running the focus test 11 times. The original cause remains unproven.

The MCP server now sends instructions (shown to clients such as Claude Code)
covering the screenshot/act/verify loop, the login handoff and profiles; the MCP
test checks they arrive through the stdio transport. Not yet observed with a real
agent run, to save the user's limited usage.

## 2026-10-04 — Persistent login profiles

Stacked on the takeover branch. `create --profile NAME` / `desktop_create(profile=)`
uses `profiles/NAME/home` as `HOME` instead of a per-session directory, which
teardown does not remove. The worker holds an exclusive `flock` on the profile for
the session's lifetime (released by the kernel if it dies); `create` also checks it
first for a clear error. `profiles` lists them; `delete-profile` refuses one in use.

The first Chromium cookie test failed: the cookie never reached the profile's
`Cookies` database, and a dangling `SingletonCookie` showed an unclean exit.
Causes, found by instrumenting teardown: the compositor was stopped before
applications, and a first fix sent SIGTERM to the process group, stopping
Chromium's zygote first. Fix: teardown now closes every window through
foreign-toplevel `close` (before the worker's own Wayland clients are closed),
waits up to 3 s, then sends SIGTERM to the launched process only and waits up to
2 s before the existing compositor/process cleanup. After it, the cookie row
existed (encrypted with the basic store) and a second session sent it.

### Validation

- `tests/test_profiles.py` 3/3 runs: invalid names; marker file persists into a
  second session; concurrent use and deletion refused; unprofiled session cannot
  see it; delete; Chromium persistent cookie set in one session is sent by the
  next (local HTTP server, mode 0700 home).
- Full suite: 39 tests OK, 8 skipped (Nix labwc/foot/wayvnc/dbus/xwayland/xterm).

Not verified: real third-party logins (deliberately not attempted); other
browsers; applications that store absolute runtime paths in their profile.

## 2026-10-04 — Human takeover for logins

The user chose takeover as the way to handle logins, 2FA and CAPTCHAs. Sessions
now have a control owner. `desktop_request_human` (MCP) or `request-human` (CLI)
records a reason that `list` shows. `agent-desktop take SESSION` starts a second,
input-enabled wayvnc on `takeover.sock` (the observer keeps `-d`) and opens
TigerVNC without `-ViewOnly`; clipboard transfer stays disabled. While a person holds
control the worker refuses input, focus, launch, window listing and screenshots.
Release (closing the viewer, the server exiting via `-e` when supported, or
`release`) increments the control epoch, which is part of every observation token,
and requires a new screenshot before input or focus. MCP has no release tool.

### Validation

Nix `labwc 0.20.2`, `wayvnc 0.10.1`, `foot`, `dbus`, `xwayland`, `xterm`:

- `tests/test_takeover.py` 5/5 runs: refused agent operations, a raw RFB client
  typing into the fixture, automatic release on disconnect, stale old token,
  required screenshot, mouse delivery, then agent Unicode typing with its own
  keymap after wayvnc's keyboard was used; destroy during takeover; validation.
- Real TigerVNC 1.16.2 viewer run inside a second private session (so nothing
  appeared on the host): its typing reached session A, closing it returned control
  (`viewer disconnected`), both sessions stopped with runtime removed.
- Full suite: 36 tests OK, 8 skipped (visible, Chromium, office/editor tools absent).

Not verified: Ubuntu's older wayvnc without `--exit-on-disconnect` relies on the
CLI's explicit release (CI will show); non-US host layouts; visible mode, where the
nested window already accepts host input regardless of owner.

## 2026-10-04 — Both repaired runtime versions pass

Source head `7766302`, CI `37215643286`: Ubuntu/Fedora/Arch all passed.
Fedora's private wlroots 0.19.3: full 33-test suite in 41.784 s (visible skip),
100/100 Xterm Unicode and mouse trials with four CPU-load processes in 141.146 s,
then lifecycle stress. Arch's private wlroots 0.20.2: full 33-test suite in
62.149 s (visible skip), 100/100 loaded Xterm trials in 367.224 s, then lifecycle
stress. Both copied compositors resolve the intended project-local library;
source checksums and patch application were verified. Ubuntu retains stock
runtime and passed its suite, focus/crash/input repetitions and lifecycle stress.

The completed comparison used $1.0474778 of the authorized $5, with 6/6 browser
tasks passed per runtime; no further model trials were run during the repair.
Stock wlroots 0.19.3/0.20.2 remain affected. The repair must be explicitly selected,
is not upstreamed, and has not been validated in visible mode or arbitrary X11
applications. Historical successful stock runs remain evidence of those runs,
not a guarantee. Human takeover/action ownership is the next implementation stage.

## 2026-10-04 — Extend mapping repair to Fedora's wlroots 0.19.3

Final documentation head `441ff30`, CI `37214999497`: stock Fedora passed
its full suite, then failed X11 mapping on repetition five (four passed).
Retained root properties match Arch: X11 fixture in the stacking list, no
mapped client list, active window zero and no foreign-toplevel. Fedora uses
labwc 0.9.6 / wlroots0.19 0.19.3, whose association/commit logic has the same
missing existing-buffer check. Thus earlier Fedora stock passes do not establish
that this failure is limited to 0.20.2. Artifacts: artifacts/ci-37214999497.

Extended the private runtime script to select only the explicitly pinned
0.19.3 or 0.20.2 source based on the installed labwc library ABI, and verify
its development package version. SHA-256 for 0.19.3:
`a6ff89b64ea15e424d1b0db4a22145fccf5ec2ff2e7b8af0fa35e2ac8975986f`.
The identical patch applies to 0.19.3 without fuzz (48-line offset). Fedora CI
now builds its matching private repair and runs 100 X11 repetitions with four
busy processes, as on Arch. Ubuntu retains stock runtime. No retries, assertion
changes or host loader/configuration changes. The first Fedora build (`37215444164`) stopped during Meson configuration:
`pkgconfig(xwayland)` was missing despite the executable being installed. Added
Fedora's `xorg-x11-server-Xwayland-devel`, which provides xwayland.pc; kept X11
support required rather than allowing a silent disabled build. Checks are pending.

## 2026-10-04 — Repaired runtime passes distribution validation

Source head `c63b109`, CI `37214448862`: Ubuntu, Fedora and Arch all passed.
Arch built the pinned patched wlroots 0.20.2 from source and verified the copied
labwc resolves its private library. Full suite: 33 tests, 50.304 s, visible skip.
Then 100/100 Xterm Unicode/mouse sessions passed with four busy CPU processes in
272.115 s, followed by lifecycle stress. Ubuntu/Fedora retained stock packages
and passed their full suite/repetitions/lifecycle checks. Local patched runtime
passed 150 loaded sessions (one buffered-at-association recovery), 100 warmed-XWM
loaded sessions, and the full suite. A final scan of 274 retained local manifests
found every session stopped/failed, no surviving runtime paths or process tokens.
All helpers/containers used for this stage are stopped; the comparison image was
removed. No additional model runs: total remains $1.0474778 of $5 authorized.

The patch is an optional runtime build, not a silent host installation or an
upstream fix. Stock 0.20.2 remains affected. Visible-mode repair behavior and
broader X11 applications are unverified; issue #17's earlier Ubuntu focus
failure may have a separate cause. Next implementation priority is explicit
human takeover/action ownership, followed by broader application coverage and
matched-environment comparisons. More account-using trials need a new scoped
budget if they go beyond this completed comparison.

## 2026-10-04 — X11 buffer-before-association repair

Latest PR #28 head `5e24a10`, CI `37211305391`: Ubuntu/Fedora passed;
Arch passed the full suite but failed its first X11 repetition. Retained root
properties show a live XWM and X11 fixture window, but `_NET_ACTIVE_WINDOW=0`,
no `_NET_CLIENT_LIST`, and no foreign-toplevel. Checks remain required.

A project-local X11 readiness/EWMH probe did not resolve mapping: four-CPU-load
runs passed 33 then failed on session 34, and passed 54 then failed on session 55.
The latter retained `WAYLAND_DEBUG=server` traffic. Moving the private pointer
and opening a native foot window did not release the stuck Xterm. The trace
shows the Xwayland surface buffer commit before association. Removed the
unsuccessful readiness implementation; its source and diagnostics remain under
ignored artifacts/x11-readiness-experiment and artifacts/x11-map-probe.

wlroots 0.20.2 attaches its commit listener during association and maps only on
subsequent commits. Added a six-line patch checking an already committed buffer
after the association event. A project-local Nix build of patched wlroots and
labwc 0.20.2 passed 150/150 Xterm sessions with four busy CPU processes in
185.860 s; one log explicitly hit buffered-at-association mapping and then
received exact Unicode text and a click. All test desktops were destroyed.
Artifacts: artifacts/x11-patched-load and x11-readiness-experiment/repeat-patched.log.
This demonstrates the diagnosed ordering is recoverable, not universal reliability.

Added an optional portable runtime build script (pinned source archive SHA-256,
new project-local output, copied labwc with a private library path) and configured
Arch CI to use it. Ubuntu/Fedora stay on stock packages. No Python linker paths,
host configuration, activation, profiles or permissions were changed. The
comparison remains complete at $1.0474778; no more paid trials were run.
Patched full suite: 33 tests in 61.067 s, all applicable checks passed, visible
mode skipped. Additional warm-XWM experiment: private `xprop -root -spy` stayed
connected before each Xterm launch; 100/100 loaded sessions passed in 123.715 s
with protocol logging. No buffered-at-association events occurred in that set;
the initial 150-session set contains the observed recovery. Two initial helper
runs stopped before any application trial (missing import path / xprop executable)
and were corrected without changing the runtime. Test cleanup and load-helper
termination completed. First portable-build CI `37214209581` compiled/installed the patched library,
but the loader check failed before desktop tests. Its exact-path grep failed
because `$ORIGIN/../lib` retains `bin/../lib` in ldd output (confirmed with a
local copied binary). The check now prints dependencies and compares canonical
paths; it still requires the private library, rather than removing verification.
Repaired distribution CI remains pending at this commit.

## 2026-10-04 — Repeated comparison complete within budget

Second container set `20261004-154321-3049`, seed 41028, claude-opus-5-5,
$0.40/task cap: code-and-drag passed (7 calls, 11.4 s, $0.069611); form
passed (11 calls, 15.7 s, $0.0924884); confirmation passed (7 calls, 16.7 s,
$0.0916244). No tool/setup/cleanup errors. Committed after this final batch.

Across two sets of three tasks: native 6/6, 46 calls, 104.7 s, $0.5183458;
Cua 6/6, 49 calls, 84.0 s, $0.529132. Combined $1.0474778, below the user
limit of $5 including the initial pair. Saved compact per-trial metrics in
benchmarks/results/2026-10-04-browser-comparison.json; all six matched page
pairs have equal hashes. Screenshot dimensions and token/caching counters are
preserved. All trial sessions/containers were removed.

Inspected Cua confirmation observations 2 and 3: a dimmed page before the
prompt is drawn, then the visible prompt. Extra screenshots account for its
additional calls; there is no repeated deletion action. Both API error counts
are zero, which does not establish semantic UI/frame readiness. Costs are nearly
equal, and unmatched environments, resource caps, cache and sample size prevent
a causal performance claim. No additional account-using runs are needed for
this comparison. Removed the exact pinned image again after the last trial,
leaving 184 KiB of project VFS metadata, and stopped only the matching API
process; it exited successfully. No trial containers remain. PR #28 final
checks passed on Ubuntu, Fedora and Arch at `1f6b417` in run
`37210945368`, including the full 33-test suite (visible skip), repeated X11
input and Ubuntu focus/crash/lifecycle checks.

## 2026-10-04 — Second native comparison set

Run `20261004-154125-494e`, seed 41028, claude-opus-5-5, $0.40/task cap:
code-and-drag passed (7 calls, 23.0 s, $0.0800196); form passed (11 calls,
17.5 s, $0.1061416); confirmation passed (5 calls, 13.4 s, $0.0721344).
No tool/setup/cleanup errors. Native has 6/6 verified trials across two sets;
comparison cumulative usage is $0.793754. Committed after this batch before
the second container set. Time varies even with identical tool counts.

## 2026-10-04 — Container form/confirmation comparison results

Run `20261004-153931-af37`, seed 41027, claude-opus-5-5, $0.40/task cap:
form passed (11 calls, 15.7 s, $0.0925628); confirmation passed (6 calls,
12.3 s, $0.0790968). No tool/setup/cleanup errors. Comparison cumulative
usage is $0.5354584; committed after this batch. First set: each runtime
passes all three tasks. A second set remains; timing is still confounded by
runtime, browser, resource and cache differences.

## 2026-10-04 — Native form/confirmation comparison results

Run `20261004-153647-ba09`, seed 41027, claude-opus-5-5, $0.40/task cap:
form passed (11 calls, 25.2 s, $0.107764); confirmation passed (5 calls,
12.6 s, $0.0719224). No tool/setup/cleanup errors. Comparison cumulative
usage is $0.3637988 including the original pair; committed after this batch.
Container dry setup overlapped this batch; do not infer isolated timing.

Source CI `37209785159` passed on Ubuntu, Fedora and Arch: full 33-test suite
(visible skip), repeated X11 input, and Ubuntu focus/crash/lifecycle checks.
Debug logging is enabled for test sessions. This does not prove the intermittent
X11 mapping cause is fixed; assertions remain and diagnostics capture recurrence.

## 2026-10-04 — Broader comparison budget and controls

User selected broader comparison with a $5 API-equivalent total limit.
Include the existing $0.1841124 pair. Plan code-and-drag, form and confirmation
on each runtime twice: ten additional task runs at a $0.40 cap give $4.1841124
including the pilot, leaving a buffer for final-response budget overshoot.
Keep seed 41027 for the first set and 41028 for the second randomized code.
Track actual cumulative usage after each batch; no new account is configured.

Native three-task negative control `20261004-153446-bedd`: all checks fail
as intended, no setup/cleanup failures. The existing X11 mapping failure is
not in these Wayland browser fixtures; diagnostics are running in CI, with
assertions preserved. Container three-task negative control `20261004-153700-9597`: all checks
fail as intended, no setup/cleanup errors. Generated pages match the native
negative-control pages byte for byte. Broader model results follow below.

## 2026-10-04 — X11 mapping failure recurs during baseline CI

PR #28 runs `37209103464` and `37209247332`: Ubuntu/Fedora passed, Arch failed.
The latter retained xterm status: application and Xwayland alive, display :0,
no mapped foreign-toplevel window. A GTK/X11 dialog also failed activation.
The explicit installed terminal font produces no missing-font warning, so it
did not resolve the mapping failure. Native Wayland and office tasks passed.
No root cause established; issue #17 remains open and checks are not waived.

CI test sessions now start labwc with debug logs and failed X11/dialog tests
retain scoped X11 root properties/window trees, status, windows and screenshot.
Diagnostic commands run only through the explicit private session environment;
errors are recorded without masking the original failure. Production runtime
behavior and assertions are unchanged. User selected broader comparisons with
up to $5 API-equivalent total; the existing paired pilot uses $0.1841124 of it.

## 2026-10-04 — Paired browser baseline pilot

Container pilot `20261004-151945-3d34` passed the same code-and-drag fixture
as native `20261004-151912-01e9`, seed 41027, claude-opus-5-5, $1/task cap.
Cua: 7 calls, 0 errors, 12.2 s, $0.1037486 API-equivalent; native: 7 calls,
0 errors, 13.0 s, $0.0803638. Both use 3 screenshots, 2 clicks, 1 type and
1 drag. Final screenshots and independent title verifiers agree; no model
shell/file/launch tools are exposed. All owned containers were removed.
After deleting local:baseline-probe, an actual stdio type call returned a
not_found error. Removed the exact pinned image from the project-only store,
reducing its VFS footprint from roughly 41 GiB to 184 KiB, then stopped only
the API process whose argv matched the project root and Unix endpoint. The
service exited successfully. Screenshot/report artifacts remain; future runs
must pull the pinned image again using their configured policy.

The Cua image startup took 16.2 s with cached image/VFS storage; native startup
was not timed. Source preparation, native result and container result were
committed separately. Usage remains the previously authorized testing client's
Pro allowance, not a newly configured API account. Future records now retain
raw token usage and per-model accounting. A single pair with different desktop,
browser, resource caps, screenshot scaling and cache counters establishes no
performance winner; exact differences and counters are in docs/BENCHMARK.md.

## 2026-10-04 — Local container baseline preparation

Added a GUI-only, fixed-local-target stdio adapter and a fresh-container harness
for three existing browser fixtures. Routing tests reject target overrides and
shell/file/launch/accessibility/session tools, preserving upstream results.
Both code-and-drag dry runs fail verification with no errors or leftovers:
native `20261004-151706-01ca`, container `20261004-151705-1f13` (29.1 s startup).
Both use seed 41027 and identical generated pages.
Native pilot `20261004-151912-01e9`, claude-opus-5-5, $1 cap: passed,
7 tool calls, no errors, 13.0 s, $0.0803638 API-equivalent, clean teardown.
Committed after this run before the corresponding container model run.

Project-local Podman 5.8.7 rootless VFS storage and its Unix API socket work with
existing user namespaces; no host permissions/configuration changed. Fetched
Podman and slirp4netns runtime tools using Nix without profile installation.
Downloaded Cua CLI 0.3.1 from its public release, checked SHA-256
`c5b3de47a8fca33e6f943c682dd3f243d7696a795d7f267119f2625617e46be3`
against the release manifest; the installer was reviewed, not executed.
All state is under ignored `artifacts/container-probe`; DO_NOT_TRACK=1.

Cua create initially failed because Podman had no default signature policy.
A project XDG_CONFIG_HOME policy did not change that lookup, and the global
--signature-policy flag is unsupported. Explicit `podman pull --signature-policy
<project-policy> <pinned-digest>` succeeded; Cua then used the cached image.
The policy rejects all images except the exact ghcr.io/trycua/linux repository;
TLS verification remains enabled. No user/system policy was written.

Actual adapter round trip on local:baseline-probe: image blocks received,
Unicode `café λ 123` typed and submitted; final screenshot and X11 title show
Task - complete. An attempted host target override returns an error. Host
active-window address and cursor snapshots match before/after; transient host
changes are not covered. The smoke container was deleted. The environments and
restricted tool access differ and are documented in docs/BENCHMARK.md; no
performance or superiority conclusion is established.

## 2026-10-04 — Xwayland fixture diagnostics and repetition

PR #27 CI run `37206984363`: Ubuntu and Arch passed; Fedora's existing
Xwayland test found no mapped window. Its retained `windows.json` is empty
and screenshot is black; xterm stderr warns that the default fixed bitmap font
is missing. This is evidence of the failure, not proof of its cause.

Select installed DejaVu Sans Mono explicitly in the test and Xterm benchmark
fixture, and retain full session status alongside window state and screenshot
on failure. CI now repeats Xwayland mapping/input ten times on all three
distributions. Local repeat: 10/10 passed in 10.465 s with xterm 411 and
Xwayland 24.1.13. Ruff lint/format passed. Final CI run `37207779152` passed on Ubuntu,
Fedora and Arch, including all ten Xwayland repetitions per distribution.
PR #27 was squash-merged at `1ad27ae`; the failure cause remains unproven.

## 2026-10-04 — M4 office benchmark preparation

Added an office suite with Writer document creation and Calc SUM entry checked
from saved files. It reuses the independently validated office verifiers, starts
fresh private profiles, and leaves first-run dialogs for the agent to handle.
Integrated CLI dry run `20261004-144149-180e`: 0/2 passes as intended, no setup
errors or cleanup failures. Earlier direct-harness negative control:
`artifacts/office-benchmark-dry/6773c191a324/report.json`.

One sparing model run with the existing $1/task cap, `20261004-144403-9eec`:
claude-opus-5-5 passed both tasks. Writer: 13 calls, 22.8 s, $0.181 API-equivalent;
Calc: 7 calls, 14.7 s, $0.083. Total 20 calls, 37.5 s, $0.264; no tool errors or
cleanup failures. First-run prompts were handled through the GUI. Usage came
from the previously authorized testing client's Pro allowance; no new paid API
account was configured. Committed preparation before the run and results after it.

Benchmark tools now explicitly exclude session creation, destruction and process
launch: the harness owns those, and tasks already have their applications open.
This also prevents substituting a launched script for the requested GUI edits.
The installed CLI's help confirms the `--disallowedTools` option. Earlier task
runs had broader tool access; this policy difference must be reported in any
comparison. Ruff lint/format and diff checks passed.

PR #26 passed Ubuntu, Fedora and Arch CI in run `37206326007` after the explicit
Calc Name Box selection, and was merged. Rapid arrow navigation remains an
observed limitation, with no proven cause; the stricter file verifier was kept.

## 2026-10-04 — M3 LibreOffice Writer and Calc

Added `scripts/office_smoke.py` and two real-application integration tests. Writer
creates Unicode text and saves it through the GTK dialog to a Unicode ODT path;
the verifier reads the saved OpenDocument paragraphs. Calc opens a small seeded
ODS, enters `=SUM(B2:B3)` in B4 through keyboard input, and saves it; the verifier
requires both the stored formula and calculated value 20, with the original
labels and amounts intact. The seed without the formula must fail verification.
Both workflows capture before/after screenshots and check session cleanup.

Applications are forced to native Wayland with the GTK3 backend and get an
explicit per-session UserInstallation profile. Initial probes typed into the
splash/first-run dialog rather than a ready document. The harness now waits for
the actual document, handles known Welcome/Tip dialogs during a three-second
startup observation period, and checks document focus. This finite startup
observation and the 300 ms file-path validation delay are fixture assumptions,
not universal widget-readiness guarantees. Unknown modals lead to failed checks.

Local smoke: both workflows passed with LibreOffice 26.8.0.3 and labwc 0.20.2,
report `artifacts/office/46d5cf42811b/report.json`. A separate Calc probe verified
the exact `of:=SUM([.B2:.B3])` formula and cached value `20`. LibreOffice was fetched
with `nix build --no-link --print-out-paths nixpkgs#libreoffice` as a runtime tool
(513.5 MiB download, no profile install or host activation); Python still uses uv.
Full local suite: 31 tests in 54.455 s, 30 passed and visible mode skipped.
Ruff lint/format and compileall passed. Both office tests also passed three
repetitions each with four busy CPU processes (6 tests in 51.296 s). Office CI
validation is pending.

First office CI (`37205919528`): Ubuntu and Arch passed; Fedora Writer passed,
but Calc saved the formula in A2 rather than B4 and correctly failed the unchanged
verifier. Its retained ODS proves wrong targeting; the cause of the lost/changed
rapid arrow navigation is not established. The scripted workflow now selects B4
explicitly through Calc's documented Name Box shortcut (`Ctrl+Shift+F5`) and
records a screenshot before formula entry. Two 200 ms focus-transition fixture
delays are explicit. Reference: [Calc keyboard shortcuts](https://books.libreoffice.org/en/CG262/CG26218-KeyboardShortcuts.html).

PR #25 passed Ubuntu, Fedora and Arch on its final source commit (run
`37205271460`) and was merged. Its earlier Arch Xwayland activation timeout
did not recur; no cause is established. Timeout diagnostics remain in the test.

## 2026-10-04 — M3 editor file dialogs and private clipboards

Added real Mousepad tasks to the compositor suite: open a Unicode filename in a
directory with spaces through the GTK chooser, replace the document, save, and
Save As to another Unicode filename; independently verify both files. Two
simultaneous sessions copy distinct Unicode text, clear/save their documents,
then paste/save. Exact file contents demonstrate that the second session's copy
does not replace the first session's clipboard. Screenshots retain visual
evidence and normal lifecycle teardown checks owned processes.

Initial Open attempts failed. Screenshots and a slower controlled experiment
showed GTK's asynchronous location-entry creation and path validation. The test
uses explicit 200/300 ms fixture delays at those transitions. Input APIs have
not gained widget-readiness guarantees; semantic readiness remains open.

Local validation (Mousepad 0.7.0, labwc 0.20.2): both tasks passed five repetitions
each (10 tests in 31.415 s). Full suite: 29 tests in 41.321 s, 28 passed and visible
mode skipped. Ruff lint/format and diff checks passed. Existing runtime binaries
were supplied through command-local PATH. CI now installs Mousepad on Ubuntu,
Fedora and Arch. In run `37203685617`, the new editor tasks passed on all three;
Ubuntu/Fedora jobs passed, but Arch's existing Xwayland test timed out waiting
for its terminal's activated state. Its child had reached the ready marker;
retained logs showed a missing fixed-font warning but did not establish cause.
The test now retains window state and a screenshot at this timeout. Full-stage
CI is being rerun before integration. No personal profiles or host changes used.

## 2026-10-04 — Wait for guardian exit in crash-cleanup test

Downloaded and inspected `desktop-tests-runtime-0` from failed Ubuntu run
`37168329845`. The unexpected token-bearing PID, 4177, exactly matches
`guardian_pid` in the retained session manifest. The guardian had stopped its
children and published failure but had not exited when the assertion ran. The
test now waits (with the existing ten-second deadline) for that specific guardian
to stop, then still requires zero token-bearing processes. It continues checking
the token-less child immediately after failure publication, so child cleanup is
not excused by this wait. Ubuntu CI repeats both the focus and guardian-crash
tests ten times and preserves the first failure. Runtime code is unchanged.

Local validation: Ruff lint/format and diff checks passed; ten repetitions of
`test_killed_supervisor_is_cleaned_up_by_guardian` passed in 5.412 seconds on
NixOS with labwc 0.20.2. CI passed on Ubuntu, Fedora and Arch in run
`37202851514`, including ten Ubuntu guardian crashes and 200 focus switches.

PR #23 passed Ubuntu, Fedora and Arch CI in run `37202636884` and was merged.
Ubuntu's ten repetitions verified 200 immediate focus/type switches. Issue #17
remains open because its original failure's cause is unproven.

## 2026-10-04 — Verify focus before reporting success

`focus` previously confirmed only that the compositor processed an activation
request. It now waits for the requested window's `activated` state, returns the
observed window, and fails if the window closes or activation is not observed
within a two-second polling deadline. This confirms compositor state, not
application input readiness; focus can still change after the response.

Validation on NixOS, labwc 0.20.2: `uv sync --locked --managed-python`, Ruff lint
and formatting, and the full headless unittest suite: 27 tests, 26 passed, one
visible-mode test skipped. Runtime binaries were supplied from existing Nix store
paths through the command's PATH; no packages or host configuration were changed.
The new real-terminal test switches focus 20 times and immediately types ASCII
and Unicode text; each terminal received exactly its ten intended lines. Tests
also cover delayed activation, refused activation, a closing target and unknown
targets. Ubuntu CI repeats the real-terminal test ten times (200 focus switches).

Issue #17 remains open: its original Ubuntu failure has no proven cause, and
observed activation does not establish that this change fixes it. CI passed on
all three distributions in run `37202636884`. No model-account usage or physical desktop interaction
was needed.

Recent-history review also found a separate Ubuntu failure on main in run
`37168329845`: `test_killed_supervisor_is_cleaned_up_by_guardian` observed one
token-bearing PID after the manifest became `failed`. The next main run passed.
This needs separate investigation of cleanup completion versus status publication;
it is outside this focus stage and was not reproduced locally.

## 2026-10-04 — M4 hard benchmark tasks

Added 10 harder tasks (`benchmarks/hard.py`). They cover multiple applications per
session, a multi-page admin site, an interrupting modal, a delayed result, chart
reading, the GTK open dialog, a shell batch rename, comparing two editor windows,
a focus-stealing warning and validation recovery. The runner now launches
several applications per task. Validation: dry run with every check failing
(`20261004-023751-0e0c`), and `node --check` on all 17 fixture scripts. The run-1
fixture bug had caused an impossible task, so this was checked first. One agent run:
10/10, 121 tool calls, $1.24 API-equivalent (`20261004-023853-8b72`). The user's
Claude Pro allowance is limited, so only one pass was made. The user asked for a
later comparison with public projects such as Cua; it is recorded in START_HERE.md.

PR #21 passed CI on all three distributions (run `37168203876`) and was merged.

## 2026-10-04 — M4 initial benchmark suite

**Outcome:** 20 representative GUI tasks across Chromium, foot, xterm/Xwayland,
mousepad, zenity and kdialog, run by Claude Code with only the desktop MCP tools
and verified independently. Run 1: 19/20, 233 tool calls, $2.24. After two fixes
it found, runs 2 and 3: 20/20 each, 149 and 154 calls, $1.78 and $1.81. No tool
errors or cleanup failures. Details, per-task calls and limits are in
`docs/BENCHMARK.md`. A dry run with no agent failed all 20 checks, as intended.

Measured findings that changed the product: the keycode collision (PR #20) and
the missing key repeat. One run-1 failure came from a fixture bug: `id=name` is
shadowed by `window.name`. The suite has now saturated, so harder tasks are the
next M4 step.

PR #20 passed Ubuntu, Fedora and Arch CI (run `37166510790`). Chromium tests ran
on Fedora and Arch and skipped on Ubuntu, where AppArmor blocks the Chromium
sandbox. Merged.

## 2026-10-04 — M1 physical key codes (found by the agent benchmark)

**Outcome:** the virtual keyboard now uses a US layout on real evdev codes.
Before, keycodes were assigned in order of first use. In the first benchmark run
(next entry) Claude Code typed `private desktop` into Chromium and got
`privatdesktop`. It reported that "space acts like Backspace" and worked around
it with `KP_Space`. The cause: in that session, space was assigned evdev code 14,
which is the physical Backspace key, and Chromium interprets some keys by
physical code. Any character could collide with a physical Tab, Enter, arrow or
function key the same way.

### Design

- ASCII on its US physical key, with Shift as a modifier for level 2. Named keys
  (Return, BackSpace, Tab, Escape, arrows, Home/End/PageUp/PageDown,
  Insert/Delete, F1–F12, keypad Enter, Menu, Print, modifier keys) use their real
  codes. Modifier keys keep the `modifier_map` entries Xwayland requires.
- Other keysyms use a pool of 19 spare codes, remapped on demand with
  least-recently-used reuse. Codes still needed by unsent keys are pinned; if the
  pool runs out, pending keys are sent first, then the keymap is replaced.
- The pool was chosen by measurement. Typing one Greek letter per candidate code into
  Chromium showed that events from codes 84 and 195 (no defined key) were dropped
  (the first attempt lost `é` this way). Codes 86, 89, 117, 121, 124, 179, 180
  and 183–194 delivered their characters.
- `key` accepts `repeat` (1–100). In the benchmark the agent pressed Right 32 times,
  one tool call each, to move a slider.

### Validation

- New `xev` test (Xwayland): `a` and `A` arrive on keycode 38 (A shifted),
  space on 65, BackSpace on 22, and `λ` on a pool code.
- New Chromium test: `Browser café: ` + 25 distinct Greek letters + ` ok!`
  (more than the pool, so codes are reused) arrives exactly. It failed with code
  84 restored to the pool and passed 3/3 with the final pool. Runs on NixOS
  and is added to Fedora/Arch CI. Containers run as root, so the test adds
  `--no-sandbox` only when the effective user is root.
- The keyboard test now types `XY`, then sends BackSpace with `repeat=2`.
- Full suite 22 tests, 1 skipped. Keyboard, Xwayland, physical-code, toolkit and
  focus tests together 5/5. Chromium smoke 3/3.
- The focus test's third terminal now runs `sh`. With the user's default zsh and an
  empty private home, zsh's first-run setup prompt could intercept the Ctrl+D used
  to close it (1 failure in 4 runs; 15/15 after the change).

## 2026-10-04 — M2 Claude Code client integration

**Outcome:** a real interactive client, Claude Code, completed a GUI task
through the MCP server. On the user's instruction ("use this repo and claude code
for testing"), the configuration is a project-scoped `.mcp.json`; the user's
global Claude Code settings were not changed.

`scripts/claude_code_task.py` runs `claude -p` with `--strict-mcp-config
--mcp-config .mcp.json --tools "" --allowedTools mcp__private-desktop`, a $2
budget cap and no session persistence. The agent therefore has no shell, file or
web tools. The task page draws a random 6-character code on a canvas. The agent
must create a session, launch the given Chromium argument list, read the code
from screenshots, type it, drag a box into a dashed target and press Submit, then
leave the session running. Afterwards the harness checks the window title through
the core API, takes its own screenshot and destroys the session. When `hyprctl`
exists, it also compares the host's active window and cursor before and after.

### Results (Claude Code 2.1.288, model claude-opus-5-5, Chromium 153)

| Run | Passed | Tool calls | Seconds | Cost (USD) | Host unchanged |
| --- | --- | ---: | ---: | ---: | --- |
| `573a7a2e55f2` | yes | 12 | 21.5 | 0.152 | not recorded |
| `ad28947d55d8` | yes | 11 | 27.0 | 0.108 | yes |
| `e03eb2e9cef0` | yes | 11 | 24.7 | 0.107 | yes |
| `6b72b1854598` | yes | 12 | 22.5 | 0.113 | yes |
| `2be85c3fad05` | yes | 10 | 21.4 | 0.092 | yes |

Screenshot tool results contained real image blocks (3 per run in the first
transcript); the code existed only in the rendered canvas. The final screenshot
was inspected: correct code in the field, box inside the target, title
`Agent task - complete`. Each session outlived the `claude` process and was still
`ready` when the harness checked it, so the session survives client disconnect.

This is one task type with one model. It shows the client integration works;
it is not a benchmark. Interactive (TTY) Claude Code uses the same `.mcp.json`
after the user approves the project server. That approval step was not exercised
here. Human takeover and action ownership are still unimplemented.

## 2026-10-04 — Handoff after M1 hardening and M3 coverage

Updated the plan status and starter prompt after PRs #10–#16. PR #16 passed
Ubuntu, Fedora and Arch CI (run on its final commit) and was merged. The next
step, configuring an interactive agent client (#7), changes the user's persistent
client configuration and waits for their choice. This documentation change adds
no runtime validation claims.

## 2026-10-04 — M3 Fedora and Arch Linux CI

**Outcome:** the full headless suite (20 tests, visible mode skipped) and stress
cycles pass in Fedora 44 and Arch Linux containers, using each distribution's own
labwc, foot, grim, wayvnc, wlr-randr, dbus-daemon, Xwayland, xterm and zenity
packages (run `37164358545`). labwc versions now covered: 0.7.1 (Ubuntu), 0.9.6
(Fedora) and 0.20.2 (Arch, NixOS). Exact package versions are in
`docs/COMPATIBILITY.md`. These are container runs on a CI host, not desktop
installs; packaging and onboarding on those desktops remain untested.

Findings:

- In GitHub's job containers, PID 1 does not reap orphans. After a double
  supervisor kill, the recovered compositor remained a zombie, and the test's
  `/proc` existence check timed out. Tests now treat zombies as stopped.
  Recovery itself worked.
- Containers have no `XDG_RUNTIME_DIR`. The runtime correctly refuses to start
  without one, so CI creates a 0700 directory.
- Ubuntu failed `test_focus_and_stale_observations` once in 7 runs: the
  focused window got an empty line instead of `fresh`. Not reproduced since (3 reruns
  passed). Tracked as issue #17. CI now uploads each test's screenshots, logs and
  fixture output when the test step fails.

## 2026-10-04 — M3 Xwayland, GTK and Qt coverage

**Outcome:** X11 applications work inside sessions, and GTK and Qt dialogs work
on both native Wayland and X11.

### Xwayland display

labwc starts Xwayland lazily and sets `DISPLAY` only in its own process.
Applications are launched by the worker, so they never saw it. labwc's
`autostart` script inherits the variable, so it now writes `$DISPLAY` to the
private runtime directory. The worker accepts only an `:N` value and passes it to
applications. `status` reports `x_display`. The host's `DISPLAY` (`:0` here) is
still removed; the session got `:1`.

### Xwayland ignored the generated keymap (fixed)

xterm received no usable text. `xev` showed keycode 9 arriving as Escape, and
`xkbcomp -xkb :1` dumped the default evdev keymap. Wayland protocol tracing
showed that Xwayland did receive the 1470-byte keymap. Xwayland 24.1.13
`XkbCompileKeymapFromString` requires key names, types, compat, symbols **and
virtual modifiers**. Otherwise it silently falls back to defaults, which explains
the unrelated `<FK23>` xkbcomp warnings. wtype's keymap layout has the same
problem. The keymap now reserves evdev codes 1–5 for Shift_L, Control_L, Alt_L,
Super_L and Num_Lock with `modifier_map` entries. Characters start at code 6
(242 per keymap). After this, xev showed `a`, `b`, `c` on the first keypress.

### Foreign-toplevel destroy opcode (fixed)

Closing a window made every later `windows` call fail with a broken pipe. On
`closed` the client sent opcode 6 (`set_rectangle`) instead of `destroy` (7).
labwc rejected it as a protocol error and disconnected the tracker. The
focus/observation test now closes a window and checks the listing.

### Validation

Executables came from `nix shell nixpkgs#labwc nixpkgs#foot nixpkgs#grim nixpkgs#xwayland
nixpkgs#xterm nixpkgs#zenity nixpkgs#kdePackages.kdialog nixpkgs#wayvnc nixpkgs#wlr-randr`.

- Full suite: 20 tests, 1 skipped (visible).
- xterm (`-u8`) running the terminal fixture: exact `x11 café λ`, a mouse click,
  and Xwayland among the session's processes. 10/10 idle and 10/10 with 12 busy processes
  (together with the keyboard test).
- zenity 4.2.2 and kdialog 26.08.1, each with `GDK_BACKEND`/`QT_QPA_PLATFORM`
  set to Wayland and X11: type `<case> café λ`, press Return, and check the exact stdout
  line after the dialog exits. 5/5 idle, 5/5 loaded.
- CI now installs xwayland, xterm and zenity; kdialog is local only.

PR #15 passed Ubuntu CI (run `37163950418`; Xwayland and GTK tests ran there) and
was merged.

### Remaining

- Only simple dialogs and terminals are covered; larger GTK/Qt applications,
  portals/file choosers, clipboard and drag-and-drop between windows are not.
- No X11 access control was added; Xwayland behaves as on an ordinary desktop.

## 2026-10-04 — M1 structured windows, focus and stale-observation protection

**Outcome:** `wlrctl` is no longer a runtime dependency. A persistent
`zwlr_foreign_toplevel_manager_v1` client provides a structured window list (stable
session-local id, title, app_id, states and parent) and a `focus` operation
(`activate` on the seat). The runtime now needs only labwc, grim and dbus-daemon.

Screenshots return an `observation` token: a hash of output size/scale and each
window's id, app_id, states and parent. It is computed before and after capture;
if the two differ, the capture is retried, so the token matches the image. Input
operations given a token compare it with the current layout and fail with
`StaleObservation` without sending anything if it differs. Titles are excluded
because browsers and terminals rewrite them continuously. This catches
appearing/closing dialogs, focus changes and output resizes. It does not catch
changes inside a window, and a change between the check and the input is still possible.

### Visible-mode extra input explained

On this branch the opt-in visible test failed 4/4 consecutive runs (one more
earlier the same day). Each time, one extra character arrived before
`private café λ`: `l` once and `\x08` (foot's Ctrl+BackSpace) twice. The
session's virtual keymap contained only the characters of that text at the time,
so the extra events were decoded with another keymap. The only other keyboard on
the nested seat is the wlroots Wayland backend's keyboard, which mirrors the
host seat. The cause is therefore host keyboard input reaching the nested window
while it has host focus; this also explains the earlier "extra space". Host
keystrokes were not injected to confirm it, because that would act on the
physical desktop. Headless sessions and the read-only observer have no host
keyboard. The README now warns about this for visible mode.

### Validation

Executables came from `nix shell nixpkgs#labwc nixpkgs#foot nixpkgs#grim nixpkgs#wayvnc
nixpkgs#wlr-randr nixpkgs#chromium`, with no wlrctl or wtype on PATH.

- Full suite: 18 tests, 1 skipped. New test: two foot windows; structured
  listing; `focus` changes the activated window; a stale token refuses `type`
  and nothing reaches either app; a fresh token types into the focused window only;
  a newly mapped window makes the token stale. 10/10 repeated runs.
- Chromium smoke 3/3 using structured window titles, including the 427 px drag.
- Lifecycle stress 10/10 with 12 busy processes.

PR #14 passed Ubuntu CI (run `37163297968`) and was merged.

## 2026-10-04 — M1 supervisor crash recovery

**Outcome:** a crashed session supervisor no longer leaves the session running.

### Design

- The session process forks. The parent is a minimal **guardian** that only waits
  for the worker child. Both are child subreapers (not inherited across `fork`,
  so each sets it). Orphans stay with the worker while it lives, then fall to the
  guardian, never to init or the host service manager.
- When the worker exits, the guardian stops anything left (subtree plus token). If
  the manifest was not already `stopped`/`failed`, it removes the runtime and
  home/config and records `failed` with the signal or exit status.
- If both supervisors are gone, `destroy` checks that no process with the
  session token is at the recorded supervisor PIDs. It then kills token
  carriers (token only, never the caller's own children, which may be other sessions'
  supervisors) and removes the runtime directory, after checking that it is
  exactly `$XDG_RUNTIME_DIR/agent-desktop/SESSION`. It returns `recovered: true`.
- `destroy` now returns only after the supervisors have exited. Before, the
  guardian could still be exiting, which the stress script reported as a leftover.

### Bug found during this stage

The full suite slowed from about 20 s to 68 s. The worker's token scan included its
parent, the guardian, which carries the token. Normal teardown therefore sent
SIGTERM to the guardian (forwarded back), waited through two 2-second phases, and
SIGKILLed it. Supervisors now exclude themselves and their parent. The round-trip
test asserts that `destroy` takes less than 2 s; it measured 4.3 s with the bug.

### Validation

- Full suite: 17 tests, 1 skipped; about 20 s. New tests: SIGKILL of the worker (guardian
  cleans up, including a `setsid env -i` daemon) and SIGKILL of both supervisors
  (`destroy` recovers; compositor and token processes gone).
- Lifecycle stress on the final code: 20/20 with 12 busy processes
  (`artifacts/stress/3d4645165309`), 20/20 idle (`48906c384180`).
- Chromium smoke 3/3 and visible test passed before the final `destroy` wait
  change. The wait only affects when `destroy` returns.

### Remaining

- If both supervisors are SIGKILLed, processes that cleared their environment
  escape recovery. A cgroup would close this gap but needs systemd delegation.
  This has not been done, to stay distribution-neutral.

PR #13 passed Ubuntu CI (run `37162992248`) and was merged.

## 2026-10-04 — M1 persistent keyboard and safe compositor bindings

**Outcome:** keyboard input no longer uses wtype or fixed sleeps. Each session
creates one `zwp_virtual_keyboard_v1` (with the pointer, before applications)
and keeps a cumulative keymap with one keycode per keysym. A new keymap is
uploaded only when new characters appear, on the same ordered connection as the keys,
followed by a sync roundtrip. With the old wtype path, every request created a new
virtual keyboard and relied on a 200 ms start delay and 20 ms per key.

### Decisions

- Typed characters map to numeric keysyms with xkbcommon's Unicode rules
  (Latin-1 direct, otherwise `0x1000000 | codepoint`; newline, tab, backspace and
  escape map to their function keysyms). Numeric keysyms in `xkb_symbols` were
  verified with xkbcommon 1.13.2. Text is layout-independent; limit raised to
  10000 characters.
- At most 247 keys (keycodes 9–255, for X11 compatibility). When a chunk needs
  more, the keymap is replaced by that chunk's characters.
- `key` names are resolved with `xkb_keysym_from_name` from the libxkbcommon that the
  compositor already maps (found in `/proc/PID/maps`), so an invalid name fails
  before a broken keymap can reach clients. Modifiers use the virtual keyboard
  modifier request (shift 1, ctrl 4, alt 8, logo 64), as wtype did.
- The keymap is passed via `SCM_RIGHTS` from an unlinked file in the session
  state directory: `os.memfd_create` is also unavailable in the uv CPython build.
- **Host-interference fix:** `rc.xml` used `<keyboard><default/>`. labwc 0.20.2's
  defaults include Execute bindings: `W-Return` → `lab-sensible-terminal`, audio
  keys → `pactl`, brightness keys → `brightnessctl`. An agent's key request
  could therefore run host commands, including changing physical backlight. Now
  only A-Tab, A-S-Tab and A-F4 are bound. A test puts a fake
  `lab-sensible-terminal` on PATH; it ran with the old config (test failed) and
  did not run with the new one. Brightness/audio keys were not sent during testing.

### Validation

Executables came from `nix shell nixpkgs#labwc nixpkgs#foot nixpkgs#grim nixpkgs#wlrctl
nixpkgs#wayvnc nixpkgs#wlr-randr nixpkgs#chromium`, with no wtype on PATH.

- Full suite: 15 tests, 1 skipped (visible); visible test passed separately.
- Keyboard test (type immediately once foot is `state:active`, Ctrl-U line kill,
  invalid key, `aa café λ` + 300 distinct CJK ideographs + `zz`, exact receipt):
  10/10 idle, 10/10 with 12 busy CPU processes.
- With the same 12 busy processes: lifecycle stress 20/20
  (`artifacts/stress/397c9ca2d3dd`, median 1.86 s); Chromium smoke 3/3 including
  `browser café λ` and the 427 px drag.

### Remaining

- The unexplained extra character in visible mode is not reproduced. A plausible but
  unproven cause is host keyboard input reaching the focused nested window; the
  virtual keyboard cannot prevent that.
- IME/dead-key composition, apps reading physical layouts and key-repeat timing
  are untested. Xwayland clients are untested.
- Supervisor crash recovery was still open at this stage.

PR #12 passed Ubuntu CI (run `37162378266`) without wtype installed and was merged.

## 2026-10-04 — M1 absolute pointer and drag

**Outcome:** pointer input no longer depends on `wlrctl`. A small dependency-free
Wayland client (`agent_desktop.wayland`) binds `zwlr_virtual_pointer_manager_v1`
and `wl_output` on the private socket. It provides absolute moves, clicks, scroll
and the new `drag` operation (CLI `drag SESSION X Y TO_X TO_Y`, MCP `desktop_drag`).
Every pointer request finishes with a `wl_display.sync` roundtrip, so "delivered"
means the compositor processed the events. Whether the application acted on them
still needs a separate check. `wlrctl` is still used for window listing.

### Decisions and evidence

- **One persistent virtual pointer per session, created before any application.**
  The first version created a pointer per request. A second click at the same
  position was then lost, and so was the round-trip test's click after an
  invalid request. Destroying the seat's only pointer removes its pointer
  capability, and foot rebinds `wl_pointer` asynchronously, so the next press could
  arrive without pointer focus. With the persistent pointer the failure did not recur.
- Absolute motion uses the live output mode as its extent. Before each pointer
  operation a roundtrip processes pending `wl_output` events. Changes of mode
  update the bounds; scale other than 1 or more than one output fails closed.
  Coordinates are no longer checked by taking a screenshot.
- Drag: move, press, 8–60 interpolated motions about 10 ms apart, then release.
  Scroll matches `wlrctl` (finger source, axis, frame, axis stop).

### Validation

- `scripts/pointer_fixture.py` enables xterm button-event tracking in foot and records
  every SGR press/motion/release. Test: repeated absolute clicks hit the same
  cell; ordering is correct; a drag gives press, ≥3 held-button motions and a release with
  monotonic columns; scroll produces a wheel event; out-of-bounds drags fail.
  10/10 idle and 10/10 with 12 busy CPU processes.
- Full suite: 14 tests, 1 skipped (visible); visible test passed separately.
- `wlr-randr` 0.5.0 (optional test, added to CI): custom mode 1024×768 changes
  screenshot size and bounds; scale 2 is rejected.
- Chromium smoke task now drags across a DOM pointer-event pad: 3/3 reported exactly the
  requested 427 px over 16–17 `pointermove` events with the button held
  (`artifacts/browser/089056ae72a1`, `9160edf57803`, `6ffb5ea64282`).

### Remaining

- Keyboard input still used wtype with fixed delays at this stage.
- No HiDPI/fractional scaling or multiple outputs; drag speed is fixed; no
  modifier-held drag.

PR #11 passed Ubuntu CI (run `37161930144`; wlr-randr 0.3.0 test ran) and was merged.

## 2026-10-04 — M1 process ownership and private-bus environment

**Outcome:** session teardown now covers processes that daemonize, call `setsid`,
clear their environment or ignore SIGTERM while forking. This stage also fixed an
isolation bug in the earlier runtime: D-Bus-activated services used the host
environment.

### Decisions

- The worker marks itself a child subreaper (`prctl(PR_SET_CHILD_SUBREAPER)`),
  so orphaned descendants are reparented to it, not to init. Ownership is the
  worker's process subtree plus the existing environment-token scan.
- The worker starts `dbus-daemon --session --nofork` itself, listening on
  `RUNTIME/bus`, after the private compositor socket exists. This replaces
  `dbus-run-session`, whose daemon was outside the worker's tree. Runtime dependency
  changes from `dbus-run-session` to `dbus-daemon`.
- Teardown: graceful labwc exit, then SIGTERM to everything except the bus, then
  SIGTERM including the bus, then SIGKILL. Each phase rescans the tree so children
  forked during teardown are included. Adopted zombies are reaped without taking
  exit codes from tracked `Popen` objects. `os.pidfd_open` is still unavailable in
  the uv-managed CPython 3.12.13 build, so PID-reuse races are reduced by short
  rescans, not eliminated.
- `status` lists live session processes (PID and command name).

### Isolation bug found

The Chromium smoke task failed 4 times in a row on this branch: a GNOME Keyring
"Choose password for new keyring" dialog took focus inside the private desktop.
The same task passed on `main`. Inspecting a `main` session's bus process showed why:
`dbus-run-session` inherited the host environment, so `HOME=/home/user`, host
`WAYLAND_DISPLAY` and `HYPRLAND_INSTANCE_SIGNATURE` were set. Activated services
(gnome-keyring, mako, xdg-desktop-portal including the Hyprland backend) therefore ran
against the user's real home and host compositor. Those services were found in the
logs, but whether any of them actually changed host state was not investigated.

On this branch, activated services get the private home, runtime directory and
private Wayland socket. A test asserts the bus environment. gnome-keyring now
offers to create a keyring inside the private session. Chromium was never meant
to use a keyring here, so the disposable-profile smoke task passes
`--password-store=basic`. Other applications may still show this private prompt;
an agent sees it in screenshots.

### Validation

Executables came from `nix shell nixpkgs#labwc nixpkgs#foot nixpkgs#grim
nixpkgs#wtype nixpkgs#wlrctl nixpkgs#wayvnc nixpkgs#chromium`; `dbus-daemon` came from the system.

- `uv run python -m unittest discover -s tests`: 12 tests, 1 skipped (visible opt-in).
  The new daemonizing-application test failed before the change and left a
  `sleep` process running; that exact PID was removed manually.
- `DESKTOP_TEST_VISIBLE=1 ... -k visible`: passed once.
- `scripts/lifecycle_stress.py --cycles 20 --load 12` on the final code: 20/20
  (`artifacts/stress/c46e4769a583`, median cycle 1.79 s). Earlier branch runs:
  20/20 idle (median 1.45 s), 20/20 loaded (median 1.58 s). Each cycle verifies
  exact typed text, a token-less `setsid env -i` daemon, and no leftovers.
- `scripts/browser_smoke.py`: 3/3 passed (`artifacts/browser/3872f9b4f984`,
  `eb0281eda3fa`, `3d1d83c98dc4`). 23 session processes, including chromium,
  crashpad, xdg portals, document portal FUSE helper and mako. No Chromium D-Bus
  abort at teardown, no leftover processes or `agent-desktop` mounts.

PR #10 passed Ubuntu CI (run `37161251759`, including 5/5 loaded stress cycles)
and was merged.

### Remaining

- If the worker itself is SIGKILLed, its adopted orphans go to init. Only
  token-carrying processes are then discoverable. Crash recovery for stale
  sessions is not implemented.
- Processes started on the user's behalf by host services (host systemd user
  manager, host portals) are outside the session tree. The private bus reduces,
  but does not eliminate, this route.
- Input readiness still relies on fixed wtype delays; the stress runs did not
  reproduce a dropped or extra character. Drag was unimplemented at this stage.

## 2026-10-04 — Development handoff and checkout location

Updated the starter prompt to continue from the implemented stages, with current
issues and priorities instead of repeating M0. Removed obsolete packaging status
from the plan. The checkout is moving to `/home/user/private-agent-desktop` at the
user's request. Historical experiment paths remain unchanged as evidence.
This documentation change adds no new runtime validation claims.

## 2026-10-03 — M3 initial real application coverage

Added an opt-in Chromium smoke task with a new private user-data directory, explicit
native Wayland mode and a local HTML form. No personal profile was accessed, and
the browser sandbox was not disabled. The task typed `browser café λ`, submitted
the form through keyboard navigation, observed the expected submitted window title
and produced a changed screenshot. The final screenshot was visually inspected.

Observed version: Chromium 153.0.8010.52. Evidence is retained in
`artifacts/browser/cfac3e875848/`, including JSON report, before/after PNGs and logs.
Teardown removed the runtime and browser profile; the final owned-process scan
was empty. This is one scripted task, not a claim of general browser reliability
or model-agent completion rates. Chromium is an optional smoke-test dependency.

Added the compatibility matrix and replayable NixOS runtime-shell instructions.
The shell supplies Linux desktop executables; Python dependencies still use uv.
Ubuntu CI validates terminal/core/MCP behavior separately from this Chromium task.

Setup validation also found that CLI defaults masked runtime executable environment
overrides. The CLI now uses the same override resolution as MCP; a real CLI test
checks the selected labwc executable. Typing is capped at 1000 characters so its
paced input stays within the current tool timeout. Viewer helper discovery has a
deadline and reports its actual log tail on startup failure. CI records package
versions, and the graphical smoke test verifies ownership of the mapped viewer.

Observer PR #4 passed Ubuntu CI (run `37159636661`) and was merged. Remaining work
is tracked in issues #5 (runtime hardening), #7 (interactive client/action ownership)
and #6 (application and Linux compatibility).

## 2026-10-03 — M2 independent read-only observer

Added `agent-desktop view SESSION`, using optional wayvnc and TigerVNC. wayvnc runs
inside the private desktop and listens only on a Unix socket under its 0700 runtime
directory. Server-side input is disabled. The graphical client uses ViewOnly,
disables clipboard transfers and remote resizing, and uses disposable configuration.
No TCP endpoint or personal viewer configuration is used.

The actual VNC handshake was tested. A client deliberately sending a keyboard
event could not modify the terminal's next received message; the private input API
still worked. Disconnecting the observer preserved the session and screenshots.
The optional graphical smoke test mapped a real TigerVNC window on Hyprland, then
closed only its own viewer and confirmed that the headless desktop survived.
Tested optional packages: wayvnc 0.10.1 and TigerVNC 1.16.2, fetched temporarily
without host activation. The VNC server remains session-owned until teardown.

MCP PR #3 passed Ubuntu CI (run `37159264698`) and was merged. Observer tests are
added to CI with the distribution wayvnc package; that validation is pending.
The observer is distinct from the interactive nested testing mode: host input
cannot be forwarded through this observer, even by a client ignoring ViewOnly.

## 2026-10-03 — M2 stdio MCP integration

Added `agent-desktop-mcp`, a thin adapter over the persistent core. Tools expose
create/list/status, launch, windows, screenshot, keyboard and pointer input, logs
and destroy. Screenshot results include PNG image content and text with dimensions
and the retained artifact path. The server uses stdio and opens no network endpoint.
Runtime executable overrides are available through `AGENT_DESKTOP_*` variables.

Selected the official MCP Python SDK's stable v1 API and pinned the dependency to
`mcp>=1,<2` (resolved to 1.30.0), avoiding an incidental migration to the v2 API.
The API was checked against installed signatures and the
[official SDK](https://github.com/modelcontextprotocol/python-sdk).

A real stdio client integration test passed: initialize, discover tools, reject
an unknown session, create a desktop, launch the native Wayland terminal fixture,
receive a real PNG block, type exact `MCP café λ`, send Return, receive a left click,
and destroy the runtime. A second created session remained available after the
MCP client disconnected; it was explicitly destroyed afterward. This validates
the transport and tool/image semantics, not every client application's support.

No persistent MCP client configuration was changed. The README supplies a generic
configuration; a chosen interactive client and an independent viewer remain open.

The complete rerun passed all headless/core/MCP tests, but the visible test observed
` private café λ` (an extra leading space). Concurrent host input can reach a
nested desktop; this observation does not establish the source of that character.
Earlier visible round trips passed, but repeatability with a human using the host
is not established. The visible test remains explicit opt-in and this gap remains
tracked; it must not be reported as the same isolation guarantee as headless mode.

M1's corrected Ubuntu CI run passed (run `37159062985`), and PR #2 was merged.
The repository now requires the `runtime` status check and pull requests on main,
requires linear history and resolved conversations, and rejects force pushes and
branch deletion. No reviewer count was imposed. The private visibility was verified.

## 2026-10-03 — M1 initial persistent runtime and visible testing

Implemented a packaged `agent-desktop` CLI and persistent per-session supervisor.
The core handles create/list/status, application launch, window enumeration,
screenshots, type/key, pointer movement/click, scroll, bounded log tails and teardown.
All control requests identify a session and go to a private local Unix socket.
The supervisor serializes requests and uses a private D-Bus/display environment.

Added `create --mode visible`: labwc's Wayland backend connects to an explicit
parent display socket and opens a nested desktop window. The application's and
input clients' display remains the private socket. Headless stays the default.
The visible window's lifecycle is tied to the session; an independent observer
viewer is still deferred.

Seven local tests passed: invalid identifiers/mode, unknown session, actual app
and compositor crashes, headless input/capture/cleanup, distinct input to two
simultaneous sessions, and the opt-in visible round trip. Both round trips check
exact `private café λ` receipt, a real left mouse event, changed PNGs and removal
of the session runtime directory. Invalid requests fail without reaching a host
display. App crashes retain stderr/exit status; compositor crashes close the
endpoint, remove runtime resources and leave failure metadata/logs.

Initial validation reported unreaped supervisor warnings. A daemon reaper thread
now retains/waits for client-created supervisors, and workers reap compositors
during cleanup. The suite is rerun with ResourceWarning promoted to errors.
That rerun also exposed a fixed-coordinate assumption in the visible fixture:
the host can resize its nested output. The test now targets the center of a fresh
screenshot instead of assuming a 1280×720 desktop. Visible mode needs resize-aware
observations, and simultaneous human input can affect the nested desktop by design.

Runtime logs are trimmed above 1 MiB to a 512 KiB tail; the log API returns at most
16 KiB per file. Screenshots and session records are retained for evidence.
Cleanup still relies on a per-session environment ownership token; arbitrary
applications which daemonize or replace their environment need stronger ownership.
Input startup delays, drag, alternate layouts, accessibility and general
application compatibility remain open.

Repository setup: private GitHub repository, `main` default, issues enabled,
wiki/projects disabled, squash-only merges and automatic branch deletion. M0 was
merged through PR #1. Added CI, a PR template and a runtime failure issue form.
No host activation, permission changes or personal application profiles were used.

The first Ubuntu CI run failed at compositor startup. Inspection of older labwc
source confirmed it does not support the new `-t` title option used by the initial
runtime. Removed that optional argument for compatibility and included log tails
in startup errors so future CI failures expose their actual cause. CI is rerun
before integrating M1.

## 2026-10-03 — M0 headless experiment

**Outcome:** a disposable native Wayland application ran in an invisible labwc
desktop. Screenshots, exact text delivery, mouse-click receipt and cleanup passed
in two complete runs. The host Hyprland workspace, focused window and pointer
coordinates matched before and after both runs. This is a foundation experiment,
not M1/M2 completion or a benchmark against competing runtimes.

### Current choices

- Experiment: labwc with wlroots headless backend and pixman software rendering.
  No physical/nested display backend is requested.
- Experiment implementation: Python 3.12, uv-managed interpreter, no Python dependencies.
- Observe/input: grim, wtype and wlrctl; all target the private Wayland socket.
- Fixture: foot running a disposable Python terminal application which reports
  actual received keyboard text and SGR mouse events.
- Session services: private `dbus-run-session`, temporary runtime directory and
  home/configuration. Personal display/IPC addresses and startup hooks are excluded.
- Cleanup: graceful labwc exit followed by cleanup of remaining processes carrying
  the experiment's unique ownership token. This is prototype lifecycle handling;
  arbitrary daemonizing applications and stronger ownership mechanisms remain M1 work.

labwc was selected for this experiment because it supplies headless rendering and
the required virtual-input protocols. Hyprland was already installed, but its
v0.56.2 startup source attempts a DRM backend; it was not started as a second
compositor. Weston and KWin were not tested.

### Environment and exact invocation

| Component | Observed version |
| --- | --- |
| Host Hyprland | 0.56.2 |
| uv | 0.12.17 |
| uv-managed Python | CPython 3.12.13 |
| labwc / wlroots | 0.20.2 / 0.20.2 |
| foot | 1.28.0 |
| wtype | Nix package 0.4 |
| wlrctl | 0.2.2 |
| grim | Existing user-profile executable; exact version not established |

Temporary desktop runtime packages were fetched into the Nix store, without profile
installation or host activation. The system nixpkgs registry resolved to revision
`4975466d324710c576dc11ad614684e6bd8cad8e`.

```sh
nix build --no-link --print-out-paths nixpkgs#labwc nixpkgs#wtype nixpkgs#foot
nix build --no-link --print-out-paths nixpkgs#wlrctl
uv sync --managed-python
uv run scripts/m0_headless.py \
  --labwc /nix/store/j5dyasxafxl595i1fkpm0lvmpwx6bzn8-labwc-0.20.2/bin/labwc \
  --foot /nix/store/6nhmbaws8lqd8bvzsx4m0gw36ssyg2iy-foot-1.28.0/bin/foot \
  --wtype /nix/store/cwzg3yii4xv6hk1yn3jjgw14cxzy98qa-wtype-0.4/bin/wtype \
  --wlrctl /nix/store/39lixl7l8bah5wsv5p1xb32w14smw2rz-wlrctl-0.2.2/bin/wlrctl
```

The Unicode run added `--text 'agent café λ 123'`. Core Python metadata contains
no Nix dependency or linker paths. These store paths document this machine's
experiment; they are not portable installation instructions or permanent GC roots.

### Evidence

| Run artifact directory | Result |
| --- | --- |
| `artifacts/m0/20261003-231227/` | Initial ASCII keyboard + screenshot proof; mouse not yet implemented |
| `artifacts/m0/20261003-231417/` | Failed: first character dropped; cleanup used unavailable `os.pidfd_open` |
| `artifacts/m0/20261003-231510/` | Passed: ASCII text, left click, changed screenshot, no owned processes remaining, temporary session removed |
| `artifacts/m0/20261003-231531/` | Passed: `agent café λ 123`, left click, changed screenshot, same cleanup checks |

The screenshots were visually inspected. Both complete runs produced 1280×720
images, showing the received text and click inside the private terminal.
Mouse receipt reported left button `0`, column `67`, row `19` in the terminal.
Full reports retain command arguments and screenshot SHA-256 values.

The failed cleanup left experiment processes running. After discovering that
the uv interpreter lacks `os.pidfd_open`, cleanup was changed to token-scoped
signals; those leftover processes were removed using their exact ownership token.
A final scan confirmed no experiment token processes remained.

Adding a 200 ms input startup delay and 20 ms inter-key delay avoided the observed
first-character loss in the complete runs. This is an experimental workaround;
M1 needs an input-readiness mechanism and repetition under varying load rather
than treating fixed sleeps as a reliability guarantee.

### What is still unverified

- Transient host focus/pointer changes between the two host-state snapshots.
- Other keyboard layouts and broader Unicode coverage.
- General GUI applications, single-instance applications, Xwayland and portals.
- Window metadata, absolute coordinates, drag, scroll and persistent sessions.
- Invalid-session/backend-failure behavior at the future core API boundary.
- Other Linux distributions, actual MCP-client integration and viewer behavior.
- Cleanup for arbitrary applications which alter their environment or daemonize.

No host rebuild/activation, persistent permission changes, personal browser
profiles or unrelated application shutdowns were used.

### Prior art reviewed

- [Cua](https://github.com/trycua/cua): reference for computer-use interfaces and
  environment lifecycle. Its README was reviewed; no source was copied and no
  hands-on compatibility claims are made.
- [wbox backend documentation](https://github.com/quazardous/wbox-mcp/blob/main/docs/backends.md):
  closer reference for labwc, headless operation and compositor-targeted input.
- [Hyprland v0.56.2 startup source](https://github.com/hyprwm/Hyprland/blob/v0.56.2/src/Compositor.cpp):
  checked before choosing the safer headless-only labwc experiment.
- Local wlrctl 0.2.2 man page: verified pointer movement/click syntax.

### Next milestone

M1: convert the experiment into a small persistent session core and CLI. Start with
lifecycle/process ownership and fail-closed session routing, then launch, screenshots,
window metadata and serialized input. Keep one backend until observed failures
justify another. MCP and the optional viewer remain M2.
