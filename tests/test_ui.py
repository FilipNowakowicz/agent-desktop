"""Semantic UI: read and operate a GTK dialog through the session's AT-SPI bus."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from test_runtime import CHROMIUM, wait_for

from agent_desktop import core
from agent_desktop.worker import find_registryd, owned_processes


class UISessionTest(unittest.TestCase):
    environment = {}

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-ui-")
        root = Path(self.temporary.name)
        keys = ("AGENT_DESKTOP_STATE_DIR", "XDG_RUNTIME_DIR", *self.environment)
        self.previous = {k: os.environ.get(k) for k in keys}
        (root / "runtime").mkdir(mode=0o700)
        os.environ["AGENT_DESKTOP_STATE_DIR"] = str(root / "state")
        os.environ["XDG_RUNTIME_DIR"] = str(root / "runtime")
        os.environ.update(self.environment)
        self.session = core.create()["session"]
        self.token = core.manifest(self.session)["token"]

    def tearDown(self):
        core.destroy(self.session)
        wait_for(lambda: not owned_processes(self.token))
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temporary.cleanup()


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "dbus-daemon", "zenity"))
    and find_registryd(),
    "desktop tools, zenity or at-spi2-core unavailable",
)
class UITests(UISessionTest):
    def find(self, predicate):
        def search():
            nodes = core.request(self.session, "ui", app="zenity")["nodes"]
            return next((n for n in nodes if predicate(n)), None)

        return wait_for(search, timeout=20)

    def test_fill_and_confirm_dialog_without_coordinates(self):
        self.assertTrue(core.request(self.session, "status")["accessibility"])
        app = core.request(
            self.session,
            "launch",
            argv=["zenity", "--entry", "--title=UI test", "--text=Your name"],
        )
        field = self.find(lambda n: "editable" in n["states"])
        self.assertIn("set_text", field["actions"])
        observation = core.request(self.session, "screenshot")["observation"]
        core.request(
            self.session,
            "ui_action",
            node=field["id"],
            action="set_text",
            text="Ada Lovelace ✓",
            observation=observation,
        )
        self.find(lambda n: n.get("text") == "Ada Lovelace ✓")
        label = self.find(lambda n: n["role"] == "label" and not n.get("actions"))
        with self.assertRaisesRegex(core.DesktopError, "AccessibilityError|no press"):
            core.request(self.session, "ui_action", node=label["id"], action="press")
        for bad in ("", "../x", ":1.2/elsewhere", None):
            with self.subTest(node=bad), self.assertRaises(core.DesktopError):
                core.request(self.session, "ui_action", node=bad, action="press")
        button = self.find(lambda n: n["role"] == "button" and n["name"] == "OK")
        core.request(self.session, "ui_action", node=button["id"], action="press")

        def exited():
            for entry in core.request(self.session, "status")["applications"]:
                if entry["pid"] == app["pid"] and entry["exit_code"] is not None:
                    return entry
            return None

        self.assertEqual(wait_for(exited)["exit_code"], 0)
        # The log also holds stderr (GTK warnings); zenity prints the entry last.
        lines = Path(app["logs"]).read_text().strip().splitlines()
        self.assertEqual(lines[-1], "Ada Lovelace ✓")

    def test_wait_for_elements_after_actions(self):
        core.request(
            self.session,
            "launch",
            argv=["zenity", "--entry", "--title=Wait test", "--text=Code"],
        )
        field = self.find(lambda n: "editable" in n["states"])
        # As a step in a sequence, an element wait re-baselines like other waits.
        result = core.run_actions(
            self.session,
            [{"action": "wait", "element": "OK", "role": "button", "timeout": 10}],
        )
        self.assertIsNone(result["stopped"], result)
        core.request(
            self.session, "ui_action", node=field["id"], action="set_text", text="4711"
        )
        found = core.wait(self.session, role=field["role"], text="4711", timeout=10)
        self.assertTrue(found["satisfied"], found)
        self.assertEqual(found["elements"][0]["id"], field["id"])
        missing = core.wait(self.session, element="No such element", timeout=0.5)
        self.assertEqual(missing["reason"], "no element")
        button = self.find(lambda n: n["role"] == "button" and n["name"] == "OK")
        core.request(self.session, "ui_action", node=button["id"], action="press")
        closed = core.wait(self.session, element="OK", gone=True, timeout=10)
        self.assertTrue(closed["satisfied"], closed)

    def test_compact_listing(self):
        core.request(
            self.session,
            "launch",
            argv=["zenity", "--entry", "--title=Compact", "--text=Code"],
        )
        field = self.find(lambda n: "editable" in n["states"])
        self.assertRegex(field["id"], r"^n[0-9]+$")
        tree = core.request(self.session, "ui", app="zenity")
        text = core.render_tree(tree)
        self.assertIn(f"{field['id']} {field['role']} 'Code' [editable", text)
        self.assertNotIn("showing", text)
        # Short ids stay stable across listings and work for actions.
        again = core.request(self.session, "ui", app="zenity")["nodes"]
        self.assertIn(field["id"], {n["id"] for n in again})
        core.request(
            self.session, "ui_action", node=field["id"], action="set_text", text="42"
        )
        self.find(lambda n: n["id"] == field["id"] and n.get("text") == "42")

    def test_combined_wait_requires_element_in_the_window(self):
        for title, text in (("Alpha dialog", "Secret code"), ("Beta dialog", "Other")):
            core.request(
                self.session,
                "launch",
                argv=["zenity", "--entry", f"--title={title}", f"--text={text}"],
            )
        self.find(lambda n: n["name"] == "Secret code")
        self.find(lambda n: n["name"] == "Other")
        # The element exists, but only in the other window.
        wrong = core.wait(
            self.session, title="Beta dialog", element="Secret code", timeout=1
        )
        self.assertFalse(wrong["satisfied"])
        self.assertEqual(wrong["reason"], "no element")
        right = core.wait(
            self.session, title="Alpha dialog", element="Secret code", timeout=5
        )
        self.assertTrue(right["satisfied"], right)

    def test_tree_filters_and_limits(self):
        core.request(
            self.session,
            "launch",
            argv=["zenity", "--info", "--title=Filter test", "--text=Hello"],
        )
        self.find(lambda n: n["role"] == "button")
        limited = core.request(self.session, "ui", max_nodes=2)
        self.assertEqual(len(limited["nodes"]), 2)
        self.assertTrue(limited["truncated"])
        self.assertEqual(
            core.request(self.session, "ui", app="no-such-app")["nodes"], []
        )
        self.assertEqual(
            core.request(self.session, "ui", window="No such window")["nodes"][1:],
            [],
        )
        with self.assertRaises(core.DesktopError):
            core.request(self.session, "ui", max_nodes=0)


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "dbus-daemon", "kdialog"))
    and find_registryd(),
    "desktop tools, kdialog or at-spi2-core unavailable",
)
class QtUITests(UISessionTest):
    def test_qt_input_dialog(self):
        app = core.request(
            self.session,
            "launch",
            argv=[
                "env",
                "QT_QPA_PLATFORM=wayland",
                "kdialog",
                "--inputbox",
                "Your name",
            ],
        )

        def nodes():
            return core.request(self.session, "ui", app="kdialog")["nodes"]

        field = wait_for(
            lambda: next((n for n in nodes() if "editable" in n["states"]), None),
            timeout=20,
        )
        core.request(
            self.session, "ui_action", node=field["id"], action="set_text", text="Grace"
        )
        button = next(n for n in nodes() if n["name"] == "OK")
        core.request(self.session, "ui_action", node=button["id"], action="press")
        wait_for(
            lambda: Path(app["logs"]).read_text().strip().splitlines()[-1:] == ["Grace"]
        )


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "dbus-daemon"))
    and CHROMIUM
    and find_registryd(),
    "desktop tools, Chromium or at-spi2-core unavailable",
)
class ChromiumUITests(UISessionTest):
    def test_web_form_without_coordinates(self):
        root = Path(self.temporary.name)
        page = root / "form.html"
        page.write_text(
            "<!doctype html><title>Login form</title>"
            "<label>Email <input></label>"
            "<button onclick=\"document.title='Sent '+"
            "document.querySelector('input').value\">Sign in</button>"
        )
        argv = [
            CHROMIUM,
            f"--user-data-dir={root / 'chromium'}",
            "--no-first-run",
            "--ozone-platform=wayland",
            "--disable-gpu",
            "--password-store=basic",
            "--force-renderer-accessibility",
        ]
        if os.geteuid() == 0:  # CI containers; never used for real profiles
            argv.append("--no-sandbox")
        app = core.request(self.session, "launch", argv=[*argv, page.as_uri()])
        found = core.wait(self.session, title="Login form", timeout=30)
        if (
            not found["satisfied"]
            and "No usable sandbox" in Path(app["logs"]).read_text()
        ):
            self.skipTest("Chromium sandbox unavailable in this environment")

        def node(name):
            nodes = core.request(self.session, "ui")["nodes"]
            return next((n for n in nodes if n["name"] == name), None)

        field = wait_for(lambda: node("Email"), timeout=30)
        self.assertIn("editable", field["states"])
        result = core.request(
            self.session,
            "ui_action",
            node=field["id"],
            action="set_text",
            text="ada@example.com",
        )
        # Chromium lacks SetTextContents; the field is focused, checked, then typed.
        self.assertEqual(result["method"], "keyboard")
        core.request(
            self.session, "ui_action", node=node("Sign in")["id"], action="press"
        )
        sent = core.wait(self.session, title="Sent ada@example.com", timeout=10)
        self.assertTrue(sent["satisfied"], sent)


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "dbus-daemon")),
    "desktop tools unavailable",
)
class NoAccessibilityTests(UISessionTest):
    environment = {"AGENT_DESKTOP_AT_SPI_REGISTRYD": "/nonexistent/registryd"}

    def test_ui_reports_missing_runtime(self):
        self.assertFalse(core.request(self.session, "status")["accessibility"])
        with self.assertRaisesRegex(core.DesktopError, "at-spi2-core"):
            core.request(self.session, "ui")


if __name__ == "__main__":
    unittest.main()
