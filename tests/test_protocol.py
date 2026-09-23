from __future__ import annotations

import struct

import pytest

from spectra.core.protocol import (
    CLIENT_PROTOCOL_VERSION,
    DEVICE_LIST_UPDATED,
    HEADER,
    MAGIC,
    MODE_FLAG_AUTOMATIC_SAVE,
    MODE_FLAG_HAS_PER_LED_COLOR,
    MODE_FLAG_HAS_SPEED,
    REQUEST_CONTROLLER_COUNT,
    REQUEST_PROTOCOL_VERSION,
    RESIZEZONE,
    SET_CLIENT_NAME,
    SET_CUSTOM_MODE,
    UPDATE_LEDS,
    UPDATE_MODE,
    UPDATE_ZONE_LEDS,
    Device,
    LayoutMismatch,
    Mode,
    OpenRGBClient,
    OpenRGBError,
    Reader,
    _parse_device,
    _parse_mode,
    _serialize_mode,
    w_string,
)


def make_mode(index=0, name="Direct", flags=MODE_FLAG_HAS_PER_LED_COLOR,
              colors=None):
    return Mode(index=index, name=name, value=index, flags=flags,
                speed_min=0, speed_max=100, brightness_min=0,
                brightness_max=255, colors_min=0, colors_max=2, speed=50,
                brightness=200, direction=1, color_mode=2,
                colors=list(colors or []))


def build_device_payload(proto, name="Mobo", vendor="Gigabyte", dtype=1,
                         modes=None, zones=None, leds=None, colors=None):
    modes = modes if modes is not None else [make_mode()]
    zones = zones if zones is not None else [("ARGB 1", 1, 0, 128, 24, 0, 0)]
    total = sum(z[4] for z in zones)
    leds = leds if leds is not None else ["LED %d" % i for i in range(total)]
    colors = colors if colors is not None else [(0, 0, 0)] * total

    body = bytearray()
    body += struct.pack("<I", dtype)
    body += w_string(name)
    if proto >= 1:
        body += w_string(vendor)
        body += w_string("descricao")
        body += w_string("1.0")
        body += w_string("SN123")
        body += w_string("USB:1")

    body += struct.pack("<H", len(modes))
    body += struct.pack("<i", 0)
    for m in modes:
        body += _serialize_mode(m, proto)

    body += struct.pack("<H", len(zones))
    for zname, ztype, lmin, lmax, lcount, mw, mh in zones:
        body += w_string(zname)
        body += struct.pack("<iIII", ztype, lmin, lmax, lcount)
        if mw and mh:
            body += struct.pack("<H", 8 + 4 * mw * mh)
            body += struct.pack("<II", mh, mw)
            for i in range(mw * mh):
                body += struct.pack("<I", i)
        else:
            body += struct.pack("<H", 0)
        if proto >= 4:
            body += struct.pack("<H", 0)
        if proto >= 5:
            body += struct.pack("<I", 0)

    body += struct.pack("<H", len(leds))
    for ln in leds:
        body += w_string(ln)
        body += struct.pack("<I", 0)

    body += struct.pack("<H", len(colors))
    for r, g, b in colors:
        body += struct.pack("<BBBB", r, g, b, 255)

    return struct.pack("<I", len(body) + 4) + bytes(body)


