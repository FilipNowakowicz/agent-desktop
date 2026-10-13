"""The benchmark's time split: model API, tool and other time per run."""

import json
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from agent_desktop import mcp_server
from scripts import benchmark


class TimeSplitTests(unittest.TestCase):
    def test_overlapping_calls_count_once(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "calls.jsonl"
            calls = [(10, 12), (11, 13), (15, 16), (100, 200)]
            log.write_text(
                "".join(json.dumps({"start": a, "end": b}) + "\n" for a, b in calls)
                + "not json\n"
            )
            # The last call started after this run and belongs to another one.
            split = benchmark.time_split(20, 9000, log, 0, 50)
        self.assertEqual(
            split, {"api_seconds": 9.0, "tool_seconds": 4.0, "other_seconds": 7.0}
        )

    def test_missing_inputs(self):
        self.assertIsNone(benchmark.time_split(20, None, "/nonexistent", 0, 1))
        self.assertIsNone(benchmark.time_split(20, 9000, None, 0, 1))

    def test_percentiles_keep_every_run(self):
        self.assertEqual(benchmark.percentiles(list(range(1, 11))), [5, 10])
        self.assertEqual(benchmark.percentiles([None, 7]), [7, 7])
        self.assertIsNone(benchmark.percentiles([]))

    def test_server_logs_calls_only_when_asked(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "calls.jsonl"
            previous = os.environ.pop("AGENT_DESKTOP_CALL_LOG", None)
            try:
                mcp_server.log_call("desktop_list", 1.0, True)
                self.assertFalse(log.exists())
                os.environ["AGENT_DESKTOP_CALL_LOG"] = str(log)
                mcp_server.log_call("desktop_list", 1.0, False)
            finally:
                os.environ.pop("AGENT_DESKTOP_CALL_LOG", None)
                if previous is not None:
                    os.environ["AGENT_DESKTOP_CALL_LOG"] = previous
            record = json.loads(log.read_text())
        self.assertEqual(record["tool"], "desktop_list")
        self.assertFalse(record["ok"])
        self.assertGreaterEqual(record["end"], record["start"])


if __name__ == "__main__":
    unittest.main()


class AgentEnvironmentTests(unittest.TestCase):
    def test_the_agent_is_not_tied_to_the_starting_session(self):
        parent = {
            "CLAUDECODE": "1",
            "CLAUDE_CODE_SESSION_ID": "s",
            "CLAUDE_CODE_REMOTE_SESSION_ID": "r",
            "CLAUDE_CODE_CHILD_SESSION": "1",
            "CLAUDE_CODE_MESSAGING_TOKEN": "t",
            "CLAUDE_EFFORT": "medium",
            "CLAUDE_CODE_OAUTH_TOKEN": "kept",
            "ANTHROPIC_API_KEY": "kept",
            "PATH": "/bin",
        }
        with unittest.mock.patch.dict(os.environ, parent, clear=True):
            environment = benchmark.agent_environment()
        self.assertEqual(
            environment,
            {
                "CLAUDE_CODE_OAUTH_TOKEN": "kept",
                "ANTHROPIC_API_KEY": "kept",
                "PATH": "/bin",
            },
        )


class SkillTests(unittest.TestCase):
    def test_the_skill_is_taken_from_the_final_reply(self):
        reply = (
            "Done.\n\nSKILL-START\n```python\nfor row in rows():\n    print(row)\n"
            "```\nSKILL-END\n"
        )
        self.assertEqual(
            benchmark.skill_from_reply(reply), "for row in rows():\n    print(row)\n"
        )
        bare = "SKILL-START\npress('Save')\nSKILL-END"
        self.assertEqual(benchmark.skill_from_reply(bare), "press('Save')\n")
        self.assertIsNone(benchmark.skill_from_reply("no skill here"))
