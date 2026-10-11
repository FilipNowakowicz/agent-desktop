# Directions board

This is a thinking board of directions the project could take. It is **not
current work and not a promise**. Current direction lives in
[PROJECT_PLAN.md](PROJECT_PLAN.md), and the active test plan is
[effect first](../research/2026-10-11-effect-first.md). Use the board when
choosing what comes next: add ideas, record evidence for or against them, and
change their status. Do not delete an idea that was rejected; mark it and say
why.

Status values: **idea** (not tested), **testing** (an experiment is running),
**supported** or **weakened** (evidence, with a link), **adopted** (moved
into the plan), **rejected** (with the reason).

## Why the board exists

All the methods built so far, and the effect-first thesis too, keep one
picture: **a model operates a GUI like a person, one look and one action at a
time.** In that picture each turn costs about 3 s, and model time is about 78%
of wall time ([effect first §1](../research/2026-10-11-effect-first.md)).
Optimising inside the picture gave 14–33% on specific tasks. A larger change
probably needs to drop one assumption of the picture. Each direction below says
which assumption it drops.

## How to choose

Prefer directions that:

- cut **turns per task**, not only the cost of a turn;
- reuse what the project uniquely has: private sessions whose applications we
  start ourselves, effect observation, accessibility, the browser bridge, the
  atlas, and takeover;
- fit the users, who are coding agents reached through MCP;
- can be tested cheaply on the subscription (`claude -p`), with no API credits
  and no GPU.

## Directions

### D1. The agent writes programs instead of clicking

- **Assumption dropped:** the agent operates the GUI step by step.
- **Idea:** the agent writes a short program against a typed desktop library,
  and the program runs at machine speed. For example, it loops over table rows,
  presses buttons through accessibility, and finishes with effect assertions.
- **Why it could be big:**
  - Coding is what models do best, and the users are coding agents.
  - Loops and conditionals turn many-turn tasks into one turn.
  - A program that works is already a reusable skill, and its assertions are
    its tests.
  - It may explain why guarded steps failed (S2): JSON step lists with optional
    expectations are foreign to the agent, while code with `assert` is not.
- **Risks:**
  - The agent still has to look at an unfamiliar UI before it can write code.
  - Arbitrary code is an unbounded action space.
  - Fast code also makes mistakes fast, so it needs private sessions and commit
    points.
