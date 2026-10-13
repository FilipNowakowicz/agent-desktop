"""The compositor renders in software unless a GPU renderer is requested."""

import glob
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from test_runtime import wait_for

from agent_desktop import core
from agent_desktop.worker import owned_processes

VARIABLES = (
    "AGENT_DESKTOP_STATE_DIR",
    "XDG_RUNTIME_DIR",
    "AGENT_DESKTOP_RENDERER",
    "AGENT_DESKTOP_RENDER_DEVICE",
    "WLR_RENDER_DRM_DEVICE",
)
RENDER_NODES = sorted(
    node
    for node in glob.glob("/dev/dri/renderD*")
    if os.access(node, os.R_OK | os.W_OK)
)


def compositor_environment(session):
    pid = core.manifest(session)["compositor_pid"]
    entries = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    return dict(e.decode().split("=", 1) for e in entries if b"=" in e)


def compositor_devices(session):
    pid = core.manifest(session)["compositor_pid"]
    devices = set()
    for fd in Path(f"/proc/{pid}/fd").iterdir():
        try:
            devices.add(os.readlink(fd))
        except FileNotFoundError:
            pass
    return devices


@unittest.skipUnless(
    all(shutil.which(t) for t in ("labwc", "grim", "dbus-daemon")),
    "desktop tools unavailable",
)
class RendererTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="desktop-renderer-")
        root = Path(self.temporary.name)
        self.previous = {k: os.environ.pop(k, None) for k in VARIABLES}
        (root / "runtime").mkdir(mode=0o700)
        os.environ["AGENT_DESKTOP_STATE_DIR"] = str(root / "state")
        os.environ["XDG_RUNTIME_DIR"] = str(root / "runtime")
        self.sessions = []

    def tearDown(self):
        for session in self.sessions:
            token = core.manifest(session)["token"]
            core.destroy(session)
            wait_for(lambda token=token: not owned_processes(token))
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temporary.cleanup()

    def test_software_by_default(self):
        session = core.create()["session"]
        self.sessions.append(session)
        environment = compositor_environment(session)
        self.assertEqual(environment["WLR_RENDERER"], "pixman")
        self.assertNotIn("WLR_RENDER_DRM_DEVICE", environment)

    @unittest.skipUnless(RENDER_NODES, "no accessible GPU render node")
    def test_gpu_renderer_and_device(self):
        node = RENDER_NODES[0]
        os.environ["AGENT_DESKTOP_RENDERER"] = "gles2"
        os.environ["AGENT_DESKTOP_RENDER_DEVICE"] = node
        session = core.create()["session"]
        self.sessions.append(session)
        environment = compositor_environment(session)
        self.assertEqual(environment["WLR_RENDERER"], "gles2")
        self.assertEqual(environment["WLR_RENDER_DRM_DEVICE"], node)
        self.assertIn(node, compositor_devices(session))
        shot = core.request(session, "screenshot")
        self.assertEqual((shot["width"], shot["height"]), (1280, 720))
        self.assertTrue(Path(shot["path"]).stat().st_size > 0)


if __name__ == "__main__":
    unittest.main()
