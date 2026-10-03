"""Stdio MCP adapter over the same session API used by the CLI."""

import json

from mcp.server.fastmcp import FastMCP, Image
from mcp.types import TextContent

from . import core

mcp = FastMCP("Private desktop")


@mcp.tool()
def desktop_create(mode: str = "headless") -> dict:
    """Create a private Linux desktop. Visible mode opens a nested host Wayland window."""
    return core.create(mode)


@mcp.tool()
def desktop_list() -> list[dict]:
    """List desktop sessions and their current availability."""
    return core.sessions()


@mcp.tool()
def desktop_status(session: str) -> dict:
    """Get session health and application exit codes."""
    return core.request(session, "status")


@mcp.tool()
def desktop_launch(session: str, argv: list[str]) -> dict:
    """Launch an application argument list in the session's private environment."""
    return core.request(session, "launch", argv=argv)


@mcp.tool()
def desktop_windows(session: str) -> dict:
    """List private desktop windows: id, title, app_id, states and parent."""
    return core.request(session, "windows")


@mcp.tool()
def desktop_focus(session: str, window: str) -> dict:
    """Activate a private desktop window by the id from desktop_windows."""
    return core.request(session, "focus", window=window)


@mcp.tool(structured_output=False)
def desktop_screenshot(session: str) -> list:
    """Return a private desktop PNG plus dimensions, artifact path and observation.

    Pass the observation token to input tools to refuse input if windows, focus
    or the output changed since this screenshot.
    """
    capture = core.request(session, "screenshot")
    return [
        TextContent(type="text", text=json.dumps(capture)),
        Image(path=capture["path"]),
    ]


@mcp.tool()
def desktop_type(session: str, text: str, observation: str | None = None) -> dict:
    """Type up to 10000 characters into the private focused app. Verify the result afterward."""
    return core.request(session, "type", text=text, observation=observation)


@mcp.tool()
def desktop_key(
    session: str,
    key: str,
    modifiers: list[str] | None = None,
    observation: str | None = None,
) -> dict:
    """Send a keysym such as Return with optional ctrl/alt/shift/logo modifiers."""
    return core.request(
        session, "key", key=key, modifiers=modifiers or [], observation=observation
    )


@mcp.tool()
def desktop_click(
    session: str, x: int, y: int, button: str = "left", observation: str | None = None
) -> dict:
    """Click private screenshot coordinates at scale 1; fails outside the desktop."""
    return core.request(
        session, "click", x=x, y=y, button=button, observation=observation
    )


@mcp.tool()
def desktop_move(session: str, x: int, y: int, observation: str | None = None) -> dict:
    """Move only the private desktop pointer to screenshot coordinates."""
    return core.request(session, "move", x=x, y=y, observation=observation)


@mcp.tool()
def desktop_drag(
    session: str,
    x: int,
    y: int,
    to_x: int,
    to_y: int,
    button: str = "left",
    observation: str | None = None,
) -> dict:
    """Press at (x, y), move in steps to (to_x, to_y) and release, in the private desktop."""
    return core.request(
        session,
        "drag",
        x=x,
        y=y,
        to_x=to_x,
        to_y=to_y,
        button=button,
        observation=observation,
    )


@mcp.tool()
def desktop_scroll(
    session: str, dy: int, dx: int = 0, observation: str | None = None
) -> dict:
    """Scroll the private desktop at its current pointer location."""
    return core.request(session, "scroll", dy=dy, dx=dx, observation=observation)


@mcp.tool()
def desktop_logs(session: str) -> dict:
    """Read bounded compositor and application log tails, including stopped sessions."""
    return core.logs(session)


@mcp.tool()
def desktop_destroy(session: str) -> dict:
    """Stop a session's owned processes and remove its private runtime/configuration."""
    return core.destroy(session)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
