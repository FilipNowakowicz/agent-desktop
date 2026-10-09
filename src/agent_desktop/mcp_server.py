"""Stdio MCP adapter over the same session API used by the CLI."""

import functools
import json
import os
import re
import uuid

import anyio
from mcp.server.fastmcp import FastMCP, Image
from mcp.types import TextContent

from . import core

INSTRUCTIONS = """\
Private Linux desktops that do not touch the user's own screen. Create a session,
launch applications, take a screenshot, act using its observation token, verify
the result, and destroy the session when finished. Input tools and
desktop_actions accept screenshot=true to return the settled screen in the same
reply: prefer that to a separate screenshot call, and batch predictable steps in
desktop_actions.

Logins, 2FA codes, CAPTCHAs and payment confirmations: never ask the user for
passwords or codes in chat and never type guessed credentials. Call
desktop_request_human with a short reason, tell the user that reason and the
returned take_command, then wait with desktop_control. For a login, also give
paste_command, which lets them paste a password from their own clipboard, and
suggest ticking "Remember me" (on some sites a separate one for "sign in with"
buttons) so the login survives the browser closing. While the user has control,
your input and screenshots are refused. When control returns, take a new screenshot
before acting. To keep a login for later tasks, create sessions with the same
profile name (one session per profile at a time).

Each session has one controller at a time. This server holds a session's
controller lease while you use it (renewed by every call, released by default
after 60 seconds without calls). If another client controls a session, your input is
refused and nothing is sent; create your own session instead of sharing one.
A step whose delivery is uncertain is reported, never retried: check the
desktop before repeating it.

For web pages in a private session, desktop_browser drives Firefox through
its DOM (start, open, find, click, fill, select, text, wait): use it instead of
screenshots and coordinates where it applies.

Only when the user asks you to act on their own screen (open an app there,
navigate, click), call desktop_request_host with the reason. They confirm it;
then use the returned session with the same tools. Their windows are real: act
carefully, prefer reading before clicking, and never close their windows. If
input is refused because they are using the computer, wait a few seconds,
then take a new screenshot. If it is refused because the screen is locked or
off, stop and tell them. Their
screen rarely stops changing, so wait for a window title rather than
stable_ms (element waits need a private session). Call
desktop_destroy on that session as soon as you are done; it never closes their
applications. Use private sessions for everything else."""

EFFECTS_INSTRUCTIONS = """

Effects (experimental, on for these sessions): replies to input, launch, focus
and ui_action include `effects`: files written in the session home (documents
under "files" with a line diff, spreadsheet cells as "Sheet!B2: value",
application state under "app_state"), windows opened, closed or retitled, focus
and processes started or exited, observed during the action. Use them to check
file and dialog outcomes instead of a screenshot; take a screenshot when the
question is visual. Applications often write after the reply: call
desktop_effects with the action's effect_id, and wait_for_file (e.g. "~/*.ods")
to wait for a save. "Nothing observed" is evidence only for its time window."""

# Experiment baseline (AGENT_DESKTOP_LOOK=0): the server as it was before input
# could return a screenshot, for matched comparisons.
LOOK = os.environ.get("AGENT_DESKTOP_LOOK") != "0"
if not LOOK:
    INSTRUCTIONS = INSTRUCTIONS.replace(
        """verify
the result, and destroy the session when finished. Input tools and
desktop_actions accept screenshot=true to return the settled screen in the same
reply: prefer that to a separate screenshot call, and batch predictable steps in
desktop_actions.""",
        """verify
with another screenshot, and destroy the session when finished.""",
    )

if os.environ.get("AGENT_DESKTOP_EFFECTS") == "1":
    INSTRUCTIONS += EFFECTS_INSTRUCTIONS

ATLAS_INSTRUCTIONS = """

Effect atlas (experimental): desktop_atlas(query, app) finds which control of an
application changes a setting, where the control is, its default and the
configuration key it changes, learned and verified automatically. Use it before
searching menus and dialogs for a setting. desktop_set(session, app, control)
applies a verified setting directly, without the GUI; check that it took effect."""

if os.environ.get("AGENT_DESKTOP_ATLAS"):
    INSTRUCTIONS += ATLAS_INSTRUCTIONS

