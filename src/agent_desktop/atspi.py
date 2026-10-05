"""Read and act on application UIs through the session's own AT-SPI bus.

Wayland gives AT-SPI no global coordinates, so actions use AT-SPI itself
(press, focus, set text) rather than pointer positions.
"""

import re
import time

from jeepney import DBusAddress, new_method_call
from jeepney.io.blocking import open_dbus_connection
from jeepney.wrappers import DBusErrorResponse, unwrap_msg

REGISTRY = ("org.a11y.atspi.Registry", "/org/a11y/atspi/accessible/root")
ACCESSIBLE = "org.a11y.atspi.Accessible"
STATES = {
    1: "active",
    4: "checked",
    7: "editable",
    10: "expanded",
    12: "focused",
    20: "pressed",
    23: "selected",
    36: "invalid",
    43: "read-only",
}
SHOWING = 25
# Unnamed layout containers are skipped (their children are kept) to save tokens.
CONTAINERS = {
    "filler",
    "panel",
    "section",
    "grouping",
    "scroll pane",
    "viewport",
    "generic",
}
TEXT_ROLES = {"text", "entry", "text box", "paragraph", "terminal", "document text"}
PRESS_ACTIONS = ("click", "press", "activate", "toggle", "jump", "dodefault")
# Offered by every Chromium node; omitted from listings, still callable by name.
HIDDEN_ACTIONS = {"showContextMenu"}
MAX_DEPTH = 200
NODE = re.compile(r"(:[0-9]+\.[0-9]+)((?:/[A-Za-z0-9_]+)+)")


class AccessibilityError(RuntimeError):
    pass


class Unsupported(AccessibilityError):
    pass


