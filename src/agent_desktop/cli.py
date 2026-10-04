import argparse
import json

from .core import (
    DesktopError,
    create,
    delete_profile,
    destroy,
    logs,
    profiles,
    request,
    sessions,
)
from .viewer import take, view


def main():
    parser = argparse.ArgumentParser(description="Private Linux desktops")
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("create")
    new.add_argument("--mode", choices=("headless", "visible"), default="headless")
    new.add_argument(
        "--profile", help="keep this named home (e.g. browser logins) across sessions"
    )
    for tool in ("labwc", "grim"):
        new.add_argument(f"--{tool}")
    sub.add_parser("list")
    sub.add_parser("profiles")
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
        if command in ("click", "move", "drag", "type", "key", "scroll"):
            operation.add_argument(
                "--observation",
                help="screenshot token; refuse input if windows or output changed",
            )
    args = vars(parser.parse_args())
    command = args.pop("command")
    try:
        if command == "create":
            mode, profile = args.pop("mode"), args.pop("profile")
            result = create(mode, tools=args, profile=profile)
        elif command == "list":
            result = sessions()
        elif command == "profiles":
            result = profiles()
        elif command == "delete-profile":
            result = delete_profile(args["profile"])
        elif command == "logs":
            result = logs(args["session"])
        elif command == "destroy":
            result = destroy(args["session"])
        elif command == "view":
            result = view(**args)
        elif command == "take":
            result = take(**args)
        elif command == "request-human":
            result = request(args["session"], "request_human", reason=args["reason"])
        else:
            session = args.pop("session")
            if command == "launch" and args["argv"][:1] == ["--"]:
                args["argv"] = args["argv"][1:]
            result = request(session, command, **args)
        print(json.dumps(result, indent=2))
    except DesktopError as error:
        print(json.dumps({"error": str(error)}))
        return 1
    return 0
