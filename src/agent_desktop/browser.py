"""Drive Firefox in a private session through WebDriver BiDi.

Firefox started with --remote-debugging-port exposes the W3C BiDi protocol on
localhost. Pages are read and changed through the DOM and trusted input events,
so no screenshot or coordinates are needed. The session worker owns the
connection, so leases and a person's control apply as for any input.
"""

import json
import time

from websockets.sync.client import connect

# Text found by `find` is bounded so a page cannot flood the reply.
MAX_ITEMS = 30
MAX_TEXT = 8000
CTRL = ""

# Runs in the page: elements matching a CSS selector or a visible text, label,
# placeholder or value. With pick, the one match itself (or null); otherwise
# up to MAX_ITEMS described as JSON, without password values.
FIND = """
(selector, text, exact, pick, within) => {
  const visible = (e) => {
    const s = getComputedStyle(e);
    return e.getClientRects().length > 0 && s.visibility !== "hidden" &&
      s.display !== "none";
  };
  const fold = (v) => (v || "").replace(/\\s+/g, " ").trim();
  const label = (e) => {
    const parts = [e.getAttribute("aria-label"), e.getAttribute("placeholder"),
      e.getAttribute("title"), e.getAttribute("alt")];
    if (e.labels) for (const l of e.labels) parts.push(l.innerText);
    return fold(parts.filter(Boolean).join(" "));
  };
  const own = (e) => fold(e.innerText !== undefined ? e.innerText : e.textContent);
  let found;
  if (selector) {
    found = [...document.querySelectorAll(selector)];
  } else {
    const wanted = fold(text);
    const candidates = document.querySelectorAll(
      "a,button,input,select,textarea,label,summary,option,[role],[onclick]," +
      "[contenteditable=''],[contenteditable=true],h1,h2,h3,h4,li,td,th,p,span,div");
    const matches = (e) => {
      const values = [own(e), label(e)];
      if (e.type === "submit" || e.type === "button") values.push(fold(e.value));
      return values.some((v) => exact ? v === wanted : v.includes(wanted));
    };
    found = [...candidates].filter(matches);
    // The innermost elements: a button rather than every div around it.
    found = found.filter((e) => !found.some((o) => o !== e && e.contains(o)));
  }
  found = found.filter(visible);
  if (within) {
    // Containers (row, list item, form, dialog...) of the innermost visible
    // elements whose text includes `within`; targets must lie inside one.
    const w = fold(within);
    let holders = [...document.body.querySelectorAll("*")].filter(
      (e) => visible(e) && own(e).includes(w));
    holders = holders.filter((e) => !holders.some((o) => o !== e && e.contains(o)));
    const scopes = holders.map((e) => e.closest(
      "tr,li,form,fieldset,section,article,dialog,[role=row],[role=dialog]," +
      "[role=listitem],[role=group]") || e.parentElement);
    found = found.filter((e) => scopes.some((c) => c && c.contains(e)));
  }
  if (pick) return found.length === 1 ? found[0] : null;
  const describe = (e) => {
    const d = {tag: e.tagName.toLowerCase()};
    for (const k of ["id", "name", "type", "role", "href"]) {
      const v = e.getAttribute(k); if (v) d[k] = v.slice(0, 200);
    }
    const t = own(e); if (t) d.text = t.slice(0, 120);
    const l = label(e); if (l) d.label = l.slice(0, 120);
    if ("value" in e && e.type !== "password" && e.tagName !== "BUTTON")
      d.value = String(e.value).slice(0, 200);
    if (e.disabled) d.disabled = true;
    if (e.checked) d.checked = true;
    if (e.tagName === "SELECT")
      d.options = [...e.options].slice(0, 30).map((o) => fold(o.text));
    return d;
  };
  return JSON.stringify({count: found.length,
    items: found.slice(0, MAX_ITEMS).map(describe)});
}
""".replace("MAX_ITEMS", str(MAX_ITEMS))


class BrowserError(RuntimeError):
    pass


