"""Hiding secret-looking text in browser replies (2026-11-20 field report).

Every credential below is a fake made for these tests.
"""

import json
import random
import string
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_desktop import browser
from agent_desktop.secret_text import cut, hide, hide_fields, looks_secret, marker
from agent_desktop.worker import Worker

FAKE_TAILSCALE = (
    "tskey-" + "api-kFAKE0EXAMPLE1CNTRL-FAKE0123456789abcdefFAKE0123456789xy"
)

# Prefixes are joined at run time so that secret scanners don't flag the fakes.
SECRETS = [
    FAKE_TAILSCALE,
    "tskey-" + "auth-kFAKE1CNTRL-0000FAKE",
    "ghp_" + "FAKE0000000000000000000000000000fake",
    "gho_" + "FAKE0000000000000000000000000000fake",
    "github_pat_" + "11FAKE000_0000000000000000000000fake",
    "glpat-" + "FAKEfake0123456789ab",
    "sk-" + "FAKEfakeFAKEfake0123456789",
    "sk-" + "ant-api03-FAKEfakeFAKEfake0123456789-FAKE",
    "sk_live_" + "FAKE0123456789fake",
    "xoxb-" + "000000000000-FAKEFAKEFAKE",
    "AKIA" + "FAKE0EXAMPLE0000",
    "AIza" + "FAKE_fake-FAKE0000000000000000000000",
    "ya29." + "FAKE-fake_FAKE0000000000000000",
    "npm_" + "FAKE0000000000000000000000000000fake",
    "pypi-" + "AgEIFAKEfakeFAKE0000000000000000000",
    "hf_" + "FAKE0000000000000000000000000000fake",
    "eyJhbGciOiJub25lIn0.eyJzdWIiOiJmYWtlIn0.RkFLRXNpZ25hdHVyZQ",
    # No known prefix: random base62 and base64.
    "q8Zr2LmX0vB7nT4kW9cY1pD6sF3hJ5gA",
    "Zm9vYmFyMTIzNDU2Nzg5MGZha2Vmb2tl/QwE7+rT9uY1==",
    "a3f9k2m8q1z7x4c6v0b5n9j2h8g4d1s7",  # lower case and digits
]

ORDINARY = [
    "Remind me later",
    "Generate API key",
    "Your API key is shown once. Copy it now.",
    "internationalization",
    "pneumonoultramicroscopicsilicovolcanoconiosis",
    "MuiButtonBase-root-MuiButton-root css-1q2w3e4-MenuList",
    "getElementByIdForTesting123",
    "ThisIsAVeryLongCamelCaseIdentifier",
    "ENTERPRISE_EDITION_LICENSE_KEY",
    "x86_64-unknown-linux-gnu",
    "libwebkit2gtk-4.1-0_2.44.2-1_amd64.deb",
    "firefox-133.0.3.tar.bz2 v1.2.3-beta.4+build.5678",
    "n2d-highcpu-16 in europe-west4-a, my-project-20261120",
    "IMG_20261120_123456789.jpg",
    "123456789012345678901234",
    "2026-11-20T00:52:54.123Z",
    # Paths and URLs.
    "src/agent_desktop/worker.py",
    "docs/trials/2026-11-20-vpn-token-and-quota-check.md",
    "/nix/store/0c6x7l5v9fake2fake3fake4fake5fake-firefox-133.0",
    "projects/my-project-123456/locations/us-central1/operations",
    "https://console.example.test/iam-admin/quotas?project=my-project-123456",
    # CSS selectors, as a find reply's text can quote them.
    "[role=dialog] code, [role=dialog] button",
    "div.card > span:nth-of-type(2) #token-field",
    # Hashes, digests and identifiers: shown on purpose.
    "Commit 3f786850e387550fdab836ed7e6dc881de23001b fixed it",
    "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "Request 123e4567-e89b-12d3-a456-426614174000 failed",
    "operation-1732060000000-6273a4b2c1d0e-9f8e7d6c-5b4a3c2d",
    "0xDEADBEEFDEADBEEFDEADBEEFDEADBEEF",
    # Words that start like a prefix.
    "sk-learn task-runner-2026 risk-assessment",
]


class DetectorTests(unittest.TestCase):
    def test_credentials_are_hidden(self):
        for secret in SECRETS:
            with self.subTest(secret=secret):
                self.assertTrue(looks_secret(secret))
                text, hidden = hide(secret)
                self.assertTrue(hidden)
                self.assertEqual(text, marker(len(secret)))

    def test_ordinary_text_is_kept(self):
        for text in ORDINARY:
            with self.subTest(text=text):
                self.assertEqual(hide(text), (text, False))

    def test_only_the_secret_is_replaced_in_a_sentence(self):
        text, hidden = hide(f'Your key: "{FAKE_TAILSCALE}". Copy it now.')
        self.assertTrue(hidden)
        self.assertEqual(
            text,
            f'Your key: "{marker(len(FAKE_TAILSCALE))}". Copy it now.',
        )
        self.assertIn(f"{len(FAKE_TAILSCALE)} chars; use send", text)

    def test_a_private_key_block_hides_the_whole_text(self):
        block = (
            "-----BEGIN OPENSSH PRIVATE KEY----- FAKEfakeFAKE "
            "-----END OPENSSH PRIVATE KEY-----"
        )
        self.assertEqual(hide(block), (marker(len(block)), True))

    def test_most_random_strings_of_32_characters_are_caught(self):
        # The threshold trades misses on short random strings for no hiding
        # of names; generated credentials are usually 32 characters or more.
        rng = random.Random(20261120)
        alphabet = string.ascii_letters + string.digits
        caught = sum(
            looks_secret("".join(rng.choice(alphabet) for _ in range(32)))
            for _ in range(1000)
        )
        self.assertGreater(caught, 950)

    def test_fields_are_hidden_then_cut_and_listed(self):
        item = {
            "tag": "code",
            "text": "x " * 50 + FAKE_TAILSCALE,
            "label": "API key",
            "options": ["S", FAKE_TAILSCALE],
        }
        hide_fields(item, ("text", "label"), 120)
        hide_fields(item, ("options",))
        self.assertNotIn(FAKE_TAILSCALE, json.dumps(item))
        # The cut keeps the whole marker rather than splitting it.
        self.assertTrue(item["text"].endswith(marker(len(FAKE_TAILSCALE))))
        self.assertEqual(item["label"], "API key")
        self.assertEqual(item["options"][1], marker(len(FAKE_TAILSCALE)))
        self.assertEqual(item["hidden"], ["options", "text"])
        self.assertEqual(cut("abcdef", 3), "abc")


