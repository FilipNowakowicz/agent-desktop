"""Key event order and layout placement, without a compositor."""

import struct
import unittest

from agent_desktop import wayland
from agent_desktop.wayland import BindLayout, VirtualKeyboard

LOGO = wayland.MODIFIER_CODES["logo"]


class Recorder:
    def __init__(self):
        self.calls = []

    def send(self, _id, opcode, payload, fd=None):
        if opcode == 1:
            _time, code, state = struct.unpack("=III", payload)
            self.calls.append(("key", code, state))
        elif opcode == 2:
            self.calls.append(("mods", struct.unpack("=IIII", payload)[0]))
        else:
            self.calls.append(("keymap",))

    def roundtrip(self):
        pass


def keyboard():
    device = VirtualKeyboard.__new__(VirtualKeyboard)
    device.connection = Recorder()
    device.id = 1
    device.scratch = None
    device.extra = {}
    device.recent = list(wayland.POOL)
    device.pinned = set()
    device.overrides = {}
    device.held = {}
    device.mask = 0
    device.uploaded = device.keymap()
    device.dirty = False
    return device


def events(device):
    return [c for c in device.connection.calls if c[0] != "keymap"]


class ChordTests(unittest.TestCase):
    def test_chord_presses_and_releases_the_real_modifier(self):
        device = keyboard()
        device.key(ord("o"), ["logo"])
        self.assertEqual(
            events(device),
            [
                ("key", LOGO, 1),
                ("mods", 64),
                ("key", 24, 1),
                ("key", 24, 0),
                ("key", LOGO, 0),
                ("mods", 0),
            ],
        )

    def test_a_held_modifier_is_not_pressed_again(self):
        device = keyboard()
        device.down(0xFFEB)
        device.connection.calls.clear()
        device.key(0xFF09, ["logo"])
        self.assertEqual(events(device), [("key", 15, 1), ("key", 15, 0)])
        self.assertEqual(device.mask, 64)

    def test_release_all_lifts_modifiers_last(self):
        device = keyboard()
        device.down(0xFFEB)
        device.down(ord("a"))
        device.connection.calls.clear()
        device.release_all()
        self.assertEqual(
            events(device), [("key", 30, 0), ("key", LOGO, 0), ("mods", 0)]
        )
        self.assertEqual(device.held, {})

    def test_releasing_a_key_that_is_not_held_is_refused(self):
        with self.assertRaisesRegex(ValueError, "not held"):
            keyboard().up(ord("a"))

    def test_override_is_dropped_after_the_chord(self):
        device = keyboard()
        layout = FakeLayout({ord("l"): (25, False, [ord("l"), ord("L")])})
        device.connection.calls.clear()
        device.key(ord("l"), ["logo"], layout=layout)
        self.assertIn(("key", 25, 1), events(device))
        self.assertEqual(device.overrides, {})
        self.assertTrue(device.dirty)


class FakeLayout:
    def __init__(self, places):
        self.places = places

    def place(self, keysym):
        return self.places.get(keysym)


@unittest.skipUnless(wayland.find_xkbcommon(), "libxkbcommon unavailable")
class BindLayoutTests(unittest.TestCase):
    def setUp(self):
        self.library = wayland.ctypes.CDLL(wayland.find_xkbcommon())

    def test_dvorak_places_letters_on_their_physical_keys(self):
        layout = BindLayout(self.library, layout="us", variant="dvorak")
        # What Hyprland reads as l, n and o on Dvorak.
        self.assertEqual(layout.place(ord("l"))[:2], (25, False))
        self.assertEqual(layout.place(ord("n"))[:2], (38, False))
        self.assertEqual(layout.place(ord("o"))[:2], (31, False))
        # Digits, Tab and media keys do not move.
        self.assertEqual(layout.place(ord("1"))[:2], (2, False))
        self.assertEqual(layout.place(0xFF09)[0], 15)
        self.assertEqual(layout.place(0x1008FF13)[0], 115)

    def test_a_us_layout_matches_the_virtual_keyboard(self):
        layout = BindLayout(self.library, layout="us")
        self.assertEqual(layout.place(ord("l"))[:2], (38, False))
        self.assertEqual(layout.place(ord("L"))[:2], (38, True))


if __name__ == "__main__":
    unittest.main()
