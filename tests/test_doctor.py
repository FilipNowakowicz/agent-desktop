"""The preflight check reports missing tools, affected runtimes and repairs."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_desktop import doctor


class DoctorTests(unittest.TestCase):
    def test_missing_required_tools_fail_with_hints(self):
        with mock.patch.dict(os.environ, {"PATH": "/nonexistent"}):
            result = doctor.doctor()
        self.assertEqual(result["status"], "fail")
        failed = {c["check"] for c in result["checks"] if c["status"] == "fail"}
        self.assertLessEqual({"labwc", "grim", "dbus-daemon"}, failed)
        self.assertTrue(
            all(c.get("hint") for c in result["checks"] if c["status"] == "fail")
        )

    def test_stock_affected_wlroots_warns_and_repair_is_recognised(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory) / "libwlroots-0.20.so"
            library.write_bytes(b"")

            def fake_run(argv, timeout=5):
                if argv[1:] == ["--version"]:
                    return 0, "labwc 0.20.2 (+xwayland) wlroots-0.20.2"
                return 0, f"\tlibwlroots-0.20.so => {library} (0x0)"

            with mock.patch.object(doctor, "run", fake_run):
                stock = doctor.wlroots("labwc")
                (Path(directory) / doctor.REPAIR_MARKER).write_text(
                    "wlroots 0.20.2 with abc"
                )
                repaired = doctor.wlroots("labwc")
        self.assertEqual(stock["status"], "warn")
        self.assertEqual(stock["version"], "0.20.2")
        self.assertIn("build_xwayland_runtime.sh", stock["hint"])
        self.assertEqual(repaired["status"], "ok")
        self.assertIn("repaired runtime", repaired["detail"])

    def test_version_from_library_name_when_labwc_omits_it(self):
        def fake_run(argv, timeout=5):
            if argv[1:] == ["--version"]:
                return 0, "labwc 0.9.6"
            return 0, "\tlibwlroots-0.19.so => /nonexistent/libwlroots-0.19.so (0x0)"

        with mock.patch.object(doctor, "run", fake_run):
            result = doctor.wlroots("labwc")
        self.assertEqual(result["version"], "0.19")
        self.assertEqual(result["status"], "warn")
        self.assertIn("patch level is unknown", result["detail"])

    def test_unknown_version_is_explained(self):
        def fake_run(argv, timeout=5):
            if argv[1:] == ["--version"]:
                return 0, "labwc 0.7.1"
            return 0, "\tlibwlroots.so.12 => /nonexistent/libwlroots.so.12 (0x0)"

        with mock.patch.object(doctor, "run", fake_run):
            result = doctor.wlroots("labwc")
        self.assertIsNone(result["version"])
        self.assertIn("could not determine", result["detail"])

    def test_runtime_directory_problems_fail(self):
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/nonexistent/runtime"}):
            self.assertEqual(doctor.runtime_directory()["status"], "fail")
        with tempfile.TemporaryDirectory() as directory:
            deep = Path(directory) / ("d" * 90)
            deep.mkdir()
            with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(deep)}):
                result = doctor.runtime_directory()
        self.assertEqual(result["status"], "fail")
        self.assertIn("too long", result["detail"])

    @unittest.skipUnless(
        all(shutil.which(t) for t in ("labwc", "grim", "dbus-daemon")),
        "desktop tools unavailable",
    )
    def test_smoke_creates_captures_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"AGENT_DESKTOP_STATE_DIR": directory}):
                result = doctor.doctor(with_smoke=True)
        smoke = next(c for c in result["checks"] if c["check"] == "smoke")
        self.assertEqual(smoke["status"], "ok", smoke)
        self.assertNotEqual(result["status"], "fail")


if __name__ == "__main__":
    unittest.main()
