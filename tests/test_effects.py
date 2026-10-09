"""Experimental effect ledger: file recording, diffs and window changes."""

import tempfile
import time
import unittest
from pathlib import Path

from agent_desktop.effects import (
    EffectLedger,
    FileRecorder,
    column_name,
    line_diff,
    odf_lines,
    window_changes,
)
from scripts import office_smoke


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class DiffTests(unittest.TestCase):
    def test_line_diff_lists_changed_lines(self):
        self.assertEqual(line_diff("a\nb\nc\n", "a\nB\nc\n"), ["-b", "+B"])

    def test_line_diff_is_bounded(self):
        diff = line_diff("", "\n".join(str(i) for i in range(50)))
        self.assertEqual(len(diff), 21)
        self.assertTrue(diff[-1].startswith("… 30 more"))

    def test_column_names(self):
        self.assertEqual(
            [column_name(i) for i in (0, 25, 26, 701, 702)],
            ["A", "Z", "AA", "ZZ", "AAA"],
        )

    def test_spreadsheet_cells(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "budget.ods"
            office_smoke.spreadsheet(path)
            self.assertEqual(
                odf_lines(path).splitlines(),
                [
                    "Budget!A1: Item",
                    "Budget!A2: Apples",
                    "Budget!B2: 12",
                    "Budget!A3: Pears",
                    "Budget!B3: 8",
                    "Budget!A4: Total",
                ],
            )

    def test_not_an_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fake.ods"
            path.write_text("not a zip")
            self.assertIsNone(odf_lines(path))


class WindowTests(unittest.TestCase):
    def test_opened_closed_retitled_and_focus(self):
        before = [
            {"id": "w1", "title": "Doc", "app_id": "ed", "states": ["activated"]},
            {"id": "w2", "title": "Tip", "app_id": "ed", "states": []},
        ]
        after = [
            {"id": "w1", "title": "*Doc", "app_id": "ed", "states": []},
            {"id": "w3", "title": "Save As", "app_id": "ed", "states": ["activated"]},
        ]
        self.assertEqual(
            window_changes(before, after),
            {
                "opened": ["'Save As' (ed)"],
                "closed": ["'Tip' (ed)"],
                "retitled": ["'Doc' → '*Doc'"],
                "focus": "'Doc' (ed) → 'Save As' (ed)",
            },
        )

    def test_no_change(self):
        windows = [{"id": "w1", "title": "A", "app_id": "x", "states": []}]
        self.assertEqual(window_changes(windows, windows), {})


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "notes.txt").write_text("one\n")
        (self.root / ".config").mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def ledger(self):
        ledger = EffectLedger(self.root, lambda: [], lambda: {})
        self.addCleanup(ledger.close)
        return ledger

    def test_modified_created_deleted_and_noise(self):
        ledger = self.ledger()
        state = ledger.begin()
        (self.root / "notes.txt").write_text("one\ntwo\n")
        (self.root / "new.txt").write_text("hello\n")
        (self.root / ".config" / "app.conf").write_text("x=1\n")
        (self.root / "temp.txt").write_text("gone")
        (self.root / "temp.txt").unlink()
        (self.root / ".cache").mkdir()
        (self.root / ".cache" / "blob").write_text("noise")
        report = ledger.finish(state)
        self.assertEqual(
            report["files"],
            [
                {
                    "path": "~/new.txt",
                    "change": "created",
                    "bytes": 6,
                    "diff": ["+hello"],
                },
                {
                    "path": "~/notes.txt",
                    "change": "modified",
                    "bytes": 8,
                    "diff": ["+two"],
                },
            ],
        )
        self.assertEqual(
            report["app_state"],
            [
                {
                    "path": "~/.config/app.conf",
                    "change": "created",
                    "bytes": 4,
                    "diff": ["+x=1"],
                }
            ],
        )
        self.assertGreaterEqual(report["noise_files"], 1)
        # Events are timestamped when read (inotify has no times): let this one
        # arrive before the next action begins, or it counts as that action's.
        recorder = ledger.recorders[0]
        count = len(recorder.events)
        (self.root / "notes.txt").unlink()
        self.assertTrue(wait_for(lambda: len(recorder.events) > count))
        recorder.summarize(recorder.since(0), 0)
        state = ledger.begin()
        (self.root / "new.txt").unlink()
        report = ledger.finish(state)
        self.assertEqual(report["files"], [{"path": "~/new.txt", "change": "deleted"}])

    def test_reports_are_repeatable(self):
        # The action's own reply must not use up the diff for later queries.
        ledger = self.ledger()
        state = ledger.begin()
        (self.root / "notes.txt").write_text("one\nchanged\n")
        first = ledger.finish(state)
        again = ledger.since(first["effect_id"])
        self.assertEqual(first["files"], again["files"])
        self.assertEqual(again["files"][0]["diff"], ["+changed"])

    def test_nothing_observed(self):
        ledger = self.ledger()
        report = ledger.finish(ledger.begin())
        self.assertNotIn("files", report)
        self.assertIn("observed_s", report)

    def test_late_write_and_match(self):
        ledger = self.ledger()
        report = ledger.finish(ledger.begin())
        action = report["effect_id"]
        self.assertFalse(ledger.matches(action, "~/*.csv"))
        (self.root / "out.csv").write_text("a,b\n")
        self.assertTrue(wait_for(lambda: ledger.matches(action, "~/*.csv")))
        late = ledger.since(action)
        self.assertEqual(late["files"][0]["path"], "~/out.csv")
        with self.assertRaises(ValueError):
            ledger.matches(action, "*.csv")
        with self.assertRaises(ValueError):
            ledger.since(9999)

    def test_files_written_before_a_new_directory_is_watched(self):
        recorder = FileRecorder(self.root, "~")
        self.addCleanup(recorder.close)
        start = time.monotonic()
        # mkdir -p and a write in one go, faster than the watch can be added.
        deep = self.root / "x" / "y"
        deep.mkdir(parents=True)
        (deep / "keyfile").write_text("[a]\nb=1\n")
        self.assertTrue(
            wait_for(lambda: any(e[2] == "x/y/keyfile" for e in recorder.since(start)))
        )

    def test_new_directories_are_watched(self):
        recorder = FileRecorder(self.root, "~")
        self.addCleanup(recorder.close)
        start = time.monotonic()
        (self.root / "a" / "b").mkdir(parents=True)
        self.assertTrue(wait_for(lambda: len(recorder.watches) >= 4))
        (self.root / "a" / "b" / "deep.txt").write_text("x\n")
        self.assertTrue(
            wait_for(lambda: any(e[2] == "a/b/deep.txt" for e in recorder.since(start)))
        )


if __name__ == "__main__":
    unittest.main()
