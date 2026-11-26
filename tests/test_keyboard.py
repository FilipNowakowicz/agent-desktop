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
        layout = FakeLayout({ord("l"): (25, False, [ord("l"), ord("L")], None)})
        device.connection.calls.clear()
        device.key(ord("l"), ["logo"], layout=layout)
        self.assertIn(("key", 25, 1), events(device))
        self.assertEqual(device.overrides, {})
        self.assertTrue(device.dirty)

    def test_typed_text_goes_to_the_codes_of_a_nested_layout(self):
        device = keyboard()
        layout = FakeLayout(
            {
                ord("h"): (32, False, [], None),  # Dvorak: the key at US "d" reads h
                ord("H"): (32, True, [], None),
                ord("!"): (2, True, [], None),
            }
        )
        missing = device.type("hH!é", layout)
        self.assertEqual(missing, 1)
        shift = wayland.MODIFIER_CODES["shift"]
        self.assertEqual(
            [e[1:] for e in events(device) if e[0] == "key"][:8],
            [(32, 1), (32, 0), (shift, 1), (32, 1), (32, 0), (shift, 0)]
            + [(shift, 1), (2, 1)],
        )

    def test_a_shifted_placed_key_presses_a_real_shift(self):
        device = keyboard()
        layout = FakeLayout({ord("L"): (25, True, [ord("l"), ord("L")], None)})
        device.key(ord("L"), [], layout=layout)
        shift = wayland.MODIFIER_CODES["shift"]
        self.assertEqual(
            [e[1:] for e in events(device) if e[0] == "key"],
            [(shift, 1), (25, 1), (25, 0), (shift, 0)],
        )

    def test_a_shifted_placed_key_keeps_a_held_right_shift(self):
        # Pressing and releasing Shift_L here would clear the Shift mask while
        # the held Shift_R is still down.
        device = keyboard()
        device.down(0xFFE2)  # Shift_R, code 54
        device.connection.calls.clear()
        layout = FakeLayout({ord("L"): (25, True, [ord("l"), ord("L")], None)})
        device.key(ord("L"), [], layout=layout)
        self.assertEqual(events(device), [("key", 25, 1), ("key", 25, 0)])
        self.assertEqual(device.mask, wayland.SHIFT)

    def test_level_three_characters_hold_the_layouts_altgr(self):
        device = keyboard()
        layout = FakeLayout(
            {
                ord("@"): (16, False, [], 100),  # German: AltGr+q
                wayland.char_keysym("Ą"): (30, True, [], 100),  # Polish: Shift+AltGr+a
                ord("a"): (30, False, [], None),
            }
        )
        self.assertEqual(device.type("@Ąa", layout), 0)
        shift = wayland.MODIFIER_CODES["shift"]
        self.assertEqual(
            [e[1:] for e in events(device) if e[0] == "key"],
            [(100, 1), (16, 1), (16, 0), (100, 0)]
            + [(shift, 1), (100, 1), (30, 1), (30, 0), (100, 0), (shift, 0)]
            + [(30, 1), (30, 0)],
        )
        # AltGr is a real key press only: the parent's modifier mask is unchanged.
        self.assertNotIn(("mods", 8), events(device))

    def test_a_level_three_key_holds_altgr_inside_the_chord(self):
        device = keyboard()
        layout = FakeLayout({ord("@"): (16, False, [ord("q"), ord("Q")], 100)})
        device.key(ord("@"), [], layout=layout)
        self.assertEqual(
            [e[1:] for e in events(device) if e[0] == "key"],
            [(100, 1), (16, 1), (16, 0), (100, 0)],
        )

    def test_holding_a_level_three_character_is_refused(self):
        device = keyboard()
        layout = FakeLayout({ord("@"): (16, False, [], 100)})
        with self.assertRaisesRegex(ValueError, "AltGr"):
            device.down(ord("@"), layout)
        self.assertEqual(events(device), [])
        self.assertEqual(device.held, {})


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

    def test_typing_places_german_altgr_characters(self):
        layout = BindLayout(self.library, typing=True, layout="de")
        self.assertEqual(layout.level3, 100)  # Right Alt is AltGr
        for character, code in (
            ("@", 16),
            ("€", 18),  # AltGr+e, not evdev's EuroSign key past X11's 255
            ("{", 8),
            ("[", 9),
            ("\\", 12),
            ("~", 27),
            ("|", 86),
        ):
            placed = layout.place(wayland.char_keysym(character))
            self.assertEqual((placed[0], placed[1], placed[3]), (code, False, 100))
        # Level one and two keep their keys and need no AltGr.
        self.assertEqual(layout.place(ord("z"))[0::3], (21, None))
        self.assertEqual(layout.place(ord('"'))[:2], (3, True))

    def test_typing_places_polish_letters_by_their_unicode_keysyms(self):
        layout = BindLayout(self.library, typing=True, layout="pl")
        for character, code, shifted in (
            ("ą", 30, False),
            ("ł", 38, False),
            ("ż", 44, False),
            ("Ę", 18, True),
            ("Ń", 49, True),
        ):
            placed = layout.place(wayland.char_keysym(character))
            self.assertEqual(
                (placed[0], placed[1], placed[3]), (code, shifted, 100), character
            )

    def test_shortcut_layouts_do_not_place_altgr_levels(self):
        # Host shortcuts resolve through levels one and two only, as before.
        layout = BindLayout(self.library, layout="de")
        self.assertIsNone(layout.place(ord("@")))
        self.assertIsNone(layout.place(wayland.char_keysym("€")))
        self.assertIsNone(layout.place(ord("z"))[3])

    def test_a_us_layout_matches_the_virtual_keyboard(self):
        layout = BindLayout(self.library, layout="us")
        self.assertEqual(layout.place(ord("l"))[:2], (38, False))
        self.assertEqual(layout.place(ord("L"))[:2], (38, True))


if __name__ == "__main__":
    unittest.main()