def bridge_with(items, cover=None):
    """A Browser whose page script returns the given find items or cover."""
    bridge = browser.Browser.__new__(browser.Browser)

    def call(function, arguments, context, ownership="none"):
        if function == browser.UNCOVERED:
            value = json.dumps(cover)
        else:
            value = json.dumps({"count": len(items), "items": items})
        return {"type": "string", "value": value}

    bridge.call = call
    return bridge


class BrowserReplyTests(unittest.TestCase):
    def test_find_hides_text_label_and_value(self):
        bridge = bridge_with(
            [
                {"tag": "code", "text": FAKE_TAILSCALE},
                {"tag": "input", "label": "Key", "value": FAKE_TAILSCALE},
                {"tag": "button", "text": "Copy"},
            ]
        )
        found = bridge.find("context", selector="[role=dialog] code")
        self.assertNotIn(FAKE_TAILSCALE, json.dumps(found))
        self.assertEqual(found["items"][0]["hidden"], ["text"])
        self.assertEqual(found["items"][1]["hidden"], ["value"])
        self.assertNotIn("hidden", found["items"][2])

    def test_ambiguity_message_lists_hidden_text(self):
        items = [{"tag": "code", "text": FAKE_TAILSCALE}, {"tag": "code", "text": "x"}]
        with self.assertRaisesRegex(browser.BrowserError, "2 elements match") as error:
            bridge_with(items).element("context", selector="code")
        self.assertNotIn(FAKE_TAILSCALE, str(error.exception))
        self.assertIn("looks like a secret", str(error.exception))

    def test_covered_names_the_dialog_and_its_text(self):
        cover = {
            "tag": "div",
            "id": None,
            "role": "dialog",
            "label": None,
            "class": "modal.prompt",
            "text": "Remind me later about two-step verification " + FAKE_TAILSCALE,
        }
        with self.assertRaises(browser.BrowserError) as error:
            bridge_with([], cover).uncovered("context", {"sharedId": "e"})
        message = str(error.exception)
        self.assertIn(
            'under div.modal.prompt[role=dialog] "Remind me later about two-step verifica …"',
            message,
        )
        self.assertIn("nothing was sent", message)

    def test_covered_by_a_backdrop_names_the_open_dialog(self):
        cover = {
            "tag": "div",
            "id": "backdrop",
            "text": "",
            "dialog": {"tag": "dialog", "label": "Security check", "text": "Later"},
        }
        with self.assertRaises(browser.BrowserError) as error:
            bridge_with([], cover).uncovered("context", {"sharedId": "e"})
        self.assertIn(
            'under div#backdrop; a dialog is open: dialog ("Security check") "Later"',
            str(error.exception),
        )

    def test_cover_text_is_hidden_when_it_looks_like_a_secret(self):
        cover = {"tag": "pre", "text": FAKE_TAILSCALE}
        with self.assertRaises(browser.BrowserError) as error:
            bridge_with([], cover).uncovered("context", {"sharedId": "e"})
        self.assertNotIn(FAKE_TAILSCALE[:20], str(error.exception))
        self.assertIn("<hidden: looks like a secret", str(error.exception))


class KeyActionTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.worker = Worker.__new__(Worker)
        self.worker.info = {"mode": "headless"}
        self.worker.env = {"HOME": str(Path(folder.name))}
        self.worker.browser = None
        self.worker.attach_browser = mock.Mock(return_value=False)

    def test_a_key_action_points_to_desktop_key(self):
        for action in ("key", "press", "type"):
            with self.subTest(action=action):
                with self.assertRaisesRegex(ValueError, "desktop_key") as error:
                    self.worker.browser_request({"action": action, "key": "Escape"})
                self.assertIn("action must be start", str(error.exception))
        self.worker.attach_browser.assert_not_called()

    def test_other_unknown_actions_list_the_valid_ones_only(self):
        with self.assertRaises(ValueError) as error:
            self.worker.browser_request({"action": "hover"})
        self.assertIn("action must be start", str(error.exception))
        self.assertNotIn("desktop_key", str(error.exception))

    def test_a_key_step_is_refused_before_any_step_runs(self):
        steps = [
            {"action": "click", "selector": "#a"},
            {"action": "key", "key": "Escape"},
        ]
        with self.assertRaisesRegex(
            ValueError, "Step 1: .*desktop_key.*nothing was run"
        ):
            self.worker.browser_steps(steps)
        self.worker.attach_browser.assert_not_called()


if __name__ == "__main__":
    unittest.main()
