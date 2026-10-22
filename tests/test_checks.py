"""Predicate evidence is scoped; partial reads cannot fabricate completion."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_desktop import checks, core


def node(name="Save", **extra):
    return {
        "id": "n1",
        "name": name,
        "role": "check box",
        "states": ["checked"],
        **extra,
    }


def tree(nodes=None, **extra):
    return {
        "nodes": [node()] if nodes is None else nodes,
        "truncated": False,
        "unreadable": 0,
        **extra,
    }


class PredicateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.info = {"home": str(self.home), "mode": "headless"}
        self.manifest = mock.patch.object(core, "manifest", return_value=self.info)
        self.manifest.start()
        self.addCleanup(self.manifest.stop)
        self.request = mock.patch.object(
            core, "request", return_value={"owner": "agent"}
        ).start()
        self.addCleanup(mock.patch.stopall)

    def test_file_content_and_delayed_persistence(self):
        predicate = {"kind": "file", "path": "~/output", "text": "done"}
        self.assertEqual(checks.evaluate("session", predicate)["status"], "violated")
        (self.home / "output").write_text("done")
        result = checks.evaluate("session", predicate)
        self.assertEqual(result["status"], "satisfied")
        self.assertNotIn("done", str(result["evidence"]))
        (self.home / "output").write_text("wrong")
        self.assertEqual(checks.evaluate("session", predicate)["status"], "violated")
        self.assertEqual(
            checks.evaluate(
                "session", {"kind": "file", "path": "~/missing", "exists": False}
            )["status"],
            "satisfied",
        )

    def test_limits_errors_and_nonregular_files_are_unknown(self):
        (self.home / "output").write_bytes(b"x" * 20)
        predicate = {"kind": "file", "path": "~/output", "contains": "x"}
        with mock.patch.object(checks, "READ_LIMIT", 10):
            self.assertEqual(checks.evaluate("session", predicate)["status"], "unknown")
        with mock.patch.object(
            checks.os, "open", side_effect=PermissionError("secret path")
        ):
            result = checks.evaluate("session", predicate)
            self.assertEqual(result["status"], "unknown")
            self.assertNotIn("secret path", str(result))
        os.mkfifo(self.home / "fifo")
        self.assertEqual(
            checks.evaluate("session", {"kind": "file", "path": "~/fifo", "text": ""})[
                "status"
            ],
            "unknown",
        )
        (self.home / "output").write_bytes(b"\xff")
        self.assertEqual(checks.evaluate("session", predicate)["status"], "unknown")

    def test_config_value_duplicate_keys_and_wrong_outputs(self):
        path = self.home / "app.ini"
        predicate = {
            "kind": "config",
            "path": "~/app.ini",
            "key": "view/wrap",
            "value": "true",
        }
        path.write_text("[view]\nwrap=true\n")
        self.assertEqual(checks.evaluate("session", predicate)["status"], "satisfied")
        path.write_text("[view]\nwrap=false\n")
        self.assertEqual(checks.evaluate("session", predicate)["status"], "violated")
        for data in ("not an ini", "[view]\nwrap=false\nwrap=true\n"):
            path.write_text(data)
            self.assertEqual(checks.evaluate("session", predicate)["status"], "unknown")

    def test_human_control_and_host_files_refuse_observation(self):
        predicate = {"kind": "file", "path": "~/output"}
        self.request.return_value = {"owner": "human"}
        with mock.patch.object(checks, "file_check") as read:
            self.assertEqual(checks.evaluate("session", predicate)["status"], "unknown")
            read.assert_not_called()
        self.request.return_value = {"owner": "agent"}
        self.info["mode"] = "host"
        self.assertEqual(checks.evaluate("session", predicate)["status"], "unknown")

    def test_ui_evidence_rules_and_narrowed_scope(self):
        query = {"role": "check box", "window": "Settings"}

        def evaluate(source, **extra):
            self.request.side_effect = [{"owner": "agent"}, source]
            return checks.evaluate("session", {"kind": "ui", "query": query, **extra})

        for partial in ({"truncated": True}, {"unreadable": 1}):
            self.assertEqual(
                evaluate(tree(**partial), claim="exists")["status"], "satisfied"
            )
            self.assertEqual(
                evaluate(tree(**partial), claim="absent")["status"], "violated"
            )
            for claim in ("absent", "unique"):
                self.assertEqual(
                    evaluate(tree([], **partial), claim=claim)["status"], "unknown"
                )
            self.assertEqual(
                evaluate(tree(**partial), claim="unique")["status"], "unknown"
            )
            self.assertEqual(
                evaluate(tree(**partial), claim="all", state="checked")["status"],
                "unknown",
            )
            self.assertEqual(
                evaluate(
                    tree([node(states=[])], **partial), claim="all", state="checked"
                )["status"],
                "violated",
            )
        result = evaluate(tree(), claim="all", state="checked")
        self.assertEqual(result["status"], "satisfied")
        self.assertEqual(result["scope"]["window"], "Settings")
        self.request.assert_called_with(
            "session", "ui", None, max_nodes=2000, window="Settings"
        )
        self.assertEqual(
            evaluate(tree([]), claim="all", state="checked")["status"], "violated"
        )
        self.assertEqual(
            evaluate(tree([node(value=3)]), claim="value", equals=3)["status"],
            "satisfied",
        )
        self.assertEqual(
            evaluate(tree([node(value=2)]), claim="value", equals=3)["status"],
            "violated",
        )
        self.assertEqual(evaluate(tree(), claim="value", equals=3)["status"], "unknown")

    def test_missing_coverage_and_state_do_not_imply_completeness(self):
        for source in (
            {"nodes": []},
            {"nodes": [node()]},
            tree(truncated="false"),
            tree(unreadable=-1),
        ):
            for claim in ("absent", "unique"):
                status, _reason, _evidence = checks.ui_check(source, {"claim": claim})
                if claim == "absent" and source["nodes"]:
                    self.assertFalse(status)
                else:
                    self.assertIsNone(status)
        self.assertFalse(
            checks.ui_check(tree([node(), node()]), {"claim": "unique"})[0]
        )
        unknown = node()
        unknown.pop("states")
        self.assertIsNone(
            checks.ui_check(tree([unknown]), {"claim": "all", "state": "checked"})[0]
        )

    def test_browser_identity_and_observation_failure(self):
        predicate = {
            "kind": "browser_context",
            "context": "a",
            "url": "https://example.com/",
        }
        for tabs, status in (
            ([{"context": "a", "url": "https://example.com/"}], "satisfied"),
            ([{"context": "a", "url": "https://elsewhere.test/"}], "violated"),
            ([], "violated"),
        ):
            self.request.side_effect = [{"owner": "agent"}, {"tabs": tabs}]
            self.assertEqual(checks.evaluate("session", predicate)["status"], status)
        self.request.side_effect = core.DesktopError("unavailable")
        self.assertEqual(checks.evaluate("session", predicate)["status"], "unknown")

    def test_invalid_predicates_raise_before_observation(self):
        for predicate in (
            {"kind": "file", "path": "relative"},
            {"kind": "file", "path": "~/x", "contain": "typo"},
            {
                "kind": "ui",
                "claim": "all",
                "query": {"state": "checked"},
                "state": "checked",
            },
            {"kind": "ui", "query": {"exact": "yes"}},
            {"kind": "ui", "claim": "value"},
        ):
            with (
                self.subTest(predicate=predicate),
                self.assertRaises(core.DesktopError),
            ):
                checks.evaluate("session", predicate)
        self.request.assert_not_called()


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "dbus-daemon")),
    "desktop runtime unavailable",
)
class PrivateCheckTests(unittest.TestCase):
    def test_persisted_file_from_a_private_session(self):
        from test_runtime import wait_for

        from agent_desktop.worker import owned_processes

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "runtime").mkdir(mode=0o700)
            with mock.patch.dict(
                os.environ,
                {
                    "AGENT_DESKTOP_STATE_DIR": str(root / "state"),
                    "XDG_RUNTIME_DIR": str(root / "runtime"),
                },
            ):
                session = core.create()["session"]
                token = core.manifest(session)["token"]
                try:
                    core.request(
                        session,
                        "launch",
                        argv=["sh", "-c", "printf verified > result.txt"],
                    )
                    path = core.session_path(session) / "home/result.txt"
                    wait_for(path.exists)
                    predicate = {
                        "kind": "file",
                        "path": "~/result.txt",
                        "text": "verified",
                    }
                    self.assertEqual(
                        checks.evaluate(session, predicate)["status"], "satisfied"
                    )
                    path.write_text("incorrect")
                    self.assertEqual(
                        checks.evaluate(session, predicate)["status"], "violated"
                    )
                finally:
                    core.destroy(session)
                    wait_for(lambda: not owned_processes(token))
