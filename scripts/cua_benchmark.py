"""Run selected browser fixtures on fresh, GUI-only local Cua sandboxes.

Requires a reachable Docker-compatible engine and a separately installed Cua CLI.
No runtime installation or host configuration is performed by this script.
"""

import argparse
import base64
import json
import os
import random
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.tasks import CanvasCodeDrag, Confirm, Form  # noqa: E402
from scripts.benchmark import run_agent  # noqa: E402

TASKS = [CanvasCodeDrag(), Form(), Confirm()]
IMAGE = "ghcr.io/trycua/linux@sha256:ac5c9fd4aba25d5f1245a206191cfa6fc6ca7fceda60fcec1b7ec9d816223107"


def command(argv, timeout=180):
    return subprocess.run(
        argv, check=True, capture_output=True, text=True, timeout=timeout
    ).stdout


class Context:
    def __init__(self, directory, engine, container):
        self.directory = directory
        self.engine = engine
        self.container = container

    def windows(self):
        clients = command(
            [self.engine, "exec", self.container, "xprop", "-root", "_NET_CLIENT_LIST"]
        )
        windows = []
        for identifier in re.findall(r"0x[0-9a-f]+", clients):
            title = command(
                [
                    self.engine,
                    "exec",
                    self.container,
                    "xprop",
                    "-id",
                    identifier,
                    "_NET_WM_NAME",
                ]
            )
            # Check the fixture's exact success title from X, independently of MCP caches.
            if "= " in title:
                windows.append(
                    {
                        "id": identifier,
                        "title": title.split("= ", 1)[1].strip().strip('"'),
                    }
                )
        return windows


def run_task(task, root, args):
    directory = (root / task.name).resolve()
    directory.mkdir()
    name = "benchmark-" + uuid.uuid4().hex[:12]
    ref = "local:" + name
    record = {"task": task.name, "passed": False, "sandbox": ref}
    created = None
    cua = [args.cua, "--embedded", "--state-dir", str(args.state_dir), "--json"]
    try:
        started = time.monotonic()
        created = json.loads(
            command(
                cua
                + [
                    "sandbox",
                    "create",
                    IMAGE,
                    "--on",
                    "local",
                    "--runtime",
                    "runc",
                    "--name",
                    name,
                    "--cpu",
                    "2",
                    "--memory",
                    "2GB",
                    "--wait",
                    "desktop",
                    "--ready-timeout",
                    "180",
                ],
                timeout=240,
            )
        )
        container = created["provider_details"]["container_id"]
        record["environment"] = created
        record["startup_seconds"] = round(time.monotonic() - started, 1)
        context = Context(directory, args.engine, container)
        argv, goal = task.setup(context)
        command([args.engine, "cp", str(directory), container + ":/tmp/benchmark"])
        argv = [
            arg.replace(str(directory), "/tmp/benchmark").replace(
                "--ozone-platform=wayland", "--ozone-platform=x11"
            )
            for arg in argv
        ]
        # The guest runs as root in a rootless host container; Chromium requires this.
        argv.insert(1, "--no-sandbox")
        command([args.engine, "exec", "-d", container, *argv])
        deadline = time.monotonic() + 30
        while not any(w["title"].startswith("Task") for w in context.windows()):
            if time.monotonic() >= deadline:
                raise RuntimeError("Browser window did not appear")
            time.sleep(0.2)
        time.sleep(1)  # Same initial-frame fixture delay as the native harness.
        record["chromium_version"] = command(
            [args.engine, "exec", container, "chromium", "--version"]
        ).strip()
        config = directory / "mcp.json"
        config.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "cua-gui": {
                            "command": "uv",
                            "args": [
                                "run",
                                str(Path(__file__).with_name("cua_gui_mcp.py")),
                                "--cua",
                                args.cua,
                                "--state-dir",
                                str(args.state_dir),
                                "--sandbox",
                                ref,
                            ],
                        }
                    }
                },
                indent=2,
            )
        )
        if not args.dry_run:
            prompt = f"""You control a private Linux desktop through the cua-gui tools.
Use its configured sandbox {ref}; it already exists and the application is already open.
Do not create or destroy sessions.

Task: {goal}

Work by taking screenshots and using input tools. When finished, reply with one
line starting with DONE, or FAILED with a short reason."""
            record.update(
                run_agent(
                    prompt,
                    directory,
                    args.budget,
                    args.model,
                    mcp_config=str(config),
                    server="cua-gui",
                    disallowed=[],
                )
            )
        time.sleep(0.5)
        record["passed"], record["detail"] = task.check(context)
        # Use the sandbox's scoped screenshot endpoint, without changing the selected target.
        import asyncio

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async def screenshot():
            entry = json.loads(config.read_text())["mcpServers"]["cua-gui"]
            params = StdioServerParameters(
                command=entry["command"], args=entry["args"], env=os.environ.copy()
            )
            async with (
                stdio_client(params) as (read, write),
                ClientSession(read, write) as client,
            ):
                await client.initialize()
                result = await client.call_tool("computer_screenshot", {})
                if result.isError:
                    raise RuntimeError("Screenshot failed")
                for block in result.content:
                    if block.type == "image":
                        path = directory / "final.png"
                        path.write_bytes(base64.b64decode(block.data))
                        return str(path)
                raise RuntimeError("Screenshot returned no image")

        record["final_screenshot"] = asyncio.run(screenshot())
    except Exception as error:
        record["error"] = f"{type(error).__name__}: {error}"
    finally:
        if created is not None:
            try:
                command(cua + ["sandbox", "delete", ref, "--force"])
                remaining = command(
                    [args.engine, "ps", "-aq", "--filter", "id=" + container]
                ).strip()
                record["leftover_container"] = remaining
                if remaining:
                    record["cleanup_error"] = "Owned container remains after deletion"
            except Exception as error:
                record["cleanup_error"] = str(error)
        (directory / "record.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cua", required=True)
    parser.add_argument(
        "--engine",
        default="podman",
        help="CLI connected to the same engine as DOCKER_HOST",
    )
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--only", nargs="*", choices=[t.name for t in TASKS])
    parser.add_argument("--seed", type=int)
    parser.add_argument("--budget", type=float, default=1.0)
    parser.add_argument("--model")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    args.cua = str(Path(args.cua).resolve())
    args.state_dir = args.state_dir.resolve()
    if not os.environ.get("DOCKER_HOST", "").startswith("unix://"):
        parser.error("Set DOCKER_HOST to the intended local Unix engine socket")
    os.environ["DO_NOT_TRACK"] = "1"
    random.seed(args.seed)
    root = Path("artifacts/cua-benchmark") / (
        time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    )
    root.mkdir(parents=True, mode=0o700)
    records = []
    for task in TASKS:
        if args.only and task.name not in args.only:
            continue
        record = run_task(task, root, args)
        records.append(record)
        print(
            json.dumps(
                {
                    k: record.get(k)
                    for k in (
                        "task",
                        "passed",
                        "error",
                        "tool_calls",
                        "cost_usd",
                        "cleanup_error",
                    )
                }
            ),
            flush=True,
        )
    (root / "summary.json").write_text(
        json.dumps({"seed": args.seed, "image": IMAGE, "records": records}, indent=2)
        + "\n"
    )
    print(root)
    return int(any(r.get("error") or r.get("cleanup_error") for r in records))


if __name__ == "__main__":
    raise SystemExit(main())
