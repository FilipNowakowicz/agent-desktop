"""E0: realistic tasks that take a person a few minutes across applications.

Each prompt states the goal as a colleague would, without hints about the
tools or the interface. The information needed is spread over windows (an
editor, a terminal, a web app), and the web apps behave like ordinary ones:
pages, conditional fields, confirmations and an interrupting dialog. Checks
read the outcome (page state, files, saved settings), never the agent's reply.
"""

import random
import re
from pathlib import Path

from .atlas import ini_value
from .tasks import Task, chromium, code, page


def editor(path):
    return ["mousepad", "--disable-server", str(path)]


def terminal(directory):
    return ["foot", "--config=/dev/null", f"--working-directory={directory}", "sh"]


class ReleaseNotes(Task):
    """Editor to web app: select the right lines, fill a date, confirm."""

    name = "real-release-notes"
    requires = ("chromium", "mousepad")

    def setup(self, context):
        version = f"4.{random.randint(2, 9)}.{random.randint(0, 9)}"
        day = random.randint(3, 27)
        user = [
            "Export to CSV keeps the column order",
            "Dark mode no longer resets after a restart",
            "Search finds names with accents",
        ]
        internal = [
            "Bump the build image to Ubuntu 24.04",
            "Remove the legacy metrics endpoint",
            "Rename CI jobs",
        ]
        lines = [f"- [user-facing] {x}" for x in user] + [
            f"- [internal] {x}" for x in internal
        ]
        random.shuffle(lines)
        context.answer = {"version": version, "day": day, "highlights": user}
        notes = context.directory / "release-notes-draft.txt"
        notes.write_text(
            f"Release {version}: draft notes\n"
            f"Planned release date: {day} November 2026\n"
            "Channel: stable\n\n" + "\n".join(lines) + "\n\n"
            "Only user-facing items go into the published highlights.\n"
        )
        page_html = page(
            "<h2>Release desk</h2>"
            "<p>Version <input id=ver placeholder='e.g. 1.2.3'></p>"
            "<p>Release date <input id=date type=date></p>"
            "<p>Channel <select id=ch><option value=''>Choose</option>"
            "<option>beta</option><option>stable</option><option>nightly</option>"
            "</select></p>"
            "<p>Highlights (one per line)<br><textarea id=hl rows=6 cols=60>"
            "</textarea></p><button id=pub>Publish</button><p id=err "
            "style='color:#b00'></p><div id=m style='display:none;position:fixed;"
            "inset:0;background:#0008'><div style='background:#fff;margin:140px auto;"
            "width:420px;padding:20px'><p id=q></p><button id=yes>Publish now</button> "
            "<button id=no>Back</button></div></div>",
            "pub.onclick=()=>{if(!ver.value||!date.value||!ch.value||!hl.value.trim())"
            "{err.textContent='Fill in every field.';return}err.textContent='';"
            "q.textContent='Publish '+ver.value+' to '+ch.value+'? Subscribers are "
            "notified immediately.';m.style.display='block'};no.onclick=()=>"
            "m.style.display='none';yes.onclick=()=>{m.style.display='none';"
            "report({version:ver.value,date:date.value,channel:ch.value,"
            "highlights:hl.value})};",
        )
        prompt = (
            "Publish the upcoming release on the release desk in the browser. The "
            "draft release notes are open in the text editor."
        )
        return [editor(notes), chromium(context, page_html)], prompt

    def check(self, context):
        state = context.reports.last()
        if state is None:
            return False, "not published"
        answer = context.answer
        # As a reader would: bullets and the [user-facing] tag do not count.
        lines = (
            re.sub(
                r"^\[user-facing\]\s*", "", re.sub(r"^[-*\s]+", "", line), flags=re.I
            )
            .strip()
            .lower()
            for line in state["highlights"].split("\n")
        )
        got = sorted(line for line in lines if line)
        ok = (
            state["version"].strip() == answer["version"]
            and state["date"] == f"2026-11-{answer['day']:02d}"
            and state["channel"] == "stable"
            and got == sorted(x.lower() for x in answer["highlights"])
        )
        return ok, {**state, "highlights": got}


