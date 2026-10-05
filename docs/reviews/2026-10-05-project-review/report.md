# Independent project review — 2026-10-05

> Archive note: this review refers to brainstorming prompts removed during later
> documentation cleanup. Its file/line evidence describes the reviewed revision;
> `prompt1.txt` and `prompt2.txt` remain available at Git commit
> `1e9b20f21188b981b1a398e79aee10ccf924afc0`. Useful ideas now live in
> [PROJECT_PLAN.md](../../../PROJECT_PLAN.md).

**Verdict: a credible engineering alpha with an unfinished daily-use release. Stop adding capabilities for now.** The core private-desktop loop is real, and much of its complexity comes from diagnosing actual failures. What has not been earned is the stronger story: convenient installation, dependable long sessions, private credential handoff, broadly reliable applications or a measured performance advantage. Recommend **O1: harden and package for daily personal use**. The other directions should compete for investment after that pilot, not accumulate as another feature list.

This review covers `8632cdedd2d20701230ae7d0b3afc8afbbce4adf` and live GitHub history checked on 2026-10-05. Source and repository state were read without changes; only this directory was written. No benchmark, paid agent, physical-desktop action, personal profile access or host change was performed. I ran lint and 11 existing non-desktop unit tests successfully, then eight focused unittest probes and one MCP scheduling probe. Those probes **confirm defects/edge cases**, not successful desktop operation. Desktop evidence here comes from inspected CI logs, retained artifacts and explicitly labeled historical reports; I did not rerun the compositor suite.

## Where the project actually stands

M0 is demonstrated; M1 has substantial real receipt, routing, cleanup and recovery coverage; M2 has working stdio/image integration and observer mechanics. Takeover and profiles are implemented but their real user login/resume experience remains unverified. M3 is partial: application fixtures and distribution CI exist, while supported installation and ordinary sustained use remain open. M4 is exploratory measurement, with useful regression fixtures and restricted comparisons. Extensions have already overtaken the unfinished M3 release gate (**F001, F023, F028–F030**).

The latest main CI, **37244764863**, passed 59 discovered tests per job, with six skips on Ubuntu and two each on Fedora/Arch. It also passed 30 Ubuntu focus/crash/X11 repetitions and 100 loaded X11 repetitions on each repaired Fedora/Arch runtime. These are meaningful results. They do not establish Qt accessibility coverage, Ubuntu Chromium coverage or real Fedora/Arch desktop installs (**F018**). The CI query returned 98 runs, 20 failed; I inspected failure excerpts from all 20 and selected full contexts. This is development history, **not** an estimated runtime failure rate: code, tests and environments changed between runs.

Several failures have good explanations: the X11 mapping ordering repair has a trace, a targeted patch and repeated receipt tests; the guardian cleanup assertion raced with guardian exit. Others do not: recent Fedora Chromium typing, the latest empty-line action failure and rapid Calc navigation remain unresolved or mitigated rather than causally explained. The Arch MCP empty-file parse is a separate likely fixture publication race still visible in current code (**F006, F012, F019**).

The inventory in [capabilities.json](capabilities.json) covers 19 capability groups. Its `proven_on` means some scoped test evidence exists, **not** universal distro/application support; limitations distinguish CI containers, historical NixOS reports, graphical viewers and skipped subcases. `repeated-tests` is reserved for repeated recorded checks; `verified-by-you` may mean source/artifact inspection or a mocked probe, as stated in the finding. A one-off observation never becomes a reliability guarantee.

## What shifted, and whether it was justified

The original central goal survived: an existing agent operates an invisible Linux application while the user continues working. This did not turn into a new model or a debugging-only product. Replacing short-lived input helpers with persistent devices, isolating D-Bus, strengthening ownership, verifying focus and repairing X11 mapping were justified by observed failure modes. The project should keep those gains (**F028, F030**).

The less defensible shift is **from “build, use, improve from failures” toward “finish extensions, then measure fixtures.”** Waiting, semantic UI, sequences and crops are plausible improvements, and measurement exposed genuine defects. But “more tools implemented” is not the same as “daily-use gate met.” Packaging and real work remain behind the feature surface. Conversely, prompt2's portable machine, snapshots, host bridge and non-Linux frontend were proposals to defer, not missing promises of the initial release. Reviving the historical debugging-first recommendation would contradict the settled project scope (**F001, F020, F030**).

## Ten highest-priority findings

Within severity, ordering reflects the recommended next work. Full evidence and concrete recommendations are in [findings.jsonl](findings.jsonl).

| Priority | Finding | Severity | Why it changes the next step |
| --- | --- | --- | --- |
| 1 | **F001 — M3 exit still open** | High | Further features are not the principal release blocker. |
| 2 | **F002 — takeover privacy overclaim** | High | Tool refusal does not revoke streams, logs or same-user access. |
| 3 | **F003 — profile deletion lock gap** | High | A persistent-data operation lacks exclusion against startup. |
| 4 | **F004 — unbounded accessibility work** | High | A slow tree can block control and teardown. |
| 5 | **F005 — false combined wait success** | High | “Saved” can be accepted from the wrong application. |
| 6 | **F006 — unexplained input failures** | High | Green reruns are not a demonstrated readiness repair. |
| 7 | **F007 — repaired X11 absent from default install** | High | The user path differs from the passing CI runtime. |
| 8 | **F011 — sequences lack ownership/partial-result safety** | Medium | Interleaving and retries can repeat already delivered actions. |
| 9 | **F013 — unbounded retained state** | Medium | Short tests cannot establish working-day resource behavior. |
| 10 | **F008 — efficiency claim exceeds comparison** | Medium | The next investment should not depend on an unproven cost advantage. |

