"""Harder tasks: multiple applications, longer flows, interruptions and recovery."""

import random

from .tasks import DialogTask, Task, chromium, code, html


class TicketTransfer(Task):
    name = "hard-terminal-to-browser"
    requires = ("chromium", "foot")

    def setup(self, context):
        context.secret = code()
        page = html(
            "<p>Support form</p><p>Ticket number <input id=t autocomplete=off></p>"
            "<button id=go>Open ticket</button>",
            f"go.onclick=()=>done(t.value.trim()==='{context.secret}',t.value);",
        )
        terminal = [
            "foot",
            "--config=/dev/null",
            "--title=Ticket log",
            "sh",
            "-c",
            f"echo 'Ticket number: {context.secret}'; echo 'Status: open'; exec sh",
        ]
        prompt = (
            "Two windows are open: a terminal ('Ticket log') and a browser support form. "
            "Copy the ticket number shown in the terminal into the browser form and "
            "open the ticket."
        )
        return [terminal, chromium(context, page)], prompt


class WebAdmin(Task):
    name = "hard-web-admin"
    requires = ("chromium",)

    def setup(self, context):
        people = [f"user{i:02d}" for i in range(40)]
        people[27] = "mallory"
        rows = "".join(
            f"{{n:'{n}',role:'{random.choice(['viewer', 'editor'])}'}}," for n in people
        )
        page = html(
            "<div id=app></div>",
            f"const users=[{rows}];let state='login';function render(){{"
            "if(state==='login')app.innerHTML='<h2>Admin sign in</h2><p>User <input id=u>'"
            "+'</p><p>Password <input id=p type=password></p><button id=s>Sign in</button>';"
            "if(state==='home')app.innerHTML='<h2>Dashboard</h2><a href=# id=nav>Manage users"
            "</a>';if(state==='users')app.innerHTML='<h2>Users</h2><table border=1 cellpadding=6>'"
            "+users.map((x,i)=>'<tr><td>'+x.n+'</td><td>'+x.role+'</td><td><button data-i='+i+"
            "'>Edit</button></td></tr>').join('')+'</table>';if(typeof state==='number'){"
            "const x=users[state];app.innerHTML='<h2>Edit '+x.n+'</h2><p>Role <select id=r>'"
            "+['viewer','editor','auditor','owner'].map(o=>'<option'+(o===x.role?' selected':'')"
            "+'>'+o+'</option>').join('')+'</select></p><button id=save>Save</button>'"
            '+\'<div id=m style="display:none;border:2px solid #a00;padding:12px">Apply role change?'
            " <button id=yes>Apply</button> <button id=no>Cancel</button></div>'}bind()}"
            "function bind(){if(state==='login')s.onclick=()=>{if(u.value==='admin'&&p.value"
            "==='hunter2'){state='home';render()}else alert('Wrong credentials')};"
            "if(state==='home')nav.onclick=e=>{e.preventDefault();state='users';render()};"
            "if(state==='users')app.querySelectorAll('button').forEach(b=>b.onclick=()=>{"
            "state=+b.dataset.i;render()});if(typeof state==='number'){save.onclick=()=>"
            "m.style.display='block';no.onclick=()=>m.style.display='none';yes.onclick=()=>{"
            "users[state].role=r.value;const x=users.find(v=>v.n==='mallory');"
            "const others=users.filter(v=>v.n!=='mallory'&&v.role==='auditor').length;"
            "done(x.role==='auditor'&&others===0,x.n+'='+x.role);state='users';render()}}}render();",
        )
        prompt = (
            "A browser shows an admin site. Sign in as 'admin' with password 'hunter2', "
            "go to user management, change the role of user 'mallory' (and nobody "
            "else) to 'auditor', and apply the change."
        )
        return [chromium(context, page)], prompt


