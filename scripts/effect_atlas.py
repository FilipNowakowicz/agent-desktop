"""Effect atlas: learn what each GUI control changes, without a model.

For an application spec, every toggle reachable from the listed menus and
every check box of its preferences dialog is clicked once in a fresh private
session. Configuration files are parsed into key/value pairs (GLib keyfiles
and INI, LibreOffice registrymodifications.xcu, Firefox prefs.js, JSON) and the
result after quitting is compared with control runs that open the same menus
and dialog without clicking. Keys that also change in the controls, or in most
treatments, are interaction noise. What remains is the control's effect.

Each learned effect is verified in another fresh session: the key is written
into the default configuration, the application is started, and (for check
boxes) the control must show the learned state; then clicking it again must
return the key to its default value. No language model is used.

    uv run scripts/effect_atlas.py mousepad [--limit N] [--output FILE]
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

os.environ.setdefault("AGENT_DESKTOP_EFFECTS", "0")

from agent_desktop import atlas, core  # noqa: E402

# Menu items never clicked: they open windows, change files or end the app.
UNSAFE = re.compile(
    r"(quit|close|exit|save|print|new|open|reload|revert|delete|detach|"
    r"fullscreen|about|help|contents|\.\.\.|…)",
    re.IGNORECASE,
)

APPS = {
    "mousepad": {
        "argv": ["mousepad"],
        "app_id": "org.xfce.mousepad",
        "menus": ["View", "Document"],
        "dialog": {"menu": "Edit", "item": "Preferences", "title": "Preferences"},
        "quit": {"key": "q", "modifiers": ["ctrl"]},
        "config": ".config",
    },
    "geany": {
        "argv": ["geany"],
        "app_id": "geany",
        "menus": ["View", "Document"],
        "dialog": {
            "menu": "Edit",
            "item": "Preferences",
            "title": "Preferences",
            "close_button": "OK",
        },
        "quit": {"key": "q", "modifiers": ["ctrl"]},
        "config": ".config",
    },
    "xed": {
        "argv": ["env", "GSETTINGS_BACKEND=keyfile", "xed"],
        "app_id": "xed",
        "menus": ["View", "Edit", "Tools"],
        "dialog": {
            "menu": "Edit",
            "item": "Preferences",
            "title": "Xed Preferences",
            "close_button": "Close",
            "pages": "list",
            "pages_depth": 3,
            "toggles": True,
        },
        "quit": {"key": "q", "modifiers": ["ctrl"]},
        "config": ".config",
    },
    "pluma": {
        "argv": ["env", "GSETTINGS_BACKEND=keyfile", "pluma"],
        "app_id": "pluma",
        "menus": ["View", "Edit"],
        "dialog": {
            "menu": "Edit",
            "item": "Preferences",
            "title": "Pluma Preferences",
            "close_button": "Close",
        },
        "quit": {"key": "q", "modifiers": ["ctrl"]},
        "config": ".config",
    },
    "galculator": {
        "argv": ["galculator"],
        "app_id": "galculator",
        "menus": ["View"],
        "precreate": [".config/galculator"],
        "dialog": {
            "menu": "Edit",
            "item": "Preferences",
            "title": "galculator Preferences",
            "close_button": "Close",
        },
        "quit": {"key": "q", "modifiers": ["ctrl"]},
        "config": ".config",
    },
}


# --- configuration as key/value pairs --------------------------------------


def parse_ini(text):
    values, section = {}, ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
        elif "=" in line:
            key, _, value = line.partition("=")
            values[f"[{section}] {key.strip()}"] = value.strip()
    return values


def parse_xcu(text):
    values = {}
    for item in re.findall(r"<item [^\n]*?</item>", text):
        path = re.search(r'oor:path="([^"]*)"', item)
        props = re.findall(r'<prop oor:name="([^"]*)"[^>]*>(.*?)</prop>', item)
        node = re.search(r'<node oor:name="([^"]*)"', item)
        prefix = (path.group(1) if path else "") + (f"/{node.group(1)}" if node else "")
        for name, value in props:
            values[f"{prefix}/{name}"] = re.sub(r"<[^>]+>", "", value)
    return values


def parse_prefs_js(text):
    return {
        name: value.strip()
        for name, value in re.findall(r'user_pref\("([^"]+)",\s*(.*?)\);', text)
    }


def flatten(value, prefix=""):
    if isinstance(value, dict):
        out = {}
        for key, inner in value.items():
            out.update(flatten(inner, f"{prefix}.{key}" if prefix else str(key)))
        return out
    return {prefix: json.dumps(value)}


def parse_config(path):
    """{key: value} for a supported configuration file, else None."""
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        return None
    if path.name == "registrymodifications.xcu":
        return parse_xcu(text)
    if path.name in ("prefs.js", "user.js"):
        return parse_prefs_js(text)
    if path.suffix == ".json":
        try:
            return flatten(json.loads(text))
        except ValueError:
            return None
    if re.search(r"^\[[^\]\n]+\]$", text, re.MULTILINE):
        return parse_ini(text)
    return None


def snapshot(home, config):
    """{relative file: {key: value}} for every parsable file under config."""
    result = {}
    root = home / config
    if not root.is_dir():
        return result
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink() and path.stat().st_size < 1 << 20:
            values = parse_config(path)
            if values:
                result[str(path.relative_to(home))] = values
    return result


def changes(before, after):
    """[(file, key, old, new)] between two snapshots (None = absent)."""
    out = []
    for name in sorted(set(before) | set(after)):
        old, new = before.get(name, {}), after.get(name, {})
        for key in sorted(set(old) | set(new)):
            if old.get(key) != new.get(key):
                out.append((name, key, old.get(key), new.get(key)))
    return out


def write_ini_key(path, key, value):
    """Set "[section] key" to value in an INI/keyfile, keeping other lines."""
    atlas.write_ini(path, key, value)


# --- driving the application ------------------------------------------------


class Run:
    def __init__(self, spec):
        self.spec = spec
        self.session = core.create()["session"]
        self.home = core.session_path(self.session) / "home"

    def start(self):
        # Some applications create only the last directory of their config path.
        for directory in self.spec.get("precreate", []):
            (self.home / directory).mkdir(parents=True, exist_ok=True)
        core.request(self.session, "launch", argv=self.spec["argv"])
        if not core.wait(
            self.session, app_id=self.spec["app_id"], timeout=30, stable_ms=800
        )["satisfied"]:
            raise RuntimeError("application window did not appear")

    def nodes(self, window=None):
        return core.request(self.session, "ui", window=window, max_nodes=900)["nodes"]

    def open_menu(self, name):
        """GTK 3 menu bars open the first menu for any menu's click action, so
        open the first one and move right to the wanted menu."""
        menus = [n for n in self.nodes() if n["role"] == "menu" and n["depth"] <= 3]
        names = [m["name"] for m in menus]
        if name not in names:
            raise RuntimeError(f"menu {name} not found in {names}")
        core.request(self.session, "ui_action", node=menus[0]["id"], action="click")
        core.wait(self.session, stable_ms=300, timeout=5)
        if names.index(name):
            core.request(self.session, "key", key="Right", repeat=names.index(name))
            core.wait(self.session, stable_ms=300, timeout=5)

    def menu_items(self, name):
        self.open_menu(name)
        found, inside, depth = [], False, None
        for node in self.nodes():
            if node["role"] == "menu" and node["name"] == name:
                inside, depth = True, node["depth"]
                continue
            if inside:
                if node["depth"] <= depth:
                    break
                if "menu item" in node["role"] and node["depth"] == depth + 1:
                    found.append(node)
        return found

    def click_menu_item(self, menu, item):
        for node in self.menu_items(menu):
            if node["name"].strip().rstrip(".…").strip() == item:
                core.request(self.session, "ui_action", node=node["id"], action="click")
                core.wait(self.session, stable_ms=400, timeout=5)
                return
        raise RuntimeError(f"menu item {menu} > {item} not found")

    def open_dialog(self):
        dialog = self.spec["dialog"]
        self.click_menu_item(dialog["menu"], dialog["item"])
        if not core.wait(
            self.session, title=dialog["title"], timeout=10, stable_ms=600
        )["satisfied"]:
            raise RuntimeError("preferences dialog did not open")

    def dialog_nodes(self):
        return self.nodes(window=self.spec["dialog"]["title"])

    def page_tabs(self):
        """Pages of the preferences dialog: notebook tabs, or (spec "pages":
        "list") the rows of a sidebar list at "pages_depth", named by their label."""
        nodes = self.dialog_nodes()
        if self.spec["dialog"].get("pages") != "list":
            return [n for n in nodes if n["role"] == "page tab"]
        found = []
        for index, node in enumerate(nodes):
            if node["role"] == "list item" and node["depth"] == self.spec["dialog"][
                "pages_depth"
            ]:
                label = next(
                    (
                        m["name"]
                        for m in nodes[index + 1 :]
                        if m["role"] == "label" and m["depth"] > node["depth"]
                    ),
                    "",
                )
                found.append({**node, "name": label})
        return found

    def select_tab(self, tab, depth=None):
        """Select a notebook tab through its parent's accessibility Selection."""
        node = next(
            n
            for n in self.page_tabs()
            if n["name"] == tab and (depth is None or n["depth"] == depth)
        )
        if "selected" not in node["states"]:
            core.request(self.session, "ui_action", node=node["id"], action="select")
            core.wait(self.session, stable_ms=400, timeout=5)

    def check_boxes(self):
        """Check boxes; with spec "toggles", unnamed toggle buttons (switches)
        are named by the label before them."""
        nodes = self.dialog_nodes()
        found = [n for n in nodes if n["role"] == "check box"]
        if self.spec["dialog"].get("toggles"):
            label = ""
            for node in nodes:
                if node["role"] == "label" and node["name"].strip():
                    label = node["name"]
                elif node["role"] == "toggle button" and not node["name"].strip():
                    found.append({**node, "name": label})
        return found

    def close_dialog(self):
        button = self.spec["dialog"].get("close_button")
        if button:
            node = next(
                n
                for n in self.dialog_nodes()
                if n["role"] in ("push button", "button") and n["name"] == button
            )
            core.request(self.session, "ui_action", node=node["id"], action="press")
        else:
            core.request(self.session, "key", key="Escape")
        core.wait(
            self.session, title=self.spec["dialog"]["title"], gone=True, timeout=5
        )

    def quit(self):
        quit_key = self.spec["quit"]
        core.request(
            self.session, "key", key=quit_key["key"], modifiers=quit_key["modifiers"]
        )
        if not core.wait(
            self.session, app_id=self.spec["app_id"], gone=True, timeout=20
        )["satisfied"]:
            raise RuntimeError("application did not quit")
        time.sleep(0.5)

    def config(self):
        return snapshot(self.home, self.spec["config"])

    def close(self):
        core.destroy(self.session)


