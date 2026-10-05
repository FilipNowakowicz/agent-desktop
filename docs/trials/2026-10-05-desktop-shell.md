# Desktop shell trial, 2026-10-05

First real-use trial chosen by the user: their waybar, control panel and
launcher (from `~/nix`, revision `b393c7e`), exercised in a private session with
`scripts/shell_trial/`. The source configuration was only read; copies live in
the git-ignored `artifacts/shell-trial/`.

## Setup and safety

- Nested Hyprland was tried first and abandoned. Aquamarine 0.11 (Hyprland
  0.56.2) attaches a buffer before acknowledging the first `xdg_surface.configure`,
  so labwc correctly disconnects it (`xdg_surface has never been configured`).
  It also tries DRM devices and `/dev/input/event*` through libseat even when
  nested; this failed only because the host Hyprland holds the seat. A bubblewrap
  namespace without `/dev/input`, KMS nodes or the system bus contained it.
- The bar and widgets run directly in labwc instead, with a fake Hyprland IPC
  (`fake_hyprland.py`) answering `hyprland/workspaces` and `hyprctl`.
- Logging stand-ins replace every external command the widgets run (found by an
  AST search after a regex audit missed multi-line calls): nmcli, bluetoothctl,
  wpctl, brightnessctl, systemctl, systemd-inhibit, pkill, pgrep, makoctl,
  tailscale, mullvad, wlsunset, hyprlock, xdg-open and others. The system bus is
  pointed at a non-existent socket. Before the stand-ins were complete, the Awake
  toggle ran the real `systemd-inhibit`; it failed against the blocked system bus
  and the host's only "Control Center" inhibitor was verified to be the user's
  own (started the previous afternoon, no session token).
- Hard-coded `/tmp/control-center.json` and `/tmp/launcher.lock` were redirected
  in the copies, so the trial cannot collide with the running instances.
- GTK 4 layer surfaces rendered blank (Vulkan `VK_ERROR_SURFACE_LOST_KHR`) in the
  software-rendered session until `GSK_RENDERER=cairo` was set for the trial.

## Results

| Component | Check | Result |
| --- | --- | --- |
| waybar | renders workspaces, clock, weather | pass |
| waybar | click workspace 3 | `dispatch focusworkspaceoncurrentmonitor 3`, highlight moves |
| waybar | 500 rapid workspace switches | 0.56 s CPU, RSS 105.4 → 105.6 MB, final state correct |
| control panel | Wi-Fi, Bluetooth, VPN, Focus, Awake, Night | each fires the expected command and restores |
| control panel | volume slider drag 45 → 80 | 8 `wpctl set-volume` calls, label 80 |
| control panel | 126 open/close toggles | RSS 106 → 136 MB in the first opens, then flat (136.3 → 136.4 over 96) |
| launcher | open, type, Enter | opens and launches, but see the completion bug |

## Findings for the user's configuration

1. Launcher: typing an exact command that prefixes another launches the longer
   one (`foot` ran `footclient`, which exited silently). `best_match` excludes
   exact matches and Enter launches typed text plus the suggestion
   (`home/files/scripts/launcher.py`). Output goes to /dev/null, so failures are
   invisible.
2. Control panel accessibility: icon-only buttons (mute, brightness, mic, theme,
   lock, sleep, power) are named only by Nerd Font private-use glyphs; the three
   sliders are not exposed at all; detail-view on/off switches are unnamed
   buttons without a checked state; the window has no name.
3. Control panel Focus toggle uses `makoctl mode -s`, which replaces all modes,
   so toggling do-not-disturb while the panel is open drops its own `cc-open`
   mode (and any other user modes).
4. Control panel single-instance check (`process_alive`) only tests that some
   process has the stored pid. After a crash with pid reuse, `--daemon` exits
   silently and the next toggle sends SIGUSR1 (default action: terminate) to an
   unrelated process.

## Unexplained

Once, after about 140 panel toggles, 500 workspace switches and a launcher run,
waybar was alive but hidden; one SIGUSR1 (its visibility toggle) restored it. A
fresh-session repetition of 190 toggles plus launcher runs never hid it. The
sender of the toggle, if any, is unknown; the earlier run also used an older,
deadlock-prone fake IPC.

## Harness lessons

- The fake IPC first deadlocked: it wrote events on the request thread while
  waybar waited for request replies. Events are now queued per listener.
- `env` execs the program, so the launched pid is the component itself; a script
  that measured "the first child" sampled short-lived helpers instead.
