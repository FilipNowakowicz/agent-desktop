"""F2: a mixed workflow, end to end (real private sessions, Firefox and Writer).

A loopback contract portal lists the current agreement and a superseded one. A
deterministic driver downloads the current one through the DOM bridge, edits
its payment clause in LibreOffice Writer (as the document workflow does), and
uploads the saved file through the browser's own file chooser. The portal
refuses the first upload in one trial and, in another, stores it but answers
after the page has given up, so the page cannot say whether it arrived. The
driver reconciles from the portal's Received list before any retry. The
evaluator never looks at the page or the local file: it checks the uploads the
portal stored, so a lost upload, a duplicate, a wrong format, the superseded
document or an unedited one each fail the trial.
"""

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urljoin

import test_browser
import test_document_workflow
from test_runtime import CHROMIUM, wait_for

from agent_desktop import core
from agent_desktop.worker import find_registryd
from benchmarks import f2_document as doc
from benchmarks.f2_mixed import (
    CURRENT,
    GOAL,
    LATE_REPLY_S,
    PAGE,
    MixedUpload,
    Portal,
    evaluate,
)
from scripts import office_smoke


class EvaluatorTests(unittest.TestCase):
    """The checker itself, against outcomes known to be wrong."""

    def setUp(self):
        self.portal = Portal(seed=5, suffix=".odt")
        self.addCleanup(self.portal.close)
        self.directory = Path(tempfile.mkdtemp(prefix="f2-mixed-"))
        self.addCleanup(shutil.rmtree, self.directory)

    def document(self, lines, suffix=".odt"):
        path = self.directory / f"made{len(list(self.directory.iterdir()))}{suffix}"
        doc.write(path, lines)
        return path.read_bytes()

    def problems(self, *uploads, portal=None):
        portal = portal or self.portal
        for name, body in uploads:
            portal.upload(name, body)
        return evaluate(portal)

    def test_one_correct_upload_passes_in_both_formats(self):
        right = self.document(doc.expected(self.portal.initial))
        self.assertEqual(self.problems(("agreement.odt", right)), [])
        word = Portal(seed=5, suffix=".docx")
        self.addCleanup(word.close)
        body = self.document(doc.expected(word.initial), ".docx")
        self.assertEqual(self.problems(("agreement.docx", body), portal=word), [])

    def test_wrong_outcomes_fail(self):
        initial = self.portal.initial
        right = self.document(doc.expected(initial))
        cases = {
            "nothing uploaded": [],
            "duplicate": [("agreement.odt", right), ("agreement.odt", right)],
            "unedited": [("agreement.odt", self.document(initial))],
            "superseded edited": [
                (
                    "agreement-2025.odt",
                    self.document(doc.expected(self.portal.superseded)),
                )
            ],
            "every 30 days changed": [
                (
                    "agreement.odt",
                    self.document([p.replace("30 days", "14 days") for p in initial]),
                )
            ],
            "incomplete": [("agreement.odt", right[: len(right) // 2])],
            "empty": [("agreement.odt", b"")],
            "other format": [
                ("agreement.docx", self.document(doc.expected(initial), ".docx"))
            ],
        }
        for name, uploads in cases.items():
            with self.subTest(name):
                portal = Portal(seed=5, suffix=".odt")
                self.addCleanup(portal.close)
                self.assertTrue(self.problems(*uploads, portal=portal), name)

    def test_refused_upload_is_not_counted_but_a_late_reply_is(self):
        right = self.document(doc.expected(self.portal.initial))
        refused = Portal(seed=5, failure="refused")
        self.addCleanup(refused.close)
        self.assertEqual(refused.upload("agreement.odt", right), (503, 0))
        self.assertEqual(evaluate(refused), ["nothing was uploaded"])
        self.assertEqual(refused.upload("agreement.odt", right)[0], 200)
        self.assertEqual(evaluate(refused), [])
        late = Portal(seed=5, failure="lost reply")
        self.addCleanup(late.close)
        self.assertEqual(late.upload("agreement.odt", right), (200, LATE_REPLY_S))
        self.assertEqual(evaluate(late), [])  # Stored, though the page never knew.
        late.upload("agreement.odt", right)
        self.assertIn("duplicate", evaluate(late)[0])

    def test_answers_stay_out_of_the_page(self):
        self.assertNotIn("14 days", PAGE)
        self.assertNotIn(doc.PAID, PAGE)
        self.assertNotEqual(self.portal.initial, self.portal.superseded)


class AgentTaskTests(unittest.TestCase):
    """The benchmark task wraps the same portal and judges only its uploads."""

    def test_task_judges_the_portal(self):
        task = MixedUpload(seed=9, suffix=".odt", failure="refused")
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            state = {"AGENT_DESKTOP_STATE_DIR": str(directory / "state")}
            with mock.patch.dict(os.environ, state):
                context = test_document_workflow.fake_context(directory)
                commands, prompt = task.setup(context)
            try:
                self.assertEqual(prompt, GOAL)
                self.assertIn("--writer", commands[0])
                self.assertEqual(commands[-1][-1], context.portal.url)
                portal = context.portal
                with mock.patch("benchmarks.f2_mixed.time.sleep"):
                    self.assertFalse(task.check(context)[0])  # Nothing uploaded.
                    path = directory / "agreement.odt"
                    doc.write(path, doc.expected(portal.initial))
                    right = path.read_bytes()
                    portal.upload("agreement.odt", right)  # Refused.
                    self.assertFalse(task.check(context)[0])
                    portal.upload("agreement.odt", right)
                    passed, detail = task.check(context)
                    self.assertTrue(passed, detail)
                    self.assertEqual(
                        [a["stored"] for a in detail["attempts"]], [False, True]
                    )
                    portal.upload("agreement.odt", right)
                    self.assertFalse(task.check(context)[0])  # A duplicate.
            finally:
                for close in context.closers:
                    close()


class Driver:
    """A deterministic procedure that sees only the page, the downloaded file
    and the session's windows."""

    DIALOG = "File Upload"

    def __init__(self, test, portal):
        self.test = test
        self.session = test.session
        self.portal = portal
        self.log = []

    def browser(self, action, **arguments):
        return self.test.browser(action, **arguments)

    def download(self):
        links = self.browser("find", selector="#docs a")["items"]
        link = next(i for i in links if i.get("text", "").startswith(CURRENT))
        url = urljoin(self.portal.url, link["href"])
        receipt = self.browser("download", url=url)
        self.log.append(f"downloaded {receipt['name']} ({receipt['bytes']} bytes)")
        return Path(receipt["file"])

    def process(self, path):
        """The document workflow's edit, save and quit, on the downloaded file."""
        initial = doc.read(path)
        office_smoke.launch(self.session, "Writer", [path])
        self.test.edit(self.session)
        self.test.save(self.session, path, initial, self.log)
        self.test.quit(self.session, path)

    def received(self):
        text = self.browser("text", selector="#received")["text"]
        rows = []
        for line in text.splitlines()[1:]:
            cells = [c.strip() for c in line.split("\t")]
            if len(cells) >= 2:
                rows.append((cells[0], int(cells[1])))
        return rows

    def choose(self, path):
        self.browser("click", selector="#file")
        self.choose_in_dialog(path)
        wait_for(
            lambda: (
                self.browser("find", selector="#file")["items"][0]
                .get("value", "")
                .endswith(path.name)
            ),
            timeout=20,
        )

    def choose_in_dialog(self, path):
        # The browser's own file chooser: type the path into its location field.
        dialog = wait_for(
            lambda: next(
                (
                    w
                    for w in core.request(self.session, "windows")["windows"]
                    if w["title"].startswith(self.DIALOG)
                ),
                None,
            ),
            timeout=20,
        )
        core.request(self.session, "focus", window=dialog["id"])
        core.request(self.session, "key", key="ctrl+l")
        time.sleep(0.3)
        core.request(self.session, "type", text=str(path))
        time.sleep(0.3)  # GTK file chooser path validation, as office_smoke has it.
        core.request(self.session, "key", key="Return")

    def send(self):
        self.browser("click", selector="#send")

    def message(self):
        def settled():
            text = self.browser("text", selector="#msg")["text"].strip()
            return text if text and not text.startswith("Uploading") else None

        return wait_for(settled, timeout=30)

    def upload(self, path):
        size = path.stat().st_size
        for attempt in range(3):
            if (path.name, size) in self.received():
                if attempt:
                    self.log.append("reconciled from Received, not resubmitted")
                return
            self.choose(path)
            self.send()
            reply = self.message()
            self.log.append(f"attempt {attempt + 1}: {reply}")
            if reply.startswith("Uploaded"):
                return
            if reply.startswith("Upload failed"):
                self.log.append("retried: the portal stored nothing")
            # No reply: the page refreshes Received after every attempt, and
            # the loop checks it before submitting again.
            time.sleep(1)
        raise AssertionError(f"upload did not settle: {self.log}")

    def run(self):
        path = self.download()
        self.process(path)
        self.upload(path)
        return path


class ChromiumDriver(Driver):
    """The same procedure in Chromium, which has no DOM bridge: the page is read
    and operated through its accessibility tree (desktop_ui)."""

    DIALOG = "Open File"

    def nodes(self):
        return core.request(self.session, "ui", max_nodes=2000)["nodes"]

    def node(self, name, role=None):
        return next(
            (
                n
                for n in self.nodes()
                if (n.get("name") or "").startswith(name)
                and (role is None or n["role"] == role)
            ),
            None,
        )

    def press(self, name, role):
        node = wait_for(lambda: self.node(name, role), timeout=20)
        core.request(self.session, "ui_action", node=node["id"], action="press")

    def download(self):
        folder = core.session_path(self.session) / "home/Downloads"
        self.press(CURRENT, "link")
        name = self.portal.name
        size = len(self.portal.files[name])
        path = folder / name
        # Chromium writes NAME.crdownload, then renames it.
        wait_for(lambda: path.exists() and path.stat().st_size == size, timeout=30)
        self.log.append(f"downloaded {name} ({size} bytes)")
        return path

    def received(self):
        cells = [
            (n.get("name") or "")
            for n in self.nodes()
            if n["role"] in ("table cell", "cell")
        ]
        return [(cells[i], int(cells[i + 1])) for i in range(0, len(cells) - 2, 3)]

    def choose(self, path):
        self.press("Choose file", "button")
        self.choose_in_dialog(path)
        wait_for(lambda: self.node(f"Choose file: {path.name}", "button"), timeout=20)

    def send(self):
        self.press("Upload", "button")

    def message(self):
        def settled():
            for n in self.nodes():
                text = (n.get("name") or "").strip()
                if n["role"] == "static" and text.startswith(
                    ("Uploaded", "Upload failed", "No reply")
                ):
                    return text
            return None

        return wait_for(settled, timeout=30)


@unittest.skipUnless(
    all(
        shutil.which(t)
        for t in ("labwc", "grim", "dbus-daemon", "firefox", "libreoffice")
    ),
    "desktop tools, Firefox or LibreOffice unavailable",
)
class MixedWorkflowTests(unittest.TestCase):
    setUp = test_browser.BrowserTests.setUp
    tearDown = test_browser.BrowserTests.tearDown
    browser = test_browser.BrowserTests.browser
    edit = test_document_workflow.DocumentWorkflowTests.edit
    save = test_document_workflow.DocumentWorkflowTests.save
    quit = test_document_workflow.DocumentWorkflowTests.quit
    button = test_document_workflow.DocumentWorkflowTests.button
    window = test_document_workflow.DocumentWorkflowTests.window

    def trial(self, seed, suffix, failure=None):
        portal = Portal(seed, suffix, failure=failure)
        self.addCleanup(portal.close)
        self.browser("start", url=portal.url)
        self.assertTrue(
            self.browser("wait", selector="#docs a", timeout=20)["satisfied"]
        )
        driver = Driver(self, portal)
        driver.run()
        time.sleep(LATE_REPLY_S + 1)  # An upload still in flight would land here.
        self.assertEqual(evaluate(portal), [], driver.log)
        return driver.log, portal

    def test_odt_upload_refused_once_then_retried(self):
        log, portal = self.trial(seed=6, suffix=".odt", failure="refused")
        self.assertIn("retried: the portal stored nothing", log)
        self.assertEqual([a["stored"] for a in portal.attempts], [False, True])

    def test_docx_reply_lost_reconciled_not_resubmitted(self):
        log, portal = self.trial(seed=8, suffix=".docx", failure="lost reply")
        self.assertIn("reconciled from Received, not resubmitted", log)
        self.assertEqual(len(portal.attempts), 1)
        self.assertTrue(
            {"kept the Word format", "saved without a format dialog"} & set(log), log
        )


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "dbus-daemon", "libreoffice"))
    and CHROMIUM
    and find_registryd(),
    "desktop tools, Chromium, LibreOffice or at-spi2-core unavailable",
)
class ChromiumMixedWorkflowTests(MixedWorkflowTests):
    """The mixed workflow with Chromium as the browser."""

    def launch(self, url):
        argv = [
            CHROMIUM,
            f"--user-data-dir={self.root / 'chromium'}",
            "--no-first-run",
            "--ozone-platform=wayland",
            "--disable-gpu",
            "--password-store=basic",
            "--force-renderer-accessibility",
        ]
        if os.geteuid() == 0:  # CI containers; never used for real profiles
            argv.append("--no-sandbox")
        app = core.request(self.session, "launch", argv=[*argv, url])
        found = core.wait(self.session, title="Contract portal", timeout=40)
        if (
            not found["satisfied"]
            and "No usable sandbox" in Path(app["logs"]).read_text()
        ):
            self.skipTest("Chromium sandbox unavailable in this environment")
        self.assertTrue(found["satisfied"], Path(app["logs"]).read_text()[-2000:])

    def trial(self, seed, suffix, failure=None):
        portal = Portal(seed, suffix, failure=failure)
        self.addCleanup(portal.close)
        self.launch(portal.url)
        driver = ChromiumDriver(self, portal)
        driver.run()
        time.sleep(LATE_REPLY_S + 1)  # An upload still in flight would land here.
        self.assertEqual(evaluate(portal), [], driver.log)
        return driver.log, portal


if __name__ == "__main__":
    unittest.main()
