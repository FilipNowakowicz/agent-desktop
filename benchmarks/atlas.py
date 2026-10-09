"""Settings tasks for the effect-atlas A/B: change a preference described in
everyday words; the check reads the application's saved configuration."""

from pathlib import Path

from .tasks import Task


def ini_value(path, section, key):
    current = None
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return None
    for line in lines:
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
        elif current == section and line.split("=", 1)[0].strip() == key:
            return line.split("=", 1)[1].strip()
    return None


class MousepadSetting(Task):
    requires = ("mousepad",)
    section = "org/xfce/mousepad/preferences/view"

    def __init__(self, name, goal, key, value, section=None):
        self.name = name
        self.goal = goal
        self.key = key
        self.value = value
        if section:
            self.section = section

    def setup(self, context):
        return ["mousepad"], (
            f"In the open Mousepad window: {self.goal} The change must be saved as "
            "Mousepad's own setting (it should still apply the next time Mousepad "
            "starts)."
        )

    def check(self, context):
        path = Path(context.home) / ".config/Mousepad/settings.conf"
        value = ini_value(path, self.section, self.key)
        return value == self.value, {"key": self.key, "value": value}


ATLAS_TASKS = [
    MousepadSetting(
        "atlas-highlight-line",
        "make it highlight the line the cursor is on.",
        "highlight-current-line",
        "true",
    ),
    MousepadSetting(
        "atlas-visible-whitespace",
        "make spaces and tabs visible as symbols in the text.",
        "show-whitespace",
        "true",
    ),
    MousepadSetting(
        "atlas-bracket-partner",
        "when the cursor is next to a bracket, emphasise its partner bracket.",
        "match-braces",
        "true",
    ),
    MousepadSetting(
        "atlas-monospace",
        "stop it from using the system-wide monospace font.",
        "use-default-monospace-font",
        "false",
    ),
]
