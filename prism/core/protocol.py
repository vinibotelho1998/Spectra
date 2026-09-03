"""Cliente do protocolo de rede do OpenRGB, falado direto em binario.

O servidor SDK do OpenRGB escuta em TCP 6742 e troca pacotes com um
cabecalho de 16 bytes seguido do corpo: magic "ORGB", indice do
dispositivo, comando e tamanho, todos little endian.

O formato mudou entre versoes do protocolo e o servidor nao anuncia qual
layout usa para cada dispositivo. Por isso `OpenRGBClient.load_devices`
tenta decodificar na versao negociada e vai baixando ate encaixar, e
`_parse_device` exige que o blob termine exatamente no fim do payload
para que um desalinhamento vire erro em vez de dispositivo silenciosamente
torto.
"""

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
    """Cursor de leitura sobre um payload binario.

    Cada metodo consome os bytes que le e avanca `off`, entao a ordem das
    chamadas precisa espelhar o layout do pacote.
    """

    def __init__(self, buf: bytes, offset: int = 0):
        self.buf = buf
        self.off = offset

    def u8(self) -> int:
        """Le um byte sem sinal."""
        v = self.buf[self.off]
        self.off += 1
        return v

    def u16(self) -> int:
        """Le um inteiro de 16 bits sem sinal."""
        v = struct.unpack_from("<H", self.buf, self.off)[0]
        self.off += 2
        return v

    def u32(self) -> int:
        """Le um inteiro de 32 bits sem sinal."""
        v = struct.unpack_from("<I", self.buf, self.off)[0]
        self.off += 4
        return v

    def i32(self) -> int:
        """Le um inteiro de 32 bits com sinal."""
        v = struct.unpack_from("<i", self.buf, self.off)[0]
        self.off += 4
        return v

    def string(self) -> str:
        """Le uma string com prefixo de tamanho de 16 bits.

        Corta no primeiro byte nulo e troca sequencia invalida por marcador, para
        que nome de hardware estranho nao derrube a conexao.
        """
        n = self.u16()
        raw = self.buf[self.off:self.off + n]
        self.off += n
        return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")

    def color(self) -> tuple[int, int, int]:
        """Le uma cor RGBA de 4 bytes e devolve so o RGB."""
        r, g, b, _a = struct.unpack_from("<BBBB", self.buf, self.off)
        self.off += 4
        return (r, g, b)


def w_string(s: str) -> bytes:
    """Serializa uma string no formato do protocolo, com tamanho e terminador."""
    raw = s.encode("utf-8") + b"\x00"
    return struct.pack("<H", len(raw)) + raw


@dataclass
class Mode:
    """Um modo de operacao anunciado por um dispositivo.

    Interessa sobretudo `per_led`: sem ele o dispositivo nao aceita cor por
    LED e nenhum efeito do Prism tem como pintar nele.
    """

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
        """Diz se o modo aceita uma cor por LED."""
        return bool(self.flags & MODE_FLAG_HAS_PER_LED_COLOR)


@dataclass
class Segment:
    """Trecho nomeado dentro de uma zona, presente a partir da v4 do protocolo."""

    name: str
    type: int
    start_idx: int
    leds_count: int


@dataclass
class Zone:
    """Um agrupamento de LEDs dentro de um dispositivo.

    `leds_min` diferente de `leds_max` marca zona redimensionavel, que e o
    caso dos headers ARGB, onde a contagem real precisa ser informada por
    quem monta o gabinete.
    """

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
        """Nome legivel do tipo da zona."""
        return ZONE_TYPE_NAMES[self.type] if 0 <= self.type < 3 else "Unknown"


