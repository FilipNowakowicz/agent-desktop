"""Tier-separating suite (2026-11): longer multi-application tasks.

The realistic suite saturated (54/54 across three model tiers). These six
tasks add what it lacked: more state to track, distractors that give a
plausible wrong answer, rules found in notes, and an interruption in the
middle (a session expiry that wipes the form, a policy modal, a data file that
changes after the second save). Checks read files and the state the page
reports, never the agent's reply. Protocol:
docs/research/2026-11-06-evidence-protocol.md.
"""

import hashlib
import random
import re
import threading
import time
from pathlib import Path

from .atlas import ini_value
from .tasks import Task, chromium, code, page


def editor(path):
    return ["mousepad", "--disable-server", str(path)]


def terminal(directory):
    return ["foot", "--config=/dev/null", f"--working-directory={directory}", "sh"]


# --- 1. incident triage ------------------------------------------------------

SERVICES = ["checkout", "checkout-api", "payments", "search", "inventory"]


def clock(second):
    return f"{second // 3600:02d}:{second % 3600 // 60:02d}:{second % 60:02d}"


class IncidentTriage(Task):
    """Compute from a big log with an exclusion rule found in a note."""

    name = "tier-incident-triage"
    requires = ("chromium", "mousepad", "foot")

    def setup(self, context):
        target, runner, decoy = random.sample(SERVICES, 3)
        base = 14 * 3600
        used_ms, used_sec, rows = set(), set(), []

        def ms(low=150, high=2400):
            while True:
                value = random.randint(low, high)
                if value not in used_ms:
                    used_ms.add(value)
                    return value

        def second(lo, hi):
            while True:
                value = random.randint(lo, hi)
                if value not in used_sec:
                    used_sec.add(value)
                    return value

        def add(svc, status, when, took, ua="web"):
            rows.append((when, svc, status, took, f"r-{code(6).lower()}", ua))

        inside = (base, base + 3599)
        count = random.randint(11, 14)
        legit = []
        for _ in range(count):
            legit.append(second(base + 60, base + 3500))
        first = min(legit)
        slow = ms(900, 1500)
        slowest_at = random.choice(legit)
        for when in legit:
            add(target, random.choice([500, 502, 503, 504]),
                when, slow if when == slowest_at else ms(150, slow - 1))
        context.answer = {
            "service": target,
            "count": count,
            "first": clock(first),
            "slowest": next(r[4] for r in rows if r[0] == slowest_at and r[1] == target),
        }
        # Decoys: load-test errors on the target (earlier and slower), a
        # service with more load-test errors than the target has real ones,
        # and a runner-up whose errors outside the window would beat it.
        add(target, 503, base + 5, ms(2500, 3000), "loadtest")
        add(target, 500, base + 11, ms(2500, 3000), "loadtest")
        for _ in range(count + 6):
            add(decoy, 500, second(*inside), ms(), "loadtest")
        for _ in range(3):
            add(decoy, 502, second(*inside), ms())
        for _ in range(count - 3):
            add(runner, random.choice([500, 503]), second(*inside), ms(150, 800))
        for _ in range(8):
            add(runner, 500, second(base - 3000, base - 30), ms(150, 800))
        add(target, 500, second(base - 1500, base - 100), ms(3000, 3500))
        add(target, 502, second(base + 3650, base + 5000), ms(3000, 3500))
        for _ in range(230):
            svc = random.choice(SERVICES)
            status = random.choice([200, 200, 200, 201, 301, 404, 429])
            when = second(base - 3000, base + 5000) if random.random() < 0.7 else second(*inside)
            add(svc, status, when, random.randint(10, 400), random.choice(["web", "web", "app", "loadtest"]))
        rows.sort()
        folder = context.directory / "logs"
        folder.mkdir()
        (folder / "access.log").write_text(
            "".join(
                f"2026-11-03T{clock(w)}Z svc={s} status={st} ms={m} req={r} ua={u}\n"
                for w, s, st, m, r, u in rows
            )
        )
        notes = context.directory / "incident-notes.txt"
        notes.write_text(
            f"INC-{random.randint(2100, 2999)}: customers report failing requests in the web shop.\n\n"
            "Look at 2026-11-03, 14:00:00 to 14:59:59 UTC only.\n"
            "A request is an error when its status is 500 or higher.\n"
            "Our own load tests (user agent loadtest) ran during the incident;\n"
            "they are not customer impact, so leave them out.\n\n"
            "The report names the service with the most errors, how many, the\n"
            "time of its first error and the id (req=) of its slowest failing request.\n"
        )
        options = "".join(f"<option>{s}</option>" for s in SERVICES)
        page_html = page(
            "<h2>Incident report</h2><p>Most affected service <select id=svc>"
            f"<option value=''>Choose</option>{options}</select></p>"
            "<p>Number of errors <input id=n type=number></p>"
            "<p>First error (UTC, HH:MM:SS) <input id=first placeholder='14:00:00'></p>"
            "<p>Slowest failing request id <input id=req></p>"
            "<button id=go>File report</button><p id=err style='color:#b00'></p>",
            "go.onclick=()=>{if(!svc.value||!n.value||!first.value||!req.value)"
            "{err.textContent='Fill in every field.';return}"
            "const st={service:svc.value,count:+n.value,first:first.value,req:req.value};"
            "document.body.innerHTML='<h2>Report filed</h2>';report(st)};",
        )
        prompt = (
            "Prepare the incident report in the browser. The incident notes are "
            "open in the text editor and the access log is in the terminal's "
            "directory."
        )
        return [editor(notes), terminal(folder), chromium(context, page_html)], prompt

    def check(self, context):
        state = context.reports.last()
        if state is None:
            return False, "not filed"
        a = context.answer
        first = state["first"].strip().removesuffix("Z").removesuffix(" UTC").strip()
        ok = (
            state["service"] == a["service"]
            and state["count"] == a["count"]
            and first == a["first"]
            and state["req"].strip().lower() == a["slowest"]
        )
        return ok, {"reported": state, "expected": a}


