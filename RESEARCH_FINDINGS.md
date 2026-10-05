# Historical research and assessment

Date: 2026-10-02

> Historical scope note, 2026-10-03: the user chose to pursue general computer use through a private Linux desktop, tested initially on NixOS. See `PROJECT_PLAN.md` for the current direction, newer popularity snapshot, implementation milestones and extensions, and [START_HERE.md](START_HERE.md) for contributor orientation. The debugging-first recommendation below is historical and is not the chosen product scope.

Based on the early brainstorming prompts (now retired; useful ideas are retained
in [the project plan](PROJECT_PLAN.md)) and a review of public project documentation and GitHub repository metadata. This is an initial survey, not an exhaustive market study or technical audit. At the time of this survey, no competing tools had been installed or benchmarked and no prototype had been implemented. Later implementation and comparisons are recorded in [the development log](DEVELOPMENT_LOG.md) and [benchmark report](docs/BENCHMARK.md).

## The proposed idea

Give a coding agent a private Linux graphical environment in which it can launch applications, inspect UI state, take screenshots and interact without interfering with the user's physical desktop.

The larger vision adds application logs and system observations, reproducible task environments, action recording, replay, GUI tests and before/after verification. A possible later direction is a managed Linux/NixOS agent machine running behind Linux, Windows or macOS frontends.

## Existing projects

The following are documented capabilities, not independently verified behavior or guarantees of compatibility with NixOS/Hyprland.

