"""Drive Firefox in a private session through WebDriver BiDi.

Firefox started with --remote-debugging-port exposes the W3C BiDi protocol on
localhost. Pages are read and changed through the DOM and trusted input events,
so no screenshot or coordinates are needed. The session worker owns the
connection, so leases and a person's control apply as for any input.
"""

import json
import time

from websockets.sync.client import connect

from .secret_text import hide, hide_fields, shorten

# Text found by `find` is bounded so a page cannot flood the reply. The page
# returns more (READ) than an item keeps, so a secret the cut would split is
# recognised whole before it is hidden.
MAX_ITEMS = 30
MAX_TEXT = 8000
READ = 400
CTRL = ""

# Runs in the page: elements matching a CSS selector or a visible text, label,
# placeholder or value. With pick, the one match itself (or null); otherwise
# up to MAX_ITEMS described as JSON, without password values. Browser.find
# then hides text, labels and values that look like credentials.
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
    // Before a page has a body, nothing is inside a scope yet.
    const root = document.body || document.documentElement;
    let holders = (root ? [...root.querySelectorAll("*")] : []).filter(
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
    const t = own(e); if (t) d.text = t.slice(0, READ);
    const l = label(e); if (l) d.label = l.slice(0, READ);
    if ("value" in e && e.type !== "password" && e.tagName !== "BUTTON")
      d.value = String(e.value).slice(0, READ);
    if (e.disabled) d.disabled = true;
    if (e.checked) d.checked = true;
    if (e.tagName === "SELECT")
      d.options = [...e.options].slice(0, 30).map((o) => fold(o.text));
    return d;
  };
  return JSON.stringify({count: found.length,
    items: found.slice(0, MAX_ITEMS).map(describe)});
}
""".replace("MAX_ITEMS", str(MAX_ITEMS)).replace("READ", str(READ))


# Bot-check interstitials ("Just a moment..." and similar). The detector is
# deliberately small and conservative; it only reports, it never tries to solve
# or bypass anything. A page is flagged when
#  - its title starts with CHALLENGE_TITLE, or
#  - it has a challenge-page element (an id Cloudflare's interstitial uses), or
#  - its whole visible text is short (CHALLENGE_SHORT characters or fewer) and
#    holds one of CHALLENGE_PHRASES.
# A long article that quotes "just a moment" is not flagged; a login form with a
# Turnstile widget is not either (the widget's iframe is not a marker).
CHALLENGE_TITLE = "just a moment"
CHALLENGE_PHRASES = (
    "performing security verification",
    "checking your browser before",
    "verify you are human",
    "verifying you are human",
)
CHALLENGE_IDS = (
    "challenge-form",
    "challenge-running",
    "challenge-stage",
    "cf-challenge-running",
)
CHALLENGE_SHORT = 800
CHALLENGE_HINT = (
    "This looks like a bot-check page. Wait a few seconds (wait with no "
    "arguments) for it to clear; if it persists, hand off with "
    "desktop_request_human (the person solves it) or use the person's own "
    "Firefox via desktop_request_host. Do not try to solve or bypass it."
)

# Runs in the page: what challenge_reason needs.
CHALLENGE_PROBE = """() => JSON.stringify({
  title: document.title,
  text: (document.body ? document.body.innerText : "").slice(0, 2000),
  ids: IDS.filter((i) => document.getElementById(i)),
})""".replace("IDS", json.dumps(list(CHALLENGE_IDS)))


def challenge_reason(title, text, ids):
    """Why the page looks like a bot-check interstitial, or None."""
    if (title or "").strip().lower().startswith(CHALLENGE_TITLE):
        return f"title {title.strip()!r}"
    if ids:
        return f"challenge element #{ids[0]}"
    folded = " ".join((text or "").split())
    if len(folded) <= CHALLENGE_SHORT:
        lowered = folded.lower()
        for phrase in CHALLENGE_PHRASES:
            if phrase in lowered:
                return f"text {phrase!r}"
    return None


class BrowserError(RuntimeError):
    pass


class Interrupted(RuntimeError):
    """A command was sent, then its wait for a reply was given up."""


# What a click at the element's centre would hit, if not the element itself:
# null when the element, or a label for it or the control it labels, is on top.
# Otherwise a JSON description of the cover (the dialog that holds what was
# hit, else the hit element) with its role, label and the start of its text,
# and of another open dialog on the page (an overlay is often its backdrop).
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
  const DIALOG = "dialog,[role=dialog],[role=alertdialog],[aria-modal=true]";
  const describe = (n) => ({
    tag: n.tagName.toLowerCase(), id: n.id || null,
    role: n.getAttribute("role"),
    label: n.getAttribute("aria-label") || n.getAttribute("title"),
    class: [...n.classList].slice(0, 2).join(".") || null,
    text: (n.innerText || n.textContent || "").replace(/\\s+/g, " ").trim()
      .slice(0, READ),
  });
  const box = hit.closest(DIALOG) || hit;
  const cover = describe(box);
  if (box === hit) {
    const open = [...document.querySelectorAll(DIALOG)].find((d) =>
      d.getClientRects().length && getComputedStyle(d).visibility !== "hidden" &&
      !d.contains(e) && !d.contains(hit));
    if (open) cover.dialog = describe(open);
  }
  return JSON.stringify(cover);
}""".replace("READ", str(READ))


