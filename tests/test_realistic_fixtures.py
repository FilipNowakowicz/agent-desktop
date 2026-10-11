"""Positive control for the realistic web fixtures: a scripted solution, run in
headless Chromium against each generated page, must complete the task, and a
wrong one must not. Catches fixture bugs (such as an element id that a window
property shadows) before an agent run is spent on them."""

import re
import shutil
import subprocess
import tempfile
import types
import unittest
from pathlib import Path

from test_runtime import CHROMIUM

from benchmarks import realistic

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


SOLVERS = {
    "real-release-notes": (release_notes, "answer"),
    "real-ticket-config": (ticket_config, "port"),
    "real-expense-claim": (expense_claim, "answer"),
    "real-inventory-cleanup": (inventory_cleanup, "directory"),
    "real-attach-invoice": (attach_invoice, "expected"),
}


@unittest.skipUnless(CHROMIUM and shutil.which(CHROMIUM), "Chromium unavailable")
class RealisticFixtureTests(unittest.TestCase):
    def title_after(self, task, right):
        directory = Path(self.temporary.name) / f"{task.name}-{right}"
        directory.mkdir()
        context = types.SimpleNamespace(directory=directory)
        task.setup(context)
        solve, field = SOLVERS[task.name]
        script = solve(getattr(context, field), right)
        page = directory / "page.html"
        page.write_text(
            page.read_text()
            + f"<script>setTimeout(()=>{{{FILL}{script}}},200)</script>"
        )
        output = subprocess.run(
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
            capture_output=True,
            text=True,
            timeout=120,
        ).stdout
        found = re.search(r"<title>(.*?)</title>", output)
        return found.group(1) if found else output[-300:]

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="realistic-")

    def tearDown(self):
        self.temporary.cleanup()

    def test_solutions_complete_and_mistakes_do_not(self):
        for task in realistic.REALISTIC_TASKS:
            if task.name not in SOLVERS:
                continue
            with self.subTest(task=task.name):
                self.assertEqual(self.title_after(task, True), "Task - complete")
                self.assertNotEqual(self.title_after(task, False), "Task - complete")


if __name__ == "__main__":
    unittest.main()
