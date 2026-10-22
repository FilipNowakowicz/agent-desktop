"""Experimental effect ledger: file recording, diffs and window changes."""

import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from agent_desktop import effects
from agent_desktop.effects import (
    EffectLedger,
    FileRecorder,
    column_name,
    ini_values,
    key_changes,
    line_diff,
    odf_lines,
    ui_delta,
    ui_lines,
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


class KeyTests(unittest.TestCase):
    CONFIG = (
        "# Checkout\n[server]\nport = 8080\nlog_level = debug\n[admin]\nport = 8081\n"
    )

    def test_ini_values(self):
        self.assertEqual(
            ini_values(self.CONFIG),
            {"server/port": "8080", "server/log_level": "debug", "admin/port": "8081"},
        )
        self.assertIsNone(ini_values("just\nsome text\n"))
        self.assertIsNone(ini_values("[a]\nx=1\nprose line\nmore prose\n"))

    def test_changes_name_the_section(self):
        after = self.CONFIG.replace("port = 8080", "port = 8443")
        self.assertEqual(
            key_changes(self.CONFIG, after), ["[server] port: 8080 → 8443"]
        )
        self.assertEqual(
            key_changes("", "[view]\ntab-width=uint32 4\n"),
            ["[view] tab-width: None → uint32 4"],
        )
        self.assertIsNone(key_changes("a\nb\n", "a\nc\n"))

    def test_recorder_reports_keys_instead_of_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.conf").write_text(self.CONFIG)
            recorder = FileRecorder(root, "~")
            self.addCleanup(recorder.close)
            start = time.monotonic()
            (root / "app.conf").write_text(self.CONFIG.replace("debug", "warn"))
            self.assertTrue(wait_for(lambda: recorder.since(start)))
            time.sleep(0.2)
            files, _noise = recorder.summarize(recorder.since(start), start)
        self.assertEqual(files[0]["keys"], ["[server] log_level: debug → warn"])
        self.assertNotIn("diff", files[0])


class UITests(unittest.TestCase):
    def snapshot(self, window, nodes):
        return {"window": window, "lines": ui_lines(nodes)}

    def test_added_removed_and_changed(self):
        field = {"role": "entry", "name": "Email", "states": ["editable"]}
        before = self.snapshot(
            "Form", [field, {"role": "push button", "name": "Send", "states": []}]
        )
        after = self.snapshot(
            "Form",
            [
                {**field, "text": "ada@example.com"},
                {"role": "label", "name": "Sent", "states": []},
            ],
        )
        self.assertEqual(
            ui_delta(before, after),
            {
                "added": ["label 'Sent'"],
                "removed": ["push button 'Send'"],
                "changed": [
                    "entry 'Email' [editable] → text='ada@example.com' [editable]"
                ],
            },
        )

    def test_new_window_and_unknown(self):
        before = self.snapshot("Form", [])
        after = self.snapshot("Confirm", [{"role": "label", "name": "Sure?"}])
        self.assertEqual(
            ui_delta(before, after),
            {"window": "Confirm", "now": ["label 'Sure?'"]},
        )
        self.assertIsNone(ui_delta(None, after))
        self.assertEqual(ui_delta(before, before), {})


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
        # Deleting the file undoes the match.
        (self.root / "out.csv").unlink()
        self.assertTrue(wait_for(lambda: not ledger.matches(action, "~/*.csv")))
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


class EvidenceRetentionTests(unittest.TestCase):
    def recorder(self, root):
        recorder = FileRecorder(root, "~")
        self.addCleanup(recorder.close)
        return recorder

    def test_many_reports_do_not_consume_baseline_and_later_writes_remain_relative(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "notes"
            path.write_text("old\n")
            recorder = self.recorder(root)
            start = time.monotonic()
            path.write_text("new\n")
            self.assertTrue(wait_for(lambda: recorder.since(start)))
            for _ in range(20):
                files, _ = recorder.summarize(recorder.since(start), start)
                self.assertEqual(files[0]["change"], "modified")
                self.assertEqual(files[0]["diff"], ["-old", "+new"])
            path.write_text("later\n")
            files, _ = recorder.summarize(recorder.since(start), start)
            self.assertEqual(files[0]["diff"], ["-old", "+later"])
            self.assertLessEqual(len(recorder.versions["notes"]), 2)

    def test_history_eviction_is_unknown_never_created(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "notes"
            path.write_text("old")
            recorder = self.recorder(root)
            start = time.monotonic()
            for _ in range(effects.VERSIONS + 1):
                path.write_text("new")
                recorder.record("notes", time.monotonic())
            files, _ = recorder.summarize([(start, "modified", "notes")], start)
            self.assertEqual(files[0]["change"], "baseline_unknown")
            self.assertNotIn("diff", files[0])
            self.assertGreaterEqual(recorder.expired_before, start)
            watermark = recorder.expired_before
            recorder.expire(0)
            self.assertEqual(recorder.expired_before, watermark)

    def test_unavailable_history_does_not_mean_known_absence(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = self.recorder(Path(directory))
            self.assertEqual(
                recorder.before("unobserved", time.monotonic()), (None, None)
            )

    def test_watch_failure_and_event_expiry_are_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = EffectLedger(Path(directory), lambda: [], lambda: {})
            self.addCleanup(ledger.close)
            recorder = ledger.recorders[0]
            recorder.add_watch(Path(directory) / "missing")
            report = ledger.finish(ledger.begin())
            self.assertIn("incomplete", report)
            self.assertIn(
                "watch registration failed", report["file_coverage"][0]["failures"][0]
            )
            start = time.monotonic()
            with patch.object(effects, "MAX_EVENTS", 2):
                for i in range(3):
                    recorder.event(start + i, "modified", "notes")
            self.assertIn(
                "file evidence expired",
                ledger.report(start)["file_coverage"][0]["reasons"],
            )

    def test_read_failure_is_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = self.recorder(Path(directory))
            recorder.stopped = True
            recorder.thread.join(2)
            recorder.stopped = False
            with (
                patch.object(
                    effects.select, "select", return_value=([recorder.fd], [], [])
                ),
                patch.object(
                    effects.os, "read", side_effect=OSError("injected read failure")
                ),
            ):
                recorder.run()
            self.assertIn("injected read failure", recorder.failures[-1])

    def test_bounded_stress_retains_explicit_expiry(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = self.recorder(Path(directory))
            start = time.monotonic()
            for i in range(effects.MAX_EVENTS * 3):
                recorder.event(start + i / 100000, "modified", f"path-{i}")
            for i in range(effects.MAX_PATHS * 2):
                recorder.record(f"absent-{i}", time.monotonic())
            self.assertEqual(len(recorder.events), effects.MAX_EVENTS)
            self.assertEqual(len(recorder.versions), effects.MAX_PATHS)
            self.assertGreater(recorder.expired_before, start)
            self.assertEqual(recorder.before("absent-0", start), (None, None))

    def test_document_limits_flat_xml_and_decompression(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            flat = root / "sheet.fods"
            xml = (
                '<office:document xmlns:office="'
                + effects.ODF["office"]
                + '" xmlns:table="'
                + effects.ODF["table"]
                + '" xmlns:text="'
                + effects.ODF["text"]
                + '"><office:body><table:table table:name="S"><table:table-row table:number-rows-repeated="1001"><table:table-cell><text:p>x</text:p></table:table-cell></table:table-row></table:table></office:body></office:document>'
            )
            flat.write_text(xml)
            coverage = {}
            result = effects.read_document(flat, coverage)
            self.assertEqual(len(result.splitlines()), 1000)
            self.assertFalse(coverage["complete"])
            self.assertIn("1000", coverage["reasons"][0])
            zipped = root / "large.ods"
            with zipfile.ZipFile(zipped, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("content.xml", b"x" * 2048)
            with patch.object(effects, "DOCUMENT_LIMIT", 1024):
                self.assertIsNone(effects.read_document(zipped, coverage))
                self.assertIn("decompressed XML", coverage["reasons"][0])

    def test_truncated_equal_documents_are_not_reported_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "sheet.fods"
            path.write_text(
                '<office:document xmlns:office="'
                + effects.ODF["office"]
                + '" xmlns:text="'
                + effects.ODF["text"]
                + '"><office:body><text:p>first</text:p><text:p>second</text:p></office:body></office:document>'
            )
            with patch.object(effects, "MAX_CELLS", 1):
                recorder = self.recorder(root)
                start = time.monotonic()
                files, _ = recorder.summarize([(start, "modified", path.name)], start)
                self.assertEqual(files[0]["change"], "modified")
                self.assertFalse(files[0]["document_coverage"]["complete"])
                self.assertFalse(files[0]["baseline_document_coverage"]["complete"])

    def test_expired_action_id_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = EffectLedger(
                Path(directory), lambda: [], lambda: {}, quiet=0, limit=0
            )
            self.addCleanup(ledger.close)
            first = ledger.finish(ledger.begin())["effect_id"]
            for _ in range(201):
                ledger.finish(ledger.begin())
            self.assertEqual(len(ledger.records), 200)
            with self.assertRaisesRegex(ValueError, "expired effect_id"):
                ledger.since(first)

    def test_evicted_path_is_not_assumed_absent_for_a_new_action(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = self.recorder(Path(directory))
            with patch.object(effects, "MAX_PATHS", 1):
                recorder.record("one", time.monotonic())
                recorder.record("two", time.monotonic())
            start = time.monotonic()
            recorder.event(start + 0.001, "created", "one")
            self.assertEqual(recorder.before("one", start), (None, None))

    def test_unchanged_document_text_does_not_claim_unchanged_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "text.fods"
            path.write_text(
                '<office:document xmlns:office="'
                + effects.ODF["office"]
                + '" xmlns:text="'
                + effects.ODF["text"]
                + '"><office:body><text:p>same</text:p></office:body></office:document>'
            )
            recorder = self.recorder(root)
            start = time.monotonic()
            path.write_text(
                path.read_text().replace("<text:p>", '<text:p text:style-name="bold">')
            )
            files, _ = recorder.summarize([(start, "modified", path.name)], start)
            self.assertEqual(files[0]["change"], "canonical text unchanged")

    def test_invalid_utf8_transitions_never_report_unchanged_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "bytes.txt"
            path.write_bytes(b"old: \xff\n")
            recorder = self.recorder(root)
            start = time.monotonic()
            path.write_bytes(b"old: \xfe\n")
            files, _ = recorder.summarize([(start, "modified", path.name)], start)
            self.assertEqual(files[0]["change"], "modified")
            self.assertFalse(files[0]["document_coverage"]["complete"])
            self.assertFalse(files[0]["baseline_document_coverage"]["complete"])
            self.assertNotIn("diff", files[0])

    def test_equal_ini_keys_do_not_imply_unchanged_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "app.ini"
            path.write_text("[section]\nkey=value\n# old comment\n")
            recorder = self.recorder(root)
            start = time.monotonic()
            path.write_text("[section]\nkey=value\n# different comment\n")
            files, _ = recorder.summarize([(start, "modified", path.name)], start)
            self.assertEqual(files[0]["change"], "modified")
            self.assertNotIn("keys", files[0])

    def test_xml_depth_and_element_limits_are_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested.fods"
            for xml, limit_name in (
                ("<a>" * 130 + "</a>" * 130, "depth"),
                ("<a><b/><c/></a>", "elements"),
            ):
                path.write_text(xml)
                coverage = {}
                with patch.object(
                    effects,
                    "MAX_XML_ELEMENTS",
                    2 if limit_name == "elements" else 100000,
                ):
                    self.assertIsNone(effects.read_document(path, coverage))
                self.assertIn("depth/element limit", coverage["reasons"][0])

    def test_entity_declaration_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "entity.fods"
            path.write_text('<!DOCTYPE x [<!ENTITY a "expanded">]><x>&a;</x>')
            coverage = {}
            self.assertIsNone(effects.read_document(path, coverage))
            self.assertIn("declarations unsupported", coverage["reasons"][0])


if __name__ == "__main__":
    unittest.main()
