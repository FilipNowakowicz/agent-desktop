"""F1: a person takes control during a long `open`, `send` or `type` (real session).

The worker serves one request at a time, so `take` used to wait for the step in
progress to finish. Each case measures how long `take` takes to be
acknowledged, checks that nothing of the agent's reaches the page or runs after
that, and that the interrupted step is reported as uncertain, never as done.
"""

import http.server
import re
import shutil
import sys
import threading
import time
import unittest
from pathlib import Path

import test_browser
import test_takeover_jobs
from test_runtime import wait_for

from agent_desktop import core, operations

# Take must be acknowledged within this bound. A long step checks for a take
# every 0.1 s (a typed chunk of 10 characters takes about 0.1 s); the rest is
# the take itself, which starts the takeover VNC server (about 0.1 s here).
# Before the fix, take waited for the whole step: up to a minute.
BOUND = 1.0
SLOW_SECONDS = 6
TYPED = "abcdefghij" * 150  # 1500 characters: about 15 s of typing

TYPE_PAGE = (
    "<title>Type</title><textarea id='box' autofocus></textarea>"
    "<p id='n'>0</p><script>box.oninput = () => n.textContent = box.value.length"
    "</script>"
)


class SlowPage(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.requested.set()
        self.server.release.wait(SLOW_SECONDS)
        body = b"<title>Slow</title><p id='done'>loaded</p>"
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            pass  # the browser closed with the session

    def log_message(self, *arguments):
        pass


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "dbus-daemon", "firefox", "wayvnc")),
    "desktop tools, Firefox or wayvnc unavailable",
)
class TakeoverDuringLongStepTests(unittest.TestCase):
    setUp = test_browser.BrowserTests.setUp
    tearDown = test_browser.BrowserTests.tearDown
    browser = test_browser.BrowserTests.browser

    def take_during(self, name, operation, in_flight, **arguments):
        """Run one request in the background, take control while in_flight()
        holds, and return the acknowledgement time and the request's outcome."""
        outcome = {}

        def run():
            started = time.monotonic()
            try:
                outcome["result"] = core.request(self.session, operation, **arguments)
            except core.DesktopError as error:
                outcome["error"] = error
            outcome["seconds"] = time.monotonic() - started

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        wait_for(in_flight, timeout=30)
        started = time.monotonic()
        taken = core.request(self.session, "take")
        acknowledged = time.monotonic() - started
        outcome["acknowledged_at"] = time.monotonic()
        self.assertEqual(taken["owner"], "human")
        print(f"\n{name}: take acknowledged in {acknowledged:.2f} s", file=sys.stderr)
        thread.join(60)
        self.assertFalse(thread.is_alive())
        self.assertLess(acknowledged, BOUND, outcome)
        return outcome

    def slow_server(self):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), SlowPage)
        server.requested, server.release = threading.Event(), threading.Event()
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(server.release.set)
        return server, f"http://127.0.0.1:{server.server_address[1]}/slow"

    def test_take_during_a_slow_open(self):
        server, url = self.slow_server()
        self.browser("start", url="about:blank")
        outcome = self.take_during(
            "open", "browser", server.requested.is_set, action="open", url=url
        )
        # The navigation was issued: reported as interrupted and uncertain.
        result = outcome["result"]
        self.assertTrue(result["uncertain"], result)
        self.assertIsNone(result["delivered"], result)
        self.assertTrue(result["interrupted"], result)
        self.assertIn("taking control", result["error"])
        server.release.set()
        core.request(self.session, "release")

    def test_a_job_stops_uncertain_at_an_interrupted_open(self):
        server, url = self.slow_server()
        self.page.write_text(test_takeover_jobs.PAGE)
        self.browser("start", url=self.page.as_uri())
        self.assertTrue(self.browser("wait", selector="#add", timeout=20)["satisfied"])
        job = operations.start(
            self.session,
            [
                {"action": "click", "selector": "#add"},
                {"action": "open", "url": url, "new_tab": True},
                {"action": "click", "selector": "#add"},
            ],
            kind="browser",
        )
        ident = job["operation_id"]
        wait_for(server.requested.is_set, timeout=20)
        started = time.monotonic()
        core.request(self.session, "take")
        acknowledged = time.monotonic() - started
        print(
            f"\nopen in a job: take acknowledged in {acknowledged:.2f} s",
            file=sys.stderr,
        )
        self.assertLess(acknowledged, BOUND)
        result = wait_for(
            lambda: (
                r
                if (r := operations.status(self.session, ident))["state"]
                in operations.TERMINAL
                else None
            ),
            timeout=20,
        )
        # Issued but not finished: uncertain, never failed or completed.
        self.assertEqual(result["state"], "delivery_unknown", result)
        self.assertEqual(result["completed"], 1, result)
        self.assertEqual(result["steps"][1]["dispatch_state"], "uncertain")
        self.assertTrue(result["steps"][1]["result"]["interrupted"], result)
        self.assertEqual(result["steps"][2]["dispatch_state"], "pending")
        server.release.set()
        core.request(self.session, "release")
        time.sleep(1)
        # Only the click before the takeover reached the page.
        self.assertEqual(self.browser("text", selector="#count", tab=0)["text"], "1")

    def test_take_during_a_send_to_a_slow_command(self):
        self.page.write_text("<title>Key</title><pre id='key'>planted-value</pre>")
        self.browser("start", url=self.page.as_uri())
        self.assertTrue(self.browser("wait", selector="#key", timeout=20)["satisfied"])
        home = Path(
            core.manifest(self.session)["home"]
            or core.session_path(self.session) / "home"
        )
        script = (
            'cat > "$HOME/got"; touch "$HOME/started"; '
            f'sleep {SLOW_SECONDS}; touch "$HOME/finished"'
        )
        outcome = self.take_during(
            "send to a command",
            "browser",
            (home / "started").exists,
            action="send",
            selector="#key",
            to_command=["sh", "-c", script],
        )
        result = outcome["result"]
        # The value had reached the command, which was stopped.
        self.assertEqual((home / "got").read_text(), "planted-value")
        self.assertTrue(result["uncertain"], result)
        self.assertTrue(result["interrupted"], result)
        self.assertIsNone(result["exit_status"], result)
        self.assertNotIn("planted-value", repr(result))
        time.sleep(SLOW_SECONDS + 1)
        # Nothing the command would have done after the takeover happened.
        self.assertFalse((home / "finished").exists())
        core.request(self.session, "release")

    def test_take_during_long_typing(self):
        self.page.write_text(TYPE_PAGE)
        self.browser("start", url=self.page.as_uri())
        self.assertTrue(self.browser("wait", selector="#box", timeout=20)["satisfied"])
        self.browser("click", selector="#box")
        began = time.monotonic()
        outcome = self.take_during(
            "long type",
            "type",
            lambda: time.monotonic() - began > 2,
            text=TYPED,
        )
        error = outcome.get("error")
        # Some characters were typed, the rest was not sent; never a success.
        self.assertIsInstance(error, core.DeliveryUnknown, outcome)
        typed, total = map(
            int, re.search(r"after (\d+) of (\d+) characters", str(error)).groups()
        )
        self.assertEqual(total, len(TYPED))
        self.assertTrue(0 < typed < total, error)
        core.request(self.session, "release")
        time.sleep(1)
        # The page received exactly what was sent before the acknowledgement.
        received = wait_for(
            lambda: (
                n
                if (n := int(self.browser("text", selector="#n")["text"])) == typed
                else None
            ),
            timeout=5,
        )
        time.sleep(1)
        self.assertEqual(int(self.browser("text", selector="#n")["text"]), received)


if __name__ == "__main__":
    unittest.main()
