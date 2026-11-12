# Beyond the delegation roadmap

Proposed 2026-11-12, as the last part of [DELEGATION.md](DELEGATION.md). These are
ideas, not plans. Each is labelled **checked** (searched on 2026-11-12, with what
was found) or **unchecked** (not searched). A check here is one or two web
searches, mostly of vendor pages and summaries, or the same day's
[prior-art scan](../research/2026-11-12-ambitious-directions-scan.md). "Not found"
never means "new".

## What this architecture can do that others structurally cannot

Compared with hosted sandboxes and cloud agents (Cua's cloud, OpenAI's agent,
Instinct, cloud browsers) and with agents that act on the person's visible screen
(Vercel Labs' agent-desktop, vendor desktop apps). Each line names the code that
makes it possible.

1. **One job that mixes the person's shell and a signed-in browser.** In the
   [cloud report](../trials/2026-11-08-gcp-tailscale-setup.md) the agent moved
   between Terraform, `gcloud`, SSH and console pages, and "the browser was the way
   to *get* API access". A hosted desktop has neither the person's SSH keys nor
   their `gh` login; `desktop_browser send` piping a new key into the local
   `gh secret set` has no hosted equivalent. An on-screen agent has both, and takes
   the screen to use them.
2. **Logins without a login event.** `cookies.py` copies chosen sites' cookies from
   the person's own Firefox files into a profile, and the session runs on the same
   machine and network. A hosted browser has to sign in fresh from somewhere else.
3. **Work in the background by construction.** Each session is its own compositor
   (`worker.py`), so input cannot reach the person's screen, sessions start in under
   a second, and several run at once with the person's installed applications. This
   includes the person's own desktop configuration under test: the
   [Hyprland report](../trials/2026-11-07-hyprland-overhaul.md) ran the real shell
   in 24 private desktops.
4. **A human turn in an ordinary browser on the same machine.** For a sign-in the
   runtime swaps the bridged Firefox for an unbridged one on the same profile
   (`worker.open_login_browser`), with the person's keyboard layout and clipboard
   paste. Their password manager and hardware keys are in the same room as the
   session.
5. **An approval surface the agent's desktop cannot see or click.** The shell draws
   a request on the person's compositor; a private session is a different
   compositor. Today this holds for the graphical path only (DELEGATION.md 2.4).
6. **One tool set for private and real.** A task can work privately and finish by
   opening its result in the person's running Firefox (`worker.open_in_person_firefox`),
   under an expiring approval.
7. **Reach.** The local network, the tailnet, a router's page, a printer, large
   local files, the local GPU.

## Which of these could make delegation dramatically better

| Idea | Why it could be large | Prior art |
| --- | --- | --- |
| **A local identity broker.** The runtime fills passwords and one-time codes from the person's own secret store, bound to the site, and checks logins when a task is delegated (stages Z5–Z6) | Every touch in the cloud report was about identity. Capabilities 2 and 4 are what make it cheap locally | **Checked: the idea is taken.** [1Password for Claude](https://www.1password.com/blog/1password-for-claude) fills logins and codes without the model seeing them (reported as Mac, Claude Desktop and Chrome only); [Browserbase with 1Password](https://siliconangle.com/2025/10/08/1password-tackles-ai-credential-risks-new-agentic-autofill-integration-browserbase/), [TinyFish Vault](https://www.tinyfish.ai/blog/tinyfish-vault-your-web-agent-can-now-log-in-without-touching-your-passwords) and [Steel](https://llms.steel.dev/articles/secure-browser-auth-for-agents/) do it for cloud browsers. One search found nothing for the Linux Secret Service or KeePassXC, or for Firefox. That is a platform gap, not a new idea |
| **A trusted approval path.** Requests drawn where the agent cannot reach, bound to the exact pending step, with the answer verbs outside the agent's sandbox (stages Z4 and Z9) | It is what makes unattended runs with identity defensible | **Checked in the scan:** forged and skipped approvals are documented attacks ([arXiv 2507.05445](https://arxiv.org/html/2507.05445v1), [Lies-in-the-Loop](https://www.infosecurity-magazine.com/news/lies-loop-attack-ai-safety-dialogs)); no compositor-level implementation was found |
| **Asking at the right moment.** The shell knows whether the person is at the keyboard, in Focus, or mid-task. Ask at delegation when possible, hold questions for a pause, and give each person a budget of questions per day | Touches cost attention, and the same touch costs less at a breakpoint. Only the person's own desktop has this signal | **Checked: research exists, no desktop product found.** Deferring to breakpoints (Iqbal and Bailey) and deciding under uncertainty (Horvitz), cited in [arXiv 2609.07741](https://arxiv.org/pdf/2609.07741); interruption budgets cut attention cost 36–73% in simulation ([summary](https://www.opentrain.ai/papers/ask-less-ask-better-allocating-user-attention-in-proactive-llm-agents-with-inter--arxiv-2610.24411/)). Read as summaries only |
| **Every touch becomes a proposed rule.** The ledger groups touches by cause and proposes the grant, credential or check that would have removed each | It turns the metric into the backlog | **Checked in the scan** as earned autonomy: crowded as marketing, a mechanism was not found, and approval counts alone mislead ([arXiv 2606.22721](https://arxiv.org/html/2606.22721v1)). Related measures: [arXiv 2602.11416](https://arxiv.org/pdf/2602.11416) |
| **A delegate passkey.** A software authenticator per identity, enrolled once by the person as an extra passkey | Would remove the touch that section 2.3 calls unavoidable | **Checked: discouraged, and feasibility doubtful.** Vendors advise against agents completing ceremonies ([Corbado](https://corbado.com/blog/ai-agents-passkeys)); Firefox's virtual authenticator exists for testing and its changelog reports unreliable endpoints ([geckodriver changes](https://kdab.searchfox.org/firefox-main/source/testing/geckodriver/CHANGES.md)). Do not build without a new argument |
| **Verify before switching.** A delegated change to the machine's own configuration is built and driven in a VM first (plan row L3) | The Hyprland "magic moment", made safe to leave alone | **Unchecked** (the 2026-11-10 notes say so too) |
| **Local reach as a task class.** Router, printer, home server, tailnet-only pages | Hosted agents cannot reach these at all | **Unchecked** |

The first three are the proposal's bets. They share a property: each uses something
only the person's own desktop has (their secret store, their compositor, their
presence).

## Three years on, if delegation fully succeeds

- **Delegating is a desktop verb,** like printing or sharing: from any window, with
  what is selected, to an agent that already has the right identity. Most tasks
  finish with zero touches, and the ones that need the person say why in one line.
- **The person's rules and identities are theirs,** in files that outlive any model
  or client. Changing agent vendor does not mean re-granting everything.
- **Overnight queues are ordinary.** Unattended work with identity runs inside real
  isolation, and the morning starts with result cards that say what was checked.
- **The ledger is a private benchmark.** Real tasks, with their outcomes and
  touches, can be re-run read-only against a new model to decide which model gets
  which kind of task (the scan's "own-task evaluation", checked there).
- **The machine keeps itself.** Configuration changes are proposed, verified away
  from the real desktop and switched with a rollback, without the person in the
  loop.
- **Other desktops implement the contract.** The event and answer contract is small
  enough for a KDE or GNOME consumer. One search found agent projects built on the
  existing remote-desktop portal ([portal-use](https://coderlegion.com/14454/i-built-a-wayland-native-ai-computer-use-server-because-nobody-else-did),
  [kwin-mcp](https://discuss.kde.org/t/kwin-mcp-mcp-server-for-gui-automation-using-kwins-eis-interface-and-virtual-sessions/44678))
  and no proposal for a delegation or approval portal. **Checked lightly**; a
  standard would need users this project does not have.

What this does not depend on the project for: models finishing long tasks
correctly. The scan reports a best completion of 20.6% on OSWorld 2.0. The design
assumes failures stay common, which is why results carry checks and unknowns.

## Already examined: do not re-propose without new evidence

The maintainer's list of directions already examined and found taken or crowded:
background agents beside the user, self-learning skill libraries, app-to-API
synthesis, effect-based success verification, desktop forking, RL training
environments, a personal-agent substrate, and fixing open-source applications.
Desktop pull requests and exactly-once transactions are candidate **features**
(DELEGATION.md stage Z7 and section 2.4), not directions. The sources recorded so
far are in the [scan](../research/2026-11-12-ambitious-directions-scan.md), the
[big-directions notes](../research/2026-11-10-big-directions-wip.md) and the
[directions board](DIRECTIONS.md).