class TicketConfig(Task):
    """Web ticket to terminal: edit one section of a config, then resolve."""

    name = "real-ticket-config"
    requires = ("chromium", "foot")

    def setup(self, context):
        folder = context.directory / "services"
        folder.mkdir()
        context.config = folder / "checkout.ini"
        context.port = random.choice([8443, 9443, 7443])
        context.original = (
            "# Checkout service\n[server]\nhost = 0.0.0.0\nport = 8080\n"
            "log_level = debug\nworkers = 4\n\n[admin]\nport = 8081\n"
            "log_level = debug\n\n[database]\nurl = postgres://db.internal/checkout\n"
        )
        context.config.write_text(context.original)
        ticket = random.randint(1200, 1999)
        page_html = page(
            f"<h2>OPS-{ticket}: checkout service config</h2>"
            "<p><b>Reporter:</b> Priya (on-call)</p><p>The checkout service on this "
            f"machine must listen on port {context.port} and log only warnings. "
            f"Its config is <code>{context.config}</code>. Change the "
            "<b>server</b> settings only; the admin interface keeps its port and "
            "its debug logging.</p><p>When it is done, resolve this ticket with a "
            "short comment.</p><hr><p>Comment<br><textarea id=c rows=3 cols=50>"
            "</textarea></p><button id=res>Resolve</button><p id=err "
            "style='color:#b00'></p>",
            "res.onclick=()=>{if(c.value.trim().length<3){err.textContent="
            "'A comment is required to resolve.';return}const state={comment:c.value};"
            "document.body.innerHTML='<h2>Resolved</h2>';report(state)};",
        )
        prompt = (
            "Handle the ops ticket that is open in the browser. A terminal is open too."
        )
        return [terminal(folder), chromium(context, page_html)], prompt

    def check(self, context):
        resolved = context.reports.last() is not None
        try:
            text = context.config.read_text()
        except OSError:
            return False, "config missing"

        def value(section, key):
            return (ini_value(context.config, section, key) or "").lower()

        ok = (
            value("server", "port") == str(context.port)
            and value("server", "log_level") in ("warn", "warning")
            and value("server", "workers") == "4"
            and value("admin", "port") == "8081"
            and value("admin", "log_level") == "debug"
            and value("database", "url") == "postgres://db.internal/checkout"
        )
        return resolved and ok, {"resolved": resolved, "config": text[-400:]}


class ExpenseClaim(Task):
    """A long form with conditional fields, filled from a receipt."""

    name = "real-expense-claim"
    requires = ("chromium", "mousepad")

    def setup(self, context):
        day = random.randint(2, 27)
        km = random.randint(30, 60)
        total = random.choice([1245, 1180, 1320, 990])
        vat = total // 5  # 25% VAT included in the total
        card = f"{random.randint(1000, 9999)}"
        context.answer = {"day": day, "km": km, "total": total, "vat": vat}
        context.answer["card"] = card
        receipt = context.directory / "receipt-taxi.txt"
        receipt.write_text(
            "NORDLYS TAXI AS            Org.nr 998 877 665 MVA\n"
            f"Date: {day:02d}.09.2026   Time: 18:42\n"
            "From: Oslo Airport (OSL)\nTo: Grünerløkka, Oslo\n"
            f"Distance: {km} km\n\nTotal NOK {total},00\n"
            f"incl. VAT 25%: NOK {vat},00\nPaid: corporate card ****{card}\n"
        )
        page_html = page(
            "<h2>Expense claim</h2><form id=f>"
            "<p>Claimant name <input id=claimant></p>"
            "<p>I am <label><input type=radio name=who value=employee>an employee"
            "</label> <label><input type=radio name=who value=contractor>a contractor"
            "</label></p><div id=contractor hidden><p>Company <input id=company></p>"
            "</div><p>Category <select id=cat><option value=''>Choose</option>"
            "<option>Meals</option><option>Travel</option><option>Equipment</option>"
            "</select></p><fieldset id=travel hidden><legend>Travel</legend>"
            "<p>Mode <select id=mode><option value=''>Choose</option><option>Taxi"
            "</option><option>Train</option><option>Flight</option></select></p>"
            "<p>From <input id=from> To <input id=to></p>"
            "<p>Distance (km) <input id=km type=number></p></fieldset>"
            "<p>Date of expense <input id=date type=date></p>"
            "<p>Amount <input id=amount type=number step=0.01> <select id=cur>"
            "<option>EUR</option><option>NOK</option><option>USD</option></select></p>"
            "<p>of which VAT <input id=vat type=number step=0.01></p>"
            "<p>Paid with <select id=paid><option value=''>Choose</option><option "
            "value=personal>My own money</option><option value=card>Corporate card"
            "</option></select></p><p id=cardrow hidden>Card, last 4 digits "
            "<input id=last4 maxlength=4 size=4></p>"
            "<p><label><input type=checkbox id=ok> I confirm this claim is correct"
            "</label></p><button>Submit claim</button><p id=err style='color:#b00'>"
            "</p></form>",
            "const show=()=>{const who=(document.querySelector(':checked[name=who]')"
            "||{}).value;contractor.hidden=who!=='contractor';travel.hidden="
            "cat.value!=='Travel';cardrow.hidden=paid.value!=='card'};"
            "f.oninput=show;f.onchange=show;f.onsubmit=e=>{e.preventDefault();"
            "if(!ok.checked){err.textContent='Please confirm the claim.';return}"
            "const who=(document.querySelector(':checked[name=who]')||{}).value;"
            "const v={name:claimant.value.trim(),who,company:company.value.trim(),"
            "cat:cat.value,mode:mode.value,from:from.value,to:to.value,km:+km.value,"
            "date:date.value,amount:+amount.value,cur:cur.value,vat:+vat.value,"
            "paid:paid.value,last4:last4.value.trim()};"
            "document.body.innerHTML='<h2>Claim submitted</h2>';report(v)};",
        )
        prompt = (
            "Submit an expense claim in the browser for the taxi receipt that is "
            "open in the text editor. The claim is for Lin Okafor, a contractor "
            "from Brightwave Ltd."
        )
        return [editor(receipt), chromium(context, page_html)], prompt

    def check(self, context):
        v = context.reports.last()
        if v is None:
            return False, "not submitted"
        answer = context.answer
        ok = (
            v["name"] == "Lin Okafor"
            and v["who"] == "contractor"
            and re.search("brightwave", v["company"], re.I) is not None
            and v["cat"] == "Travel"
            and v["mode"] == "Taxi"
            and re.search("oslo airport|osl", v["from"], re.I) is not None
            and re.search("grünerløkka", v["to"], re.I) is not None
            and v["km"] == answer["km"]
            and v["date"] == f"2026-09-{answer['day']:02d}"
            and v["amount"] == answer["total"]
            and v["cur"] == "NOK"
            and v["vat"] == answer["vat"]
            and v["paid"] == "card"
            and v["last4"] == answer["card"]
        )
        return ok, v