class InterruptingModal(Task):
    name = "hard-interrupting-modal"
    requires = ("chromium",)

    def setup(self, context):
        page = html(
            "<form id=f><p>Street <input id=street></p><p>City <input id=city></p>"
            "<p>Postcode <input id=zip></p><button>Save address</button></form>"
            "<div id=m style='display:none;position:fixed;inset:0;background:#0008'>"
            "<div style='background:#fff;margin:120px auto;width:360px;padding:20px'>"
            "Your session is about to expire.<p><button id=stay>Stay signed in</button>"
            " <button id=out>Sign out</button></p></div></div>",
            "let signedOut=false,shown=false;street.oninput=()=>{if(!shown){shown=true;"
            "setTimeout(()=>{m.style.display='block';document.activeElement.blur()},1500)}};"
            "stay.onclick=()=>m.style.display='none';out.onclick=()=>{signedOut=true;"
            "m.style.display='none';document.body.innerHTML='<h1>Signed out</h1>';done(false,"
            "'signed out')};f.onsubmit=e=>{e.preventDefault();const ok=!signedOut&&"
            "street.value.trim()==='12 Harbour Road'&&city.value.trim()==='Bergen'&&"
            "zip.value.trim()==='5003';done(ok,JSON.stringify([street.value,city.value,"
            "zip.value]))};",
        )
        prompt = (
            "Fill the address form in the browser: street '12 Harbour Road', city "
            "'Bergen', postcode '5003', and save it. Do not sign out."
        )
        return [chromium(context, page)], prompt


class SlowLoad(Task):
    name = "hard-slow-load"
    requires = ("chromium",)

    def setup(self, context):
        context.secret = code()
        page = html(
            "<p>Press <b>Generate</b> to create a voucher, then enter the voucher code "
            "below and redeem it.</p><button id=gen>Generate</button><p id=out></p>"
            "<p>Voucher <input id=v autocomplete=off> <button id=red>Redeem</button></p>",
            "gen.onclick=()=>{out.textContent='Generating... please wait';"
            f"setTimeout(()=>out.textContent='Your voucher: {context.secret}',7000)}};"
            f"red.onclick=()=>done(v.value.trim()==='{context.secret}',v.value);",
        )
        return [chromium(context, page)], "Complete the task shown on the web page."


class ChartReading(Task):
    name = "hard-chart-reading"
    requires = ("chromium",)

    def setup(self, context):
        months = ["January", "February", "March", "April", "May", "June"]
        values = random.sample(range(20, 95, 7), len(months))
        context.answer = months[values.index(max(values))]
        page = html(
            "<p>Monthly sales (bar chart). Which month had the highest sales?</p>"
            "<canvas id=c width=640 height=320></canvas><p>Answer <input id=a> "
            "<button id=go>Submit</button></p>",
            f"const m={months},v={values};const g=c.getContext('2d');g.font='14px sans-serif';"
            "m.forEach((x,i)=>{g.fillStyle='#46a';g.fillRect(20+i*100,300-v[i]*3,60,v[i]*3);"
            "g.fillStyle='#000';g.fillText(x.slice(0,3),30+i*100,316)});"
            f"go.onclick=()=>done(a.value.trim().toLowerCase()==='{context.answer.lower()}',a.value);",
        )
        prompt = (
            "Answer the question on the web page (type the full month name) and submit."
        )
        return [chromium(context, page)], prompt


class EditorOpenEdit(Task):
    name = "hard-editor-open-edit"
    requires = ("mousepad",)

    def setup(self, context):
        folder = context.directory / "projects" / "2026" / "q3"
        folder.mkdir(parents=True)
        context.target = folder / "plan.txt"
        context.target.write_text(
            "Plan for Q3\nStatus: DRAFT\nOwner: Lin\nBudget: 4200\n"
        )
        (folder / "notes.txt").write_text("Status: DRAFT\n")
        prompt = (
            "A text editor is open. Use File > Open to open "
            f"{context.target}, change 'Status: DRAFT' to 'Status: FINAL' in that "
            "file only, and save it."
        )
        return [["mousepad", "--disable-server"]], prompt

    def check(self, context):
        text = context.target.read_text()
        notes = (context.target.parent / "notes.txt").read_text()
        ok = text == "Plan for Q3\nStatus: FINAL\nOwner: Lin\nBudget: 4200\n"
        return ok and notes == "Status: DRAFT\n", text


