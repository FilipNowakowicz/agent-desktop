"""The preflight check reports missing tools, affected runtimes and repairs."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_desktop import core, doctor


class DoctorTests(unittest.TestCase):
    def test_missing_required_tools_fail_with_hints(self):
        environment = {"PATH": "/nonexistent", "XDG_DATA_HOME": "/nonexistent"}
        with mock.patch.dict(os.environ, environment):
            os.environ.pop("AGENT_DESKTOP_RUNTIME", None)
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

    def test_version_from_numbered_library_before_0_18(self):
        def fake_run(argv, timeout=5):
            if argv[1:] == ["--version"]:
                return 0, "labwc 0.7.1"
            return 0, "\tlibwlroots.so.12 => /nonexistent/libwlroots.so.12 (0x0)"

        with mock.patch.object(doctor, "run", fake_run):
            result = doctor.wlroots("labwc")
        self.assertEqual((result["version"], result["status"]), ("0.17", "ok"))

    def test_unknown_version_is_explained(self):
        def fake_run(argv, timeout=5):
            if argv[1:] == ["--version"]:
                return 0, "labwc 0.1.0"
            return 0, "\tlibwlroots.so.99 => /nonexistent/libwlroots.so.99 (0x0)"

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

    def test_registryd_found_in_libexec_beside_path_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "bin").mkdir()
            registryd = Path(directory) / "libexec" / "at-spi2-registryd"
            registryd.parent.mkdir()
            registryd.write_text("#!/bin/sh\n")
            registryd.chmod(0o755)
            environment = {"PATH": f"{directory}/bin"}
            with mock.patch.dict(os.environ, environment):
                os.environ.pop("AGENT_DESKTOP_AT_SPI_REGISTRYD", None)
                self.assertEqual(doctor.accessibility()["path"], str(registryd))

    def test_selected_runtime_goes_first_on_path(self):
        with tempfile.TemporaryDirectory() as directory:
            linked = Path(directory) / "agent-desktop" / "runtime"
            (linked / "bin").mkdir(parents=True)
            environment = {"PATH": "/usr/bin", "XDG_DATA_HOME": directory}
            with mock.patch.dict(os.environ, environment):
                os.environ.pop("AGENT_DESKTOP_RUNTIME", None)
                self.assertEqual(core.use_runtime(), linked)
                core.use_runtime()
                self.assertEqual(os.environ["PATH"], f"{linked}/bin:/usr/bin")
                self.assertEqual(doctor.runtime_selection()["path"], str(linked))
                os.environ["AGENT_DESKTOP_RUNTIME"] = f"{directory}/missing"
                self.assertEqual(doctor.runtime_selection()["status"], "fail")
            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": f"{directory}/empty"}):
                os.environ.pop("AGENT_DESKTOP_RUNTIME", None)
                self.assertIsNone(core.runtime_prefix())

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
