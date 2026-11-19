# How Agent Desktop is actually used

This is a list of real uses by the maintainer's own agents (Claude Code and Codex), not
planned features. Each use comes from a dated [field report](trials/), reconstructed
from transcripts. Nobody asked the agents to report, so the list shows what people delegate
in practice and how agents chose to do it. Benchmarks and scripted experiments are listed
in [BENCHMARK.md](BENCHMARK.md) instead.

Each new field report updates the table and the coverage below. Private details
(accounts, course names, file names, cookie values) are never recorded here.

## Use cases

| Use case | What agents do | Main tools | How well it works | Reports |
| --- | --- | --- | --- | --- |
| **Testing desktop software in throwaway desktops** | Run a bar, launcher, nested Hyprland or Quickshell build in a guarded private desktop, drive it, read its state, screenshot, destroy. Also used to compare themes and try terminal settings before enabling them | `create` (`guard_host`), `launch`, `screenshot`, `key`, `destroy` | Reliable. GPU sessions fail first on NixOS until Mesa is set up | [10-05](trials/2026-10-05-desktop-shell.md), [11-07](trials/2026-11-07-hyprland-overhaul.md), [11-08](trials/2026-11-08-gcp-tailscale-setup.md), [11-19](trials/2026-11-19-coursework-and-shell-tests.md) |
| **Web consoles with the person's logins, in the background** | Import the person's Firefox cookies into a named profile, then do account setup in cloud and VPN consoles (projects, billing alerts, auth keys, OAuth clients, DNS) without their screen | `import-cookies` (CLI), `desktop_browser`, `send` for secrets | Works. Login handoffs fail on sites that detect automation | [11-08](trials/2026-11-08-gcp-tailscale-setup.md) |
| **Collecting files from signed-in sites** | List a learning platform's courses through its API in the browser, download PDFs, captions and recordings, verify them and file them in a project | `desktop_browser` (`open`, `wait`, `send`), shell | Works with workarounds: downloads are found by polling, large listings exceed the 64 KiB `send` limit, videos need cookies copied to the shell | [11-12](trials/2026-11-12-canvas-materials-crawl.md), [11-19](trials/2026-11-19-coursework-and-shell-tests.md) |
| **Driving a native app on the person's own data** | Open the person's Anki profile in a private desktop, change settings, check decks, test card delivery, quit cleanly | `launch`, `click`, `scroll`, `key`, `screenshot` | Works by coordinates. The accessibility tools were not used | [11-19](trials/2026-11-19-coursework-and-shell-tests.md) |
| **Acting on the person's real screen** | With approval, install a userscript in their Firefox, demo a new shell live, check host-session features | `desktop_request_host`, `screenshot`, `click`, `type` | Works. Input pauses while the person types; their Firefox can't be driven through the DOM | [10-09](trials/2026-10-09-host-browser-task.md), [11-07](trials/2026-11-07-hyprland-overhaul.md), [11-19](trials/2026-11-19-coursework-and-shell-tests.md) |
| **Reviewing design mock-ups** | Open an HTML design study in a private Firefox, click through the options, screenshot each | `desktop_browser`, `screenshot` | Reliable, about a minute each | [11-07](trials/2026-11-07-hyprland-overhaul.md) |
| **Office and research tasks (structured pilot)** | Research in a browser, a GUI setting verified on disk, data entry in LibreOffice Calc | all input tools | 37 of 40 sessions passed. Calc was the weak point | [pilot](trials/pilot.md) |

## Coverage

| Period | Report |
| --- | --- |
| 2026-10-05 to 10-06 | [Pilot diary](trials/pilot.md), [desktop shell trial](trials/2026-10-05-desktop-shell.md) |
| 2026-10-09 | [Host browser trial](trials/2026-10-09-host-browser-task.md) |
| 2026-11-06 to 11-07 | [Hyprland field report](trials/2026-11-07-hyprland-overhaul.md) |
| 2026-11-08 to 11-09 | [Cloud setup field report](trials/2026-11-08-gcp-tailscale-setup.md) |
| 2026-11-12 (Codex) | [Canvas collection report](trials/2026-11-12-canvas-materials-crawl.md) |
| 2026-11-10 to 11-18 | [Coursework and shell-testing report](trials/2026-11-19-coursework-and-shell-tests.md) |

Reviewed through: **2026-11-18**. The next review starts from this date.

Use between 10-10 and 11-05 was never reviewed, and its transcripts have expired.
