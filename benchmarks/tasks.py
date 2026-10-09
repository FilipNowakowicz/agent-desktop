"""Representative GUI tasks with independent outcome checks.

Each task launches its application in a harness-created session, gives the agent
a goal, and verifies the result without trusting the agent's reply.
"""

import os
import random

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def code(length=6):
    return "".join(random.choice(CODE_ALPHABET) for _ in range(length))


def chromium(context, page):
    """The browser command for a page: Chromium, or Firefox with a WebDriver
    BiDi port when the harness runs with --firefox."""
    path = context.directory / "page.html"
    path.write_text(page)
    if os.environ.get("AGENT_DESKTOP_BENCH_BROWSER") == "firefox":
        return ["firefox", "--remote-debugging-port=0", path.as_uri()]
    return [
        "chromium",
        f"--user-data-dir={context.directory / 'profile'}",
        "--no-first-run",
        "--no-default-browser-check",
        "--ozone-platform=wayland",
        "--disable-gpu",
        "--password-store=basic",
        "--window-size=1200,680",
        # Web content in the accessibility tree (used by the semantic UI tools).
        "--force-renderer-accessibility",
        path.as_uri(),
    ]


def html(body, script=""):
    return (
        '<!doctype html><meta charset="utf-8"><title>Task</title>'
        "<style>body{font:18px sans-serif;margin:24px}</style>"
        f"{body}<script>function done(ok, detail){{document.title='Task - '"
        f"+(ok?'complete':'incomplete '+(detail||''));}}\n{script}</script>"
    )


def title_complete(context):
    titles = [w["title"] for w in context.windows()]
    return any(t.startswith("Task - complete") for t in titles), titles


class Task:
    name = ""
    requires = ()

    def setup(self, context):
        """Return (argv, prompt)."""
        raise NotImplementedError

    def check(self, context):
        return title_complete(context)


class CanvasCodeDrag(Task):
    name = "chromium-canvas-code-drag"
    requires = ("chromium",)

    def setup(self, context):
        context.secret = code()
        page = html(
            "<p>Type the code drawn below, drag the red box into the dashed target, "
            "then press Submit.</p><canvas id=c width=260 height=60></canvas>"
            "<p><input id=answer autocomplete=off> <button id=submit>Submit</button></p>"
            '<div id=zone style="position:absolute;left:520px;top:300px;width:200px;'
            'height:140px;border:3px dashed #383">target</div>'
            '<div id=box style="position:absolute;left:80px;top:320px;width:90px;'
            'height:90px;background:#c33"></div>',
            f"const code='{context.secret}';const g=c.getContext('2d');"
            "g.font='bold 40px monospace';g.fillText(code,10,45);let d=null;"
            "box.onpointerdown=e=>{d=[e.clientX-box.offsetLeft,e.clientY-box.offsetTop];"
            "box.setPointerCapture(e.pointerId)};box.onpointermove=e=>{if(d){"
            "box.style.left=e.clientX-d[0]+'px';box.style.top=e.clientY-d[1]+'px'}};"
            "box.onpointerup=()=>d=null;function inside(){const b=box.getBoundingClientRect(),"
            "z=zone.getBoundingClientRect();return b.left>=z.left&&b.right<=z.right&&"
            "b.top>=z.top&&b.bottom<=z.bottom}submit.onclick=()=>done("
            "answer.value.trim()===code&&inside(),'code='+(answer.value.trim()===code)"
            "+' box='+inside());",
        )
        return chromium(context, page), "Complete the task shown on the web page."


class Form(Task):
    name = "chromium-form"
    requires = ("chromium",)

    def setup(self, context):
        page = html(
            "<form id=f><p>Name <input id=fullname></p><p>Country <select id=country>"
            "<option>Choose</option><option>Norway</option><option>Peru</option>"
            "<option>Japan</option></select></p><p>Size <label><input type=radio "
            "name=size value=S>S</label><label><input type=radio name=size value=M>M"
            "</label><label><input type=radio name=size value=L>L</label></p><p><label>"
            "<input type=checkbox id=terms> I accept the terms</label></p>"
            "<button>Send</button></form>",
            "f.onsubmit=e=>{e.preventDefault();const s=(document.querySelector("
            "'input[name=size]:checked')||{}).value;const ok=fullname.value==='Grace Hopper'"
            "&&country.value==='Peru'&&s==='L'&&terms.checked;done(ok,JSON.stringify("
            "[fullname.value,country.value,s,terms.checked]))};",
        )
        prompt = (
            "Fill the web form: name 'Grace Hopper', country Peru, size L, accept "
            "the terms, then send it."
        )
        return chromium(context, page), prompt