# One controller id for this server's lifetime (AGENT_DESKTOP_CONTROLLER overrides).
CONTROLLER = os.environ.get("AGENT_DESKTOP_CONTROLLER") or (
    f"mcp-{os.getpid()}-{uuid.uuid4().hex[:8]}"
)


def call(session, operation, **arguments):
    """A session request made as this server's controller."""
    return core.request(session, operation, CONTROLLER, **arguments)


mcp = FastMCP("Agent Desktop", instructions=INSTRUCTIONS)

# After input with screenshot=true: capture once the screen has been still for
# SETTLE_MS (blinking carets ignored), or after SETTLE_TIMEOUT_MS regardless.
SETTLE_MS = 300
SETTLE_TIMEOUT_MS = 3000


def looked(session, result, screenshot):
    """`result`, plus the settled screen when `screenshot` is true."""
    if not screenshot:
        return result
    capture = call(
        session,
        "screenshot",
        settle_ms=SETTLE_MS,
        settle_timeout_ms=SETTLE_TIMEOUT_MS,
    )
    return [
        TextContent(type="text", text=json.dumps({**result, "screenshot": capture})),
        Image(path=capture["path"]),
    ]


def tool(**options):
    """Register a tool that runs in a worker thread.

    FastMCP runs synchronous tools on its event loop, so one long wait would
    block every other request of the server, including other sessions.
    """

    def register(function):
        @functools.wraps(function)
        async def threaded(*args, **kwargs):
            return await anyio.to_thread.run_sync(
                functools.partial(function, *args, **kwargs)
            )

        return mcp.tool(**options)(threaded)

    return register


@tool()
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


@tool()
def desktop_profiles() -> list[dict]:
    """List saved profiles and whether a session is using them."""
    return core.profiles()


@tool()
def desktop_list() -> list[dict]:
    """List desktop sessions and their current availability."""
    return core.sessions()


@tool()
def desktop_status(session: str) -> dict:
    """Get session health and application exit codes."""
    return call(session, "status")


@tool()
def desktop_launch(session: str, argv: list[str], cwd: str | None = None) -> dict:
    """Launch an application argument list in the session's private environment.

    It runs in the session's private home unless cwd (an absolute directory)
    is given; use absolute paths for files.
    """
    return call(session, "launch", argv=argv, cwd=cwd)


@tool()
def desktop_windows(session: str) -> dict:
    """List private desktop windows: id, title, app_id, states and parent."""
    return call(session, "windows")


@tool()
def desktop_atlas(query: str, app: str | None = None) -> list[dict]:
    """Find the control that changes a setting, e.g. query="highlight current
    line", app="mousepad": its location (menu or dialog tab and label), default
    state and the configuration key it changes. An empty query lists the app's
    known controls. Experimental: needs AGENT_DESKTOP_ATLAS."""
    from . import atlas

    return atlas.search(query, app)


@tool()
def desktop_set(session: str, app: str, control: str) -> dict:
    """Apply a verified atlas setting without the GUI: write the configuration
    change learned for `control` (the control text from desktop_atlas) into the
    private session's home. Many applications pick the change up while running;
    others on their next start. Verify the result (e.g. desktop_ui). Not for
    host sessions. Experimental: needs AGENT_DESKTOP_ATLAS."""
    return call(
        session,
        "set",
        app=app,
        control=control,
        atlas=os.environ.get("AGENT_DESKTOP_ATLAS"),
    )


@tool()
def desktop_effects(
    session: str,
    effect_id: int,
    wait_for_file: str | None = None,
    timeout: float = 10,
) -> dict:
    """Effects observed since an earlier action (by its effect_id), including
    files written after its reply. With wait_for_file (a "~/..." glob such as
    "~/*.ods"), first wait up to timeout seconds for a matching file to be
    written and go quiet; satisfied says whether it was. Experimental: only for
    sessions created with AGENT_DESKTOP_EFFECTS=1."""
    if wait_for_file is None:
        return call(session, "effects", effect_id=effect_id)
    return core.wait_effect(
        session, effect_id, wait_for_file, timeout=timeout, controller=CONTROLLER
    )


