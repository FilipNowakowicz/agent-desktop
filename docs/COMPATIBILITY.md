# Tested configurations

Updated: 2026-10-04. Distinguish observed tests from advertised runtime support.

| Environment | Observation |
| --- | --- |
| NixOS / Hyprland 0.56.2, labwc 0.20.2 / wlroots 0.20.2 | Headless keyboard, mouse, screenshots, concurrent sessions, CLI lifecycle and stdio MCP transport passed locally |
| Same host, visible nested labwc | Round trips pass when the host keyboard is idle. Host keyboard input reaches the nested session whenever its window has host focus; three 2026-10-04 runs received an extra character decoded with the host keymap |
| Ubuntu 24.04 GitHub Actions runner, distribution runtime packages | Headless CLI tests passed in run 37159062985; real stdio MCP/image integration passed in run 37159264698 |
| Ubuntu 24.04 CI (labwc 0.7.1, foot 1.16.2, Xwayland 23.2.6, xterm 390, zenity 4.0.1, wayvnc 0.7.2) | Full headless suite including Xwayland and GTK dialogs, plus stress cycles. One intermittent focus-test failure in 7 runs (issue #17) |
| Fedora 44 container in CI (labwc 0.9.6, foot 1.27.0, Xwayland 24.1.13, xterm 411, zenity 4.2.2, wayvnc 0.9.1) | Full headless suite and stress cycles passed (run 37164358545) |
| Arch Linux container in CI (labwc 0.20.2, foot 1.28.0, Xwayland 24.1.13, xterm 411, zenity 4.2.2, wayvnc 0.10.2) | Full headless suite and stress cycles passed (run 37164358545) |
| NixOS / Hyprland, wayvnc 0.10.1 + TigerVNC 1.16.2 | Unix VNC handshake, ignored observer input, viewer disconnect survival and graphical observer window passed locally |
| NixOS / Chromium 153.0.8010.52, native Wayland, disposable profile | Local HTML form task passed with Unicode text, submitted-title verification, changed screenshot and no owned processes remaining; with `--password-store=basic` after the private-bus fix (3/3 runs, 23 owned processes including crashpad, portals and mako) |
| NixOS, pointer fixture in foot and Chromium DOM pointer events | Absolute clicks repeat on the same cell; drag delivers press, held-button motion and release (pointer test 10/10 idle, 10/10 with 12 busy processes); Chromium drag 3/3 at the exact requested 427 px distance |
| NixOS, persistent virtual keyboard into foot | Typing immediately after the window becomes active, 300+ distinct CJK characters (keymap reset), repeats, Ctrl modifier and invalid-key rejection: 10/10 idle, 10/10 with 12 busy processes; no wtype installed |
| NixOS, Xwayland 24.1.13 + xterm 411 | X11 terminal receives `x11 café λ` and a mouse click: 10/10 idle, 10/10 with 12 busy processes |
| NixOS, zenity 4.2.2 (GTK) and kdialog 26.08.1 (Qt 6), each on native Wayland and X11 | Entry dialogs receive Unicode text and Return; exact stdout checked: 5/5 idle, 5/5 loaded |
| NixOS, wlr-randr 0.5.0 on headless output | Mode change to 1024×768 updates coordinate bounds; scale 2 is rejected |
| NixOS, supervisor crash | SIGKILL of the worker: guardian stopped all processes including a token-less daemon, removed the runtime and marked the session failed. SIGKILL of worker and guardian: `destroy` recovered by token |
| NixOS, terminal fixture plus daemonizing child, repeated lifecycle | Final code: 20/20 create/type/destroy cycles with 12 busy CPU processes on 12 cores; 40/40 earlier branch cycles (20 idle, 20 loaded). No token, daemon or runtime leftovers |

The fixture is a native Wayland foot 1.28.0 terminal on the initial machine.
Headless rendering uses pixman, one output and scale 1. Tested text includes ASCII,
`café`, Greek lambda and 300 CJK ideographs. Typed text uses a generated per-character
keymap, so it is layout-independent; key chords use keysym names. Input methods (IME),
dead keys and applications that interpret physical layouts are not covered.

Ubuntu checks skip visible testing because the runner has no physical Wayland host.
Do not infer general support for browsers beyond the one tested fixture, GTK/Qt
applications beyond simple dialogs, X11 applications beyond xterm and the dialogs,
or processes started by host services outside the session tree. General applications need explicit profile separation and task-specific
outcome checks.
