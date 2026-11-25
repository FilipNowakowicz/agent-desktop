"""Browser pages that render after load: open and a bare wait settle (real Firefox)."""

import http.server
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from test_runtime import wait_for

from agent_desktop import core
from agent_desktop.browser import Browser
from agent_desktop.worker import (
    HumanControl,
    Worker,
    browser_trace,
    fixed_wait_hint,
    owned_processes,
)

# Like a cloud console: "Loading" at load, then a slow API call, then the content.
CONSOLE = """<!doctype html><meta charset="utf-8"><title>Console</title>
<main id="app">Loading</main><button id="next">Next page</button>
<script>
const show = (path, label) => fetch(path).then((r) => r.text()).then((t) => {
  app.textContent = "Loading.";
  setTimeout(() => { app.textContent = label + ": " + t; }, 200);
});
show("/api/quota", "Quota");
next.onclick = () => { app.textContent = "Loading"; show("/api/keys", "Keys"); };
</script>
"""
# Never still: a clock that changes the DOM every 100 ms.
TICKER = """<!doctype html><title>Ticker</title><p id="t">0</p>
<script>setInterval(() => { t.textContent = Date.now(); }, 100);</script>
"""


# Content that is done, with a spinner a script turns every frame through its
# style, as many sites animate: still content, so open should settle.
SPINNER = """<!doctype html><title>Spinner</title><h1>Ready</h1>
<div id="s" style="width:20px;height:20px;background:#08f"></div>
<script>
let a = 0;
const turn = () => { a = (a + 6) % 360; s.style.transform = `rotate(${a}deg)`;
  requestAnimationFrame(turn); };
turn();
</script>
"""


