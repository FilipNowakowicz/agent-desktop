"""Accessibility listings stay bounded by nodes, visits and time (no desktop)."""

import time
import unittest

from agent_desktop.atspi import REGISTRY, Accessibility


class FakeTree(Accessibility):
    """A synthetic accessibility bus: `shape` maps a node to its children."""

    def __init__(self, shape, delay=0.0, unnamed=False):
        self.shape = shape
        self.delay = delay
        self.unnamed = unnamed

    def children(self, node):
        return self.shape.get(node, [])

    def get(self, node, _interface, _name):
        return f"app{node[1]}"

    def describe(self, node):
        time.sleep(self.delay)
        name = "" if self.unnamed else f"button {node[1]}"
        role = "panel" if self.unnamed else "button"
        return {"id": "".join(node), "role": role, "name": name, "states": []}, True


def chain(length):
    """One application whose window holds `length` nested unnamed panels."""
    shape = {REGISTRY: [(":1.1", "/app")], (":1.1", "/app"): [(":1.1", "/0")]}
    for index in range(length):
        shape[(":1.1", f"/{index}")] = [(":1.1", f"/{index + 1}")]
    return shape


class TreeBoundTests(unittest.TestCase):
    def test_application_records_count_toward_the_node_limit(self):
        apps = [(f":1.{i}", f"/a{i}") for i in range(3)]
        tree = FakeTree({REGISTRY: apps}).tree(max_nodes=1)
        self.assertEqual(len(tree["nodes"]), 1)
        self.assertTrue(tree["truncated"])
        self.assertEqual(tree["truncated_by"], "node limit")

    def test_unnamed_containers_hit_the_visit_limit(self):
        tree = FakeTree(chain(5000), unnamed=True).tree(max_nodes=50)
        self.assertEqual(tree["truncated_by"], "visit limit")
        self.assertEqual(len(tree["nodes"]), 1)  # only the application

    def test_slow_application_hits_the_time_budget(self):
        started = time.monotonic()
        tree = FakeTree(chain(200), delay=0.01).tree(max_nodes=1000, budget=0.3)
        self.assertEqual(tree["truncated_by"], "time limit")
        self.assertLess(time.monotonic() - started, 1.0)

    def test_cycles_terminate(self):
        shape = chain(3)
        shape[(":1.1", "/3")] = [(":1.1", "/0")]  # back to the top
        tree = FakeTree(shape).tree(max_nodes=100)
        self.assertEqual(len(tree["nodes"]), 1 + 4)
        self.assertFalse(tree["truncated"])

    def test_complete_listing_is_not_truncated(self):
        tree = FakeTree(chain(3)).tree(max_nodes=100)
        self.assertFalse(tree["truncated"])
        self.assertIsNone(tree["truncated_by"])


if __name__ == "__main__":
    unittest.main()
