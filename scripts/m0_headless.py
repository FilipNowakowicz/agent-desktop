"""Disposable headless labwc experiment; never connect input to the host display."""

import argparse
import hashlib
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path


def run(argv, *, env=None, timeout=10):
    return subprocess.run(
        argv, env=env, check=True, capture_output=True, text=True, timeout=timeout
    ).stdout.strip()


def host_state():
    if not shutil.which("hyprctl") or not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return None
    workspace = json.loads(run(["hyprctl", "-j", "activeworkspace"]))
    window = json.loads(run(["hyprctl", "-j", "activewindow"]))
    cursor = json.loads(run(["hyprctl", "-j", "cursorpos"]))
    return {
        "workspace": workspace.get("id"),
        "window": window.get("address"),
        "cursor": cursor,
    }


def wait_for(predicate, process, description, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"Compositor exited ({process.returncode}): {description}"
            )
        value = predicate()
        if value:
            return value
        time.sleep(0.1)
    raise TimeoutError(description)


def owned_processes(token):
    marker = f"AGENT_DESKTOP_EXPERIMENT={token}".encode()
    found = []
    for path in Path("/proc").iterdir():
        if not path.name.isdecimal():
            continue
        try:
            if marker in (path / "environ").read_bytes().split(b"\0"):
                found.append(int(path.name))
        except (OSError, PermissionError):
            pass
    return found


