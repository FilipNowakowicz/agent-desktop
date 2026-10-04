"""Minimal Wayland client for session-local pointer input (no Python dependencies).

Speaks just enough of the wire protocol to bind wl_output and
zwlr_virtual_pointer_manager_v1 on one private compositor socket.
"""

import array
import ctypes
import socket
import struct
import tempfile
import time
from pathlib import Path

BUTTONS = {"left": 0x110, "right": 0x111, "middle": 0x112}
VERTICAL, HORIZONTAL = 0, 1
SOURCE_FINGER = 2


class WaylandError(RuntimeError):
    pass


def fixed(value):
    return int(round(value * 256))


def string(value):
    data = value.encode() + b"\0"
    return struct.pack("=I", len(data)) + data + b"\0" * (-len(data) % 4)


def timestamp():
    return int(time.monotonic() * 1000) & 0xFFFFFFFF


class Connection:
    def __init__(self, path, timeout=5):
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.settimeout(timeout)
        self.socket.connect(str(path))
        self.buffer = b""
        self.next_id = 2  # 1 is wl_display
        self.globals = {}
        self.outputs = {}
        self.listeners = {}
        self.registry = self.new_id()
        self.send(1, 1, struct.pack("=I", self.registry))  # wl_display.get_registry
        self.listeners[self.registry] = self.registry_event
        self.roundtrip()

    def close(self):
        self.socket.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def new_id(self):
        value = self.next_id
        self.next_id += 1
        return value

    def send(self, obj, opcode, payload=b"", fd=None):
        size = 8 + len(payload)
        message = struct.pack("=II", obj, size << 16 | opcode) + payload
        if fd is None:
            self.socket.sendall(message)
            return
        rights = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [fd]))]
        sent = self.socket.sendmsg([message], rights)
        if sent < len(message):
            self.socket.sendall(message[sent:])

    def bind(self, interface, version):
        if interface not in self.globals:
            raise WaylandError(f"Compositor does not provide {interface}")
        name, advertised = self.globals[interface][0]
        new = self.new_id()
        self.send(
            self.registry,
            0,
            struct.pack("=I", name)
            + string(interface)
            + struct.pack("=II", min(version, advertised), new),
        )
        return new

    def registry_event(self, opcode, payload):
        if opcode == 0:  # global(name, interface, version)
            name, length = struct.unpack_from("=II", payload)
            interface = payload[8 : 8 + length - 1].decode()
            offset = 8 + length + (-length % 4)
            (version,) = struct.unpack_from("=I", payload, offset)
            self.globals.setdefault(interface, []).append((name, version))

    def roundtrip(self):
        callback = self.new_id()
        done = []
        self.listeners[callback] = lambda _opcode, _payload: done.append(True)
        self.send(1, 0, struct.pack("=I", callback))  # wl_display.sync
        while not done:
            self.dispatch()
        del self.listeners[callback]

    def dispatch(self):
        while len(self.buffer) < 8:
            self.receive()
        obj, word = struct.unpack_from("=II", self.buffer)
        size, opcode = word >> 16, word & 0xFFFF
        while len(self.buffer) < size:
            self.receive()
        payload, self.buffer = self.buffer[8:size], self.buffer[size:]
        if obj == 1 and opcode == 0:  # wl_display.error(object, code, message)
            _, code, length = struct.unpack_from("=III", payload)
            message = payload[12 : 12 + length - 1].decode(errors="replace")
            raise WaylandError(f"Wayland protocol error {code}: {message}")
        listener = self.listeners.get(obj)
        if listener:
            listener(opcode, payload)

    def receive(self):
        data = self.socket.recv(65536)
        if not data:
            raise WaylandError("Compositor closed the connection")
        self.buffer += data

    def watch_output(self):
        """Bind the single output; its mode and scale stay current in the result."""
        outputs = self.globals.get("wl_output", [])
        if len(outputs) != 1:
            raise WaylandError(f"Expected one output, found {len(outputs)}")
        state = {"scale": 1}

        def event(opcode, payload):
            if opcode == 1:  # mode(flags, width, height, refresh)
                flags, width, height, _ = struct.unpack_from("=Iiii", payload)
                if flags & 1:  # current
                    state["width"], state["height"] = width, height
            elif opcode == 3:  # scale(factor)
                (state["scale"],) = struct.unpack_from("=i", payload)

        output = self.bind("wl_output", 2)
        self.listeners[output] = event
        self.roundtrip()
        if "width" not in state:
            raise WaylandError("Output reported no current mode")
        return state


