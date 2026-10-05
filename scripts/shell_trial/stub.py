#!/usr/bin/env python3
"""Logging stand-in for system tools called by desktop-shell widgets.

Installed under each tool's name ahead of the real ones on PATH, so a widget
under test can never change the host (Wi-Fi, Bluetooth, audio, brightness,
power). It records argv to $SHELL_TRIAL_LOG and answers with plausible output
from a small state file, so toggles are reflected back to the widget.
"""

import json
import os
import signal
import socket
import sys
import time
from pathlib import Path

STATE_DEFAULT = {
    "wifi": True,
    "bluetooth": True,
    "volume": 0.45,
    "muted": False,
    "mic_volume": 0.7,
    "mic_muted": False,
    "brightness": 60,
    "modes": ["default"],
    "processes": [],
}


def load(path):
    try:
        return {**STATE_DEFAULT, **json.loads(path.read_text())}
    except (OSError, ValueError):
        return dict(STATE_DEFAULT)


def wpctl_status(state):
    return (
        "PipeWire 'pipewire-0' [1.4.0]\n"
        "Audio\n"
        " ├─ Devices:\n"
        " │      40. Built-in Audio                      [alsa]\n"
        " │\n"
        " ├─ Sinks:\n"
        f" │  *   48. Built-in Audio Analog Stereo        [vol: {state['volume']:.2f}"
        f"{' MUTED' if state['muted'] else ''}]\n"
        " │      52. Headphones                          [vol: 0.30]\n"
        " │\n"
        " ├─ Sources:\n"
        f" │  *   49. Built-in Audio Analog Stereo        [vol: {state['mic_volume']:.2f}"
        f"{' MUTED' if state['mic_muted'] else ''}]\n"
        " │\n"
        " ├─ Filters:\n"
        " │\n"
        " └─ Streams:\n"
    )


def hyprctl(args):
    request = " ".join(a for a in args if a != "-j")
    if "-j" in args:
        request = "j/" + request
    path = (
        Path(os.environ["XDG_RUNTIME_DIR"])
        / "hypr"
        / os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "missing")
        / ".socket.sock"
    )
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(str(path))
        connection.sendall(request.encode())
        connection.shutdown(socket.SHUT_WR)
        reply = b""
        while chunk := connection.recv(65536):
            reply += chunk
    return reply.decode()


