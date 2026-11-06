"""Stock vs repaired wlroots: does a plain xterm map under CPU load?

Sessions run one at a time under N busy CPU processes, alternating between
the two runtimes in randomised pairs (fixed seed) so drift in machine load
hits both arms equally. A session fails if no window titled TITLE appears in
the session's window list within TIMEOUT seconds of launching xterm. Each
session records which wlroots library its compositor actually mapped.

    uv run scripts/wlroots_ab.py --stock RT --patched RT --pairs N --out FILE
"""

import argparse
import json
import multiprocessing
import os
import random
import time
from pathlib import Path

os.environ.setdefault("AGENT_DESKTOP_EFFECTS", "0")
from agent_desktop import core  # noqa: E402

TITLE = "X11 fixture"
TIMEOUT = 20.0


def busy(stop):
    while not stop.is_set():
        pass


def labwc_pids():
    out = {}
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():
            continue
        try:
            if Path(p, "comm").read_text().strip() == "labwc":
                out[int(p.name)] = Path(p, "maps").read_text()
        except OSError:
            pass
    return out


def wlroots_of(maps):
    libs = {l.split()[-1] for l in maps.splitlines() if "libwlroots" in l}
    return sorted(libs)


def one(runtime, base_path):
    os.environ["PATH"] = f"{runtime}/bin:{base_path}"
    before = set(labwc_pids())
    session = core.create()["session"]
    row = {"session": session}
    try:
        new = {p: m for p, m in labwc_pids().items() if p not in before}
        row["wlroots"] = sorted({x for m in new.values() for x in wlroots_of(m)})
        core.request(
            session, "launch",
            argv=["xterm", "-u8", "-title", TITLE, "-e", "sleep", "60"],
        )
        start = time.monotonic()
        mapped = None
        while time.monotonic() - start < TIMEOUT:
            if any(w["title"] == TITLE
                   for w in core.request(session, "windows")["windows"]):
                mapped = time.monotonic() - start
                break
            time.sleep(0.05)
        row["ok"] = mapped is not None
        row["map_seconds"] = None if mapped is None else round(mapped, 3)
    except Exception as error:  # session machinery failed: not a map failure
        row["ok"] = None
        row["error"] = f"{type(error).__name__}: {error}"[:300]
    finally:
        try:
            core.destroy(session)
        except Exception as error:
            row["destroy_error"] = str(error)[:200]
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stock", required=True)
    ap.add_argument("--patched", required=True)
    ap.add_argument("--pairs", type=int, required=True)
    ap.add_argument("--load", type=int, default=4)
    ap.add_argument("--seed", type=int, default=20261106)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    arms = {"stock": args.stock, "patched": args.patched}
    base_path = os.environ["PATH"]
    rng = random.Random(args.seed)
    stop = multiprocessing.Event()
    load = [multiprocessing.Process(target=busy, args=(stop,)) for _ in range(args.load)]
    for p in load:
        p.start()
    try:
        with args.out.open("a") as fh:
            for i in range(args.pairs):
                order = ["stock", "patched"]
                rng.shuffle(order)
                for arm in order:
                    row = one(arms[arm], base_path)
                    row.update(arm=arm, pair=i, t=time.time(),
                               loadavg=os.getloadavg()[0])
                    fh.write(json.dumps(row) + "\n")
                    fh.flush()
    finally:
        stop.set()
        for p in load:
            p.join()


if __name__ == "__main__":
    main()
