"""Testes do renderizador: pilha de camadas, alvo, envio e o laco.

Nenhum fala com o OpenRGB: o cliente e falso e so anota o que receberia,
e os dispositivos sao os da bancada de `fakes`.
"""
from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from spectra.core.protocol import (MODE_FLAG_HAS_PER_LED_COLOR, Device, Mode,
                                   OpenRGBError, Zone)
from spectra.effects.base import EFFECTS, EffectDef
from spectra.engine.canvas import device_key
from spectra.engine.renderer import Layer, Renderer


class ClienteQueAnota:
    """Cliente que guarda o ultimo pacote de cada dispositivo."""

    def __init__(self):
        self.pacotes = {}
        self.modos = []

    def update_leds(self, i, cores, n):
        assert len(cores) == 4 * n
        self.pacotes[i] = cores

    def set_direct_mode(self, i):
        self.modos.append(i)
        return True


class ClienteQueCaiu:
    """Cliente cuja conexao ja caiu: todo envio levanta."""

    def update_leds(self, i, cores, n):
        raise OpenRGBError("conexao perdida ao enviar")


def _vermelho(**kw):
    return Layer("static", {"color": "#ff0000", "intensity": 1.0}, **kw)


def _efeito(monkeypatch, nome, fn):
    monkeypatch.setitem(EFFECTS, nome, EffectDef(nome, nome, "Basicos", "", [], fn))


@pytest.fixture
def motor(devices):
    return Renderer(ClienteQueAnota(), devices, {},
                    {"brightness": 1.0, "gamma": 1.0})


def _faixa(motor, nome):
    dev = next(d for d in motor.canvas.devices if d.name == nome)
    _i, start, count = next(s for s in motor.canvas.slices if s[0] == dev.index)
    return dev, start, count


class TestAlvo:
    """Camada presa a um dispositivo ou zona pinta so ali."""

    def test_alvo_de_dispositivo_pinta_so_os_leds_dele(self, motor):
        dev, start, count = _faixa(motor, "RAM")
        motor.set_layers([_vermelho(targets=[device_key(dev)])])
        q = motor.render_once(1 / 60)
        assert np.allclose(q[start:start + count], (1.0, 0.0, 0.0))
        fora = np.delete(q, np.s_[start:start + count], axis=0)
        assert not fora.any()

    def test_alvo_de_zona_pinta_so_a_zona(self, motor):
        mobo = next(d for d in motor.canvas.devices if d.name == "Mobo")
        zi = next(z for z in motor.canvas.zone_info
                  if z["device_key"] == device_key(mobo) and z["zone_index"] == 1)
        motor.set_layers([_vermelho(targets=[f"{device_key(mobo)}:1"])])
        q = motor.render_once(1 / 60)
        acesos = np.flatnonzero(q[:, 0] > 0)
        assert acesos.tolist() == list(range(zi["start"], zi["start"] + zi["count"]))

    def test_alvo_que_nao_existe_nao_pinta_nada(self, motor):
        motor.set_layers([_vermelho(targets=["sumiu#123"])])
        assert not motor.render_once(1 / 60).any()

    def test_camada_de_cima_com_alvo_nao_apaga_o_resto(self, motor):
        dev, start, count = _faixa(motor, "RAM")
        azul = Layer("static", {"color": "#0000ff", "intensity": 1.0})
        motor.set_layers([azul, _vermelho(targets=[device_key(dev)])])
        q = motor.render_once(1 / 60)
        assert np.allclose(q[start:start + count], (1.0, 0.0, 0.0))
        assert np.allclose(q[:start], (0.0, 0.0, 1.0))

    def test_mascara_acompanha_o_canvas_remontado(self, motor):
        # sem refazer a mascara, a do canvas velho teria o tamanho errado
        dev, _s, _c = _faixa(motor, "RAM")
        camada = _vermelho(targets=[device_key(dev)])
        motor.set_layers([camada])
        motor.render_once(1 / 60)
        cooler = next(d for d in motor.canvas.devices if d.name == "Cooler")
        motor.settings["enabled_devices"] = {device_key(cooler): False}
        motor.rebuild()
        q = motor.render_once(1 / 60)
        dev, start, count = _faixa(motor, "RAM")
        assert len(camada.mask_for(motor.canvas)) == motor.canvas.n
        assert np.allclose(q[start:start + count], (1.0, 0.0, 0.0))


