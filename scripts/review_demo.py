"""Generate the synthetic evidence report; optionally inspect it in private Firefox."""

import argparse
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from agent_desktop import core, review
from agent_desktop.worker import owned_processes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--visual",
        action="store_true",
        help="open a headless private Firefox and capture screenshots",
    )
    args = parser.parse_args()
    repository = Path(__file__).resolve().parent.parent
    output = repository / "artifacts" / "evidence-review"
    output.mkdir(parents=True, exist_ok=True)
    result = review.from_file(
        repository / "docs/examples/evidence-review.json", output / "review.html"
    )
    if args.visual:
        core.use_runtime()
        with tempfile.TemporaryDirectory(prefix="desktop-review-visual-") as directory:
            root = Path(directory)
            (root / "runtime").mkdir(mode=0o700)
            os.environ["AGENT_DESKTOP_STATE_DIR"] = str(root / "state")
            os.environ["XDG_RUNTIME_DIR"] = str(root / "runtime")
            session = core.create()["session"]
            token = core.manifest(session)["token"]
            try:
                core.request(
                    session,
                    "browser",
                    action="start",
                    url=Path(result["path"]).as_uri(),
                )
                core.request(
                    session, "browser", action="wait", selector="h1", timeout=20
                )
                screenshots = []

                def capture(name):
                    frame = core.request(
                        session, "screenshot", settle_ms=300, settle_timeout_ms=3000
                    )
                    shutil.copyfile(frame["path"], output / name)
                    screenshots.append(name)

                capture("review-top.png")
                core.request(session, "scroll", dy=5)
                capture("review-checks.png")
                core.request(
                    session,
                    "browser",
                    action="click",
                    selector="li.step:nth-child(2) > ul.checks details > summary",
                )
                capture("review-details.png")
                visible = core.request(
                    session, "browser", action="text", selector="main"
                )
                page_text = json.dumps(visible)
                for expected in (
                    "Satisfied: Browser context",
                    "Violated: Output file",
                    "Unknown: Visible UI",
                    "Delivery unknown",
                ):
                    if expected not in page_text:
                        raise RuntimeError(f"Rendered page is missing {expected!r}")
                result.update(
                    private_desktop=True, screenshots=screenshots, page_evidence=visible
                )
            finally:
                core.destroy(session)
                deadline = time.monotonic() + 5
                while owned_processes(token) and time.monotonic() < deadline:
                    time.sleep(0.05)
                if owned_processes(token):
                    raise RuntimeError("Private desktop cleanup incomplete")
                result["desktop_stopped"] = True
    (output / "validation.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