def wait_for_registry(session_bus, timeout=5):
    """Wait until the AT-SPI registry owns its name on the session's a11y bus.

    Applications register only at startup, so one started before the registry
    would stay invisible to the semantic UI tools.
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            accessibility = Accessibility(session_bus)
            try:
                reply = accessibility.connection.send_and_get_reply(
                    new_method_call(
                        DBusAddress(
                            "/org/freedesktop/DBus",
                            "org.freedesktop.DBus",
                            "org.freedesktop.DBus",
                        ),
                        "NameHasOwner",
                        "s",
                        (REGISTRY[0],),
                    ),
                    timeout=1,
                )
                if unwrap_msg(reply)[0]:
                    return
            finally:
                accessibility.close()
        except (OSError, DBusErrorResponse, TimeoutError):
            pass
        if time.monotonic() >= deadline:
            raise AccessibilityError("The accessibility registry did not start")
        time.sleep(0.05)


class Accessibility:
    def __init__(self, session_bus, timeout=2):
        self.timeout = timeout
        with open_dbus_connection(session_bus) as bus:
            reply = bus.send_and_get_reply(
                new_method_call(
                    DBusAddress("/org/a11y/bus", "org.a11y.Bus", "org.a11y.Bus"),
                    "GetAddress",
                ),
                timeout=timeout,
            )
        self.connection = open_dbus_connection(reply.body[0])

    def close(self):
        self.connection.close()

    def call(self, node, interface, method, signature=None, body=()):
        message = new_method_call(
            DBusAddress(node[1], node[0], interface), method, signature, body
        )
        reply = self.connection.send_and_get_reply(message, timeout=self.timeout)
        try:
            return unwrap_msg(reply)
        except DBusErrorResponse as error:
            raise AccessibilityError(f"{method}: {error}") from None

    def get(self, node, interface, name):
        return self.call(
            node, "org.freedesktop.DBus.Properties", "Get", "ss", (interface, name)
        )[0][1]

    def describe(self, node):
        role = self.call(node, ACCESSIBLE, "GetRoleName")[0]
        name = self.get(node, ACCESSIBLE, "Name")
        words = self.call(node, ACCESSIBLE, "GetState")[0]
        bits = {
            index
            for index in range(len(words) * 32)
            if words[index // 32] >> (index % 32) & 1
        }
        interfaces = set(self.call(node, ACCESSIBLE, "GetInterfaces")[0])
        record = {
            "id": node[0] + node[1],
            "role": role,
            "name": name,
            "states": [STATES[b] for b in sorted(bits) if b in STATES],
        }
        if "org.a11y.atspi.Text" in interfaces and (
            role in TEXT_ROLES or "editable" in record["states"]
        ):
            text = self.call(node, "org.a11y.atspi.Text", "GetText", "ii", (0, 500))[0]
            record["text"] = text
        if "org.a11y.atspi.Value" in interfaces:
            record["value"] = self.get(node, "org.a11y.atspi.Value", "CurrentValue")
        if "org.a11y.atspi.Action" in interfaces:
            # GTK 4 also exposes widget action groups (clipboard.copy, ...);
            # they stay usable by name but are omitted to keep the list short.
            record["actions"] = [
                n
                for n in self.action_names(node)
                if n and "." not in n and n not in HIDDEN_ACTIONS
            ]
        if "org.a11y.atspi.EditableText" in interfaces:
            record.setdefault("actions", []).append("set_text")
        return record, SHOWING in bits

    def action_names(self, node):
        """Non-localized action names (Chromium leaves the localized ones empty)."""
        count = self.get(node, "org.a11y.atspi.Action", "NActions")
        return [
            self.call(node, "org.a11y.atspi.Action", "GetName", "i", (i,))[0]
            for i in range(count)
        ]

    def parse(self, node_id):
        match = NODE.fullmatch(node_id) if isinstance(node_id, str) else None
        if not match:
            raise ValueError("Unknown UI node identifier")
        return match.groups()

    def focus(self, node_id, timeout=1):
        """Grab focus and wait until the node reports it."""
        node = self.parse(node_id)
        self.call(node, "org.a11y.atspi.Component", "GrabFocus")
        deadline = time.monotonic() + timeout
        while "focused" not in self.describe(node)[0]["states"]:
            if time.monotonic() >= deadline:
                raise AccessibilityError("The element did not take focus")
            time.sleep(0.02)

    def children(self, node):
        return [tuple(c) for c in self.call(node, ACCESSIBLE, "GetChildren")[0]]

    def tree(self, app=None, window=None, max_nodes=300, budget=3.0):
        """Visible UI nodes as a flat list with depth, filtered by app or window.

        Bounded by listed nodes, visited nodes and elapsed time, so a slow or
        enormous application cannot monopolize the session worker.
        """
        nodes, truncated = [], None
        deadline = time.monotonic() + budget
        visited = 0
        max_visited = max(2000, max_nodes * 10)

        def exhausted():
            nonlocal truncated
            if len(nodes) >= max_nodes:
                truncated = truncated or "node limit"
            elif visited >= max_visited:
                truncated = truncated or "visit limit"
            elif time.monotonic() >= deadline:
                truncated = truncated or "time limit"
            return truncated is not None

        seen = set()

        def walk(window_nodes):
            """Depth-first, in order, with an explicit stack (trees can be deep)."""
            nonlocal visited, truncated
            stack = [(node, 1, True) for node in reversed(window_nodes)]
            while stack and not exhausted():
                node, depth, is_window = stack.pop()
                if node in seen:  # a cyclic tree must not loop forever
                    continue
                seen.add(node)
                visited += 1
                if depth > MAX_DEPTH:
                    truncated = truncated or "depth limit"
                    continue
                try:
                    record, showing = self.describe(node)
                    children = self.children(node)
                except (AccessibilityError, TimeoutError):
                    # Elements disappear while the tree is read (e.g. a closing window).
                    continue
                if not showing:
                    continue
                if is_window and window and window not in record["name"]:
                    continue
                keep = not (
                    record["role"] in CONTAINERS
                    and not record["name"]
                    and set(record.get("actions", ())) <= {"doDefault"}
                )
                if keep:
                    nodes.append({**record, "depth": depth})
                below = depth + 1 if keep else depth
                stack.extend((child, below, False) for child in reversed(children))

        for application in self.children(REGISTRY):
            if exhausted():
                break
            try:
                name = self.get(application, ACCESSIBLE, "Name")
                windows = self.children(application)
            except (AccessibilityError, TimeoutError):
                continue
            if app and app.lower() not in name.lower():
                continue
            if name == "xdg-desktop-portal-gtk" and not app:
                continue
            nodes.append(
                {
                    "id": "".join(application),
                    "role": "application",
                    "name": name,
                    "states": [],
                    "depth": 0,
                }
            )
            walk(windows)
        return {
            "nodes": nodes,
            "truncated": truncated is not None,
            "truncated_by": truncated,
        }

    def act(self, node_id, action, text=None):
        node = self.parse(node_id)
        if action == "focus":
            done = self.call(node, "org.a11y.atspi.Component", "GrabFocus")[0]
        elif action == "set_text":
            if not isinstance(text, str) or len(text) > 10000:
                raise ValueError("set_text needs text of at most 10000 characters")
            try:
                done = self.call(
                    node, "org.a11y.atspi.EditableText", "SetTextContents", "s", (text,)
                )[0]
            except AccessibilityError as error:
                if "UnknownMethod" in str(error) or "NotSupported" in str(error):
                    raise Unsupported(str(error)) from None
                raise
        else:
            names = self.action_names(node)
            folded = [n.lower() for n in names]
            wanted = [action.lower()] if action != "press" else list(PRESS_ACTIONS)
            index = next((folded.index(n) for n in wanted if n in folded), None)
            if index is None:
                raise ValueError(f"Node offers no {action} action; it has {names}")
            done = self.call(node, "org.a11y.atspi.Action", "DoAction", "i", (index,))[
                0
            ]
        if not done:
            raise AccessibilityError(f"The application refused {action}")
        return {"node": node_id, "action": action, "delivered": True}
