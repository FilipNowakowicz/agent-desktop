"""F2: a browser dataset edit, end to end (real private sessions).

A loopback inventory service owns the records and serves one page of them at a
time; the browser page only shows what it is given. A deterministic driver
traverses the pages through the DOM bridge, edits the intended records by ID and
handles a session-expiry modal, while the helper running its edits is killed at
chosen points. The evaluator never looks at the page: it compares the
service's final records with the initial snapshot by ID and counts the saves the
service received, so a missed target, a changed bystander, a lost or added row
or a duplicate submission each fail the trial.
"""

import json
import random
import shutil
import signal
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import test_browser
from test_runtime import wait_for

from agent_desktop import core, operations
from agent_desktop.worker import signal_process

PER_PAGE = 12
SUPPLIERS = ["Acme", "Borealis", "Kestrel", "Norvika", "Tamsin"]
GONE = "Norvik"

PAGE = """<!doctype html><meta charset="utf-8"><title>Inventory</title>
<style>#dlg,#exp{display:none;position:fixed;inset:0;background:#0006}
#dlg>div,#exp>div{background:#fff;margin:90px auto;width:360px;padding:16px}</style>
<h2>Inventory</h2><div id="app">Loading</div>
<div id="dlg"><div><h3 id="dt"></h3><p><label>Stock <input id="st" type="number">
</label></p><p><label>Status <select id="ss"><option>Active</option>
<option>Discontinued</option><option>On hold</option></select></label></p>
<p><button id="sv">Save</button> <button id="cx">Cancel</button></p></div></div>
<div id="exp"><div><p>Your session expires in 60 seconds.</p>
<p><button id="stay">Stay signed in</button> <button id="out">Sign out</button></p>
</div></div>
<script>
let page = +(new URLSearchParams(location.search).get("page") || 1), pages = 1;
let rows = [], cur = null;
async function load() {
  const r = await fetch("/records?page=" + page);
  const d = await r.json(); rows = d.rows; pages = d.pages; render();
}
function render() {
  app.innerHTML = "<table border=1 cellpadding=4><tr><th>SKU<th>Name<th>Supplier"
    + "<th>Stock<th>Status<th></tr>" + rows.map((r) => "<tr><td>" + r.sku + "<td>"
    + r.name + "<td>" + r.supplier + "<td>" + r.stock + "<td>" + r.status
    + "<td><button data-sku='" + r.sku + "'>Edit</button>").join("")
    + "</table><p><button id=prev>Previous</button> <span id=where>Page " + page
    + " of " + pages + "</span> <button id=next>Next</button></p>";
  app.querySelectorAll("button[data-sku]").forEach((b) => b.onclick = () => {
    cur = rows.find((r) => r.sku === b.dataset.sku);
    dt.textContent = "Edit " + cur.name + " (" + cur.sku + ")";
    st.value = cur.stock; ss.value = cur.status; sv.disabled = false;
    sv.textContent = "Save"; dlg.style.display = "block";
  });
  prev.onclick = () => { if (page > 1) { page--; load(); } };
  next.onclick = () => { if (page < pages) { page++; load(); } };
}
cx.onclick = () => { dlg.style.display = "none"; };
sv.onclick = async () => {
  sv.disabled = true; sv.textContent = "Saving";
  const r = await fetch("/save", {method: "POST", body: JSON.stringify(
    {sku: cur.sku, stock: +st.value, status: ss.value})});
  const d = await r.json();
  dlg.style.display = "none";
  if (d.expire !== undefined && d.expire >= 0) setTimeout(() => { exp.style.display = "block"; }, d.expire);
  load();
};
stay.onclick = () => { exp.style.display = "none"; };
out.onclick = () => { fetch("/signout", {method: "POST"}); document.body.innerHTML = "<h2>Signed out</h2>"; };
load();
</script>
"""