class TerminalRename(Task):
    name = "hard-terminal-rename"
    requires = ("foot",)

    def setup(self, context):
        context.folder = context.directory / "photos"
        context.folder.mkdir()
        for i in (1, 2, 3, 7, 12, 30):
            (context.folder / f"IMG_{i}.JPG").write_text(str(i))
        prompt = (
            f"A terminal is open. In {context.folder}, rename every file IMG_<n>.JPG to "
            "photo-<n>.jpg with <n> zero-padded to three digits (IMG_7.JPG becomes "
            "photo-007.jpg). Keep the file contents."
        )
        return [["foot", "--config=/dev/null", "sh"]], prompt

    def check(self, context):
        found = {p.name: p.read_text() for p in context.folder.iterdir()}
        expected = {f"photo-{i:03d}.jpg": str(i) for i in (1, 2, 3, 7, 12, 30)}
        return found == expected, sorted(found)


class MissingName(DialogTask):
    name = "hard-compare-two-windows"
    requires = ("mousepad", "zenity")

    def setup(self, context):
        names = [
            "Amara",
            "Bjorn",
            "Chen",
            "Dalia",
            "Emeka",
            "Farah",
            "Goran",
            "Hana",
            "Ivo",
            "Jun",
            "Kofi",
            "Lena",
            "Mateo",
            "Nia",
        ]
        random.shuffle(names)
        self.expected = names[5]
        first = context.directory / "list-a.txt"
        second = context.directory / "list-b.txt"
        first.write_text("\n".join(names) + "\n")
        rest = [n for n in names if n != self.expected]
        random.shuffle(rest)
        second.write_text("\n".join(rest) + "\n")
        dialog = [
            "zenity",
            "--entry",
            "--title=Answer",
            "--text=Which name is in list-a.txt but missing from list-b.txt?",
        ]
        prompt = (
            "Two editor windows show list-a.txt and list-b.txt. Find the one name that "
            "appears in list-a but not in list-b and enter it in the 'Answer' dialog."
        )
        return [
            ["mousepad", "--disable-server", str(first)],
            ["mousepad", "--disable-server", str(second)],
            dialog,
        ], prompt


class FocusSteal(Task):
    name = "hard-focus-steal"
    requires = ("chromium", "zenity")

    def setup(self, context):
        context.text = (
            "The quarterly review is moved to Thursday at 14:00 in room Fjord. "
            "Please bring the updated figures and the hiring plan."
        )
        page = html(
            "<p>Message</p><textarea id=t rows=6 cols=70></textarea>"
            "<p><button id=send>Send</button></p>",
            "send.onclick=()=>{const v=t.value.replace(/\\s+/g,' ').trim();"
            f"done(v==={context.text!r},v)}};",
        )
        warning = [
            "sh",
            "-c",
            "sleep 6; exec zenity --warning --title=Updates "
            "--text='Updates are available.'",
        ]
        prompt = (
            "In the browser, type this message into the text box and send it:\n"
            f"{context.text}\n"
            "Other windows may appear; close them and make sure the message is exact."
        )
        context.wait_windows = 1
        return [chromium(context, page), warning], prompt

    def check(self, context):
        ok, titles = super().check(context)
        warning_closed = context.applications[1]
        status = context.status_of(warning_closed)
        closed = status is not None and status["exit_code"] is not None
        return ok and closed, {"titles": titles, "warning_closed": closed}


class Validation(Task):
    name = "hard-validation-fix"
    requires = ("chromium",)

    def setup(self, context):
        page = html(
            "<h2>Order bolts</h2><p>Quantity <input id=q type=number></p>"
            "<button id=o>Place order</button><p id=err style='color:#b00'></p>",
            "o.onclick=()=>{const n=+q.value;if(n%6){err.textContent='Bolts ship in "
            "boxes of 6: quantity must be a multiple of 6.';done(false,'q='+n);return}"
            "err.textContent='';done(n===24,'q='+n)};",
        )
        prompt = (
            "In the browser, order the smallest quantity of bolts that is at least 20 "
            "and that the shop accepts. Make sure the order is placed."
        )
        return [chromium(context, page)], prompt


HARD_TASKS = [
    TicketTransfer(),
    WebAdmin(),
    InterruptingModal(),
    SlowLoad(),
    ChartReading(),
    EditorOpenEdit(),
    TerminalRename(),
    MissingName(),
    FocusSteal(),
    Validation(),
]
