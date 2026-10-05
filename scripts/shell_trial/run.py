"""Run a desktop shell (bar, control panel, launcher) in a private session.

`prepare` copies the user's configuration into a git-ignored trial directory,
redirects hard-coded global /tmp paths into it, installs logging stand-ins for
system tools and captures the runtime environment of the installed wrappers
(minus their PATH, which would put the real tools first). `start` creates a
private desktop running a fake Hyprland IPC, waybar and the control panel.
Nothing here modifies the source configuration or the host desktop.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from agent_desktop import core  # noqa: E402

HERE = Path(__file__).resolve().parent
TOOLS = (
    "hyprctl",
    "nmcli",
    "bluetoothctl",
    "wpctl",
    "brightnessctl",
    "systemctl",
    "loginctl",
    "powerprofilesctl",
    "tailscale",
    "mullvad",
    "makoctl",
    "wlsunset",
    "theme-switch",
    "nm-connection-editor",
    "blueman-manager",
    "pavucontrol",
    "kitty",
    "poweroff",
    "reboot",
    "shutdown",
    "pgrep",
    "pkill",
    "hyprlock",
    "halt",
    "systemd-inhibit",
    "xdg-open",
)
SIGNATURE = "trial"


def wrapper_environment(executable):
    """Variables a makeWrapper/gApps wrapper sets, except PATH/PYTHONPATH."""
    text = subprocess.run(
        ["strings", executable], capture_output=True, text=True, check=True
    ).stdout
    environment = {}
    for flag, name, *rest in re.findall(
        r"--(set|set-default|prefix) '([^']+)'(?: '([^']*)')?(?: '([^']*)')?", text
    ):
        if name in ("PATH", "PYTHONPATH"):
            continue
        if flag == "prefix":
            separator, value = rest[0], rest[1]
            current = environment.get(name)
            environment[name] = value + (separator + current if current else "")
        else:
            environment.setdefault(name, rest[0])
    exec_line = re.search(r"exec (\S+python3\S*) ", text) or re.search(
        r"(/nix/store/\S+-python3-[^/\s]+-env/bin/python3)", text
    )
    return environment, exec_line.group(1) if exec_line else None


def localize_tmp(root, tmp):
    """Point hard-coded /tmp paths at the trial directory; return the changes."""
    changes = []
    for path in root.rglob("*.py"):
        text = path.read_text()
        updated = re.sub(r"(['\"])/tmp/", lambda m: f"{m.group(1)}{tmp}/", text)
        if updated != text:
            changes.append(str(path.relative_to(root)))
            path.write_text(updated)
    return changes


def prepare(args):
    source = Path(args.source).expanduser().resolve()
    trial = Path(args.trial).resolve()
    if trial.exists():
        shutil.rmtree(trial)
    (trial / "tmp").mkdir(parents=True, mode=0o700)
    shutil.copytree(source / "packages/control-center/src", trial / "control-center")
    (trial / "launcher").mkdir()
    shutil.copyfile(
        source / "home/files/scripts/launcher.py", trial / "launcher/launcher.py"
    )
    waybar = trial / "waybar"
    waybar.mkdir()
    for name in ("config", "style.css", "colors.css"):
        deployed = Path.home() / ".config/waybar" / name
        shutil.copyfile(deployed.resolve(), waybar / name)
    style = (waybar / "style.css").read_text()
    (waybar / "style.css").write_text(
        style.replace(
            str(Path.home() / ".config/waybar/colors.css"), str(waybar / "colors.css")
        )
    )
    changes = localize_tmp(trial / "control-center", trial / "tmp")
    changes += localize_tmp(trial / "launcher", trial / "tmp")
    stubs = trial / "stubs"
    stubs.mkdir()
    for tool in TOOLS:
        (stubs / tool).symlink_to(HERE / "stub.py")
    environments = {}
    for name in ("control-center", "launcher"):
        executable = Path(shutil.which(name)).resolve()
        environment, _ = wrapper_environment(executable)
        wrapped = executable.with_name(f".{executable.name}-wrapped")
        found = re.search(r"exec (\S+/bin/python3)", wrapped.read_text())
        environments[name] = {
            "env": environment,
            "python": found.group(1),
            "source": str(executable),
        }
    manifest = {
        "source": str(source),
        "source_revision": subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "tmp_redirected_in": changes,
        "stubbed_tools": list(TOOLS),
        "waybar": shutil.which("waybar"),
        "environments": environments,
    }
    (trial / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        json.dumps(
            {k: manifest[k] for k in ("source_revision", "tmp_redirected_in")}, indent=2
        )
    )


def command_for(trial, manifest, component, extra=()):
    """argv that runs one component with stubs first on PATH and no system bus."""
    log = trial / "calls.jsonl"
    common = {
        "PATH": f"{trial / 'stubs'}:{os.environ['PATH']}",
        "SHELL_TRIAL_LOG": str(log),
        "SHELL_TRIAL_STATE": str(trial / "tmp/stub-state.json"),
        "HYPRLAND_INSTANCE_SIGNATURE": SIGNATURE,
        # Read-only system-bus probes (BlueZ, power profiles) degrade instead.
        "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/nonexistent/system_bus_socket",
        "GDK_BACKEND": "wayland",
        # Headless sessions render in software; GTK 4 would pick Vulkan or GL.
        "GSK_RENDERER": "cairo",
    }
    if component == "hyprland":
        argv = [sys.executable, str(HERE / "fake_hyprland.py")]
        environment = common
    elif component == "waybar":
        argv = [
            manifest["waybar"],
            "-c",
            str(trial / "waybar/config"),
            "-s",
            str(trial / "waybar/style.css"),
        ]
        environment = common
    else:
        spec = manifest["environments"][component]
        environment = {**spec["env"], **common}
        if component == "control-center":
            environment["PYTHONPATH"] = str(trial / "control-center")
            argv = [spec["python"], "-m", "control_center", *extra]
        else:
            argv = [spec["python"], str(trial / "launcher/launcher.py"), *extra]
    return ["env", *(f"{k}={v}" for k, v in environment.items()), *argv]


def start(args):
    trial = Path(args.trial).resolve()
    manifest = json.loads((trial / "manifest.json").read_text())
    session = core.create(profile=None)["session"]
    print(json.dumps({"session": session}), flush=True)
    runtime = Path(core.manifest(session)["runtime"])
    core.request(session, "launch", argv=command_for(trial, manifest, "hyprland"))
    ready = runtime / "hypr" / SIGNATURE / "ready"
    deadline = time.monotonic() + 10
    while not ready.exists():
        if time.monotonic() > deadline:
            raise SystemExit("fake Hyprland IPC did not start")
        time.sleep(0.05)
    apps = {
        "waybar": core.request(
            session, "launch", argv=command_for(trial, manifest, "waybar")
        ),
        "control-center": core.request(
            session,
            "launch",
            argv=command_for(trial, manifest, "control-center", ["--daemon"]),
        ),
    }
    (trial / "session.json").write_text(
        json.dumps({"session": session, "apps": apps}, indent=2) + "\n"
    )
    print(
        json.dumps({"session": session, "apps": {k: v["pid"] for k, v in apps.items()}})
    )


def launch(args):
    """Run a component once more, e.g. `control-center` to toggle the panel."""
    trial = Path(args.trial).resolve()
    manifest = json.loads((trial / "manifest.json").read_text())
    session = json.loads((trial / "session.json").read_text())["session"]
    result = core.request(
        session,
        "launch",
        argv=command_for(trial, manifest, args.component, args.extra),
    )
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", default="artifacts/shell-trial")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--source", default="~/nix")
    sub.add_parser("start")
    p = sub.add_parser("launch")
    p.add_argument("component", choices=("control-center", "launcher", "waybar"))
    p.add_argument("extra", nargs="*")
    args = parser.parse_args()
    {"prepare": prepare, "start": start, "launch": launch}[args.command](args)


if __name__ == "__main__":
    main()