def stop_owned(token):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid in owned_processes(token):
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and owned_processes(token):
            time.sleep(0.1)
        if not owned_processes(token):
            return
    raise RuntimeError(f"Owned processes remain: {owned_processes(token)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for tool in ("labwc", "foot", "wtype", "grim", "wlrctl"):
        parser.add_argument(f"--{tool}", default=tool)
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts/m0"))
    parser.add_argument("--text", default="agent desktop 123")
    args = parser.parse_args()
    binaries = {}
    for tool in ("labwc", "foot", "wtype", "grim", "wlrctl"):
        binaries[tool] = shutil.which(getattr(args, tool))
        if not binaries[tool]:
            parser.error(f"Missing executable: {getattr(args, tool)}")
    output = args.artifacts.resolve() / time.strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    report = {"tools": binaries, "host_before": host_state(), "passed": False}
    process = None
    token = uuid.uuid4().hex
    report["ownership_token"] = token
    try:
        with tempfile.TemporaryDirectory(prefix="agent-desktop-m0-") as directory:
            root = Path(directory)
            runtime = root / "runtime"
            runtime.mkdir(mode=0o700)
            home = root / "home"
            home.mkdir(mode=0o700)
            config = root / "config"
            config.mkdir()
            (config / "rc.xml").write_text(
                "<labwc_config><core><decoration>server</decoration></core>"
                "<keyboard><default/></keyboard></labwc_config>\n"
            )
            # Empty files prevent loading personal startup/environment hooks.
            for filename in ("autostart", "environment", "shutdown"):
                (config / filename).write_text("")
            ready = root / "ready"
            result = root / "typed.txt"
            startup = shlex.join(
                [
                    binaries["foot"],
                    "--config=/dev/null",
                    "--title=Agent desktop M0",
                    "--window-size-pixels=800x500",
                    sys.executable,
                    str(Path(__file__).with_name("m0_terminal.py").resolve()),
                    str(root),
                ]
            )
            env = os.environ.copy()
            for key in (
                "DISPLAY",
                "WAYLAND_DISPLAY",
                "WAYLAND_SOCKET",
                "DBUS_SESSION_BUS_ADDRESS",
                "DBUS_SESSION_BUS_PID",
                "AT_SPI_BUS_ADDRESS",
                "HYPRLAND_INSTANCE_SIGNATURE",
                "SWAYSOCK",
                "I3SOCK",
                "SESSION_MANAGER",
                "DESKTOP_STARTUP_ID",
                "XAUTHORITY",
                "XDG_ACTIVATION_TOKEN",
            ):
                env.pop(key, None)
            env.update(
                {
                    "HOME": str(home),
                    "XDG_RUNTIME_DIR": str(runtime),
                    "XDG_CONFIG_HOME": str(home / ".config"),
                    "XDG_CACHE_HOME": str(home / ".cache"),
                    "XDG_DATA_HOME": str(home / ".local/share"),
                    "XDG_STATE_HOME": str(home / ".local/state"),
                    "XDG_SESSION_TYPE": "wayland",
                    "XDG_CURRENT_DESKTOP": "labwc",
                    "WLR_BACKENDS": "headless",
                    "WLR_RENDERER": "pixman",
                    "WLR_HEADLESS_OUTPUTS": "1",
                    "WLR_LIBINPUT_NO_DEVICES": "1",
                    "XKB_DEFAULT_LAYOUT": "us",
                    "AGENT_DESKTOP_EXPERIMENT": token,
                }
            )
            argv = [
                "dbus-run-session",
                "--",
                binaries["labwc"],
                "-C",
                str(config),
                "-s",
                startup,
            ]
            report["command"] = argv
            report["session_environment"] = {
                key: env[key]
                for key in ("WLR_BACKENDS", "WLR_RENDERER", "XKB_DEFAULT_LAYOUT")
            }
            with (output / "session.log").open("w") as log:
                process = subprocess.Popen(
                    argv, env=env, stdout=log, stderr=log, start_new_session=True
                )
                try:
                    socket = wait_for(
                        lambda: next(
                            (p for p in runtime.glob("wayland-*") if p.is_socket()),
                            None,
                        ),
                        process,
                        "waiting for private Wayland socket",
                    )
                    env["WAYLAND_DISPLAY"] = socket.name
                    assert (
                        Path(env["XDG_RUNTIME_DIR"]) / env["WAYLAND_DISPLAY"] == socket
                    )
                    wait_for(ready.exists, process, "waiting for disposable terminal")
                    time.sleep(0.5)
                    before = output / "before.png"
                    after = output / "after.png"
                    run([binaries["grim"], str(before)], env=env)
                    text = args.text
                    run(
                        [
                            binaries["wtype"],
                            "-s",
                            "200",
                            "-d",
                            "20",
                            text,
                            "-k",
                            "Return",
                        ],
                        env=env,
                    )
                    wait_for(result.exists, process, "waiting for typed message")
                    received = result.read_text()
                    report["expected_text"] = text
                    report["received_text"] = received
                    if received != text:
                        raise RuntimeError(f"Keyboard mismatch: {received!r}")
                    wait_for(
                        (root / "mouse-ready").exists,
                        process,
                        "waiting for mouse fixture",
                    )
                    run(
                        [binaries["wlrctl"], "pointer", "move", "-10000", "-10000"],
                        env=env,
                    )
                    run([binaries["wlrctl"], "pointer", "move", "640", "360"], env=env)
                    run([binaries["wlrctl"], "pointer", "click", "left"], env=env)
                    mouse = root / "mouse.json"
                    wait_for(mouse.exists, process, "waiting for delivered mouse click")
                    report["mouse_event"] = json.loads(mouse.read_text())
                    if report["mouse_event"]["button"] != 0:
                        raise RuntimeError("Expected a left mouse click")
                    time.sleep(0.3)
                    run([binaries["grim"], str(after)], env=env)
                    report["screenshots"] = {
                        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in (before, after)
                    }
                    if before.read_bytes() == after.read_bytes():
                        raise RuntimeError("Screenshot did not change")
                    report["passed"] = True
                finally:
                    try:
                        run([binaries["labwc"], "-e"], env=env, timeout=5)
                        process.wait(timeout=5)
                    except (subprocess.SubprocessError, OSError):
                        pass
                    # Includes app children which create their own process groups.
                    stop_owned(token)
                    process.wait(timeout=5)
            report["compositor_stopped"] = process.poll() is not None
            report["owned_processes_remaining"] = owned_processes(token)
        report["temporary_session_removed"] = not root.exists()
    except Exception as error:
        report["passed"] = False
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        report["host_after"] = host_state()
        report["host_state_equal"] = report["host_before"] == report["host_after"]
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"artifacts": str(output), **report}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
