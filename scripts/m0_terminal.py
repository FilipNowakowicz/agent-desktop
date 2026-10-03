"""Disposable terminal fixture that reports actual keyboard and mouse delivery."""

import json
import re
import sys
import termios
import time
import tty
from pathlib import Path

root = Path(sys.argv[1])
print("PRIVATE AGENT DESKTOP\nType a message:", flush=True)
(root / "ready").touch()
message = input()
print(f"Received: {message}", flush=True)
(root / "typed.txt").write_text(message)
fd = sys.stdin.fileno()
original = termios.tcgetattr(fd)
try:
    tty.setraw(fd)
    print("\033[?1000h\033[?1006h", end="", flush=True)
    (root / "mouse-ready").touch()
    received = ""
    while True:
        received += sys.stdin.read(1)
        match = re.search(r"\x1b\[<(\d+);(\d+);(\d+)M", received)
        if match:
            event = dict(
                zip(("button", "column", "row"), map(int, match.groups()), strict=True)
            )
            (root / "mouse.json").write_text(json.dumps(event))
            break
finally:
    print("\033[?1000l\033[?1006l", end="", flush=True)
    termios.tcsetattr(fd, termios.TCSADRAIN, original)
print(f"Received mouse click: {event}", flush=True)
time.sleep(60)