class InventoryCleanup(Task):
    """A paginated table, an edit dialog per row and an interruption."""

    name = "real-inventory-cleanup"
    requires = ("chromium",)

    def setup(self, context):
        suppliers = ["Acme", "Borealis", "Kestrel", "Norvika", "Tamsin"]
        rows = []
        for i in range(60):
            rows.append(
                {
                    "sku": f"SKU-{code(4)}",
                    "name": f"Item {i + 1:02d}",
                    "supplier": random.choice(suppliers),
                    "stock": random.randint(1, 90),
                    "status": "Active",
                }
            )
        for index in random.sample(range(60), 4):
            rows[index]["supplier"] = "Norvik"
        context.rows = [dict(row) for row in rows]
        page_html = page(
            "<h2>Inventory</h2><div id=app></div><div id=dlg style='display:none;"
            "position:fixed;inset:0;background:#0006'><div style='background:#fff;"
            "margin:100px auto;width:380px;padding:20px'><h3 id=dt></h3><p>Stock "
            "<input id=st type=number></p><p>Status <select id=ss><option>Active"
            "</option><option>Discontinued</option><option>On hold</option></select>"
            "</p><button id=sv>Save</button> <button id=cx>Cancel</button></div>"
            "</div><div id=exp style='display:none;position:fixed;inset:0;"
            "background:#0009'><div style='background:#fff;margin:160px auto;"
            "width:380px;padding:20px'>Your session expires in 60 seconds."
            "<p><button id=stay>Stay signed in</button> <button id=out>Sign out"
            "</button></p></div></div>",
            f"const rows={rows!r};"
            "let page=0,cur=null,saves=0,gone=false;const per=15;function render(){"
            "const part=rows.slice(page*per,page*per+per);app.innerHTML="
            "'<table border=1 cellpadding=5><tr><th>SKU<th>Name<th>Supplier<th>Stock"
            "<th>Status<th></tr>'+part.map((r,i)=>'<tr><td>'+r.sku+'<td>'+r.name+"
            "'<td>'+r.supplier+'<td>'+r.stock+'<td>'+r.status+'<td><button data-i='+"
            "(page*per+i)+'>Edit</button>').join('')+'</table><p><button id=prev>"
            "Previous</button> Page '+(page+1)+' of 4 <button id=next>Next</button>"
            "</p>';app.querySelectorAll('button[data-i]').forEach(b=>b.onclick=()=>{"
            "cur=+b.dataset.i;dt.textContent='Edit '+rows[cur].name+' ('+rows[cur]"
            ".sku+')';st.value=rows[cur].stock;ss.value=rows[cur].status;"
            "dlg.style.display='block'});prev.onclick=()=>{if(page>0){page--;render()}}"
            ";next.onclick=()=>{if(page<3){page++;render()}}}cx.onclick=()=>"
            "dlg.style.display='none';sv.onclick=()=>{if(gone)return;rows[cur].stock="
            "+st.value;rows[cur].status=ss.value;dlg.style.display='none';render();"
            "saves++;if(saves===2)setTimeout(()=>exp.style.display='block',800);"
            "report({rows})};stay.onclick=()=>exp.style.display='none';out.onclick=()=>{"
            "gone=true;document.body.innerHTML='<h2>Signed out</h2>';"
            "report({signedOut:true})};render();",
        )
        prompt = (
            "Our supplier Norvik has gone out of business. In the inventory app in "
            "the browser, mark all of their products as discontinued with no stock "
            "left. Other products must not change."
        )
        return [chromium(context, page_html)], prompt

    def check(self, context):
        states = context.reports.states()
        if any(state.get("signedOut") for state in states):
            return False, "signed out"
        if not states:
            return False, "nothing saved"
        wrong = [
            row["sku"]
            for row, was in zip(states[-1]["rows"], context.rows, strict=True)
            if (
                (row["stock"], row["status"]) != (0, "Discontinued")
                if was["supplier"] == "Norvik"
                else (row["stock"], row["status"]) != (was["stock"], was["status"])
            )
        ]
        return not wrong, f"{len(wrong)} rows wrong: {wrong}"