- **Prior art:** [Agent S](https://arxiv.org/pdf/2410.08164) avoided code as
  its main action for these reasons. [Jev-Mobile](https://arxiv.org/pdf/2609.30186)
  runs a programmatic executor over the accessibility tree. The
  [GUI agent survey](https://arxiv.org/pdf/2504.13865) separates API actions
  from simulated input. No search so far found a desktop agent whose main action
  is writing programs.
- **Cheapest test:** one tool that runs Python in the session with a small
  library (accessibility find and press, browser bridge, effect assertions),
  compared with the current tools on `hard-web-admin` and the E0 suite. It is
  worth pursuing only if turns fall by 50% or more on the table task at equal
  success.
- **Status:** idea. Proposed in discussion as the leading candidate together
  with D2; not yet decided.

### D2. Make every application readable as structure

- **Assumption dropped:** the screen is pixels.
- **Idea:** extend the browser bridge to every toolkit:
  - Electron applications (VS Code, Slack, Discord, Obsidian) through the
    DevTools protocol (`--remote-debugging-port`);
  - GTK and Qt through inspectors and object models;
  - LibreOffice through UNO;
  - terminals as text.

  In a private session we start every application ourselves, so we can switch
  these hooks on. A tool that drives the person's own desktop cannot do that.
- **Why it could be big:** most applications become a DOM. Pixels are needed
  only for canvas, games, video and remote desktops.
- **Risks:** an adapter is needed for each toolkit, and adapters break across
  versions. Debug ports must be protected.
- **Prior art:** [Tactile](https://arxiv.org/pdf/2607.14443) argues for
  accessibility first, and
  [DirectShell](https://dev.to/tlrag/-directshell-i-turned-the-accessibility-layer-into-a-universal-app-interface-no-screenshots-no-2457)
  uses the accessibility layer as a universal interface. Another project, also
  called [agent-desktop](https://www.mintlify.com/lahfir/agent-desktop/api/click),
  tries accessibility actions before clicks. That matters for naming.
- **Cheapest test:** one Electron adapter (DevTools protocol) for a single
  application, measured against pixels on two tasks, as the browser-bridge A/B
  was.
- **Status:** idea. It pairs with D1, which gives the agent the language and D2
  the surface.

### D3. Know what happened instead of looking (effect first)

- **Assumption dropped:** the agent checks progress by looking.
- **Idea, evidence and test plan:** [effect first](../research/2026-10-11-effect-first.md)
  §3 and E2.
- **Status:** testing is planned, with E2 as the gate. Under D1 it becomes the
  assertion library.

### D4. Learn from the person

- **Assumption dropped:** the agent works out every task itself.
- **Idea:** the person does a task once, or normal use is recorded together
  with its effects, and the result is compiled into a checked, parameterised
  procedure.
- **Why it could be big:** first runs need no exploration, and the idea fits
  takeover and profiles. Programming by demonstration is old (Automator,
  Sikuli). What it lacked was generalisation, which language models now
  provide, and verification, which effects provide.
- **Risks:** a recording overfits to one screen state. Recording real use
  raises privacy questions, so it must be opt-in and visible.
- **Cheapest test:** record one takeover with its effects, have the agent turn
  it into a procedure, then replay it from a fresh state with changed
  parameters.
- **Status:** idea. PROJECT_PLAN already lists human demonstration as a later
  idea.

### D5. Shared app knowledge

- **Assumption dropped:** every agent starts from zero on each application.
- **Idea:** a public registry of version-pinned application maps and skills
  (for example a "Geany 2.1 settings atlas" or "LibreOffice 25.2 skills"), each
  checked by effects so that anyone can verify it again.
- **Why it could be big:** one person's exploration makes everyone's first run
  fast. It has a network effect and is the strongest platform shape for the
  project.
- **Risks:** it needs users before it has value. It needs signing and
  re-checking so that it cannot carry malicious skills. It needs a maintainer
  decision on publishing.
- **Cheapest test:** publish the Mousepad and Geany atlases as versioned files
  and re-check them on a different machine or version.
- **Status:** idea.

### D6. The person does not wait

- **Assumption dropped:** speed means the latency of one task.
- **Idea:** many private desktops work in parallel in the background, and the
  person reviews their effects as a pull request.
- **Why it could matter:** for much work, not waiting matters more than the
  seconds per turn.
- **Risks:** it does not make any single task faster, so it is a product
  framing rather than a breakthrough. It also needs a review app.
- **Status:** idea. It is linked to the review app in
  [effect first §8](../research/2026-10-11-effect-first.md).

### D7. Applications declare their actions

- **Assumption dropped:** agents adapt to applications.
- **Idea:** operating systems are starting to expose application actions to
  agents (Apple App Intents, and announcements around MCP in Windows). Linux
  has no equivalent. A D-Bus or portal "intents" layer, filled in by our
  adapters and atlas, could provide one.
- **Risks:** it is long-term and depends on application developers adopting it.
  The Windows claim above has not been checked in detail.
- **Status:** idea.

### D8. A continuous agent

- **Assumption dropped:** the request-and-response turn.
- **Idea:** perception runs continuously and narrates changes as text
  ([AOI](https://arxiv.org/abs/2606.29472)), steps execute while the reply is
  still streaming, and the next observation is prepared while the model thinks.
  In the end this means a model that takes a video stream.
- **Risks:** most of it needs our own API loop, and true streaming needs a model
  trained for it, which is lab territory.
- **Status:** idea. It is deferred until there is funding
  ([effect first §7](../research/2026-10-11-effect-first.md)).

### D9. A two-speed agent and a small specialist model

- **Assumption dropped:** one large model does everything.
- **Idea:** a fast model locates elements and checks results at about 1 s per
  step, and the large model decides and handles surprises. Later, a small
  model could be LoRA-tuned on effect-labelled data from D3.
- **Risks:** no GPU or API credits now. Training a general computer-use model is
  out of reach and not the project's strength.
- **Status:** idea. Haiku subagents through `claude -p` could approximate it.

## Product and platform notes

These are not directions on their own, but they constrain the directions.

- **End state:** an engine, MCP as the agent interface, and a review app
  ("effects as a pull request"). See
  [effect first §8](../research/2026-10-11-effect-first.md).
- **Windows and macOS:** first a Linux desktop inside them (WSL2 with WSLg, or
  a VM), then native host mode, then native private sessions. Port only after
  the thesis holds. See [effect first §9](../research/2026-10-11-effect-first.md).

## Log

- 2026-10-11: board created from discussion with the maintainer; D1–D9 recorded
  as ideas.
