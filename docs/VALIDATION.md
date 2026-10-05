# Validation guide

Run checks from the repository root after `uv sync --managed-python --locked`.
Tests and fixtures establish specific observations; they do not establish
universal application support. See [compatibility](COMPATIBILITY.md) and
[benchmark results](BENCHMARK.md) for recorded evidence.

## Checks

```sh
uv run ruff check src scripts tests
uv run ruff format --check src scripts tests
uv run python -m unittest discover -s tests -v
# Optional: opens and tears down a visible test desktop.
DESKTOP_TEST_VISIBLE=1 uv run python -m unittest discover -s tests -v
# Repeated lifecycle cycles, optionally with busy CPU processes.
uv run scripts/lifecycle_stress.py --cycles 20 --load 4
```

Integration tests skip when desktop tools are missing; passing unit-only checks
must not be described as a desktop validation.

GitHub Actions minutes are limited. Every PR runs only `Lint` (ruff, compile, unit
tests with desktop tests skipped). The full desktop matrix (`Checks`: Ubuntu,
Nix, Fedora and Arch, about 30 runner-minutes) runs for release tags or on
demand: `gh workflow run checks.yml --ref BRANCH`. Run it before merging changes
to the runtime, packaging or CI, and at milestones; otherwise run the desktop
suite locally and record the result in the PR.

## Original headless experiment

The runtime needs `labwc`, `grim` and `dbus-daemon`; tests also use `foot`.
The original M0 experiment script additionally needs `wtype` and `wlrctl`. Install
them using your distribution's package manager. Python is managed with uv:

```sh
uv sync --managed-python --locked
uv run scripts/m0_headless.py
uv run scripts/m0_headless.py --text 'agent café λ 123'
```

On NixOS, an optional temporary shell can supply the actual desktop runtime tools.
Python and project dependencies remain managed with uv:

```sh
nix shell nixpkgs#labwc nixpkgs#foot nixpkgs#grim nixpkgs#wtype nixpkgs#wlrctl \
  nixpkgs#wayvnc nixpkgs#tigervnc --command zsh
# Inside that temporary shell:
uv run agent-desktop create
```

Runtime executable paths can be supplied with `--labwc` and `--grim` (the M0
script also accepts `--foot`, `--wtype` and `--wlrctl`). The tested NixOS invocation is
in the [development log](../DEVELOPMENT_LOG.md). Headless CI also runs in Fedora
and Arch containers; desktop installs on those distributions remain untested.

The experiment creates a temporary headless labwc session with software rendering,
a private runtime directory, disposable home/configuration and a separate D-Bus
session. It launches a terminal fixture, captures screenshots, types a message and
delivers a virtual mouse click. The fixture checks actual received text and mouse
events. Session resources are stopped and removed; screenshots, logs and a JSON
report remain under `artifacts/m0/`.

When launched from Hyprland, the report compares the host workspace, focused window
and pointer position before and after. These snapshots cannot prove there was no
transient disturbance, and normal human activity can change them.

Graphical separation and disposable configuration do not constitute a security
sandbox. Applications still run as your user with host filesystem and network access.

## Application smoke tests

For a scripted Chromium GUI task with a disposable profile and local HTML fixture:

```sh
uv run scripts/browser_smoke.py
```

For Writer document creation and a Calc formula/save workflow, install optional
LibreOffice Writer, Calc and GTK3 integration, then run:

```sh
uv run scripts/office_smoke.py
uv run scripts/office_smoke.py --component writer
```

The script uses native Wayland, separate disposable office profiles, and validates
the saved ODT paragraphs and ODS formula/result. It handles known first-run
Welcome/Tip dialogs, checks session cleanup and writes artifacts under
`artifacts/office/`. File-dialog validation includes a short fixture delay;
this does not establish general application widget readiness.

For an optional graphical observer smoke test on Hyprland (opens and closes its
own viewer window):

```sh
uv run scripts/viewer_smoke.py
```

See [the benchmark report](BENCHMARK.md) for verified GUI tasks and a
restricted local-container comparison. Its optional harness uses an existing
local runtime and performs no host installation or configuration.

For the reproduced X11 mapping race on wlroots 0.19.3/0.20.2, see the optional
[project-local runtime repair](../runtime/README.md). Stock-package passes do not
establish reliable X11 mapping on that version.
