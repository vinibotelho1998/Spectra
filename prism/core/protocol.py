from __future__ import annotations

import socket
import struct
import threading
from dataclasses import dataclass, field
from typing import Any

MAGIC = b"ORGB"
HEADER = struct.Struct("<4sIII")

REQUEST_CONTROLLER_COUNT = 0
REQUEST_CONTROLLER_DATA = 1
REQUEST_PROTOCOL_VERSION = 40
SET_CLIENT_NAME = 50
DEVICE_LIST_UPDATED = 100
RESIZEZONE = 1000
UPDATE_LEDS = 1050
UPDATE_ZONE_LEDS = 1051
UPDATE_SINGLE_LED = 1052
SET_CUSTOM_MODE = 1100
UPDATE_MODE = 1101

CLIENT_PROTOCOL_VERSION = 5

MODE_FLAG_HAS_SPEED = 1 << 0
MODE_FLAG_HAS_DIRECTION_LR = 1 << 1
MODE_FLAG_HAS_DIRECTION_UD = 1 << 2
MODE_FLAG_HAS_DIRECTION_HV = 1 << 3
MODE_FLAG_HAS_BRIGHTNESS = 1 << 4
MODE_FLAG_HAS_PER_LED_COLOR = 1 << 5
MODE_FLAG_HAS_MODE_SPECIFIC_COLOR = 1 << 6
MODE_FLAG_HAS_RANDOM_COLOR = 1 << 7
MODE_FLAG_MANUAL_SAVE = 1 << 8
MODE_FLAG_AUTOMATIC_SAVE = 1 << 9

DEVICE_TYPE_NAMES = [
    "Motherboard", "DRAM", "GPU", "Cooler", "LED Strip", "Keyboard", "Mouse",
    "Mousemat", "Headset", "Headset Stand", "Gamepad", "Light", "Speaker",
    "Virtual", "Storage", "Case", "Microphone", "Accessory", "Keypad",
    "Laptop", "Monitor", "Unknown",
]

ZONE_TYPE_NAMES = ["Single", "Linear", "Matrix"]


class Reader:

    def __init__(self, buf: bytes, offset: int = 0):
        self.buf = buf
        self.off = offset

    def u8(self) -> int:
        v = self.buf[self.off]
        self.off += 1
        return v

    def u16(self) -> int:
        v = struct.unpack_from("<H", self.buf, self.off)[0]
        self.off += 2
        return v

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.buf, self.off)[0]
        self.off += 4
        return v

    def i32(self) -> int:
        v = struct.unpack_from("<i", self.buf, self.off)[0]
        self.off += 4
        return v

    def string(self) -> str:
        n = self.u16()
        raw = self.buf[self.off:self.off + n]
        self.off += n
        return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")

    def color(self) -> tuple[int, int, int]:
        r, g, b, _a = struct.unpack_from("<BBBB", self.buf, self.off)
        self.off += 4
        return (r, g, b)


def w_string(s: str) -> bytes:
    raw = s.encode("utf-8") + b"\x00"
    return struct.pack("<H", len(raw)) + raw


@dataclass
class Mode:
    index: int
    name: str
    value: int
    flags: int
    speed_min: int
    speed_max: int
    brightness_min: int
    brightness_max: int
    colors_min: int
    colors_max: int
    speed: int
    brightness: int
    direction: int
    color_mode: int
    colors: list = field(default_factory=list)

    @property
    def per_led(self) -> bool:
        return bool(self.flags & MODE_FLAG_HAS_PER_LED_COLOR)


@dataclass
class Segment:
    name: str
    type: int
    start_idx: int
    leds_count: int


@dataclass
class Zone:
    index: int
    name: str
    type: int
    leds_min: int
    leds_max: int
    leds_count: int
    matrix_width: int = 0
    matrix_height: int = 0
    matrix: list = field(default_factory=list)
    segments: list = field(default_factory=list)
    flags: int = 0
    start_idx: int = 0

    @property
    def type_name(self) -> str:
        return ZONE_TYPE_NAMES[self.type] if 0 <= self.type < 3 else "Unknown"


