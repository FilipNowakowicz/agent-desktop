"""Repeat the Xwayland mapping and input test with busy CPU processes."""

import argparse
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

NAME = "test_runtime.RuntimeTests.test_xwayland_application_receives_input"

parser = argparse.ArgumentParser()
parser.add_argument("--repetitions", type=int, default=100)
parser.add_argument("--load", type=int, default=4, help="busy CPU processes")
args = parser.parse_args()

suite = unittest.TestSuite(
    unittest.defaultTestLoader.loadTestsFromName(NAME) for _ in range(args.repetitions)
)
load = []
try:
    for _ in range(args.load):
        load.append(subprocess.Popen([sys.executable, "-c", "while True: pass"]))
    result = unittest.TextTestRunner(verbosity=2, failfast=True).run(suite)
finally:
    for child in load:
        child.terminate()
    for child in load:
        child.wait()
sys.exit(not result.wasSuccessful())