def cover_text(cover):
    """A cover for a covered: refusal, e.g. div[role=dialog] "Remind me later …".

    Its label and text pass through the same secret hiding as find items.
    """
    name = cover.get("tag") or "element"
    if cover.get("id"):
        name += "#" + cover["id"]
    elif cover.get("class"):
        name += "." + cover["class"]
    if cover.get("role"):
        name += f"[role={cover['role']}]"
    label = hide(cover.get("label") or "")[0]
    if label:
        name += f" ({json.dumps(shorten(label, 40), ensure_ascii=False)})"
    text = hide(cover.get("text") or "")[0]
    if text:
        name += " " + json.dumps(shorten(text, 40), ensure_ascii=False)
    return name


SETTLE_EVENTS = [
    "network.beforeRequestSent",
    "network.responseCompleted",
    "network.fetchError",
]
SANDBOX = "agent-desktop-settle"
LONG_REQUEST = 5
# Installs an observer on the first call in each document, then reports whether
# the document has loaded and how long its DOM has been unchanged. A change of
# only a style attribute does not count: scripts animate spinners and carousels
# through it every frame, and such a page would otherwise never settle.
DOM_QUIET = """() => {
  const now = performance.now();
  if (!window.__adQuiet) {
    window.__adQuiet = {since: now};
    new MutationObserver((records) => {
      if (records.some((r) => r.type !== "attributes" || r.attributeName !== "style"))
        window.__adQuiet.since = performance.now();
    }).observe(document, {subtree: true, childList: true, attributes: true,
      characterData: true});
  }
  return JSON.stringify({ready: document.readyState === "complete",
    idle_ms: Math.round(now - window.__adQuiet.since)});
}"""