@dataclass
class Device:
    index: int
    type: int
    name: str
    vendor: str
    description: str
    version: str
    serial: str
    location: str
    modes: list
    active_mode: int
    zones: list
    leds: list
    colors: list

    @property
    def type_name(self) -> str:
        if 0 <= self.type < len(DEVICE_TYPE_NAMES):
            return DEVICE_TYPE_NAMES[self.type]
        return "Unknown"

    @property
    def led_count(self) -> int:
        return len(self.leds)

    def direct_mode(self):
        for pref in ("direct", "custom", "static"):
            for m in self.modes:
                if m.name.strip().lower() == pref and m.per_led:
                    return m
        for m in self.modes:
            if m.per_led and not (m.flags & MODE_FLAG_AUTOMATIC_SAVE):
                return m
        return None

    def to_json(self) -> dict:
        return {
            "index": self.index,
            "name": self.name,
            "vendor": self.vendor,
            "type": self.type,
            "type_name": self.type_name,
            "description": self.description,
            "location": self.location,
            "serial": self.serial,
            "led_count": self.led_count,
            "active_mode": self.active_mode,
            "modes": [m.name for m in self.modes],
            "has_direct": self.direct_mode() is not None,
            "zones": [
                {
                    "index": z.index,
                    "name": z.name,
                    "type": z.type,
                    "type_name": z.type_name,
                    "leds_count": z.leds_count,
                    "start_idx": z.start_idx,
                    "matrix_width": z.matrix_width,
                    "matrix_height": z.matrix_height,
                    "resizable": z.leds_min != z.leds_max,
                    "leds_min": z.leds_min,
                    "leds_max": z.leds_max,
                }
                for z in self.zones
            ],
            "leds": self.leds,
        }


class OpenRGBError(RuntimeError):
    pass


class LayoutMismatch(OpenRGBError):
    pass


def _parse_mode(r: Reader, index: int, proto: int) -> Mode:
    name = r.string()
    value = r.i32()
    flags = r.u32()
    speed_min = r.u32()
    speed_max = r.u32()
    if proto >= 3:
        brightness_min = r.u32()
        brightness_max = r.u32()
    else:
        brightness_min = brightness_max = 0
    colors_min = r.u32()
    colors_max = r.u32()
    speed = r.u32()
    brightness = r.u32() if proto >= 3 else 0
    direction = r.u32()
    color_mode = r.u32()
    ncolors = r.u16()
    colors = [r.color() for _ in range(ncolors)]
    return Mode(index, name, value, flags, speed_min, speed_max, brightness_min,
                brightness_max, colors_min, colors_max, speed, brightness,
                direction, color_mode, colors)


def _serialize_mode(m: Mode, proto: int) -> bytes:
    out = bytearray()
    out += w_string(m.name)
    out += struct.pack("<iIII", m.value, m.flags, m.speed_min, m.speed_max)
    if proto >= 3:
        out += struct.pack("<II", m.brightness_min, m.brightness_max)
    out += struct.pack("<III", m.colors_min, m.colors_max, m.speed)
    if proto >= 3:
        out += struct.pack("<I", m.brightness)
    out += struct.pack("<II", m.direction, m.color_mode)
    out += struct.pack("<H", len(m.colors))
    for (cr, cg, cb) in m.colors:
        out += struct.pack("<BBBB", cr, cg, cb, 0)
    return bytes(out)


def _parse_device(payload: bytes, index: int, proto: int) -> Device:
    r = Reader(payload)
    r.u32()
    dtype = r.u32()
    name = r.string()
    vendor = r.string() if proto >= 1 else ""
    description = r.string() if proto >= 1 else ""
    version = r.string() if proto >= 1 else ""
    serial = r.string() if proto >= 1 else ""
    location = r.string() if proto >= 1 else ""

    nmodes = r.u16()
    active_mode = r.i32()
    modes = [_parse_mode(r, i, proto) for i in range(nmodes)]

    nzones = r.u16()
    zones = []
    for zi in range(nzones):
        zname = r.string()
        ztype = r.i32()
        lmin, lmax, lcount = r.u32(), r.u32(), r.u32()
        z = Zone(zi, zname, ztype, lmin, lmax, lcount)
        matrix_len = r.u16()
        if matrix_len:
            z.matrix_height = r.u32()
            z.matrix_width = r.u32()
            z.matrix = [r.u32() for _ in range(z.matrix_height * z.matrix_width)]
        if proto >= 4:
            nseg = r.u16()
            for _ in range(nseg):
                sname = r.string()
                stype = r.i32()
                sstart = r.u32()
                scount = r.u32()
                z.segments.append(Segment(sname, stype, sstart, scount))
        if proto >= 5:
            z.flags = r.u32()
        zones.append(z)

    acc = 0
    for z in zones:
        z.start_idx = acc
        acc += z.leds_count

    nleds = r.u16()
    leds = []
    for _ in range(nleds):
        leds.append(r.string())
        r.u32()

    ncolors = r.u16()
    colors = [r.color() for _ in range(ncolors)]

    dev = Device(index, dtype, name, vendor, description, version, serial,
                 location, modes, active_mode, zones, leds, colors)
    if r.off != len(payload):
        raise LayoutMismatch(
            "blob do device %d nao alinhou na v%d: consumi %d de %d bytes"
            % (index, proto, r.off, len(payload)))
    return dev


