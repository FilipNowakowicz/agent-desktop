"""Browser bridge: a private Firefox driven through WebDriver BiDi (real browser)."""

import functools
import json
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

    def test_send_moves_a_secret_without_returning_it(self):
        planted = "tskey-auth-PLANTED0123456789"
        self.page.write_text(
            '<title>Key</title><h1>Your key</h1><pre id="key">\n'
            + planted
            + "\n</pre><pre>other</pre>"
            '<button id="copy" onclick="navigator.clipboard.writeText('
            "key.textContent.trim()).then(() => {state.textContent = 'Copied'}, "
            "(e) => {state.textContent = 'Failed ' + e})\">"
            'Copy</button><p id="state"></p>'
        )
        self.browser("start", url=self.page.as_uri())
        self.assertTrue(self.browser("wait", selector="#key", timeout=20)["satisfied"])
        home = Path(
            core.manifest(self.session)["home"]
            or core.session_path(self.session) / "home"
        )
        replies = []
        sent = self.browser("send", selector="#key", to_file="key.txt")
        replies.append(sent)
        self.assertEqual(sent["bytes"], len(planted))
        self.assertEqual(sent["prefix"], "tske")
        written = home / "key.txt"
        self.assertEqual(written.read_text(), planted)
        self.assertEqual(written.stat().st_mode & 0o777, 0o600)
        # An existing file is kept unless overwrite; ambiguity lists nothing.
        with self.assertRaisesRegex(core.DesktopError, "exists") as refused:
            self.browser("send", selector="#key", to_file="~/key.txt")
        replies.append(str(refused.exception))
        with self.assertRaisesRegex(core.DesktopError, "2 visible") as refused:
            self.browser("send", selector="pre", to_file="other.txt")
        replies.append(str(refused.exception))
        self.assertFalse((home / "other.txt").exists())
        # A command that echoes its input: its output is discarded.
        echoed = self.browser(
            "send",
            selector="#key",
            reveal=0,
            to_command=[
                "sh",
                "-c",
                'tee "$HOME/stdin.txt"; tee /dev/stderr <"$HOME/stdin.txt"',
            ],
        )
        replies.append(echoed)
        self.assertEqual(echoed["exit_status"], 0)
        self.assertNotIn("prefix", echoed)
        self.assertEqual((home / "stdin.txt").read_text(), planted)
        # The clipboard source, after a page's Copy button.
        self.browser("click", selector="#copy")
        copied = self.browser("wait", text="Copied", timeout=10)
        self.assertTrue(copied["satisfied"], self.browser("text", selector="#state"))
        clipped = self.browser(
            "steps",
            steps=[{"action": "send", "source": "clipboard", "to_file": "clip.txt"}],
        )
        replies.append(clipped)
        self.assertIsNone(clipped["stopped"], clipped)
        self.assertEqual((home / "clip.txt").read_text(), planted)
        for reply in replies:
            self.assertNotIn(planted, json.dumps(reply))
        # Nothing the runtime keeps holds it: traces, journals, logs, records.
        leaks = []
        for path in self.root.rglob("*"):
            if (
                not path.is_file()
                or path.is_symlink()
                or home in path.parents
                or path == self.page
            ):
                continue
            try:
                if planted.encode() in path.read_bytes():
                    leaks.append(path)
            except OSError:
                continue
        self.assertEqual(leaks, [])

    def test_send_hides_the_file_from_effect_reports(self):
        planted = "tskey-client-PLANTEDEFFECTS42"
        self.page.write_text(f'<title>Key</title><pre id="key">{planted}</pre>')
        with mock.patch.dict(os.environ, {"AGENT_DESKTOP_EFFECTS": "1"}):
            session = core.create()["session"]
        token = core.manifest(session)["token"]
        try:
            request = functools.partial(core.request, session, "browser")
            request(action="start", url=self.page.as_uri())
            self.assertTrue(
                request(action="wait", selector="#key", timeout=20)["satisfied"]
            )
            sent = request(action="send", selector="#key", to_file="key.txt")
            self.assertNotIn(planted, json.dumps(sent))
            listed = [
                f for f in sent["effects"].get("files", []) if f["path"] == "~/key.txt"
            ]
            self.assertEqual(listed[0]["content"], "hidden", sent["effects"])
        finally:
            core.destroy(session)
            wait_for(lambda: not owned_processes(token))

    def test_clicks_report_whether_a_toggle_changed(self):
        self.page.write_text(
            "<title>Toggles</title>"
            '<label>Ephemeral <input id="locked" type="checkbox" '
            'onclick="return false"></label>'
            '<button id="sw" role="switch" aria-checked="false" onclick="'
            "this.setAttribute('aria-checked', String(this.getAttribute("
            "'aria-checked') !== 'true'))\">Reusable</button>"
            '<button id="plain">Plain</button>'
        )
        self.browser("start", url=self.page.as_uri())
        self.assertTrue(self.browser("wait", selector="#sw", timeout=20)["satisfied"])
        # A delivered label click that the page ignores: visibly unchanged.
        ignored = self.browser("click", text="Ephemeral")
        self.assertTrue(ignored["delivered"])
        self.assertEqual(
            ignored["toggle"], {"before": "false", "after": "false", "changed": False}
        )
        switched = self.browser("click", selector="#sw")
        self.assertEqual(
            switched["toggle"], {"before": "false", "after": "true", "changed": True}
        )
        self.assertNotIn("toggle", self.browser("click", selector="#plain"))

    def test_activity_counts_stopped_batches_and_waits(self):
        self.browser("start", url=self.page.as_uri())
        stopped = self.browser(
            "steps",
            steps=[
                {"action": "wait", "selector": "#fullname", "timeout": 20},
                {"action": "wait", "seconds": 0.2},
                {"action": "click", "text": "Save"},
            ],
        )
        self.assertEqual(stopped["stopped"]["step"], 2, stopped)
        summary = core.activity(self.session)
        self.assertEqual(summary["browser_batches"], 1)
        self.assertEqual(summary["browser_stops_by_reason"], {"ambiguous": 1})
        self.assertEqual(summary["browser_waits_fixed"], 1)
        self.assertEqual(summary["browser_waits_for_condition"], 1)
        self.assertEqual(summary["browser_fixed_wait_seconds"], 0.2)

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

    def test_find_items_carry_classes_and_a_unique_selector(self):
        rows = "".join(
            f'<tr><td>{n}</td><td><button class="btn btn-small edit">Edit</button>'
            "</td></tr>"
            for n in ("alice", "bob")
        )
        self.page.write_text(
            f'<title>Rows</title><div id="admin"><table>{rows}</table></div>'
            '<button id="go" class="primary">Go</button>'
        )
        self.browser("start", url=self.page.as_uri())
        self.assertTrue(self.browser("wait", selector="#go", timeout=20)["satisfied"])
        found = self.browser("find", text="Edit")
        self.assertEqual(found["count"], 2)
        selectors = [item["selector"] for item in found["items"]]
        self.assertEqual(found["items"][0]["class"], "btn btn-small edit")
        self.assertEqual(len(set(selectors)), 2)
        self.assertTrue(all(s.startswith("#admin > ") for s in selectors), selectors)
        # Each selector picks exactly its own element.
        clicked = self.browser("click", selector=selectors[1])
        self.assertTrue(clicked["delivered"])
        self.assertEqual(self.browser("find", text="Go")["items"][0]["selector"], "#go")

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
