"""Commands printed for the person, written so that they run as printed.

The MCP server is often started as `uv --directory CHECKOUT run agent-desktop-mcp`.
`uv run` puts the project's virtual environment first on the server's own PATH,
so `agent-desktop` resolves there but not in the person's terminal. A printed
command therefore uses the bare name only when the PATH without that virtual
environment finds it, and the installed script's absolute path otherwise.
"""

import os
import shlex
import shutil
import sys
from pathlib import Path

NAME = "agent-desktop"


def prefix(environ=None, base=None):
    """The words that start a CLI command the person can type, as a string."""
    environ = os.environ if environ is None else environ
    override = environ.get("AGENT_DESKTOP_CLI")
    if override:
        return override
    base = Path(sys.prefix if base is None else base)
    bin_directory = base / "bin"
    own = bin_directory / NAME
    entries = [
        entry
        for entry in environ.get("PATH", "").split(os.pathsep)
        if entry and Path(entry).resolve() != bin_directory.resolve()
    ]
    if shutil.which(NAME, path=os.pathsep.join(entries)):
        return NAME
    if own.is_file() and os.access(own, os.X_OK):
        return shlex.quote(str(own))
    return NAME


def command(*words, environ=None, base=None):
    """A full printed command: the CLI prefix followed by quoted words."""
    return " ".join([prefix(environ, base), *(shlex.quote(str(w)) for w in words)])
