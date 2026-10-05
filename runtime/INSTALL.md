# Installing the desktop runtime

The Python package and the desktop runtime are installed separately. Python always
comes from the repository: `uv sync`, then `uv run agent-desktop ...`. The desktop
runtime is the compositor and session tools, and comes from one of the two supported paths
below. Fedora and Arch also run in CI (see `.github/workflows/checks.yml`), but they
are not documented installation targets yet.

## Before you start

You need git, curl and [uv](https://docs.astral.sh/uv/). uv installs with
`curl -LsSf https://astral.sh/uv/install.sh | sh`; open a new login shell
afterwards (or `source ~/.local/bin/env`) so `uv` is on PATH. Then:

```sh
git clone <repository URL> private-agent-desktop
cd private-agent-desktop
uv sync --managed-python   # a uv-managed Python, not the system one
```

After installing, run `uv run agent-desktop doctor --smoke`. It checks the
tools, the runtime directory, accessibility and the wlroots version labwc loads,
then creates, captures and destroys one session.

## NixOS (or any Linux with Nix)

`runtime/nix/flake.nix` builds labwc 0.20.2 against wlroots 0.20.2 with the
X11 mapping repair (`runtime/patches/`), together with grim, dbus, Xwayland and
the optional viewer, clipboard, accessibility and terminal tools. nixpkgs is
pinned by `runtime/nix/flake.lock`. Nothing is installed into a profile and the
host is not changed:

```sh
runtime=$(nix build --no-link --print-out-paths ./runtime/nix)
PATH="$runtime/bin:$PATH" uv run agent-desktop doctor --smoke
```

`doctor` should report `repaired runtime (... (nix))`. Start your agent or MCP
client with the same `PATH` so the sessions it creates use this runtime. A
garbage collection can remove the build; `nix build --out-link` gives it a GC
root if you want to keep it.

## Ubuntu 24.04 LTS

```sh
sh runtime/install-ubuntu.sh   # apt: labwc grim dbus-daemon xwayland + optional tools
uv run agent-desktop doctor --smoke
```

`doctor` should report every check `ok` (wlroots `0.17`). Stopped sessions,
including the one the smoke check creates, stay listed until `uv run
agent-desktop prune`.

Ubuntu 24.04 ships labwc 0.7.1 with wlroots 0.17. Its association code lacks
the same existing-buffer check, but CI has not observed the X11 mapping failure
there. CI runs 100 loaded Xwayland repetitions on stock Ubuntu packages, which
bounds the risk but does not prove it absent. If X11 windows fail to appear,
report it with the `doctor` output.

## What each tool is for

| Tool | Needed for |
| --- | --- |
| labwc, grim, dbus-daemon | Every session (required) |
| Xwayland | X11 applications |
| wayvnc + TigerVNC `vncviewer` | `view` (watch) and `take` (human takeover) |
| wl-clipboard | Clipboard handling, including clearing it after takeover |
| at-spi2-core | Semantic UI tools (`desktop_ui`, `desktop_ui_action`) |
| foot | A terminal for trying sessions by hand |

The full test suite also uses applications that are not part of the runtime.
Tests skip, with a reason, when one is missing. On Ubuntu: `sudo apt-get install
xterm zenity mousepad x11-utils wlr-randr` (and optionally Chromium, LibreOffice
Writer/Calc and kdialog). On Nix, the CI `nix` job shows the equivalent packages.
