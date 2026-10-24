"""Bounded reproductions for the 2026-10-15 correctness review.

Run with uv run python docs/research/completion_probes.py. No desktop, account,
model, or network access. Mocks supply boundary responses, not claimed GUI
behaviour. Results describe current behaviour; they are not passing regression
tests for the proposed fixes. Temporary files and one short-lived child process
are used. The child exits itself and is explicitly waited for by its marker.
"""

import json
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent_desktop import core, effects, mcp_server, script
from agent_desktop.browser import Browser


def main():
    results = {}
    node = {
        "id": "example",
        "name": "Save",
        "role": "button",
        "states": [],
        "depth": 1,
    }
    tree = {"nodes": [node], "truncated": True, "unreadable": 1}
    with patch.object(core, "request", return_value=tree):
        results["incomplete_unique_target"] = core.resolve_element(
            "fake", None, element="Save"
        )
    with patch.object(script, "request", return_value=tree):
        results["script_drops_coverage"] = script.one("Save")
    results["unreadable_rendering"] = core.render_tree(
        {"nodes": [], "truncated": False, "unreadable": 1}
    )

    browser = object.__new__(Browser)
    browser.context = "closed-target"
    browser.command = lambda *_args, **_kwargs: {
        "contexts": [{"context": "unrelated-tab"}]
    }
    results["closed_browser_target"] = browser.target()

    socket = MagicMock()
    connection = socket.return_value.__enter__.return_value
    stream = connection.makefile.return_value.__enter__.return_value
    stream.readline.return_value = b'{"ok":true,"result":{}}\n'
    with (
        patch.object(core, "manifest", return_value={"control_socket": "fake"}),
        patch.object(core.socket, "socket", socket),
    ):
        core.request("fake", "browser", action="wait", selector="x", timeout=60)
    results["browser_60s_wait_transport_timeout"] = (
        connection.settimeout.call_args.args[0]
    )

    with patch.object(
        mcp_server, "call", side_effect=core.DesktopError("capture failed")
    ):
        try:
            mcp_server.looked("fake", {"delivered": True}, True)
        except core.DesktopError as error:
            results["delivery_result_lost_on_capture_error"] = str(error)

    with tempfile.TemporaryDirectory(prefix="completion-review-") as directory:
        root = Path(directory)
        document = root / "repeated.ods"
        with zipfile.ZipFile(document, "w") as archive:
            archive.writestr(
                "content.xml",
                (
                    "<office:document-content "
                    f'xmlns:office="{effects.ODF["office"]}" '
                    f'xmlns:table="{effects.ODF["table"]}" '
                    f'xmlns:text="{effects.ODF["text"]}">'
                    '<office:body><office:spreadsheet><table:table table:name="S">'
                    '<table:table-row table:number-rows-repeated="1001">'
                    "<table:table-cell><text:p>x</text:p></table:table-cell>"
                    "</table:table-row></table:table></office:spreadsheet>"
                    "</office:body></office:document-content>"
                ),
            )
        lines = effects.odf_lines(document).splitlines()
        results["odf_silent_partial_read"] = {
            "expected_rows": 1001,
            "returned_rows": len(lines),
            "last": lines[-1],
        }

        # Exercise version accounting without a real watcher thread or timing race.
        recorder = object.__new__(effects.FileRecorder)
        recorder.root = root
        recorder.label = "~"
        recorder.versions = {}
        recorder.text_bytes = 0
        recorder.state_lock = threading.RLock()
        path = root / "existing.txt"
        path.write_text("old")
        recorder.record("existing.txt", 0)
        start = time.monotonic()
        path.write_text("new")
        events = [(start, "modified", "existing.txt")]
        reports = [recorder.summarize(events, start)[0][0] for _ in range(8)]
        results["effect_baseline_eviction"] = {
            "first": reports[0],
            "eighth": reports[-1],
        }
        recorder.libc = MagicMock()
        recorder.libc.inotify_add_watch.return_value = -1
        recorder.fd = -1
        recorder.watches = {}
        results["failed_watch_registration"] = {
            "return": recorder.add_watch(root),
            "watches": recorder.watches,
        }

        marker = root / "child-finished"
        child_code = (
            "import time; from pathlib import Path; time.sleep(2); "
            f"Path({str(marker)!r}).write_text('finished')"
        )
        code = (
            "import subprocess, sys, time\n"
            f"subprocess.Popen([sys.executable, '-c', {child_code!r}], "
            "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
            "time.sleep(10)\n"
        )
        with patch.object(core, "manifest", return_value={"mode": "headless"}):
            result = mcp_server.desktop_run("fake", code, timeout=1)
        at_return = marker.exists()
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        results["script_child_after_timeout"] = {
            "timed_out": result.get("timed_out", False),
            "marker_at_return": at_return,
            "marker_after_return": marker.exists(),
        }
        # Marker is the child's last operation; give interpreter shutdown a beat.
        time.sleep(0.1)

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