@tool()
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
    state: str | None = None,
    exact: bool = False,
) -> dict:
    """Wait instead of polling with screenshots.

    With title (substring) and/or app_id (exact), wait for a matching window, or
    for none to remain if gone is true. With element (accessible name substring),
    role (exact, as listed by desktop_ui) and/or text (substring of its text or
    value), wait for a matching UI element, e.g. a "Saved" label, or for it to
    disappear when gone is true and no window is given. exact=true matches the
    whole name; state requires checked, unchecked, enabled, disabled, focused,
    selected, expanded, collapsed, editable, pressed, busy or idle. Elements
    are searched within the matched windows. With stable_ms, then wait
    until the screen has not changed for that long (a blinking caret is ignored).
    seconds (up to 30) pauses first, for changes no condition describes.
    Returns satisfied=false at the timeout (at most 120 s); when no window
    matched, open_windows lists the titles and app_ids that do exist.
    """
    return core.wait(
        session,
        title,
        app_id,
        gone,
        stable_ms,
        timeout,
        element,
        role,
        text,
        seconds,
        controller=CONTROLLER,
        state=state,
        exact=exact,
    )


@tool(structured_output=False)
def desktop_actions(
    session: str,
    actions: list[dict],
    observation: str | None = None,
    screenshot: bool = False,
    timeout: float | None = None,
) -> dict | list:
    """Run up to 50 steps in one call, e.g. click a field, type, press Return.

    Each step is {"action": NAME, ...arguments of that tool}; NAME is click, move,
    drag, scroll, type, key, ui_action, focus or wait (e.g. {"action": "wait",
    "seconds": 1}). A ui_action step names its UI action as "name", e.g.
    {"action": "ui_action", "node": "n5", "name": "set_text", "text": "Ada"}.
    Pass the observation token of the screenshot you planned from; coordinates
    in every step are then in that screenshot's image. Input is sent only while
    windows and focus are as they were after the previous step; otherwise the
    run stops and reports which step and why. No other client can send input
    while the steps run. Steps are never retried: a step reported with
    "uncertain": true may or may not have happened, so check before repeating it.

    Guarded steps: plan several steps ahead and say what each should cause.
    Any step can carry "expect": desktop_wait conditions (title, app_id, gone,
    element, role, text, state, exact, timeout default 5) that must hold after
    it, e.g. {"action": "key", "key": "Return", "expect": {"title": "Saved"}};
    if not, the run stops there with "expectation": true and the step counted
    as done. A ui_action step can name its target instead of a node id
    (element, role, state, exact, window, app), looked up when the step
    runs: {"action": "ui_action", "element": "Save", "role": "push button",
    "name": "press"}; it must match exactly one element, otherwise nothing is
    sent and the run stops. timeout (seconds) bounds the whole run.

    With screenshot=true the reply ends with the screen after the last step run
    (also when the run stopped early), once it has been still for 0.3 s (at most
    3 s; "settled" says which).
    """
    result = core.run_actions(session, actions, observation, CONTROLLER, timeout)
    return looked(session, result, screenshot)


