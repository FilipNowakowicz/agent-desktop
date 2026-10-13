"""Positive control for the realistic web fixtures: a scripted solution, run in
headless Chromium against each generated page, must pass the task's check, and
a wrong one must not. Catches fixture bugs (such as an element id that a window
property shadows) before an agent run is spent on them. Without a browser:
pages must not carry their judge or the expected answer."""

import os
import shutil
import signal
import subprocess
import tempfile
import types
import unittest
from pathlib import Path

from test_runtime import CHROMIUM

from benchmarks import realistic
from benchmarks.tasks import Reports

FILL = (
    "const set=(e,v)=>{e.value=v;e.dispatchEvent(new Event('input',{bubbles:true}));"
    "e.dispatchEvent(new Event('change',{bubbles:true}))};"
)


def release_notes(answer, right):
    lines = "\\n".join(answer["highlights"][: 3 if right else 2])
    return (
        f"set(ver,{answer['version']!r});set(date,'2026-11-{answer['day']:02d}');"
        f"set(ch,'stable');set(hl,'{lines}');pub.click();yes.click();"
    )


def ticket_config(answer, right):
    return "set(c,'done');res.click();" if right else "res.click();"


def expense_claim(answer, right):
    return (
        "set(claimant,'Lin Okafor');document.querySelector('[value=contractor]')"
        ".click();set(company,'Brightwave Ltd');set(cat,'Travel');set(mode,'Taxi');"
        "set(from,'Oslo Airport (OSL)');set(to,'Grünerløkka, Oslo');"
        f"set(km,{answer['km']});set(date,'2026-09-{answer['day']:02d}');"
        f"set(amount,{answer['total']});set(cur,'NOK');set(vat,{answer['vat']});"
        f"set(paid,'card');set(last4,'{answer['card'] if right else '0000'}');"
        "ok.click();f.requestSubmit();"
    )


def inventory_cleanup(answer, right):
    # Through the page's own controls: pages, edit buttons, the dialog, and
    # "Stay signed in" when the expiry dialog appears after the second save.
    target = "'Norvik'" if right else "'Norvika'"
    return (
        "const todo=rows.map((r,i)=>i).filter(i=>rows[i].supplier==="
        f"{target});let k=0;function step(){{if(exp.style.display==='block')"
        "stay.click();if(k===todo.length)return;const i=todo[k++];page=Math.floor("
        "i/15);render();app.querySelector('button[data-i=\"'+i+'\"]').click();"
        "set(st,0);set(ss,'Discontinued');sv.click();setTimeout(step,1000)}step();"
    )


def attach_invoice(answer, right):
    name = answer if right else answer.replace("northwind", "northwind-draft")
    return (
        "set(s,'Northwind');const t=new DataTransfer();"
        f"t.items.add(new File(['%PDF'],{name!r}));file.files=t.files;send.click();"
    )


def fixed_config(context, right):
    """The terminal half of the ticket: the server section edited."""
    if right:
        context.config.write_text(
            context.original.replace(
                "port = 8080", f"port = {context.port}", 1
            ).replace("log_level = debug", "log_level = warning", 1)
        )


PREPARE = {"real-ticket-config": fixed_config}

SOLVERS = {
    "real-release-notes": (release_notes, "answer"),
    "real-ticket-config": (ticket_config, "port"),
    "real-expense-claim": (expense_claim, "answer"),
    "real-inventory-cleanup": (inventory_cleanup, "directory"),
    "real-attach-invoice": (attach_invoice, "expected"),
}


def snap_wrapper(path):
    """Ubuntu's chromium-browser is a script that installs a snap; it hangs
    on runners without snapd (the Lint job)."""
    real = os.path.realpath(path)
    try:
        return real.startswith("/snap/") or b"snap" in Path(real).read_bytes()[:4096]
    except OSError:
        return True


# With the desktop tests: the Lint job runs no browsers.
@unittest.skipUnless(
    shutil.which("labwc") and CHROMIUM and not snap_wrapper(CHROMIUM),
    "desktop runtime or a non-snap Chromium unavailable",
)
class RealisticFixtureTests(unittest.TestCase):
    def passes(self, task, right):
        directory = Path(self.temporary.name) / f"{task.name}-{right}"
        directory.mkdir()
        reports = Reports()
        self.addCleanup(reports.close)
        context = types.SimpleNamespace(
            directory=directory, reports=reports, report_url=reports.url
        )
        task.setup(context)
        PREPARE.get(task.name, lambda *args: None)(context, right)
        solve, field = SOLVERS[task.name]
        script = solve(getattr(context, field), right)
        page = directory / "page.html"
        page.write_text(
            page.read_text()
            + f"<script>setTimeout(()=>{{{FILL}{script}}},200)</script>"
        )
        if self.hung:
            self.skipTest("headless Chromium did not finish here")
        try:
            self.render(page, directory)
        except subprocess.TimeoutExpired:
            # Seen on CI runners; the positive control needs a working browser.
            self.hung = True
            self.skipTest("headless Chromium did not finish here")
        return task.check(context)

    def render(self, page, directory):
        # Its own process group: on a timeout every Chromium process stops
        # before the profile directory is removed.
        process = subprocess.Popen(
            [
                CHROMIUM,
                "--headless",
                "--disable-gpu",
                "--no-sandbox",
                f"--user-data-dir={directory / 'profile'}",
                "--virtual-time-budget=15000",
                "--dump-dom",
                page.as_uri(),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )
        try:
            return process.communicate(timeout=30)[0]
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise

    hung = False

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix="realistic-", ignore_cleanup_errors=True
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_solutions_complete_and_mistakes_do_not(self):
        for task in realistic.REALISTIC_TASKS:
            if task.name not in SOLVERS:
                continue
            with self.subTest(task=task.name):
                passed, detail = self.passes(task, True)
                self.assertTrue(passed, detail)
                passed, detail = self.passes(task, False)
                self.assertFalse(passed, detail)


class PageLeakTests(unittest.TestCase):
    """The agent can read a page's source and its window title: neither may
    say whether the task was done right."""

    def test_pages_carry_no_judge_or_answer(self):
        with tempfile.TemporaryDirectory() as temporary:
            for task in realistic.REALISTIC_TASKS:
                if task.name not in SOLVERS:
                    continue
                with self.subTest(task=task.name):
                    directory = Path(temporary) / task.name
                    directory.mkdir()
                    context = types.SimpleNamespace(
                        directory=directory, report_url="http://127.0.0.1:9/"
                    )
                    task.setup(context)
                    source = (directory / "page.html").read_text()
                    self.assertNotIn("done(", source)
                    self.assertNotIn("document.title", source)
                    answer = getattr(context, "answer", {})
                    for secret in (
                        answer.get("card"),
                        answer.get("version"),
                        getattr(context, "expected", None),
                    ):
                        if secret:
                            self.assertNotIn(secret, source)


if __name__ == "__main__":
    unittest.main()
