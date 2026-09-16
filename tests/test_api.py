"""Cobre a camada que a interface consome: estado, quadro e as rotas de escrita.

Estes testes montam um `SpectraApp` sobre um cliente falso, sem OpenRGB e sem
hardware, e com a configuracao apontada para um diretorio temporario, para que
rodar a suite nunca toque na configuracao real de quem esta desenvolvendo.
"""

from __future__ import annotations

import time
import types

import pytest

from spectra import app as app_mod
from spectra.core.protocol import MODE_FLAG_HAS_PER_LED_COLOR, Device, Mode, Zone
from spectra.engine.renderer import Renderer
from spectra.server import Handler


def _mode(i, name, flags=0):
    return Mode(i, name, i, flags, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, [])


def _zone(i, name, count, resizable=False):
    lo, hi = (0, 512) if resizable else (count, count)
    return Zone(i, name, 1, lo, hi, count)


def _device(index, name, zones, has_direct=True):
    modes = ([_mode(0, "Direct", MODE_FLAG_HAS_PER_LED_COLOR), _mode(1, "Static")]
             if has_direct else [_mode(0, "Static")])
    leds = []
    acc = 0
    for z in zones:
        z.start_idx = acc
        acc += z.leds_count
        leds += ["%s %d" % (z.name, i) for i in range(z.leds_count)]
    return Device(index, 0, name, "ACME", "bancada", "1.0", "SN%d" % index, "",
                  modes, 1, zones, leds, [(0, 0, 0)] * len(leds))


class FakeClient:
    """Aceita tudo e guarda o ultimo quadro enviado a cada dispositivo."""

    def __init__(self, devices):
        self.devices = devices
        self.protocol = 5
        self.last = {}
        self.zone_writes = []

    def connect(self, timeout=4.0):
        pass

    def close(self):
        pass

    @property
    def connected(self):
        return True

    def load_devices(self):
        return list(self.devices)

    def set_direct_mode(self, i):
        m = self.devices[i].direct_mode()
        if m is None:
            return False
        self.devices[i].active_mode = m.index
        return True

    def update_leds(self, i, colors, count):
        self.last[i] = colors

    def update_zone_leds(self, i, zi, colors, count):
        self.zone_writes.append((i, zi, count))
        self.last[(i, zi)] = colors

    def resize_zone(self, i, zi, size):
        z = self.devices[i].zones[zi]
        z.leds_count = max(z.leds_min, min(z.leds_max, int(size)))