@tool()
def desktop_browser(
    session: str,
    action: str,
    url: str | None = None,
    selector: str | None = None,
    text: str | None = None,
    exact: bool = False,
    value: str | None = None,
    tab: int | None = None,
    new_tab: bool = False,
    gone: bool = False,
    timeout: float = 10,
    within: str | None = None,
    steps: list[dict] | None = None,
) -> dict:
    """Use Firefox in a private session through its DOM, without screenshots.

    action "start" opens Firefox (url optional) with a local WebDriver BiDi
    bridge, or connects to one already started in the session with
    --remote-debugging-port (other actions connect to that one too); a Firefox
    started without it must be closed first. Then: "open" a url
    (new_tab for a new tab), "tabs", "text" (visible text of the page or
    selector), "find" (elements by CSS selector or by visible text, label or
    placeholder; exact for the whole text), "wait" (until found, or gone; up to
    60 s), "click", "fill" (replace a field's text with value, typed as real
    keys) and "select" (an option of a <select> by text or value). click, fill
    and select need exactly one visible, enabled match, otherwise nothing is
    done and the matches are listed. Replies include the page url and title,
    and the element's value afterwards (never a password's). tab picks a tab by
    index from "tabs"; later calls stay on it. within narrows a target to the
    row, list item, form or dialog containing that text, e.g. text="Edit",
    within="mallory". action "steps" runs a list of these actions in one call
    (steps=[{"action": "fill", "selector": "#u", "value": "admin"},
    {"action": "click", "text": "Sign in"}, {"action": "wait", "text":
    "Dashboard"}]) and stops at the first failure or unmet wait: plan several
    actions per call. Faster and more exact than pixels for web pages; use
    screenshots for visual questions.
    """
    arguments = {
        "url": url,
        "selector": selector,
        "text": text,
        "exact": exact,
        "value": value,
        "tab": tab,
        "new_tab": new_tab,
        "gone": gone,
        "timeout": timeout,
        "within": within,
        "steps": steps,
    }
    return call(
        session,
        "browser",
        action=action,
        **{k: v for k, v in arguments.items() if v is not None},
    )


@tool()
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
        call(session, "ui", app=app, window=window, max_nodes=max_nodes)
    )


@tool(structured_output=False)
def desktop_ui_action(
    session: str,
    node: str,
    action: str,
    text: str | None = None,
    observation: str | None = None,
    screenshot: bool = False,
) -> dict | list:
    """Act on a desktop_ui node: "press" (click/activate/toggle), "focus",
    "set_text" (replace an editable field's text), "select" (choose a tab or
    list item within its parent) or a listed action name.

    Works without coordinates. Verify the result with desktop_ui or a screenshot.

    With screenshot=true the reply also contains the settled screen.
    """
    result = call(
        session,
        "ui_action",
        node=node,
        action=action,
        text=text,
        observation=observation,
    )
    return looked(session, result, screenshot)


@tool()
def desktop_focus(session: str, window: str) -> dict:
    """Activate a private window and wait for its activated state (up to 2 seconds).

    Returns the observed window; fails if it closes or activation is not observed.
    Focus can still change afterward, so use screenshot observations for input.
    """
    return call(session, "focus", window=window)


@tool(structured_output=False)
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
    capture = call(session, "screenshot", region=region, scale=scale)
    return [
        TextContent(type="text", text=json.dumps(capture)),
        Image(path=capture["path"]),
    ]


@tool(structured_output=False)
def desktop_type(
    session: str,
    text: str,
    observation: str | None = None,
    screenshot: bool = False,
) -> dict | list:
    """Type up to 10000 characters into the private focused app, about 8 ms per key.

    Verify the result afterward. Paste long text instead of typing it.

    With screenshot=true the reply also contains the screen once it has been still
    for 0.3 s (at most 3 s; "settled" says which), with its observation token,
    so no separate desktop_screenshot call is needed. Still means repainted, not
    necessarily finished: check that the result is what you expected.
    """
    return looked(
        session, call(session, "type", text=text, observation=observation), screenshot
    )


@tool(structured_output=False)
def desktop_key(
    session: str,
    key: str,
    modifiers: list[str] | None = None,
    repeat: int = 1,
    observation: str | None = None,
    screenshot: bool = False,
) -> dict | list:
    """Send a keysym such as Return or Right, optionally with ctrl/alt/shift/logo
    modifiers and repeated up to 100 times.

    With screenshot=true the reply also contains the screen once it has been still
    for 0.3 s (at most 3 s; "settled" says which), with its observation token,
    so no separate desktop_screenshot call is needed. Still means repainted, not
    necessarily finished: check that the result is what you expected.
    """
    result = call(
        session,
        "key",
        key=key,
        modifiers=modifiers or [],
        repeat=repeat,
        observation=observation,
    )
    return looked(session, result, screenshot)