class VirtualPointer:
    """A persistent virtual pointer on a private compositor socket.

    Keep one per session: destroying the seat's only pointer device removes the
    pointer capability, and clients may miss input until they rebind.
    """

    def __init__(self, display_path):
        self.connection = Connection(display_path)
        self.output = self.connection.watch_output()
        manager = self.connection.bind("zwlr_virtual_pointer_manager_v1", 1)
        self.id = self.connection.new_id()
        self.connection.send(manager, 0, struct.pack("=II", 0, self.id))
        self.connection.roundtrip()

    @property
    def size(self):
        return self.output["width"], self.output["height"]

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def request(self, opcode, fmt="", *values):
        self.connection.send(self.id, opcode, struct.pack("=" + fmt, *values))

    def check(self, x, y):
        # Process pending output events first so mode/scale changes apply.
        self.connection.roundtrip()
        if self.output["scale"] != 1:
            raise ValueError("Only output scale 1 is supported")
        width, height = self.size
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError("Coordinates outside private desktop")

    def move(self, x, y):
        width, height = self.size
        self.request(1, "IIIII", timestamp(), int(x), int(y), width, height)
        self.request(4)

    def button(self, name, pressed):
        self.request(2, "III", timestamp(), BUTTONS[name], int(pressed))
        self.request(4)

    def scroll(self, dy, dx):
        for axis, value in ((HORIZONTAL, dx), (VERTICAL, dy)):
            if value:
                self.request(5, "I", SOURCE_FINGER)
                self.request(3, "IIi", timestamp(), axis, fixed(value))
        self.request(4)
        for axis, value in ((HORIZONTAL, dx), (VERTICAL, dy)):
            if value:
                self.request(5, "I", SOURCE_FINGER)
                self.request(6, "II", timestamp(), axis)
        self.request(4)

    def sync(self):
        """Wait until the compositor has processed every request sent so far."""
        self.connection.roundtrip()


MODIFIERS = {"shift": 1, "ctrl": 4, "alt": 8, "logo": 64}
CONTROL_KEYSYMS = {"\n": 0xFF0D, "\t": 0xFF09, "\b": 0xFF08, "\x1b": 0xFF1B}
SHIFT = MODIFIERS["shift"]

