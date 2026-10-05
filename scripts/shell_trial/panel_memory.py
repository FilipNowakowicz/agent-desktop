"""Toggle the control panel repeatedly and sample its memory."""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run import command_for  # noqa: E402

from agent_desktop import core  # noqa: E402

TRIAL = Path(sys.argv[1] if len(sys.argv) > 1 else "artifacts/shell-trial").resolve()
ROUNDS = int(os.environ.get("ROUNDS", 6))
PER_ROUND = int(os.environ.get("PER_ROUND", 16))
info = json.loads((TRIAL / "session.json").read_text())
manifest = json.loads((TRIAL / "manifest.json").read_text())
SESSION = info["session"]
# `env` execs the program, so the launched pid is the panel itself.
pid = info["apps"]["control-center"]["pid"]


def rss():
    return round(
        int(Path(f"/proc/{pid}/statm").read_text().split()[1])
        * os.sysconf("SC_PAGE_SIZE")
        / 2**20,
        1,
    )


samples = [{"toggles": 0, "rss_mb": rss()}]
done = 0
for _ in range(ROUNDS):
    for _ in range(PER_ROUND):  # even: the panel ends closed each round
        app = core.request(
            SESSION, "launch", argv=command_for(TRIAL, manifest, "control-center")
        )
        while True:
            entry = next(
                a
                for a in core.request(SESSION, "status")["applications"]
                if a["pid"] == app["pid"]
            )
            if entry["exit_code"] is not None:
                break
            time.sleep(0.05)
        time.sleep(0.25)
        done += 1
    time.sleep(3)
    samples.append({"toggles": done, "rss_mb": rss()})
    print(json.dumps(samples[-1]), flush=True)
(TRIAL / "panel-memory.json").write_text(json.dumps(samples, indent=2) + "\n")
