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
# Fixed modifier keys (evdev codes 1-5). Xwayland rejects a keymap without
# virtual-modifier mappings and silently falls back to its default layout.
MODIFIER_KEYS = (
    ("LFSH", "Shift_L", "Shift"),
    ("LCTL", "Control_L", "Control"),
    ("LALT", "Alt_L", "Mod1"),
    ("LWIN", "Super_L", "Mod4"),
    ("NMLK", "Num_Lock", "Mod2"),
)
FIRST_CHARACTER_CODE = len(MODIFIER_KEYS) + 1
# X11 clients cannot use keycodes above 255; xkb keycode = evdev code + 8.
MAX_KEYS = 255 - 8 - len(MODIFIER_KEYS)


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
    """A persistent virtual keyboard with a cumulative one-key-per-keysym keymap.

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
        self.keys = []
        self.uploaded = None
        self.upload()
        self.connection.roundtrip()

    def close(self):
        self.connection.close()

    def keymap(self):
        first = FIRST_CHARACTER_CODE + 8
        last = first + max(1, len(self.keys)) - 1
        lines = [
            "xkb_keymap {",
            'xkb_keycodes "(unnamed)" {',
            f"minimum = 8; maximum = {last};",
            *(f"<{name}> = {i + 9};" for i, (name, _, _) in enumerate(MODIFIER_KEYS)),
            *(f"<K{code}> = {code};" for code in range(first, last + 1)),
            "};",
            'xkb_types "(unnamed)" { include "complete" };',
            'xkb_compatibility "(unnamed)" { include "complete" };',
            'xkb_symbols "(unnamed)" {',
            *(f"key <{name}> {{[{sym}]}};" for name, sym, _ in MODIFIER_KEYS),
            *(f"modifier_map {mod} {{ <{name}> }};" for name, _, mod in MODIFIER_KEYS),
            *(f"key <K{first + i}> {{[0x{k:x}]}};" for i, k in enumerate(self.keys)),
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
        self.uploaded = list(self.keys)

    def codes(self, keysyms):
        """Evdev codes for keysyms, uploading a new keymap only when needed."""
        missing = [k for k in dict.fromkeys(keysyms) if k not in self.keys]
        if missing:
            if len(self.keys) + len(missing) > MAX_KEYS:
                self.keys = list(dict.fromkeys(keysyms))
                if len(self.keys) > MAX_KEYS:
                    raise ValueError("Too many distinct characters in one chunk")
            else:
                self.keys += missing
            self.upload()
        return [self.keys.index(k) + FIRST_CHARACTER_CODE for k in keysyms]

    def tap(self, code):
        self.connection.send(self.id, 1, struct.pack("=III", timestamp(), code, 1))
        self.connection.send(self.id, 1, struct.pack("=III", timestamp(), code, 0))

    def modifiers(self, mask):
        self.connection.send(self.id, 2, struct.pack("=IIII", mask, 0, 0, 0))

    def type(self, text):
        keysyms = [char_keysym(c) for c in text]
        for start in range(0, len(keysyms), MAX_KEYS):
            for code in self.codes(keysyms[start : start + MAX_KEYS]):
                self.tap(code)
        self.connection.roundtrip()

    def key(self, keysym, modifiers=()):
        (code,) = self.codes([keysym])
        mask = 0
        for name in modifiers:
            mask |= MODIFIERS[name]
        if mask:
            self.modifiers(mask)
        self.tap(code)
        if mask:
            self.modifiers(0)
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
                self.connection.roundtrip()
                return
        raise ValueError(f"Unknown window: {window_id}")
