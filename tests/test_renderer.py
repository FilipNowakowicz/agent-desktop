"""The compositor renders in software unless a GPU renderer is configured."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_runtime import wait_for

from agent_desktop import core, doctor
from agent_desktop.worker import owned_processes

UNSET = ("AGENT_DESKTOP_RENDERER", "AGENT_DESKTOP_RENDER_DEVICE")


def configured(**variables):
    environment = {k: v for k, v in os.environ.items() if k not in UNSET}
    return mock.patch.dict(os.environ, {**environment, **variables}, clear=True)


class RendererConfigurationTests(unittest.TestCase):
    def test_software_by_default(self):
        with configured():
            self.assertEqual(
                core.compositor_renderer(), {"name": "pixman", "device": None}
            )

    def test_invalid_configurations_are_refused(self):
        node = next(iter(core.render_nodes()), "/dev/dri/renderD128")
        for variables in (
            {"AGENT_DESKTOP_RENDERER": "gl"},
            {"AGENT_DESKTOP_RENDER_DEVICE": node},
            {
                "AGENT_DESKTOP_RENDERER": "gles2",
                "AGENT_DESKTOP_RENDER_DEVICE": "/dev/null",
            },
        ):
            with self.subTest(**variables), configured(**variables):
                with self.assertRaises(core.DesktopError):
                    core.compositor_renderer()
                self.assertEqual(doctor.renderer()["status"], "fail")

    def test_doctor_asks_for_a_device_when_there_is_a_choice(self):
        nodes = {"/dev/dri/renderD128": "i915", "/dev/dri/renderD129": "nvidia"}
        with (
            configured(AGENT_DESKTOP_RENDERER="gles2"),
            mock.patch.object(core, "render_nodes", return_value=nodes),
        ):
            check = doctor.renderer()
        self.assertEqual(check["status"], "warn")
        self.assertIn("/dev/dri/renderD129 (nvidia)", check["hint"])


def compositor(session):
    pid = core.manifest(session)["compositor_pid"]
    entries = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    environment = dict(e.decode().split("=", 1) for e in entries if b"=" in e)
    devices = set()
    for fd in Path(f"/proc/{pid}/fd").iterdir():
        try:
            devices.add(os.readlink(fd))
        except OSError:
            pass
    return environment, devices


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "dbus-daemon")),
    "desktop tools unavailable",
)
class RendererSessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-renderer-")
        root = Path(self.temporary.name)
        (root / "run").mkdir(mode=0o700)
        self.isolated = configured(
            AGENT_DESKTOP_STATE_DIR=str(root / "state"),
            XDG_RUNTIME_DIR=str(root / "run"),
        )
        self.isolated.start()
        self.created = []

    def tearDown(self):
        for session in self.created:
            info = core.manifest(session)
            if info["status"] == "ready":
                core.destroy(session)
            wait_for(lambda info=info: not owned_processes(info["token"]))
        self.isolated.stop()
        self.temporary.cleanup()

    def test_software_session_ignores_a_host_render_node(self):
        # A render node chosen for the person's own compositor is not inherited.
        os.environ["WLR_RENDER_DRM_DEVICE"] = "/dev/dri/renderD128"
        session = core.create()["session"]
        self.created.append(session)
        environment, _ = compositor(session)
        self.assertEqual(environment["WLR_RENDERER"], "pixman")
        self.assertIsNone(environment.get("WLR_RENDER_DRM_DEVICE"))
        self.assertEqual(
            core.request(session, "status")["renderer"],
            {"name": "pixman", "device": None},
        )

    @unittest.skipUnless(core.render_nodes(), "no accessible render node")
    def test_gles2_on_each_usable_render_node(self):
        # A node may be accessible but unusable here (e.g. a vendor GL driver
        # outside this environment); that is reported, not counted as a pass.
        usable = []
        for node in core.render_nodes():
            os.environ["AGENT_DESKTOP_RENDERER"] = "gles2"
            os.environ["AGENT_DESKTOP_RENDER_DEVICE"] = node
            with self.subTest(node=node):
                try:
                    session = core.create()["session"]
                except core.DesktopError as error:
                    if "Failed to create a GLES2 renderer" not in str(error):
                        raise
                    continue
                self.created.append(session)
                environment, devices = compositor(session)
                self.assertEqual(environment["WLR_RENDERER"], "gles2")
                self.assertEqual(environment["WLR_RENDER_DRM_DEVICE"], node)
                self.assertIn(node, devices)
                shot = core.request(session, "screenshot")
                self.assertEqual((shot["width"], shot["height"]), (1280, 720))
                self.assertGreater(Path(shot["path"]).stat().st_size, 0)
                usable.append(node)
        if not usable:
            self.skipTest("no render node could start a GLES2 compositor")


if __name__ == "__main__":
    unittest.main()