class TestReader:

    def test_le_inteiros_em_little_endian(self):
        r = Reader(struct.pack("<BHIi", 200, 4000, 3000000000, -7))
        assert r.u8() == 200
        assert r.u16() == 4000
        assert r.u32() == 3000000000
        assert r.i32() == -7
        assert r.off == 11

    def test_string_para_no_terminador(self):
        bruto = w_string("Direct")
        r = Reader(bruto)
        assert r.string() == "Direct"
        assert r.off == len(bruto)

    def test_string_vazia(self):
        assert Reader(w_string("")).string() == ""

    def test_string_longa_preserva_o_conteudo(self):
        nome = "Ventoinha traseira do gabinete"
        assert Reader(w_string(nome)).string() == nome

    def test_byte_invalido_nao_estoura(self):
        raw = b"\xff\xfe"
        r = Reader(struct.pack("<H", len(raw)) + raw)
        assert isinstance(r.string(), str)

    def test_color_descarta_o_alfa(self):
        r = Reader(struct.pack("<BBBB", 10, 20, 30, 255))
        assert r.color() == (10, 20, 30)
        assert r.off == 4

    def test_leitura_sequencial_mantem_o_offset(self):
        buf = w_string("a") + w_string("b")
        r = Reader(buf)
        assert r.string() == "a"
        assert r.string() == "b"
        assert r.off == len(buf)

    def test_offset_inicial_e_respeitado(self):
        r = Reader(b"\xaa\xbb" + struct.pack("<I", 77), offset=2)
        assert r.u32() == 77


class TestModo:

    @pytest.mark.parametrize("proto", [0, 1, 2, 3, 4, 5])
    def test_serializa_e_volta_igual(self, proto):
        original = make_mode(
            name="Rainbow Wave",
            flags=MODE_FLAG_HAS_SPEED | MODE_FLAG_HAS_PER_LED_COLOR,
            colors=[(255, 0, 0), (0, 255, 0)])
        bruto = _serialize_mode(original, proto)
        r = Reader(bruto)
        volta = _parse_mode(r, original.index, proto)

        assert volta.name == original.name
        assert volta.value == original.value
        assert volta.flags == original.flags
        assert volta.speed == original.speed
        assert volta.direction == original.direction
        assert volta.color_mode == original.color_mode
        assert volta.colors == original.colors
        assert r.off == len(bruto)

    def test_brilho_so_existe_a_partir_da_v3(self):
        original = make_mode()
        antigo = _parse_mode(Reader(_serialize_mode(original, 2)), 0, 2)
        novo = _parse_mode(Reader(_serialize_mode(original, 3)), 0, 3)
        assert antigo.brightness == 0
        assert novo.brightness == original.brightness

    def test_modo_sem_cor_serializa_vazio(self):
        m = make_mode(colors=[])
        volta = _parse_mode(Reader(_serialize_mode(m, 5)), 0, 5)
        assert volta.colors == []

    def test_per_led_le_a_flag(self):
        assert make_mode(flags=MODE_FLAG_HAS_PER_LED_COLOR).per_led is True
        assert make_mode(flags=MODE_FLAG_HAS_SPEED).per_led is False


