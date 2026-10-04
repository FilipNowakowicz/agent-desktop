"""Office GUI tasks checked from saved files rather than completion claims."""

from pathlib import Path

from agent_desktop import core
from scripts import office_smoke

from .tasks import Task


def command(context, component, files=()):
    profile = (core.session_path(context.session) / "home/office-profile").as_uri()
    return [
        "env",
        "GDK_BACKEND=wayland",
        "SAL_USE_VCLPLUGIN=gtk3",
        "libreoffice",
        "-env:UserInstallation=" + profile,
        "--norestore",
        "--nofirststartwizard",
        "--" + component,
        *map(str, files),
    ]


class WriterDocument(Task):
    name = "office-writer-document"
    requires = ("libreoffice",)

    def setup(self, context):
        context.target = context.directory / "document café λ.odt"
        return command(context, "writer"), (
            "Create a Writer document with exactly these two paragraphs:\n"
            + office_smoke.WRITER_TEXT
            + f"\nSave it in ODT format to {context.target}. "
            "Handle any first-run dialogs. Work through screenshots and GUI input."
        )

    def check(self, context):
        return office_smoke.writer_matches(context.target), str(context.target)


class CalcBudget(Task):
    name = "office-calc-budget"
    requires = ("libreoffice",)

    def setup(self, context):
        context.target = context.directory / "budget.ods"
        office_smoke.spreadsheet(context.target)
        return command(context, "calc", [context.target]), (
            "In the open Calc budget sheet, enter a SUM formula in cell B4 that adds "
            "the amounts in B2 and B3. Save the spreadsheet to its existing file. "
            "Preserve the other cells. Handle any first-run dialogs. "
            "Work through screenshots and GUI input."
        )

    def check(self, context):
        return office_smoke.calc_matches(Path(context.target)), str(context.target)


OFFICE_TASKS = [WriterDocument(), CalcBudget()]