# --- 2. bulk entry with a session expiry ------------------------------------

VENDORS = ["Nordlys Taxi", "Fjord Catering", "Bergen Print", "Oslo Parking",
           "Aker Office Supply", "Vest Hotel", "Kysten Train", "Arctic Coffee", "Maple Books"]


class BulkEntry(Task):
    """Enter unfiled lines only; the session expires after the fourth save."""

    name = "tier-bulk-entry"
    requires = ("chromium", "mousepad")

    def setup(self, context):
        ids = random.sample(range(1000, 9999), 12)
        lines = []
        for index in range(9):
            lines.append({
                "id": f"EXP-{ids[index]}",
                "date": f"2026-10-{random.randint(1, 28):02d}",
                "vendor": VENDORS[index],
                "amount": random.randint(120, 4800),
            })
        filed = random.sample(range(9), 3)
        ledger = [dict(lines[i], amount=lines[i]["amount"]) for i in filed]
        ledger += [
            {"id": f"EXP-{ids[9 + k]}", "date": "2026-09-30",
             "vendor": "Older Vendor", "amount": 100 + k}
            for k in range(3)
        ]
        random.shuffle(ledger)
        password = code(8).lower()
        context.answer = {
            "new": [l for i, l in enumerate(lines) if i not in filed],
            "ledger": ledger,
        }
        note = context.directory / "october-expenses.txt"
        note.write_text(
            "Expenses to enter (amounts in NOK)\n"
            f"Ledger login if it asks: finance / {password}\n\n"
            + "".join(
                f"{l['id']} | {l['date']} | {l['vendor']} | {l['amount']}\n" for l in lines
            )
        )
        page_html = page(
            "<h2>Expense ledger</h2><div id=main><table border=1 cellpadding=5 id=t></table>"
            "<h3>Add entry</h3><p>ID <input id=eid> Date (YYYY-MM-DD) <input id=edate> "
            "Vendor <input id=ev> Amount <input id=ea size=6> <button id=add>Add</button></p>"
            "<p id=err style='color:#b00'></p></div>"
            "<div id=login hidden><h3>Session expired</h3><p>Sign in again to continue.</p>"
            "<p>User <input id=u> Password <input id=p type=password> "
            "<button id=si>Sign in</button></p><p id=lerr style='color:#b00'></p></div>",
            f"let rows={ledger!r};let adds=0,expired=false;const PW={password!r};"
            "function draw(){t.innerHTML='<tr><th>ID<th>Date<th>Vendor<th>Amount</tr>'+"
            "rows.map(r=>'<tr><td>'+r.id+'<td>'+r.date+'<td>'+r.vendor+'<td>'+r.amount).join('')}"
            "draw();report({rows});"
            "add.onclick=()=>{if(expired){err.textContent='Session expired. Sign in again.';return}if(!eid.value||!edate.value||!ev.value||!ea.value.trim())"
            "{err.textContent='Fill in every field.';return}"
            "if(rows.some(r=>r.id===eid.value.trim())){err.textContent='That ID is already in the ledger.';return}"
            "rows.push({id:eid.value.trim(),date:edate.value.trim(),vendor:ev.value.trim(),"
            "amount:+ea.value});err.textContent='';draw();report({rows});adds++;"
            "[eid,edate,ev,ea].forEach(e=>e.value='');"
            "if(adds===4)setTimeout(()=>{expired=true;main.hidden=true;login.hidden=false;[eid,edate,ev,ea].forEach(e=>e.value='')},1200)};"
            "si.onclick=()=>{if(u.value==='finance'&&p.value===PW){login.hidden=true;expired=false;"
            "main.hidden=false;lerr.textContent=''}else lerr.textContent='Wrong user or password.'};",
        )
        prompt = (
            "Enter this month's expenses from the text editor into the expense "
            "ledger in the browser. Lines that are already in the ledger must not "
            "be entered again."
        )
        return [editor(note), chromium(context, page_html)], prompt

    def check(self, context):
        state = context.reports.last()
        if state is None:
            return False, "nothing reported"
        rows = state["rows"]
        want = {r["id"]: r for r in context.answer["ledger"] + context.answer["new"]}
        got = {r["id"]: r for r in rows}
        key = lambda r: (r["id"], r["date"], r["vendor"], r["amount"])  # noqa: E731
        ok = (
            len(rows) == len(got) == len(want)
            and all(i in got and key(got[i]) == key(want[i]) for i in want)
        )
        return ok, {"rows": len(rows), "expected": len(want)}