class TestParseDevice:

    @pytest.mark.parametrize("proto", [0, 1, 2, 3, 4, 5])
    def test_alinha_o_blob_inteiro(self, proto):
        dev = _parse_device(build_device_payload(proto), 0, proto)
        assert dev.name == "Mobo"
        assert dev.led_count == 24
        assert len(dev.zones) == 1

    def test_vendor_lido_a_partir_da_v1(self):
        dev = _parse_device(build_device_payload(1), 0, 1)
        assert dev.vendor == "Gigabyte"
        assert dev.serial == "SN123"
        assert dev.location == "USB:1"

    def test_v0_nao_tem_vendor_nem_serial(self):
        dev = _parse_device(build_device_payload(0), 0, 0)
        assert dev.vendor == ""
        assert dev.serial == ""
        assert dev.name == "Mobo"

    def test_blob_de_outra_versao_nao_vira_device_torto(self):
        with pytest.raises((LayoutMismatch, struct.error, IndexError)):
            _parse_device(build_device_payload(1), 0, 0)

    def test_sobra_de_bytes_vira_layout_mismatch(self):
        payload = build_device_payload(5) + b"\x00\x00"
        with pytest.raises(LayoutMismatch) as e:
            _parse_device(payload, 3, 5)
        assert "device 3" in str(e.value)

    def test_matriz_le_largura_e_altura(self):
        zones = [("Matrix", 2, 0, 64, 12, 4, 3)]
        dev = _parse_device(build_device_payload(5, zones=zones), 0, 5)
        z = dev.zones[0]
        assert (z.matrix_width, z.matrix_height) == (4, 3)
        assert len(z.matrix) == 12

    def test_start_idx_acumula_entre_zonas(self):
        zones = [("A", 1, 0, 128, 24, 0, 0),
                 ("B", 1, 0, 128, 18, 0, 0),
                 ("C", 0, 0, 1, 1, 0, 0)]
        dev = _parse_device(build_device_payload(5, zones=zones), 0, 5)
        assert [z.start_idx for z in dev.zones] == [0, 24, 42]
        assert dev.led_count == 43

    def test_varios_modos_recebem_indice_proprio(self):
        modes = [make_mode(0, "Direct"), make_mode(1, "Static"),
                 make_mode(2, "Breathing", MODE_FLAG_HAS_SPEED)]
        dev = _parse_device(build_device_payload(5, modes=modes), 0, 5)
        assert [m.index for m in dev.modes] == [0, 1, 2]
        assert [m.name for m in dev.modes] == ["Direct", "Static", "Breathing"]

    def test_type_name_conhecido_e_desconhecido(self):
        dev = _parse_device(build_device_payload(5, dtype=1), 0, 5)
        assert dev.type_name != "Unknown"
        fora = Device(0, 999, "X", "", "", "", "", "", [], 0, [], [], [])
        assert fora.type_name == "Unknown"

    def test_to_json_expoe_o_essencial(self):
        d = _parse_device(build_device_payload(5), 0, 5).to_json()
        assert d["name"] == "Mobo"
        assert d["led_count"] == 24
        assert d["has_direct"] is True
        assert d["zones"][0]["resizable"] is True


class ClienteFalso(OpenRGBClient):

    def __init__(self, payload, quantos=1):
        super().__init__()
        self.payload = payload
        self.quantos = quantos
        self.pedidos = []

    def _request(self, dev, cmd, data=b""):
        self.pedidos.append((dev, cmd))
        if cmd == REQUEST_CONTROLLER_COUNT:
            return struct.pack("<I", self.quantos)
        return self.payload


class TestDowngrade:

    @pytest.mark.parametrize("real", [2, 3, 4, 5])
    def test_cai_de_versao_ate_decodificar(self, real):
        c = ClienteFalso(build_device_payload(real))
        c.protocol = CLIENT_PROTOCOL_VERSION
        devs = c.load_devices()
        assert c.protocol == real
        assert len(devs) == 1
        assert devs[0].name == "Mobo"
        assert devs[0].led_count == 24

    def test_v1_e_v2_compartilham_o_mesmo_layout(self):
        assert build_device_payload(1) == build_device_payload(2)

    def test_blob_v1_para_na_v2_e_ainda_decodifica(self):
        c = ClienteFalso(build_device_payload(1))
        c.protocol = CLIENT_PROTOCOL_VERSION
        devs = c.load_devices()
        assert c.protocol == 2
        assert devs[0].vendor == "Gigabyte"

    def test_nao_desce_quando_a_versao_ja_esta_certa(self):
        c = ClienteFalso(build_device_payload(5))
        c.protocol = 5
        c.load_devices()
        assert c.protocol == 5

    def test_desiste_quando_nenhuma_versao_serve(self):
        c = ClienteFalso(struct.pack("<I", 64) + b"\xff" * 8)
        c.protocol = CLIENT_PROTOCOL_VERSION
        with pytest.raises(OpenRGBError, match="nenhuma versao"):
            c.load_devices()

    def test_guarda_os_devices_carregados(self):
        c = ClienteFalso(build_device_payload(5), quantos=3)
        c.protocol = 5
        devs = c.load_devices()
        assert len(devs) == 3
        assert c.devices is devs