@tool(structured_output=False)
def desktop_click(
    session: str,
    x: int,
    y: int,
    button: str = "left",
    observation: str | None = None,
    screenshot: bool = False,
) -> dict | list:
    """Click at x/y: coordinates in the screenshot whose observation is passed,
    otherwise desktop pixels. Fails outside the desktop.

    With screenshot=true the reply also contains the screen once it has been still
    for 0.3 s (at most 3 s; "settled" says which), with its observation token,
    so no separate desktop_screenshot call is needed. Still means repainted, not
    necessarily finished: check that the result is what you expected.
    """
    result = call(session, "click", x=x, y=y, button=button, observation=observation)
    return looked(session, result, screenshot)


@tool()
def desktop_move(session: str, x: int, y: int, observation: str | None = None) -> dict:
    """Move only the private desktop pointer (coordinates as for desktop_click)."""
    return call(session, "move", x=x, y=y, observation=observation)


@tool(structured_output=False)
def desktop_drag(
    session: str,
    x: int,
    y: int,
    to_x: int,
    to_y: int,
    button: str = "left",
    observation: str | None = None,
    screenshot: bool = False,
) -> dict | list:
    """Press at (x, y), move in steps to (to_x, to_y) and release (coordinates as
    for desktop_click).

    With screenshot=true the reply also contains the settled screen."""
    result = call(
        session,
        "drag",
        x=x,
        y=y,
        to_x=to_x,
        to_y=to_y,
        button=button,
        observation=observation,
    )
    return looked(session, result, screenshot)


@tool(structured_output=False)
def desktop_scroll(
    session: str,
    dy: int,
    dx: int = 0,
    observation: str | None = None,
    screenshot: bool = False,
) -> dict | list:
    """Scroll at the current pointer location by mouse-wheel notches: dy > 0
    scrolls down, dx > 0 right (a notch is usually about three lines).

    With screenshot=true the reply also contains the settled screen."""
    result = call(session, "scroll", dy=dy, dx=dx, observation=observation)
    return looked(session, result, screenshot)


@tool()
def desktop_request_human(session: str, reason: str) -> dict:
    """Ask the user to take control, e.g. to log in, enter a 2FA code or pass a CAPTCHA.

    Do not ask the user for passwords or codes. Tell them the reason and the
    returned take_command (paste_command for a login), then wait with desktop_control. While they have
    control, input and screenshots are refused; afterwards take a new screenshot.
    """
    return call(session, "request_human", reason=reason)


@tool()
def desktop_request_host(reason: str, minutes: float = 15) -> dict:
    """Ask the user to let you act on their own screen.

    Only for tasks the user asked to happen on their screen. They see the reason
    and approve or decline. Waits up to 50 seconds; if it returns status
    "pending", tell the user to click the notification and call again with the
    same reason. On approval this returns a host session to use with the other
    tools until it expires (minutes, at most 240) or you destroy it.
    Applications you launch there stay open afterwards. Your input pauses while
    the user is typing or moving the mouse.
    """
    return core.request_host(reason, minutes)


@tool()
def desktop_control(session: str, wait_seconds: int = 0) -> dict:
    """Report who controls the session, any pending request for the user and
    which client holds the controller lease.

    With wait_seconds (up to 600), wait until the user has finished and control
    is back with the agent; call again if it is still pending.
    """
    return core.wait_for_agent_control(session, wait_seconds, CONTROLLER)


@tool()
def desktop_logs(session: str) -> dict:
    """Read bounded compositor and application log tails, including stopped sessions."""
    return core.logs(session)


@tool()
def desktop_destroy(session: str) -> dict:
    """Stop a session's owned processes and remove its private runtime/configuration."""
    return core.destroy(session)


# Experiment baseline (AGENT_DESKTOP_GUARDS=0): sequences without the
# guarded-step description, for matched comparisons.
if os.environ.get("AGENT_DESKTOP_GUARDS") == "0":
    for registered in mcp._tool_manager.list_tools():
        if registered.name == "desktop_actions":
            registered.description = re.sub(
                r"\n\s*\n\s*Guarded steps:.*?(?=\n\s*\n)",
                "",
                registered.description,
                flags=re.S,
            )

if not LOOK:
    for registered in mcp._tool_manager.list_tools():
        if registered.parameters.get("properties", {}).pop("screenshot", None):
            registered.description = re.split(
                r"\n\s*\n\s*With screenshot=true", registered.description
            )[0]


def main():
    core.use_runtime()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
