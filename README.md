# Private agent desktop

Give an existing agent its own Linux desktop while you keep using your computer.

The first headless experiment works on NixOS + Hyprland. This is an experiment,
not yet a persistent desktop runtime or MCP server. See [PROJECT_PLAN.md](PROJECT_PLAN.md)
for the product direction and [DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md) for observed results.

## Run the experiment

Install `labwc`, `foot`, `wtype`, `wlrctl`, `grim` and `dbus-run-session` using your
distribution's package manager. Python is managed with uv:

```sh
uv sync --managed-python
uv run scripts/m0_headless.py
uv run scripts/m0_headless.py --text 'agent café λ 123'
```

Executable paths can be supplied with `--labwc`, `--foot`, `--wtype`, `--wlrctl`
and `--grim`. The tested NixOS invocation is in the development log. Other Linux
distributions have not yet been tested.

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

## Next

Implement persistent session lifecycle, application launch, observation and input
through a small CLI/core. Add MCP and a viewer after that core works reliably.