class TestDirectMode:

    def build(self, modes):
        return Device(0, 1, "X", "", "", "", "", "", modes, 0, [], [], [])

    def test_prefere_direct_pelo_nome(self):
        dev = self.build([make_mode(0, "Static"), make_mode(1, "Direct")])
        assert dev.direct_mode().name == "Direct"

    def test_cai_para_custom_quando_nao_ha_direct(self):
        dev = self.build([make_mode(0, "Breathing", MODE_FLAG_HAS_SPEED),
                          make_mode(1, "Custom")])
        assert dev.direct_mode().name == "Custom"

    def test_ignora_modo_sem_per_led_mesmo_chamado_direct(self):
        dev = self.build([make_mode(0, "Direct", MODE_FLAG_HAS_SPEED)])
        assert dev.direct_mode() is None

    def test_evita_modo_que_grava_na_flash(self):
        dev = self.build([
            make_mode(0, "Salvavel",
                      MODE_FLAG_HAS_PER_LED_COLOR | MODE_FLAG_AUTOMATIC_SAVE),
            make_mode(1, "Volatil", MODE_FLAG_HAS_PER_LED_COLOR),
        ])
        assert dev.direct_mode().name == "Volatil"

    def test_sem_modo_utilizavel_devolve_none(self):
        assert self.build([]).direct_mode() is None


class SocketQuebrado:

    def __init__(self, erro=None):
        self.erro = erro or OSError(10054, "conexao abortada pelo host")

    def sendall(self, data):
        raise self.erro

    def recv(self, n):
        raise self.erro


class SocketFechado:

    def recv(self, n):
        return b""


class SocketOk:

    def __init__(self):
        self.enviados = []

    def sendall(self, data):
        self.enviados.append(data)


class SocketQueTroca:
    """Falha no envio enquanto outra thread ja reconectou o cliente."""

    def __init__(self, cliente, novo):
        self.cliente = cliente
        self.novo = novo

    def sendall(self, data):
        self.cliente.sock = self.novo
        raise OSError(10038, "operacao em algo que nao e socket")


class SocketQueSome:
    """Entrega um byte por vez enquanto outra thread fecha o cliente."""

    def __init__(self, cliente):
        self.cliente = cliente

    def recv(self, n):
        self.cliente.sock = None
        return b"\x00"


class TestCliente:

    def test_envio_monta_o_header_com_magic(self):
        c = OpenRGBClient()
        c.sock = SocketOk()
        c._send(2, 1050, b"\x01\x02")
        pkt = c.sock.enviados[0]
        magic, dev, cmd, size = HEADER.unpack(pkt[:HEADER.size])
        assert magic == MAGIC
        assert (dev, cmd, size) == (2, 1050, 2)
        assert pkt[HEADER.size:] == b"\x01\x02"

    def test_sem_socket_avisa_que_nao_esta_conectado(self):
        c = OpenRGBClient()
        with pytest.raises(OpenRGBError, match="nao conectado"):
            c._send(0, 1050, b"")

    def test_queda_no_envio_vira_openrgberror(self):
        c = OpenRGBClient()
        c.sock = SocketQuebrado()
        with pytest.raises(OpenRGBError, match="conexao perdida ao enviar"):
            c._send(0, 1050, b"\x00")

    def test_queda_no_envio_limpa_o_socket(self):
        c = OpenRGBClient()
        c.sock = SocketQuebrado()
        with pytest.raises(OpenRGBError):
            c._send(0, 1050, b"\x00")
        assert c.sock is None
        assert c.connected is False

    def test_connection_reset_nao_escapa_como_oserror(self):
        c = OpenRGBClient()
        c.sock = SocketQuebrado(ConnectionResetError(10054, "reset"))
        with pytest.raises(OpenRGBError):
            c._send(0, 1050, b"\x00")

    def test_queda_na_leitura_vira_openrgberror(self):
        c = OpenRGBClient()
        c.sock = SocketQuebrado()
        with pytest.raises(OpenRGBError, match="conexao perdida ao ler"):
            c._recv_exact(4)
        assert c.sock is None

    def test_servidor_fechando_vira_openrgberror(self):
        c = OpenRGBClient()
        c.sock = SocketFechado()
        with pytest.raises(OpenRGBError, match="fechada pelo servidor"):
            c._recv_exact(4)
        assert c.sock is None

    def test_close_zera_o_socket(self):
        c = OpenRGBClient()
        c.sock = SocketOk()
        c.sock.close = lambda: None
        c.close()
        assert c.connected is False

    def test_versao_do_cliente_declarada(self):
        assert OpenRGBClient().protocol == CLIENT_PROTOCOL_VERSION

    def test_queda_no_envio_nao_derruba_a_conexao_nova(self):
        c = OpenRGBClient()
        novo = SocketOk()
        c.sock = SocketQueTroca(c, novo)
        with pytest.raises(OpenRGBError):
            c._send(0, 1050, b"\x00")
        assert c.sock is novo

    def test_leitura_sem_socket_vira_openrgberror(self):
        with pytest.raises(OpenRGBError, match="nao conectado"):
            OpenRGBClient()._recv_exact(4)

    def test_fechar_no_meio_da_leitura_nao_vira_attributeerror(self):
        c = OpenRGBClient()
        c.sock = SocketQueSome(c)
        assert c._recv_exact(4) == b"\x00" * 4

    def test_fechar_duas_vezes_nao_quebra(self):
        c = OpenRGBClient()
        c.sock = SocketOk()
        c.sock.close = lambda: None
        c.close()
        c.close()
        assert c.sock is None