# A US keyboard layout on real evdev codes. Applications such as Chromium also
# interpret physical codes (e.g. 14 is Backspace), so characters must not land
# on codes that mean something else.
US_ROWS = {
    2: "1!",
    3: "2@",
    4: "3#",
    5: "4$",
    6: "5%",
    7: "6^",
    8: "7&",
    9: "8*",
    10: "9(",
    11: "0)",
    12: "-_",
    13: "=+",
    16: "qQ",
    17: "wW",
    18: "eE",
    19: "rR",
    20: "tT",
    21: "yY",
    22: "uU",
    23: "iI",
    24: "oO",
    25: "pP",
    26: "[{",
    27: "]}",
    30: "aA",
    31: "sS",
    32: "dD",
    33: "fF",
    34: "gG",
    35: "hH",
    36: "jJ",
    37: "kK",
    38: "lL",
    39: ";:",
    40: "'\"",
    41: "`~",
    43: "\\|",
    44: "zZ",
    45: "xX",
    46: "cC",
    47: "vV",
    48: "bB",
    49: "nN",
    50: "mM",
    51: ",<",
    52: ".>",
    53: "/?",
    57: "  ",
}
# Function and modifier keys on their physical codes: keysym -> code.
NAMED_KEYS = {
    0xFF1B: 1,
    0xFF08: 14,
    0xFF09: 15,
    0xFF0D: 28,
    0xFFE3: 29,
    0xFFE1: 42,
    0xFFE9: 56,
    0xFFE5: 58,
    0xFF7F: 69,
    0xFF8D: 96,
    0xFF61: 99,
    0xFF50: 102,
    0xFF52: 103,
    0xFF55: 104,
    0xFF51: 105,
    0xFF53: 106,
    0xFF57: 107,
    0xFF54: 108,
    0xFF56: 109,
    0xFF63: 110,
    0xFFFF: 111,
    0xFFEB: 125,
    0xFF67: 127,
    0xFFE4: 97,
    0xFFE2: 54,
    0xFFEA: 100,
    **{0xFFBE + i: 59 + i for i in range(10)},  # F1-F10
    0xFFC8: 87,
    0xFFC9: 88,  # F11, F12
}
# Xwayland rejects a keymap without virtual-modifier mappings.
MODIFIER_MAP = {"Shift": 42, "Control": 29, "Mod1": 56, "Mod2": 69, "Mod4": 125}
# Codes no US layout uses but that applications still accept (102nd key, Ro,
# keypad =/,, Yen, keypad parentheses, F13-F24) carry every other keysym,
# remapped on demand. Chromium drops events from codes without a defined key
# (e.g. 84, 195), so those are excluded.
POOL = (86, 89, 117, 121, 124, 179, 180, *range(183, 195))
FIXED = {}
for _code, _pair in US_ROWS.items():
    for _level, _char in enumerate(_pair):
        FIXED.setdefault(ord(_char), (_code, _level))
FIXED.update({keysym: (code, 0) for keysym, code in NAMED_KEYS.items()})


def char_keysym(character):
    """Keysym for one character, matching xkbcommon's Unicode fallback rules."""
    if character in CONTROL_KEYSYMS:
        return CONTROL_KEYSYMS[character]
    point = ord(character)
    if point < 0x20 or 0x7F <= point < 0xA0 or 0xD800 <= point < 0xE000:
        raise ValueError(f"Cannot type control character U+{point:04X}")
    return point if point < 0x100 else 0x1000000 | point


class Keysyms:
    """Resolve keysym names with the libxkbcommon already loaded by the compositor."""

    def __init__(self, compositor_pid):
        library = None
        try:
            for line in Path(f"/proc/{compositor_pid}/maps").read_text().splitlines():
                path = line.split()[-1]
                if "/libxkbcommon.so" in path:
                    library = path
                    break
        except OSError:
            pass
        if not library:
            raise WaylandError("Cannot locate the compositor's libxkbcommon")
        self.library = ctypes.CDLL(library)
        self.library.xkb_keysym_from_name.restype = ctypes.c_uint32
        self.library.xkb_keysym_from_name.argtypes = [ctypes.c_char_p, ctypes.c_int]

    def resolve(self, name):
        keysym = self.library.xkb_keysym_from_name(name.encode(), 0)
        if not keysym:
            raise ValueError(f"Unknown key name: {name}")
        return keysym


