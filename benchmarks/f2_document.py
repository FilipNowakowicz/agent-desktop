"""F2 native document edit: the fixture document and its evaluator.

A short agreement is written as OpenDocument (.odt) or Word (.docx). The task
changes the payment term in the payment clause only; two other clauses use the
same "30 days" wording. The evaluator reads only the saved file and the folder
it is in: every paragraph against the expected text, the format kept, and no
copies, renamed saves or lock files left behind.
"""

import random
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

ODF = {
    name: f"urn:oasis:names:tc:opendocument:xmlns:{name}:1.0"
    for name in ("office", "text")
}
WORD = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

TITLE = "Supply agreement"
PAYMENT = "Payment. Invoices are payable within 30 days of receipt."
PAID = "Payment. Invoices are payable within 14 days of receipt."
CLAUSES = [
    "Parties. This agreement is between Northwind Supplies and Harbor Cafe.",
    "Term. The agreement runs for twelve months from signature.",
    "Delivery. Goods are delivered within 30 days of each order.",
    PAYMENT,
    "Notice. Either party may end this agreement with 30 days written notice.",
    "Governing law. The law of the place of signature applies.",
]
GOAL = (
    "In the payment clause, change the payment term from 30 days to 14 days. "
    "Change nothing else."
)


def paragraphs(seed):
    """The document's paragraphs: a title, then numbered clauses whose order
    (after the parties) follows the seed."""
    rest = CLAUSES[1:]
    random.Random(seed).shuffle(rest)
    clauses = [CLAUSES[0], *rest]
    return [TITLE, *(f"{i}. {text}" for i, text in enumerate(clauses, 1))]


def expected(initial):
    return [p.replace(PAYMENT, PAID) if p.endswith(PAYMENT) else p for p in initial]


def write(path, lines):
    path = Path(path)
    if path.suffix == ".docx":
        write_docx(path, lines)
    else:
        write_odt(path, lines)


def write_odt(path, lines):
    office, text = ODF["office"], ODF["text"]
    root = ET.Element(f"{{{office}}}document-content")
    root.set(f"{{{office}}}version", "1.2")
    body = ET.SubElement(ET.SubElement(root, f"{{{office}}}body"), f"{{{office}}}text")
    for line in lines:
        ET.SubElement(body, f"{{{text}}}p").text = line
    mime = "application/vnd.oasis.opendocument.text"
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


def write_docx(path, lines):
    body = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{escape(line)}</w:t></w:r></w:p>'
        for line in lines
    )
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?><Types xmlns='
            '"http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType='
            '"application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns='
            '"http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
        )
        archive.writestr(
            "word/document.xml",
            f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{WORD}">'
            f"<w:body>{body}</w:body></w:document>",
        )


def escape(value):
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def read(path):
    """The saved document's non-empty paragraphs, or None if it cannot be read
    (saving can briefly expose an incomplete file)."""
    try:
        with ZipFile(path) as archive:
            if Path(path).suffix == ".docx":
                root = ET.fromstring(archive.read("word/document.xml"))
                found = [
                    "".join(t.text or "" for t in p.iter(f"{{{WORD}}}t"))
                    for p in root.iter(f"{{{WORD}}}p")
                ]
            else:
                root = ET.fromstring(archive.read("content.xml"))
                found = [
                    "".join(p.itertext())
                    for p in root.iter()
                    if p.tag in (f"{{{ODF['text']}}}p", f"{{{ODF['text']}}}h")
                ]
    except (OSError, BadZipFile, ET.ParseError, KeyError):
        return None
    return [p for p in found if p.strip()]


def evaluate(path, initial, closed=True):
    """Problems with the saved document, judged from the file and its folder."""
    path = Path(path)
    problems = []
    found = read(path)
    if found is None:
        return [f"{path.name} is missing or unreadable"]
    want = expected(initial)
    if found != want:
        if len(found) != len(want):
            problems.append(f"{len(found)} paragraphs, expected {len(want)}")
        for index, (got, wanted) in enumerate(zip(found, want, strict=False)):
            if got != wanted:
                role = "target" if wanted.endswith(PAID) else "bystander"
                problems.append(f"{role} paragraph {index} reads {got!r}")
    others = sorted(
        p.name
        for p in path.parent.iterdir()
        if p != path and not (p.name.startswith(".~lock.") and not closed)
    )
    if others:
        # A save in another format or name, or a lock left by an unclosed app.
        problems.append(f"other files beside the document: {others}")
    return problems