class Browser:
    """One BiDi session with a Firefox instance."""

    def __init__(self, url, timeout=10):
        self.socket = connect(
            url.rstrip("/") + "/session", open_timeout=timeout, max_size=2**24
        )
        self.next_id = 0
        # Requests in flight, {id: (context, started)}, and each context's last
        # network event, both in wall-clock seconds from the events' timestamps.
        self.requests = {}
        self.network_at = {}
        try:
            self.command("session.new", {"capabilities": {}})
        except Exception:
            self.socket.close()
            raise
        try:
            # From the start, so a page's first requests are known to be open.
            self.command("session.subscribe", {"events": SETTLE_EVENTS})
        except BrowserError:
            pass  # without events, settling follows the DOM alone
        self.context = None

    def network_event(self, message):
        params = message.get("params", {})
        context = params.get("context")
        request = params.get("request", {}).get("request")
        at = params.get("timestamp", time.time() * 1000) / 1000
        if message["method"] == "network.beforeRequestSent":
            if len(self.requests) < 10000:
                self.requests[request] = (context, at)
        else:
            self.requests.pop(request, None)
        self.network_at[context] = max(self.network_at.get(context, 0), at)

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

    def command(self, method, params, timeout=30, interrupt=None):
        """Send one BiDi command and wait for its reply.

        With `interrupt`, the wait checks it every 0.1 s and raises Interrupted
        when it returns true. The command has then been sent and may still run.
        Network events that arrive meanwhile are recorded; others are dropped.
        """
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
            if interrupt is not None:
                if interrupt():
                    raise Interrupted(method)
                try:
                    message = json.loads(self.socket.recv(timeout=min(0.1, remaining)))
                except TimeoutError:
                    continue
            else:
                message = json.loads(self.socket.recv(timeout=remaining))
            if message.get("id") != ident:
                if str(message.get("method", "")).startswith("network."):
                    self.network_event(message)
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

    def settle(self, context, quiet=0.5, limit=10.0, interrupt=None):
        """Wait until the page has loaded and neither its requests nor its DOM
        have changed for `quiet` seconds, at most `limit` seconds.

        With `interrupt`, the wait stops as soon as it returns true and the
        reply says interrupted; the caller decides what that means.

        Single-page apps finish `load` and then fetch and render their content,
        so a navigation that returned "complete" can still show "Loading".
        Requests are followed through BiDi network events (see network_event),
        the DOM through a MutationObserver in a sandbox the page cannot see. A
        request open longer than LONG_REQUEST (a long poll, a stream) is ignored.
        """
        started = time.monotonic()
        deadline = started + limit
        if getattr(self, "deadline", None) is not None:
            deadline = min(deadline, self.deadline - 1)
        settled = interrupted = False
        while True:
            if interrupt is not None and interrupt():
                interrupted = True
                break
            try:
                state = json.loads(
                    remote_value(
                        self.command(
                            "script.callFunction",
                            {
                                "functionDeclaration": DOM_QUIET,
                                "arguments": [],
                                "target": {"context": context, "sandbox": SANDBOX},
                                "awaitPromise": False,
                            },
                        )
                    )
                )
            except (BrowserError, TypeError, ValueError):
                state = {}  # mid-navigation: the document is being replaced
            now, wall = time.monotonic(), time.time()
            busy = any(
                c == context and wall - at < LONG_REQUEST
                for c, at in self.requests.values()
            )
            if (
                state.get("ready")
                and not busy
                and wall - self.network_at.get(context, 0) >= quiet
                and state.get("idle_ms", 0) >= quiet * 1000
            ):
                settled = True
                break
            if now >= deadline:
                break
            time.sleep(min(0.1, max(0.0, deadline - now)))
        result = {
            "settled": settled,
            "settle_ms": round((time.monotonic() - started) * 1000),
        }
        if interrupted:
            result["interrupted"] = True
        return result

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
        found = json.loads(remote_value(value))
        for item in found["items"]:
            hide_fields(item, ("text", "label"), 120)
            hide_fields(item, ("value",), 200)
            hide_fields(item, ("options",))
        return found

    def challenge(self, context):
        """{"challenge": True, "challenge_hint": ...} on a bot-check page, else {}.

        Best effort: a page that is navigating or not scriptable reports {}.
        """
        try:
            probe = json.loads(remote_value(self.call(CHALLENGE_PROBE, [], context)))
            reason = challenge_reason(probe["title"], probe["text"], probe["ids"])
        except Exception:
            return {}
        if not reason:
            return {}
        return {"challenge": True, "challenge_hint": CHALLENGE_HINT}

    def title_matches(self, context, text, exact=False):
        """Whether the document title holds the text (find matches only the body)."""
        title = remote_value(self.call("() => document.title", [], context)) or ""
        title = " ".join(title.split())
        wanted = " ".join((text or "").split())
        return bool(wanted) and (title == wanted if exact else wanted in title)

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
            cover = json.loads(cover)
            under = cover_text(cover)
            if cover.get("dialog"):
                under += f"; a dialog is open: {cover_text(cover['dialog'])}"
            raise BrowserError(
                f"covered: the element is under {under}; nothing was sent. "
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