class Browser:
    """One BiDi session with a Firefox instance."""

    def __init__(self, url, timeout=10):
        self.socket = connect(
            url.rstrip("/") + "/session", open_timeout=timeout, max_size=2**24
        )
        self.next_id = 0
        try:
            self.command("session.new", {"capabilities": {}})
        except Exception:
            self.socket.close()
            raise
        self.context = None

    def alive(self):
        try:
            self.command("session.status", {}, timeout=2)
            return True
        except Exception:
            return False

    def close(self):
        try:
            self.command("session.end", {}, timeout=2)
        except Exception:
            pass
        self.socket.close()

    def command(self, method, params, timeout=30):
        self.next_id += 1
        ident = self.next_id
        self.socket.send(json.dumps({"id": ident, "method": method, "params": params}))
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Firefox did not answer {method}")
            message = json.loads(self.socket.recv(timeout=remaining))
            if message.get("id") != ident:
                continue  # an event
            if message.get("type") == "error":
                raise BrowserError(
                    f"{message.get('error')}: {message.get('message', '')}".strip()
                )
            return message.get("result", {})

    def tabs(self):
        tree = self.command("browsingContext.getTree", {"maxDepth": 0})["contexts"]
        tabs = []
        for index, context in enumerate(tree):
            try:
                title = self.evaluate("document.title", context["context"])
            except BrowserError:
                title = None  # privileged pages (about:, extensions) refuse scripts
            tabs.append({"tab": index, "url": context["url"], "title": title})
        return tree, tabs

    def target(self, tab=None):
        tree = self.command("browsingContext.getTree", {"maxDepth": 0})["contexts"]
        if not tree:
            raise BrowserError("Firefox has no open tab")
        if tab is not None:
            if not isinstance(tab, int) or not 0 <= tab < len(tree):
                raise ValueError(f"tab must be 0 to {len(tree) - 1}")
            self.context = tree[tab]["context"]
        elif self.context not in {c["context"] for c in tree}:
            self.context = tree[-1]["context"]
        return self.context

    def evaluate(self, expression, context):
        result = self.command(
            "script.evaluate",
            {
                "expression": expression,
                "target": {"context": context},
                "awaitPromise": True,
            },
        )
        return remote_value(result)

    def call(self, function, arguments, context, ownership="none"):
        result = self.command(
            "script.callFunction",
            {
                "functionDeclaration": function,
                "arguments": [local_value(a) for a in arguments],
                "target": {"context": context},
                "awaitPromise": True,
                "resultOwnership": ownership,
            },
        )
        if result.get("type") == "exception":
            details = result.get("exceptionDetails", {})
            raise BrowserError(f"Page script failed: {details.get('text', details)}")
        return result["result"]

    def find(self, context, selector=None, text=None, exact=False, within=None):
        if not (selector or text):
            raise ValueError("Give a CSS selector or a text")
        value = self.call(FIND, [selector, text, exact, False, within], context)
        return json.loads(remote_value(value))

    def element(self, context, selector=None, text=None, exact=False, within=None):
        """A reference to the one visible element that matches."""
        found = self.find(context, selector, text, exact, within)
        if found["count"] != 1:
            described = repr(selector or text)
            if not found["count"]:
                raise BrowserError(f"No visible element matches {described}")
            sample = "; ".join(json.dumps(i) for i in found["items"][:4])
            raise BrowserError(
                f"{found['count']} elements match {described} ({sample}); use a "
                "more specific selector, exact text or within (text of the row, "
                "item or form that holds it)"
            )
        node = self.call(FIND, [selector, text, exact, True, within], context)
        if node.get("type") != "node":
            raise BrowserError("The element changed while it was looked up")
        return {"sharedId": node["sharedId"]}, found["items"][0]

    def click(self, context, element):
        self.call(
            "(e) => e.scrollIntoView({block: 'center', inline: 'center'})",
            [element],
            context,
        )
        self.command(
            "input.performActions",
            {
                "context": context,
                "actions": [
                    {
                        "type": "pointer",
                        "id": "mouse",
                        "parameters": {"pointerType": "mouse"},
                        "actions": [
                            {
                                "type": "pointerMove",
                                "x": 0,
                                "y": 0,
                                "origin": {"type": "element", "element": element},
                            },
                            {"type": "pointerDown", "button": 0},
                            {"type": "pointerUp", "button": 0},
                        ],
                    }
                ],
            },
        )

    def keys(self, context, text, select_all=False):
        actions = []
        if select_all:
            actions += [
                {"type": "keyDown", "value": CTRL},
                {"type": "keyDown", "value": "a"},
                {"type": "keyUp", "value": "a"},
                {"type": "keyUp", "value": CTRL},
                {"type": "keyDown", "value": ""},  # Backspace
                {"type": "keyUp", "value": ""},
            ]
        for character in text:
            actions += [
                {"type": "keyDown", "value": character},
                {"type": "keyUp", "value": character},
            ]
        if actions:
            self.command(
                "input.performActions",
                {
                    "context": context,
                    "actions": [{"type": "key", "id": "keyboard", "actions": actions}],
                },
                timeout=30 + len(text) * 0.05,
            )


def local_value(value):
    if isinstance(value, dict) and "sharedId" in value:
        return value
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "boolean", "value": value}
    if isinstance(value, (int, float)):
        return {"type": "number", "value": value}
    return {"type": "string", "value": str(value)}


def remote_value(result):
    value = result.get("result", result)
    if value.get("type") in ("string", "number", "boolean"):
        return value["value"]
    if value.get("type") in ("null", "undefined"):
        return None
    return value
