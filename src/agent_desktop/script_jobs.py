"""Bounded script jobs; process-group cleanup is lifecycle hygiene, not isolation."""

import contextvars
import ctypes
import json
import os
import select
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import anyio

CANCELLATION = contextvars.ContextVar("script_cancellation", default=None)
OUTPUT_LIMIT = 8000
JOURNAL_LIMIT = 1024 * 1024
SUPERVISOR_GRACE = 3


def identity(pid):
    """Process identity used only to reconcile the dedicated job supervisor."""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return {
            "state": fields[0],
            "parent": int(fields[1]),
            "group": int(fields[2]),
            "start": int(fields[19]),
        }
    except (OSError, ValueError, IndexError):
        return None


def recover_supervisor(supervisor, root):
    """Bound waiting for a stopped helper, retaining unknown cleanup on failure.

    Stop the supervisor before examining its child: it cannot reap the group
    leader and release its PID while we validate and signal that group.
    """
    try:
        supervisor.send_signal(signal.SIGSTOP)
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            state = identity(supervisor.pid)
            if state is None or state["state"] in ("T", "t", "Z", "X"):
                break
            time.sleep(0.01)
        if state and state["state"] in ("T", "t"):
            try:
                leader = json.loads((root / "leader.json").read_text())
                pid = leader["pid"]
                current = identity(pid) if type(pid) is int and pid > 1 else None
                if (
                    current
                    and current["parent"] == supervisor.pid
                    and current["group"] == pid
                    and current["start"] == leader["start"]
                ):
                    os.killpg(pid, signal.SIGKILL)
            except (OSError, ValueError, KeyError, TypeError):
                pass
        supervisor.send_signal(signal.SIGCONT)
        supervisor.terminate()
        try:
            supervisor.wait(timeout=2)
            return True
        except subprocess.TimeoutExpired:
            supervisor.kill()
            supervisor.wait(timeout=1)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return False


async def cancellable_call(function):
    """Signal a synchronous job on cancellation and wait for its cleanup."""
    cancelled = threading.Event()
    finished = anyio.Event()
    outcome = []

    async def run():
        token = CANCELLATION.set(cancelled)
        try:
            try:
                try:
                    outcome.append((True, await anyio.to_thread.run_sync(function)))
                except Exception as error:
                    outcome.append((False, error))
            finally:
                finished.set()
        finally:
            CANCELLATION.reset(token)

    async with anyio.create_task_group() as group:
        group.start_soon(run)
        try:
            await finished.wait()
        except anyio.get_cancelled_exc_class():
            cancelled.set()
            with anyio.CancelScope(shield=True):
                await finished.wait()
            raise
    succeeded, result = outcome[0]
    if not succeeded:
        raise result
    return result


def operation(operation_name, function):
    """Journal receipt boundaries without arguments, secrets or result payloads."""
    path = os.environ.get("AGENT_DESKTOP_SCRIPT_JOURNAL")
    if not path:
        return function()

    operation_id = uuid.uuid4().hex

    def record(state):
        descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            if os.fstat(descriptor).st_size >= JOURNAL_LIMIT:
                Path(path + ".truncated").touch()
                return
            item = {
                "id": operation_id,
                "operation": operation_name[:100],
                "state": state,
            }
            os.write(descriptor, (json.dumps(item) + "\n").encode())
        finally:
            os.close(descriptor)

    record("started")
    try:
        result = function()
    except BaseException:
        record("unknown")
        raise
    record("returned")
    return result