def pacote(dev, cmd, data=b""):
    return HEADER.pack(MAGIC, dev, cmd, len(data)) + data


def abre(pkt):
    magic, dev, cmd, size = HEADER.unpack(pkt[:HEADER.size])
    assert magic == MAGIC
    data = pkt[HEADER.size:]
    assert len(data) == size
    return dev, cmd, data


class SocketRoteiro:
    """Servidor de mentira: responde o que o teste escreveu, byte a byte."""

    def __init__(self, respostas=b""):
        self.enviados = []
        self.buf = bytearray(respostas)
        self.opcoes = []

    def sendall(self, data):
        self.enviados.append(bytes(data))

    def recv(self, n):
        n = min(n, len(self.buf), 5)
        out, self.buf = bytes(self.buf[:n]), self.buf[n:]
        return out

    def setsockopt(self, *a):
        self.opcoes.append(a)

    def settimeout(self, t):
        self.timeout = t

    def close(self):
        pass


def _cliente(respostas=b""):
    c = OpenRGBClient()
    c.sock = SocketRoteiro(respostas)
    return c


class TestPacotesDeCor:
    """O formato que o servidor espera, campo a campo."""

    def test_quadro_inteiro(self):
        c = _cliente()
        cores = b"\x01\x02\x03\x00\x04\x05\x06\x00"
        c.update_leds(3, cores, 2)
        dev, cmd, data = abre(c.sock.enviados[0])
        assert (dev, cmd) == (3, UPDATE_LEDS)
        assert struct.unpack_from("<IH", data) == (len(data), 2)
        assert data[6:] == cores

    def test_uma_zona(self):
        c = _cliente()
        cores = b"\xff\x00\x00\x00" * 3
        c.update_zone_leds(1, 2, cores, 3)
        dev, cmd, data = abre(c.sock.enviados[0])
        assert (dev, cmd) == (1, UPDATE_ZONE_LEDS)
        assert struct.unpack_from("<IIH", data) == (len(data), 2, 3)
        assert data[10:] == cores

    def test_contagem_da_zona(self):
        c = _cliente()
        c.resize_zone(0, 1, 40)
        dev, cmd, data = abre(c.sock.enviados[0])
        assert (dev, cmd) == (0, RESIZEZONE)
        assert struct.unpack("<ii", data) == (1, 40)


