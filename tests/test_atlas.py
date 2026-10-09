"""Experimental effect atlas: configuration parsing, lookup and applying."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

from agent_desktop import atlas

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import effect_atlas  # noqa: E402

ATLAS = {
    "summary": {"app": "editor"},
    "atlas": [
        {
            "kind": "check box",
            "tab": [[3, "View"]],
            "label": "Highlight current line",
            "default": False,
            "effect": [
                {
                    "file": "~/.config/editor/settings.conf",
                    "key": "[prefs/view] highlight-current-line",
                    "from": None,
                    "to": "true",
                }
            ],
            "verified": True,
        },
        {
            "kind": "menu",
            "menu": "View",
            "label": "Menubar",
            "effect": [
                {
                    "file": "~/.config/editor/settings.conf",
                    "key": "[prefs/window] menubar-visible",
                    "from": None,
                    "to": "false",
                }
            ],
        },
        {"kind": "menu", "menu": "Document", "label": "Viewer Mode", "effect": []},
    ],
}


class ParseTests(unittest.TestCase):
    def test_ini(self):
        self.assertEqual(
            effect_atlas.parse_ini("[a]\nx=1\n# c\n[b/c]\ny = two\n"),
            {"[a] x": "1", "[b/c] y": "two"},
        )

    def test_xcu(self):
        text = (
            '<item oor:path="/org.openoffice.Office.Calc/Input"><prop '
            'oor:name="AutoInput" oor:op="fuse"><value>false</value></prop></item>'
        )
        self.assertEqual(
            effect_atlas.parse_xcu(text),
            {"/org.openoffice.Office.Calc/Input/AutoInput": "false"},
        )

    def test_prefs_js(self):
        self.assertEqual(
            effect_atlas.parse_prefs_js('user_pref("browser.startup.page", 3);\n'),
            {"browser.startup.page": "3"},
        )

    def test_changes(self):
        before = {"f": {"a": "1", "b": "2"}}
        after = {"f": {"a": "1", "b": "3", "c": "4"}}
        self.assertEqual(
            effect_atlas.changes(before, after),
            [("f", "b", "2", "3"), ("f", "c", None, "4")],
        )

    def test_write_ini_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "s.conf"
            path.write_text("[a]\nx=1\n\n[b]\ny=2\n")
            effect_atlas.write_ini_key(path, "[a] x", "9")
            effect_atlas.write_ini_key(path, "[b] z", "3")
            effect_atlas.write_ini_key(path, "[c] w", "4")
            self.assertEqual(
                effect_atlas.parse_ini(path.read_text()),
                {"[a] x": "9", "[b] z": "3", "[b] y": "2", "[c] w": "4"},
            )


class LookupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        (self.directory / "atlas-editor.json").write_text(json.dumps(ATLAS))

    def tearDown(self):
        self.temporary.cleanup()

    def test_search_by_everyday_words(self):
        found = atlas.search(
            "highlight the line the cursor is on", "editor", directory=self.directory
        )
        self.assertEqual(
            found[0]["control"],
            "Preferences dialog > View tab > check box 'Highlight current line'",
        )
        self.assertTrue(found[0]["verified"])

    def test_entries_without_effect_are_not_listed(self):
        found = atlas.search("", "editor", directory=self.directory)
        self.assertEqual(len(found), 2)

    def test_apply_writes_the_learned_key(self):
        home = self.directory / "home"
        result = atlas.apply(
            home, "editor", "Highlight current line", directory=self.directory
        )
        self.assertEqual(len(result["written"]), 1)
        text = (home / ".config/editor/settings.conf").read_text()
        self.assertIn("[prefs/view]\nhighlight-current-line=true", text)

    def test_apply_refuses_a_different_starting_value(self):
        home = self.directory / "home"
        path = home / ".config/editor/settings.conf"
        path.parent.mkdir(parents=True)
        path.write_text("[prefs/view]\nhighlight-current-line=maybe\n")
        with self.assertRaisesRegex(ValueError, "nothing was written"):
            atlas.apply(
                home, "editor", "Highlight current line", directory=self.directory
            )
        self.assertIn("=maybe", path.read_text())
        path.write_text("[prefs/view]\nhighlight-current-line=true\n")
        result = atlas.apply(
            home, "editor", "Highlight current line", directory=self.directory
        )
        self.assertEqual(result["written"], [])
        self.assertEqual(len(result["unchanged"]), 1)

    def test_apply_refuses_unverified_and_unknown(self):
        for control in ("Menubar", "Nothing"):
            with self.subTest(control=control), self.assertRaises(ValueError):
                atlas.apply(self.directory, "editor", control, directory=self.directory)

    def test_no_atlas(self):
        with self.assertRaises(ValueError):
            atlas.search("x", directory=self.directory / "missing")


if __name__ == "__main__":
    unittest.main()
