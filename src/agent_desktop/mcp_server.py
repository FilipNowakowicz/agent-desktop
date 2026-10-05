"""Stdio MCP adapter over the same session API used by the CLI."""

import json

from mcp.server.fastmcp import FastMCP, Image
from mcp.types import TextContent

from . import core

INSTRUCTIONS = """\
Private Linux desktops that do not touch the user's own screen. Create a session,
launch applications, take a screenshot, act using its observation token, verify
with another screenshot, and destroy the session when finished.

Logins, 2FA codes, CAPTCHAs and payment confirmations: never ask the user for
passwords or codes in chat and never type guessed credentials. Call
desktop_request_human with a short reason, tell the user that reason and the
returned take_command, then wait with desktop_control. While the user has control,
your input and screenshots are refused. When control returns, take a new screenshot
before acting. To keep a login for later tasks, create sessions with the same
profile name (one session per profile at a time)."""

mcp = FastMCP("Private desktop", instructions=INSTRUCTIONS)


@mcp.tool()
def desktop_create(
    mode: str = "headless", profile: str | None = None, guard_host: bool = False
) -> dict:
    """Create a private Linux desktop. Visible mode opens a nested host Wayland window.

    A named profile keeps the session's home directory (browser logins, app
    settings) for later sessions; one session can use a profile at a time.
    Without a profile, everything is deleted at destroy. guard_host blocks the
    system bus and common host-affecting commands (power, network, Bluetooth,
    brightness, pkill) for applications in the session; use it when testing
    panels, widgets or scripts that could change the real machine.
    """
    return core.create(mode, profile=profile, guard_host=guard_host)


@mcp.tool()
def desktop_profiles() -> list[dict]:
    """List saved profiles and whether a session is using them."""
    return core.profiles()


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
def desktop_wait(
    session: str,
    title: str | None = None,
    app_id: str | None = None,
    gone: bool = False,
    stable_ms: int = 0,
    timeout: float = 10,
    element: str | None = None,
    role: str | None = None,
    text: str | None = None,
    seconds: float = 0,
) -> dict:
    """Wait instead of polling with screenshots.

    With title (substring) and/or app_id (exact), wait for a matching window, or
    for none to remain if gone is true. With element (accessible name substring),
    role (exact, as listed by desktop_ui) and/or text (substring of its text or
    value), wait for a matching UI element, e.g. a "Saved" label, or for it to
    disappear when gone is true and no window is given. With stable_ms, then wait
    until the screen has not changed for that long (a blinking caret is ignored).
    seconds (up to 30) pauses first, for changes no condition describes.
    Returns satisfied=false at the timeout (at most 120 s).
    """
    return core.wait(
        session, title, app_id, gone, stable_ms, timeout, element, role, text, seconds
    )


@mcp.tool()
def desktop_actions(
    session: str, actions: list[dict], observation: str | None = None
) -> dict:
    """Run up to 50 steps in one call, e.g. click a field, type, press Return.

    Each step is {"action": NAME, ...arguments of that tool}; NAME is click, move,
    drag, scroll, type, key, ui_action, focus or wait (e.g. {"action": "wait",
    "seconds": 1}). Pass the observation token of the screenshot you planned
    from; coordinates in every step are then in that screenshot's image. Input is sent only while windows and focus are
    as they were after the previous step; otherwise the run stops and reports
    which step and why. Insert a wait step where you expect a window to open or
    close. Popups and changes inside a window are not detected, so take a
    screenshot afterwards to verify the result.
    """
    return core.run_actions(session, actions, observation)


@mcp.tool()
def desktop_ui(
    session: str,
    app: str | None = None,
    window: str | None = None,
    max_nodes: int = 300,
) -> str:
    """List visible UI elements through accessibility, one indented line each:
    id (for desktop_ui_action), role, name, states, text, value and actions.

    Filter by application name and/or window title substring. Usually much
    smaller than a screenshot and exact about labels and field contents. Some
    applications expose little (e.g. Chromium needs --force-renderer-accessibility).
    """
    return core.render_tree(
        core.request(session, "ui", app=app, window=window, max_nodes=max_nodes)
    )


@mcp.tool()
def desktop_ui_action(
    session: str,
    node: str,
    action: str,
    text: str | None = None,
    observation: str | None = None,
) -> dict:
    """Act on a desktop_ui node: "press" (click/activate/toggle), "focus",
    "set_text" (replace an editable field's text) or a listed action name.

    Works without coordinates. Verify the result with desktop_ui or a screenshot.
    """
    return core.request(
        session,
        "ui_action",
        node=node,
        action=action,
        text=text,
        observation=observation,
    )


@mcp.tool()
def desktop_focus(session: str, window: str) -> dict:
    """Activate a private window and wait for its activated state (up to 2 seconds).

    Returns the observed window; fails if it closes or activation is not observed.
    Focus can still change afterward, so use screenshot observations for input.
    """
    return core.request(session, "focus", window=window)


@mcp.tool(structured_output=False)
def desktop_screenshot(
    session: str, region: list[int] | None = None, scale: float | None = None
) -> list:
    """Return a private desktop PNG plus dimensions, artifact path and observation.

    Pass the observation token to input tools to refuse input if windows, focus
    or the output changed since this screenshot. To save image tokens, region
    [x, y, width, height] captures part of the desktop and scale (0.1-1) shrinks
    the image. Input tools given this screenshot's observation interpret x/y as
    coordinates in this image; without an observation they are desktop pixels.
    """
    capture = core.request(session, "screenshot", region=region, scale=scale)
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
    repeat: int = 1,
    observation: str | None = None,
) -> dict:
    """Send a keysym such as Return or Right, optionally with ctrl/alt/shift/logo
    modifiers and repeated up to 100 times."""
    return core.request(
        session,
        "key",
        key=key,
        modifiers=modifiers or [],
        repeat=repeat,
        observation=observation,
    )


@mcp.tool()
def desktop_click(
    session: str, x: int, y: int, button: str = "left", observation: str | None = None
) -> dict:
    """Click at x/y: coordinates in the screenshot whose observation is passed,
    otherwise desktop pixels. Fails outside the desktop."""
    return core.request(
        session, "click", x=x, y=y, button=button, observation=observation
    )


@mcp.tool()
def desktop_move(session: str, x: int, y: int, observation: str | None = None) -> dict:
    """Move only the private desktop pointer (coordinates as for desktop_click)."""
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
    """Press at (x, y), move in steps to (to_x, to_y) and release (coordinates as
    for desktop_click)."""
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
def desktop_request_human(session: str, reason: str) -> dict:
    """Ask the user to take control, e.g. to log in, enter a 2FA code or pass a CAPTCHA.

    Do not ask the user for passwords or codes. Tell them the reason and the
    returned take_command, then wait with desktop_control. While they have
    control, input and screenshots are refused; afterwards take a new screenshot.
    """
    return core.request(session, "request_human", reason=reason)


@mcp.tool()
def desktop_control(session: str, wait_seconds: int = 0) -> dict:
    """Report who controls the session and any pending request for the user.

    With wait_seconds (up to 600), wait until the user has finished and control
    is back with the agent; call again if it is still pending.
    """
    return core.wait_for_agent_control(session, wait_seconds)


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