class OpenRGBClient:

    def __init__(self, host: str = "127.0.0.1", port: int = 6742,
                 name: str = "Prism"):
        self.host = host
        self.port = port
        self.client_name = name
        self.sock = None
        self.protocol = CLIENT_PROTOCOL_VERSION
        self.devices = []
        self._lock = threading.Lock()

    def connect(self, timeout: float = 4.0) -> None:
        s = socket.create_connection((self.host, self.port), timeout=timeout)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.settimeout(timeout)
        self.sock = s
        self._send(0, SET_CLIENT_NAME, self.client_name.encode() + b"\x00")
        self._negotiate()

    def close(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None

    @property
    def connected(self) -> bool:
        return self.sock is not None

    def _send(self, dev: int, cmd: int, data: bytes = b"") -> None:
        if not self.sock:
            raise OpenRGBError("nao conectado ao servidor OpenRGB")
        pkt = HEADER.pack(MAGIC, dev, cmd, len(data)) + data
        with self._lock:
            try:
                self.sock.sendall(pkt)
            except OSError as exc:
                self.sock = None
                raise OpenRGBError(f"conexao perdida ao enviar: {exc}") from exc

    def _recv_exact(self, n: int) -> bytes:
        chunks = []
        got = 0
        while got < n:
            try:
                c = self.sock.recv(n - got)
            except OSError as exc:
                self.sock = None
                raise OpenRGBError(f"conexao perdida ao ler: {exc}") from exc
            if not c:
                self.sock = None
                raise OpenRGBError("conexao fechada pelo servidor OpenRGB")
            chunks.append(c)
            got += len(c)
        return b"".join(chunks)

    def _recv_packet(self):
        head = self._recv_exact(HEADER.size)
        magic, dev, cmd, size = HEADER.unpack(head)
        if magic != MAGIC:
            raise OpenRGBError("magic invalido: %r" % (magic,))
        data = self._recv_exact(size) if size else b""
        return dev, cmd, data

    def _request(self, dev: int, cmd: int, data: bytes = b"") -> bytes:
        self._send(dev, cmd, data)
        while True:
            rdev, rcmd, rdata = self._recv_packet()
            if rcmd == DEVICE_LIST_UPDATED:
                continue
            if rcmd == cmd:
                return rdata

    def _negotiate(self) -> None:
        try:
            resp = self._request(0, REQUEST_PROTOCOL_VERSION,
                                 struct.pack("<I", CLIENT_PROTOCOL_VERSION))
            server = struct.unpack("<I", resp[:4])[0]
            self.protocol = min(server, CLIENT_PROTOCOL_VERSION)
        except Exception:
            self.protocol = 0

    def controller_count(self) -> int:
        resp = self._request(0, REQUEST_CONTROLLER_COUNT)
        return struct.unpack("<I", resp[:4])[0]

    def load_devices(self) -> list:
        n = self.controller_count()
        while True:
            try:
                out = []
                for i in range(n):
                    payload = self._request(i, REQUEST_CONTROLLER_DATA,
                                            struct.pack("<I", self.protocol))
                    out.append(_parse_device(payload, i, self.protocol))
                break
            except (LayoutMismatch, struct.error, IndexError) as exc:
                if self.protocol <= 1:
                    raise OpenRGBError(
                        "nenhuma versao de protocolo decodificou o device") from exc
                self.protocol -= 1
        self.devices = out
        return out

    def set_direct_mode(self, dev_index: int) -> bool:
        d = self.devices[dev_index]
        m = d.direct_mode()
        if m is None:
            try:
                self._send(dev_index, SET_CUSTOM_MODE)
            except OpenRGBError:
                return False
            return False
        body = struct.pack("<I", m.index) + _serialize_mode(m, self.protocol)
        data = struct.pack("<I", len(body) + 4) + body
        self._send(dev_index, UPDATE_MODE, data)
        d.active_mode = m.index
        return True

    def update_leds(self, dev_index: int, colors: bytes, count: int) -> None:
        body = struct.pack("<H", count) + colors
        data = struct.pack("<I", len(body) + 4) + body
        self._send(dev_index, UPDATE_LEDS, data)

    def update_zone_leds(self, dev_index: int, zone: int, colors: bytes,
                         count: int) -> None:
        body = struct.pack("<IH", zone, count) + colors
        data = struct.pack("<I", len(body) + 4) + body
        self._send(dev_index, UPDATE_ZONE_LEDS, data)

    def resize_zone(self, dev_index: int, zone: int, size: int) -> None:
        self._send(dev_index, RESIZEZONE, struct.pack("<ii", zone, size))
