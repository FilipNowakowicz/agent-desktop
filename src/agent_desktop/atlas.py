"""Experimental effect-atlas lookup: which control changes which setting.

Atlas files are produced by scripts/effect_atlas.py: for each control of an
application, where it is, its default state and the configuration keys it was
observed to change (verified by applying them alone). AGENT_DESKTOP_ATLAS names
a directory of atlas JSON files.
"""

import json
import os
import re
from pathlib import Path

STOP = {
    "a",
    "an",
    "and",
    "any",
    "are",
    "as",
    "be",
    "can",
    "do",
    "for",
    "from",
    "has",
    "how",
    "i",
    "in",
    "is",
    "it",
    "its",
    "make",
    "me",
    "my",
    "not",
    "of",
    "on",
    "or",
    "so",
    "that",
    "the",
    "this",
    "to",
    "turn",
    "use",
    "when",
    "with",
}


def words(text):
    return {
        w
        for w in re.findall(r"[a-z0-9]+", text.lower())
        if w not in STOP and len(w) > 1
    }


def location(entry):
    if entry["kind"] == "menu":
        return f"{entry['menu']} menu > {entry['label']}"
    tab = entry.get("tab", [])
    path = [tab] if isinstance(tab, str) else [step[-1] for step in tab]
    tabs = " > ".join(path)
    return f"Preferences dialog > {tabs} tab > check box {entry['label']!r}"


def load(directory=None):
    directory = directory or os.environ.get("AGENT_DESKTOP_ATLAS")
    if not directory:
        return []
    entries = []
    for path in sorted(Path(directory).glob("atlas-*.json")):
        data = json.loads(path.read_text())
        app = data["summary"]["app"]
        for entry in data["atlas"]:
            if entry.get("effect"):
                entries.append({"app": app, **entry})
    return entries


def search(query, app=None, limit=5, directory=None):
    """Controls whose label, location or configuration keys match the query."""
    entries = load(directory)
    if not entries:
        raise ValueError(
            "No atlas available; set AGENT_DESKTOP_ATLAS to a directory of atlas files"
        )
    wanted = words(query)
    scored = []
    for entry in entries:
        if app and entry["app"] != app:
            continue
        label = words(entry["label"]) | words(location(entry))
        keys = set()
        for effect in entry["effect"]:
            keys |= words(effect["key"].split("] ")[-1])
        score = 2 * len(wanted & label) + len(wanted & keys)
        if score or not wanted:  # no search words: list the app's controls
            scored.append((score, entry))
    scored.sort(key=lambda item: (-item[0], not item[1].get("verified")))
    return [
        {
            "app": entry["app"],
            "control": location(entry),
            "default_checked": entry.get("default"),
            "changes": [
                f"{e['file']} {e['key']}: {e['from']} -> {e['to']}"
                for e in entry["effect"]
            ],
            "verified": bool(entry.get("verified")),
        }
        for _score, entry in scored[: limit if wanted else 60]
    ]


def write_ini(path, key, value):
    """Set "[section] name" in an INI/GLib keyfile, keeping other lines."""
    section, _, name = key.partition("] ")
    header = section + "]"
    lines = path.read_text().splitlines() if path.exists() else []
    if header not in lines:
        lines += ["", header, f"{name}={value}"]
    else:
        index = lines.index(header) + 1
        while index < len(lines) and not lines[index].startswith("["):
            if lines[index].split("=", 1)[0].strip() == name:
                lines[index] = f"{name}={value}"
                break
            index += 1
        else:
            lines.insert(index, f"{name}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def apply(home, app, control, directory=None):
    """Write the configuration change learned for `control` ("Menu > Label",
    the label alone, or the control text desktop_atlas returned) into a
    session home. Only verified entries with keyfile/INI effects are applied."""
    matches = [
        entry
        for entry in load(directory)
        if entry["app"] == app
        and control in (entry["label"], location(entry))
        and entry.get("verified")
    ]
    if not matches:
        raise ValueError(
            f"No verified atlas entry for {app}: {control!r}; use desktop_atlas to "
            "find the exact control text"
        )
    entry = matches[0]
    written = []
    for effect in entry["effect"]:
        if not effect["key"].startswith("[") or effect["to"] is None:
            raise ValueError("This entry's effect cannot be applied as a key")
        path = Path(home) / effect["file"].removeprefix("~/")
        write_ini(path, effect["key"], effect["to"])
        written.append(f"{effect['file']} {effect['key']} = {effect['to']}")
    return {"app": app, "control": location(entry), "written": written}