class Scroll(Task):
    name = "chromium-scroll"
    requires = ("chromium",)

    def setup(self, context):
        rows = "".join(f"<p>Paragraph {i}</p>" for i in range(120))
        page = html(
            f"<h1>Long page</h1>{rows}<button id=finish>Finish</button>{rows}",
            "finish.onclick=()=>done(true);",
        )
        prompt = (
            "On the web page, find the 'Finish' button (it is not visible "
            "initially) and click it."
        )
        return chromium(context, page), prompt


class Confirm(Task):
    name = "chromium-confirm-dialog"
    requires = ("chromium",)

    def setup(self, context):
        page = html(
            "<p>Press the button and accept the confirmation.</p>"
            "<button id=del>Delete draft</button>",
            "del.onclick=()=>done(confirm('Really delete the draft?'),'cancelled');",
        )
        prompt = "On the web page, delete the draft and confirm the deletion."
        return chromium(context, page), prompt


class SecondTab(Task):
    name = "chromium-second-tab"
    requires = ("chromium",)

    def setup(self, context):
        context.secret = code()
        secret = context.directory / "secret.html"
        secret.write_text(
            '<!doctype html><meta charset="utf-8"><title>Secret</title>'
            f"<h1>The access code is {context.secret}</h1>"
        )
        page = html(
            f'<p><a href="{secret.as_uri()}" target=_blank>Open the code page</a></p>'
            "<p>Access code <input id=answer> <button id=go>Unlock</button></p>",
            f"go.onclick=()=>done(answer.value.trim()==='{context.secret}');",
        )
        prompt = (
            "On the web page, open the code page link (it opens a new tab), read "
            "the access code there, return to the first tab, enter it and unlock."
        )
        return chromium(context, page), prompt


class Slider(Task):
    name = "chromium-slider"
    requires = ("chromium",)

    def setup(self, context):
        context.target = random.randint(20, 80)
        page = html(
            f"<p>Set the volume to exactly {context.target}.</p>"
            "<input type=range id=v min=0 max=100 value=50 style='width:600px'>"
            " <b id=out>50</b><p><button id=save>Save</button></p>",
            "v.oninput=()=>out.textContent=v.value;"
            f"save.onclick=()=>done(+v.value==={context.target},'value='+v.value);",
        )
        return chromium(context, page), "Complete the task shown on the web page."


class ContextMenu(Task):
    name = "chromium-context-menu"
    requires = ("chromium",)

    def setup(self, context):
        page = html(
            "<p>Right-click the message below and choose <b>Archive</b>.</p>"
            "<div id=msg style='padding:20px;border:1px solid #888;width:300px'>"
            "Quarterly report</div><div id=menu style='display:none;position:absolute;"
            "background:#eee;border:1px solid #444'><div class=i>Reply</div>"
            "<div class=i>Archive</div><div class=i>Delete</div></div>",
            "msg.oncontextmenu=e=>{e.preventDefault();menu.style.left=e.pageX+'px';"
            "menu.style.top=e.pageY+'px';menu.style.display='block'};"
            "document.querySelectorAll('.i').forEach(i=>{i.style.padding='8px 24px';"
            "i.onclick=()=>{menu.style.display='none';done(i.textContent==='Archive',"
            "i.textContent)}});",
        )
        return chromium(context, page), "Complete the task shown on the web page."


class DoubleClickEdit(Task):
    name = "chromium-double-click-edit"
    requires = ("chromium",)

    def setup(self, context):
        page = html(
            "<p>Double-click Bob's age to edit it, change it to 47 and press Enter.</p>"
            "<table border=1 cellpadding=8><tr><th>Name</th><th>Age</th></tr>"
            "<tr><td>Alice</td><td>31</td></tr><tr><td>Bob</td><td id=bob>52</td></tr>"
            "</table>",
            "bob.ondblclick=()=>{bob.contentEditable=true;bob.focus()};"
            "bob.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();"
            "bob.contentEditable=false;done(bob.textContent.trim()==='47',"
            "bob.textContent)}};",
        )
        return chromium(context, page), "Complete the task shown on the web page."


