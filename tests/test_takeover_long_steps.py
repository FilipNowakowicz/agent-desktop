"""F1: a person takes control during a long `open`, `send`, `type` or
accessibility check (real session).

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
import test_interruptions
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

# Cookies over the pipe buffer (64 KiB), so a command that stops reading leaves
# send writing: 40 cookies of 3000 characters (Firefox keeps up to 4 KiB each).
COOKIES = 40
COOKIE_PAGE = (
    f"<title>Cookies</title><script>for (let i = 0; i < {COOKIES}; i++) "
    "document.cookie = 'c' + i + '=' + 'v'.repeat(3000) + '; path=/';"
    "document.title = 'Cookies set'</script><p id='set'>set</p>"
).encode()

TYPE_PAGE = (
    "<title>Type</title><textarea id='box' autofocus></textarea>"
    "<p id='n'>0</p><script>box.oninput = () => n.textContent = box.value.length"
    "</script>"
)


class SlowPage(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/cookies":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(COOKIE_PAGE)))
            self.end_headers()
            self.wfile.write(COOKIE_PAGE)
            return
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
        self.assertEqual(result["bytes_written"], len("planted-value"), result)
        self.assertIn("whole value (13 bytes)", result["error"])
        self.assertNotIn("planted-value", repr(result))
        time.sleep(SLOW_SECONDS + 1)
        # Nothing the command would have done after the takeover happened.
        self.assertFalse((home / "finished").exists())
        core.request(self.session, "release")

    def test_take_while_send_writes_a_value_over_the_pipe_buffer(self):
        # The command reads 1000 bytes, then stops reading but keeps its
        # stdin open: send is left writing the rest when the person takes
        # control, and the reply must say how much of the value was written.
        server, _ = self.slow_server()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        self.browser("start", url=f"{base}/cookies")
        self.assertTrue(self.browser("wait", selector="#set", timeout=20)["satisfied"])
        home = Path(
            core.manifest(self.session)["home"]
            or core.session_path(self.session) / "home"
        )
        script = (
            'head -c 1000 > "$HOME/got"; touch "$HOME/started"; '
            f'sleep {SLOW_SECONDS}; touch "$HOME/finished"'
        )
        outcome = self.take_during(
            "send over the pipe buffer",
            "browser",
            (home / "started").exists,
            action="send",
            source="cookies",
            site="127.0.0.1",
            to_command=["sh", "-c", script],
        )
        result = outcome["result"]
        self.assertEqual(result["cookies"], COOKIES, result)
        total, written = result["bytes"], result["bytes_written"]
        print(f"send stopped after {written} of {total} bytes", file=sys.stderr)
        self.assertGreater(total, 64 * 1024, result)
        # At least what the command read, at most what fits behind it in the
        # pipe: never the whole value, never nothing.
        self.assertGreaterEqual(written, 1000, result)
        self.assertLess(written, total, result)
        self.assertEqual((home / "got").stat().st_size, 1000)
        self.assertTrue(result["uncertain"], result)
        self.assertTrue(result["interrupted"], result)
        self.assertIsNone(result["exit_status"], result)
        self.assertIn(f"after {written} of {total} bytes", result["error"])
        # The command ran: it is never reported as not run.
        self.assertIn("may have partly run", result["error"])
        self.assertNotIn("v" * 100, repr(result))
        time.sleep(SLOW_SECONDS + 1)
        self.assertFalse((home / "finished").exists())
        core.request(self.session, "release")

    def test_take_during_a_jobs_accessibility_check(self):
        # Every read of the crowded page lasts until its node limit or 3 s
        # budget; a take sent during one must not wait for it.
        if not core.request(self.session, "status").get("accessibility"):
            self.skipTest("accessibility unavailable")
        self.page.write_text(test_interruptions.CROWDED_PAGE)
        self.browser("start", url=self.page.as_uri())
        self.assertTrue(
            self.browser("wait", selector="#late-add", timeout=30)["satisfied"]
        )
        predicates = [{"kind": "ui", "query": {"element": "Row"}, "claim": "absent"}]
        predicates += [{"kind": "ui", "query": {"element": "Add"}} for _ in range(9)]
        job = operations.start(
            self.session,
            [{"action": "click", "selector": "#add"}],
            kind="browser",
            predicates=predicates,
        )
        ident = job["operation_id"]
        # The first check's read is under way.
        wait_for(
            lambda: (
                (r := operations.status(self.session, ident))["state"] == "running"
                and r["completed"] == 1
                and not r["checks"]
            ),
            timeout=20,
        )
        time.sleep(0.3)
        started = time.monotonic()
        self.assertEqual(core.request(self.session, "take")["owner"], "human")
        acknowledged = time.monotonic() - started
        print(
            f"\naccessibility check: take acknowledged in {acknowledged:.2f} s",
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
            timeout=30,
        )
        # The click had reached the page: completed, never cancelled. The
        # interrupted read is unknown; its partial tree (full of "Row" buttons)
        # never refutes the absence claim.
        self.assertEqual(result["state"], "completed", result)
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["steps"][0]["dispatch_state"], "acknowledged")
        self.assertEqual(result["verification"], "unknown")
        self.assertEqual(len(result["checks"]), len(predicates))
        first = result["checks"][0]
        self.assertEqual(first["status"], "unknown", first)
        self.assertEqual(first["reason"], "human_control: observation interrupted")
        self.assertNotIn("violated", [c["status"] for c in result["checks"]])
        core.request(self.session, "release")
        time.sleep(1)
        self.assertEqual(self.browser("text", selector="#count")["text"], "1")

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