# --- 3. configuration rollout with a rollback note ---------------------------

class ConfigRollout(Task):
    """Edit staging only, keep prod, write the old values into a note."""

    name = "tier-config-rollout"
    requires = ("chromium", "mousepad", "foot")

    def setup(self, context):
        root = context.directory / "deploy"
        context.root = root
        names = ["orders", "billing", "catalog"]
        low = random.sample(names, 2)
        context.low = low
        context.old = {}
        context.files = {}
        for env in ("staging", "prod"):
            (root / env).mkdir(parents=True)
        for name in names:
            timeout = random.choice([800, 1000, 1200, 1500, 1800]) if name in low else 3000
            retries = random.randint(0, 2) if name in low else 2
            if name in low:
                context.old[name] = (timeout, retries)
            for env in ("staging", "prod"):
                text = (
                    f"# {name} ({env})\n[client]\ntimeout_ms = {timeout}\nretries = {retries}\n"
                    "pool = 8\n\n[admin]\ntimeout_ms = 1000\nretries = 1\n\n"
                    f"[server]\nlisten = 0.0.0.0:{random.choice([8080, 8090, 9000])}\n"
                )
                path = root / env / f"{name}.ini"
                path.write_text(text)
                context.files[(env, name)] = (path, text)
        note = context.directory / "rollback.txt"
        note.write_text("")
        context.note = note
        cr = random.randint(300, 399)
        page_html = page(
            f"<h2>CR-{cr}: client timeouts</h2><p>Staging clients give up too early. "
            f"In <code>{root}/staging</code>, for every service whose "
            "<b>[client]</b> <code>timeout_ms</code> is below 2000, set "
            "<code>timeout_ms = 2500</code> and <code>retries = 3</code>. Services at "
            "2000 or above stay as they are. Production is out of scope for this change; "
            "leave the <b>[admin]</b> sections alone.</p>"
            f"<p>Before changing anything, write the old values into <code>{note}</code>, "
            "one line per changed service, like <code>orders: timeout 800, retries 1</code>.</p>"
            "<p>Then close this change request: number of services changed "
            "<input id=n type=number> <button id=done>Close change request</button></p>"
            "<p id=err style='color:#b00'></p>",
            "done.onclick=()=>{if(!n.value){err.textContent='Enter the number changed.';return}"
            "const st={changed:+n.value};document.body.innerHTML='<h2>Change request closed</h2>';report(st)};",
        )
        prompt = (
            "Carry out the change request in the browser. A terminal is open in "
            "the deploy directory and the rollback note is open in the text editor."
        )
        return [terminal(root), editor(note), chromium(context, page_html)], prompt

    def check(self, context):
        state = context.reports.last()
        problems = []
        for (env, name), (path, original) in context.files.items():
            text = path.read_text() if path.exists() else None
            if env == "prod" or name not in context.low:
                if text != original:
                    problems.append(f"{env}/{name} changed")
                continue
            if text is None:
                problems.append(f"{env}/{name} missing")
                continue
            got = {
                (s, k): ini_value(path, s, k)
                for s in ("client", "admin")
                for k in ("timeout_ms", "retries")
            }
            if (got[("client", "timeout_ms")], got[("client", "retries")]) != ("2500", "3"):
                problems.append(f"{name} client values {got}")
            if (got[("admin", "timeout_ms")], got[("admin", "retries")]) != ("1000", "1"):
                problems.append(f"{name} admin changed")
            if ini_value(path, "client", "pool") != "8":
                problems.append(f"{name} pool changed")
        notes = context.note.read_text().lower().splitlines()
        for name, (timeout, retries) in context.old.items():
            lines = [l for l in notes if name in l]
            if not any(
                re.search(rf"\b{timeout}\b", l) and re.search(rf"\b{retries}\b", l.replace(str(timeout), ""))
                for l in lines
            ):
                problems.append(f"rollback note lacks {name}")
        if len(notes) and any(
            n for n in ("catalog", "orders", "billing") if n not in context.low
            and any(n in l for l in notes)
        ):
            problems.append("rollback note lists an unchanged service")
        if state is None or state.get("changed") != len(context.low):
            problems.append(f"closed with {state}")
        return not problems, problems or "ok"