class TestCamadaDefeituosa:

    def test_efeito_que_quebra_e_desligado_e_o_resto_segue(self, motor,
                                                            monkeypatch):
        def quebra(ctx, p, st):
            raise ValueError("divisao estranha")

        _efeito(monkeypatch, "teste_quebra", quebra)
        ruim = Layer("teste_quebra")
        motor.set_layers([_vermelho(), ruim])
        q = motor.render_once(1 / 60)
        assert ruim.enabled is False
        assert "teste_quebra" in motor.last_error
        assert np.allclose(q, (1.0, 0.0, 0.0))

    def test_saida_de_tamanho_errado_e_descartada(self, motor, monkeypatch):
        _efeito(monkeypatch, "teste_torto",
                lambda ctx, p, st: np.ones((ctx.n + 1, 3), dtype=np.float32))
        torto = Layer("teste_torto")
        motor.set_layers([_vermelho(), torto])
        q = motor.render_once(1 / 60)
        assert np.allclose(q, (1.0, 0.0, 0.0))
        assert torto.enabled is True

    def test_nan_vira_preto(self, motor, monkeypatch):
        _efeito(monkeypatch, "teste_nan",
                lambda ctx, p, st: np.full((ctx.n, 3), np.nan, dtype=np.float32))
        motor.set_layers([Layer("teste_nan")])
        assert not motor.render_once(1 / 60).any()

    def test_efeito_desconhecido_e_pulado(self, motor):
        motor.set_layers([Layer("nao_existe"), _vermelho()])
        assert np.allclose(motor.render_once(1 / 60), (1.0, 0.0, 0.0))

    def test_camada_transparente_nem_e_avaliada(self, motor, monkeypatch):
        chamadas = []
        _efeito(monkeypatch, "teste_conta", lambda ctx, p, st: (
            chamadas.append(1), np.ones((ctx.n, 3), dtype=np.float32))[1])
        motor.set_layers([Layer("teste_conta", opacity=0.0),
                          Layer("teste_conta", enabled=False)])
        assert not motor.render_once(1 / 60).any()
        assert chamadas == []

    def test_saida_acima_de_um_e_cortada(self, motor, monkeypatch):
        _efeito(monkeypatch, "teste_forte",
                lambda ctx, p, st: np.full((ctx.n, 3), 3.0, dtype=np.float32))
        motor.set_layers([Layer("teste_forte")])
        assert np.allclose(motor.render_once(1 / 60), 1.0)


class TestParametros:

    def test_parametro_nulo_cai_no_padrao(self):
        camada = Layer("static", {"color": None, "intensity": 0.5})
        p = camada.resolved_params()
        assert p["color"] == EFFECTS["static"].defaults()["color"]
        assert p["intensity"] == 0.5

    def test_camada_volta_igual_do_json(self):
        a = Layer("static", {"color": "#00ff00"}, "add", 0.4, False,
                  ["Mobo#1"], "Fundo")
        b = Layer.from_json(a.to_json())
        assert b.to_json() == a.to_json()

    def test_json_antigo_sem_campos_abre_com_padroes(self):
        c = Layer.from_json({})
        assert (c.effect_id, c.blend, c.opacity, c.enabled, c.targets) == (
            "static", "normal", 1.0, True, [])

    def test_cena_carregada_so_traz_os_ajustes_conhecidos(self, motor):
        motor.load_scene({"layers": [{"effect": "static"}],
                          "settings": {"gamma": 2.6, "paused": True,
                                       "enabled_devices": {"x": False}}})
        assert motor.settings["gamma"] == 2.6
        assert motor.settings["paused"] is False
        assert motor.settings["enabled_devices"] == {}
        assert [l.effect_id for l in motor.layers] == ["static"]


class TestEnvio:

    def test_cada_dispositivo_recebe_a_sua_fatia(self, motor):
        dev, start, count = _faixa(motor, "RAM")
        q = np.zeros((motor.canvas.n, 3), dtype=np.float32)
        q[start:start + count] = (0.0, 1.0, 0.0)
        motor.push(q)
        pacote = motor.client.pacotes[dev.index]
        assert pacote == b"\x00\xff\x00\x00" * count
        mobo, _s, n = _faixa(motor, "Mobo")
        assert motor.client.pacotes[mobo.index] == b"\x00" * 4 * n

    def test_brilho_e_gama_entram_antes_dos_oito_bits(self, motor):
        q = np.full((motor.canvas.n, 3), 0.5, dtype=np.float32)
        motor.settings.update(brightness=1.0, gamma=1.0)
        assert motor.to_wire(q)[0, 0] == 128
        motor.settings.update(gamma=2.2)
        assert motor.to_wire(q)[0, 0] == round(0.5 ** 2.2 * 255)
        motor.settings.update(brightness=0.5, gamma=1.0)
        assert motor.to_wire(q)[0, 0] == 64
        assert (motor.to_wire(q)[:, 3] == 0).all()

    def test_queda_no_envio_sobe_e_fica_anotada(self, devices):
        r = Renderer(ClienteQueCaiu(), devices)
        with pytest.raises(OpenRGBError):
            r.push(np.zeros((r.canvas.n, 3), dtype=np.float32))
        assert "conexao perdida" in r.last_error

    def test_apagar_manda_preto_e_engole_a_queda(self, motor, devices):
        motor.blank()
        assert all(set(p) == {0} for p in motor.client.pacotes.values())
        assert len(motor.client.pacotes) == len(motor.canvas.slices)
        Renderer(ClienteQueCaiu(), devices).blank()


def _modo_direto(i=0):
    return Mode(i, "Direct", i, MODE_FLAG_HAS_PER_LED_COLOR,
                0, 0, 0, 0, 0, 0, 0, 0, 0, 0, [])


