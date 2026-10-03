"""Terminal fixture that records received mouse presses, drags and releases."""

import json
import re
import sys
import tty
from pathlib import Path

root = Path(sys.argv[1])
fd = sys.stdin.fileno()
tty.setraw(fd)
# Button-event tracking (1002) reports motion while a button is held; 1006 is SGR.
print("\033[?1002h\033[?1006hPOINTER FIXTURE", end="", flush=True)
(root / "ready").touch()
pattern = re.compile(r"\x1b\[<(\d+);(\d+);(\d+)([Mm])")
received = ""
with (root / "events.jsonl").open("a") as log:
    while True:
        received += sys.stdin.read(1)
        match = pattern.search(received)
        if not match:
            continue
        received = received[match.end() :]
        code, column, row = map(int, match.groups()[:3])
        event = {
            "button": code & 3,
            "motion": bool(code & 32),
            "wheel": bool(code & 64),
            "column": column,
            "row": row,
            "pressed": match.group(4) == "M",
        }
        log.write(json.dumps(event) + "\n")
        log.flush()
