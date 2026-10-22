"""Browser bridge: a private Firefox driven through WebDriver BiDi (real browser)."""

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from test_runtime import wait_for

from agent_desktop import core, mcp_server
from agent_desktop.worker import owned_processes

PAGE = """<!doctype html><meta charset="utf-8"><title>Bridge form</title>
<h1>Order</h1>
<p><label>Full name <input id="fullname"></label></p>
<p><label>Secret <input id="secret" type="password"></label></p>
<p><label>Size <select id="size"><option>S</option><option>M</option>
<option>L</option></select></label></p>
<p><label><input id="terms" type="checkbox"> Accept terms</label></p>
<p><button id="save">Save</button> <button disabled>Delete</button>
<button>Save draft</button></p>
<p id="out"></p>
<script>
save.onclick = () => {
  out.textContent = [fullname.value, size.value, terms.checked, secret.value.length].join("|");
  document.title = "Saved";
};
</script>
"""


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "dbus-daemon", "firefox")),
    "desktop tools or Firefox unavailable",
)
class BrowserTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-browser-")
        self.root = Path(self.temporary.name)
        self.previous = {
            k: os.environ.get(k) for k in ("AGENT_DESKTOP_STATE_DIR", "XDG_RUNTIME_DIR")
        }
        (self.root / "runtime").mkdir(mode=0o700)
        os.environ["AGENT_DESKTOP_STATE_DIR"] = str(self.root / "state")
        os.environ["XDG_RUNTIME_DIR"] = str(self.root / "runtime")
        self.session = core.create()["session"]
        self.token = core.manifest(self.session)["token"]
        self.page = self.root / "form.html"
        self.page.write_text(PAGE)

    def tearDown(self):
        core.destroy(self.session)
        wait_for(lambda: not owned_processes(self.token))
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temporary.cleanup()

    def browser(self, action, **arguments):
        return core.request(self.session, "browser", action=action, **arguments)

    def test_delayed_wait_exceeds_old_socket_timeout(self):
        self.page.write_text(
            '<title>Delayed</title><p id="out">pending</p>'
            '<script>setTimeout(() => {out.textContent = "ready"}, 31000)</script>'
        )
        self.browser("start", url=self.page.as_uri())
        result = self.browser("wait", text="ready", exact=True, timeout=60)
        self.assertTrue(result["satisfied"], result)

    def test_input_receipt_survives_optional_capture_failure(self):
        self.browser("start", url=self.page.as_uri())
        delivered = self.browser("fill", selector="#fullname", value="received once")
        with mock.patch.object(
            mcp_server, "call", side_effect=core.DesktopError("capture failed")
        ):
            result = mcp_server.looked(self.session, delivered, True)
        self.assertTrue(result["delivered"])
        self.assertEqual(result["observation_error"], "capture failed")
        self.assertEqual(
            self.browser("find", selector="#fullname")["items"][0]["value"],
            "received once",
        )

    def test_fill_and_submit_a_form_without_coordinates(self):
        with self.assertRaisesRegex(core.DesktopError, "start"):
            self.browser("tabs")
        started = self.browser("start", url=self.page.as_uri())
        self.assertEqual(len(started["tabs"]), 1)
        self.assertTrue(
            self.browser("wait", selector="#fullname", timeout=20)["satisfied"]
        )
        filled = self.browser("fill", text="Full name", value="Grace Hopper ✓")
        self.assertEqual(filled["now"]["value"], "Grace Hopper ✓")
        secret = self.browser("fill", selector="#secret", value="hunter2")
        self.assertNotIn("value", secret["now"])
        self.assertNotIn("value", secret["element"])
        self.browser("select", selector="#size", value="L")
        self.assertTrue(self.browser("click", selector="#terms")["now"]["checked"])
        # Ambiguous and disabled targets are refused; nothing is clicked.
        with self.assertRaisesRegex(core.DesktopError, "2 elements match"):
            self.browser("click", text="Save")
        with self.assertRaisesRegex(core.DesktopError, "disabled"):
            self.browser("click", text="Delete", exact=True)
        clicked = self.browser("click", text="Save", exact=True)
        self.assertTrue(clicked["delivered"])
        saved = self.browser("wait", text="Grace Hopper ✓|L|true|7", timeout=10)
        self.assertTrue(saved["satisfied"], saved)
        text = self.browser("text")
        self.assertIn("Grace Hopper ✓|L|true|7", text["text"])
        self.assertEqual(text["title"], "Saved")
        found = self.browser("find", selector="select")
        self.assertEqual(found["items"][0]["options"], ["S", "M", "L"])
        opened = self.browser("open", url="about:blank", new_tab=True)
        self.assertEqual(opened["url"], "about:blank")
        self.assertEqual(len(self.browser("tabs")["tabs"]), 2)

    def test_start_as_a_named_controller(self):
        # MCP clients name a controller; the request takes the lease, and the
        # Firefox launch inside start (and inside steps) must run as its holder.
        started = core.request(
            self.session,
            "browser",
            "mcp-test",
            action="steps",
            steps=[
                {"action": "start", "url": self.page.as_uri()},
                {"action": "wait", "selector": "#fullname", "timeout": 20},
                {"action": "fill", "text": "Full name", "value": "Ada"},
            ],
        )
        self.assertIsNone(started["stopped"], started)
        self.assertEqual(started["results"][2]["now"]["value"], "Ada")
        self.assertEqual(
            core.request(self.session, "control")["lease"]["holder"], "mcp-test"
        )
        with self.assertRaisesRegex(core.DesktopError, "LeaseHeld"):
            self.browser("fill", text="Full name", value="Grace")

    def test_closed_target_requires_explicit_rebinding(self):
        started = self.browser("start", url=self.page.as_uri())
        first = started["tabs"][0]["context"]
        self.browser("wait", selector="#fullname", timeout=20)
        second = self.browser("open", url=self.page.as_uri(), new_tab=True)["context"]
        self.assertNotEqual(first, second)
        self.browser("close", context=second)
        self.assertEqual(self.browser("tabs")["tabs"][0]["context"], first)
        for selection in ({}, {"context": second}):
            with self.assertRaisesRegex(core.DesktopError, "target_lost"):
                self.browser("fill", selector="#fullname", value="wrong", **selection)
        # Explicit selection recovers; no rejected action reached the other tab.
        self.assertEqual(
            self.browser("find", selector="#fullname", context=first)["items"][0][
                "value"
            ],
            "",
        )
        self.assertEqual(
            self.browser("fill", selector="#fullname", value="Ada")["now"]["value"],
            "Ada",
        )
        self.browser("open", url="about:blank", new_tab=True)
        self.browser("close")
        # Creating a new tab is explicit and needs no surviving prior target.
        self.assertEqual(
            self.browser("open", url="about:blank", new_tab=True)["url"], "about:blank"
        )

    def test_tab_closed_outside_the_bridge_does_not_retarget(self):
        first = self.browser("start", url=self.page.as_uri())["tabs"][0]["context"]
        self.browser("wait", selector="#fullname", timeout=20)
        second = self.browser("open", url=self.page.as_uri(), new_tab=True)["context"]
        # Close the foreground tab via actual input to this private desktop,
        # independently of the bridge's own close action.
        core.request(self.session, "screenshot")
        core.request(self.session, "key", key="w", modifiers=["ctrl"])
        wait_for(
            lambda: all(t["context"] != second for t in self.browser("tabs")["tabs"])
        )
        with self.assertRaisesRegex(core.DesktopError, "target_lost"):
            self.browser("fill", selector="#fullname", value="wrong")
        self.assertEqual(
            self.browser("find", selector="#fullname", context=first)["items"][0][
                "value"
            ],
            "",
        )

    def test_attaches_to_a_firefox_started_with_the_port(self):
        launched = core.request(
            self.session,
            "launch",
            argv=["firefox", "--remote-debugging-port=0", self.page.as_uri()],
        )
        wait_for(
            lambda: "WebDriver BiDi listening" in Path(launched["logs"]).read_text(),
            timeout=30,
        )
        # Any action attaches; "start" is not needed for it.
        tabs = self.browser("tabs")
        self.assertEqual(tabs["tabs"][0]["url"], self.page.as_uri())
        started = self.browser("start")
        self.assertEqual(started["tabs"][0]["url"], self.page.as_uri())
        self.assertEqual(len(core.request(self.session, "status")["applications"]), 1)

    def test_steps_and_targets_within_a_row(self):
        rows = "".join(
            f"<tr><td>{n}</td><td><button onclick=\"document.title='{n}'\">Edit"
            "</button></td></tr>"
            for n in ("alice", "mallory", "bob")
        )
        table = self.root / "table.html"
        table.write_text(
            '<!doctype html><meta charset="utf-8"><title>Users</title>'
            '<p><input id="u"> <button onclick="document.body.dataset.in=u.value;'
            "document.title='Signed in'\">Sign in</button></p>"
            f"<table>{rows}</table>"
        )
        self.browser("start", url=table.as_uri())
        result = self.browser(
            "steps",
            steps=[
                {"action": "wait", "selector": "#u", "timeout": 20},
                {"action": "fill", "selector": "#u", "value": "admin"},
                {"action": "click", "text": "Sign in"},
                {"action": "click", "text": "Edit", "within": "mallory"},
                {"action": "click", "text": "Edit"},
                {"action": "fill", "selector": "#u", "value": "never"},
            ],
        )
        self.assertEqual(result["completed"], 4, result)
        self.assertIn("3 elements match", result["stopped"]["reason"])
        self.assertEqual(self.browser("tabs")["tabs"][0]["title"], "mallory")
        self.assertEqual(
            self.browser("find", selector="#u")["items"][0]["value"], "admin"
        )
        waited = self.browser(
            "steps", steps=[{"action": "wait", "text": "nobody", "timeout": 0.3}]
        )
        self.assertEqual(waited["stopped"]["reason"], "wait not satisfied")
        # seconds pauses as in desktop_actions, alone or before a condition.
        started = time.monotonic()
        paused = self.browser(
            "steps",
            steps=[
                {"action": "wait", "seconds": 0.5},
                {"action": "wait", "seconds": 0.2, "selector": "#u"},
            ],
        )
        self.assertIsNone(paused["stopped"], paused)
        self.assertGreaterEqual(time.monotonic() - started, 0.7)
        self.assertEqual(paused["results"][0], {"satisfied": True, "waited": 0.5})
        with self.assertRaisesRegex(core.DesktopError, "or seconds"):
            self.browser("wait")


if __name__ == "__main__":
    unittest.main()