| Project | Relevant documented capabilities | Implication |
| --- | --- | --- |
| [wbox-mcp](https://github.com/quazardous/wbox-mcp) | Private nested Linux compositor, headless operation, screenshots, isolated input, MCP and application logs | Close overlap with the initial private-desktop MVP; worth evaluating before rebuilding it. |
| [kde-mcp](https://github.com/atassis/kde-mcp) | AT-SPI accessibility-first control, screenshot fallback, headless KWin mode and optional VNC viewing | Semantic interaction combined with a private Wayland desktop already has an implementation. |
| [Cua](https://github.com/trycua/cua) | Desktop automation, local/cloud sandboxes, commands, services, files, agent integrations and evaluation tooling | Significant overlap with the broader agent-computer vision. |
| [E2B Desktop](https://github.com/e2b-dev/desktop) | Programmable desktop sandboxes, screenshots, keyboard/mouse input, window control and streaming | Virtual computers for agents are an existing product category. SDK sources now live in the E2B monorepo. |

Related precedent: [Playwright Trace Viewer](https://playwright.dev/docs/trace-viewer) connects browser actions with snapshots, logs and network activity. It is a useful reference for debugging evidence, although its scope differs from general Linux desktop automation.

## Popularity snapshot

These exact counts were retrieved from the GitHub repository API on 2026-10-02. They will change.

| Repository | Stars | Forks |
| --- | ---: | ---: |
| [quazardous/wbox-mcp](https://github.com/quazardous/wbox-mcp) | 10 | 2 |
| [atassis/kde-mcp](https://github.com/atassis/kde-mcp) | 8 | 0 |
| [trycua/cua](https://github.com/trycua/cua) | 27,691 | 1,949 |
| [e2b-dev/desktop](https://github.com/e2b-dev/desktop) | 1,501 | 186 |
| [e2b-dev/E2B](https://github.com/e2b-dev/E2B) | 14,088 | 1,068 |

API source pattern: `https://api.github.com/repos/<owner>/<repository>`; fields: `stargazers_count` and `forks_count`.

Interpretation:

- The closest Linux-specific projects have very limited public traction.
- The broader platforms have substantial developer interest.
- Stars and forks do not establish active usage, reliability, customer numbers or revenue.
- Broader platform popularity does not prove adoption of this particular GUI debugging workflow.
- Low adoption of the small projects could reflect limited visibility, an immature implementation or a small market. This survey cannot distinguish those explanations.

## Assessment, including the correction made during discussion

The private desktop addresses a concrete personal problem: agent GUI interaction interrupts the user's work. A dependable solution could be valuable even without becoming a business.

An initially suggested differentiator was the full loop:

> Reproduce a GUI bug → inspect UI and system evidence → change code → repeat the interaction → verify the fix.

The user correctly challenged whether existing tools can already support this. They can supply the capabilities for an agent to perform that loop. Calling the workflow itself a distinct opportunity overstated the evidence. A more integrated implementation may be useful, but the workflow is not established as a novel invention.

The defensible conclusions are:

- **Useful personal/engineering project:** yes, particularly if existing tools fail on the user's actual setup and tasks.
- **Potential open-source product:** plausible if it materially improves reliability, setup, reproducibility or usability.
- **Commercial opportunity:** unproven; no customer or willingness-to-pay research was performed.
- **Revolutionary idea as currently described:** insufficient evidence. Combining the listed capabilities does not by itself establish a breakthrough.
- **Already solved by a popular, polished direct competitor:** also not established. Close implementations exist, but their real-world suitability remains untested.

Reliability, diagnosis quality, cost and repeatability are possible dimensions of improvement. They are hypotheses to test, not gaps demonstrated by this survey.

## Technical points to preserve

1. **The agent compositor need not match the host compositor.** A controlled private compositor may avoid maintaining separate control paths for every physical desktop. [Weston documents headless and nested backends](https://wayland.pages.freedesktop.org/weston/toc/running-weston.html), but capture and isolated input still need a compatible implementation.
2. **Display separation is not a complete security sandbox.** Separate windows and input do not automatically separate filesystem access, credentials, application profiles or session services. Define the actual boundary explicitly.
3. **Session services matter.** Accessibility has its own bus discovery and lifecycle; merely changing the display socket is not a complete session-isolation design. See the [AT-SPI bus documentation](https://github.com/GNOME/at-spi2-core/blob/main/bus/README.md).
4. **Semantic UI access is useful but needs application-specific validation.** [AT-SPI](https://docs.gtk.org/atspi2/class.Accessible.html) exposes names, roles, states and actions. Experiments must establish coverage in target apps. Semantic success alone cannot verify visual layout or rendering.
5. **Recording, replay and bug reproduction are different milestones.** Replay needs stable targeting, waits and assertions. Reproduction also needs appropriate initial data, dependencies and external-service behavior.
6. **Pinned software does not imply deterministic runtime state.** Nix can help define the software environment, but does not alone reproduce mutable data, live services, timing or external responses. Start with repeatable startup from known state before attempting full running-machine snapshots.
7. **Event proximity does not prove causation.** A click followed by a network error is useful evidence, but the events may be unrelated. Begin with application output and its process tree before collecting broad host telemetry.
8. **Portable Linux execution verifies Linux behavior.** It does not automatically test the native Windows or macOS behavior of cross-platform applications.

## Recommended next investigation

Evaluate the strongest existing candidates on the tasks actually wanted before choosing to build a competing runtime. Reuse, contribution or packaging may solve the original need.

### First: test the private desktop foundation

- Try representative applications on the user's NixOS/Hyprland machine.
- Verify invisible screenshots, keyboard/mouse routing, application profile separation, clean teardown and uninterrupted host use.
- Repeat runs to expose intermittent failures.
- Record concrete failures and setup friction instead of relying on feature lists.

### Then: test whether a new layer improves debugging

- Select roughly three real GUI bugs.
- Reproduce each from known initial state, inspect evidence, apply a fix and rerun the same check.
- Require the verification to fail on the original revision and pass on the fixed revision.
- Compare with the current manual/agent workflow and the closest existing tool.
- Measure task completion, human interventions, elapsed time, model usage and failed reruns.

Only expand if those experiments reveal a recurring problem that can be solved materially better. Keep the managed Windows/macOS Linux-machine direction deferred until the smaller workflow earns repeat use.

## Open questions

- Which existing tool works best on the user's actual machine?
- Where do existing tools fail repeatedly on real debugging tasks?
- Are the failures in infrastructure, application accessibility, agent reasoning or verification design?
- Can a targeted improvement substantially reduce failures or human intervention?
- Do other developers experience the same problem frequently enough to adopt a new tool?
- Would extending an existing project achieve the same result with less maintenance?

The next useful evidence is hands-on comparison. Neither feature overlap nor GitHub popularity settles the product question.
