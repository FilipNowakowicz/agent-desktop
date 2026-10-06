"""Exercise Writer/Calc in private sessions and verify saved OpenDocument files."""

import argparse
import json
import os
import shutil
import time
import uuid
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from agent_desktop import core
from agent_desktop.worker import owned_processes

NS = {
    name: f"urn:oasis:names:tc:opendocument:xmlns:{name}:1.0"
    for name in ("office", "table", "text")
}
WRITER_TEXT = "Private document café λ\nBudget: 4200"


def wait_for(condition, timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if value := condition():
            return value
        time.sleep(0.1)
    raise RuntimeError("Timed out waiting for an observed office result")


def active(session):
    return next(
        (
            w
            for w in core.request(session, "windows")["windows"]
            if "activated" in w["states"]
        ),
        {},
    )


# Settings a new profile would otherwise get from its first-run dialogs, which
# can appear seconds after the document under load and take the input.
FIRST_RUN_DONE = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry"
 xmlns:xs="http://www.w3.org/2001/XMLSchema"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<item oor:path="/org.openoffice.Office.Common/Misc"><prop oor:name="FirstRun" oor:op="fuse"><value>false</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Misc"><prop oor:name="ShowTipOfTheDay" oor:op="fuse"><value>false</value></prop></item>
<item oor:path="/org.openoffice.Setup/Product"><prop oor:name="ooSetupLastVersion" oor:op="fuse"><value>99.0</value></prop></item>
</oor:items>
"""


def launch(session, component, files=()):
    directory = core.session_path(session) / "home/office-profile"
    seed = directory / "user/registrymodifications.xcu"
    if not seed.exists():
        seed.parent.mkdir(parents=True)
        seed.write_text(FIRST_RUN_DONE)
    profile = directory.as_uri()
    core.request(
        session,
        "launch",
        argv=[
            "env",
            "GDK_BACKEND=wayland",
            "SAL_USE_VCLPLUGIN=gtk3",
            "libreoffice",
            "-env:UserInstallation=" + profile,
            "--norestore",
            "--nofirststartwizard",
            "--" + component.lower(),
            *map(str, files),
        ],
    )
    wait_for(
        lambda: any(
            component in w["title"] for w in core.request(session, "windows")["windows"]
        )
    )
    # New profiles can show a delayed Welcome or Tip dialog after the document
    # maps. This fixture handles those known dialogs, then verifies document focus.
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        window = active(session)
        if window.get("title", "").startswith(
            ("Welcome to LibreOffice", "Tip of the Day")
        ):
            core.request(session, "focus", window=window["id"])
            core.request(session, "key", key="F4", modifiers=["alt"])
        time.sleep(0.1)

    def document_focused():
        window = active(session)
        return window if component in window.get("title", "") else None

    window = wait_for(document_focused)
    core.request(session, "focus", window=window["id"])


def content(path):
    try:
        with ZipFile(path) as archive:
            return ET.fromstring(archive.read("content.xml"))
    except (OSError, BadZipFile, ET.ParseError, KeyError):
        return None  # Saving can briefly expose an incomplete file.


def writer_matches(path):
    root = content(path)
    if root is None:
        return False
    paragraphs = ["".join(p.itertext()) for p in root.findall(".//text:p", NS)]
    return paragraphs == WRITER_TEXT.split("\n")


def writer(session, directory):
    target = directory / "document café λ.odt"
    launch(session, "Writer")
    before = core.request(session, "screenshot")
    core.request(session, "type", text=WRITER_TEXT)
    core.request(session, "key", key="s", modifiers=["ctrl"])
    wait_for(lambda: active(session).get("title") in ("Save", "Save As"))
    core.request(session, "screenshot")
    core.request(session, "key", key="a", modifiers=["ctrl"])
    core.request(session, "type", text=str(target))
    time.sleep(0.3)  # GTK file chooser path validation; not a generic readiness API.
    core.request(session, "key", key="Return")
    wait_for(lambda: writer_matches(target))
    wait_for(lambda: target.name in active(session).get("title", ""))
    return {
        "file": str(target),
        "before": before,
        "after": core.request(session, "screenshot"),
    }


def spreadsheet(path):
    root = ET.Element("{" + NS["office"] + "}document-content")
    root.set("{" + NS["office"] + "}version", "1.2")
    body = ET.SubElement(root, "{" + NS["office"] + "}body")
    sheet = ET.SubElement(body, "{" + NS["office"] + "}spreadsheet")
    table = ET.SubElement(sheet, "{" + NS["table"] + "}table")
    table.set("{" + NS["table"] + "}name", "Budget")
    for label, number in (
        ("Item", None),
        ("Apples", 12),
        ("Pears", 8),
        ("Total", None),
    ):
        row = ET.SubElement(table, "{" + NS["table"] + "}table-row")
        cell = ET.SubElement(row, "{" + NS["table"] + "}table-cell")
        cell.set("{" + NS["office"] + "}value-type", "string")
        ET.SubElement(cell, "{" + NS["text"] + "}p").text = label
        cell = ET.SubElement(row, "{" + NS["table"] + "}table-cell")
        if number is not None:
            cell.set("{" + NS["office"] + "}value-type", "float")
            cell.set("{" + NS["office"] + "}value", str(number))
            ET.SubElement(cell, "{" + NS["text"] + "}p").text = str(number)
    mime = "application/vnd.oasis.opendocument.spreadsheet"
    manifest = (
        '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"'
        ' manifest:version="1.2"><manifest:file-entry manifest:full-path="/"'
        f' manifest:media-type="{mime}"/><manifest:file-entry manifest:full-path="content.xml"'
        ' manifest:media-type="text/xml"/></manifest:manifest>'
    )
    with ZipFile(path, "w") as archive:
        archive.writestr("mimetype", mime)
        archive.writestr("content.xml", ET.tostring(root))
        archive.writestr("META-INF/manifest.xml", manifest)


def calc_matches(path):
    root = content(path)
    if root is None:
        return False
    rows = root.findall(".//table:table-row", NS)
    if len(rows) < 4:
        return False
    cells = [row.findall("table:table-cell", NS) for row in rows[:4]]
    if any(len(row) < 2 for row in cells):
        return False
    labels = ["".join(row[0].itertext()) for row in cells]
    values = [row[1].get("{" + NS["office"] + "}value") for row in cells]
    formula = cells[3][1].get("{" + NS["table"] + "}formula")
    return (
        labels == ["Item", "Apples", "Pears", "Total"]
        and values[1:] == ["12", "8", "20"]
        and formula == "of:=SUM([.B2:.B3])"
    )


def cells(path):
    """{"A1": text or formula} for the first table, expanding repeated cells."""
    root = content(path)
    if root is None:
        return None
    result = {}
    table = root.find(".//table:table", NS)
    row_number = 0
    for row in table.findall("table:table-row", NS):
        rows = int(row.get("{" + NS["table"] + "}number-rows-repeated", 1))
        column = 0
        for cell in row.findall("table:table-cell", NS):
            columns = int(cell.get("{" + NS["table"] + "}number-columns-repeated", 1))
            value = cell.get("{" + NS["table"] + "}formula") or "".join(cell.itertext())
            if value and rows == 1:
                for offset in range(min(columns, 26 - column)):
                    result[f"{chr(65 + column + offset)}{row_number + 1}"] = value
            column += columns
        row_number += rows
    return result


ROWS_START = 10
ROWS = (("Paper", "4", "2"), ("Pens", "1", "9"), ("Stapler", "12", "2"))


def calc_rows(session, directory):
    """Type rows with Tab, Home and Down in one sequence, as an agent would."""
    target = directory / "rows.ods"
    spreadsheet(target)
    launch(session, "Calc", [target])
    core.request(session, "key", key="F5", modifiers=["ctrl", "shift"])
    time.sleep(0.2)
    core.request(session, "key", key="a", modifiers=["ctrl"])
    core.request(session, "type", text=f"A{ROWS_START}")
    core.request(session, "key", key="Return")
    time.sleep(0.2)
    steps = [{"action": "type", "text": "Item\tPrice\tQty\tCost\t"}]
    for offset, (item, price, quantity) in enumerate(ROWS, 1):
        row = ROWS_START + offset
        steps += [
            {"action": "key", "key": "Home"},
            {"action": "key", "key": "Down"},
            {
                "action": "type",
                "text": f"{item}\t{price}\t{quantity}\t=B{row}*C{row}\t",
            },
        ]
    last = ROWS_START + len(ROWS)
    steps += [
        {"action": "key", "key": "Home"},
        {"action": "key", "key": "Down"},
        {"action": "type", "text": f"Total\t\t\t=SUM(D{ROWS_START + 1}:D{last})\t"},
    ]
    core.run_actions(session, steps)
    core.request(session, "key", key="s", modifiers=["ctrl"])
    try:
        wait_for(lambda: calc_rows_match(cells(target) or {}), timeout=20)
    except RuntimeError:
        pass  # The caller compares and reports what was saved.
    return cells(target)


def calc_name_box(session, directory):
    """Close the Welcome dialog, then jump with the Name Box and type at once.

    In pilot session 29 the text arrived before the shortcut had moved focus,
    while Calc was still returning focus from the closed dialog. This uses a
    new profile (no seed) so that the dialog appears.
    """
    target = directory / "jump.ods"
    spreadsheet(target)
    profile = (core.session_path(session) / "home/fresh-profile").as_uri()
    core.request(
        session,
        "launch",
        argv=[
            "env",
            "GDK_BACKEND=wayland",
            "SAL_USE_VCLPLUGIN=gtk3",
            "libreoffice",
            "-env:UserInstallation=" + profile,
            "--norestore",
            "--calc",
            str(target),
        ],
    )
    welcome = core.wait(session, title="Welcome", timeout=60, stable_ms=500)
    steps = []
    if welcome["satisfied"]:
        steps += [
            {"action": "key", "key": "Escape"},
            {"action": "wait", "title": "Welcome", "gone": True, "timeout": 10},
        ]
    steps += [
        {"action": "key", "key": "F5", "modifiers": ["ctrl", "shift"]},
        {"action": "type", "text": "D6\n"},
        {"action": "type", "text": "marker\n"},
        {"action": "key", "key": "s", "modifiers": ["ctrl"]},
    ]
    core.run_actions(session, steps)
    # Saving an .ods asks nothing; wait for the file to show the marker.
    try:
        wait_for(lambda: (cells(target) or {}).get("D6") == "marker", timeout=20)
    except RuntimeError:
        pass  # The caller compares and reports what was saved.
    return cells(target)


def calc_rows_match(found):
    expected = {f"A{ROWS_START}": "Item", f"D{ROWS_START}": "Cost"}
    for offset, (item, price, quantity) in enumerate(ROWS, 1):
        row = ROWS_START + offset
        expected.update(
            {
                f"A{row}": item,
                f"B{row}": price,
                f"C{row}": quantity,
                f"D{row}": f"of:=[.B{row}]*[.C{row}]",
            }
        )
    last = ROWS_START + len(ROWS)
    expected[f"A{last + 1}"] = "Total"
    expected[f"D{last + 1}"] = f"of:=SUM([.D{ROWS_START + 1}:.D{last}])"
    return {k: found.get(k) for k in expected} == expected


def calc(session, directory):
    target = directory / "budget.ods"
    spreadsheet(target)
    launch(session, "Calc", [target])
    before = core.request(session, "screenshot")
    # Explicit cell selection avoids relying on unobserved rapid arrow moves.
    # Calc's documented Ctrl+Shift+F5 focuses the Name Box.
    core.request(session, "key", key="F5", modifiers=["ctrl", "shift"])
    time.sleep(0.2)
    core.request(session, "key", key="a", modifiers=["ctrl"])
    core.request(session, "type", text="B4")
    core.request(session, "key", key="Return")
    time.sleep(0.2)
    core.request(session, "screenshot")
    core.request(session, "type", text="=SUM(B2:B3)")
    core.request(session, "key", key="Return")
    core.request(session, "key", key="s", modifiers=["ctrl"])
    wait_for(lambda: calc_matches(target))
    return {
        "file": str(target),
        "before": before,
        "after": core.request(session, "screenshot"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--component", choices=("writer", "calc", "both"), default="both"
    )
    args = parser.parse_args()
    if not shutil.which("libreoffice"):
        parser.error("LibreOffice with its GTK3 integration is required")
    directory = (Path("artifacts/office") / uuid.uuid4().hex[:12]).resolve()
    directory.mkdir(parents=True)
    previous = os.environ.get("AGENT_DESKTOP_STATE_DIR")
    os.environ["AGENT_DESKTOP_STATE_DIR"] = str(directory / "state")
    records = []
    try:
        for name in ("writer", "calc"):
            if args.component not in (name, "both"):
                continue
            record = {"component": name, "passed": False}
            records.append(record)
            session = core.create()["session"]
            info = core.manifest(session)
            record["session"] = session
            try:
                record.update(
                    {"writer": writer, "calc": calc}[name](session, directory)
                )
                record["passed"] = True
            except Exception as error:
                record["error"] = str(error)
                record["logs"] = core.logs(session)
                try:
                    record["windows"] = core.request(session, "windows")
                    record["failure_screenshot"] = core.request(session, "screenshot")
                except core.DesktopError as inspection_error:
                    record["inspection_error"] = str(inspection_error)
            finally:
                try:
                    record["cleanup"] = core.destroy(session)
                    wait_for(
                        lambda info=info: not owned_processes(info["token"]), timeout=10
                    )
                except Exception as cleanup_error:
                    record["cleanup_error"] = str(cleanup_error)
                    record["passed"] = False
                record["processes_remaining"] = owned_processes(info["token"])
    finally:
        if previous is None:
            os.environ.pop("AGENT_DESKTOP_STATE_DIR", None)
        else:
            os.environ["AGENT_DESKTOP_STATE_DIR"] = previous
        (directory / "report.json").write_text(json.dumps(records, indent=2) + "\n")
    print(json.dumps({"artifacts": str(directory), "results": records}, indent=2))
    return 0 if records and all(r["passed"] for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
