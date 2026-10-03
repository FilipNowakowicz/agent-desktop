# Tested configurations

Updated: 2026-10-03. Distinguish observed tests from advertised runtime support.

| Environment | Observation |
| --- | --- |
| NixOS / Hyprland 0.56.2, labwc 0.20.2 / wlroots 0.20.2 | Headless keyboard, mouse, screenshots, concurrent sessions, CLI lifecycle and stdio MCP transport passed locally |
| Same host, visible nested labwc | Complete round trips passed, but a later run received an extra space; concurrent-input repeatability remains open |
| Ubuntu 24.04 GitHub Actions runner, distribution runtime packages | Headless CLI lifecycle, input, capture, separation and crash tests passed in run 37159062985; MCP validation follows in its PR |

The fixture is a native Wayland foot 1.28.0 terminal on the initial machine.
Headless rendering uses pixman, one output and scale 1. Tested text includes ASCII,
`café` and Greek lambda with a US session layout. This is not full Unicode/layout coverage.

Ubuntu checks skip visible testing because the runner has no physical Wayland host.
Do not infer support for Xwayland, browsers, GTK/Qt applications or arbitrary
daemonizing processes from these results. General applications need explicit
profile separation and task-specific outcome checks.
