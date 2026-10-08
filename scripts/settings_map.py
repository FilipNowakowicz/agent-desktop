"""Differential settings discovery: map GUI check items to configuration keys.

For LibreOffice Calc's View and Tools menus (or --menus), each checkable menu
item is toggled once in a fresh profile. Its configuration after quitting is
compared with two untouched control profiles; lines that differ between the
two controls are noise (positions, times) and ignored. What remains is the
item's effect. Each learned effect is then verified: written alone into a
fresh profile, the menu item must show the toggled state.

    uv run scripts/settings_map.py [--menus View Tools] [--limit N] [--output F]
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

os.environ["AGENT_DESKTOP_EFFECTS"] = "1"

from agent_desktop import core  # noqa: E402

CALC = ["libreoffice", "--calc", "--norestore", "--nologo"]
XCU = ".config/libreoffice/4/user/registrymodifications.xcu"
MENU_KEYS = {
    "File": "f",
    "Edit": "e",
    "View": "v",
    "Insert": "i",
    "Format": "o",
    "Sheet": "s",
    "Data": "d",
    "Tools": "t",
    "Window": "w",
}


class Profile:
    def __init__(self, name):
        self.name = name
        try:
            core.delete_profile(name)
        except core.DesktopError:
            pass
        self.session = core.create(profile=name)["session"]

    @property
    def xcu(self):
        return core.profile_path(self.name) / "home" / XCU

    def open(self):
        core.request(self.session, "launch", argv=CALC)
        if not core.wait(self.session, title="Calc", timeout=90, stable_ms=1500)[
            "satisfied"
        ]:
            raise RuntimeError("Calc did not open")

    def quit(self):
        result = core.request(self.session, "key", key="q", modifiers=["ctrl"])
        core.wait_effect(
            self.session, result["effects"]["effect_id"], "~/" + XCU, timeout=20
        )
        if not core.wait(
            self.session, app_id="libreoffice-calc", gone=True, timeout=20
        )["satisfied"]:
            # A "save changes?" dialog: discard (toggles may mark the document).
            core.request(self.session, "key", key="d", modifiers=["alt"])
            core.wait(self.session, app_id="libreoffice-calc", gone=True, timeout=20)
        time.sleep(1)

    def menu(self, name):
        core.request(self.session, "key", key=MENU_KEYS[name], modifiers=["alt"])
        core.wait(self.session, stable_ms=500, timeout=5)
        nodes = core.request(self.session, "ui", max_nodes=800)["nodes"]
        # Items of the open menu: check items one level below the menu node.
        items, inside, depth = [], False, None
        for node in nodes:
            if node["role"] == "menu" and node["name"] == name and depth is None:
                inside, depth = True, node["depth"]
                continue
            if inside:
                if node["depth"] <= depth:
                    break
                if node["role"] == "check menu item" and node["depth"] == depth + 1:
                    items.append(node)
        return items

    def close(self):
        core.destroy(self.session)
        core.delete_profile(self.name)


def items_of(path):
    """Configuration <item> lines (one per line in registrymodifications.xcu)."""
    return {
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip().startswith("<item ")
    }


def control(name):
    profile = Profile(name)
    try:
        profile.open()
        profile.quit()
        profile.open()  # a second start, as treatments get
        profile.quit()
        return items_of(profile.xcu)
    finally:
        profile.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--menus", nargs="*", default=["View", "Tools"])
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    started = time.monotonic()
    first, second = control("map-control-1"), control("map-control-2")
    noise = first ^ second
    baseline = first & second
    # Discover the checkable items once.
    probe = Profile("map-probe")
    try:
        probe.open()
        catalog = []
        for menu in args.menus:
            for node in probe.menu(menu):
                catalog.append(
                    {"menu": menu, "item": node["name"], "states": node["states"]}
                )
            core.request(probe.session, "key", key="Escape")
            core.request(probe.session, "key", key="Escape")
    finally:
        probe.close()
    catalog = catalog[: args.limit]
    results = []
    for entry in catalog:
        record = dict(entry)
        profile = Profile("map-item")
        try:
            profile.open()
            profile.quit()
            profile.open()
            target = next(
                (n for n in profile.menu(entry["menu"]) if n["name"] == entry["item"]),
                None,
            )
            if target is None:
                record["error"] = "item not found"
                continue
            core.request(
                profile.session, "ui_action", node=target["id"], action="click"
            )
            time.sleep(0.5)
            profile.quit()
            after = items_of(profile.xcu)
            learned = sorted(line for line in after - baseline if line not in noise)
            removed = sorted(line for line in baseline - after if line not in noise)
            record["learned"] = learned
            record["removed"] = removed
        except Exception as error:  # record and continue
            record["error"] = f"{type(error).__name__}: {error}"
        finally:
            profile.close()
        if record.get("learned"):
            # Verify: apply only the learned lines to a fresh profile.
            check = Profile("map-verify")
            try:
                check.open()
                check.quit()
                text = check.xcu.read_text()
                check.xcu.write_text(
                    re.sub(
                        r"</oor:items>",
                        "\n".join(record["learned"]) + "\n</oor:items>",
                        text,
                    )
                )
                check.open()
                node = next(
                    (
                        n
                        for n in check.menu(entry["menu"])
                        if n["name"] == entry["item"]
                    ),
                    None,
                )
                record["applied_states"] = node["states"] if node else None
                record["verified"] = bool(node) and (
                    ("checked" in node["states"]) != ("checked" in entry["states"])
                )
            except Exception as error:
                record["verify_error"] = f"{type(error).__name__}: {error}"
            finally:
                check.close()
        results.append(record)
        print(json.dumps(record, ensure_ascii=False)[:400], flush=True)
    summary = {
        "menus": args.menus,
        "items": len(results),
        "with_effect": sum(bool(r.get("learned")) for r in results),
        "verified": sum(bool(r.get("verified")) for r in results),
        "noise_lines": len(noise),
        "minutes": round((time.monotonic() - started) / 60, 1),
    }
    print(json.dumps(summary))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {"summary": summary, "results": results}, indent=1, ensure_ascii=False
            )
            + "\n"
        )


if __name__ == "__main__":
    sys.exit(main())