@pytest.fixture
def spectra(tmp_path, monkeypatch):
    """Um app pronto, com dois dispositivos falsos e configuracao isolada."""
    monkeypatch.setattr(app_mod, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(app_mod, "PROFILES_DIR", str(tmp_path / "profiles"))
    monkeypatch.setattr(app_mod, "CONFIG_FILE", str(tmp_path / "config.json"))

    devices = [
        _device(0, "Mobo", [_zone(0, "ARGB 1", 8, resizable=True),
                            _zone(1, "ARGB 2", 4, resizable=True)]),
        _device(1, "RAM", [_zone(0, "DIMM", 3)]),
    ]
    a = app_mod.SpectraApp()
    a.client = FakeClient(devices)
    a.renderer = Renderer(a.client, devices, {}, {"enabled_devices": {}})
    a.renderer.load_scene(app_mod.DEFAULT_SCENE)
    a.connected = True
    a.status_msg = "bancada"
    yield a
    a.renderer.stop()


class TestQuadro:

    def test_preview_hex_tem_seis_digitos_por_led(self, spectra):
        spectra.renderer.frame = spectra.renderer.render_once(0.016)
        h = spectra.preview_hex()
        assert len(h) == spectra.renderer.canvas.n * 6

    def test_preview_hex_so_tem_digito_hexadecimal(self, spectra):
        spectra.renderer.frame = spectra.renderer.render_once(0.016)
        assert set(spectra.preview_hex()) <= set("0123456789abcdef")

    def test_preview_hex_vazio_sem_quadro(self, spectra):
        spectra.renderer.frame = None
        assert spectra.preview_hex() == ""

    def test_preview_hex_bate_com_a_lista_de_cores(self, spectra):
        spectra.renderer.frame = spectra.renderer.render_once(0.016)
        lista = "".join(c[1:] for c in spectra.preview())
        assert spectra.preview_hex() == lista

    def test_brilho_zero_apaga_o_quadro(self, spectra):
        spectra.renderer.settings["brightness"] = 0.0
        spectra.renderer.frame = spectra.renderer.render_once(0.016)
        assert set(spectra.preview_hex()) == {"0"}


class TestFontesAoVivo:

    def test_sem_fonte_ligada_nao_reporta_nada(self, spectra):
        assert spectra.live_sources() == {}

    def test_audio_ligado_reporta_bandas(self, spectra):
        spectra.audio = types.SimpleNamespace(running=True)
        spectra.renderer.ctx.audio.level = 0.5
        spectra.renderer.ctx.audio.bass = 0.25
        d = spectra.live_sources()
        assert d["audio"]["level"] == 0.5
        assert d["audio"]["bass"] == 0.25
        assert len(d["audio"]["bands"]) == len(spectra.renderer.ctx.audio.bands)

    def test_tela_ligada_reporta_a_cor_media(self, spectra):
        spectra.screen = types.SimpleNamespace(running=True)
        spectra.renderer.ctx.screen.average[:] = (0.2, 0.4, 0.6)
        assert spectra.live_sources()["screen"] == [0.2, 0.4, 0.6]

    def test_fonte_parada_fica_de_fora(self, spectra):
        spectra.audio = types.SimpleNamespace(running=False)
        assert "audio" not in spectra.live_sources()


class TestEstado:

    def test_traz_versao_e_diretorio_de_configuracao(self, spectra):
        st = spectra.state()
        assert st["version"]
        assert st["config_dir"]

    def test_traz_o_sinal_de_conectando(self, spectra):
        assert spectra.state()["connecting"] is False
        spectra.connecting = True
        assert spectra.state()["connecting"] is True

    def test_traz_as_preferencias_de_comportamento(self, spectra):
        st = spectra.state()
        assert st["exclusive_mode"] is True
        assert st["autostart_openrgb"] is True

    def test_estado_serializavel(self, spectra):
        import json
        json.dumps(spectra.state(), default=str)


class TestPreferencias:

    def test_desliga_o_modo_exclusivo(self, spectra):
        spectra.update_settings({"exclusive_mode": False})
        assert spectra.config["exclusive_mode"] is False
        assert spectra.state()["exclusive_mode"] is False

    def test_desliga_o_autostart(self, spectra):
        spectra.update_settings({"autostart_openrgb": False})
        assert spectra.config["autostart_openrgb"] is False

    def test_brilho_continua_indo_para_o_renderizador(self, spectra):
        spectra.update_settings({"brightness": 0.4})
        assert spectra.renderer.settings["brightness"] == 0.4


class TestCenaDaInterface:

    def test_troca_a_pilha_e_marca_cena_personalizada(self, spectra):
        spectra.config["last_preset"] = "cabo_cross"
        spectra.set_layers([{"effect": "static", "params": {"color": "#ff0000"}}],
                         preset=None)
        assert spectra.config["last_preset"] is None
        assert [l.effect_id for l in spectra.renderer.layers] == ["static"]

    def test_sem_dizer_o_preset_o_anterior_permanece(self, spectra):
        spectra.config["last_preset"] = "cabo_cross"
        spectra.set_layers([{"effect": "static"}])
        assert spectra.config["last_preset"] == "cabo_cross"

    def test_restaura_um_preset_nomeado(self, spectra):
        spectra.set_layers([{"effect": "static"}], preset="cabo_cross")
        assert spectra.config["last_preset"] == "cabo_cross"


class TestIdentificarZona:

    def test_acende_a_zona_inteira_e_pausa_o_render(self, spectra):
        key = spectra.state()["devices"][0]["key"]
        r = spectra.identify_zone(key, 0, seconds=0.3)
        assert r["ok"] is True
        assert r["lit"] == 8
        assert spectra.renderer.settings["paused"] is True

    def test_pinta_todos_os_leds_da_zona_com_a_cor_pedida(self, spectra):
        key = spectra.state()["devices"][0]["key"]
        spectra.identify_zone(key, 1, seconds=0.3, color="#00ff00")
        buf = spectra.client.last[(0, 1)]
        assert len(buf) == 4 * 4
        assert buf[0:3] == b"\x00\xff\x00"

    def test_retoma_o_render_quando_o_prazo_acaba(self, spectra):
        key = spectra.state()["devices"][0]["key"]
        spectra.identify_zone(key, 0, seconds=0.3)
        time.sleep(0.6)
        assert spectra.renderer.settings["paused"] is False

    def test_zona_desconhecida_devolve_erro(self, spectra):
        r = spectra.identify_zone("nao existe", 0)
        assert r["ok"] is False

    def test_nao_atropela_o_assistente_de_leds(self, spectra):
        key = spectra.state()["devices"][0]["key"]
        spectra._probe_session = {"sizes": {}, "commits": {}, "was_paused": False}
        r = spectra.identify_zone(key, 0)
        assert r["ok"] is False
        spectra._probe_session = None


class TestOrigemDoPedido:
    """O servidor escuta em loopback, que qualquer site aberto tambem alcanca."""

    def _pedido(self, **headers):
        return types.SimpleNamespace(headers=headers)

    def test_aceita_pedido_da_propria_interface(self):
        req = self._pedido(**{"Origin": "http://127.0.0.1:7311",
                              "Host": "127.0.0.1:7311",
                              "Content-Type": "application/json"})
        assert Handler._foreign(req) is False

    def test_aceita_pedido_sem_origem_declarada(self):
        assert Handler._foreign(
            self._pedido(**{"Content-Type": "application/json"})) is False

    def test_recusa_origem_de_outro_site(self):
        req = self._pedido(**{"Origin": "http://exemplo.invalido",
                              "Host": "127.0.0.1:7311",
                              "Content-Type": "application/json"})
        assert Handler._foreign(req) is True

    def test_recusa_porta_diferente_na_mesma_maquina(self):
        req = self._pedido(**{"Origin": "http://127.0.0.1:9999",
                              "Host": "127.0.0.1:7311",
                              "Content-Type": "application/json"})
        assert Handler._foreign(req) is True

    def test_recusa_corpo_que_nao_e_json(self):
        req = self._pedido(**{"Host": "127.0.0.1:7311",
                              "Content-Type": "application/x-www-form-urlencoded"})
        assert Handler._foreign(req) is True

    def test_recusa_pedido_sem_tipo_de_conteudo(self):
        assert Handler._foreign(self._pedido(**{"Host": "127.0.0.1:7311"})) is True
