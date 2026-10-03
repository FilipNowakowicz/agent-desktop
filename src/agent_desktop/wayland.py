"""Minimal Wayland client for session-local pointer input (no Python dependencies).

Speaks just enough of the wire protocol to bind wl_output and
zwlr_virtual_pointer_manager_v1 on one private compositor socket.
"""

import socket
import struct
import time

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

    def send(self, obj, opcode, payload=b""):
        size = 8 + len(payload)
        self.socket.sendall(struct.pack("=II", obj, size << 16 | opcode) + payload)

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
