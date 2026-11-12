"""F2 browser dataset edit: the inventory service, its page and its evaluator.

Shared by the deterministic driver (tests/test_dataset_workflow.py) and the
agent-driven benchmark task below. The service owns the records; the page shows
only what it is given; the evaluator reads only the service.
"""

import json
import os
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .tasks import Task, browser_command

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


class DatasetEdit(Task):
    """An agent does the dataset edit the deterministic driver does.

    Records span four pages, two products share a name, one supplier name
    ("Norvika") nearly matches the one to retire, and a session-expiry modal
    opens after a save. The check reads only the service.
    """

    name = "f2-dataset-edit"

    @property
    def requires(self):
        """The browser browser_command() will launch."""
        firefox = os.environ.get("AGENT_DESKTOP_BENCH_BROWSER") == "firefox"
        return ("firefox",) if firefox else ("chromium",)

    def __init__(self, seed=None, start_page=None, expire_after=None):
        self.seed, self.start_page, self.expire_after = seed, start_page, expire_after

    def setup(self, context):
        # Without a fixed seed, follow the harness's --seed so a run can be repeated.
        chooser = random.Random(self.seed if self.seed is not None else random.random())
        seed = self.seed if self.seed is not None else chooser.randrange(10**6)
        start = self.start_page or chooser.randint(1, 4)
        expire = self.expire_after or chooser.randint(1, 3)
        context.inventory = Inventory(seed, expire_after=expire, expire_ms=600)
        context.closers = [*getattr(context, "closers", []), context.inventory.close]
        context.trial = {"seed": seed, "start_page": start, "expire_after": expire}
        prompt = (
            "The browser shows an inventory list that spans several pages. The "
            f"supplier {GONE} has closed. For every product whose supplier is "
            f"exactly {GONE}, set its stock to 0 and its status to Discontinued, "
            "and save each one. Change nothing else. Say when you are done."
        )
        return browser_command(context, f"{context.inventory.url}?page={start}"), prompt

    def check(self, context):
        inventory = context.inventory
        time.sleep(1)  # A save still in flight would show up here.
        problems = evaluate(
            inventory.initial, inventory.records, inventory.saves, inventory.signed_out
        )
        detail = {**context.trial, "saves": len(inventory.saves), "problems": problems}
        return not problems, detail


F2_TASKS = [DatasetEdit()]
