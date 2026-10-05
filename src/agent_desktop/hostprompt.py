"""Show a host-session request as a notification and record the answer.

Runs detached from the requesting client, so a tool call never has to block
for the whole time the person takes to decide.
"""

import json
import subprocess
import sys
import time
from pathlib import Path


def main():
    path = Path(sys.argv[1])
    request = json.loads(path.read_text())
    remaining = max(1, int(request["expires"] - time.time()))
    try:
        chosen = subprocess.run(
            [
                "notify-send",
                "--app-name=Agent Desktop",
                "--urgency=critical",
                f"--expire-time={remaining * 1000}",
                "--action=default=Allow",
                "--action=deny=Decline",
                "Allow an agent to use your screen?",
                f"{request['reason']}\n{request['minutes']:g} min. Click to allow; "
                "dismiss to decline. Terminal: agent-desktop host approve",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=remaining + 5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return
    try:
        current = json.loads(path.read_text())
    except (OSError, ValueError):
        return
    # A terminal answer, or a newer request, takes precedence.
    if current.get("id") != request["id"] or current.get("answer"):
        return
    current["answer"] = "approved" if chosen == "default" else "declined"
    path.write_text(json.dumps(current))


if __name__ == "__main__":
    main()