# --- 4. meeting slot ---------------------------------------------------------

DAYS = ["Mon 16 Nov", "Tue 17 Nov", "Wed 18 Nov"]
ROOMS = ["Fjord", "Ridge", "Atrium"]


def hm(slot):  # slot 0 = 09:00, half hours
    minutes = 9 * 60 + slot * 30
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def solutions(alice, bob, rooms):
    out = []
    for day in range(3):
        for start in range(0, 15):  # 60-minute meetings, last start 16:00
            span = {start, start + 1}
            if any(s in alice[day] or s in bob[day] for s in span):
                continue
            begin = 9 * 60 + start * 30
            if begin < 10 * 60:  # Bob takes no meetings before 10:00
                continue
            if begin < 13 * 60 and begin + 60 > 12 * 60:  # lunch 12:00-13:00
                continue
            if day == 2 and begin + 60 > 16 * 60:  # Alice leaves at 16:00 on Wed
                continue
            for room in range(3):
                if all(s not in rooms[room][day] for s in span):
                    out.append((day, start, room))
    return out


def busy_slots():
    slots = set()
    for _ in range(random.randint(3, 5)):
        start = random.randint(0, 14)
        slots |= set(range(start, min(start + random.choice([1, 2, 3]), 16)))
    return slots


def listing(slots):
    out, run = [], None
    for s in sorted(slots) + [99]:
        if run and s == run[1]:
            run[1] = s + 1
        else:
            if run:
                out.append(f"{hm(run[0])}-{hm(run[1])}")
            run = [s, s + 1]
    return out