class Shortcut(Task):
    name = "chromium-keyboard-shortcut"
    requires = ("chromium",)

    def setup(self, context):
        page = html(
            "<p>This page has a hidden search box. Open it with Ctrl+K, search "
            "for <b>private desktop</b> and press Enter.</p>"
            "<input id=q style='display:none'>",
            "document.onkeydown=e=>{if(e.ctrlKey&&e.key==='k'){e.preventDefault();"
            "q.style.display='inline';q.focus()}};q.onkeydown=e=>{if(e.key==="
            "'Enter')done(q.value.trim()==='private desktop',q.value)};",
        )
        return chromium(context, page), "Complete the task shown on the web page."


class Reorder(Task):
    name = "chromium-drag-reorder"
    requires = ("chromium",)

    def setup(self, context):
        page = html(
            "<p>Drag the items so the list reads <b>One, Two, Three, Four</b> from top "
            "to bottom, then press Done.</p><ul id=list style='list-style:none;"
            "padding:0;width:240px'></ul><button id=fin>Done</button>",
            "['Three','One','Four','Two'].forEach(t=>{const li=document."
            "createElement('li');li.textContent=t;li.style.cssText='padding:14px;"
            "margin:6px;background:#dde;cursor:grab;user-select:none';list.append(li)});"
            "let held=null;list.onpointerdown=e=>{held=e.target.closest('li')};"
            "document.onpointerup=e=>{if(!held)return;const over=document."
            "elementFromPoint(e.clientX,e.clientY);const target=over&&over.closest"
            "('li');if(target&&target!==held){const items=[...list.children];if("
            "items.indexOf(held)<items.indexOf(target))target.after(held);else "
            "target.before(held)}held=null};fin.onclick=()=>{const v=[...list."
            "children].map(l=>l.textContent).join(',');done(v==='One,Two,Three,Four',v)};",
        )
        return chromium(context, page), "Complete the task shown on the web page."


class FootFile(Task):
    name = "foot-shell-file"
    requires = ("foot",)

    def setup(self, context):
        context.target = context.directory / "note.txt"
        prompt = (
            "A terminal window is open. Use it to create the file "
            f"{context.target} containing exactly one line: hello from the agent"
        )
        return ["foot", "--config=/dev/null", "sh"], prompt

    def check(self, context):
        try:
            content = context.target.read_text()
        except OSError:
            return False, "missing file"
        return content.strip() == "hello from the agent", content


class XtermTitleCode(Task):
    name = "xterm-title-code"
    requires = ("xterm",)

    def setup(self, context):
        context.secret = code()
        context.target = context.directory / "codes"
        prompt = (
            "An X11 terminal is open. Create the directory "
            f"{context.target} and inside it an empty file named after the code "
            "shown in the terminal's window title, with the extension .txt."
        )
        title = f"Code {context.secret}"
        return [
            "xterm",
            "-u8",
            "-fa",
            "DejaVu Sans Mono",
            "-T",
            title,
            "-e",
            "sh",
        ], prompt

    def check(self, context):
        expected = context.target / f"{context.secret}.txt"
        found = (
            sorted(p.name for p in context.target.glob("*"))
            if context.target.is_dir()
            else []
        )
        return expected.is_file(), found


class EditorSave(Task):
    name = "mousepad-save"
    requires = ("mousepad",)

    def setup(self, context):
        context.target = context.directory / "letter.txt"
        prompt = (
            "A text editor is open. Write two lines, 'Dear team,' and 'The desktop "
            f"works.', then save the document as {context.target}."
        )
        return ["mousepad", "--disable-server"], prompt

    def check(self, context):
        try:
            lines = context.target.read_text().strip().splitlines()
        except OSError:
            return False, "missing file"
        return [line.strip() for line in lines] == [
            "Dear team,",
            "The desktop works.",
        ], lines


class DialogTask(Task):
    """A dialog that prints its answer on stdout and exits."""

    expected = ""

    def check(self, context):
        status = context.application_status()
        if status is None or status["exit_code"] is None:
            return False, "dialog still open"
        output = context.application_output().strip().splitlines()
        answer = output[-1].strip() if output else ""
        return status["exit_code"] == 0 and answer == self.expected, answer


