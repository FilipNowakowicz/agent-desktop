"""Planted false success must remain visible in the offline evidence review."""

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from agent_desktop import review
from agent_desktop.core import DesktopError


class ParsedReport(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.words = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.words.append(data)


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-review-test-")
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_delivered_save_with_missing_output_is_visibly_violated(self):
        # The action reports delivery, but an independent output check finds
        # the planted missing save. Rendering must never promote it to success.
        output = self.root / "missing.csv"
        check = {
            "predicate": {"kind": "file", "path": str(output)},
            "status": "satisfied" if output.exists() else "violated",
            "reason": "Expected output file was not found.",
            "scope": "Saved file at the recorded path only",
        }
        source = review.render(
            {
                "state": "completed",
                "steps": [
                    {
                        "request": {"kind": "key", "key": "ctrl+s"},
                        "dispatch_state": "acknowledged",
                        "result": {"delivered": True},
                        "checks": [check],
                    }
                ],
            }
        )
        parsed = ParsedReport(source)
        visible = " ".join(parsed.words)
        self.assertIn("Response returned", visible)
        self.assertIn("Violated: Output file", visible)
        self.assertIn("Review the result before continuing", visible)
        self.assertIn("0 satisfied, 1 violated, 0 unknown", visible)
        self.assertIn(("strong", {"class": "violated"}), parsed.tags)
        self.assertNotIn(("strong", {"class": "satisfied"}), parsed.tags)

    def test_unknown_and_observation_failure_remain_prominent(self):
        source = review.render(
            {
                "state": "delivery_unknown",
                "steps": [
                    {
                        "request": {"kind": "click"},
                        "dispatch_state": "uncertain",
                        "result": {"observation_error": "capture unavailable"},
                        "checks": [
                            {"status": "unknown", "reason": "No complete listing"}
                        ],
                    }
                ],
            }
        )
        visible = " ".join(ParsedReport(source).words)
        self.assertIn("Delivery unknown", visible)
        self.assertIn("1 unknown", visible)
        self.assertIn("Observation unavailable: capture unavailable", visible)
        self.assertIn("before repeating", visible)

    def test_satisfied_checks_do_not_claim_general_task_success(self):
        source = review.render(
            {
                "predicate": {"kind": "file"},
                "status": "satisfied",
                "reason": "File exists",
                "scope": "One output file",
            }
        )
        visible = " ".join(ParsedReport(source).words)
        self.assertIn("Satisfied: Output file", visible)
        self.assertIn("Scope: One output file", visible)
        self.assertIn("not new verification", visible)
        self.assertNotIn("Task succeeded", visible)

    def test_active_markup_and_external_assets_are_never_rendered(self):
        payload = (
            '<script>alert("bad")</script><img src="https://example.invalid/leak">'
        )
        source = review.render(
            {
                "checks": [{"status": "unknown", "reason": payload}],
                "url": "https://example.invalid/path",
            }
        )
        parsed = ParsedReport(source)
        self.assertIn("&lt;script&gt;", source)
        self.assertFalse(
            any(
                tag in ("script", "img", "iframe", "a", "form")
                for tag, _ in parsed.tags
            )
        )
        self.assertFalse(
            any("href" in attrs or "src" in attrs for _, attrs in parsed.tags)
        )
        self.assertTrue(any(tag == "details" for tag, _ in parsed.tags))
        self.assertIn("default-src &#x27;none&#x27;", source.replace("'", "&#x27;"))

    def test_default_redaction_covers_nested_values_and_url_credentials(self):
        source = review.render(
            {
                "steps": [
                    {
                        "request": {
                            "kind": "type",
                            "text": "private-text-123",
                            "actual_value": "private-value-456",
                            "password": "pw-789",
                            "url": "https://someone:pw-abc@example.invalid/path?token=query-secret#fragment-secret",
                        },
                        "dispatch_state": "acknowledged",
                        "result": {"stdout": "private-log-321"},
                    }
                ],
                "metadata": {
                    "api_key": "api-secret-654",
                    "reason": "Bearer inline-secret-987",
                },
            }
        )
        for secret in (
            "private-text-123",
            "private-value-456",
            "pw-789",
            "pw-abc",
            "query-secret",
            "fragment-secret",
            "private-log-321",
            "api-secret-654",
            "inline-secret-987",
        ):
            self.assertNotIn(secret, source)
        self.assertIn("https://example.invalid/path", source)
        self.assertIn("[redacted]", source)

    def test_expected_values_arguments_and_private_paths_are_redacted(self):
        source = review.render(
            {
                "checks": [
                    {
                        "status": "unknown",
                        "predicate": {
                            "equals": "private-equality-123",
                            "path": "/home/private/file-456",
                        },
                    }
                ],
                "steps": [
                    {
                        "request": {
                            "action": "launch",
                            "argv": ["app", "positional-password-789"],
                            "args": ["private-args-321"],
                            "cwd": "/home/private/cwd-987",
                            "command": "app positional-command-secret-111",
                        }
                    }
                ],
                "references": ["file:///home/private/secret-654.csv"],
                "file": "/private/file-222",
                "home": "/home/private/home-333",
                "output_path": "/home/private/output-444",
                "filename": "private-name-555",
            }
        )
        for secret in (
            "private-equality-123",
            "file-456",
            "positional-password-789",
            "private-args-321",
            "cwd-987",
            "secret-654",
            "file-222",
            "home-333",
            "positional-command-secret-111",
            "output-444",
            "private-name-555",
        ):
            self.assertNotIn(secret, source)
        self.assertIn("[redacted file URL]", source)

    def test_omitted_or_malformed_evidence_never_establishes_completion(self):
        source = review.render(
            {"steps": [None] * (review.MAX_STEPS + 1), "checks": ["broken"]}
        )
        visible = " ".join(ParsedReport(source).words)
        self.assertIn("Evidence coverage is limited", visible)
        self.assertIn("Unknown:", visible)
        self.assertIn("Delivery is unknown", visible)

    def test_report_file_is_private_and_replaces_symlink_without_following(self):
        target = self.root / "target"
        target.write_text("keep")
        output = self.root / "report.html"
        output.symlink_to(target)
        result = review.write_report({}, output)
        self.assertEqual(result["path"], str(output))
        self.assertEqual(target.read_text(), "keep")
        self.assertFalse(output.is_symlink())
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)

    def test_invalid_or_oversized_input_preserves_previous_report(self):
        source = self.root / "input.json"
        output = self.root / "report.html"
        output.write_text("keep")
        for data in ("[1]", "{", "x" * (review.MAX_INPUT_BYTES + 1)):
            source.write_text(data)
            with self.assertRaises(DesktopError):
                review.from_file(source, output)
            self.assertEqual(output.read_text(), "keep")
        with (
            patch.object(review, "MAX_OUTPUT_BYTES", 128),
            self.assertRaises(DesktopError),
        ):
            review.write_report({}, output)
        self.assertEqual(output.read_text(), "keep")

    def test_named_pipe_input_is_refused_without_waiting_for_a_writer(self):
        source = self.root / "input-pipe"
        os.mkfifo(source)
        with self.assertRaisesRegex(DesktopError, "regular JSON file"):
            review.from_file(source, self.root / "report.html")

    def test_cli_renders_without_a_desktop(self):
        source = self.root / "input.json"
        source.write_text(json.dumps({"checks": [{"status": "unknown"}]}))
        output = self.root / "review.html"
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from agent_desktop.cli import main; raise SystemExit(main())",
                "review",
                "--input",
                str(source),
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "AGENT_DESKTOP_STATE_DIR": str(self.root / "unused-state"),
            },
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue(output.exists())
        self.assertTrue(json.loads(result.stdout)["experimental"])
        self.assertFalse((self.root / "unused-state").exists())