class MeetingSlot(Task):
    """Find the only slot that fits two calendars, a room and the rules."""

    name = "tier-meeting-slot"
    requires = ("chromium", "mousepad")

    def setup(self, context):
        for _ in range(5000):
            alice = [busy_slots() for _ in DAYS]
            bob = [busy_slots() for _ in DAYS]
            rooms = [[busy_slots() | busy_slots() for _ in DAYS] for _ in ROOMS]
            found = solutions(alice, bob, rooms)
            if len(found) == 1:
                break
        else:
            raise RuntimeError("no unique meeting slot found")
        context.answer = found[0]
        files = []
        for person, calendar in (("Alice", alice), ("Bob", bob)):
            path = context.directory / f"{person.lower()}-calendar.txt"
            path.write_text(
                f"{person}'s calendar: busy times\n\n"
                + "".join(
                    f"{DAYS[d]}\n"
                    + "".join(f"  {t} busy\n" for t in listing(calendar[d])) + "\n"
                    for d in range(3)
                )
            )
            files.append(path)
        room_html = "".join(
            f"<tr><td>{ROOMS[r]}" + "".join(
                f"<td>booked: {', '.join(listing(rooms[r][d])) or 'nothing'}"
                for d in range(3)
            ) + "</tr>"
            for r in range(3)
        )
        day_options = "".join(f"<option>{d}</option>" for d in DAYS)
        room_options = "".join(f"<option>{r}</option>" for r in ROOMS)
        page_html = page(
            "<h2>Book the project sync</h2><p>Alice and Bob need a 60-minute meeting "
            "on Monday, Tuesday or Wednesday this week, within 09:00 to 17:00. "
            "Their busy times are in the two calendar files open in the text editor. "
            "Rules: Bob takes no meetings before 10:00; nothing may overlap the lunch "
            "hour 12:00 to 13:00; Alice leaves at 16:00 on Wednesday. Meetings start "
            "on the hour or half hour. There is exactly one slot and room that works.</p>"
            "<table border=1 cellpadding=5><tr><th>Room" + "".join(f"<th>{d}" for d in DAYS)
            + f"</tr>{room_html}</table>"
            f"<p>Day <select id=day><option value=''>Choose</option>{day_options}</select> "
            "Start (HH:MM) <input id=start size=6> Room <select id=room><option value=''>"
            f"Choose</option>{room_options}</select> <button id=book>Book</button></p>"
            "<p id=err style='color:#b00'></p><div id=m style='display:none;position:fixed;"
            "inset:0;background:#0008'><div style='background:#fff;margin:140px auto;"
            "width:440px;padding:20px'><p id=q></p><button id=yes>Send invitations"
            "</button> <button id=no>Back</button></div></div>",
            "book.onclick=()=>{if(!day.value||!start.value.trim()||!room.value)"
            "{err.textContent='Choose a day, a start time and a room.';return}err.textContent='';"
            "q.textContent='Invite Alice and Bob to '+room.value+' on '+day.value+' at '+"
            "start.value.trim()+'?';m.style.display='block'};no.onclick=()=>m.style.display='none';"
            "yes.onclick=()=>{m.style.display='none';const st={day:day.value,start:start.value,room:room.value};"
            "document.body.innerHTML='<h2>Invitations sent</h2>';report(st)};",
        )
        prompt = (
            "Book the project sync for Alice and Bob in the booking page in the "
            "browser. Their calendars are open in the text editor."
        )
        return [editor(files[0]), editor(files[1]), chromium(context, page_html)], prompt

    def check(self, context):
        state = context.reports.last()
        if state is None:
            return False, "not booked"
        day, start, room = context.answer
        ok = (
            state["day"] == DAYS[day]
            and state["start"].strip().lstrip("0") == hm(start).lstrip("0")
            and state["room"] == ROOMS[room]
        )
        return ok, {"reported": state, "expected": [DAYS[day], hm(start), ROOMS[room]]}