class ZenityList(DialogTask):
    name = "zenity-radio-list"
    requires = ("zenity",)
    expected = "Banana"

    def setup(self, context):
        argv = [
            "zenity",
            "--list",
            "--radiolist",
            "--title=Fruit",
            "--text=Choose the fruit that is yellow, then press OK.",
            "--column=Pick",
            "--column=Fruit",
            "FALSE",
            "Apple",
            "FALSE",
            "Banana",
            "FALSE",
            "Cherry",
            "FALSE",
            "Grape",
        ]
        return argv, "Answer the dialog that is open on the desktop."


class ZenityForms(DialogTask):
    name = "zenity-forms"
    requires = ("zenity",)
    expected = "Ada Lovelace|ada@example.org|London"

    def setup(self, context):
        argv = [
            "zenity",
            "--forms",
            "--title=Contact",
            "--text=New contact",
            "--add-entry=Name",
            "--add-entry=Email",
            "--add-entry=City",
        ]
        prompt = (
            "Fill the open form with name 'Ada Lovelace', email 'ada@example.org' "
            "and city 'London', then press OK."
        )
        return argv, prompt


class ZenityFile(DialogTask):
    name = "zenity-file-chooser"
    requires = ("zenity",)

    def setup(self, context):
        root = context.directory / "files"
        for folder in ("inbox", "archive", "drafts"):
            (root / folder).mkdir(parents=True)
            for year in (2024, 2025, 2026):
                (root / folder / f"report-{year}.txt").write_text(folder)
        self.expected = str(root / "archive" / "report-2025.txt")
        argv = ["zenity", "--file-selection", "--title=Open", f"--filename={root}/"]
        prompt = (
            "A file chooser is open. Select the file report-2025.txt inside the "
            "archive folder and confirm."
        )
        return argv, prompt


class ZenityCalendar(DialogTask):
    name = "zenity-calendar"
    requires = ("zenity",)
    expected = "2026-03-14"

    def setup(self, context):
        argv = [
            "zenity",
            "--calendar",
            "--title=Date",
            "--text=Select March 14, 2026.",
            "--day=1",
            "--month=1",
            "--year=2026",
            "--date-format=%Y-%m-%d",
        ]
        return argv, "Answer the dialog that is open on the desktop."


class ZenityScale(DialogTask):
    name = "zenity-scale"
    requires = ("zenity",)
    expected = "42"

    def setup(self, context):
        argv = [
            "zenity",
            "--scale",
            "--title=Level",
            "--text=Set the level to 42.",
            "--min-value=0",
            "--max-value=100",
            "--value=10",
        ]
        return argv, "Answer the dialog that is open on the desktop."


class KdialogCombo(DialogTask):
    name = "kdialog-combobox"
    requires = ("kdialog",)
    expected = "Saturn"

    def setup(self, context):
        argv = [
            "kdialog",
            "--title",
            "Planets",
            "--combobox",
            "Pick the planet with prominent rings",
            "Mars",
            "Venus",
            "Saturn",
            "Mercury",
        ]
        return argv, "Answer the dialog that is open on the desktop."


class KdialogChecklist(DialogTask):
    name = "kdialog-checklist"
    requires = ("kdialog",)
    expected = '"2" "5" "11"'

    def setup(self, context):
        argv = [
            "kdialog",
            "--title",
            "Primes",
            "--checklist",
            "Select every prime number",
            "2",
            "2",
            "off",
            "4",
            "4",
            "off",
            "5",
            "5",
            "off",
            "9",
            "9",
            "off",
            "11",
            "11",
            "off",
        ]
        return argv, "Answer the dialog that is open on the desktop."


TASKS = [
    CanvasCodeDrag(),
    Form(),
    Scroll(),
    Confirm(),
    SecondTab(),
    Slider(),
    ContextMenu(),
    DoubleClickEdit(),
    Shortcut(),
    Reorder(),
    FootFile(),
    XtermTitleCode(),
    EditorSave(),
    ZenityList(),
    ZenityForms(),
    ZenityFile(),
    ZenityCalendar(),
    ZenityScale(),
    KdialogCombo(),
    KdialogChecklist(),
]