class VirtualKeyboard:
    """A persistent virtual keyboard with a US layout plus on-demand extra keys.

    Keymap uploads and key events share one ordered connection, so a client
    always receives the keymap before the keys that need it.
    """

    def __init__(self, display_path, scratch_directory):
        self.connection = Connection(display_path)
        self.scratch = scratch_directory
        seat = self.connection.bind("wl_seat", 1)
        manager = self.connection.bind("zwp_virtual_keyboard_manager_v1", 1)
        self.id = self.connection.new_id()
        self.connection.send(manager, 0, struct.pack("=II", seat, self.id))
        self.extra = {}  # pool code -> keysym
        self.recent = list(POOL)  # least recently used first
        self.pinned = set()  # pool codes needed by keys not yet sent
        self.dirty = True
        self.upload()
        self.connection.roundtrip()

    def close(self):
        self.connection.close()

    def keymap(self):
        symbols = {}
        for code, pair in US_ROWS.items():
            symbols[code] = [ord(pair[0]), ord(pair[1])]
        for keysym, code in NAMED_KEYS.items():
            symbols[code] = [keysym]
        for code, keysym in self.extra.items():
            symbols[code] = [keysym]
        codes = sorted(symbols)
        lines = [
            "xkb_keymap {",
            'xkb_keycodes "(unnamed)" {',
            f"minimum = 8; maximum = {max(codes) + 8};",
            *(f"<K{c}> = {c + 8};" for c in codes),
            "};",
            'xkb_types "(unnamed)" { include "complete" };',
            'xkb_compatibility "(unnamed)" { include "complete" };',
            'xkb_symbols "(unnamed)" {',
            *(
                f"key <K{c}> {{[{', '.join(f'0x{k:x}' for k in symbols[c])}]}};"
                for c in codes
            ),
            *(f"modifier_map {m} {{ <K{c}> }};" for m, c in MODIFIER_MAP.items()),
            "};",
            "};",
        ]
        return ("\n".join(lines) + "\n").encode() + b"\0"

    def upload(self):
        data = self.keymap()
        with tempfile.TemporaryFile(dir=self.scratch) as stream:
            stream.write(data)
            stream.flush()
            # zwp_virtual_keyboard_v1.keymap(format=xkb_v1, fd, size)
            self.connection.send(
                self.id, 0, struct.pack("=II", 1, len(data)), fd=stream.fileno()
            )
            self.connection.roundtrip()
        self.dirty = False

    def lookup(self, keysym):
        """(code, shifted) for a keysym, or None if the extra pool is exhausted."""
        if keysym in FIXED:
            return FIXED[keysym][0], FIXED[keysym][1] == 1
        code = next((c for c, k in self.extra.items() if k == keysym), None)
        if code is None:
            free = [c for c in self.recent if c not in self.pinned]
            if not free:
                return None
            code = free[0]
            self.extra[code] = keysym
            self.dirty = True
        self.recent.remove(code)
        self.recent.append(code)
        self.pinned.add(code)
        return code, False

    def send(self, keys, mask=0, repeat=1):
        if self.dirty:
            self.upload()
        for code, shifted in keys:
            state = mask | (SHIFT if shifted else 0)
            if state:
                self.modifiers(state)
            for _ in range(repeat):
                self.tap(code)
            if state:
                self.modifiers(0)
        self.pinned.clear()

    def tap(self, code):
        self.connection.send(self.id, 1, struct.pack("=III", timestamp(), code, 1))
        self.connection.send(self.id, 1, struct.pack("=III", timestamp(), code, 0))

    def modifiers(self, mask):
        self.connection.send(self.id, 2, struct.pack("=IIII", mask, 0, 0, 0))

    def type(self, text):
        pending = []
        for keysym in [char_keysym(c) for c in text]:
            key = self.lookup(keysym)
            if key is None:
                # Every extra key is in use by pending keys: send them first.
                self.send(pending)
                pending = []
                key = self.lookup(keysym)
            pending.append(key)
        self.send(pending)
        self.connection.roundtrip()

    def key(self, keysym, modifiers=(), repeat=1):
        mask = 0
        for name in modifiers:
            mask |= MODIFIERS[name]
        self.send([self.lookup(keysym)], mask, repeat)
        self.connection.roundtrip()


TOPLEVEL_STATES = {0: "maximized", 1: "minimized", 2: "activated", 3: "fullscreen"}


def read_string(payload, offset=0):
    (length,) = struct.unpack_from("=I", payload, offset)
    return payload[offset + 4 : offset + 4 + length - 1].decode(errors="replace")


