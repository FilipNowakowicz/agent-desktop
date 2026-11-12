"""F2: a native document edit, end to end (real private sessions, LibreOffice).

A deterministic driver opens an agreement in Writer, changes the payment term in
one clause through Find, saves, closes LibreOffice, and opens the file again.
Trials vary the format (.odt, and .docx with its "Keep current format" dialog),
the clause order, and kill LibreOffice before a save, which leaves a stale lock
file for the reopen. The evaluator reads only the saved file and its folder.
"""

import os
import shutil
import signal
import tempfile
import time
import unittest
from pathlib import Path

import test_runtime
from test_runtime import wait_for

from agent_desktop import core
from agent_desktop.worker import owned_processes
from benchmarks import f2_document as doc
from scripts import office_smoke


class EvaluatorTests(unittest.TestCase):
    """The checker itself, against outcomes known to be wrong."""

    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="f2-doc-"))
        self.addCleanup(shutil.rmtree, self.directory)
        self.initial = doc.paragraphs(seed=3)

    def outcome(self, lines, name="agreement.odt", extra=()):
        folder = Path(tempfile.mkdtemp(dir=self.directory))
        path = folder / name
        doc.write(path, lines)
        for other in extra:
            (folder / other).write_text("x")
        return doc.evaluate(path, self.initial)

    def test_correct_outcome_passes_in_both_formats(self):
        right = doc.expected(self.initial)
        self.assertEqual(self.outcome(right), [])
        self.assertEqual(self.outcome(right, "agreement.docx"), [])
        docx = Path(tempfile.mkdtemp(dir=self.directory)) / "agreement.docx"
        doc.write(docx, right)
        self.assertEqual(doc.read(docx), right)

    def test_wrong_outcomes_fail(self):
        right = doc.expected(self.initial)
        untouched = self.outcome(self.initial)
        self.assertTrue(any(p.startswith("target") for p in untouched), untouched)
        every = [p.replace("30 days", "14 days") for p in self.initial]
        self.assertTrue(
            any(p.startswith("bystander") for p in self.outcome(every)), every
        )
        self.assertTrue(self.outcome(right[:-1]))  # A lost paragraph.
        self.assertTrue(self.outcome(right, extra=["agreement (1).odt"]))
        self.assertTrue(self.outcome(right, extra=[".~lock.agreement.odt#"]))
        self.assertIn("missing", doc.evaluate(self.directory / "gone.odt", right)[0])

    def test_the_seed_moves_the_payment_clause(self):
        positions = {
            next(i for i, p in enumerate(doc.paragraphs(s)) if p.endswith(doc.PAYMENT))
            for s in range(20)
        }
        self.assertGreater(len(positions), 2)


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "dbus-daemon", "libreoffice")),
    "desktop tools or LibreOffice unavailable",
)
class DocumentWorkflowTests(unittest.TestCase):
    setUp = test_runtime.RuntimeTests.setUp
    tearDown = test_runtime.RuntimeTests.tearDown
    new_session = test_runtime.RuntimeTests.new_session

    def trial(self, seed, suffix, kill_before_save=False):
        session = self.new_session()
        token = core.manifest(session)["token"]
        folder = self.root / f"documents-{seed}"
        folder.mkdir()
        path = folder / f"agreement{suffix}"
        initial = doc.paragraphs(seed)
        doc.write(path, initial)
        log = []
        office_smoke.launch(session, "Writer", [path])
        self.edit(session)
        if kill_before_save:
            self.kill_office(token)
            log.append("killed before save")
            self.assertEqual(doc.read(path), initial)  # Nothing was saved.
            self.open_again(session, path, log)
            self.edit(session)
        self.save(session, path, initial, log)
        self.quit(session, path)
        # The saved file opens again in a fresh LibreOffice.
        self.open_again(session, path, log)
        self.quit(session, path)
        self.assertEqual(doc.evaluate(path, initial), [], log)
        return log

    def edit(self, session):
        # Find selects the one sentence of the payment clause; typing replaces it.
        core.request(session, "key", key="ctrl+f")
        time.sleep(0.5)
        core.request(session, "key", key="ctrl+a")
        core.request(session, "type", text="within 30 days of receipt")
        core.request(session, "key", key="Return")
        time.sleep(0.3)
        core.request(session, "key", key="Escape")
        time.sleep(0.3)
        core.request(session, "type", text="within 14 days of receipt")

    def save(self, session, path, initial, log):
        core.request(session, "key", key="ctrl+s")
        if path.suffix == ".docx":
            # "Non-standard file format": an untitled dialog offering ODF or
            # Word. Press the Word button by name, through the accessibility tree.
            button = wait_for(lambda: self.button(session, "Use Word"), timeout=20)
            core.request(session, "ui_action", node=button["id"], action="press")
            log.append("kept the Word format")
        wait_for(lambda: doc.read(path) == doc.expected(initial), timeout=30)

    def quit(self, session, path):
        # After a save through a dialog, wait for the document to be the active
        # window again, so Ctrl+Q does not go to the closing dialog.
        window = wait_for(
            lambda: (
                (w := office_smoke.active(session))
                and path.name in w.get("title", "")
                and w
            ),
            timeout=20,
        )
        core.request(session, "focus", window=window["id"])
        core.request(session, "key", key="ctrl+q")
        wait_for(lambda: not self.window(session, "LibreOffice"), timeout=30)
        lock = path.with_name(f".~lock.{path.name}#")
        wait_for(lambda: not lock.exists(), timeout=10)

    def open_again(self, session, path, log):
        # LibreOffice 26 reopened over its own stale lock (same user and host)
        # without a "Document in Use" dialog; the lock is replaced on open.
        lock = path.with_name(f".~lock.{path.name}#")
        if lock.exists():
            log.append("reopened over a stale lock")
        office_smoke.launch(session, "Writer", [path])
        self.assertIn(path.name, office_smoke.active(session).get("title", ""))

    def button(self, session, prefix):
        dialog = office_smoke.active(session)
        if not dialog or dialog.get("title"):
            return None  # The dialog is the untitled active window.
        # Untitled, so not selectable by title: search the whole tree.
        nodes = core.request(session, "ui", max_nodes=2000)["nodes"]
        return next(
            (
                n
                for n in nodes
                if n.get("role") in ("button", "push button")
                and (n.get("name") or "").startswith(prefix)
            ),
            None,
        )

    def window(self, session, text):
        return next(
            (
                w
                for w in core.request(session, "windows")["windows"]
                if text in w["title"]
            ),
            None,
        )

    def kill_office(self, token):
        for pid in owned_processes(token):
            try:
                name = Path(f"/proc/{pid}/comm").read_text().strip()
            except OSError:
                continue
            if name.startswith(("soffice", "oosplash")):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        wait_for(
            lambda: (
                not any(
                    Path(f"/proc/{p}/comm").exists()
                    and Path(f"/proc/{p}/comm").read_text().startswith("soffice")
                    for p in owned_processes(token)
                )
            ),
            timeout=15,
        )

    def test_odt_clean_run(self):
        self.trial(seed=1, suffix=".odt")

    def test_docx_keeps_its_format(self):
        log = self.trial(seed=2, suffix=".docx")
        self.assertIn("kept the Word format", log)

    def test_killed_before_save_and_reopened_over_a_stale_lock(self):
        log = self.trial(seed=4, suffix=".odt", kill_before_save=True)
        self.assertIn("killed before save", log)
        self.assertIn("reopened over a stale lock", log)