def _dispositivo(index, ativo):
    z = Zone(0, "Fita", 1, 4, 4, 4)
    return Device(index, 0, "Fita %d" % index, "", "", "", "SN%d" % index, "",
                  [_modo_direto(0), Mode(1, "Static", 1, 0, 0, 0, 0, 0, 0, 0,
                                         0, 0, 0, 0, [])],
                  ativo, [z], ["L"] * 4, [(0, 0, 0)] * 4)


class ClienteDeModo(ClienteQueAnota):

    def __init__(self, recusa=False):
        super().__init__()
        self.recusa = recusa

    def set_direct_mode(self, i):
        if self.recusa:
            raise OpenRGBError("dispositivo nao respondeu")
        return super().set_direct_mode(i)


class TestModoDireto:
    """Trocar de modo sem precisar faz o controlador piscar."""

    def test_quem_ja_esta_no_direto_nao_recebe_troca(self):
        c = ClienteDeModo()
        r = Renderer(c, [_dispositivo(0, 0), _dispositivo(1, 1)])
        r.arm_direct()
        assert c.modos == [1]
        assert r.direct_ok == {0: True, 1: True}

    def test_forcar_manda_para_todos(self):
        c = ClienteDeModo()
        r = Renderer(c, [_dispositivo(0, 0), _dispositivo(1, 1)])
        r.arm_direct(force=True)
        assert c.modos == [0, 1]

    def test_recusa_marca_o_dispositivo_e_nao_derruba(self):
        r = Renderer(ClienteDeModo(recusa=True), [_dispositivo(0, 1)])
        r.arm_direct()
        assert r.direct_ok == {0: False}
        assert "nao respondeu" in r.last_error


def _espera(cond, prazo=2.0):
    fim = time.monotonic() + prazo
    while not cond() and time.monotonic() < fim:
        time.sleep(0.01)
    return cond()


class TestLaco:

    def test_conexao_caida_para_o_laco_e_avisa(self, devices):
        r = Renderer(ClienteQueCaiu(), devices)
        r.set_layers([_vermelho()])
        r.start()
        try:
            assert _espera(lambda: not r._thread.is_alive())
        finally:
            r.stop()
        assert r.connection_lost is True

    def test_destino_extra_que_quebra_e_solto_e_o_laco_segue(self, motor):
        quadros = []

        def quebra(q):
            raise RuntimeError("teclado sumiu")

        motor.ambiente = quebra
        motor.set_layers([_vermelho()])
        motor.start()
        try:
            assert _espera(lambda: motor.ambiente is None)
            quadros.append(motor.ctx.frame)
            assert _espera(lambda: motor.ctx.frame > quadros[0] + 2)
        finally:
            motor.stop()
        assert "teclado sumiu" in motor.last_error
        assert motor._thread.is_alive() is False

    def test_suavizacao_mistura_com_o_quadro_anterior(self, motor, monkeypatch):
        vezes = []

        def pisca(ctx, p, st):
            vezes.append(1)
            v = 1.0 if len(vezes) == 1 else 0.0
            return np.full((ctx.n, 3), v, dtype=np.float32)

        _efeito(monkeypatch, "teste_pisca", pisca)
        segundo = threading.Event()
        vistos = []

        def anota(i, cores, n):
            vistos.append(cores[0])
            if len(vistos) >= 2 * len(motor.canvas.slices):
                segundo.set()

        motor.client.update_leds = anota
        motor.settings["smoothing"] = 0.5
        motor.set_layers([Layer("teste_pisca")])
        motor.start()
        try:
            assert segundo.wait(2)
        finally:
            motor.stop()
        primeiro = vistos[0]
        depois = vistos[len(motor.canvas.slices)]
        assert primeiro == 255
        assert depois == 128

    def test_ligar_duas_vezes_nao_sobe_dois_lacos(self, motor):
        motor.start()
        try:
            primeira = motor._thread
            motor.start()
            assert motor._thread is primeira
        finally:
            motor.stop()


class TestPilha:

    def test_tirar_camada_pelo_id(self, motor):
        motor.set_layers([_vermelho(id="a"), _vermelho(id="b")])
        motor.remove_layer("a")
        assert [l.id for l in motor.layers] == ["b"]
        assert motor.get_layer("a") is None
        motor.remove_layer("nao_existe")
        assert [l.id for l in motor.layers] == ["b"]

    def test_camada_nova_entra_na_posicao_pedida(self, motor):
        motor.set_layers([_vermelho(id="a"), _vermelho(id="b")])
        motor.add_layer(_vermelho(id="c"), 1)
        motor.add_layer(_vermelho(id="d"), -1)
        motor.add_layer(_vermelho(id="e"))
        assert [l.id for l in motor.layers] == ["d", "a", "c", "b", "e"]

    def test_gabinete_sem_led_nao_quebra(self):
        r = Renderer(ClienteQueAnota(), [])
        r.set_layers([_vermelho()])
        assert r.render_once(1 / 60).shape == (0, 3)
        r.blank()
        assert r.client.pacotes == {}

    def test_remontar_zera_a_memoria_das_camadas(self, motor):
        camada = _vermelho()
        camada.state["particulas"] = [1, 2, 3]
        motor.set_layers([camada])
        motor.rebuild()
        assert camada.state == {}