def perform(run, control, click=True):
    """Reach a control and (optionally) click it; returns its state before."""
    if control["kind"] == "menu":
        if click:
            run.click_menu_item(control["menu"], control["label"])
        else:
            run.menu_items(control["menu"])
            core.request(run.session, "key", key="Escape")
            core.request(run.session, "key", key="Escape")
        return None
    run.open_dialog()
    for depth, tab in control["tab"]:
        run.select_tab(tab, depth)
    node = next(n for n in run.check_boxes() if n["name"] == control["label"])
    state = "checked" in node["states"]
    if click:
        action = "toggle" if node["role"] == "toggle button" else "click"
        core.request(run.session, "ui_action", node=node["id"], action=action)
        core.wait(run.session, stable_ms=400, timeout=5)
    run.close_dialog()
    return state


def discover(spec):
    run = Run(spec)
    controls = []
    try:
        run.start()
        for menu in spec.get("menus", []):
            for node in run.menu_items(menu):
                label = node["name"].strip()
                if label and node["role"] != "menu" and not UNSAFE.search(label):
                    controls.append({"kind": "menu", "menu": menu, "label": label})
            core.request(run.session, "key", key="Escape")
            core.request(run.session, "key", key="Escape")
        if spec.get("dialog"):
            run.open_dialog()
            seen = set()

            def collect(path):
                for node in run.check_boxes():
                    key = (tuple(tab for _depth, tab in path), node["name"])
                    if node["name"].strip() and key not in seen:
                        seen.add(key)
                        controls.append(
                            {
                                "kind": "check box",
                                "tab": list(path),
                                "label": node["name"],
                                "default": "checked" in node["states"],
                            }
                        )

            tabs = run.page_tabs()
            top = min((n["depth"] for n in tabs), default=0)
            for tab in [n["name"] for n in tabs if n["depth"] == top]:
                run.select_tab(tab, top)
                inner = [
                    n
                    for n in run.page_tabs()
                    if n["depth"] > top
                ]
                if not inner:
                    collect([(top, tab)])
                for sub in inner:
                    run.select_tab(sub["name"], sub["depth"])
                    collect([(top, tab), (sub["depth"], sub["name"])])
            run.close_dialog()
    finally:
        run.close()
    return controls


