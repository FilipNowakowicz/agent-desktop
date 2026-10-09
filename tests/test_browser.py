"""Browser bridge: a private Firefox driven through WebDriver BiDi (real browser)."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from test_runtime import wait_for

from agent_desktop import core
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
        started = self.browser("start")
        self.assertEqual(started["tabs"][0]["url"], self.page.as_uri())
        self.assertEqual(len(core.request(self.session, "status")["applications"]), 1)


if __name__ == "__main__":
    unittest.main()