class TestTrocaDeModo:

    def _com(self, modos, proto=5):
        c = _cliente()
        c.protocol = proto
        c.devices = [Device(0, 1, "X", "", "", "", "", "", modos, 9, [], [], [])]
        return c

    def test_manda_o_modo_direto_com_o_indice_e_o_tamanho(self):
        direto = make_mode(2, "Direct")
        c = self._com([make_mode(0, "Static", MODE_FLAG_HAS_SPEED), direto])
        assert c.set_direct_mode(0) is True
        dev, cmd, data = abre(c.sock.enviados[0])
        assert cmd == UPDATE_MODE
        tam, indice = struct.unpack_from("<Ii", data)
        assert (tam, indice) == (len(data), 2)
        assert data[8:] == _serialize_mode(direto, 5)
        assert c.devices[0].active_mode == 2

    def test_modo_segue_a_versao_negociada(self):
        direto = make_mode(0, "Direct")
        c = self._com([direto], proto=2)
        c.set_direct_mode(0)
        assert abre(c.sock.enviados[0])[2][8:] == _serialize_mode(direto, 2)

    def test_sem_modo_direto_pede_o_personalizado_e_diz_que_nao(self):
        c = self._com([make_mode(0, "Rainbow", MODE_FLAG_HAS_SPEED)])
        assert c.set_direct_mode(0) is False
        assert abre(c.sock.enviados[0])[:2] == (0, SET_CUSTOM_MODE)
        assert c.devices[0].active_mode == 9

    def test_sem_modo_direto_e_sem_conexao_nao_levanta(self):
        c = self._com([make_mode(0, "Rainbow", MODE_FLAG_HAS_SPEED)])
        c.sock = None
        assert c.set_direct_mode(0) is False


class TestConversa:

    def test_resposta_espera_o_comando_pedido(self):
        # o aviso de lista mudou chega no meio, sem ninguem ter pedido
        c = _cliente(pacote(0, DEVICE_LIST_UPDATED)
                     + pacote(0, 77, b"outro")
                     + pacote(0, REQUEST_CONTROLLER_COUNT, struct.pack("<I", 4)))
        assert c.controller_count() == 4
        assert abre(c.sock.enviados[0])[:2] == (0, REQUEST_CONTROLLER_COUNT)
        assert c.sock.buf == b""

    def test_magic_errado_e_erro_de_protocolo(self):
        c = _cliente(b"XXXX" + bytes(12))
        with pytest.raises(OpenRGBError, match="magic"):
            c._recv_packet()

    @pytest.mark.parametrize("servidor, esperado", [(3, 3), (5, 5), (9, 5)])
    def test_versao_negociada_e_a_menor_das_duas(self, servidor, esperado):
        c = _cliente(pacote(0, REQUEST_PROTOCOL_VERSION,
                            struct.pack("<I", servidor)))
        c._negotiate()
        assert c.protocol == esperado
        dev, cmd, data = abre(c.sock.enviados[0])
        assert cmd == REQUEST_PROTOCOL_VERSION
        assert struct.unpack("<I", data) == (CLIENT_PROTOCOL_VERSION,)

    def test_servidor_antigo_que_nao_responde_a_versao_fica_na_zero(self):
        c = _cliente(b"")
        c._negotiate()
        assert c.protocol == 0

    def test_conectar_se_apresenta_e_negocia(self, monkeypatch):
        from spectra.core import protocol as proto_mod
        sock = SocketRoteiro(pacote(0, REQUEST_PROTOCOL_VERSION,
                                    struct.pack("<I", 4)))
        pedidos = []

        def create_connection(addr, timeout):
            pedidos.append((addr, timeout))
            return sock

        monkeypatch.setattr(proto_mod.socket, "create_connection",
                            create_connection)
        c = OpenRGBClient("127.0.0.1", 6799, name="Spectra")
        c.connect(timeout=1.5)
        assert pedidos == [(("127.0.0.1", 6799), 1.5)]
        assert abre(sock.enviados[0]) == (0, SET_CLIENT_NAME, b"Spectra\x00")
        assert abre(sock.enviados[1])[1] == REQUEST_PROTOCOL_VERSION
        assert c.protocol == 4
        assert c.connected is True
        assert sock.timeout == 1.5