def trial(spec, control, click=True):
    run = Run(spec)
    try:
        run.start()
        before = perform(run, control, click)
        run.quit()
        return run.config(), before
    finally:
        run.close()


def verify(spec, control, effect, default_config):
    """Apply the learned keys to a default configuration and check the app
    honours them: the control shows the learned state (check boxes), and one
    more click returns each key to its default value."""
    run = Run(spec)
    try:
        run.start()
        run.quit()  # creates the default configuration
        for name, key, _old, new in effect:
            path = run.home / name
            if new is None:
                return {"verified": False, "reason": "learned a removal"}
            write_ini_key(path, key, new)
        run.start()
        state = perform(run, control, click=True)
        run.quit()
        after = run.config()
    finally:
        run.close()
    restored = all(
        after.get(name, {}).get(key) == default_config.get(name, {}).get(key)
        or (old is None and after.get(name, {}).get(key) != new)
        for name, key, old, new in effect
    )
    shown = None if state is None else state != control.get("default")
    return {
        "verified": restored and shown is not False,
        "state_shown": shown,
        "restored_by_click": restored,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("app", choices=sorted(APPS))
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--negative-control",
        action="store_true",
        help="also verify each effect with its keys written at their default value",
    )
    args = parser.parse_args()
    spec = APPS[args.app]
    started = time.monotonic()
    controls = discover(spec)[: args.limit]
    print(json.dumps({"controls": len(controls)}), flush=True)
    # Controls: reach a menu and the dialog without clicking anything, twice.
    probes = [c for c in controls if c["kind"] == "check box"][:1] + [
        c for c in controls if c["kind"] == "menu"
    ][:1]
    baselines = [
        trial(spec, probe, click=False)[0] for probe in probes for _ in range(2)
    ]
    default = baselines[0]
    noise = {
        (name, key)
        for other in baselines[1:]
        for name, key, _o, _n in changes(default, other)
    }
    raw = []
    for control in controls:
        try:
            after, before_state = trial(spec, control)
            found = [c for c in changes(default, after) if (c[0], c[1]) not in noise]
            raw.append((control, found, before_state))
        except Exception as error:  # record and continue
            raw.append((control, None, f"{type(error).__name__}: {error}"))
    # Keys changed by most treatments come from any interaction, not a control.
    counts = {}
    for _control, found, _state in raw:
        for name, key, _o, _n in found or []:
            counts[(name, key)] = counts.get((name, key), 0) + 1
    common = {k for k, n in counts.items() if n > max(2, len(raw) // 2)}
    atlas = []
    for control, found, state in raw:
        entry = dict(control)
        if found is None:
            entry["error"] = state
        else:
            effect = [c for c in found if (c[0], c[1]) not in common]
            entry["effect"] = [
                {"file": "~/" + n, "key": k, "from": o, "to": v}
                for n, k, o, v in effect
            ]
            if effect:
                try:
                    entry.update(verify(spec, control, effect, default))
                    if args.negative_control and all(o is not None for _n, _k, o, _v in effect):
                        flat = [(n, k, o, o) for n, k, o, _v in effect]
                        entry["negative_control_verified"] = verify(
                            spec, control, flat, default
                        )["verified"]
                except Exception as error:
                    entry["verify_error"] = f"{type(error).__name__}: {error}"
        atlas.append(entry)
        print(json.dumps(entry, ensure_ascii=False)[:300], flush=True)
    summary = {
        "app": args.app,
        "controls": len(atlas),
        "with_effect": sum(bool(e.get("effect")) for e in atlas),
        "verified": sum(bool(e.get("verified")) for e in atlas),
        "negative_control_run": sum("negative_control_verified" in e for e in atlas),
        "negative_control_false_pass": sum(
            bool(e.get("negative_control_verified")) for e in atlas
        ),
        "errors": sum("error" in e for e in atlas),
        "noise_keys": len(noise),
        "interaction_keys": sorted(f"{n} {k}" for n, k in common),
        "minutes": round((time.monotonic() - started) / 60, 1),
    }
    print(json.dumps(summary), flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {"summary": summary, "atlas": atlas}, indent=1, ensure_ascii=False
            )
            + "\n"
        )


if __name__ == "__main__":
    sys.exit(main())