Additional correctness defects deserve small targeted fixes: unstable screenshot retries still succeed (**F009**); synchronous MCP handlers block unrelated requests (**F010**); semantic IDs recycle into different targets (**F016**); allowed UI output can exceed the RPC response cap (**F017**); clipboard-clear failure resumes control (**F024**); plain waits can ignore both session validity and their timeout (**F036**). Observation tokens remain useful topology/focus guards, but are not pixel, geometry or widget-state guards (**F038**).

Maintainability is becoming a real obligation: a large worker, a hand-written Wayland client, an accessibility client and a private runtime patch sit behind a seemingly small CLI. Lint is clean and there is good test investment; neither substitutes for bounded APIs and clear subsystem contracts. Avoid a wholesale rewrite or universal backend framework while fixing these defects (**F019, F027**).

## Measurement: useful engineering, weak product inference

The recorded numbers are not fabricated: all ten exported tool-profile runs match their retained raw records, and all twelve native/container browser page hashes match their artifacts. Independent page/file/dialog verifiers and negative controls are strengths. The measurements found real fixture, keymap and coordinate problems (**F008, F021, F022**).

The interpretation needs restraint. Matched early standard rounds have 39/40 successes for each profile, fewer full-tool calls, but **higher** full-tool cost. After fixes, one full-only round costs less than older basic rounds; that is promising, not a matched causal result. Hard-suite call savings repeat, but bundling steps itself reduces call count and can increase tokens. Cache behavior, changes to code and prompts, and a discarded usage-limit attempt matter (**F008, F022**).

The Cua comparison supports only successful execution of three fixtures twice on each restricted interface. It cannot separate runtime, browser, screen dimensions, resource caps, caching and adapter effects, and it omits comparable startup timing. Office agent coverage is one two-task run. Saturated synthetic tasks are valuable regressions; they are poor evidence of setup-to-result daily work, which may legitimately combine shell, files, APIs and GUI (**F020–F022**).

## Competitive position

These comparisons use primary documentation accessed **2026-10-05**, not newly installed competitors. Their advertised behavior remains unverified here; the historical Cua artifact comparison has the narrower scope above.

| Alternative | Same, better or worse relative to this project | Worth adopting |
| --- | --- | --- |
| [wbox-mcp](https://github.com/quazardous/wbox-mcp) | Strong overlap in the private/headless compositor/MCP promise; documents more direct onboarding and housekeeping. No demonstrated reliability ranking. **F031** | Project setup, dependency guidance and clean/prune UX. |
| [kde-mcp](https://github.com/atassis/kde-mcp) | Documents semantic-first interaction, leases, policy gates and auditing; more KDE-specific. Its efficiency claims are not evidence for this project. **F032** | Ownership leases, concise state differences, bounded audit records. |
| [Cua](https://github.com/trycua/cua) | Broader documented drivers, provisioning, SDKs and portable environments. This project's narrower local runtime is easier to reason about, but not proven faster or cheaper. **F033** | Readiness/provenance practices; evaluate reuse before building a machine manager. |
| [E2B Desktop](https://github.com/e2b-dev/desktop) | Documents provisioned sandbox APIs and authenticated streaming; its hosted quickstart needs an account/key. Local operation here avoids that dependency but lacks a comparable security boundary. **F034** | Provisioning and streaming contracts when remote execution fits. |

The credible position is a focused, locally controlled Linux runtime with inspectable receipt/recovery evidence. Neither private desktops nor semantic UI nor takeover is unique. Its prospective advantage is **making the user's actual workflow dependable on their chosen machine**; no current comparison establishes that advantage over the alternatives. A bounded diagnostic trace inspired by [Playwright](https://playwright.dev/docs/trace-viewer) could help explain failures, without turning this into a testing product (**F035**).

## Recommendation and decision gates

[options.json](options.json) separates five choices: daily-use hardening (**O1**, recommended), deeper interaction (**O2**), a real isolation boundary (**O3**), portable machines (**O4**) and reuse/contribution (**O5**). O2 needs recurring interaction failures and paired evidence. O3 needs a stated threat model. O4 needs a real non-Linux use case and a provisioning comparison. O5 remains a legitimate way to satisfy the original goal with less maintenance.

[plan.md](plan.md) orders the work: truthful contract → correctness/control → two reproducible installs → bounded working-day operation → actual personal-use pilot → evidence-based investment decision. It includes replacement handoff priorities and status text. [questions.md](questions.md) asks only for choices the code cannot answer: recurring tasks, audience, trust boundary, accounts, platforms, retention, controller ownership, acceptable failure and future usage budget.

The decision to earn next is simple: after ten working days, does the user voluntarily keep using it, and can the failures be explained and recovered without developer intervention? That evidence is more valuable now than another completed extension.
