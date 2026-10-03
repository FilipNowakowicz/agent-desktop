import argparse
import json

from .core import DesktopError, create, destroy, logs, request, sessions
from .viewer import view


def main():
    parser = argparse.ArgumentParser(description="Private Linux desktops")
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("create")
    new.add_argument("--mode", choices=("headless", "visible"), default="headless")
    for tool in ("labwc", "grim", "wtype", "wlrctl"):
        new.add_argument(f"--{tool}")
    sub.add_parser("list")
    observer = sub.add_parser("view")
    observer.add_argument("session")
    observer.add_argument("--wayvnc")
    observer.add_argument("--viewer")
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
        "type",
        "key",
        "scroll",
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
        elif command == "scroll":
            operation.add_argument("dy", type=int)
            operation.add_argument("--dx", type=int, default=0)
    args = vars(parser.parse_args())
    command = args.pop("command")
    try:
        if command == "create":
            mode = args.pop("mode")
            result = create(mode, tools=args)
        elif command == "list":
            result = sessions()
        elif command == "logs":
            result = logs(args["session"])
        elif command == "destroy":
            result = destroy(args["session"])
        elif command == "view":
            result = view(**args)
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