class Inventory:
    """The authoritative records, behind a loopback HTTP service."""

    def __init__(
        self, seed, expire_after=2, expire_ms=800, save_delay=0.0, slow_save=None
    ):
        chooser = random.Random(seed)
        self.records = {}
        names = [f"Item {i + 1:02d}" for i in range(44)]
        # Duplicate labels: two different products share a name.
        names[chooser.randrange(1, 44)] = names[0]
        for name in names:
            sku = f"SKU-{chooser.randrange(16**4):04X}"
            while sku in self.records:
                sku = f"SKU-{chooser.randrange(16**4):04X}"
            self.records[sku] = {
                "sku": sku,
                "name": name,
                "supplier": chooser.choice(SUPPLIERS),
                "stock": chooser.randint(1, 90),
                "status": "Active",
            }
        for sku in chooser.sample(sorted(self.records), 4):
            self.records[sku]["supplier"] = GONE
        self.initial = json.loads(json.dumps(self.records))
        self.saves = []
        self.signed_out = False
        self.expire_after = expire_after
        self.expire_ms = expire_ms
        self.save_delay = save_delay
        self.slow_save = slow_save  # Index of one save that takes much longer.
        self.lock = threading.Lock()
        inventory = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                url = urlparse(self.path)
                if url.path == "/":
                    return self.reply(PAGE.encode(), "text/html")
                if url.path == "/records":
                    number = int(parse_qs(url.query).get("page", ["1"])[0])
                    return self.reply(inventory.page(number))
                self.send_error(404)

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if self.path == "/signout":
                    inventory.signed_out = True
                    return self.reply({})
                if self.path != "/save":
                    return self.send_error(404)
                return self.reply(inventory.save(json.loads(body)))

            def reply(self, data, kind="application/json"):
                body = data if isinstance(data, bytes) else json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *arguments):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/"

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def page(self, number):
        with self.lock:
            ordered = [self.records[sku] for sku in sorted(self.records)]
        pages = -(-len(ordered) // PER_PAGE)
        number = min(max(number, 1), pages)
        start = (number - 1) * PER_PAGE
        return {"rows": ordered[start : start + PER_PAGE], "pages": pages}

    def save(self, change):
        with self.lock:
            index = len(self.saves)
            self.saves.append(change)
        delay = 2.5 if index == self.slow_save else self.save_delay
        time.sleep(delay)
        with self.lock:
            record = self.records[change["sku"]]
            record["stock"] = change["stock"]
            record["status"] = change["status"]
        expire = self.expire_ms if len(self.saves) == self.expire_after else -1
        return {"ok": True, "expire": expire}


def targets(initial):
    return {sku for sku, r in initial.items() if r["supplier"] == GONE}


def evaluate(initial, final, saves, signed_out=False):
    """Problems with an outcome, judged from the service's records only."""
    problems = []
    if signed_out:
        problems.append("signed out")
    wanted = targets(initial)
    if set(final) != set(initial):
        missing = sorted(set(initial) - set(final))
        extra = sorted(set(final) - set(initial))
        problems.append(f"membership changed: missing {missing}, extra {extra}")
    for sku, before in initial.items():
        after = final.get(sku)
        if after is None:
            continue
        expected = dict(before)
        if sku in wanted:
            expected.update(stock=0, status="Discontinued")
        changed = sorted(k for k in expected if after.get(k) != expected[k])
        if changed:
            role = "target" if sku in wanted else "bystander"
            problems.append(f"{role} {sku} wrong in {changed}")
    counts = {}
    for change in saves:
        counts[change["sku"]] = counts.get(change["sku"], 0) + 1
    for sku, count in sorted(counts.items()):
        if sku not in wanted:
            problems.append(f"bystander {sku} was submitted {count} times")
        elif count > 1:
            problems.append(f"target {sku} was submitted {count} times")
    return problems


class EvaluatorTests(unittest.TestCase):
    """The checker itself, against outcomes known to be wrong."""

    def setUp(self):
        self.inventory = Inventory(seed=7)
        self.addCleanup(self.inventory.close)
        self.initial = self.inventory.initial
        self.wanted = sorted(targets(self.initial))
        self.final = json.loads(json.dumps(self.initial))
        self.saves = []
        for sku in self.wanted:
            self.final[sku].update(stock=0, status="Discontinued")
            self.saves.append({"sku": sku, "stock": 0, "status": "Discontinued"})

    def problems(self, final=None, saves=None, signed_out=False):
        return evaluate(
            self.initial,
            self.final if final is None else final,
            self.saves if saves is None else saves,
            signed_out,
        )

    def test_correct_outcome_passes(self):
        self.assertEqual(len(self.wanted), 4)
        self.assertEqual(self.problems(), [])

    def test_wrong_outcomes_fail(self):
        bystander = next(s for s in self.initial if s not in self.wanted)
        near = next(
            (s for s, r in self.initial.items() if r["supplier"] == "Norvika"), None
        )
        cases = {}
        missed = json.loads(json.dumps(self.final))
        missed[self.wanted[0]] = dict(self.initial[self.wanted[0]])
        cases["missed target"] = (missed, self.saves[1:])
        half = json.loads(json.dumps(self.final))
        half[self.wanted[1]]["stock"] = self.initial[self.wanted[1]]["stock"]
        cases["half-edited target"] = (half, None)
        touched = json.loads(json.dumps(self.final))
        touched[bystander]["status"] = "Discontinued"
        cases["changed bystander"] = (touched, None)
        renamed = json.loads(json.dumps(self.final))
        renamed[bystander]["name"] += " (old)"
        cases["renamed bystander"] = (renamed, None)
        lost = json.loads(json.dumps(self.final))
        del lost[bystander]
        cases["lost row"] = (lost, None)
        added = json.loads(json.dumps(self.final))
        added["SKU-NEW1"] = dict(self.initial[bystander], sku="SKU-NEW1")
        cases["added row"] = (added, None)
        cases["duplicate submission"] = (None, self.saves + self.saves[:1])
        cases["bystander submitted unchanged"] = (
            None,
            self.saves + [dict(self.initial[bystander])],
        )
        if near:
            fuzzy = json.loads(json.dumps(self.final))
            fuzzy[near].update(stock=0, status="Discontinued")
            cases["near-duplicate supplier edited"] = (fuzzy, None)
        for name, (final, saves) in cases.items():
            with self.subTest(name):
                self.assertTrue(self.problems(final, saves), name)
        self.assertEqual(self.problems(signed_out=True), ["signed out"])

    def test_answers_stay_out_of_the_page(self):
        self.assertNotIn(GONE, PAGE)
        for sku in self.initial:
            self.assertNotIn(sku, PAGE)


class Driver:
    """A deterministic procedure that sees only what the page shows."""

    def __init__(self, test, inventory, kills):
        self.test = test
        self.inventory = inventory
        self.kills = dict(kills)  # Target index -> "before save" or "after save".
        self.session = test.session
        self.log = []

    def browser(self, action, **arguments):
        return self.test.browser(action, **arguments)

    def visible_rows(self):
        text = self.browser("text", selector="#app table")["text"]
        rows = []
        for line in text.splitlines()[1:]:
            cells = [c.strip() for c in line.split("\t")]
            if len(cells) >= 5:
                rows.append(
                    {
                        "sku": cells[0],
                        "supplier": cells[2],
                        "stock": cells[3],
                        "status": cells[4],
                    }
                )
        return rows

    def where(self):
        text = self.browser("text", selector="#where")["text"]
        number, pages = text.removeprefix("Page ").split(" of ")
        return int(number), int(pages)

    def settle(self):
        """Dismiss the expiry modal or a leftover dialog, never by signing out."""
        if self.browser("find", selector="#stay")["count"]:
            self.browser("click", selector="#stay")
            self.log.append("stayed signed in")
        if self.browser("find", selector="#cx")["count"]:
            self.browser("click", selector="#cx")
            self.log.append("cancelled a leftover dialog")

    def go_to(self, number):
        for _ in range(20):
            self.settle()
            current, _ = self.where()
            if current == number:
                return
            try:
                self.browser("click", selector="#next" if current < number else "#prev")
            except core.DesktopError as error:
                # A modal that appeared after settle() covers the button: the
                # click was refused and nothing was sent, so settle and retry.
                if "covered" not in str(error):
                    raise
                self.log.append("navigation refused: covered")
                continue
            wait_for(lambda was=current: self.where()[0] != was, timeout=10)
        raise AssertionError(f"could not reach page {number}")

    def survey(self):
        """Page by page from the first: the target IDs and the page of each."""
        self.go_to(1)
        found = {}
        _, pages = self.where()
        for number in range(1, pages + 1):
            self.go_to(number)
            for row in self.visible_rows():
                if row["supplier"] == GONE:
                    found[row["sku"]] = number
        return found

    def row(self, sku):
        return next((r for r in self.visible_rows() if r["sku"] == sku), None)

    def done(self, sku):
        row = self.row(sku)
        return row and (row["stock"], row["status"]) == ("0", "Discontinued")

    def edit_steps(self, sku, hold=False):
        steps = [
            {"action": "click", "selector": f'button[data-sku="{sku}"]'},
            {"action": "fill", "selector": "#st", "value": "0"},
            {"action": "select", "selector": "#ss", "value": "Discontinued"},
            {"action": "click", "selector": "#sv"},
            {"action": "wait", "selector": "#dlg", "gone": True, "timeout": 15},
        ]
        if hold:
            # Injection point: a pause with the dialog filled but not saved.
            steps.insert(3, {"action": "wait", "seconds": 10})
        return steps

    def status(self, ident):
        return operations.status(self.session, ident)

    def run_edit(self, sku, kill=None):
        steps = self.edit_steps(sku, hold=kill == "before save")
        save = next(i for i, s in enumerate(steps) if s.get("selector") == "#sv")
        ident = operations.start(self.session, steps, kind="browser")["operation_id"]
        if kill:
            index, states = (
                (save - 1, ("dispatching",))
                if kill == "before save"
                else (save, ("acknowledged", "observed"))
            )
            running = wait_for(
                lambda: (
                    r
                    if (r := self.status(ident))["steps"][index]["dispatch_state"]
                    in states
                    or r["state"] in operations.TERMINAL
                    else None
                ),
                timeout=30,
            )
            if running["state"] not in operations.TERMINAL:
                signal_process(running["pid"], running["process_start"], signal.SIGKILL)
                self.log.append(f"killed {sku} {kill}")
        result = wait_for(
            lambda: (
                r if (r := self.status(ident))["state"] in operations.TERMINAL else None
            ),
            timeout=60,
        )
        submitted = result["steps"][save]["dispatch_state"] != "pending"
        return result, submitted

    def landed(self, sku, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.settle()
            if self.done(sku):
                return True
            time.sleep(0.5)
        return False

    def edit(self, index, sku, number):
        for attempt in range(3):
            self.go_to(number)
            if self.done(sku):
                return
            kill = self.kills.pop(index, None) if attempt == 0 else None
            result, submitted = self.run_edit(sku, kill)
            self.log.append(f"{sku} attempt {attempt + 1}: {result['state']}")
            if submitted:
                # The save may still be in flight, or the page still reloading
                # after it: reconcile from the page before any retry, and never
                # submit again while it might land.
                if self.landed(sku, timeout=15):
                    if result["state"] != "completed":
                        self.log.append(
                            f"{sku} reconciled from the page, not resubmitted"
                        )
                    return
            else:
                self.log.append(f"{sku} retried: nothing was submitted")
        raise AssertionError(f"{sku} not edited: {self.log}")

    def run(self):
        found = self.survey()
        for index, (sku, number) in enumerate(sorted(found.items())):
            self.edit(index, sku, number)
        self.settle()
        return found


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "dbus-daemon", "firefox")),
    "desktop tools or Firefox unavailable",
)
class DatasetWorkflowTests(unittest.TestCase):
    setUp = test_browser.BrowserTests.setUp
    tearDown = test_browser.BrowserTests.tearDown
    browser = test_browser.BrowserTests.browser

    def trial(self, seed, start_page, kills, **service):
        inventory = Inventory(seed, **service)
        self.addCleanup(inventory.close)
        self.browser("start", url=f"{inventory.url}?page={start_page}")
        self.assertTrue(
            self.browser("wait", selector="#where", timeout=20)["satisfied"]
        )
        driver = Driver(self, inventory, kills)
        found = driver.run()
        # The driver's survey came from the page; the check comes from the service.
        self.assertEqual(set(found), targets(inventory.initial))
        time.sleep(1)  # A save still in flight would show up here.
        problems = evaluate(
            inventory.initial,
            inventory.records,
            inventory.saves,
            inventory.signed_out,
        )
        self.assertEqual(problems, [], driver.log)
        return driver.log

    def test_clean_run_from_a_later_page_with_the_modal(self):
        # The modal opens as the second save returns, so it covers the next edit.
        log = self.trial(seed=11, start_page=3, kills={}, expire_after=2, expire_ms=0)
        self.assertIn("stayed signed in", log)

    def test_helper_killed_while_a_slow_save_is_in_flight(self):
        # The save is submitted, the helper dies before the reply, and the
        # service applies it later: the driver must reconcile, not resubmit.
        log = self.trial(
            seed=23, start_page=1, kills={1: "after save"}, expire_after=3, slow_save=1
        )
        self.assertTrue(any(line.endswith("after save") for line in log), log)
        self.assertTrue(any("not resubmitted" in line for line in log), log)

    def test_helper_killed_before_saving_and_modal_over_the_page(self):
        # First held out (it passed on its first run), now a regular trial:
        # killed with the dialog filled but not saved,
        # a later start page and the modal after the first save.
        log = self.trial(
            seed=37,
            start_page=4,
            kills={0: "before save", 2: "after save"},
            expire_after=1,
            save_delay=0.4,
        )
        self.assertTrue(any(line.endswith("before save") for line in log), log)
        self.assertTrue(any("nothing was submitted" in line for line in log), log)


if __name__ == "__main__":
    unittest.main()