# --- 5. delivery note that changes after the second save ---------------------

class MovingTarget(Task):
    """Stock receipts from a note; after two saves the note is corrected."""

    name = "tier-moving-target"
    requires = ("chromium", "mousepad")

    def setup(self, context):
        skus = [f"SKU-{n}" for n in random.sample(range(1000, 9999), 12)]
        stock = {s: random.randint(5, 60) for s in skus}
        receipt = {s: random.randint(4, 30) for s in random.sample(skus, 6)}
        order = list(receipt)
        changed, cancelled = random.sample(order, 2)
        new_qty = receipt[changed] + random.choice([5, 8, 11])
        final = dict(stock)
        for s, q in receipt.items():
            if s == cancelled:
                continue
            final[s] += new_qty if s == changed else q
        context.answer = final
        note = context.directory / "delivery-note.txt"
        context.note = note
        first = "Delivery note: add these quantities to the stock on hand\n\n" + "".join(
            f"{s}  +{receipt[s]}\n" for s in order
        )
        note.write_text(first)
        corrected = first + (
            "\nCORRECTION from the warehouse (replaces the lines above for these items):\n"
            f"{changed}  +{new_qty}\n{cancelled}  not delivered, no change\n"
        )
        context.corrected = corrected
        context.stop = threading.Event()

        def watcher():
            while not context.stop.is_set():
                if len(context.reports.states()) >= 3:  # initial + two saves
                    time.sleep(1.0)
                    note.write_text(corrected)
                    return
                time.sleep(0.25)

        threading.Thread(target=watcher, daemon=True).start()
        rows = [{"sku": s, "stock": stock[s]} for s in skus]
        page_html = page(
            "<h2>Stock</h2><div id=banner hidden style='background:#fe9;padding:10px'>"
            "The warehouse has updated the delivery note. Check it before you continue."
            "</div><div id=app></div><div id=dlg style='display:none;position:fixed;"
            "inset:0;background:#0006'><div style='background:#fff;margin:100px auto;"
            "width:340px;padding:20px'><h3 id=dt></h3><p>Stock on hand <input id=st "
            "type=number></p><button id=sv>Save</button> <button id=cx>Cancel</button>"
            "</div></div>",
            f"const rows={rows!r};let cur=null,saves=0;function render(){{app.innerHTML="
            "'<table border=1 cellpadding=5><tr><th>SKU<th>Stock on hand<th></tr>'+rows.map("
            "(r,i)=>'<tr><td>'+r.sku+'<td>'+r.stock+'<td><button data-i='+i+'>Edit</button>')"
            ".join('')+'</table>';app.querySelectorAll('button').forEach(b=>b.onclick=()=>{"
            "cur=+b.dataset.i;dt.textContent=rows[cur].sku;st.value=rows[cur].stock;"
            "dlg.style.display='block'})}cx.onclick=()=>dlg.style.display='none';"
            "sv.onclick=()=>{rows[cur].stock=+st.value;dlg.style.display='none';render();"
            "saves++;if(saves>=2)banner.hidden=false;report({rows})};render();report({rows});",
        )
        prompt = (
            "Book the delivery into the stock page in the browser. The delivery "
            "note is open in the text editor."
        )
        return [editor(note), chromium(context, page_html)], prompt

    def check(self, context):
        context.stop.set()
        state = context.reports.last()
        if state is None:
            return False, "nothing reported"
        got = {r["sku"]: r["stock"] for r in state["rows"]}
        wrong = {s: (got.get(s), want) for s, want in context.answer.items() if got.get(s) != want}
        return not wrong, wrong or "ok"


# --- 6. file triage ----------------------------------------------------------

