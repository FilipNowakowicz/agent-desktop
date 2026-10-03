"""Operate a disposable Chromium GUI without personal profiles or network tasks."""

import json
import os
import shutil
import time
import uuid
from pathlib import Path

from agent_desktop import core
from agent_desktop.worker import owned_processes


def main():
    browser = shutil.which("chromium")
    if not browser:
        raise RuntimeError("Optional smoke test requires Chromium")
    artifact = Path("artifacts/browser") / uuid.uuid4().hex[:12]
    artifact.mkdir(parents=True, mode=0o700)
    previous = os.environ.get("AGENT_DESKTOP_STATE_DIR")
    os.environ["AGENT_DESKTOP_STATE_DIR"] = str((artifact / "state").resolve())
    session = core.create()["session"]
    info = core.manifest(session)
    page = artifact / "fixture.html"
    page.write_text(
        '<!doctype html><meta charset="utf-8"><title>Private browser fixture - ready</title>'
        '<h1>Private browser fixture</h1><form id="form">'
        '<label>Message <input id="message" autofocus></label><button>Submit</button></form>'
        '<p id="result"></p><script>form.onsubmit=(event)=>{event.preventDefault();'
        'const text=document.getElementById("message").value;'
        'document.getElementById("result").textContent="Received: "+text;'
        'document.title="Private browser fixture - submitted: "+text;};</script>'
    )
    report = {"session": session, "passed": False}
    try:
        app = core.request(
            session,
            "launch",
            argv=[
                browser,
                "--user-data-dir="
                + str(core.session_path(session) / "home/browser-profile"),
                "--no-first-run",
                "--no-default-browser-check",
                "--ozone-platform=wayland",
                "--disable-gpu",
                "--disable-background-networking",
                "--disable-component-update",
                # Disposable profile: avoid a private keyring creation prompt.
                "--password-store=basic",
                page.resolve().as_uri(),
            ],
        )
        report["application"] = app
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if any(
                "Private browser fixture - ready" in w
                for w in core.request(session, "windows")["windows"]
            ):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Browser fixture window did not appear")
        time.sleep(0.5)
        report["before"] = core.request(session, "screenshot")
        core.request(session, "type", text="browser café λ")
        core.request(session, "key", key="Tab")
        core.request(session, "key", key="Return")
        expected = "Private browser fixture - submitted: browser café λ"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            windows = core.request(session, "windows")["windows"]
            if any(expected in w for w in windows):
                report["observed_windows"] = windows
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Browser did not submit the expected text")
        report["after"] = core.request(session, "screenshot")
        # Chromium's helpers show whether ownership covers its whole process tree.
        report["session_processes"] = core.request(session, "status")["processes"]
        assert (
            Path(report["before"]["path"]).read_bytes()
            != Path(report["after"]["path"]).read_bytes()
        )
        report["passed"] = True
    except Exception as error:
        report["error"] = str(error)
    finally:
        report["cleanup"] = core.destroy(session)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and owned_processes(info["token"]):
            time.sleep(0.05)
        report["processes_remaining"] = owned_processes(info["token"])
        if report["processes_remaining"]:
            report["passed"] = False
        (artifact / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        if previous is None:
            os.environ.pop("AGENT_DESKTOP_STATE_DIR", None)
        else:
            os.environ["AGENT_DESKTOP_STATE_DIR"] = previous
    print(json.dumps({"artifacts": str(artifact), **report}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
