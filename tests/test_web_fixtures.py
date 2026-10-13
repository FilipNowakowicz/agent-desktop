"""Positive control for the benchmark web fixtures: a scripted solution, run in
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

from benchmarks.hard import HARD_TASKS
from benchmarks.realistic import REALISTIC_TASKS
from benchmarks.tasks import TASKS, Reports, Task

FILL = (
    "const set=(e,v)=>{e.value=v;e.dispatchEvent(new Event('input',{bubbles:true}));"
    "e.dispatchEvent(new Event('change',{bubbles:true}))};"
    "const enter=e=>e.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter'}));"
)


def release_notes(context, right):
    answer = context.answer
    lines = "\\n".join(answer["highlights"][: 3 if right else 2])
    return (
        f"set(ver,{answer['version']!r});set(date,'2026-11-{answer['day']:02d}');"
        f"set(ch,'stable');set(hl,'{lines}');pub.click();yes.click();"
    )


def ticket_config(context, right):
    return "set(c,'done');res.click();" if right else "res.click();"


def expense_claim(context, right):
    answer = context.answer
    return (
        "set(claimant,'Lin Okafor');document.querySelector('[value=contractor]')"
        ".click();set(company,'Brightwave Ltd');set(cat,'Travel');set(mode,'Taxi');"
        "set(from,'Oslo Airport (OSL)');set(to,'Grünerløkka, Oslo');"
        f"set(km,{answer['km']});set(date,'2026-09-{answer['day']:02d}');"
        f"set(amount,{answer['total']});set(cur,'NOK');set(vat,{answer['vat']});"
        f"set(paid,'card');set(last4,'{answer['card'] if right else '0000'}');"
        "ok.click();f.requestSubmit();"
    )


def inventory_cleanup(context, right):
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


def attach_invoice(context, right):
    name = context.expected
    if not right:
        name = name.replace("northwind", "northwind-draft")
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


def typed(field, button, value, wrong="WRONG"):
    """Type a value into a field and press a button."""
    return lambda context, right: (
        f"set({field},{(value(context) if right else wrong)!r});{button}.click();"
    )


def canvas_code_drag(context, right):
    # Inside the dashed target either way; only the code differs.
    code = context.secret if right else "WRONG"
    return (
        f"set(answer,{code!r});box.style.left='560px';box.style.top='320px';"
        "submit.click();"
    )


def form(context, right):
    size = "L" if right else "M"
    return (
        "set(fullname,'Grace Hopper');set(country,'Peru');document.querySelector("
        f"'[name=size][value={size}]').click();terms.click();f.requestSubmit();"
    )


def web_admin(context, right):
    row = 27 if right else 26  # mallory is user 27
    return (
        "set(u,'admin');set(p,'hunter2');s.click();nav.click();"
        f"app.querySelector('button[data-i=\"{row}\"]').click();"
        "set(r,'auditor');save.click();yes.click();"
    )


def interrupting_modal(context, right):
    fill = "set(street,'12 Harbour Road');set(city,'Bergen');set(zip,'5003');"
    return fill + ("f.requestSubmit();" if right else "out.click();")


def reorder(context, right):
    order = "['One','Two','Three','Four']" if right else "['Two','One','Three','Four']"
    return (
        f"{order}.forEach(t=>list.append([...list.children].find("
        "l=>l.textContent===t)));fin.click();"
    )


PREPARE = {"real-ticket-config": fixed_config}

SOLVERS = {
    "real-release-notes": release_notes,
    "real-ticket-config": ticket_config,
    "real-expense-claim": expense_claim,
    "real-inventory-cleanup": inventory_cleanup,
    "real-attach-invoice": attach_invoice,
    "chromium-canvas-code-drag": canvas_code_drag,
    "chromium-form": form,
    "chromium-scroll": lambda context, right: "finish.click();" if right else "",
    "chromium-confirm-dialog": lambda context, right: (
        f"window.confirm=()=>{str(right).lower()};del.click();"
    ),
    "chromium-second-tab": typed("answer", "go", lambda c: c.secret),
    "chromium-slider": lambda context, right: (
        f"set(v,{context.target if right else context.target + 1});save.click();"
    ),
    "chromium-context-menu": lambda context, right: (
        f"document.querySelectorAll('.i')[{1 if right else 2}].click();"
    ),
    "chromium-double-click-edit": lambda context, right: (
        f"bob.textContent='{47 if right else 48}';enter(bob);"
    ),
    "chromium-keyboard-shortcut": lambda context, right: (
        f"q.value='{'private desktop' if right else 'public'}';enter(q);"
    ),
    "chromium-drag-reorder": reorder,
    "hard-terminal-to-browser": typed("t", "go", lambda c: c.secret),
    "hard-web-admin": web_admin,
    "hard-interrupting-modal": interrupting_modal,
    "hard-slow-load": typed("v", "red", lambda c: c.secret),
    "hard-chart-reading": typed("a", "go", lambda c: c.answer, wrong="Never"),
    "hard-focus-steal": typed("t", "send", lambda c: c.text, wrong="Hello"),
    "hard-validation-fix": lambda context, right: (
        f"set(q,{24 if right else 20});o.click();"
    ),
}

# Checks that also look at other applications: only the page part is run here.
PAGE_ONLY = {"hard-focus-steal"}

# Answers that must not be in the page source. Some tasks' answers are the
# page's own content (a code drawn on a canvas, chart values, a voucher shown
# after a delay) and stay in the source, as in any web app.
SECRETS = {
    "real-release-notes": lambda c: [c.answer["version"]],
    "real-expense-claim": lambda c: [c.answer["card"]],
    "real-attach-invoice": lambda c: [c.expected],
    "chromium-second-tab": lambda c: [c.secret],
    "hard-terminal-to-browser": lambda c: [c.secret],
}

WEB_TASKS = [
    task for task in TASKS + HARD_TASKS + REALISTIC_TASKS if task.name in SOLVERS
]


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
class WebFixtureTests(unittest.TestCase):
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
        script = SOLVERS[task.name](context, right)
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
        check = Task.check if task.name in PAGE_ONLY else type(task).check
        return check(task, context)

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
            prefix="web-fixture-", ignore_cleanup_errors=True
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_solutions_complete_and_mistakes_do_not(self):
        for task in WEB_TASKS:
            with self.subTest(task=task.name):
                passed, detail = self.passes(task, True)
                self.assertTrue(passed, detail)
                passed, detail = self.passes(task, False)
                self.assertFalse(passed, detail)


class PageLeakTests(unittest.TestCase):
    """The agent can read a page's source and its window title: neither may
    say whether the task was done right."""

    def test_every_web_task_has_a_solver(self):
        pages = []
        with tempfile.TemporaryDirectory() as temporary:
            for task in TASKS + HARD_TASKS + REALISTIC_TASKS:
                directory = Path(temporary) / task.name
                directory.mkdir()
                context = types.SimpleNamespace(directory=directory, home=temporary)
                try:
                    task.setup(context)
                except (AttributeError, OSError):
                    continue  # needs a live session; not a web page
                if (directory / "page.html").exists():
                    pages.append(task.name)
        self.assertEqual(sorted(pages), sorted(t.name for t in WEB_TASKS))

    def test_pages_carry_no_judge_or_answer(self):
        with tempfile.TemporaryDirectory() as temporary:
            for task in WEB_TASKS:
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
                    for secret in SECRETS.get(task.name, lambda c: [])(context):
                        self.assertNotIn(secret, source)


if __name__ == "__main__":
    unittest.main()
