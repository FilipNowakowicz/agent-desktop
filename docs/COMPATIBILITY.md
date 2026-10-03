# Tested configurations

Updated: 2026-10-04. Distinguish observed tests from advertised runtime support.

| Environment | Observation |
| --- | --- |
| NixOS / Hyprland 0.56.2, labwc 0.20.2 / wlroots 0.20.2 | Headless keyboard, mouse, screenshots, concurrent sessions, CLI lifecycle and stdio MCP transport passed locally |
| Same host, visible nested labwc | Complete round trips passed, but a later run received an extra space; concurrent-input repeatability remains open |
| Ubuntu 24.04 GitHub Actions runner, distribution runtime packages | Headless CLI tests passed in run 37159062985; real stdio MCP/image integration passed in run 37159264698 |
| NixOS / Hyprland, wayvnc 0.10.1 + TigerVNC 1.16.2 | Unix VNC handshake, ignored observer input, viewer disconnect survival and graphical observer window passed locally |
| NixOS / Chromium 153.0.8010.52, native Wayland, disposable profile | Local HTML form task passed with Unicode text, submitted-title verification, changed screenshot and no owned processes remaining; with `--password-store=basic` after the private-bus fix (3/3 runs, 23 owned processes including crashpad, portals and mako) |
| NixOS, terminal fixture plus daemonizing child, repeated lifecycle | Final code: 20/20 create/type/destroy cycles with 12 busy CPU processes on 12 cores; 40/40 earlier branch cycles (20 idle, 20 loaded). No token, daemon or runtime leftovers |

The fixture is a native Wayland foot 1.28.0 terminal on the initial machine.
Headless rendering uses pixman, one output and scale 1. Tested text includes ASCII,
`café` and Greek lambda with a US session layout. This is not full Unicode/layout coverage.

Ubuntu checks skip visible testing because the runner has no physical Wayland host.
Do not infer general support for Xwayland, browsers beyond the one tested fixture,
GTK/Qt applications, or processes started by host services outside the session
tree. General applications need explicit profile separation and task-specific
outcome checks.
