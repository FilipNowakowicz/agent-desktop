import argparse
import json
import os

from .core import (
    DesktopError,
    active_host_session,
    answer_host,
    create,
    delete_profile,
    destroy,
    logs,
    profiles,
    prune,
    request,
    request_host,
    run_actions,
    sessions,
    stop_host,
    trace,
    usage,
    use_runtime,
    wait,
)
from .doctor import doctor
from .viewer import take, view


def main():
    use_runtime()
    parser = argparse.ArgumentParser(
        description="Private Linux desktops",
        epilog="Each session has one controller. Input, launch, focus and "
        "ui-action from a named controller take the session's lease (renewed by "
        "its requests, expiring after AGENT_DESKTOP_LEASE_SECONDS, default 60, "
        "without them); other controllers' input is refused while it is held. "
        "Without a controller id, input works only while no lease is held.",
    )
    parser.add_argument(
        "--controller",
        help="controller id for the session lease (default: $AGENT_DESKTOP_CONTROLLER)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("create")
    new.add_argument("--mode", choices=("headless", "visible"), default="headless")
    new.add_argument(
        "--profile", help="keep this named home (e.g. browser logins) across sessions"
    )
    new.add_argument(
        "--guard-host",
        action="store_true",
        help="block the system bus and host-affecting commands for session apps",
    )
    for tool in ("labwc", "grim"):
        new.add_argument(f"--{tool}")
    sub.add_parser("list")
    checkup = sub.add_parser("doctor", help="check the runtime before first use")
    checkup.add_argument(
        "--smoke",
        action="store_true",
        help="also create, capture and destroy a session",
    )
    sub.add_parser("profiles")
    sub.add_parser("usage", help="disk used by sessions, screenshots and profiles")
    pruning = sub.add_parser("prune", help="delete stopped/failed sessions' state")
    pruning.add_argument("--older-than", type=float, default=0, metavar="DAYS")
    pruning.add_argument("--dry-run", action="store_true")
    removal = sub.add_parser("delete-profile", help="permanently delete saved logins")
    removal.add_argument("profile")
    for name, text in (
        ("view", "watch a session read-only"),
        ("take", "control a session yourself; closing the viewer hands it back"),
    ):
        observer = sub.add_parser(name, help=text)
        observer.add_argument("session")
        observer.add_argument("--wayvnc")
        observer.add_argument("--viewer")
        if name == "take":
            observer.add_argument(
                "--paste",
                action="store_true",
                help="send your clipboard in (cleared from the session on release)",
            )
            observer.add_argument(
                "--keyboard",
                help="your layout, e.g. us-dvorak (default: detected from the host)",
            )
    waiter = sub.add_parser("wait", help="wait for a window and/or a settled screen")
    waiter.add_argument("session")
    waiter.add_argument("--title")
    waiter.add_argument("--app-id")
    waiter.add_argument("--gone", action="store_true")
    waiter.add_argument("--stable-ms", type=int, default=0)
    waiter.add_argument("--seconds", type=float, default=0, help="pause first")
    waiter.add_argument("--timeout", type=float, default=10)
    waiter.add_argument("--element", help="accessible name substring")
    waiter.add_argument("--role")
    waiter.add_argument("--text", help="substring of the element's text or value")
    tree = sub.add_parser("ui", help="list visible UI elements (accessibility)")
    tree.add_argument("session")
    tree.add_argument("--app")
    tree.add_argument("--window")
    tree.add_argument("--max-nodes", type=int, default=300)
    act = sub.add_parser("ui-action", help="press, focus or set_text on a UI node")
    act.add_argument("session")
    act.add_argument("node")
    act.add_argument("action")
    act.add_argument("--text")
    act.add_argument("--observation")
    steps = sub.add_parser(
        "actions", help="run a JSON list of steps, stopping on surprises"
    )
    steps.add_argument("session")
    steps.add_argument("actions", type=json.loads)
    steps.add_argument("--observation")
    leasing = sub.add_parser(
        "lease", help="take, renew or release this controller's session lease"
    )
    leasing.add_argument("session")
    leasing.add_argument("--seconds", type=float, help="expiry after inactivity")
    leasing.add_argument("--release", action="store_true")
    leasing.add_argument(
        "--force", action="store_true", help="release another controller's lease"
    )
    hosting = sub.add_parser(
        "host", help="let an agent use your own screen (experimental, opt-in)"
    )
    hosting.add_argument(
        "action",
        choices=("start", "approve", "deny", "stop", "request", "status"),
        help="start/approve: allow (approve answers a pending request); deny; "
        "stop: end the host session; request: ask as an agent would",
    )
    hosting.add_argument("reason", nargs="?", help="for request")
    hosting.add_argument("--minutes", type=float, default=15)
    tracing = sub.add_parser(
        "trace", help="recent actions: target, focus and outcome, no typed text"
    )
    tracing.add_argument("session")
    tracing.add_argument("--limit", type=int, default=50)
    waiting = sub.add_parser("request-human", help="ask a person to take control")
    waiting.add_argument("session")
    waiting.add_argument("reason")
    for command in (
        "status",
        "windows",
        "screenshot",
        "logs",
        "destroy",
        "launch",
        "click",
        "move",
        "drag",
        "focus",
        "type",
        "key",
        "scroll",
        "control",
        "release",
    ):
        operation = sub.add_parser(command)
        operation.add_argument("session")
        if command == "launch":
            operation.add_argument("argv", nargs=argparse.REMAINDER)
        elif command in ("click", "move", "drag"):
            operation.add_argument("x", type=int)
            operation.add_argument("y", type=int)
            if command == "drag":
                operation.add_argument("to_x", type=int)
                operation.add_argument("to_y", type=int)
            if command in ("click", "drag"):
                operation.add_argument(
                    "--button", default="left", choices=("left", "middle", "right")
                )
        elif command == "type":
            operation.add_argument("text")
        elif command == "key":
            operation.add_argument("key")
            operation.add_argument(
                "--modifier", action="append", dest="modifiers", default=[]
            )
            operation.add_argument("--repeat", type=int, default=1)
        elif command == "scroll":
            operation.add_argument("dy", type=int)
            operation.add_argument("--dx", type=int, default=0)
        elif command == "focus":
            operation.add_argument("window")
        elif command == "release":
            operation.add_argument(
                "--force",
                action="store_true",
                help="return control even if the clipboard could not be cleared",
            )
        elif command == "screenshot":
            operation.add_argument(
                "--region",
                type=lambda v: [int(n) for n in v.split(",")],
                help="x,y,width,height in desktop coordinates",
            )
            operation.add_argument("--scale", type=float)
        if command in ("click", "move", "drag", "type", "key", "scroll"):
            operation.add_argument(
                "--observation",
                help="screenshot token; refuse input if windows or output changed",
            )
    args = vars(parser.parse_args())
    command = args.pop("command")
    controller = args.pop("controller")
    try:
        if command == "create":
            mode, profile = args.pop("mode"), args.pop("profile")
            guard = args.pop("guard_host")
            result = create(mode, tools=args, profile=profile, guard_host=guard)
        elif command == "list":
            result = sessions()
        elif command == "doctor":
            result = doctor(with_smoke=args["smoke"])
            print(json.dumps(result, indent=2))
            return 0 if result["status"] != "fail" else 1
        elif command == "profiles":
            result = profiles()
        elif command == "usage":
            result = usage()
        elif command == "prune":
            result = prune(args["older_than"], args["dry_run"])
        elif command == "delete-profile":
            result = delete_profile(args["profile"])
        elif command == "logs":
            result = logs(args["session"])
        elif command == "host":
            action = args["action"]
            if action in ("start", "approve"):
                result = answer_host(True, args["minutes"])
            elif action == "deny":
                result = answer_host(False)
            elif action == "stop":
                result = stop_host()
            elif action == "request":
                result = {"status": "pending"}
                while result.get("status") == "pending":
                    result = request_host(args["reason"] or "", args["minutes"])
            else:
                result = {"session": active_host_session()}
        elif command == "trace":
            result = trace(args["session"], args["limit"])
        elif command == "destroy":
            result = destroy(args["session"])
        elif command == "view":
            result = view(**args)
        elif command in ("ui", "ui-action"):
            session = args.pop("session")
            result = request(session, command.replace("-", "_"), controller, **args)
        elif command == "actions":
            result = run_actions(**args, controller=controller)
        elif command == "wait":
            result = wait(**args, controller=controller)
        elif command == "lease":
            options = {"action": "release" if args["release"] else "acquire"}
            if args["seconds"] is not None:
                options["seconds"] = args["seconds"]
            if args["force"]:
                options["force"] = True
            result = request(args["session"], "lease", controller, **options)
        elif command == "take":
            result = take(**args)
        elif command == "request-human":
            result = request(
                args["session"], "request_human", controller, reason=args["reason"]
            )
        else:
            session = args.pop("session")
            if command == "launch" and args["argv"][:1] == ["--"]:
                args["argv"] = args["argv"][1:]
            if command == "launch":
                # Relative paths on the command line mean the caller's directory.
                args["cwd"] = os.getcwd()
            result = request(session, command, controller, **args)
        print(json.dumps(result, indent=2))
    except DesktopError as error:
        print(json.dumps({"error": str(error)}))
        return 1
    return 0
