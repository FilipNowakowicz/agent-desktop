"""Incomplete evidence and vanished targets must not authorize another action."""

import unittest
from unittest import mock

from agent_desktop import core, script
from agent_desktop.browser import Browser, BrowserError
from agent_desktop.worker import Worker


def node(ident="save", name="Save", depth=1, role="push button"):
    return {"id": ident, "name": name, "depth": depth, "role": role, "states": []}


def tree(nodes=None, **coverage):
    return {
        "nodes": [node()] if nodes is None else nodes,
        "truncated": False,
        "truncated_by": None,
        "unreadable": 0,
        **coverage,
    }


class CoverageTests(unittest.TestCase):
    def test_partial_reads_allow_presence_but_not_absence_or_dispatch(self):
        with mock.patch.object(core, "request", return_value=tree(unreadable=1)):
            self.assertTrue(
                core.wait("session", element="Save", timeout=0)["satisfied"]
            )
        with mock.patch.object(core, "request", return_value=tree([], unreadable=1)):
            absent = core.wait("session", element="Save", gone=True, timeout=0)
            self.assertFalse(absent["satisfied"])
            self.assertIn("unknown", absent["reason"])

        def read(_session, operation, *_args, **_kwargs):
            if operation == "observe":
                return {"observation": "a" * 16}
            if operation == "ui":
                return tree(truncated=True)
            self.fail(f"Unexpected dispatch: {operation}")

        with mock.patch.object(core, "request", side_effect=read):
            result = core.run_steps(
                "session",
                [{"action": "ui_action", "element": "Save", "name": "press"}],
                None,
                "controller",
            )
        self.assertEqual(result["completed"], 0)
        self.assertIn("incomplete", result["stopped"]["reason"])

    def test_partial_unique_match_never_sends_an_action(self):
        for coverage in (
            {"truncated": True, "truncated_by": "node limit"},
            {"unreadable": 1},
        ):
            with self.subTest(coverage=coverage):
                with mock.patch.object(core, "request", return_value=tree(**coverage)):
                    with self.assertRaisesRegex(core.DesktopError, "incomplete"):
                        core.resolve_element("session", None, element="Save")
                with mock.patch.object(
                    script, "request", return_value=tree(**coverage)
                ) as send:
                    with self.assertRaisesRegex(LookupError, "incomplete"):
                        script.press("Save")
                    self.assertEqual([c.args[0] for c in send.call_args_list], ["ui"])
                    # A positive witness is available without a uniqueness claim.
                    found = script.find("Save")
                    self.assertEqual(found[0]["id"], "save")
                    self.assertEqual(
                        found.coverage["unreadable"], coverage.get("unreadable", 0)
                    )

    def test_partial_empty_read_is_not_reported_as_absence(self):
        partial = tree([], unreadable=2)
        with mock.patch.object(script, "request", return_value=partial):
            with self.assertRaisesRegex(LookupError, "uniqueness is unknown"):
                script.one("Save")
        rendered = core.render_tree(partial)
        self.assertIn("2 unreadable", rendered)
        self.assertNotIn("no accessible elements", rendered)
        self.assertEqual(core.render_tree(tree([])), "(no accessible elements)")
        self.assertIn(
            "time limit",
            core.render_tree(tree([], truncated=True, truncated_by="time limit")),
        )

    def test_filtering_retains_source_coverage(self):
        nodes = [
            node("row", "SKU-1", 0, "table row"),
            node("cell", "SKU-1", 1, "table cell"),
            node(),
        ]
        with mock.patch.object(
            script, "request", return_value=tree(nodes, unreadable=1)
        ):
            self.assertTrue(script.find("Save", within="SKU-1").coverage["unreadable"])
            self.assertTrue(script.rows(within="SKU-1").coverage["unreadable"])
            with self.assertRaisesRegex(LookupError, "incomplete"):
                script.one("Save", within="SKU-1")

    def test_fresh_narrow_scope_can_be_complete(self):
        def read(operation, **kwargs):
            return tree(unreadable=0 if kwargs.get("window") == "Editor" else 1)

        with mock.patch.object(script, "request", side_effect=read) as send:
            with self.assertRaises(LookupError):
                script.one("Save")
            self.assertEqual(script.one("Save", window="Editor")["id"], "save")
            self.assertEqual(
                script.find(window="Editor").coverage["scope"]["window"], "Editor"
            )
            self.assertTrue(all(c.args[0] == "ui" for c in send.call_args_list))
        with mock.patch.object(core, "request", return_value=tree()):
            self.assertEqual(
                core.resolve_element("session", None, element="Save", window="Editor"),
                "save",
            )


class BrowserTargetTests(unittest.TestCase):
    def bridge(self):
        bridge = Browser.__new__(Browser)
        bridge.context = None
        bridge.command = mock.Mock(
            return_value={
                "contexts": [
                    {"context": "a", "url": "about:blank"},
                    {"context": "b", "url": "about:blank"},
                ]
            }
        )
        return bridge

    def test_binding_survives_reordering_and_loss_requires_reselection(self):
        bridge = self.bridge()
        self.assertEqual(bridge.target(), "b")
        bridge.command.return_value["contexts"].reverse()
        self.assertEqual(bridge.target(), "b")
        bridge.command.return_value = {"contexts": [{"context": "a"}]}
        for _ in range(2):
            with self.assertRaisesRegex(BrowserError, "target_lost"):
                bridge.target()
            self.assertEqual(bridge.context, "b")
        self.assertEqual(bridge.target(context="a"), "a")
        self.assertEqual(bridge.target(tab=0), "a")
        with self.assertRaises(ValueError):
            bridge.target(tab=0, context="a")
        with self.assertRaisesRegex(BrowserError, "target_lost"):
            bridge.target(context="b")
        self.assertEqual(bridge.context, "a")

    def test_tabs_expose_stable_ids(self):
        bridge = self.bridge()
        bridge.evaluate = mock.Mock(return_value="Page")
        self.assertEqual([t["context"] for t in bridge.tabs()[1]], ["a", "b"])

    def test_worker_refuses_lost_target_in_private_and_standin_host_modes(self):
        for mode in ("headless", "host"):
            bridge = self.bridge()
            bridge.context = "lost"
            worker = Worker.__new__(Worker)
            worker.info = {"mode": mode}
            worker.browser = (bridge, lambda: None)
            worker.agent_tabs = set()
            worker.attach_browser = lambda: True
            bridge.element = mock.Mock()
            for selection in ({}, {"context": "lost"}):
                with self.subTest(mode=mode, selection=selection):
                    with self.assertRaisesRegex(ValueError, "target_lost"):
                        worker.browser_request(
                            {"action": "click", "text": "Pay", **selection}
                        )
            bridge.element.assert_not_called()
            # Recovery discovery is observational and leaves the lost binding intact.
            bridge.evaluate = mock.Mock(return_value="Page")
            self.assertEqual(len(worker.browser_request({"action": "tabs"})["tabs"]), 2)
            self.assertEqual(bridge.context, "lost")
