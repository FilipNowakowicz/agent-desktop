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
  // A CSS selector that matches only this element now: its id if unique,
  // else a short child path from the nearest ancestor with a unique id.
  const unique = (q) => { try { return document.querySelectorAll(q).length === 1; }
    catch (_) { return false; } };
  const css = (e) => {
    const byId = (n) => n.id && unique("#" + CSS.escape(n.id)) ? "#" + CSS.escape(n.id) : null;
    if (byId(e)) return byId(e);
    const parts = [];
    let n = e;
    while (n && n.parentElement && n !== document.body && parts.length < 8) {
      const id = byId(n);
      if (id) { parts.unshift(id); break; }
      let part = n.tagName.toLowerCase();
      const same = [...n.parentElement.children].filter((c) => c.tagName === n.tagName);
      if (same.length > 1) part += ":nth-of-type(" + (same.indexOf(n) + 1) + ")";
      parts.unshift(part);
      n = n.parentElement;
    }
    if (n === document.body) parts.unshift("body");
    const q = parts.join(" > ");
    return q.length <= 300 && unique(q) ? q : null;
  };
  const describe = (e) => {
    const d = {tag: e.tagName.toLowerCase()};
    for (const k of ["id", "name", "type", "role", "href"]) {
      const v = e.getAttribute(k); if (v) d[k] = v.slice(0, 200);
    }
    const classes = [...e.classList].slice(0, 4).join(" ");
    if (classes) d.class = classes.slice(0, 120);
    const q = css(e); if (q) d.selector = q;
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


# What a click at the element's centre would hit, if not the element itself:
# null when the element, or a label for it or the control it labels, is on top.
UNCOVERED = """(e) => {
  e.scrollIntoView({block: "center", inline: "center"});
  const rect = [...e.getClientRects()].find((r) => r.width && r.height);
  if (!rect) return null;
  const x = (Math.max(rect.left, 0) + Math.min(rect.right, innerWidth)) / 2;
  const y = (Math.max(rect.top, 0) + Math.min(rect.bottom, innerHeight)) / 2;
  const root = e.getRootNode();
  const hit = (root.elementFromPoint ? root : document).elementFromPoint(x, y);
  if (!hit || hit === e || e.contains(hit)) return null;
  // A label and the control it is for are one target: a styled span inside
  // the label over a hidden input, or an input stretched over its label.
  if (hit.closest("label")?.control === e || e.control === hit) return null;
  if (hit.shadowRoot && hit.contains(e)) return null;
  const text = (hit.innerText || hit.textContent || "").trim().slice(0, 40);
  return hit.tagName.toLowerCase() + (hit.id ? "#" + hit.id : "") +
    (text ? " (" + JSON.stringify(text) + ")" : "");
}"""


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
        deadline = time.monotonic() + timeout
        if getattr(self, "deadline", None) is not None:
            deadline = min(deadline, self.deadline)
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Browser operation deadline reached before {method}")
        self.next_id += 1
        ident = self.next_id
        self.socket.send(json.dumps({"id": ident, "method": method, "params": params}))
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
            tabs.append(
                {
                    "tab": index,
                    "context": context["context"],
                    "url": context["url"],
                    "title": title,
                }
            )
        return tree, tabs

    def target(self, tab=None, context=None):
        if tab is not None and context is not None:
            raise ValueError("Choose either tab or context, not both")
        tree = self.command("browsingContext.getTree", {"maxDepth": 0})["contexts"]
        contexts = {c["context"] for c in tree}
        if context is not None:
            if not isinstance(context, str) or context not in contexts:
                raise BrowserError(
                    "target_lost: requested browser context is unavailable"
                )
            self.context = context
        elif tab is not None:
            if type(tab) is not int or not 0 <= tab < len(tree):
                raise ValueError(f"tab must be 0 to {len(tree) - 1}")
            self.context = tree[tab]["context"]
        elif self.context is not None and self.context not in contexts:
            raise BrowserError(
                "target_lost: selected browser context disappeared; "
                "list tabs and explicitly choose a context or tab"
            )
        elif self.context is None:
            if not tree:
                raise BrowserError("Firefox has no open tab")
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

    def uncovered(self, context, element):
        """Refuse, before any input, when something else would take the click.

        A pointer click lands on whatever is on top at the element's centre;
        a modal or overlay there would receive it instead of the element.
        """
        cover = remote_value(self.call(UNCOVERED, [element], context))
        if cover:
            raise BrowserError(
                f"covered: the element is under {cover}; nothing was sent. "
                "Dismiss or handle what covers it, then try again"
            )

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