class Toplevels:
    """Live window list from the wlr foreign-toplevel protocol."""

    def __init__(self, display_path):
        self.connection = Connection(display_path)
        self.seat = self.connection.bind("wl_seat", 1)
        manager = self.connection.bind("zwlr_foreign_toplevel_manager_v1", 3)
        self.connection.listeners[manager] = self.manager_event
        self.windows = {}  # protocol object id -> window record
        self.serial = 0
        self.connection.roundtrip()

    def close(self):
        self.connection.close()

    def manager_event(self, opcode, payload):
        if opcode != 0:  # toplevel(new_id)
            return
        (handle,) = struct.unpack_from("=I", payload)
        self.serial += 1
        window = {
            "id": f"w{self.serial}",
            "title": "",
            "app_id": "",
            "states": [],
            "parent": None,
        }
        pending = dict(window)

        def event(opcode, payload):
            if opcode == 0:
                pending["title"] = read_string(payload)
            elif opcode == 1:
                pending["app_id"] = read_string(payload)
            elif opcode == 4:
                (length,) = struct.unpack_from("=I", payload)
                values = struct.unpack_from(f"={length // 4}I", payload, 4)
                pending["states"] = sorted(
                    TOPLEVEL_STATES[v] for v in values if v in TOPLEVEL_STATES
                )
            elif opcode == 5:  # done: apply the atomic update
                self.windows[handle] = dict(pending)
            elif opcode == 6:  # closed
                self.windows.pop(handle, None)
                self.connection.listeners.pop(handle, None)
                self.connection.send(handle, 7)  # destroy
            elif opcode == 7:
                (parent,) = struct.unpack_from("=I", payload)
                pending["parent"] = parent or None

        self.connection.listeners[handle] = event

    def current(self):
        self.connection.roundtrip()
        by_handle = {h: w["id"] for h, w in self.windows.items()}
        return [
            {**w, "parent": by_handle.get(w["parent"])} for w in self.windows.values()
        ]

    def activate(self, window_id):
        self.connection.roundtrip()
        for handle, window in self.windows.items():
            if window["id"] == window_id:
                self.connection.send(handle, 4, struct.pack("=I", self.seat))
                break
        else:
            raise ValueError(f"Unknown window: {window_id}")
        # A sync confirms request processing, not that activation was accepted.
        # Observe the compositor's state before allowing the caller to type.
        deadline = time.monotonic() + 2
        while True:
            target = next((w for w in self.current() if w["id"] == window_id), None)
            if target is None:
                raise WaylandError(f"Window closed during activation: {window_id}")
            if "activated" in target["states"]:
                return target
            if time.monotonic() >= deadline:
                raise WaylandError(f"Window activation timed out: {window_id}")
            time.sleep(0.01)

    def close_all(self, timeout):
        """Ask every window to close, as a person would; True if all closed."""
        self.connection.roundtrip()
        for handle in list(self.windows):
            self.connection.send(handle, 5)  # close
        deadline = time.monotonic() + timeout
        while self.current():
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)
        return True


def clear_selection(display_path):
    """Clear the session's clipboard and primary selection through data-control."""
    with Connection(display_path) as connection:
        for interface in (
            "ext_data_control_manager_v1",
            "zwlr_data_control_manager_v1",
        ):
            if interface in connection.globals:
                break
        else:
            raise WaylandError("Compositor provides no data-control protocol")
        version = connection.globals[interface][0][1]
        seat = connection.bind("wl_seat", 1)
        manager = connection.bind(interface, 2)
        device = connection.new_id()
        connection.send(manager, 1, struct.pack("=II", device, seat))
        connection.send(device, 0, struct.pack("=I", 0))  # set_selection(null)
        if version >= 2 or interface.startswith("ext_"):
            connection.send(device, 2, struct.pack("=I", 0))  # set_primary_selection
        connection.roundtrip()