class EditorIndentation(Task):
    """Settings plus a check that they work: indent with spaces, then use it."""

    name = "real-editor-indentation"
    requires = ("mousepad",)

    def setup(self, context):
        context.target = context.directory / "greet.py"
        prompt = (
            "Set up the text editor for Python: pressing Tab should insert 4 "
            "spaces, never a tab character, and line numbers should be shown. "
            "These must stay set the next time the editor starts. Then write "
            "this function in a new file and save it as "
            f"{context.target}:\n\ndef greet(name):\n    return 'Hello, ' + name\n"
        )
        return [["mousepad", "--disable-server"]], prompt

    def check(self, context):
        path = Path(context.home) / ".config/Mousepad/settings.conf"
        section = "org/xfce/mousepad/preferences/view"
        settings = {
            key: ini_value(path, section, key)
            for key in ("insert-spaces", "tab-width", "indent-width")
        }
        settings["show-line-numbers"] = ini_value(path, section, "show-line-numbers")
        width = settings["indent-width"]
        if width in (None, "-1"):
            width = settings["tab-width"]
        # GSettings' keyfile backend writes unsigned values as "uint32 4".
        width = (width or "").split()[-1:]
        try:
            text = context.target.read_text()
        except OSError:
            text = None
        ok = (
            settings["insert-spaces"] == "true"
            and width == ["4"]
            and settings["show-line-numbers"] == "true"
            and text is not None
            and text.rstrip("\n") == "def greet(name):\n    return 'Hello, ' + name"
        )
        return ok, {"settings": settings, "file": text}


class AttachInvoice(Task):
    """A web upload through the file chooser, with similar names to tell apart."""

    name = "real-attach-invoice"
    requires = ("chromium",)

    def setup(self, context):
        folder = context.directory / "invoices"
        folder.mkdir()
        month = random.choice(["03", "04", "05"])
        context.expected = f"INV-2026-{month}-northwind.pdf"
        names = [
            context.expected,
            f"INV-2026-{month}-northwind-draft.pdf",
            f"INV-2025-{month}-northwind.pdf",
            f"INV-2026-{month}-contoso.pdf",
            "INV-2026-01-northwind.pdf",
        ]
        for name in names:
            (folder / name).write_bytes(b"%PDF-1.4\n% placeholder invoice\n")
        months = {"03": "March", "04": "April", "05": "May"}
        page_html = page(
            "<h2>Supplier payments</h2><p>Supplier <select id=s><option value=''>"
            "Choose</option><option>Contoso</option><option>Northwind</option>"
            "</select></p><p>Invoice (PDF) <input id=file type=file accept=.pdf>"
            "</p><button id=send>Send for payment</button><p id=err "
            "style='color:#b00'></p>",
            "send.onclick=()=>{const f=file.files[0];if(!s.value||!f){"
            "err.textContent='Choose a supplier and attach the invoice.';return}"
            "const state={supplier:s.value,file:f.name};"
            "document.body.innerHTML='<h2>Sent for payment</h2>';report(state)};",
        )
        prompt = (
            f"Send Northwind's final invoice for {months[month]} 2026 for payment "
            f"in the browser. Our invoices are in {folder}."
        )
        return [chromium(context, page_html)], prompt

    def check(self, context):
        state = context.reports.last()
        if state is None:
            return False, "not sent"
        ok = state == {"supplier": "Northwind", "file": context.expected}
        return ok, state


REALISTIC_TASKS = [
    ReleaseNotes(),
    TicketConfig(),
    ExpenseClaim(),
    InventoryCleanup(),
    EditorIndentation(),
    AttachInvoice(),
]
