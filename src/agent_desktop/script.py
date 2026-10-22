"""The library desktop_run scripts start with (`from agent_desktop.script import *`).

Every call acts on one private session as the controller that ran the script,
so the lease and a person's takeover apply as for the tools. Targets are
looked up when the call runs; a call that cannot find exactly one target, or a
wait that is not met, raises and stops the script.
"""

import os
from pathlib import Path

from . import core

__all__ = [
    "SESSION",
    "home",
    "windows",
    "focus",
    "find",
    "one",
    "text",
    "rows",
    "act",
    "press",
    "set_text",
    "select",
    "type_text",
    "key",
    "click",
    "scroll",
    "wait",
    "browser",
    "screenshot",
]

SESSION = os.environ.get("AGENT_DESKTOP_SESSION", "")
CONTROLLER = core.controller_id()


def request(operation, **arguments):
    return core.request(
        SESSION,
        operation,
        CONTROLLER,
        **{k: v for k, v in arguments.items() if v is not None},
    )


def home():
    """The session's home directory, for reading the files a task produces."""
    info = core.manifest(SESSION)
    return Path(info.get("home") or core.session_path(SESSION) / "home")


def windows():
    """Windows as dicts: id, title, app_id, states, parent."""
    return request("windows")["windows"]


def focus(window):
    """Activate a window by id ("w2") or by a title substring."""
    if not (window.startswith("w") and window[1:].isdigit()):
        matches = [w for w in windows() if window in w["title"]]
        if len(matches) != 1:
            raise LookupError(f"{len(matches)} windows match {window!r}")
        window = matches[0]["id"]
    return request("focus", window=window)


# Roles that group a record or a form: what `within` narrows a lookup to.
CONTAINERS = (
    "table row",
    "list item",
    "row",
    "dialog",
    "alert",
    "form",
    "group",
    "panel",
    "section",
)


class UIListing(list):
    """Visible results with coverage for the source read, before filtering.

    Complete means the requested accessibility scope was read without errors
    or limits; it does not cover offscreen or virtualized application data.
    """

    def __init__(self, items, coverage):
        super().__init__(items)
        self.coverage = dict(coverage)

    def require_complete(self):
        if self.coverage.get("truncated") or self.coverage.get("unreadable"):
            raise LookupError(
                "The UI listing was incomplete; uniqueness is unknown. "
                "Filter by app or window and read again before acting."
            )


def listing(window=None, app=None):
    tree = request("ui", window=window, app=app, max_nodes=2000)
    return UIListing(
        tree["nodes"],
        {
            **{k: v for k, v in tree.items() if k != "nodes"},
            "scope": {"window": window, "app": app, "visible_only": True},
        },
    )


def subtree(nodes, index):
    """The nodes under nodes[index] in a depth-first listing."""
    end = index + 1
    while end < len(nodes) and nodes[end]["depth"] > nodes[index]["depth"]:
        end += 1
    return nodes[index + 1 : end]


def mentions(node, value):
    return value in node["name"] or value in str(node.get("text") or "")


def scoped(nodes, within):
    """Nodes inside the innermost containers (rows, list items, dialogs,
    forms) that contain `within` in a name or text."""
    holders = []
    for index, node in enumerate(nodes):
        if node["role"] in CONTAINERS:
            inside = subtree(nodes, index)
            if any(mentions(n, within) for n in inside):
                holders.append((index, len(inside)))
    innermost = [
        (index, size)
        for index, size in holders
        if not any(index < other <= index + size for other, _ in holders)
    ]
    return [n for index, size in innermost for n in nodes[index + 1 : index + 1 + size]]


def find(
    element=None,
    role=None,
    text=None,
    state=None,
    exact=False,
    window=None,
    app=None,
    within=None,
):
    """Visible UI nodes that match, as dicts: id, role, name, states, text,
    value, actions. element is a name substring (whole with exact), text a
    substring of the text or value, state e.g. "checked" or "enabled";
    within="SKU-1" keeps only nodes in the row, list item, dialog or form
    that contains that text. The list's .coverage describes the source read;
    a partial read can establish presence, not uniqueness or absence."""
    source = nodes = listing(window, app)
    if within is not None:
        nodes = scoped(nodes, within)
    matched = [
        index
        for index, n in enumerate(nodes)
        if core.node_matches(n, element, role, text, state, exact)
    ]
    # Containers are often named after their content (a cell "Edit" around
    # its button "Edit"): keep the innermost of nested matches.
    innermost = [
        index
        for index in matched
        if not any(
            index < other <= index + len(subtree(nodes, index)) for other in matched
        )
    ]
    return UIListing([nodes[index] for index in innermost], source.coverage)


def rows(window=None, app=None, within=None):
    """Visible rows as lists of cell texts, with source-read .coverage.

    This does not enumerate offscreen or virtualized records.
    """
    source = nodes = listing(window, app)
    if within is not None:
        nodes = scoped(nodes, within)
    found = []
    for index, node in enumerate(nodes):
        if node["role"] in ("table row", "list item", "row"):
            cells = [
                n["name"] or str(n.get("text") or "")
                for n in subtree(nodes, index)
                if n["role"] in ("table cell", "cell", "column header", "row header")
            ]
            if cells:
                found.append(cells)
    return UIListing(found, source.coverage)


def one(element=None, **query):
    """The one node that matches (a whole-name match wins over substrings)."""
    found = find(element, **query)
    found.require_complete()
    if len(found) > 1 and element is not None and not query.get("exact"):
        whole = [n for n in found if n["name"] == element]
        if len(whole) == 1:
            found = whole
    if len(found) != 1:
        sample = "; ".join(f"{n['role']} {n['name']!r}" for n in found[:4])
        raise LookupError(
            f"{len(found)} elements match {element!r} {query or ''}"
            + (f": {sample}" if sample else "")
        )
    return found[0]


def text(element=None, **query):
    """The text (or value) of the one matching node."""
    node = one(element, **query)
    return node.get("text") if node.get("text") is not None else node.get("value")


def act(node, action, text=None):
    """A UI action on a node from find/one: press, focus, set_text, select or
    a listed action name."""
    return request("ui_action", node=node["id"], action=action, text=text)


def press(element=None, **query):
    return act(one(element, **query), "press")


def set_text(element, value, **query):
    return act(one(element, **query), "set_text", value)


def select(element, **query):
    return act(one(element, **query), "select")


def type_text(value):
    """Type into the focused application."""
    return request("type", text=value)


def key(name, modifiers=(), repeat=1):
    """A key or chord: key("Return"), key("ctrl+s")."""
    return request("key", key=name, modifiers=list(modifiers), repeat=repeat)


def click(x, y, button="left"):
    """Click at desktop pixels."""
    return request("click", x=x, y=y, button=button)


def scroll(dy, dx=0, x=None, y=None):
    return request("scroll", dy=dy, dx=dx, x=x, y=y)


def wait(timeout=10, **conditions):
    """Wait like desktop_wait (title, app_id, gone, element, role, text, state,
    exact, stable_ms, seconds, file, contains, key, value); raise
    TimeoutError if the conditions do not hold by the timeout."""
    result = core.wait(SESSION, timeout=timeout, controller=CONTROLLER, **conditions)
    if not result.get("satisfied"):
        raise TimeoutError(f"wait {conditions} not met: {result.get('reason')}")
    return result


def browser(action, **arguments):
    """desktop_browser in the session's bridged Firefox; returns its reply."""
    return request("browser", action=action, **arguments)


def screenshot():
    """Save a screenshot and return its path (the script cannot see it; the
    tool can return the final screen)."""
    return request("screenshot")["path"]