@dataclass
class Device:
    """Um controlador de RGB visto pelo servidor OpenRGB.

    Guarda o que veio do servidor sem interpretar: os modos anunciados, as
    zonas com suas contagens e a lista de LEDs.
    """

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
        """Nome legivel do tipo do dispositivo."""
        if 0 <= self.type < len(DEVICE_TYPE_NAMES):
            return DEVICE_TYPE_NAMES[self.type]
        return "Unknown"

    @property
    def led_count(self) -> int:
        """Quantidade de LEDs, contada pela lista que o servidor mandou."""
        return len(self.leds)

    def direct_mode(self):
        """Escolhe o modo que aceita pintura por LED sem gravar na flash.

        Prefere os nomes conhecidos, Direct, Custom e Static, nessa ordem. Se
        nenhum aparecer, aceita qualquer modo com cor por LED que nao tenha a
        flag de gravacao automatica, porque escrever a 60 fps num modo que
        persiste desgastaria a memoria do controlador.

        Devolve None quando o dispositivo nao serve para efeito nenhum.
        """
        for pref in ("direct", "custom", "static"):
            for m in self.modes:
                if m.name.strip().lower() == pref and m.per_led:
                    return m
        for m in self.modes:
            if m.per_led and not (m.flags & MODE_FLAG_AUTOMATIC_SAVE):
                return m
        return None

    def to_json(self) -> dict:
        """Descreve o dispositivo no formato que a interface consome."""
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
    """Falha ao falar com o servidor OpenRGB."""

    pass


class LayoutMismatch(OpenRGBError):
    """O blob do dispositivo nao encaixou na versao de protocolo tentada.

    Sinaliza para `OpenRGBClient.load_devices` que vale tentar uma versao
    mais baixa.
    """

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
    """Conexao com um servidor SDK do OpenRGB.

    Nao e thread-safe por acidente e sim por construcao: o envio e protegido
    por lock, porque a thread de render escreve cores a 60 fps enquanto a
    thread da interface pode pedir troca de modo ou redimensionar zona.

    Qualquer queda de conexao vira `OpenRGBError` e zera o socket, para que
    a thread de render descubra a perda em vez de morrer calada com um
    `OSError` cru.
    """

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
        """Abre a conexao, se apresenta e negocia a versao do protocolo."""
        s = socket.create_connection((self.host, self.port), timeout=timeout)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.settimeout(timeout)
        self.sock = s
        self._send(0, SET_CLIENT_NAME, self.client_name.encode() + b"\x00")
        self._negotiate()

    def close(self) -> None:
        """Fecha a conexao, se houver alguma aberta."""
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None

    @property
    def connected(self) -> bool:
        """Diz se existe socket aberto."""
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
        """Pergunta quantos dispositivos o servidor conhece."""
        resp = self._request(0, REQUEST_CONTROLLER_COUNT)
        return struct.unpack("<I", resp[:4])[0]

    def load_devices(self) -> list:
        """Carrega todos os dispositivos, baixando a versao ate decodificar.

        O servidor aceita a versao que o cliente pedir, mas o layout do blob de
        cada dispositivo varia entre versoes e nem toda combinacao de servidor e
        plugin respeita isso. Entao, a cada falha de decodificacao, desce um
        degrau e tenta de novo, ate a v1.

        Levanta `OpenRGBError` se nem a v1 servir.
        """
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
        """Coloca o dispositivo no modo de pintura por LED.

        Devolve False quando o dispositivo nao tem modo utilizavel, o que e o
        caso de teclado e mouse com firmware fechado.
        """
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
        """Manda o quadro inteiro de cores para um dispositivo."""
        body = struct.pack("<H", count) + colors
        data = struct.pack("<I", len(body) + 4) + body
        self._send(dev_index, UPDATE_LEDS, data)

    def update_zone_leds(self, dev_index: int, zone: int, colors: bytes,
                         count: int) -> None:
        """Manda as cores de uma zona so."""
        body = struct.pack("<IH", zone, count) + colors
        data = struct.pack("<I", len(body) + 4) + body
        self._send(dev_index, UPDATE_ZONE_LEDS, data)

    def resize_zone(self, dev_index: int, zone: int, size: int) -> None:
        """Informa quantos LEDs existem numa zona redimensionavel.

        Header ARGB de 3 pinos e via unica: o controlador nao tem como contar o
        que foi plugado nele, entao a contagem vem do assistente de descoberta.
        """
        self._send(dev_index, RESIZEZONE, struct.pack("<ii", zone, size))