def run(code, environment, timeout):
    """Run Python under a Linux subreaper that owns only this job's children."""
    started = time.monotonic()
    cancelled = CANCELLATION.get()
    with tempfile.TemporaryDirectory(prefix="desktop-script-") as directory:
        root = Path(directory)
        (root / "code.py").write_text("from agent_desktop.script import *\n" + code)
        environment = {
            **environment,
            "AGENT_DESKTOP_SCRIPT_JOURNAL": str(root / "operations.jsonl"),
        }
        supervisor = subprocess.Popen(
            [sys.executable, "-I", "-m", __name__, str(root)],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        reason = None
        stopping_at = None
        recovered = False
        while supervisor.poll() is None:
            if reason is None:
                if cancelled is not None and cancelled.is_set():
                    reason = "cancelled"
                elif time.monotonic() - started >= timeout:
                    reason = "timed_out"
                if reason:
                    stopping_at = time.monotonic()
                    supervisor.terminate()
            elif time.monotonic() - stopping_at >= SUPERVISOR_GRACE:
                recovered = recover_supervisor(supervisor, root)
                break
            time.sleep(0.02)
        if supervisor.poll() is not None:
            supervisor.wait()
        try:
            status = json.loads((root / "status.json").read_text())
        except (OSError, ValueError):
            status = {"exit_code": None, "cleanup": {"state": "unknown"}}
        result = dict(status)
        if stopping_at is not None and supervisor.poll() is None:
            result["cleanup"] = {
                "state": "unknown",
                "scope": "ordinary script process group",
            }
        if recovered:
            result["supervisor_recovered"] = True
        if reason:
            result[reason] = True
            result["exit_code"] = None
        for name in ("stdout", "stderr"):
            try:
                with (root / name).open("rb") as stream:
                    stream.seek(0, os.SEEK_END)
                    stream.seek(max(0, stream.tell() - OUTPUT_LIMIT * 4))
                    decoded = stream.read().decode(errors="replace")
                    result[name] = decoded[-OUTPUT_LIMIT:]
                    if len(decoded) > OUTPUT_LIMIT:
                        result.setdefault("output_truncated", {})[name] = True
            except OSError:
                result[name] = ""
                result.setdefault("output_truncated", {})[name] = True
        journal = root / "operations.jsonl"
        # Keep the returned summary bounded; preserve failed/unfinished calls
        # independently so a later successful read cannot erase uncertainty.
        returned = 0
        pending = {}
        uncertain = {}
        if journal.exists():
            with journal.open() as stream:
                for line in stream:
                    try:
                        item = json.loads(line)
                    except ValueError:
                        continue
                    if item["state"] == "returned":
                        returned += 1
                        pending.pop(item["id"], None)
                    elif item["state"] == "unknown":
                        pending.pop(item["id"], None)
                        uncertain[item["id"]] = item["operation"]
                    else:
                        pending[item["id"]] = item["operation"]
        journal_truncated = Path(str(journal) + ".truncated").exists()
        result["operations"] = {
            "truncated": journal_truncated,
            "returned": returned,
            "in_flight": list(pending.values())[:20],
            "in_flight_count": len(pending),
            "uncertain": list(uncertain.values())[:20],
            "uncertain_count": len(uncertain),
            "delivery": "unknown"
            if pending or uncertain or journal_truncated
            else "no_pending_helper_call",
            "scope": "script helpers only; returned calls do not prove task completion",
        }
        result["seconds"] = round(time.monotonic() - started, 2)
        return result


def supervise(root):
    """Reap ordinary descendants without adopting unrelated server children."""
    # PR_SET_CHILD_SUBREAPER: grandchildren orphaned by the script are adopted
    # here. Applications started through the session worker are not descendants.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0):
        raise OSError(ctypes.get_errno(), "cannot enable script subreaper")
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    # Gate script execution until its identity has been published for the
    # parent's bounded recovery path. A helper failure before publication
    # leaves a child that exits without executing user code.
    bootstrap = (
        "import sys,time\nfrom pathlib import Path\n"
        "gate,code = map(Path,sys.argv[1:])\nend=time.monotonic()+5\n"
        "while not gate.exists():\n"
        " if time.monotonic()>=end: sys.exit(1)\n time.sleep(.01)\n"
        "exec(compile(code.read_text(),'<desktop_run>','exec'))\n"
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-I",
            "-c",
            bootstrap,
            str(root / "start"),
            str(root / "code.py"),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    leader = identity(process.pid)
    if leader is None:
        raise RuntimeError("Script exited before identity publication")
    (root / "leader.json").write_text(
        json.dumps({"pid": process.pid, "start": leader["start"]})
    )
    (root / "start").touch()
    stop_readers = threading.Event()
    tails = {"stdout": bytearray(), "stderr": bytearray()}
    totals = {"stdout": 0, "stderr": 0}
    output_complete = {"stdout": False, "stderr": False}

    def read_output(name, stream):
        while not stop_readers.is_set():
            readable, _, _ = select.select([stream.fileno()], [], [], 0.05)
            if readable:
                data = os.read(stream.fileno(), 65536)
                if not data:
                    output_complete[name] = True
                    break
                totals[name] += len(data)
                tails[name].extend(data)
                del tails[name][: -OUTPUT_LIMIT * 4]

    readers = [
        threading.Thread(target=read_output, args=(name, stream), daemon=True)
        for name, stream in (("stdout", process.stdout), ("stderr", process.stderr))
    ]
    for reader in readers:
        reader.start()
    try:
        completed = None
        while not stopping:
            completed = os.waitid(
                os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT
            )
            if completed is not None:
                break
            time.sleep(0.02)
        exit_code = (
            completed.si_status
            if completed is not None and completed.si_code == os.CLD_EXITED
            else -completed.si_status
            if completed is not None
            else None
        )
        # Keep the leader unreaped until the signal is sent: its PID cannot be
        # reused as an unrelated process group's ID during cleanup.
        # A script job ends when its parent returns as well as when cancelled.
        # Background work must be launched through the session to outlive it.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        # Retain the unreaped leader through both signals, including when
        # only detached descendants remain; group IDs cannot be reused here.
        time.sleep(0.3)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 1
        remaining = True
        while time.monotonic() < deadline:
            try:
                child, child_status = os.waitpid(-1, os.WNOHANG)
                if child == process.pid:
                    process.returncode = os.waitstatus_to_exitcode(child_status)
            except ChildProcessError:
                remaining = False
                break
            if not child:
                time.sleep(0.01)
        # Detached descendants may escape the group. Do not claim they were
        # stopped, or block indefinitely on children outside this contract.
        (root / "status.json").write_text(
            json.dumps(
                {
                    "exit_code": exit_code,
                    "cleanup": {
                        "state": "complete" if not remaining else "incomplete",
                        "scope": "ordinary script process group",
                        "detached_descendants": "not_guaranteed",
                    },
                }
            )
        )
    finally:
        # Ordinary descendants have closed their pipes. A detached descendant
        # may retain them; stopping the readers never waits for its EOF.
        for reader in readers:
            reader.join(timeout=0.1)
        stop_readers.set()
        for reader in readers:
            reader.join()
        for name in ("stdout", "stderr"):
            (root / name).write_bytes(tails[name])
        process.stdout.close()
        process.stderr.close()
        status_path = root / "status.json"
        if status_path.exists():
            status = json.loads(status_path.read_text())
            status["output_truncated"] = {
                name: totals[name] > len(tails[name]) or not output_complete[name]
                for name in tails
            }
            status_path.write_text(json.dumps(status))


if __name__ == "__main__":
    supervise(Path(sys.argv[1]))
