"""Effect induction: learn a setting's effect from one GUI change, apply it directly.

1. Demonstrate: in a fresh profile, turn Calc's Tools > AutoInput off through
   the menu; the effect ledger records the configuration lines that changed.
2. Apply: in another fresh profile, write only those lines into Calc's
   configuration (no GUI), then open the menu and read the item's state.
3. Control: a third fresh profile without the change.

    uv run scripts/effect_induction_demo.py
"""

import json
import os
import re
import time

os.environ["AGENT_DESKTOP_EFFECTS"] = "1"

from agent_desktop import core  # noqa: E402

CALC = ["libreoffice", "--calc", "--norestore", "--nologo"]
XCU = "~/.config/libreoffice/4/user/registrymodifications.xcu"


def open_calc(session):
    core.request(session, "launch", argv=CALC)
    if not core.wait(session, title="Calc", timeout=90, stable_ms=1500)["satisfied"]:
        raise RuntimeError("Calc did not open")


def autoinput_node(session):
    core.request(session, "key", key="t", modifiers=["alt"])
    core.wait(session, stable_ms=500, timeout=5)
    for node in core.request(session, "ui", max_nodes=600)["nodes"]:
        if node["name"] == "AutoInput":
            return node
    raise RuntimeError("AutoInput menu item not found")


def quit_calc(session):
    """Ctrl+Q and wait for the configuration write that follows."""
    result = core.request(session, "key", key="q", modifiers=["ctrl"])
    waited = core.wait_effect(session, result["effects"]["effect_id"], XCU, timeout=20)
    core.wait(session, app_id="libreoffice-calc", gone=True, timeout=20)
    return waited


def fresh(profile):
    try:
        core.delete_profile(profile)
    except core.DesktopError:
        pass
    return core.create(profile=profile)["session"]


def main():
    report = {}
    # 1. Demonstrate through the GUI.
    session = fresh("induce-a")
    try:
        open_calc(session)
        node = autoinput_node(session)
        report["before_demo"] = node["states"]
        clicked = core.request(session, "ui_action", node=node["id"], action="click")
        report["click_effects"] = clicked.get("effects")
        time.sleep(0.5)
        waited = quit_calc(session)
        report["quit_effects"] = waited["effects"]
    finally:
        core.destroy(session)
    entries = [e for e in waited["effects"].get("app_state", []) if e["path"] == XCU]
    added = [
        line[1:] for e in entries for line in e.get("diff", []) if line.startswith("+")
    ]
    learned = [line for line in added if "AutoInput" in line]
    report["learned"] = learned
    if not learned:
        # The diff in app_state is shortened; read the full change from the file.
        path = core.profile_path("induce-a") / "home" / XCU[2:]
        learned = [
            line for line in path.read_text().splitlines() if "AutoInput" in line
        ]
        report["learned_from_file"] = learned
    # 2. Apply the effect directly to a fresh profile.
    results = {}
    for profile, apply in (("induce-b", True), ("induce-c", False)):
        session = fresh(profile)
        try:
            open_calc(session)  # creates the default configuration
            quit_calc(session)
            if apply:
                path = core.profile_path(profile) / "home" / XCU[2:]
                text = path.read_text()
                text = re.sub(
                    r"</oor:items>", "\n".join(learned) + "\n</oor:items>", text
                )
                path.write_text(text)
            open_calc(session)
            results[profile] = autoinput_node(session)["states"]
            core.request(session, "key", key="Escape")
        finally:
            core.destroy(session)
    report["applied_states"] = results["induce-b"]
    report["control_states"] = results["induce-c"]
    report["shown"] = (
        "checked" in report["before_demo"]
        and "checked" not in results["induce-b"]
        and "checked" in results["induce-c"]
    )
    for profile in ("induce-a", "induce-b", "induce-c"):
        core.delete_profile(profile)
    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
