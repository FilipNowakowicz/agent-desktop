"""F2 mixed workflow: download a document, edit it in LibreOffice, upload it.

A loopback contract portal lists two agreements (the current one and a
superseded one with the same clauses) and takes one upload. The document and
the expected edit are the native document edit's (benchmarks/f2_document.py).
The portal can refuse the first upload (nothing is stored) or store it and
answer too late for the page (the page cannot tell whether it arrived). The
evaluator reads only what the portal received: exactly one accepted upload, in
the downloaded file's format, whose paragraphs are the expected ones.

Shared by the deterministic driver (tests/test_mixed_workflow.py) and the
agent-driven benchmark task below.
"""

import json
import os
import random
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from . import f2_document as doc
from .office import command as office_command
from .tasks import Task, browser_command

REPLY_TIMEOUT_MS = 3000  # The page gives up waiting for an upload's reply.
LATE_REPLY_S = 6  # A "lost reply" upload is stored, then answered after this.
SUPERSEDED = "Supply agreement 2025 (superseded)"
CURRENT = "Supply agreement (current)"

PAGE = """<!doctype html><meta charset="utf-8"><title>Contract portal</title>
<h2>Contract portal</h2>
<h3>Agreements</h3><ul id="docs">Loading</ul>
<h3>Upload a revised agreement</h3>
<p><input id="file" type="file" accept=".odt,.docx"> <button id="send">Upload</button></p>
<p id="msg"></p>
<h3>Received</h3><table id="received" border=1 cellpadding=4></table>
<script>
async function listed() {
  const d = await (await fetch("/documents")).json();
  docs.innerHTML = d.map((x) => "<li><a href='" + x.href + "'>" + x.title
    + "</a> (" + x.name + ")</li>").join("");
}
async function received() {
  const d = await (await fetch("/received")).json();
  const table = "<tr><th>File<th>Bytes<th>Received</tr>" + d.map((r) => "<tr><td>"
    + r.name + "<td>" + r.bytes + "<td>" + r.at).join("");
  document.getElementById("received").innerHTML = table;
}
send.onclick = async () => {
  const f = file.files[0];
  if (!f) { msg.textContent = "Choose a file first."; return; }
  send.disabled = true; msg.textContent = "Uploading " + f.name;
  const stop = new AbortController();
  const timer = setTimeout(() => stop.abort(), __TIMEOUT_MS__);
  try {
    const r = await fetch("/upload", {method: "POST", body: f, signal: stop.signal,
      headers: {"X-File-Name": encodeURIComponent(f.name)}});
    msg.textContent = r.ok ? "Uploaded " + f.name + " (" + f.size + " bytes)"
      : "Upload failed: the server answered " + r.status + ". Nothing was stored.";
  } catch (e) {
    msg.textContent = "No reply from the server. The upload may or may not have "
      + "arrived: check Received before uploading again.";
  }
  clearTimeout(timer); send.disabled = false; received();
};
listed(); received();
</script>
""".replace("__TIMEOUT_MS__", str(REPLY_TIMEOUT_MS))


class Portal:
    """The contract portal behind a loopback HTTP service: what it serves and
    every upload attempt it received."""

    def __init__(self, seed, suffix=".odt", failure=None):
        if failure not in (None, "refused", "lost reply"):
            raise ValueError(f"unknown failure {failure!r}")
        self.initial = doc.paragraphs(seed)
        # The superseded agreement has the same clauses in another order, so
        # only the right download yields the expected paragraphs.
        other = next(
            s for s in range(seed + 1, seed + 50) if doc.paragraphs(s) != self.initial
        )
        self.superseded = doc.paragraphs(other)
        self.suffix = suffix
        self.name = f"agreement{suffix}"
        self.files = {}
        with tempfile.TemporaryDirectory() as directory:
            for name, lines in (
                (self.name, self.initial),
                (f"agreement-2025{suffix}", self.superseded),
            ):
                path = Path(directory) / name
                doc.write(path, lines)
                self.files[name] = path.read_bytes()
        self.failure = failure
        self.attempts = []  # Every POST: name, bytes, and whether it was stored.
        self.lock = threading.Lock()
        portal = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                url = urlparse(self.path)
                if url.path == "/":
                    return self.reply(PAGE.encode(), "text/html")
                if url.path == "/documents":
                    return self.reply(portal.documents())
                if url.path == "/received":
                    return self.reply(portal.received())
                name = unquote(url.path.removeprefix("/files/"))
                if url.path.startswith("/files/") and name in portal.files:
                    return self.reply(
                        portal.files[name],
                        "application/octet-stream",
                        {"Content-Disposition": f'attachment; filename="{name}"'},
                    )
                self.send_error(404)

            def do_POST(self):
                if self.path != "/upload":
                    return self.send_error(404)
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                name = unquote(self.headers.get("X-File-Name") or "")
                status, delay = portal.upload(name, body)
                time.sleep(delay)
                try:
                    if status != 200:
                        return self.send_error(status)
                    return self.reply({"ok": True})
                except (BrokenPipeError, ConnectionResetError):
                    pass  # The page stopped waiting.

            def reply(self, data, kind="application/json", headers=None):
                body = data if isinstance(data, bytes) else json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
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

    def documents(self):
        return [
            {"title": CURRENT, "name": self.name, "href": f"/files/{quote(self.name)}"},
            {
                "title": SUPERSEDED,
                "name": f"agreement-2025{self.suffix}",
                "href": f"/files/{quote(f'agreement-2025{self.suffix}')}",
            },
        ]

    def upload(self, name, body):
        """(HTTP status, seconds before replying) for one attempt."""
        with self.lock:
            first = not self.attempts
            refused = first and self.failure == "refused"
            self.attempts.append(
                {
                    "name": name,
                    "bytes": len(body),
                    "body": body,
                    "stored": not refused,
                    "at": time.strftime("%H:%M:%S"),
                }
            )
        if refused:
            return 503, 0
        late = first and self.failure == "lost reply"
        return 200, LATE_REPLY_S if late else 0

    def received(self):
        with self.lock:
            return [
                {"name": a["name"], "bytes": a["bytes"], "at": a["at"]}
                for a in self.attempts
                if a["stored"]
            ]

    def stored(self):
        with self.lock:
            return [a for a in self.attempts if a["stored"]]