class Pages(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/"):
            time.sleep(1.5)
            body = b"42" if self.path == "/api/quota" else b"3 active"
            kind = "text/plain"
        else:
            body = {"/console": CONSOLE, "/spinner": SPINNER}.get(self.path, TICKER)
            body = body.encode()
            kind = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


class HintTests(unittest.TestCase):
    def test_a_fixed_pause_after_open_or_click_carries_a_hint(self):
        pause = {"action": "wait", "seconds": 5}
        after_click = fixed_wait_hint([{"action": "click", "text": "Go"}, pause], 1)
        self.assertIn('{"action": "wait"} without seconds', after_click)
        after_open = fixed_wait_hint([{"action": "open", "url": "x"}, pause], 1)
        self.assertIn("open already waited", after_open)
        for steps, index in (
            ([pause], 0),
            ([{"action": "text"}, pause], 1),
            ([{"action": "click"}, {"action": "wait", "text": "Done"}], 1),
            ([{"action": "click"}, {"action": "wait"}], 1),
        ):
            self.assertIsNone(fixed_wait_hint(steps, index), steps)

    def test_a_bare_wait_counts_as_a_condition(self):
        self.assertTrue(browser_trace({"action": "wait"})["condition"])
        self.assertTrue(browser_trace({"action": "wait", "text": "x"})["condition"])
        self.assertFalse(browser_trace({"action": "wait", "seconds": 2})["condition"])


class SettleTakeTests(unittest.TestCase):
    """A person taking control stops a settle wait at once (no Firefox)."""

    def busy_bridge(self):
        # A page that is never still: loaded, but its DOM always just changed.
        bridge = Browser.__new__(Browser)
        bridge.requests, bridge.network_at, bridge.deadline = {}, {}, None
        state = '{"ready": true, "idle_ms": 0}'
        bridge.command = mock.Mock(
            return_value={
                "type": "success",
                "result": {"type": "string", "value": state},
            }
        )
        return bridge

    def test_settle_stops_when_interrupted(self):
        bridge = self.busy_bridge()
        began = time.monotonic()
        result = bridge.settle(
            "context", limit=30, interrupt=lambda: time.monotonic() - began > 0.3
        )
        self.assertLess(time.monotonic() - began, 2)
        self.assertEqual((result["settled"], result["interrupted"]), (False, True))

    def test_a_bare_wait_gives_way_to_a_take(self):
        worker = Worker.__new__(Worker)
        worker.info = {"mode": "headless"}
        bridge = self.busy_bridge()
        bridge.target = mock.Mock(return_value="context")
        worker.browser = (bridge, lambda: None)
        worker.attach_browser = mock.Mock(return_value=True)
        began = time.monotonic()
        worker.take_requested = lambda: time.monotonic() - began > 0.3
        with self.assertRaises(HumanControl):
            worker.browser_request({"action": "wait", "timeout": 30})
        self.assertLess(time.monotonic() - began, 2)


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "dbus-daemon", "firefox")),
    "desktop tools or Firefox unavailable",
)
class SettleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-settle-")
        self.root = Path(self.temporary.name)
        self.previous = {
            k: os.environ.get(k) for k in ("AGENT_DESKTOP_STATE_DIR", "XDG_RUNTIME_DIR")
        }
        (self.root / "runtime").mkdir(mode=0o700)
        os.environ["AGENT_DESKTOP_STATE_DIR"] = str(self.root / "state")
        os.environ["XDG_RUNTIME_DIR"] = str(self.root / "runtime")
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Pages)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.session = core.create()["session"]
        self.token = core.manifest(self.session)["token"]

    def tearDown(self):
        core.destroy(self.session)
        wait_for(lambda: not owned_processes(self.token))
        self.server.shutdown()
        self.server.server_close()
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temporary.cleanup()

    def browser(self, action, **arguments):
        return core.request(self.session, "browser", action=action, **arguments)

    def test_open_returns_after_late_content_and_a_bare_wait_follows_a_click(self):
        self.browser("start")
        opened = self.browser("open", url=self.base + "/console")
        self.assertTrue(opened["settled"], opened)
        self.assertGreaterEqual(opened["settle_ms"], 1500, opened)
        # Read straight away: no pause, no text to wait for.
        self.assertIn("Quota: 42", self.browser("text", selector="#app")["text"])

        batch = self.browser(
            "steps",
            steps=[
                {"action": "click", "text": "Next page"},
                {"action": "wait"},
                {"action": "text", "selector": "#app"},
            ],
        )
        self.assertIsNone(batch["stopped"], batch)
        self.assertTrue(batch["results"][1]["satisfied"], batch)
        self.assertEqual(batch["results"][2]["text"], "Keys: 3 active")

        summary = core.activity(self.session)
        self.assertEqual(summary["browser_waits_for_condition"], 1)
        self.assertEqual(summary["browser_waits_fixed"], 0)

    def test_open_without_settling_and_a_fixed_pause_hint(self):
        self.browser("start")
        skipped = self.browser("open", url=self.base + "/console", timeout=0)
        self.assertNotIn("settled", skipped)
        batch = self.browser(
            "steps",
            steps=[
                {"action": "click", "text": "Next page"},
                {"action": "wait", "seconds": 0.2},
            ],
        )
        self.assertIn("without seconds", batch["results"][1]["hint"])

    def test_a_style_animation_does_not_hold_the_page_open(self):
        self.browser("start")
        opened = self.browser("open", url=self.base + "/spinner", timeout=5)
        self.assertTrue(opened["settled"], opened)
        self.assertLess(opened["settle_ms"], 3000, opened)

    def test_a_page_that_never_settles_is_bounded(self):
        self.browser("start")
        began = time.monotonic()
        opened = self.browser("open", url=self.base + "/ticker", timeout=2)
        self.assertFalse(opened["settled"], opened)
        self.assertLess(time.monotonic() - began, 10)
        self.assertEqual(opened["title"], "Ticker")
        batch = self.browser(
            "steps",
            steps=[{"action": "wait", "timeout": 1}, {"action": "text"}],
        )
        self.assertEqual(batch["stopped"]["reason"], "wait not satisfied", batch)
        self.assertFalse(batch["results"][0]["settled"])


if __name__ == "__main__":
    unittest.main()
