"""The Claude Code hook in docs/INTEGRATIONS.md answers "ask" with a clear reason."""

import json
import re
import subprocess
import unittest
from pathlib import Path

DOC = Path(__file__).resolve().parent.parent / "docs" / "INTEGRATIONS.md"


class HostHookTests(unittest.TestCase):
    def test_documented_hook_prints_an_ask_whose_reason_says_what_happened(self):
        section = DOC.read_text().split("#### Asking in Claude Code", 1)[1]
        settings = json.loads(re.search(r"```json\n(.*?)```", section, re.S)[1])
        (entry,) = settings["hooks"]["PreToolUse"]
        self.assertEqual(entry["matcher"], "mcp__agent-desktop__desktop_request_host")
        command = entry["hooks"][0]["command"]
        printed = subprocess.run(
            ["sh", "-c", command], capture_output=True, text=True, check=True
        ).stdout
        output = json.loads(printed)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PreToolUse")
        self.assertEqual(output["permissionDecision"], "ask")
        # Read by the person in the prompt, and by the agent when Claude Code
        # denies an unanswered prompt in a non-interactive run.
        reason = output["permissionDecisionReason"]
        self.assertIn("use your screen", reason)
        self.assertIn("Nothing runs on it until you approve", reason)
        self.assertIn("ask you in chat", reason)


if __name__ == "__main__":
    unittest.main()
