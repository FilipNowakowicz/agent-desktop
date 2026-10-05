"""Stress a running shell trial: rapid workspace switches and panel toggles.

Measures CPU time and resident memory of the bar and panel before and after,
checks they are still running, and captures the final bar and panel.
"""

import json
import os
import random
import shutil
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from agent_desktop import core  # noqa: E402

TRIAL = Path(sys.argv[1] if len(sys.argv) > 1 else "artifacts/shell-trial").resolve()
SWITCHES = int(os.environ.get("SWITCHES", 500))
TOGGLES = int(os.environ.get("TOGGLES", 30))
info = json.loads((TRIAL / "session.json").read_text())
SESSION = info["session"]
runtime = Path(core.manifest(SESSION)["runtime"])
TICK = os.sysconf("SC_CLK_TCK")


def usage(pid):
    stat = Path(f"/proc/{pid}/stat").read_text()
    fields = stat[stat.rindex(")") + 2 :].split()
    cpu = (int(fields[11]) + int(fields[12])) / TICK
    rss = int(Path(f"/proc/{pid}/statm").read_text().split()[1]) * os.sysconf(
        "SC_PAGE_SIZE"
    )
    return {"cpu_s": round(cpu, 2), "rss_mb": round(rss / 2**20, 1)}


def process(name):
    """`env` execs the program, so the launched pid is the component itself."""
    return info["apps"][name]["pid"]


def dispatch(request):
    path = runtime / "hypr/trial/.socket.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(str(path))
        connection.sendall(request.encode())
        connection.shutdown(socket.SHUT_WR)
        return connection.recv(4096).decode()


pids = {name: process(name) for name in ("waybar", "control-center")}
report = {"before": {n: usage(p) for n, p in pids.items()}}
random.seed(1)
started = time.monotonic()
last = 1
for _ in range(SWITCHES):
    last = random.randint(1, 5)
    dispatch(f"dispatch workspace {last}")
report["switches"] = {
    "count": SWITCHES,
    "seconds": round(time.monotonic() - started, 2),
    "final": last,
}
time.sleep(2)
report["after_switches"] = {n: usage(p) for n, p in pids.items()}
manifest = json.loads((TRIAL / "manifest.json").read_text())
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run import command_for  # noqa: E402

started = time.monotonic()
for _ in range(TOGGLES):
    app = core.request(
        SESSION, "launch", argv=command_for(TRIAL, manifest, "control-center")
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = next(
            a
            for a in core.request(SESSION, "status")["applications"]
            if a["pid"] == app["pid"]
        )
        if state["exit_code"] is not None:
            break
        time.sleep(0.05)
report["toggles"] = {"count": TOGGLES, "seconds": round(time.monotonic() - started, 2)}
time.sleep(2)
report["after_toggles"] = {n: usage(p) for n, p in pids.items()}
report["alive"] = {n: Path(f"/proc/{p}").exists() for n, p in pids.items()}
capture = core.request(SESSION, "screenshot")
shutil.copy(capture["path"], TRIAL / "stress-final.png")
report["final_screenshot"] = str(TRIAL / "stress-final.png")
(TRIAL / "stress.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