class FileTriage(Task):
    """Rules in a note: delete temp files and exact duplicates, file the rest."""

    name = "tier-file-triage"
    requires = ("mousepad", "foot")

    def setup(self, context):
        inbox = context.directory / "inbox"
        inbox.mkdir()
        context.inbox = inbox

        def body(label):
            return f"{label}\n" + "".join(f"{code(10)}\n" for _ in range(4))

        minutes, budget, notes = body("minutes"), body("budget"), body("notes")
        summary, photo = body("summary"), body("photo")
        files = {
            "2026-03-14_minutes.txt": minutes,
            "2026-03-20_budget.txt": budget,
            "2026-03-20_budget-v2.txt": budget.rstrip("\n"),  # one byte shorter: keep
            "2026-04-02_notes.txt": notes,
            "2026-04-02_notes copy.txt": notes,  # exact duplicate: delete
            "2026-05-01_summary.txt": summary,
            "summary-old.txt": summary,  # exact duplicate of a dated file: delete
            "readme.txt": body("readme"),
            "todo.txt": body("todo"),
            "photo-final.txt": photo,
            "photo-final-2.txt": photo,  # exact duplicate: delete
            "photo-final-2b.txt": photo.replace(photo.splitlines()[1], "x" * 10, 1),
            "scratch.tmp": body("scratch"),
            "session.tmp": body("session"),
        }
        for name, text in files.items():
            (inbox / name).write_text(text)
        kept = {}
        seen = {}
        for name in sorted(n for n in files if not n.endswith(".tmp")):
            digest = hashlib.sha256(files[name].encode()).hexdigest()
            if digest in seen:
                continue
            seen[digest] = name
            kept[name] = files[name]
        expected = {}
        for name, text in kept.items():
            dated = re.match(r"(\d{4}-\d{2})-\d{2}_", name)
            folder = f"archive/{dated.group(1)}" if dated else "misc"
            expected[f"{folder}/{name}"] = text
        context.expected = expected
        rules = context.directory / "inbox-rules.txt"
        rules.write_text(
            "Tidy the inbox folder in this order:\n\n"
            "1. Delete every .tmp file.\n"
            "2. If several files have exactly the same content (byte for byte), keep\n"
            "   the one whose name sorts first and delete the others. Files that\n"
            "   merely look alike stay.\n"
            "3. A file whose name starts with a date (YYYY-MM-DD_) goes into\n"
            "   archive/YYYY-MM/ inside the inbox folder.\n"
            "4. Every other file goes into misc/ inside the inbox folder.\n"
            "5. Finish by writing manifest.csv in the inbox folder itself: one line per\n"
            "   file left, its path relative to the inbox folder, sorted, no header.\n"
        )
        prompt = (
            "Tidy up the inbox folder in the terminal following the rules in the "
            "text editor."
        )
        return [terminal(inbox), editor(rules)], prompt

    def check(self, context):
        inbox = context.inbox
        actual = {}
        for path in sorted(inbox.rglob("*")):
            if path.is_file() and path.name != "manifest.csv":
                actual[str(path.relative_to(inbox))] = path.read_text()
        problems = []
        if actual != context.expected:
            problems.append(
                {
                    "missing": sorted(set(context.expected) - set(actual)),
                    "extra": sorted(set(actual) - set(context.expected)),
                    "wrong_content": sorted(
                        p for p in set(actual) & set(context.expected)
                        if actual[p] != context.expected[p]
                    ),
                }
            )
        manifest = inbox / "manifest.csv"
        if not manifest.exists():
            problems.append("no manifest")
        else:
            lines = [l.strip() for l in manifest.read_text().splitlines() if l.strip()]
            if lines != sorted(context.expected):
                problems.append({"manifest": lines})
        return not problems, problems or "ok"


TIER_TASKS = [
    IncidentTriage(),
    BulkEntry(),
    ConfigRollout(),
    MeetingSlot(),
    MovingTarget(),
    FileTriage(),
]