def respond(name, args, state):
    """Return (stdout, exit code) and update state for toggles."""
    joined = " ".join(args)
    if name == "hyprctl":
        return hyprctl(args), 0
    if name == "nmcli":
        if joined == "radio wifi":
            return ("enabled" if state["wifi"] else "disabled") + "\n", 0
        if joined.startswith("radio wifi "):
            state["wifi"] = args[-1] == "on"
            return "", 0
        if "dev show" in joined:
            return (
                "GENERAL.DEVICE:wlan0\nGENERAL.TYPE:wifi\nGENERAL.CONNECTION:"
                + ("TrialNet" if state["wifi"] else "--")
                + "\nIP4.ADDRESS[1]:192.168.50.20/24\nIP4.GATEWAY:192.168.50.1\n"
            ), 0
        if "wifi list" in joined:
            if not state["wifi"]:
                return "", 0
            return (
                "yes:TrialNet:78:5180 MHz:WPA2\n"
                "no:Neighbour\\:5G:41:5745 MHz:WPA3\n"
                "no:CoffeeShop:22:2437 MHz:\n"
            ), 0
        return "", 0
    if name == "wpctl":
        if args[:1] == ["status"]:
            return wpctl_status(state), 0
        if args[:1] == ["get-volume"]:
            sink = "SOURCE" not in joined
            volume = state["volume" if sink else "mic_volume"]
            muted = state["muted" if sink else "mic_muted"]
            return f"Volume: {volume:.2f}{' [MUTED]' if muted else ''}\n", 0
        if args[:1] == ["inspect"]:
            return 'node.description = "Built-in Audio Analog Stereo"\n', 0
        if args[:1] == ["set-volume"] and len(args) >= 3:
            key = "mic_volume" if "SOURCE" in args[1] else "volume"
            value = args[2].rstrip("%")
            try:
                number = float(value.rstrip("+-"))
                if args[2].endswith("%"):
                    number /= 100
                state[key] = round(max(0.0, min(1.5, number)), 2)
            except ValueError:
                return "", 1
            return "", 0
        if args[:1] == ["set-mute"] and len(args) >= 3:
            key = "mic_muted" if "SOURCE" in args[1] else "muted"
            state[key] = not state[key] if args[2] == "toggle" else args[2] == "1"
            return "", 0
        return "", 0
    if name == "brightnessctl":
        if args[:1] == ["set"] and len(args) > 1:
            state["brightness"] = int(args[1].rstrip("%"))
            return "", 0
        return (
            f"intel_backlight,backlight,{state['brightness']},{state['brightness']}%,100\n",
            0,
        )
    if name == "bluetoothctl":
        if args[:1] == ["power"] and len(args) > 1:
            state["bluetooth"] = args[1] == "on"
        if args[:1] == ["show"]:
            return f"Powered: {'yes' if state['bluetooth'] else 'no'}\n", 0
        return "", 0
    if name == "makoctl":
        if args[:1] == ["mode"]:
            modes = state["modes"]
            for flag, mode in zip(args[1::2], args[2::2], strict=False):
                if flag == "-a" and mode not in modes:
                    modes.append(mode)
                elif flag == "-r" and mode in modes:
                    modes.remove(mode)
                elif flag == "-t":
                    (modes.remove if mode in modes else modes.append)(mode)
                elif flag == "-s":
                    modes[:] = [mode]
            return "".join(m + "\n" for m in modes), 0
        return "", 0
    if name == "pgrep":
        # Never report host processes (e.g. a real wlsunset) to the widget.
        running = [a for a in args if not a.startswith("-") and a in state["processes"]]
        return ("4242\n", 0) if running else ("", 1)
    if name == "pkill":
        # The real pkill would stop host processes such as the user's wlsunset.
        names = [a for a in args if not a.startswith("-")]
        before = len(state["processes"])
        state["processes"] = [p for p in state["processes"] if p not in names]
        return "", 0 if len(state["processes"]) < before else 1
    if name == "wlsunset":
        state["processes"].append("wlsunset")
        return "", 0
    if name == "powerprofilesctl":
        return "balanced\n", 0
    # systemctl, loginctl, tailscale, mullvad, wlsunset, theme-switch and
    # external tools: recorded only, never executed.
    return "", 0


def main():
    name = Path(sys.argv[0]).name
    args = sys.argv[1:]
    log = Path(os.environ.get("SHELL_TRIAL_LOG", "/dev/null"))
    state_path = Path(
        os.environ.get(
            "SHELL_TRIAL_STATE", Path(os.environ["XDG_RUNTIME_DIR"]) / "stub-state.json"
        )
    )
    state = load(state_path)
    try:
        output, code = respond(name, args, state)
    except OSError as error:
        output, code = "", 1
        print(f"stub {name}: {error}", file=sys.stderr)
    state_path.write_text(json.dumps(state))
    if name == "systemd-inhibit":
        # Hold like a real inhibitor until terminated, without contacting logind.
        with log.open("a") as stream:
            stream.write(
                json.dumps(
                    {
                        "t": time.time(),
                        "source": "stub",
                        "tool": name,
                        "args": args,
                        "exit": None,
                    }
                )
                + "\n"
            )
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT})
        signal.sigwait({signal.SIGTERM, signal.SIGINT})
        return 0
    with log.open("a") as stream:
        stream.write(
            json.dumps(
                {
                    "t": time.time(),
                    "source": "stub",
                    "tool": name,
                    "args": args,
                    "exit": code,
                }
            )
            + "\n"
        )
    sys.stdout.write(output)
    return code


if __name__ == "__main__":
    sys.exit(main())