def evaluate(portal):
    """Problems with the outcome, judged from the uploads the portal stored."""
    stored = portal.stored()
    if not stored:
        return ["nothing was uploaded"]
    problems = []
    if len(stored) > 1:
        problems.append(f"{len(stored)} uploads stored: a duplicate submission")
    for index, upload in enumerate(stored):
        label = f"upload {index + 1} ({upload['name']!r}, {upload['bytes']} bytes)"
        if Path(upload["name"]).suffix.lower() != portal.suffix:
            problems.append(f"{label} is not a {portal.suffix} file")
        with tempfile.TemporaryDirectory() as directory:
            # The document check, on a copy of exactly the bytes received.
            path = Path(directory) / f"upload{portal.suffix}"
            path.write_bytes(upload["body"])
            for problem in doc.evaluate(path, portal.initial):
                problems.append(f"{label}: {problem}")
    return problems


GOAL = (
    "The browser shows a contract portal. Download the current supply agreement "
    "(not the superseded one), and in LibreOffice Writer change the payment term "
    "in its payment clause from 30 days to 14 days. Change nothing else, and keep "
    "the file's format. Then upload the revised file through the portal, so "
    "that the portal has received it exactly once. Say when you are done."
)


def trial(seed, chooser):
    """The varied inputs for one agent run."""
    return {
        "seed": seed,
        "suffix": chooser.choice([".odt", ".docx"]),
        "failure": chooser.choice(["refused", "lost reply"]),
    }


class MixedUpload(Task):
    """An agent does what the mixed driver does: download from a portal, edit in
    LibreOffice Writer (already open, with no document), upload once. The first
    upload is refused or answered too late for the page, as the seed chooses."""

    name = "f2-mixed-upload"

    @property
    def requires(self):
        """The browser browser_command() will launch, and LibreOffice."""
        firefox = os.environ.get("AGENT_DESKTOP_BENCH_BROWSER") == "firefox"
        return ("firefox" if firefox else "chromium", "libreoffice")

    def __init__(self, seed=None, suffix=None, failure=None):
        self.seed, self.suffix, self.failure = seed, suffix, failure

    def setup(self, context):
        chooser = random.Random(self.seed if self.seed is not None else random.random())
        seed = self.seed if self.seed is not None else chooser.randrange(10**6)
        context.trial = trial(seed, chooser)
        if self.suffix:
            context.trial["suffix"] = self.suffix
        if self.failure:
            context.trial["failure"] = self.failure
        context.portal = Portal(
            seed, context.trial["suffix"], failure=context.trial["failure"]
        )
        context.closers = [*getattr(context, "closers", []), context.portal.close]
        # LibreOffice first, the browser last: the browser holds the answer.
        return [
            office_command(context, "writer", first_run_done=True),
            browser_command(context, context.portal.url),
        ], GOAL

    def check(self, context):
        time.sleep(LATE_REPLY_S + 1)  # An upload still in flight would land here.
        problems = evaluate(context.portal)
        attempts = [
            {k: a[k] for k in ("name", "bytes", "stored")}
            for a in context.portal.attempts
        ]
        detail = {**context.trial, "attempts": attempts, "problems": problems}
        return not problems, detail
