import json
import stat
import tempfile
import unittest
from pathlib import Path

from scripts import usage_review


def claude_lines():
    def use(i, time, name, arguments):
        return {
            "type": "assistant",
            "timestamp": time,
            "cwd": "/home/someone/project",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": f"t{i}",
                        "name": name,
                        "input": arguments,
                    }
                ]
            },
        }

    def result(i, time, text, error=False):
        return {
            "type": "user",
            "timestamp": time,
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": f"t{i}",
                        "content": [{"type": "text", "text": text}],
                        "is_error": error,
                    }
                ]
            },
        }

    created = json.dumps({"session": "aaaaaaaaaaaa", "status": "ready"})
    stopped = json.dumps(
        {"completed": 1, "stopped": {"step": 1, "reason": "wait not satisfied"}}
    )
    steps = {
        "session": "aaaaaaaaaaaa",
        "action": "steps",
        "steps": [
            {"action": "open", "url": "https://example.test/"},
            {"action": "wait", "seconds": 3},
            {"action": "wait", "text": "Done"},
        ],
    }
    gpu = {"renderer": "gles2"}
    return [
        {
            "type": "user",
            "timestamp": "2026-11-10T10:00:00Z",
            "message": {"content": "actually use the other profile"},
        },
        use(1, "2026-11-10T10:00:05Z", "mcp__agent-desktop__desktop_create", {}),
        result(1, "2026-11-10T10:00:06Z", created),
        use(2, "2026-11-10T10:01:00Z", "mcp__agent-desktop__desktop_browser", steps),
        result(2, "2026-11-10T10:01:05Z", stopped),
        use(3, "2026-11-10T10:02:00Z", "mcp__agent-desktop__desktop_create", gpu),
        result(3, "2026-11-10T10:02:01Z", "Session startup failed; see /x/y", True),
        use(4, "2026-11-10T10:02:05Z", "mcp__agent-desktop__desktop_create", gpu),
        result(4, "2026-11-10T10:02:06Z", "Session startup failed; see /x/y", True),
        use(
            5,
            "2026-11-10T10:03:00Z",
            "Bash",
            {
                "command": "cp ~/.local/state/agent-desktop/profiles/p/home/.mozilla/x/cookies.sqlite ."
            },
        ),
        # Repeated by compaction: must be counted once.
        use(2, "2026-11-10T10:01:00Z", "mcp__agent-desktop__desktop_browser", steps),
        use(
            6,
            "2026-11-10T10:40:00Z",
            "mcp__agent-desktop__desktop_screenshot",
            {"session": "aaaaaaaaaaaa"},
        ),
        # Outside --until: ignored.
        use(7, "2026-11-12T10:00:00Z", "mcp__agent-desktop__desktop_status", {}),
    ]


def codex_lines():
    return [
        {"type": "session_meta", "payload": {"cwd": "/home/someone/other"}},
        {
            "type": "event_msg",
            "timestamp": "2026-11-10T11:00:00Z",
            "payload": {
                "type": "mcp_tool_call_end",
                "call_id": "c1",
                "invocation": {
                    "server": "agent-desktop",
                    "tool": "desktop_destroy",
                    "arguments": {"session": "bbbbbbbbbbbb"},
                },
                "result": {"Ok": {"content": [{"type": "text", "text": "{}"}]}},
            },
        },
        {
            "type": "event_msg",
            "timestamp": "2026-11-10T11:00:01Z",
            "payload": {
                "type": "mcp_tool_call_end",
                "call_id": "c2",
                "invocation": {"server": "github", "tool": "search", "arguments": {}},
                "result": {"Ok": {}},
            },
        },
    ]


class UsageReviewTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        claude = self.root / "claude/-home-someone-project"
        codex = self.root / "codex/2026/11/10"
        claude.mkdir(parents=True)
        codex.mkdir(parents=True)
        for path, lines in (
            (claude / "one.jsonl", claude_lines()),
            (codex / "rollout.jsonl", codex_lines()),
        ):
            path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")

    def run_review(self):
        transcripts = usage_review.find_transcripts(
            self.root / "claude", self.root / "codex"
        )
        return usage_review.review(
            transcripts, usage_review.day("2026-11-10"), usage_review.day("2026-11-11")
        )

    def test_counts_each_call_once_within_the_window(self):
        summary, _, _ = self.run_review()
        self.assertEqual(summary["calls"], 6)
        self.assertEqual(summary["calls_by_tool"]["desktop_create"], 3)
        self.assertEqual(summary["calls_by_tool"]["desktop_browser"], 1)
        self.assertNotIn("search", summary["calls_by_tool"])
        self.assertEqual(summary["browser_steps"], {"open": 1, "wait": 2})
        self.assertEqual(summary["totals"]["fixed waits"], 1)
        self.assertEqual(summary["totals"]["waits for a condition"], 1)
        self.assertEqual(summary["totals"]["failed GPU creates"], 2)
        self.assertIn("desktop_ui", summary["tools_not_called"])

    def test_flags_what_a_report_should_read(self):
        summary, flags, _ = self.run_review()
        kinds = {kind for kind, *_ in flags}
        self.assertLessEqual(
            {
                "batch stopped",
                "tool error",
                "repeated after error",
                "shell: profile internals",
                "idle session",
                "left running",
                "person's remark",
            },
            kinds,
        )
        self.assertEqual(summary["batch_stops"], {"wait not satisfied": 1})
        self.assertEqual(
            summary["errors"], {"desktop_create: Session startup failed": 2}
        )

    def test_summary_json_holds_no_arguments_or_messages(self):
        summary, _, _ = self.run_review()
        text = json.dumps(summary)
        for private in ("example.test", "other profile", "cookies.sqlite", "/x/y"):
            self.assertNotIn(private, text)

    def test_writes_a_private_folder_outside_the_repository(self):
        out = self.root / "review"
        usage_review.main(
            [
                "--since",
                "2026-11-10",
                "--until",
                "2026-11-11",
                "--out",
                str(out),
                "--claude",
                str(self.root / "claude"),
                "--codex",
                str(self.root / "codex"),
            ]
        )
        self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o700)
        self.assertTrue((out / "summary.md").exists())
        self.assertEqual(len(list((out / "timelines").iterdir())), 2)
        with self.assertRaises(SystemExit):
            usage_review.main(["--out", str(usage_review.REPO / "review")])


if __name__ == "__main__":
    unittest.main()
