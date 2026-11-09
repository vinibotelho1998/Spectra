"""Cobre a camada que a interface consome: estado, quadro e as rotas de escrita.

Estes testes montam um `SpectraApp` sobre um cliente falso, sem OpenRGB e sem
hardware, e com a configuracao apontada para um diretorio temporario, para que
rodar a suite nunca toque na configuracao real de quem esta desenvolvendo.
"""

from __future__ import annotations

import io
import json
import sys
import threading
import time
import types

import numpy as np
import pytest

from spectra import app as app_mod
from spectra import server as server_mod
from spectra import tray as tray_mod
from spectra.core.protocol import (MODE_FLAG_HAS_PER_LED_COLOR, Device, Mode,
                                   OpenRGBError, Zone)
from spectra.effects.base import EFFECTS, EffectDef
from spectra.engine.renderer import Layer, Renderer
from spectra.server import Handler
from spectra.tray import Tray


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


class TecladoAusente:
    """Teclado que nunca e encontrado, no lugar do HID de verdade."""

    def __init__(self, *_a, **_k):
        self.conectado = False
        self.caminho = None
        self.erro = "teclado Akko nao encontrado"

    def abrir(self):
        return False

    def fechar(self):
        pass

    def to_json(self):
        return {"kind": "akko", "connected": False, "error": self.erro}


def _sem_nada_de_verdade(monkeypatch):
    """Fecha todo caminho que sai do processo de teste.

    Uma reconexao do vigia ou uma camada de audio bastavam para abrir o
    teclado, a captura de som ou subir o servidor do OpenRGB de verdade. O
    teste que precisa de um desses troca pela sua versao falsa.
    """
    from spectra.core import admin
    monkeypatch.setattr(app_mod, "AudioSource", FonteQueFalha)
    monkeypatch.setattr(app_mod, "ScreenSource", FonteQueFalha)
    monkeypatch.setattr(app_mod, "SensorSource", FonteQueFalha)
    monkeypatch.setattr(app_mod, "OPENRGB_CANDIDATES", [])
    # No Linux o executavel tambem e procurado no PATH. A suite nao deve
    # descobrir nem iniciar a instalacao real da maquina de desenvolvimento.
    monkeypatch.setattr(app_mod.shutil, "which", lambda *_a, **_k: None)
    # nem a sondagem da porta: com o OpenRGB aberto na maquina, ela o achava
    monkeypatch.setattr(app_mod, "_port_open", lambda *a, **k: False)
    for nome, valor in (("tarefa_existe", False), ("rodar_tarefa", False),
                        ("criar_tarefa", "recusado"), ("encerrar_openrgb", None),
                        ("encerrar_tarefa", False),
                        ("sou_admin", False), ("openrgb_elevado", False),
                        ("openrgb_rodando", False),
                        ("pawnio_instalado", False)):
        monkeypatch.setattr(admin, nome, lambda *a, _v=valor, **k: _v)
    try:
        from spectra.core import akko
    except ImportError:
        return
    monkeypatch.setattr(akko, "AkkoKeyboard", TecladoAusente)


@pytest.fixture
def spectra(tmp_path, monkeypatch):
    """Um app pronto, com dois dispositivos falsos e configuracao isolada."""
    monkeypatch.setattr(app_mod, "ESTABILIZACAO_DISPOSITIVOS", 0.0)
    monkeypatch.setattr(app_mod, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(app_mod, "PROFILES_DIR", str(tmp_path / "profiles"))
    monkeypatch.setattr(app_mod, "CONFIG_FILE", str(tmp_path / "config.json"))
    _sem_nada_de_verdade(monkeypatch)

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

    def test_recusa_dominio_apontado_para_o_loopback(self):
        # site que troca o proprio DNS para 127.0.0.1: Origin e Host batem
        req = self._pedido(**{"Origin": "http://exemplo.invalido:7311",
                              "Host": "exemplo.invalido:7311",
                              "Content-Type": "application/json"})
        assert Handler._foreign(req) is True

    def test_aceita_localhost_pelo_nome(self):
        req = self._pedido(**{"Origin": "http://localhost:7311",
                              "Host": "localhost:7311",
                              "Content-Type": "application/json"})
        assert Handler._foreign(req) is False


class Resposta:
    """Faz as vezes do handler, guardando o que seria enviado."""

    def __init__(self, path="/", host="127.0.0.1:7311"):
        self.path = path
        self.headers = {"Host": host}
        self.app = types.SimpleNamespace(state=lambda: {"segredo": True})
        self.code = None
        self.body = None

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        self.code, self.body = code, body

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode("utf-8"))


class TestArquivosEstaticos:

    @pytest.fixture
    def ui(self, tmp_path, monkeypatch):
        pasta = tmp_path / "ui"
        pasta.mkdir()
        (pasta / "index.html").write_text("ok", encoding="utf-8")
        vizinha = tmp_path / "ui2"
        vizinha.mkdir()
        (vizinha / "segredo.txt").write_text("segredo", encoding="utf-8")
        monkeypatch.setattr(server_mod, "UI_DIR", str(pasta))
        return pasta

    def test_serve_o_arquivo_da_interface(self, ui):
        r = Resposta()
        Handler._static(r, "/index.html")
        assert r.code == 200
        assert r.body == b"ok"

    def test_nao_serve_pasta_vizinha_com_o_mesmo_comeco(self, ui):
        r = Resposta()
        Handler._static(r, "/../ui2/segredo.txt")
        assert r.code == 404

    def test_leitura_por_dominio_de_fora_e_recusada(self):
        r = Resposta("/api/state", host="exemplo.invalido:7311")
        Handler.do_GET(r)
        assert r.code == 403
        assert b"segredo" not in r.body

    def test_leitura_pelo_loopback_passa(self):
        r = Resposta("/api/state")
        Handler.do_GET(r)
        assert r.code == 200


class TestPerfis:

    def test_salva_carrega_e_apaga(self, spectra):
        assert spectra.save_profile("Noite")["ok"]
        assert "Noite" in spectra.list_profiles()
        assert spectra.load_profile("Noite") is True
        assert spectra.delete_profile("Noite") is True
        assert "Noite" not in spectra.list_profiles()

    def test_nome_com_caminho_nao_apaga_a_configuracao(self, spectra, tmp_path):
        spectra.save_config()
        assert (tmp_path / "config.json").exists()
        assert spectra.delete_profile("../config") is False
        assert (tmp_path / "config.json").exists()

    def test_nome_com_caminho_nao_carrega_arquivo_de_fora(self, spectra, tmp_path):
        (tmp_path / "fora.json").write_text(
            json.dumps({"layers": [{"effect": "static"}]}), encoding="utf-8")
        antes = [l.id for l in spectra.renderer.layers]
        assert spectra.load_profile("../fora") is False
        assert [l.id for l in spectra.renderer.layers] == antes

    def test_perfil_com_formato_estranho_e_recusado(self, spectra, tmp_path):
        (tmp_path / "profiles" / "torto.json").write_text("[1, 2]", encoding="utf-8")
        assert spectra.load_profile("torto") is False

    def test_perfil_estranho_na_abertura_cai_na_cena_padrao(self, spectra, tmp_path):
        (tmp_path / "profiles" / "torto.json").write_text(
            json.dumps({"layers": [1]}), encoding="utf-8")
        spectra.config["last_profile"] = "torto"
        spectra.renderer.layers = []
        spectra._load_startup_scene()
        assert [l.effect_id for l in spectra.renderer.layers] == ["rainbow_wave"]

    def test_falha_ao_gravar_preserva_o_perfil_anterior(self, spectra, tmp_path):
        spectra.save_profile("Noite")
        arq = tmp_path / "profiles" / "Noite.json"
        antes = arq.read_text(encoding="utf-8")
        spectra.renderer.layers[0].params["quebra"] = object()
        with pytest.raises(TypeError):
            spectra.save_profile("Noite", sobrescrever=True)
        assert arq.read_text(encoding="utf-8") == antes
        assert not (tmp_path / "profiles" / "Noite.json.tmp").exists()

    def test_sem_a_pasta_a_lista_vem_vazia(self, spectra, tmp_path):
        (tmp_path / "profiles").rmdir()
        assert spectra.list_profiles() == []
        json.dumps(spectra.state(), default=str)


class TestConfiguracao:

    def test_arquivo_ilegivel_fica_guardado_ao_lado(self, spectra, tmp_path):
        (tmp_path / "config.json").write_text("{ quebrado", encoding="utf-8")
        novo = app_mod.SpectraApp()
        guardado = tmp_path / "config.json.corrompido"
        assert guardado.read_text(encoding="utf-8") == "{ quebrado"
        assert novo.config["exclusive_mode"] is True

    def test_grava_mesmo_sem_a_pasta(self, spectra, tmp_path, monkeypatch):
        destino = tmp_path / "sumiu"
        monkeypatch.setattr(app_mod, "CONFIG_DIR", str(destino))
        monkeypatch.setattr(app_mod, "CONFIG_FILE", str(destino / "config.json"))
        spectra.save_config()
        assert json.loads((destino / "config.json").read_text(encoding="utf-8"))


class TestFontesAoRemontar:
    """As fontes guardam o estado que receberam e seguem escrevendo nele."""

    def test_mexer_no_layout_mantem_o_audio_chegando(self, spectra):
        do_audio = spectra.renderer.ctx.audio
        key = spectra.state()["devices"][0]["key"]
        spectra.set_zone_geometry(key, 0, {"shape": "line", "x1": 0.1,
                                           "y1": 0.5, "x2": 0.9, "y2": 0.5})
        do_audio.level = 0.9
        assert spectra.renderer.ctx.audio.level == 0.9

    def test_trocar_dispositivos_mantem_tela_e_sensores(self, spectra):
        ctx = spectra.renderer.ctx
        spectra.renderer.set_devices(spectra.client.load_devices())
        assert spectra.renderer.ctx is not ctx
        assert spectra.renderer.ctx.screen is ctx.screen
        assert spectra.renderer.ctx.sensors is ctx.sensors


class FonteQueFalha:
    """Fonte cuja captura nunca abre, contando quantas vezes tentaram."""

    def __init__(self, *_a, **_k):
        self.running = False
        self.tentativas = 0

    def start(self):
        self.tentativas += 1
        return False

    def stop(self):
        pass


class TestFontesQueFalham:

    def test_captura_quebrada_nao_e_reaberta_a_cada_passo(self, spectra):
        # arrastar um slider manda uma mudanca de camada a cada 40 ms
        fonte = FonteQueFalha()
        spectra.audio = fonte
        spectra.set_layers([{"effect": "audio_vu"}])
        lid = spectra.renderer.layers[0].id
        for i in range(10):
            spectra.update_layer(lid, {"params": {"gain": 1.0 + i / 10}})
        assert fonte.tentativas == 1

    def test_configuracao_nova_tenta_na_hora(self, spectra, monkeypatch):
        spectra.audio = FonteQueFalha()
        spectra.set_layers([{"effect": "audio_vu"}])
        nova = FonteQueFalha()
        monkeypatch.setattr(app_mod, "AudioSource", lambda *a, **k: nova)
        spectra.set_source_config("audio", {"device": 3})
        assert nova.tentativas == 1


class TecladoFalso:
    """Teclado aberto que so anota a cor que receberia."""

    def __init__(self):
        self.conectado = True
        self.plugado = True
        self.caminho = "hid#akko"
        self.cores = []
        self.aberturas = 0

    def abrir(self):
        self.aberturas += 1
        self.conectado = self.plugado
        return self.conectado

    def cor_em_fluxo(self, r, g, b):
        self.cores.append((r, g, b))
        return True

    def apagar(self):
        self.cores.append((0, 0, 0))
        return True

    def fechar(self):
        self.conectado = False

    def to_json(self):
        return {"kind": "akko", "connected": self.conectado}


class TestTecladoAoVivo:

    @pytest.fixture
    def com_teclado(self, spectra, monkeypatch):
        pytest.importorskip("spectra.core.akko", reason="modulo so existe no Windows")
        # nenhuma fonte de verdade: tela e audio ficam so no estado
        monkeypatch.setattr(spectra, "_sync_sources", lambda: None)
        spectra.teclado = TecladoFalso()
        spectra._liga_teclado()
        return spectra

    def test_pintar_nao_espera_a_trava_do_app(self, com_teclado):
        # O laco de render chama isto segurando a trava do renderizador, e
        # as rotas da interface pegam a do app antes da do renderizador.
        # Esperar a do app aqui travava os dois lados para sempre.
        pinta = com_teclado.renderer.ambiente
        quadro = com_teclado.renderer.render_once(1 / 60)
        pegou, solta = threading.Event(), threading.Event()

        def dono():
            with com_teclado._lock:
                pegou.set()
                solta.wait(5)

        t = threading.Thread(target=dono, daemon=True)
        t.start()
        assert pegou.wait(2)
        feito = threading.Event()
        threading.Thread(target=lambda: (pinta(quadro), feito.set()),
                         daemon=True).start()
        try:
            assert feito.wait(1.0), "o teclado ficou esperando a trava do app"
        finally:
            solta.set()
            t.join(2)

    def test_efeito_de_tela_chega_ao_teclado(self, com_teclado):
        com_teclado.set_layers([{"effect": "screen_average",
                                 "params": {"smooth": 0.0, "dominant": False}}])
        com_teclado.renderer.ctx.screen.average[:] = (1.0, 0.0, 0.0)
        pinta = com_teclado.renderer.ambiente
        pinta(com_teclado.renderer.render_once(1 / 60))
        r, g, b = com_teclado.teclado.cores[-1]
        assert r > 200 and g == 0 and b == 0

    def _cor_com_brilho(self, app, brilho):
        app.config["akko_suavizacao"] = 0.0
        app._liga_teclado()
        app.set_layers([{"effect": "static", "params": {"color": "#ff0000"}}])
        app.update_settings({"brightness": brilho})
        app.renderer.ambiente(app.renderer.render_once(1 / 60))
        return app.teclado.cores[-1]

    def test_apagar_os_leds_apaga_o_teclado(self, com_teclado):
        assert self._cor_com_brilho(com_teclado, 0.0) == (0, 0, 0)

    def test_brilho_pela_metade_escurece_o_teclado(self, com_teclado):
        cheio = self._cor_com_brilho(com_teclado, 1.0)
        metade = self._cor_com_brilho(com_teclado, 0.5)
        assert cheio == (255, 0, 0)
        assert 0 < metade[0] < cheio[0]

    def test_teclado_fora_nao_recebe_cor(self, com_teclado):
        com_teclado.teclado.conectado = False
        com_teclado.renderer.ambiente(com_teclado.renderer.render_once(1 / 60))
        assert com_teclado.teclado.cores == []

    def test_tirar_do_controle_apaga_e_solta_o_teclado(self, com_teclado):
        # solto sem apagar, ele ficava para sempre na ultima cor
        com_teclado.config["akko_keyboard"] = False
        com_teclado._liga_teclado()
        assert com_teclado.teclado.cores[-1] == (0, 0, 0)
        assert com_teclado.teclado.conectado is False
        assert com_teclado.renderer.ambiente is None

    def test_apagar_com_render_pausado_apaga_o_teclado(self, com_teclado):
        app = com_teclado
        app.config["akko_suavizacao"] = 0.0
        app._liga_teclado()
        app.set_layers([{"effect": "static", "params": {"color": "#ff0000"}}])
        app.renderer.frame = app.renderer.render_once(1 / 60)
        app.renderer.settings["paused"] = True
        app.update_settings({"brightness": 0.0})
        assert app.teclado.cores[-1] == (0, 0, 0)

    def test_vigia_reabre_o_teclado_que_voltou(self, com_teclado):
        t = com_teclado.teclado
        t.conectado = t.plugado = False
        com_teclado.renderer.ambiente = None
        com_teclado._vigia_teclado()
        assert t.aberturas == 1
        assert com_teclado.renderer.ambiente is None
        t.plugado = True
        com_teclado._teclado_proxima = 0.0
        com_teclado._vigia_teclado()
        assert t.conectado is True
        assert com_teclado.renderer.ambiente is not None

    def test_vigia_espera_entre_uma_procura_e_outra(self, com_teclado):
        t = com_teclado.teclado
        t.conectado = t.plugado = False
        com_teclado._vigia_teclado()
        antes = t.aberturas
        com_teclado._vigia_teclado()
        assert t.aberturas == antes

    def test_vigia_nao_procura_teclado_que_nunca_abriu(self, com_teclado):
        t = com_teclado.teclado
        t.conectado = t.plugado = False
        t.caminho = None
        antes = t.aberturas
        com_teclado._vigia_teclado()
        assert t.aberturas == antes

    def test_vigia_da_conexao_reabre_o_teclado(self, com_teclado, monkeypatch):
        # a procura so acontece se o laco do vigia a chamar a cada volta
        t = com_teclado.teclado
        t.conectado = False
        com_teclado.renderer.ambiente = None
        monkeypatch.setattr(com_teclado, "_connect",
                            lambda exclusive_pass, pode_subir=True: True)
        com_teclado._watchdog_stop = ParadaDepoisDe(1)
        com_teclado._watchdog_loop()
        assert t.conectado is True
        assert com_teclado.renderer.ambiente is not None


class TestConexao:

    def test_duas_tentativas_ao_mesmo_tempo_viram_fila(self, spectra, monkeypatch):
        dentro, maximo = [0], [0]
        conta = threading.Lock()

        def falso(exclusive_pass, pode_subir=True):
            with conta:
                dentro[0] += 1
                maximo[0] = max(maximo[0], dentro[0])
            time.sleep(0.15)
            with conta:
                dentro[0] -= 1
            return True

        monkeypatch.setattr(spectra, "_connect", falso)
        ts = [threading.Thread(target=spectra.connect) for _ in range(3)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(5)
        assert maximo[0] == 1
        assert spectra.connecting is False


class TestCamadas:

    def _tres(self, spectra):
        spectra.set_layers([{"effect": "static", "id": i} for i in "abc"])

    def test_opacidade_em_texto_nao_derruba_o_render(self, spectra):
        lid = spectra.renderer.layers[0].id
        spectra.update_layer(lid, {"opacity": "0.5", "enabled": 1})
        assert spectra.renderer.layers[0].opacity == 0.5
        assert spectra.renderer.layers[0].enabled is True
        spectra.renderer.render_once(1 / 60)

    def test_reordenar_sem_citar_uma_camada_nao_a_apaga(self, spectra):
        self._tres(spectra)
        spectra.reorder_layers(["c", "a"])
        assert [l.id for l in spectra.renderer.layers] == ["c", "a", "b"]

    def test_id_repetido_na_ordem_conta_uma_vez(self, spectra):
        self._tres(spectra)
        spectra.reorder_layers(["b", "a", "b", "c"])
        assert [l.id for l in spectra.renderer.layers] == ["b", "a", "c"]


class TestQuadroDeCanvasAnterior:

    def test_nao_vai_pacote_com_contagem_maior_que_as_cores(self, spectra):
        # render pausado e canvas remontado: o ultimo quadro e do tamanho velho
        r = spectra.renderer
        velho = np.zeros((r.canvas.n - 3, 3), dtype=np.float32)
        enviados = []
        spectra.client.update_leds = (
            lambda i, cores, n: enviados.append((len(cores), n)))
        r.push(velho)
        assert all(tam == 4 * n for tam, n in enviados)

    def test_brilho_com_render_pausado_depois_de_religar_dispositivo(self, spectra):
        r = spectra.renderer
        key = spectra.state()["devices"][1]["key"]
        spectra.update_settings({"enabled_devices": {key: False}})
        r.frame = r.render_once(1 / 60)
        r.settings["paused"] = True
        spectra.update_settings({"enabled_devices": {key: True}})
        enviados = []
        spectra.client.update_leds = (
            lambda i, cores, n: enviados.append((len(cores), n)))
        spectra.update_settings({"brightness": 0.3})
        assert all(tam == 4 * n for tam, n in enviados)


class RelogioDeUmMes:
    """Relogio que salta trinta dias logo depois do laco comecar."""

    def __init__(self):
        self.chamadas = 0

    def perf_counter(self):
        self.chamadas += 1
        return 0.0 if self.chamadas == 1 else 30 * 86400.0 + self.chamadas * 1e-3

    def sleep(self, s):
        time.sleep(min(s, 0.002))


class TestRelogioDosEfeitos:

    def test_tempo_dos_efeitos_nao_cresce_sem_fim(self, spectra, monkeypatch):
        # com um mes de app ligado, o float32 dos efeitos ja nao anda
        from spectra.engine import renderer as renderer_mod
        monkeypatch.setattr(renderer_mod, "time", RelogioDeUmMes())
        r = spectra.renderer
        r.start()
        prazo = time.monotonic() + 2.0
        while r.ctx.frame < 3 and time.monotonic() < prazo:
            time.sleep(0.01)
        r.stop()
        assert r.ctx.frame >= 3
        assert 0.0 <= r.ctx.t < 86400.0


class TestAssistenteDuranteOPiscar:

    def test_render_nao_fica_parado_depois_do_assistente(self, spectra):
        key = spectra.state()["devices"][0]["key"]
        spectra.identify_zone(key, 0, seconds=5)
        assert spectra.renderer.settings["paused"] is True
        assert spectra.probe_multi_start()["ok"] is True
        spectra.probe_finish()
        assert spectra.renderer.settings["paused"] is False


class QuadroLento:
    """Efeito que para no meio do quadro ate o teste soltar.

    E o jeito de pegar o laco de render com a trava na mao, desenhando, para
    outra thread mexer na cena exatamente nesse momento.
    """

    def __init__(self, monkeypatch, app):
        self.dentro = threading.Event()
        self.solta = threading.Event()
        monkeypatch.setitem(EFFECTS, "teste_lento", EffectDef(
            "teste_lento", "Lento", "Basicos", "", [], self._fn))
        app.set_layers([{"effect": "teste_lento", "id": "L"}])

    def _fn(self, ctx, p, st):
        st["fase"] = 1.0
        self.dentro.set()
        self.solta.wait(2)
        return np.full((ctx.n, 3), st["fase"], dtype=np.float32)


class TestCenaDuranteOQuadro:

    def test_trocar_o_efeito_no_meio_do_quadro_nao_desliga_a_camada(
            self, spectra, monkeypatch):
        # sem a trava do renderizador o estado era limpo com o efeito ainda
        # rodando, e o erro dele desligava a camada como se fosse defeito
        lento = QuadroLento(monkeypatch, spectra)
        r = spectra.renderer
        r.start()
        try:
            assert lento.dentro.wait(2)
            t = threading.Thread(target=spectra.update_layer,
                                 args=("L", {"effect": "static"}), daemon=True)
            t.start()
            time.sleep(0.1)
            lento.solta.set()
            t.join(2)
        finally:
            lento.solta.set()
            r.stop()
        camada = r.get_layer("L")
        assert camada.effect_id == "static"
        assert camada.enabled is True
        assert r.last_error is None

    def test_apagar_pela_bandeja_apaga_mesmo_com_quadro_em_andamento(
            self, spectra, monkeypatch):
        lento = QuadroLento(monkeypatch, spectra)
        r = spectra.renderer
        r.start()
        try:
            assert lento.dentro.wait(2)
            threading.Timer(0.1, lento.solta.set).start()
            Tray(None, spectra, lambda: None)._alternar_luz()
            time.sleep(0.2)
        finally:
            lento.solta.set()
            r.stop()
        assert r.settings["brightness"] == 0.0
        # o ultimo pacote de cada dispositivo tem que ser o preto
        assert all(set(cores) == {0} for cores in spectra.client.last.values())

    def test_render_pausado_nao_segura_a_trava(self, spectra):
        r = spectra.renderer
        r.settings["paused"] = True
        r.start()
        livres = 0
        try:
            time.sleep(0.05)
            for _ in range(20):
                if r._lock.acquire(blocking=False):
                    r._lock.release()
                    livres += 1
                time.sleep(0.005)
        finally:
            r.stop()
        assert livres == 20


class ParadaDepoisDe:
    """Faz as vezes do evento de parada do vigia, liberando algumas voltas."""

    def __init__(self, voltas):
        self.voltas = voltas

    def wait(self, _timeout):
        self.voltas -= 1
        return self.voltas < 0


class TestVigia:

    def test_erro_inesperado_ao_reconectar_nao_mata_o_vigia(self, spectra,
                                                             monkeypatch):
        tentativas = []

        def quebra(exclusive_pass, pode_subir=True):
            tentativas.append(exclusive_pass)
            raise RuntimeError("falha inesperada")

        monkeypatch.setattr(spectra, "_connect", quebra)
        spectra._watchdog_stop = ParadaDepoisDe(3)
        spectra.renderer.connection_lost = True
        spectra._watchdog_loop()
        assert len(tentativas) == 3
        assert "falha inesperada" in spectra.status_msg
        assert spectra.connecting is False


class TestConcorrenciaNasRotas:
    """Duas threads do servidor atendendo pedidos ao mesmo tempo."""

    def test_duas_sincronias_de_fonte_juntas_criam_uma_so(self, spectra,
                                                          monkeypatch):
        # a conexao e a carga de perfil sincronizam as fontes sem a trava do
        # app, e a fonte que sobrasse capturaria para sempre
        criadas = []

        class FonteLenta(FonteQueFalha):
            def __init__(self, *a, **k):
                super().__init__()
                criadas.append(self)
                time.sleep(0.1)

        monkeypatch.setattr(app_mod, "AudioSource", FonteLenta)
        with spectra.renderer._lock:
            spectra.renderer.layers = [Layer("audio_vu")]
        ts = [threading.Thread(target=spectra._sync_sources, daemon=True)
              for _ in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(2)
        assert len(criadas) == 1
        assert spectra.audio is criadas[0]

    def test_salvar_o_mesmo_perfil_duas_vezes_juntas_vira_fila(
            self, spectra, tmp_path, monkeypatch):
        dentro, maximo = [0], [0]
        conta = threading.Lock()
        real = app_mod._grava_json

        def lento(path, data):
            if path.endswith("Noite.json"):
                with conta:
                    dentro[0] += 1
                    maximo[0] = max(maximo[0], dentro[0])
                time.sleep(0.1)
                with conta:
                    dentro[0] -= 1
            real(path, data)

        monkeypatch.setattr(app_mod, "_grava_json", lento)
        ts = [threading.Thread(target=spectra.save_profile, args=("Noite",),
                               daemon=True) for _ in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(2)
        assert maximo[0] == 1
        arq = tmp_path / "profiles" / "Noite.json"
        assert json.loads(arq.read_text(encoding="utf-8"))["layers"]


def _reabre(monkeypatch, devices_fn):
    """Abre um app novo sobre a configuracao gravada, como num reinicio.

    Passa pelo `connect` de verdade, com o cliente falso e sem nada que
    suba servidor, abra teclado ou consulte o Windows.
    """
    b = app_mod.SpectraApp()
    b.client = FakeClient(devices_fn())
    monkeypatch.setattr(b, "ensure_openrgb", lambda **_: True)
    monkeypatch.setattr(b, "check_elevacao", lambda: {})
    monkeypatch.setattr(b, "_liga_teclado", lambda: None)
    monkeypatch.setattr(b, "start_watchdog", lambda: None)
    assert b.connect() is True
    b.renderer.stop()
    return b


def _bancada():
    return [
        _device(0, "Mobo", [_zone(0, "ARGB 1", 8, resizable=True),
                            _zone(1, "ARGB 2", 4, resizable=True)]),
        _device(1, "RAM", [_zone(0, "DIMM", 3)]),
    ]


class TestCenaAoReabrir:
    """O que estava no ar volta quando o app abre de novo."""

    def test_preset_e_ajustes_voltam(self, spectra, monkeypatch):
        spectra.apply_preset("aurora")
        spectra.update_settings({"gamma": 2.6, "fps": 30, "brightness": 0.4})
        spectra.shutdown(blank=False)
        b = _reabre(monkeypatch, _bancada)
        s = b.renderer.settings
        assert (s["gamma"], s["fps"], s["brightness"]) == (2.6, 30, 0.4)
        esperado = [l["effect"] for l in app_mod.ps.by_id("aurora").layers]
        assert [l.effect_id for l in b.renderer.layers] == esperado
        assert b.state()["last_preset"] == "aurora"

    def test_ajuste_feito_depois_do_perfil_nao_volta_atras(self, spectra,
                                                          monkeypatch):
        spectra.save_profile("Noite")
        spectra.update_settings({"gamma": 2.8, "brightness": 0.2})
        spectra.apply_preset("fogo")
        spectra.shutdown(blank=False)
        b = _reabre(monkeypatch, _bancada)
        assert b.renderer.settings["gamma"] == 2.8
        assert b.renderer.settings["brightness"] == 0.2
        esperado = [l["effect"] for l in app_mod.ps.by_id("fogo").layers]
        assert [l.effect_id for l in b.renderer.layers] == esperado

    def test_camada_mexida_a_mao_tambem_volta(self, spectra, monkeypatch):
        lid = spectra.renderer.layers[0].id
        spectra.update_layer(lid, {"params": {"speed": 0.9}})
        spectra.add_layer("static", params={"color": "#00ff00"})
        spectra.shutdown(blank=False)
        b = _reabre(monkeypatch, _bancada)
        assert [l.effect_id for l in b.renderer.layers] == ["rainbow_wave", "static"]
        assert b.renderer.layers[0].params["speed"] == 0.9

    def test_apagado_abre_aceso_no_ultimo_brilho(self, spectra, monkeypatch):
        spectra.update_settings({"brightness": 0.3})
        spectra.update_settings({"brightness": 0.0})
        spectra.shutdown(blank=False)
        b = _reabre(monkeypatch, _bancada)
        assert b.renderer.settings["brightness"] == 0.3

    def test_primeira_abertura_toca_o_preset_inicial(self, spectra, monkeypatch):
        b = _reabre(monkeypatch, _bancada)
        assert b.state()["last_preset"] == app_mod.PRESET_INICIAL
        assert [l.effect_id for l in b.renderer.layers] == ["rainbow_wave"]

    def test_slider_arrastado_nao_grava_a_cada_passo(self, spectra, tmp_path):
        lid = spectra.renderer.layers[0].id
        spectra.update_layer(lid, {"params": {"speed": 0.5}})
        gravado = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
        assert gravado["cena"]["layers"][0]["params"]["speed"] == 0.5
        spectra.update_layer(lid, {"params": {"speed": 0.6}})
        assert spectra._gravar_pendente is True
        gravado = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
        assert gravado["cena"]["layers"][0]["params"]["speed"] == 0.5

    def test_vigia_grava_o_que_ficou_pendente(self, spectra, tmp_path,
                                              monkeypatch):
        lid = spectra.renderer.layers[0].id
        spectra.update_layer(lid, {"params": {"speed": 0.5}})
        spectra.update_layer(lid, {"params": {"speed": 0.6}})
        # o render desta bancada nunca subiu, entao o vigia tenta reconectar:
        # a conexao falsa impede que ele va atras de servidor e teclado
        monkeypatch.setattr(spectra, "_connect",
                            lambda exclusive_pass, pode_subir=True: True)
        spectra._watchdog_stop = ParadaDepoisDe(1)
        spectra._watchdog_loop()
        gravado = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
        assert gravado["cena"]["layers"][0]["params"]["speed"] == 0.6


class TestCenaAtual:
    """O que a vitrine e o Tocando agora dizem que esta no ar."""

    def test_carregar_perfil_tira_a_marca_do_preset(self, spectra):
        spectra.save_profile("Noite")
        spectra.apply_preset("fogo")
        assert spectra.load_profile("Noite") is True
        st = spectra.state()
        assert st["last_preset"] is None
        assert st["perfil_atual"] == "Noite"

    def test_aplicar_preset_tira_a_marca_do_perfil(self, spectra):
        spectra.save_profile("Noite")
        spectra.apply_preset("fogo")
        assert spectra.state()["perfil_atual"] is None

    def test_apagar_o_perfil_atual_nao_deixa_nome_orfao(self, spectra):
        spectra.save_profile("Temp")
        spectra.delete_profile("Temp")
        st = spectra.state()
        assert st["last_profile"] is None
        assert st["perfil_atual"] is None

    def test_desfazer_devolve_a_marca_do_perfil(self, spectra):
        spectra.save_profile("Noite")
        spectra.set_layers([{"effect": "static"}], preset=None, perfil="Noite")
        assert spectra.state()["perfil_atual"] == "Noite"
        spectra.set_layers([{"effect": "static"}], preset=None)
        assert spectra.state()["perfil_atual"] is None


class TestSalvarPerfil:

    def test_nome_existente_pergunta_antes(self, spectra, tmp_path):
        spectra.save_profile("Jogo")
        arq = tmp_path / "profiles" / "Jogo.json"
        antes = arq.read_text(encoding="utf-8")
        spectra.apply_preset("fogo")
        r = spectra.save_profile("Jogo")
        assert r == {"ok": False, "existe": True, "name": "Jogo"}
        assert arq.read_text(encoding="utf-8") == antes

    def test_nome_que_vira_um_existente_depois_de_limpo(self, spectra):
        spectra.save_profile("Jogo")
        r = spectra.save_profile("Jogo!")
        assert r["existe"] is True
        assert r["name"] == "Jogo"

    def test_confirmado_sobrescreve(self, spectra, tmp_path):
        spectra.save_profile("Jogo")
        spectra.apply_preset("fogo")
        assert spectra.save_profile("Jogo", sobrescrever=True)["ok"] is True
        salvo = json.loads((tmp_path / "profiles" / "Jogo.json")
                           .read_text(encoding="utf-8"))
        assert salvo["layers"][0]["effect"] == app_mod.ps.by_id("fogo").layers[0]["effect"]


class TestMapa:

    def _plano(self, spectra):
        key = spectra.state()["devices"][0]["key"]
        spectra.set_zone_plan(key, 0, [{"kind": "fan", "count": 4, "spot": "topo_esq"},
                                       {"kind": "fan", "count": 4, "spot": "topo_dir"}])
        return key

    def test_restaurar_devolve_o_mapa_anterior(self, spectra):
        key = self._plano(spectra)
        anterior = spectra.reset_layout()
        assert spectra.config["layout"] == {}
        assert anterior[key]["zones"]["0"]["shape"] == "multi"

    def test_desfazer_regrava_o_mapa(self, spectra):
        key = self._plano(spectra)
        anterior = spectra.reset_layout()
        assert spectra.set_layout(anterior)["ok"] is True
        geo = next(z for z in spectra.renderer.canvas.zone_info
                   if z["device_key"] == key and z["zone_index"] == 0)["geometry"]
        assert geo["shape"] == "multi"

    def test_mapa_ilegivel_e_recusado(self, spectra):
        antes = dict(spectra.config.get("layout") or {})
        assert spectra.set_layout({"x": 1})["ok"] is False
        assert spectra.set_layout([1])["ok"] is False
        assert (spectra.config.get("layout") or {}) == antes

    def test_geometria_nula_volta_ao_automatico(self, spectra):
        key = self._plano(spectra)
        spectra.set_zone_geometry(key, 0, None)
        assert "0" not in spectra.config["layout"][key]["zones"]


class TestContagemManual:

    def test_campo_vazio_responde_o_que_digitar(self, spectra):
        key = spectra.state()["devices"][0]["key"]
        r = spectra.resize_zone(key, 0, None)
        assert r["ok"] is False
        assert "Digite" in r["error"]

    def test_fora_da_faixa_nao_e_gravado(self, spectra):
        key = spectra.state()["devices"][0]["key"]
        r = spectra.resize_zone(key, 0, 900)
        assert r["ok"] is False
        assert "a 512" in r["error"]
        assert spectra.client.zone_writes == []
        assert f"{key}:0" not in (spectra.config.get("zone_sizes") or {})

    def test_dentro_da_faixa_aplica(self, spectra):
        key = spectra.state()["devices"][0]["key"]
        assert spectra.resize_zone(key, 0, 12)["ok"] is True
        assert spectra.config["zone_sizes"][f"{key}:0"] == 12


class TestDispositivoForaDoControle:

    def test_recebe_preto_ao_sair_do_controle(self, spectra):
        r = spectra.renderer
        r.push(np.ones((r.canvas.n, 3), dtype=np.float32))
        assert set(spectra.client.last[1]) != {0}
        key = spectra.state()["devices"][1]["key"]
        spectra.update_settings({"enabled_devices": {key: False}})
        assert set(spectra.client.last[1]) == {0}

    def test_quem_segue_no_controle_nao_e_apagado(self, spectra):
        r = spectra.renderer
        r.push(np.ones((r.canvas.n, 3), dtype=np.float32))
        antes = spectra.client.last[0]
        key = spectra.state()["devices"][1]["key"]
        spectra.update_settings({"enabled_devices": {key: False}})
        assert spectra.client.last[0] == antes


class SensoresSemDll:
    """Fonte de sensores so com psutil, como na maquina sem a DLL."""

    def __init__(self, state, dll_path="", **_k):
        self.running = False
        self.psutil_ok = True
        self.lhm_ok = False
        self.available = []
        self.error = None
        self.lhm = types.SimpleNamespace(dll_path=dll_path, error="ausente")

    def start(self):
        self.running = True
        return True

    def stop(self):
        self.running = False

    def status(self):
        return {"running": self.running, "lhm": False, "available": [],
                "dll_path": self.lhm.dll_path}


class TestFonteQueNaoEntrega:

    def test_preset_de_temperatura_sem_dll_avisa(self, spectra, monkeypatch,
                                                 tmp_path):
        monkeypatch.setattr(app_mod, "SensorSource", SensoresSemDll)
        r = spectra.apply_preset("termometro")
        assert r["ok"] is True
        assert r["falhou"], "o termometro ficaria azul parado sem aviso"
        if sys.platform == "win32":
            assert str(tmp_path / "vendor") in r["falhou"][0]
        else:
            assert "temperatura" in r["falhou"][0]
        lid = spectra.renderer.layers[0].id
        assert "temperatura" in spectra.state()["avisos"][lid]

    def test_preset_de_uso_da_cpu_funciona_sem_dll(self, spectra, monkeypatch):
        monkeypatch.setattr(app_mod, "SensorSource", SensoresSemDll)
        assert spectra.apply_preset("carga")["falhou"] == []

    def test_captura_que_nao_abre_avisa_no_preset(self, spectra, monkeypatch):
        monkeypatch.setattr(app_mod, "AudioSource", FonteQueFalha)
        r = spectra.apply_preset("espectro")
        assert any("audio indisponivel" in m for m in r["falhou"])

    def test_trocar_dispositivo_que_falha_devolve_o_erro(self, spectra,
                                                         monkeypatch):
        # a fonte falsa vem antes da camada, senao a captura real abriria
        monkeypatch.setattr(app_mod, "AudioSource", FonteQueFalha)
        spectra.set_layers([{"effect": "audio_vu"}])
        r = spectra.set_source_config("audio", {"device": 3})
        assert r["ok"] is False
        assert "nao abriu" in r["error"]

    def test_fonte_que_nenhuma_camada_usa_so_guarda_a_escolha(self, spectra):
        r = spectra.set_source_config("screen", {"output": 1, "fps": 20})
        assert r == {"ok": True, "running": False, "em_uso": False}

    def test_vitrine_sabe_quais_presets_usam_temperatura(self, spectra):
        presets = {p["id"]: p for g in spectra.catalog()["presets"]
                   for p in g["presets"]}
        assert presets["termometro"]["sensores"] == ["cpu_temp"]
        assert presets["cpu_gpu"]["sensores"] == ["cpu_temp", "gpu_temp"]
        assert presets["carga"]["sensores"] == ["cpu_load"]
        assert presets["fogo"]["sensores"] == []

    def test_estado_mostra_onde_por_a_dll(self, spectra, tmp_path):
        s = spectra.state()["sources"]["sensors"]
        assert s["dll_dir"] == str(tmp_path / "vendor")
        assert s["dll_present"] is False


class TestFavoritosEInventario:

    def test_favoritos_ficam_na_configuracao(self, spectra, tmp_path):
        r = spectra.set_favoritos(["fogo", "nao_existe", "fogo", 3, "aurora"])
        assert r["favoritos"] == ["fogo", "aurora"]
        gravado = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
        assert gravado["favoritos"] == ["fogo", "aurora"]
        assert spectra.state()["favoritos"] == ["fogo", "aurora"]

    def test_inventario_fica_na_configuracao(self, spectra):
        itens = [{"id": "f", "label": "Fans", "kind": "fan", "pieces": 3}, "lixo"]
        assert spectra.set_inventario(itens)["ok"] is True
        assert spectra.state()["inventario"] == itens[:1]

    def test_formato_errado_e_recusado(self, spectra):
        assert spectra.set_favoritos("fogo")["ok"] is False
        assert spectra.set_inventario({"a": 1})["ok"] is False


class TestCamadasNaPosicao:

    def test_duplicar_poe_a_copia_logo_acima(self, spectra):
        spectra.set_layers([{"effect": "static", "id": i} for i in "abc"])
        nova = spectra.add_layer("static", acima_de="a")
        assert [l.id for l in spectra.renderer.layers] == ["a", nova["id"], "b", "c"]

    def test_sem_referencia_vai_para_o_topo(self, spectra):
        spectra.set_layers([{"effect": "static", "id": i} for i in "ab"])
        nova = spectra.add_layer("static")
        assert spectra.renderer.layers[-1].id == nova["id"]

    def test_trocar_efeito_troca_o_nome_que_era_do_efeito(self, spectra):
        L = spectra.add_layer("rainbow_wave")
        spectra.update_layer(L["id"], {"effect": "static"})
        assert (spectra.renderer.get_layer(L["id"]).name
                == app_mod.fx.get("static").label)

    def test_camada_da_cor_unica_troca_o_nome_junto(self, spectra):
        # a barra de cor unica nomeia a camada "Cor unica", com u minusculo
        spectra.set_layers([{"effect": "static", "id": "c", "name": "Cor unica"}])
        spectra.update_layer("c", {"effect": "rainbow_wave"})
        assert (spectra.renderer.get_layer("c").name
                == app_mod.fx.get("rainbow_wave").label)

    def test_nome_dado_pela_pessoa_fica(self, spectra):
        L = spectra.add_layer("rainbow_wave", name="Fundo do gabinete")
        spectra.update_layer(L["id"], {"effect": "static"})
        assert spectra.renderer.get_layer(L["id"]).name == "Fundo do gabinete"


class TestConcorrentes:

    def test_botao_de_fechar_agora_vale_com_o_automatico_desligado(
            self, spectra, monkeypatch):
        from spectra.core import exclusive
        chamadas = []

        def enforce():
            chamadas.append(1)
            return {"fechados": [], "falhou": [], "total": 0}

        monkeypatch.setattr(exclusive, "enforce", enforce)
        monkeypatch.setattr(exclusive, "minimize_openrgb", lambda: False)
        spectra.config["exclusive_mode"] = False
        assert spectra.enforce_exclusive()["skipped"] is True
        assert chamadas == []
        r = spectra.enforce_exclusive(forcar=True)
        assert chamadas == [1]
        assert "skipped" not in r


class TestMotivoDaConexao:

    def test_partida_automatica_desligada(self, spectra, monkeypatch):
        monkeypatch.setattr(app_mod, "_port_open", lambda *a, **k: False)
        spectra.config["autostart_openrgb"] = False
        assert spectra.ensure_openrgb() is False
        assert spectra.state()["motivo_conexao"] == "partida_desligada"

    def test_openrgb_nao_instalado(self, spectra, monkeypatch, tmp_path):
        from spectra.core import admin
        monkeypatch.setattr(app_mod, "_port_open", lambda *a, **k: False)
        monkeypatch.setattr(admin, "tarefa_existe", lambda nome: False)
        monkeypatch.setattr(app_mod, "OPENRGB_CANDIDATES",
                            [str(tmp_path / "nada" / "OpenRGB.exe")])
        assert spectra.ensure_openrgb() is False
        assert spectra.motivo_conexao == "nao_instalado"

    def test_erro_do_windows_nao_vai_para_a_barra(self, spectra, monkeypatch):
        monkeypatch.setattr(spectra, "ensure_openrgb", lambda **_: True)

        def recusa(timeout=4.0):
            raise ConnectionRefusedError(10061, "a maquina de destino as recusou")

        monkeypatch.setattr(spectra.client, "connect", recusa)
        assert spectra.connect() is False
        st = spectra.state()
        assert st["status"] == "sem conexao com o OpenRGB"
        assert "recusou" in st["erro_conexao"]
        assert st["motivo_conexao"] == "recusada"

    def test_caminho_do_openrgb_informado(self, spectra, tmp_path):
        exe = tmp_path / ("OpenRGB.exe" if sys.platform == "win32" else "openrgb")
        exe.write_bytes(b"")
        exe.chmod(0o755)
        assert spectra.set_openrgb_exe(f'"{exe}"')["ok"] is True
        assert spectra._openrgb_exe() == str(exe)

    def test_caminho_que_nao_e_o_openrgb_e_recusado(self, spectra, tmp_path):
        outro = tmp_path / "outro.exe"
        outro.write_bytes(b"")
        assert spectra.set_openrgb_exe(str(outro))["ok"] is False
        assert spectra.set_openrgb_exe(str(tmp_path / "OpenRGB.exe"))["ok"] is False
        assert "openrgb_exe" not in spectra.config


def _post(app, path, body=None):
    """Chama uma rota de escrita do servidor sem abrir porta nenhuma."""
    dados = json.dumps(body or {}).encode("utf-8")
    h = Handler.__new__(Handler)
    h.path = path
    h.headers = {"Host": "127.0.0.1:7311", "Content-Type": "application/json",
                 "Content-Length": str(len(dados))}
    h.rfile = io.BytesIO(dados)
    h.app = app
    saida = {}

    def _send(code, corpo, ctype=""):
        saida["code"], saida["body"] = code, json.loads(corpo.decode("utf-8"))

    h._send = _send
    Handler.do_POST(h)
    return saida["code"], saida["body"]


class TestRotas:

    def test_sem_conexao_responde_com_frase_e_nao_com_excecao(self, spectra):
        r, spectra.renderer = spectra.renderer, None
        try:
            code, body = _post(spectra, "/api/preset/apply", {"id": "fogo"})
        finally:
            spectra.renderer = r
        assert code == 503
        assert "NoneType" not in body["error"]
        assert "OpenRGB" in body["error"]

    def test_erro_inesperado_nao_mostra_o_nome_da_excecao(self, spectra,
                                                          monkeypatch):
        def quebra(*a, **k):
            raise RuntimeError("disco cheio")

        monkeypatch.setattr(spectra, "set_favoritos", quebra)
        code, body = _post(spectra, "/api/favoritos", {"ids": []})
        assert code == 500
        assert body["error"] == "Nao consegui concluir: disco cheio"

    def test_mostrar_janela_chama_quem_a_registrou(self, spectra):
        chamadas = []
        spectra.ao_mostrar_janela = lambda: chamadas.append(1)
        code, body = _post(spectra, "/api/janela/mostrar")
        assert body == {"ok": True}
        assert chamadas == [1]

    def test_sem_janela_diz_que_nao_mostrou(self, spectra):
        assert _post(spectra, "/api/janela/mostrar")[1] == {"ok": False}

    def test_restaurar_mapa_devolve_o_anterior(self, spectra):
        key = spectra.state()["devices"][0]["key"]
        spectra.set_zone_geometry(key, 0, {"shape": "line", "x1": 0.1,
                                           "y1": 0.5, "x2": 0.9, "y2": 0.5})
        code, body = _post(spectra, "/api/layout/reset")
        assert body["anterior"][key]["zones"]["0"]["shape"] == "line"
        code, body = _post(spectra, "/api/layout", {"layout": body["anterior"]})
        assert body == {"ok": True}

    def test_contagem_vazia_pela_rota(self, spectra):
        key = spectra.state()["devices"][0]["key"]
        code, body = _post(spectra, "/api/zone/resize",
                           {"device": key, "zone": 0, "size": None})
        assert body["ok"] is False
        assert "Digite" in body["error"]


class TestSegundaAbertura:

    def test_pede_a_janela_para_a_instancia_aberta(self, spectra):
        import run
        chamadas = []
        spectra.ao_mostrar_janela = lambda: chamadas.append(1)
        httpd = server_mod.serve(spectra, port=0)
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            assert run.pedir_janela(httpd.server_address[1]) is True
        finally:
            httpd.shutdown()
            httpd.server_close()
        assert chamadas == [1]

    def test_sem_instancia_ouvindo_cai_no_plano_antigo(self):
        import socket
        import run
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
        s.close()
        assert run.pedir_janela(porta) is False


class JanelaFalsa:

    def __init__(self):
        self.escondida = False

    def hide(self):
        self.escondida = True


class IconeFalso:

    def __init__(self):
        self.avisos = []

    def notify(self, msg, titulo=None):
        self.avisos.append(msg)


class TestBandeja:

    def _tray(self, spectra):
        t = Tray(JanelaFalsa(), spectra, lambda: None)
        t.icon = IconeFalso()
        return t

    def test_x_esconde_e_avisa_so_na_primeira_vez(self, spectra, monkeypatch):
        monkeypatch.setattr(tray_mod, "sessao_encerrando", lambda: False)
        t = self._tray(spectra)
        assert t.ao_fechar() is False
        assert t.window.escondida is True
        assert t.ao_fechar() is False
        assert len(t.icon.avisos) == 1
        assert spectra.config["aviso_bandeja"] is True

    def test_windows_desligando_fecha_de_verdade(self, spectra, monkeypatch):
        monkeypatch.setattr(tray_mod, "sessao_encerrando", lambda: True)
        t = self._tray(spectra)
        assert t.ao_fechar() is True
        assert t.window.escondida is False

    def test_fechamento_do_desligamento_nao_e_cancelado(self, spectra,
                                                        monkeypatch):
        # o tratador do pywebview ja cancelou porque o X esconde na bandeja;
        # o Windows perguntando se pode desligar tem que ouvir sim
        monkeypatch.setattr(tray_mod, "sessao_encerrando", lambda: False)
        t = self._tray(spectra)
        args = types.SimpleNamespace(CloseReason="WindowsShutDown", Cancel=True)
        t.ao_fechar_form(None, args)
        assert args.Cancel is False
        assert t.quitting is True

    def test_x_da_janela_continua_indo_para_a_bandeja(self, spectra):
        t = self._tray(spectra)
        args = types.SimpleNamespace(CloseReason="UserClosing", Cancel=True)
        t.ao_fechar_form(None, args)
        assert args.Cancel is True
        assert t.quitting is False

    def test_acender_volta_ao_brilho_de_antes(self, spectra):
        t = self._tray(spectra)
        spectra.update_settings({"brightness": 0.35})
        assert t._luz_label() == "Apagar LEDs"
        t._alternar_luz()
        assert spectra.renderer.settings["brightness"] == 0.0
        assert t._luz_label() == "Acender LEDs"
        t._alternar_luz()
        assert spectra.renderer.settings["brightness"] == 0.35


class TestAssistente:

    def test_estado_diz_que_o_assistente_ficou_aberto(self, spectra):
        assert spectra.state()["assistente_ativo"] is False
        spectra.probe_multi_start()
        assert spectra.state()["assistente_ativo"] is True
        spectra.probe_finish()
        assert spectra.state()["assistente_ativo"] is False

    def test_zonas_trazem_a_contagem_de_antes(self, spectra):
        r = spectra.probe_multi_start(probe_max=64)
        try:
            por_nome = {z["zone_name"]: z for z in r["zones"]}
            assert por_nome["ARGB 1"]["antes"] == 8
            assert por_nome["ARGB 1"]["max"] == 64
        finally:
            spectra.probe_finish()


class TempoRapido:
    """Relogio de verdade com as esperas zeradas, anotando cada uma.

    O app espera o controlador reaplicar a contagem e o servidor subir;
    nos testes isso so atrasaria a suite.
    """

    def __init__(self):
        self.esperas = []
        self.avanco = 0.0

    def sleep(self, s):
        self.esperas.append(s)
        self.avanco += s

    def monotonic(self):
        return time.monotonic() + self.avanco
    perf_counter = staticmethod(time.perf_counter)
    time = staticmethod(time.time)


@pytest.fixture
def sem_espera(monkeypatch):
    t = TempoRapido()
    monkeypatch.setattr(app_mod, "time", t)
    return t


def _leds(buf):
    """Bytes RGBA de uma zona como lista de triplas."""
    return [tuple(buf[i:i + 3]) for i in range(0, len(buf), 4)]


def _conta(spectra, dev, zona):
    d = next(x for x in spectra.renderer.all_devices if x.index == dev)
    return d.zones[zona].leds_count


BRANCO, AZUL = (255, 255, 255), (0, 110, 255)


class TestAssistenteDeLeds:
    """A descoberta de quantos LEDs cada conector ARGB tem."""

    @pytest.fixture
    def chave(self, spectra, sem_espera):
        return spectra.state()["devices"][0]["key"]

    def test_abrir_expande_os_conectores_e_guarda_a_contagem_de_antes(
            self, spectra, chave):
        r = spectra.probe_multi_start(probe_max=64)
        assert r["ok"] is True
        assert (_conta(spectra, 0, 0), _conta(spectra, 0, 1)) == (64, 64)
        assert spectra._probe_session["sizes"] == {f"{chave}:0": 8, f"{chave}:1": 4}
        assert spectra.renderer.settings["paused"] is True
        # a contagem de teste nao vai para o disco
        assert (spectra.config.get("zone_sizes") or {}) == {}

    def test_passo_acende_do_indice_ate_o_fim(self, spectra, chave):
        spectra.probe_multi_start(probe_max=16)
        r = spectra.probe_multi_paint([{"device": chave, "zone": 0, "index": 5,
                                        "color": "#ff0000"}])
        assert r["painted"] == [{"zone": "ARGB 1", "index": 5}]
        assert _leds(spectra.client.last[(0, 0)]) == [(0, 0, 0)] * 4 + [(255, 0, 0)] * 12

    def test_passo_sem_cauda_acende_um_so(self, spectra, chave):
        spectra.probe_multi_start(probe_max=16)
        spectra.probe_multi_paint([{"device": chave, "zone": 1, "index": 3,
                                    "tail": False}])
        cores = _leds(spectra.client.last[(0, 1)])
        assert [i for i, c in enumerate(cores) if c != (0, 0, 0)] == [2]
        assert cores[2] == BRANCO

    def test_passo_fora_da_zona_e_ignorado(self, spectra, chave):
        spectra.probe_multi_start(probe_max=16)
        r = spectra.probe_multi_paint([
            {"device": chave, "zone": 0, "index": 0},
            {"device": chave, "zone": 0, "index": 17},
            {"device": chave, "zone": 7, "index": 1},
            {"device": "sumiu#1", "zone": 0, "index": 1},
            {"device": chave, "zone": 1, "index": 16}])
        assert r["painted"] == [{"zone": "ARGB 2", "index": 16}]

    def test_passo_sem_sessao_aberta_e_recusado(self, spectra, chave):
        r = spectra.probe_multi_paint([{"device": chave, "zone": 0, "index": 1}])
        assert r["ok"] is False
        assert spectra.client.zone_writes == []

    def test_isolar_acende_so_o_trecho(self, spectra, chave):
        r = spectra.probe_isolate(chave, 0, 2, 3, "#00ff00")
        assert r == {"ok": True, "lit": 3}
        cores = _leds(spectra.client.last[(0, 0)])
        assert cores == [(0, 0, 0)] * 2 + [(0, 255, 0)] * 3 + [(0, 0, 0)] * 3

    def test_isolar_nao_passa_do_fim_da_zona(self, spectra, chave):
        assert spectra.probe_isolate(chave, 0, 6, 10)["lit"] == 2
        assert spectra.probe_isolate("sumiu#1", 0, 0, 1)["ok"] is False

    def test_divisao_pinta_cada_peca_de_uma_cor(self, spectra, chave):
        r = spectra.probe_split_preview(chave, 0, 3, 7)
        assert r == {"ok": True, "segments": 3}
        c = _leds(spectra.client.last[(0, 0)])
        assert c[0] == c[1] == c[2] != c[3]
        assert c[3] == c[4] == c[5] != c[6]
        assert c[6] != (0, 0, 0) and c[7] == (0, 0, 0)

    def test_divisao_de_zona_que_nao_existe(self, spectra, chave):
        assert spectra.probe_split_preview(chave, 9, 3, 7)["ok"] is False

    def test_concluir_grava_o_confirmado_e_devolve_o_resto(self, spectra, chave):
        spectra.probe_multi_start(probe_max=64)
        assert spectra.probe_commit(chave, 0, 10) == {"ok": True}
        r = spectra.probe_finish()
        assert r == {"ok": True, "applied": {f"{chave}:0": 10}}
        assert (_conta(spectra, 0, 0), _conta(spectra, 0, 1)) == (10, 4)
        assert spectra.config["zone_sizes"] == {f"{chave}:0": 10}
        assert spectra.renderer.settings["paused"] is False
        assert spectra.state()["assistente_ativo"] is False

    def test_conector_vazio_fica_gravado_como_zero(self, spectra, chave):
        spectra.probe_multi_start(probe_max=64)
        spectra.probe_commit(chave, 1, 0)
        spectra.probe_finish()
        assert _conta(spectra, 0, 1) == 0
        assert spectra.config["zone_sizes"] == {f"{chave}:1": 0}
        assert spectra.setup_todo()[0]["zone"] == 1

    def test_render_ja_pausado_continua_pausado(self, spectra, chave):
        spectra.renderer.settings["paused"] = True
        spectra.probe_multi_start()
        spectra.probe_finish()
        assert spectra.renderer.settings["paused"] is True

    def test_confirmar_sem_sessao_e_recusado(self, spectra, chave):
        assert spectra.probe_commit(chave, 0, 10)["ok"] is False
        assert spectra.probe_finish() == {"ok": True, "applied": {}}

    def test_sem_conector_ajustavel_avisa(self, spectra, chave, monkeypatch):
        monkeypatch.setattr(spectra, "resizable_zones", lambda: [])
        r = spectra.probe_multi_start()
        assert r["ok"] is False
        spectra.probe_finish()


class TestAssistenteDeUmaZona:
    """As rotas antigas, de uma zona por vez."""

    @pytest.fixture
    def chave(self, spectra, sem_espera):
        return spectra.state()["devices"][0]["key"]

    def test_comeca_acendendo_o_primeiro(self, spectra, chave):
        r = spectra.probe_start(chave, 0, 32)
        assert r == {"ok": True, "probe_max": 32}
        cores = _leds(spectra.client.last[(0, 0)])
        assert cores[0] == BRANCO and set(cores[1:]) == {(0, 0, 0)}

    def test_zona_fixa_ou_que_nao_existe_nao_comeca(self, spectra, chave):
        ram = spectra.state()["devices"][1]["key"]
        assert "fixo" in spectra.probe_start(ram, 0)["error"]
        assert spectra.probe_start("sumiu#1", 0)["ok"] is False
        assert spectra.probe_start(chave, 5)["ok"] is False
        assert getattr(spectra, "_probe_session", None) is None

    def test_encher_ate_a_contagem(self, spectra, chave):
        spectra.probe_start(chave, 0, 8)
        assert spectra.probe_paint(3) == {"ok": True, "count": 3, "of": 8}
        assert _leds(spectra.client.last[(0, 0)]) == (
            [AZUL, AZUL, BRANCO] + [(0, 0, 0)] * 5)

    def test_ponto_acende_so_a_posicao(self, spectra, chave):
        spectra.probe_start(chave, 0, 8)
        spectra.probe_paint(3, "dot")
        assert _leds(spectra.client.last[(0, 0)]) == (
            [(0, 0, 0)] * 2 + [BRANCO] + [(0, 0, 0)] * 5)

    def test_regua_marca_de_dez_em_dez(self, spectra, chave):
        spectra.probe_start(chave, 0, 25)
        spectra.probe_paint(0, "ruler")
        cores = _leds(spectra.client.last[(0, 0)])
        assert [i for i, c in enumerate(cores) if c == BRANCO] == [9, 19]
        assert cores[0] != cores[10] and cores[0] == cores[20]

    def test_contagem_alem_da_zona_para_no_fim(self, spectra, chave):
        spectra.probe_start(chave, 0, 8)
        assert spectra.probe_paint(99)["count"] == 8

    def test_parar_anota_e_concluir_grava(self, spectra, chave):
        spectra.probe_start(chave, 0, 32)
        assert spectra.probe_stop(commit=12) == {"ok": True, "committed": 12}
        assert spectra.probe_paint(1)["ok"] is False
        spectra.probe_finish()
        assert _conta(spectra, 0, 0) == 12
        assert _conta(spectra, 0, 1) == 4
        assert spectra.config["zone_sizes"] == {f"{chave}:0": 12}

    def test_parar_sem_nada_em_andamento(self, spectra, chave):
        assert spectra.probe_stop(5)["ok"] is False


class TestContagemEmLote:

    @pytest.fixture
    def chave(self, spectra, sem_espera):
        return spectra.state()["devices"][0]["key"]

    def test_diminuir_apaga_antes_os_leds_que_sobram(self, spectra, chave):
        # sem isso os LEDs de fora ficavam acesos na ultima cor para sempre
        r = spectra.resize_zones([(chave, 0, 5)])
        assert r == {"ok": True, "changed": True}
        assert spectra.client.zone_writes == [(0, 0, 8)]
        assert set(spectra.client.last[(0, 0)]) == {0}
        assert _conta(spectra, 0, 0) == 5

    def test_aumentar_nao_precisa_apagar(self, spectra, chave):
        spectra.resize_zones([(chave, 0, 20)])
        assert spectra.client.zone_writes == []
        assert spectra.renderer.canvas.n == 20 + 4 + 3

    def test_mesma_contagem_nao_recarrega(self, spectra, chave, sem_espera):
        assert spectra.resize_zones([(chave, 0, 8)]) == {"ok": True, "changed": False}
        assert sem_espera.esperas == []

    def test_uma_recarga_so_para_varias_zonas(self, spectra, chave, sem_espera,
                                               monkeypatch):
        cargas = []
        real = spectra.client.load_devices
        monkeypatch.setattr(spectra.client, "load_devices",
                            lambda: cargas.append(1) or real())
        spectra.resize_zones([(chave, 0, 10), (chave, 1, 6)])
        assert cargas == [1]
        assert sem_espera.esperas.count(0.6) == 1

    def test_erro_do_servidor_volta_como_frase(self, spectra, chave,
                                               monkeypatch):
        def recusa(i, zi, size):
            raise OpenRGBError("zona nao aceita esse tamanho")

        monkeypatch.setattr(spectra.client, "resize_zone", recusa)
        r = spectra.resize_zones([(chave, 0, 20)])
        assert r == {"ok": False, "error": "zona nao aceita esse tamanho"}
        assert f"{chave}:0" not in (spectra.config.get("zone_sizes") or {})

    def test_zona_que_nao_existe_e_pulada(self, spectra, chave):
        r = spectra.resize_zones([("sumiu#1", 0, 5), (chave, 9, 5)])
        assert r == {"ok": True, "changed": False}

    def test_zero_passa_no_conector_que_aceita(self, spectra, chave):
        assert spectra.resize_zone(chave, 1, 0)["ok"] is True
        assert spectra.config["zone_sizes"][f"{chave}:1"] == 0

    def test_texto_com_numero_e_aceito(self, spectra, chave):
        assert spectra.resize_zone(chave, 0, "12")["ok"] is True
        assert _conta(spectra, 0, 0) == 12


class TestPlanoDaZona:
    """Pecas de um conector viram geometria no mapa do gabinete."""

    @pytest.fixture
    def chave(self, spectra):
        return spectra.state()["devices"][0]["key"]

    def test_dois_fans_no_mesmo_lugar_nao_se_sobrepoem(self, spectra, chave):
        r = spectra.set_zone_plan(chave, 0, [
            {"kind": "fan", "count": 4, "spot": "topo_esq"},
            {"kind": "fan", "count": 4, "spot": "topo_esq"}])
        partes = r["geometry"]["parts"]
        assert r["geometry"]["shape"] == "multi"
        assert [p["shape"] for p in partes] == ["ring", "ring"]
        assert partes[0]["cx"] == app_mod.CASE_SPOTS["topo_esq"][0]
        assert partes[1]["cx"] == pytest.approx(partes[0]["cx"] + 0.16)
        assert partes[0]["cy"] == partes[1]["cy"]

    def test_muitas_pecas_no_mesmo_lugar_ficam_dentro_do_gabinete(self, spectra,
                                                                  chave):
        r = spectra.set_zone_plan(chave, 0, [
            {"kind": "fan", "count": 1, "spot": "topo_dir"} for _ in range(6)])
        xs = [p["cx"] for p in r["geometry"]["parts"]]
        assert all(0.04 <= x <= 0.96 for x in xs)
        assert xs[1] > xs[0] > xs[2]

    def test_fita_na_frente_fica_em_pe_e_no_topo_deitada(self, spectra, chave):
        r = spectra.set_zone_plan(chave, 0, [
            {"kind": "strip", "count": 4, "spot": "frente_meio"},
            {"kind": "strip", "count": 4, "spot": "topo_centro", "reverse": 1}])
        em_pe, deitada = r["geometry"]["parts"]
        assert em_pe["x1"] == em_pe["x2"] and em_pe["y1"] < em_pe["y2"]
        assert deitada["y1"] == deitada["y2"] and deitada["x1"] < deitada["x2"]
        assert deitada["reverse"] is True

    def test_cabo_leva_as_fileiras_e_a_ordem(self, spectra, chave):
        r = spectra.set_zone_plan(chave, 0, [
            {"kind": "cable", "count": 8, "spot": "traseira", "lanes": 4,
             "order": "along"}])
        g = r["geometry"]
        assert (g["shape"], g["lanes"], g["order"]) == ("cable", 4, "along")
        assert g["x1"] == g["x2"]
        assert "count" not in g

    def test_cabo_deitado_com_fileiras_padrao(self, spectra, chave):
        g = spectra.set_zone_plan(chave, 0, [
            {"kind": "cable", "count": 8, "spot": "gpu"}])["geometry"]
        assert g["y1"] == g["y2"] and g["lanes"] == 12

    def test_lugar_desconhecido_cai_no_meio(self, spectra, chave):
        g = spectra.set_zone_plan(chave, 0, [
            {"kind": "fan", "count": 8, "spot": "atras_da_tv"}])["geometry"]
        assert (g["cx"], g["cy"]) == app_mod.CASE_SPOTS["meio"]

    def test_peca_sem_led_e_pulada_e_plano_vazio_e_recusado(self, spectra,
                                                            chave):
        antes = dict(spectra.config.get("layout") or {})
        r = spectra.set_zone_plan(chave, 0, [{"kind": "fan", "count": 0},
                                             {"kind": "fan", "count": -2}])
        assert r == {"ok": False, "error": "plano vazio"}
        assert (spectra.config.get("layout") or {}) == antes

    def test_plano_vai_para_o_mapa_e_para_o_disco(self, spectra, chave, tmp_path):
        spectra.set_zone_plan(chave, 0, [{"kind": "fan", "count": 8,
                                          "spot": "gpu"}])
        gravado = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
        assert gravado["layout"][chave]["zones"]["0"]["shape"] == "ring"
        geo = next(z for z in spectra.renderer.canvas.zone_info
                   if z["device_key"] == chave and z["zone_index"] == 0)["geometry"]
        assert (geo["cx"], geo["cy"]) == app_mod.CASE_SPOTS["gpu"]


def _exe_openrgb(tmp_path):
    exe = tmp_path / "OpenRGB" / "OpenRGB.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    return str(exe)


class Windows:
    """Agendador, elevacao e processo trocados por falsos que anotam tudo."""

    def __init__(self, monkeypatch, tarefa=False, roda=False, criar="recusado",
                 popen_erro=None):
        from spectra.core import admin
        self.criadas, self.rodadas, self.abertos, self.encerrados = [], [], [], []
        self.tarefa, self.roda, self.criar = tarefa, roda, criar
        monkeypatch.setattr(admin, "tarefa_existe", lambda nome: self.tarefa)
        monkeypatch.setattr(admin, "rodar_tarefa",
                            lambda nome: self.rodadas.append(nome) or self.roda)
        monkeypatch.setattr(admin, "criar_tarefa", lambda nome, exe, args: (
            self.criadas.append((nome, exe, list(args))) or self.criar))
        monkeypatch.setattr(admin, "encerrar_openrgb",
                            lambda: self.encerrados.append(1) or True)

        def popen(args, **kw):
            if popen_erro:
                raise popen_erro
            self.abertos.append((list(args), kw.get("creationflags")))

        monkeypatch.setattr(app_mod, "subprocess",
                            types.SimpleNamespace(Popen=popen))


@pytest.mark.skipif(sys.platform != "win32", reason="partida elevada por tarefas do Windows")
class TestPartidaDoOpenRGB:
    """Subir o servidor gastando o menor numero de avisos do Windows."""

    @pytest.fixture
    def exe(self, spectra, tmp_path):
        spectra.config["openrgb_exe"] = _exe_openrgb(tmp_path)
        return spectra.config["openrgb_exe"]

    def test_tarefa_pronta_sobe_elevado_sem_aviso(self, spectra, exe,
                                                  monkeypatch):
        w = Windows(monkeypatch, tarefa=True, roda=True)
        assert spectra._start_openrgb() is True
        assert w.rodadas == [app_mod.OPENRGB_TASK]
        assert w.criadas == [] and w.abertos == []

    def test_sem_tarefa_cria_uma_vez_e_roda(self, spectra, exe, monkeypatch):
        w = Windows(monkeypatch, criar="ok", roda=True)
        assert spectra._start_openrgb() is True
        assert w.criadas == [(app_mod.OPENRGB_TASK, exe, app_mod.OPENRGB_ARGS)]
        assert w.abertos == []

    def test_aviso_recusado_nao_volta_a_perguntar(self, spectra, exe, tmp_path,
                                                  monkeypatch):
        w = Windows(monkeypatch, criar="recusado")
        assert spectra._start_openrgb() is True
        gravado = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
        assert gravado["elevar_openrgb"] is False
        assert spectra._start_openrgb() is True
        assert len(w.criadas) == 1
        assert len(w.abertos) == 2
        assert spectra.check_elevacao()["recusado"] is True

    def test_sem_elevacao_abre_o_executavel_solto_do_app(self, spectra, exe,
                                                         monkeypatch):
        w = Windows(monkeypatch, criar="erro")
        assert spectra._start_openrgb() is True
        args, flags = w.abertos[0]
        assert args == [exe] + app_mod.OPENRGB_ARGS
        # processo desanexado: fechar o Spectra nao derruba o servidor
        assert flags == 0x00000008 | 0x00000200
        assert spectra.config.get("elevar_openrgb", True) is True

    def test_tarefa_que_nao_roda_cai_no_executavel(self, spectra, exe,
                                                   monkeypatch):
        w = Windows(monkeypatch, tarefa=True, roda=False, criar="ok")
        assert spectra._start_openrgb() is True
        assert len(w.rodadas) == 2
        assert len(w.abertos) == 1

    def test_executavel_que_nao_abre_explica_o_motivo(self, spectra, exe,
                                                      monkeypatch):
        Windows(monkeypatch, criar="erro", popen_erro=OSError("acesso negado"))
        assert spectra._start_openrgb() is False
        assert spectra.motivo_conexao == "falha_partida"
        assert "acesso negado" in spectra.erro_conexao
        assert "acesso negado" in spectra.status_msg

    def test_caminho_informado_vem_antes_da_lista(self, spectra, exe, tmp_path,
                                                  monkeypatch):
        outro = tmp_path / "padrao.exe"
        outro.write_bytes(b"")
        monkeypatch.setattr(app_mod, "OPENRGB_CANDIDATES", [str(outro)])
        assert spectra._openrgb_exe() == exe
        spectra.config["openrgb_exe"] = str(tmp_path / "apagado" / "OpenRGB.exe")
        assert spectra._openrgb_exe() == str(outro)


class TestEsperaDoServidor:

    def _porta(self, monkeypatch, respostas):
        it = iter(respostas)
        monkeypatch.setattr(app_mod, "_port_open",
                            lambda *a, **k: next(it, respostas[-1]))

    def test_porta_aberta_nao_sobe_nada(self, spectra, monkeypatch):
        self._porta(monkeypatch, [True])
        monkeypatch.setattr(spectra, "_start_openrgb", lambda: pytest.fail(
            "subiu outro servidor com um no ar"))
        assert spectra.ensure_openrgb() is True

    def test_espera_o_servidor_subir(self, spectra, monkeypatch, sem_espera):
        self._porta(monkeypatch, [False, False, False, True])
        monkeypatch.setattr(spectra, "_start_openrgb", lambda: True)
        assert spectra.ensure_openrgb(wait=30.0) is True
        assert sem_espera.esperas == [0.5, 0.5]

    def test_servidor_que_nao_responde_a_tempo(self, spectra, monkeypatch):
        self._porta(monkeypatch, [False])
        monkeypatch.setattr(spectra, "_start_openrgb", lambda: True)
        assert spectra.ensure_openrgb(wait=0.0) is False
        assert spectra.motivo_conexao == "sem_resposta"
        assert spectra.status_msg == "OpenRGB nao respondeu a tempo"

    def test_partida_que_falhou_nao_fica_esperando(self, spectra, monkeypatch,
                                                   sem_espera):
        self._porta(monkeypatch, [False])
        monkeypatch.setattr(spectra, "_start_openrgb", lambda: False)
        assert spectra.ensure_openrgb(wait=30.0) is False
        assert sem_espera.esperas == []

    @pytest.mark.skipif(sys.platform != "win32", reason="consulta de processo pelo Windows")
    def test_openrgb_abrindo_nao_ganha_um_segundo(self, spectra, monkeypatch,
                                                  sem_espera):
        # no logon a tarefa antiga ja tinha aberto um, que leva uns cinco
        # segundos para abrir a porta; subir outro deixava os dois brigando
        from spectra.core import admin
        self._porta(monkeypatch, [False, False, True])
        monkeypatch.setattr(admin, "openrgb_rodando", lambda: True)
        monkeypatch.setattr(spectra, "_start_openrgb", lambda: pytest.fail(
            "subiu outro OpenRGB com um abrindo"))
        assert spectra.ensure_openrgb(wait=30.0) is True
        assert sem_espera.esperas == [0.5]

    @pytest.mark.skipif(sys.platform != "win32", reason="consulta de processo pelo Windows")
    def test_openrgb_abrindo_que_nunca_responde(self, spectra, monkeypatch):
        from spectra.core import admin
        self._porta(monkeypatch, [False])
        monkeypatch.setattr(admin, "openrgb_rodando", lambda: True)
        monkeypatch.setattr(spectra, "_start_openrgb", lambda: pytest.fail(
            "subiu outro OpenRGB com um abrindo"))
        assert spectra.ensure_openrgb(wait=0.0) is False
        assert spectra.motivo_conexao == "sem_resposta"

    def test_sem_poder_subir_nao_abre_o_openrgb(self, spectra, monkeypatch):
        self._porta(monkeypatch, [False])
        spectra.config["autostart_openrgb"] = True
        monkeypatch.setattr(spectra, "_start_openrgb", lambda: pytest.fail(
            "o vigia abriu o OpenRGB que a pessoa fechou"))
        assert spectra.ensure_openrgb(pode_subir=False) is False
        assert spectra.motivo_conexao == "servidor_fechado"

    def test_abertura_do_app_ainda_sobe(self, spectra, monkeypatch, sem_espera):
        self._porta(monkeypatch, [False, True])
        spectra.config["autostart_openrgb"] = True
        subidas = []
        monkeypatch.setattr(spectra, "_start_openrgb",
                            lambda: subidas.append(1) or True)
        assert spectra.ensure_openrgb() is True
        assert subidas == [1]


@pytest.mark.skipif(sys.platform != "win32", reason="reparo por tarefa agendada do Windows")
class TestReparoDaElevacao:

    @pytest.fixture
    def exe(self, spectra, tmp_path, sem_espera):
        spectra.config["openrgb_exe"] = _exe_openrgb(tmp_path)
        return spectra.config["openrgb_exe"]

    def _conectar(self, spectra, monkeypatch, ok=True):
        vistos = []
        monkeypatch.setattr(spectra, "connect",
                            lambda: vistos.append(spectra._reparando) or ok)
        return vistos

    def test_sem_openrgb_nao_ha_o_que_reparar(self, spectra, monkeypatch):
        monkeypatch.setattr(app_mod, "OPENRGB_CANDIDATES", [])
        assert spectra.reparar_elevacao() == {"ok": False,
                                              "erro": "OpenRGB nao encontrado"}

    @pytest.mark.parametrize("resposta, frase", [
        ("recusado", "o aviso de administrador foi recusado"),
        ("erro", "nao consegui criar a tarefa agendada")])
    def test_tarefa_nao_criada_nao_derruba_o_servidor(self, spectra, exe,
                                                      monkeypatch, resposta,
                                                      frase):
        w = Windows(monkeypatch, criar=resposta)
        r = spectra.reparar_elevacao()
        assert r["ok"] is False
        assert r["erro"] == frase
        assert w.encerrados == []
        assert spectra.connected is True

    def test_tarefa_que_nao_roda(self, spectra, exe, monkeypatch):
        w = Windows(monkeypatch, tarefa=True, roda=False)
        monkeypatch.setattr(app_mod, "_port_open", lambda *a, **k: False)
        r = spectra.reparar_elevacao()
        assert r["erro"] == "a tarefa agendada nao rodou"
        assert w.encerrados == [1]

    def test_troca_o_servidor_e_avisa_quando_a_ram_nao_aparece(
            self, spectra, exe, monkeypatch, sem_espera):
        w = Windows(monkeypatch, tarefa=True, roda=True)
        portas = iter([True, True, False, False, True])
        monkeypatch.setattr(app_mod, "_port_open", lambda *a, **k: next(portas))
        vistos = self._conectar(spectra, monkeypatch)
        r = spectra.reparar_elevacao()
        assert r["ok"] is True
        assert "PawnIO" in r["aviso"]
        assert w.encerrados == [1] and w.rodadas == [app_mod.OPENRGB_TASK]
        # espera o velho cair e o novo subir
        assert sem_espera.esperas == [0.3, 0.3, 0.5]
        # o vigia fica de fora durante a troca, e so durante
        assert vistos == [True]
        assert spectra._reparando is False
        assert spectra.connected is False

    def _troca_rapida(self, monkeypatch):
        """O servidor velho ja caiu e o novo sobe na primeira olhada."""
        portas = iter([False, True])
        monkeypatch.setattr(app_mod, "_port_open", lambda *a, **k: next(portas))

    def test_com_o_driver_o_aviso_nao_culpa_o_driver(self, spectra, exe,
                                                     monkeypatch):
        from spectra.core import admin
        Windows(monkeypatch, tarefa=True, roda=True)
        monkeypatch.setattr(admin, "pawnio_instalado", lambda: True)
        self._troca_rapida(monkeypatch)
        self._conectar(spectra, monkeypatch)
        r = spectra.reparar_elevacao()
        assert r["ok"] is True
        assert "nenhum pente" in r["aviso"]
        assert "PawnIO" not in r["aviso"]

    def test_ram_que_aparece_encerra_sem_aviso(self, spectra, exe, monkeypatch):
        Windows(monkeypatch, tarefa=True, roda=True)
        self._troca_rapida(monkeypatch)
        self._conectar(spectra, monkeypatch)
        spectra.renderer.all_devices[1].type = 1
        r = spectra.reparar_elevacao()
        assert r["ok"] is True
        assert "aviso" not in r
        assert r["elevacao"]["dram"] == 1


def _app_novo(monkeypatch, devices):
    """Um segundo app sobre a mesma configuracao, sem nada de verdade."""
    b = app_mod.SpectraApp()
    b.client = FakeClient(devices)
    monkeypatch.setattr(b, "ensure_openrgb", lambda **_: True)
    monkeypatch.setattr(b, "check_elevacao", lambda: {})
    monkeypatch.setattr(b, "_liga_teclado", lambda: None)
    monkeypatch.setattr(b, "start_watchdog", lambda: None)
    return b


class TestConexaoCompleta:

    @pytest.mark.skipif(sys.platform != "win32", reason="elevacao do OpenRGB no Windows")
    @pytest.mark.parametrize("reconexao", [False, True])
    def test_elevacao_conta_a_ram_da_lista_recem_carregada(
            self, spectra, monkeypatch, reconexao):
        devices = _bancada()
        devices[1].type = 1
        b = _app_novo(monkeypatch, devices)
        if reconexao:
            antigos = _bancada()
            b.renderer = Renderer(b.client, antigos)
        monkeypatch.setattr(b, "check_elevacao", lambda: (
            app_mod.SpectraApp.check_elevacao(b)))
        try:
            assert b.connect() is True
            assert b.elevacao["dram"] == 1
        finally:
            b.renderer.stop()

    @pytest.mark.parametrize("reconexao", [False, True])
    def test_conexao_reaplica_modo_direto_mesmo_quando_ja_informado(
            self, spectra, monkeypatch, reconexao):
        devices = _bancada()
        for device in devices:
            device.active_mode = device.direct_mode().index
        b = _app_novo(monkeypatch, devices)
        if reconexao:
            b.renderer = Renderer(b.client, _bancada())
        pedidos = []
        original = b.client.set_direct_mode
        b.client.set_direct_mode = lambda i: pedidos.append(i) or original(i)
        try:
            assert b.connect() is True
            assert pedidos == [0, 1]
        finally:
            b.renderer.stop()

    def test_contagem_salva_vale_antes_de_montar_o_mapa(self, spectra, tmp_path,
                                                        monkeypatch, sem_espera):
        mobo, ram = (d["key"] for d in spectra.state()["devices"])
        spectra.config["zone_sizes"] = {f"{mobo}:0": 20, f"{ram}:0": 10}
        spectra.save_config()
        b = _app_novo(monkeypatch, _bancada())
        pedidos = []
        real = b.client.resize_zone
        b.client.resize_zone = lambda i, zi, n: pedidos.append((i, zi, n)) or real(i, zi, n)
        try:
            assert b.connect() is True
            assert pedidos == [(0, 0, 20)]
            assert b.renderer.canvas.n == 20 + 4 + 3
        finally:
            b.renderer.stop()

    def test_servidor_ainda_detectando_espera_o_hardware(self, spectra,
                                                         monkeypatch, sem_espera):
        b = _app_novo(monkeypatch, _bancada())
        vazias = [[], []]
        real = b.client.load_devices
        b.client.load_devices = lambda: vazias.pop() if vazias else real()
        try:
            assert b.connect() is True
            assert sem_espera.esperas.count(1.5) == 2
            assert b.renderer.canvas.n == 15
            assert b.status_msg == "conectado"
        finally:
            b.renderer.stop()

    def test_descoberta_parcial_espera_placa_aparecer(self, spectra,
                                                       monkeypatch, sem_espera):
        monkeypatch.setattr(app_mod, "ESTABILIZACAO_DISPOSITIVOS", 3.0)
        devices = _bancada()
        b = _app_novo(monkeypatch, devices)
        listas = iter([devices[:1], devices, devices, devices])
        b.client.load_devices = lambda: next(listas)
        try:
            assert b.connect() is True
            assert [d.name for d in b.renderer.all_devices] == ["Mobo", "RAM"]
            assert len(sem_espera.esperas) == 3
        finally:
            b.renderer.stop()

    def test_lista_instavel_tem_prazo(self, spectra, monkeypatch, sem_espera):
        monkeypatch.setattr(app_mod, "ESTABILIZACAO_DISPOSITIVOS", 3.0)
        devices = _bancada()
        b = _app_novo(monkeypatch, devices)
        chamadas = []

        def lista_mutavel():
            chamadas.append(1)
            return devices[:1] if len(chamadas) % 2 else devices

        b.client.load_devices = lista_mutavel
        try:
            assert b.connect() is True
            assert 19.9 <= sum(sem_espera.esperas) <= 20.1
            assert len(chamadas) > 2
        finally:
            b.renderer.stop()

    def test_encerrar_interrompe_espera_de_descoberta(self, spectra,
                                                    monkeypatch, sem_espera):
        monkeypatch.setattr(app_mod, "ESTABILIZACAO_DISPOSITIVOS", 3.0)
        b = _app_novo(monkeypatch, _bancada())
        chamadas = []
        b.client.load_devices = lambda: chamadas.append(1) or b.client.devices
        sem_espera.sleep = lambda _: setattr(b, "_encerrando", True)
        assert b.connect() is False
        assert chamadas == [1]
        assert b.renderer is None

    def test_passagem_exclusiva_na_abertura(self, spectra, monkeypatch):
        from spectra.core import exclusive
        monkeypatch.setattr(exclusive, "enforce", lambda: {
            "fechados": [{"pid": 1, "processo": "iCUE.exe", "rotulo": "Corsair iCUE"}],
            "falhou": [], "total": 1})
        monkeypatch.setattr(exclusive, "minimize_openrgb", lambda: True)
        b = _app_novo(monkeypatch, _bancada())
        try:
            assert b.connect(exclusive_pass=True) is True
            assert b.last_exclusive["ao_iniciar"] is True
            assert b.last_exclusive["openrgb_minimizado"] is True
        finally:
            b.renderer.stop()

    def test_varredura_que_quebra_nao_impede_a_conexao(self, spectra,
                                                       monkeypatch):
        from spectra.core import exclusive

        def quebra():
            raise RuntimeError("tasklist sumiu")

        monkeypatch.setattr(exclusive, "enforce", quebra)
        b = _app_novo(monkeypatch, _bancada())
        try:
            assert b.connect(exclusive_pass=True) is True
            assert "tasklist sumiu" in b.last_error_exclusive
        finally:
            b.renderer.stop()

    def test_reconectar_mantem_a_cena_e_troca_o_cliente(self, spectra,
                                                        monkeypatch):
        spectra.set_layers([{"effect": "static", "id": "fica"}])
        r = spectra.renderer
        novo = FakeClient(_bancada())
        spectra.client = novo
        for nome, valor in (("ensure_openrgb", lambda **_: True),
                            ("check_elevacao", lambda: {}),
                            ("_liga_teclado", lambda: None),
                            ("start_watchdog", lambda: None)):
            monkeypatch.setattr(spectra, nome, valor)
        spectra.config["settings"]["gamma"] = 2.7
        r.connection_lost = True
        assert spectra.connect() is True
        assert spectra.renderer is r
        assert r.client is novo
        assert [l.id for l in r.layers] == ["fica"]
        assert r.settings["gamma"] == 2.7
        assert r.connection_lost is False

    def test_brilho_ilegivel_abre_aceso(self, spectra, tmp_path, monkeypatch):
        (tmp_path / "config.json").write_text(json.dumps({
            "settings": {"brightness": "muito"}, "brilho_aceso": 0.6}),
            encoding="utf-8")
        b = _app_novo(monkeypatch, _bancada())
        try:
            b.connect()
            assert b.renderer.settings["brightness"] == 0.6
        finally:
            b.renderer.stop()

    def test_motivo_de_antes_da_conexao_nao_e_trocado(self, spectra,
                                                      monkeypatch):
        def sem_openrgb(wait=25.0, pode_subir=True):
            spectra.motivo_conexao = "nao_instalado"
            return False

        def recusa(timeout=4.0):
            raise ConnectionRefusedError(10061, "recusou")

        monkeypatch.setattr(spectra, "ensure_openrgb", sem_openrgb)
        monkeypatch.setattr(spectra.client, "connect", recusa)
        assert spectra.connect() is False
        assert spectra.motivo_conexao == "nao_instalado"
        assert spectra.connected is False


class TestCenaDaAbertura:

    def _grava(self, tmp_path, **config):
        (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")

    def test_sem_cena_gravada_vale_o_ultimo_perfil_sem_o_brilho_dele(
            self, spectra, tmp_path, monkeypatch):
        spectra.set_layers([{"effect": "static", "id": "p"}])
        spectra.update_settings({"brightness": 0.3})
        spectra.save_profile("Noite")
        self._grava(tmp_path, last_profile="Noite",
                    settings={"brightness": 0.9, "gamma": 2.2, "fps": 60,
                              "smoothing": 0.0})
        b = _reabre(monkeypatch, _bancada)
        assert [l.id for l in b.renderer.layers] == ["p"]
        assert b.renderer.settings["brightness"] == 0.9
        st = b.state()
        assert (st["perfil_atual"], st["last_preset"]) == ("Noite", None)

    def test_cena_gravada_ilegivel_cai_no_perfil(self, spectra, tmp_path,
                                                 monkeypatch):
        spectra.set_layers([{"effect": "static", "id": "p"}])
        spectra.save_profile("Noite")
        self._grava(tmp_path, last_profile="Noite", cena={"layers": ["torto"]})
        b = _reabre(monkeypatch, _bancada)
        assert [l.id for l in b.renderer.layers] == ["p"]

    def test_perfil_que_sumiu_cai_no_preset_inicial(self, spectra, tmp_path,
                                                    monkeypatch):
        self._grava(tmp_path, last_profile="Apagado")
        b = _reabre(monkeypatch, _bancada)
        assert b.state()["last_preset"] == app_mod.PRESET_INICIAL


class FonteQueAnota:
    """Fonte ligada que conta as paradas, e pode quebrar ao parar."""

    def __init__(self, *_a, quebra=False, **kw):
        self.running = True
        self.error = None
        self.paradas = 0
        self.quebra = quebra
        self.kw = kw

    def start(self):
        self.running = True
        return True

    def stop(self):
        self.paradas += 1
        self.running = False
        if self.quebra:
            raise RuntimeError("driver de audio travou")


class TestEncerramento:

    def test_apaga_tudo_e_solta_o_teclado(self, spectra, tmp_path):
        spectra.teclado = TecladoFalso()
        spectra.audio = FonteQueAnota(quebra=True)
        spectra.screen = FonteQueAnota()
        spectra.renderer.push(np.ones((spectra.renderer.canvas.n, 3),
                                      dtype=np.float32))
        spectra.shutdown()
        assert all(set(c) == {0} for c in spectra.client.last.values())
        assert spectra.teclado.cores == [(0, 0, 0)]
        assert spectra.teclado.conectado is False
        assert spectra.screen.paradas == 1
        assert spectra._watchdog_stop.is_set()
        assert (tmp_path / "config.json").exists()

    def test_sem_apagar_deixa_a_luz_como_esta(self, spectra):
        spectra.teclado = TecladoFalso()
        spectra.shutdown(blank=False)
        assert spectra.client.last == {}
        assert spectra.teclado.cores == []
        assert spectra.teclado.conectado is False

    def test_falha_ao_gravar_nao_impede_de_apagar(self, spectra, monkeypatch):
        def cheio():
            raise OSError("disco cheio")

        monkeypatch.setattr(spectra, "save_config", cheio)
        spectra.shutdown()
        assert spectra.client.last and all(
            set(c) == {0} for c in spectra.client.last.values())


class TestFontesPelaCena:

    def test_tirar_a_camada_de_audio_para_a_captura(self, spectra):
        fonte = FonteQueAnota()
        spectra.audio = fonte
        spectra.set_layers([{"effect": "audio_vu"}])
        assert fonte.paradas == 0
        spectra.set_layers([{"effect": "static"}])
        assert fonte.paradas == 1

    def test_camada_desligada_nao_pede_fonte(self, spectra, monkeypatch):
        criadas = []
        monkeypatch.setattr(app_mod, "AudioSource",
                            lambda *a, **k: criadas.append(k) or FonteQueAnota())
        spectra.set_layers([{"effect": "audio_vu", "enabled": False}])
        assert criadas == []
        assert spectra.state()["needed"] == []

    def test_tela_abre_na_saida_e_taxa_escolhidas(self, spectra, monkeypatch):
        criadas = []
        monkeypatch.setattr(app_mod, "ScreenSource",
                            lambda st, **k: criadas.append(k) or FonteQueAnota())
        spectra.config["sources"]["screen"] = {"output": 1, "fps": 20}
        spectra.set_layers([{"effect": "screen_average"}])
        assert criadas == [{"output_idx": 1, "fps": 20}]

    def test_audio_abre_pelo_nome_guardado(self, spectra, monkeypatch):
        criadas = []
        monkeypatch.setattr(app_mod, "AudioSource",
                            lambda st, **k: criadas.append(k) or FonteQueAnota())
        spectra.config["sources"]["audio"] = {"device": 3, "nome": "Caixa"}
        spectra.set_layers([{"effect": "audio_vu"}])
        assert criadas == [{"device_index": 3, "device_name": "Caixa"}]

    def test_sensores_parados_quando_nenhuma_camada_usa(self, spectra):
        fonte = FonteQueAnota()
        spectra.sensors = fonte
        spectra.set_layers([{"effect": "static"}])
        assert fonte.paradas == 1

    def test_dll_na_pasta_de_configuracao_vem_primeiro(self, spectra, tmp_path,
                                                       monkeypatch):
        embutida = tmp_path / "app" / "vendor" / "LibreHardwareMonitorLib.dll"
        embutida.parent.mkdir(parents=True)
        embutida.write_bytes(b"")
        monkeypatch.setattr(app_mod, "VENDOR_DLL", str(embutida))
        assert app_mod._dll_sensores() == str(embutida)
        propria = tmp_path / "vendor" / "LibreHardwareMonitorLib.dll"
        propria.parent.mkdir()
        propria.write_bytes(b"")
        assert app_mod._dll_sensores() == str(propria)


class SensoresLigados:
    """Fonte de sensores de pe, com o que cada biblioteca entrega."""

    def __init__(self, dll_path, lhm_ok=False, available=(), erro=None):
        self.running = True
        self.psutil_ok = True
        self.lhm_ok = lhm_ok
        self.available = list(available)
        self.error = None
        self.lhm = types.SimpleNamespace(dll_path=dll_path, error=erro)

    def stop(self):
        self.running = False


class TestAvisosDeSensor:

    def _aviso(self, spectra, sensor):
        spectra.set_layers([{"effect": "temp_gradient", "id": "t",
                             "params": {"sensor": sensor}}])
        return spectra._avisos_das_camadas().get("t")

    @pytest.mark.skipif(sys.platform != "win32", reason="LibreHardwareMonitor e especifico do Windows")
    def test_dll_presente_que_nao_abriu_mostra_o_erro(self, spectra, tmp_path):
        dll = tmp_path / "LibreHardwareMonitorLib.dll"
        dll.write_bytes(b"")
        spectra.sensors = SensoresLigados(str(dll), erro="BadImageFormatException")
        aviso = self._aviso(spectra, "cpu_temp")
        assert "nao abriu" in aviso and "BadImageFormatException" in aviso

    def test_maquina_sem_a_leitura_diz_qual_falta(self, spectra, tmp_path):
        spectra.sensors = SensoresLigados(str(tmp_path / "x.dll"), lhm_ok=True,
                                          available=["cpu_temp", "cpu_load"])
        assert self._aviso(spectra, "gpu_load").startswith(
            "esta maquina nao informa uso da GPU")
        assert self._aviso(spectra, "cpu_temp") is None

    @pytest.mark.skipif(sys.platform != "win32", reason="LibreHardwareMonitor e especifico do Windows")
    def test_antes_da_primeira_leitura_vale_o_que_a_biblioteca_le(
            self, spectra, tmp_path):
        spectra.sensors = SensoresLigados(str(tmp_path / "x.dll"), lhm_ok=True)
        assert self._aviso(spectra, "gpu_temp") is None
        spectra.sensors = SensoresLigados(str(tmp_path / "x.dll"))
        assert "falta a LibreHardwareMonitorLib.dll" in self._aviso(spectra,
                                                                     "gpu_temp")
        assert self._aviso(spectra, "ram_load") is None

    def test_camada_desligada_nao_avisa(self, spectra):
        spectra.set_layers([{"effect": "audio_vu", "id": "a", "enabled": False}])
        assert spectra._avisos_das_camadas() == {}

    @pytest.mark.parametrize("efeito, params, esperado", [
        ("dual_sensor", {}, {"cpu_temp", "gpu_temp"}),
        ("temp_gradient", {"sensor": "gpu_temp"}, {"gpu_temp"}),
        ("temp_gradient", {"sensor": None}, {"cpu_temp"}),
        ("load_bar", None, {"cpu_load"}),
        ("static", {}, set()),
        ("nao_existe", {}, set()),
    ])
    def test_leituras_que_cada_camada_consome(self, efeito, params, esperado):
        assert app_mod.sensores_da_camada(efeito, params) == esperado


class TestBrilhoAceso:

    @pytest.mark.parametrize("gravado, esperado", [
        (0.4, 0.4), (None, 1.0), ("x", 1.0), (-2, 1.0), (7.5, 1.0)])
    def test_ultimo_brilho_aceso(self, spectra, gravado, esperado):
        spectra.config["brilho_aceso"] = gravado
        assert spectra._brilho_aceso() == esperado

    def test_apagar_nao_esquece_o_brilho_de_antes(self, spectra):
        spectra.update_settings({"brightness": 0.45})
        spectra.update_settings({"brightness": 0})
        spectra.update_settings({"brightness": "nada"})
        assert spectra.config["brilho_aceso"] == 0.45

    def test_fechados_na_varredura_aparecem_na_barra(self, spectra, monkeypatch):
        from spectra.core import exclusive
        monkeypatch.setattr(exclusive, "enforce", lambda: {"fechados": [
            {"rotulo": "SignalRGB"}, {"rotulo": "Corsair iCUE"},
            {"rotulo": "Corsair iCUE"}], "falhou": [], "total": 3})
        monkeypatch.setattr(exclusive, "minimize_openrgb", lambda: False)
        spectra.enforce_exclusive()
        assert spectra.status_msg == "fechei: Corsair iCUE, SignalRGB"

    def test_janela_que_falha_ao_mostrar(self, spectra):
        def quebra():
            raise RuntimeError("janela destruida")

        spectra.ao_mostrar_janela = quebra
        assert spectra.mostrar_janela() == {"ok": False}


class RelogioManual:
    """Relogio do app que so anda quando o teste manda."""

    def __init__(self):
        self.agora = 1000.0

    def monotonic(self):
        return self.agora

    def sleep(self, s):
        pass

    time = staticmethod(time.time)


class TestCorDoTeclado:

    @pytest.fixture
    def kb(self, spectra, monkeypatch):
        pytest.importorskip("spectra.core.akko", reason="modulo so existe no Windows")
        monkeypatch.setattr(spectra, "_sync_sources", lambda: None)
        spectra.teclado = TecladoFalso()
        spectra.config["akko_suavizacao"] = 0.0
        return spectra

    def _cor(self, app, cor, intensidade=1.0):
        app.set_layers([{"effect": "static",
                         "params": {"color": cor, "intensity": intensidade}}])
        app.renderer.ambiente(app.renderer.render_once(1 / 60))
        return app.teclado.cores[-1]

    def test_troca_de_cor_vem_aos_poucos(self, kb, monkeypatch):
        relogio = RelogioManual()
        monkeypatch.setattr(app_mod, "time", relogio)
        kb.config["akko_suavizacao"] = 1.0
        kb._liga_teclado()
        assert self._cor(kb, "#ff0000") == (255, 0, 0)
        relogio.agora += 0.5
        assert self._cor(kb, "#0000ff") == (128, 0, 128)
        relogio.agora += 1.0
        assert self._cor(kb, "#0000ff") == (0, 0, 255)

    def test_brilho_proprio_do_teclado(self, kb):
        kb.config["akko_brilho"] = 0.5
        kb._liga_teclado()
        assert self._cor(kb, "#00ff00") == (0, 128, 0)

    def test_cena_preta_apaga_o_teclado(self, kb):
        kb._liga_teclado()
        assert self._cor(kb, "#000000") == (0, 0, 0)

    def test_momento_mais_claro_vale_brilho_cheio(self, kb):
        # cada efeito tem o seu teto; sem o ganho, a cena media deixava o
        # teclado apagado
        kb._liga_teclado()
        assert self._cor(kb, "#ff0000", 0.5) == (255, 0, 0)
        escuro = self._cor(kb, "#ff0000", 0.25)
        assert 0 < escuro[0] < 128

    def test_piso_segura_um_minimo_de_luz(self, kb):
        kb._liga_teclado()
        self._cor(kb, "#ff0000")
        sem = self._cor(kb, "#ff0000", 0.2)[0]
        kb.config["akko_piso"] = 0.5
        kb._liga_teclado()
        self._cor(kb, "#ff0000")
        com = self._cor(kb, "#ff0000", 0.2)[0]
        assert com > sem + 60

    def test_teclado_que_falha_ao_religar_aparece_na_barra(self, kb,
                                                            monkeypatch):
        t = kb.teclado
        t.conectado = False

        def quebra():
            raise OSError("HID ocupado")

        monkeypatch.setattr(kb, "_liga_teclado", quebra)
        kb._teclado_proxima = 0.0
        kb._vigia_teclado()
        assert kb.status_msg == "teclado: HID ocupado"


def _get(app, path, host="127.0.0.1:7311"):
    """Chama uma rota de leitura do servidor sem abrir porta nenhuma."""
    h = Handler.__new__(Handler)
    h.path = path
    h.headers = {"Host": host}
    h.app = app
    saida = {}

    def _send(code, corpo, ctype="application/json; charset=utf-8"):
        saida.update(code=code, ctype=ctype, corpo=corpo)

    h._send = _send
    Handler.do_GET(h)
    if saida["ctype"].startswith("application/json"):
        saida["body"] = json.loads(saida["corpo"].decode("utf-8"))
    return saida


class TestRotasDeLeitura:

    def test_quadro_vem_em_hex_com_a_taxa(self, spectra):
        spectra.renderer.frame = spectra.renderer.render_once(1 / 60)
        spectra.renderer.fps_actual = 59.96
        r = _get(spectra, "/api/preview?t=123")
        assert r["code"] == 200
        assert r["body"]["hex"] == spectra.preview_hex()
        assert r["body"]["fps"] == 60.0
        assert r["body"]["src"] == {}

    def test_quadro_sem_conexao_nao_quebra(self, spectra):
        r, spectra.renderer = spectra.renderer, None
        try:
            assert _get(spectra, "/api/preview")["body"] == {"hex": "", "fps": 0,
                                                             "src": {}}
        finally:
            spectra.renderer = r

    def test_catalogo(self, spectra):
        body = _get(spectra, "/api/catalog")["body"]
        assert {"effects", "blends", "palettes", "presets", "spots"} <= set(body)

    def test_lista_de_audio_e_de_monitores(self, spectra, monkeypatch):
        from spectra.sources.audio import AudioSource
        from spectra.sources.screen import ScreenSource
        monkeypatch.setattr(AudioSource, "list_devices",
                            staticmethod(lambda: ([{"index": 9}], None)))
        monkeypatch.setattr(ScreenSource, "list_outputs",
                            staticmethod(lambda: ([], "sem dxcam")))
        assert _get(spectra, "/api/audio-devices")["body"] == {
            "devices": [{"index": 9}], "error": None}
        assert _get(spectra, "/api/screen-outputs")["body"] == {
            "outputs": [], "error": "sem dxcam"}

    def test_rota_de_api_que_nao_existe(self, spectra):
        r = _get(spectra, "/api/nada")
        assert r["code"] == 404
        assert r["body"] == {"error": "rota desconhecida"}

    def test_raiz_entrega_a_interface(self, spectra, tmp_path, monkeypatch):
        ui = tmp_path / "ui"
        (ui / "js").mkdir(parents=True)
        (ui / "index.html").write_text("<p>oi</p>", encoding="utf-8")
        (ui / "js" / "app.js").write_text("1", encoding="utf-8")
        assets = tmp_path / "assets"
        assets.mkdir()
        (assets / "logo.png").write_bytes(b"\x89PNG")
        monkeypatch.setattr(server_mod, "UI_DIR", str(ui))
        monkeypatch.setattr(server_mod, "ASSETS_DIR", str(assets))
        r = _get(spectra, "/")
        assert (r["code"], r["corpo"]) == (200, b"<p>oi</p>")
        assert r["ctype"] == "text/html; charset=utf-8"
        assert _get(spectra, "/js/app.js")["ctype"].endswith("; charset=utf-8")
        r = _get(spectra, "/assets/logo.png")
        assert (r["code"], r["ctype"], r["corpo"]) == (200, "image/png", b"\x89PNG")
        assert _get(spectra, "/assets/../ui/index.html")["code"] == 404
        assert _get(spectra, "/nao-existe.html")["code"] == 404


class AppQueAnota:
    """App falso que so anota qual metodo a rota chamou e com o que."""

    def __init__(self, com_motor=True):
        self.chamadas = []
        self.renderer = object() if com_motor else None
        self.config = {}
        self.teclado = None

    def __getattr__(self, nome):
        def anota(*a, **k):
            self.chamadas.append((nome, a, k))
            return {"de": nome}
        return anota


ROTAS = [
    ("/api/layers", {"layers": [1], "preset": None, "perfil": "N"},
     ("set_layers", ([1], None, "N"), {})),
    ("/api/layers", {"layers": []}, ("set_layers", ([], "keep", None), {})),
    ("/api/layer/add", {"effect": "static", "params": {"a": 1}, "acima_de": "x",
                        "lixo": 1},
     ("add_layer", ("static",), {"params": {"a": 1}, "acima_de": "x"})),
    ("/api/layer/update", {"id": "L", "patch": {"x": 1}},
     ("update_layer", ("L", {"x": 1}), {})),
    ("/api/layer/remove", {"id": "L"}, ("remove_layer", ("L",), {})),
    ("/api/layer/reorder", {"order": ["a"]}, ("reorder_layers", (["a"],), {})),
    ("/api/settings", {"gamma": 2.4}, ("update_settings", ({"gamma": 2.4},), {})),
    ("/api/zone/geometry", {"device": "D", "zone": "1", "geometry": None},
     ("set_zone_geometry", ("D", 1, None), {})),
    ("/api/zone/resize", {"device": "D", "zone": 2, "size": "10"},
     ("resize_zone", ("D", 2, "10"), {})),
    ("/api/layout/reset", {}, ("reset_layout", (), {})),
    ("/api/layout", {"layout": {"k": {}}}, ("set_layout", ({"k": {}},), {})),
    ("/api/source", {"kind": "audio", "config": {"device": 1}},
     ("set_source_config", ("audio", {"device": 1}), {})),
    ("/api/probe/start", {"device": "D", "zone": "0"},
     ("probe_start", ("D", 0, 256), {})),
    ("/api/probe/paint", {"count": "3"}, ("probe_paint", (3, "fill"), {})),
    ("/api/probe/stop", {"commit": 5}, ("probe_stop", (5,), {})),
    ("/api/probe/finish", {}, ("probe_finish", (), {})),
    ("/api/probe/commit", {"device": "D", "zone": 1, "count": "7"},
     ("probe_commit", ("D", 1, 7), {})),
    ("/api/probe/multi/start", {"max": 64}, ("probe_multi_start", (64,), {})),
    ("/api/probe/multi/paint", {"items": [1]}, ("probe_multi_paint", ([1],), {})),
    ("/api/probe/split", {"device": "D", "zone": 0, "size": 4, "total": 8},
     ("probe_split_preview", ("D", 0, 4, 8), {})),
    ("/api/probe/isolate", {"device": "D", "zone": 0, "start": 2, "count": 3},
     ("probe_isolate", ("D", 0, 2, 3, "#ffffff"), {})),
    ("/api/zone/identify", {"device": "D", "zone": 0},
     ("identify_zone", ("D", 0, 1.6, "#ffffff"), {})),
    ("/api/zone/plan", {"device": "D", "zone": 0, "parts": [1]},
     ("set_zone_plan", ("D", 0, [1]), {})),
    ("/api/preset/apply", {"id": "fogo"}, ("apply_preset", ("fogo",), {})),
    ("/api/profile/save", {"name": "N", "sobrescrever": 1},
     ("save_profile", ("N", True), {})),
    ("/api/profile/load", {"name": "N"}, ("load_profile", ("N",), {})),
    ("/api/profile/delete", {"name": "N"}, ("delete_profile", ("N",), {})),
    ("/api/favoritos", {"ids": ["a"]}, ("set_favoritos", (["a"],), {})),
    ("/api/inventario", {"itens": []}, ("set_inventario", ([],), {})),
    ("/api/openrgb/exe", {"path": "p"}, ("set_openrgb_exe", ("p",), {})),
    ("/api/elevacao/reparar", {}, ("reparar_elevacao", (), {})),
    ("/api/reconnect", {}, ("connect", (), {})),
]


class TestMapaDeRotas:
    """Cada rota de escrita chama o metodo certo, com os argumentos certos."""

    @pytest.mark.parametrize("path, corpo, esperado", ROTAS,
                             ids=[f"{r[0]}-{i}" for i, r in enumerate(ROTAS)])
    def test_rota_chama_o_metodo(self, path, corpo, esperado):
        app = AppQueAnota()
        code, _body = _post(app, path, corpo)
        assert code == 200
        assert app.chamadas[0] == esperado

    @pytest.mark.parametrize("path", sorted(server_mod.PRECISA_MOTOR))
    def test_rota_do_motor_sem_motor_nem_chega_ao_app(self, path):
        app = AppQueAnota(com_motor=False)
        code, body = _post(app, path, {"id": "x"})
        assert code == 503
        assert app.chamadas == []

    def test_rota_de_configuracao_funciona_antes_da_conexao(self):
        app = AppQueAnota(com_motor=False)
        code, _ = _post(app, "/api/source", {"kind": "screen", "config": {}})
        assert code == 200
        assert app.chamadas[0][0] == "set_source_config"

    def test_parametro_faltando_diz_qual(self):
        code, body = _post(AppQueAnota(), "/api/layer/remove", {})
        assert code == 400
        assert body["error"] == "parametro faltando: 'id'"

    def test_corpo_que_nao_e_json_e_recusado(self):
        h = Handler.__new__(Handler)
        h.headers = {"Content-Length": "5"}
        h.rfile = io.BytesIO(b"{oops")
        with pytest.raises(server_mod.PedidoInvalido, match="JSON invalido"):
            Handler._body(h)
        h.headers = {}
        assert Handler._body(h) == {}

    def test_rota_de_escrita_que_nao_existe(self):
        app = AppQueAnota()
        code, body = _post(app, "/api/apagar-tudo", {})
        assert code == 404
        assert app.chamadas == []

    def test_modo_exclusivo_grava_a_chave_e_varre(self):
        app = AppQueAnota()
        _post(app, "/api/exclusive", {"enabled": 0, "forcar": 1})
        assert app.config["exclusive_mode"] is False
        assert [c[0] for c in app.chamadas] == ["save_config", "enforce_exclusive"]
        assert app.chamadas[1][1] == (True,)

    def test_so_varrer_nao_mexe_na_chave(self):
        app = AppQueAnota()
        _post(app, "/api/exclusive", {})
        assert app.config == {}
        assert app.chamadas == [("enforce_exclusive", (False,), {})]

    def test_teclado_desligado_pela_rota(self):
        app = AppQueAnota()
        code, body = _post(app, "/api/teclado", {"enabled": False})
        assert body == {"ok": True, "teclado": None}
        assert app.config["akko_keyboard"] is False
        assert [c[0] for c in app.chamadas] == ["save_config", "_liga_teclado"]

    def test_teclado_sem_motor_so_grava(self):
        app = AppQueAnota(com_motor=False)
        _post(app, "/api/teclado", {"enabled": True})
        assert [c[0] for c in app.chamadas] == ["save_config"]

    def test_encerrar_responde_antes_de_derrubar_o_servidor(self):
        app = AppQueAnota()
        caiu = threading.Event()
        dados = b"{}"
        h = Handler.__new__(Handler)
        h.path = "/api/shutdown"
        h.headers = {"Host": "127.0.0.1:7311", "Content-Type": "application/json",
                     "Content-Length": str(len(dados))}
        h.rfile = io.BytesIO(dados)
        h.app = app
        h.server = types.SimpleNamespace(shutdown=caiu.set)
        respostas = []
        h._send = lambda code, corpo, ctype="": respostas.append(
            (code, json.loads(corpo)))
        Handler.do_POST(h)
        assert respostas == [(200, {"ok": True})]
        assert caiu.wait(2)

    def test_pedido_de_outro_site_nao_chega_ao_app(self):
        app = AppQueAnota()
        h = Handler.__new__(Handler)
        h.path = "/api/layer/remove"
        h.headers = {"Host": "127.0.0.1:7311", "Origin": "http://mal.invalido",
                     "Content-Type": "application/json", "Content-Length": "2"}
        h.rfile = io.BytesIO(b"{}")
        h.app = app
        respostas = []
        h._send = lambda code, corpo, ctype="": respostas.append(code)
        Handler.do_POST(h)
        assert respostas == [403]
        assert app.chamadas == []


class SaidaQueCai:
    """Conexao do navegador que fecha depois de algumas mensagens."""

    def __init__(self, aguenta):
        self.aguenta = aguenta
        self.escritos = []

    def write(self, dados):
        if len(self.escritos) >= self.aguenta:
            raise ConnectionAbortedError("aba fechada")
        self.escritos.append(dados)

    def flush(self):
        pass


class TestFluxoDoQuadro:

    def _handler(self, app, saida):
        h = Handler.__new__(Handler)
        h.app = app
        h.wfile = saida
        h.cabecalhos = []
        h.send_response = lambda code: h.cabecalhos.append(code)
        h.send_header = lambda k, v: h.cabecalhos.append((k, v))
        h.end_headers = lambda: None
        return h

    def test_manda_o_quadro_quando_muda_e_para_quando_a_aba_fecha(
            self, spectra, monkeypatch):
        quadros = iter(["aa", "aa", "bb", "cc"])
        monkeypatch.setattr(spectra, "preview_hex", lambda: next(quadros, "zz"))
        saida = SaidaQueCai(aguenta=2)
        h = self._handler(spectra, saida)
        Handler._stream(h)
        assert h.close_connection is True
        assert ("Content-Type", "text/event-stream; charset=utf-8") in h.cabecalhos
        msgs = [json.loads(e[len(b"data: "):-2]) for e in saida.escritos]
        assert [m["h"] for m in msgs] == ["aa", "bb"]
        assert all(e.startswith(b"data: ") and e.endswith(b"\n\n")
                   for e in saida.escritos)
        assert msgs[0]["src"] == {}

    def test_resposta_para_aba_que_fechou_nao_estoura(self):
        h = Handler.__new__(Handler)
        h.wfile = SaidaQueCai(aguenta=0)
        h.send_response = lambda code: None
        h.send_header = lambda k, v: None
        h.end_headers = lambda: None
        Handler._send(h, 200, b"{}")


class IconeQueAnota:

    def __init__(self, quebra=False):
        self.paradas = 0
        self.quebra = quebra

    def stop(self):
        self.paradas += 1
        if self.quebra:
            raise RuntimeError("bandeja ja fechada")

    def notify(self, msg, titulo=None):
        raise OSError("notificacoes desligadas")


class JanelaQueAnota:

    def __init__(self, quebra=False):
        self.chamadas = []
        self.quebra = quebra

    def show(self):
        if self.quebra:
            raise RuntimeError("janela destruida")
        self.chamadas.append("show")

    def restore(self):
        self.chamadas.append("restore")


class TestBandejaMenu:

    def test_status_sem_conexao_e_conectado(self, spectra):
        t = Tray(None, spectra, lambda: None)
        spectra.renderer.fps_actual = 59.6
        assert t._status() == f"{spectra.renderer.canvas.n} LEDs · 60 fps"
        spectra.connected = False
        assert t._status() == "Sem conexao com o OpenRGB"

    def test_sair_para_o_icone_e_encerra_mesmo_com_erro(self, spectra):
        saiu = []
        t = Tray(None, spectra, lambda: saiu.append(1))
        t.icon = IconeQueAnota(quebra=True)
        t._sair()
        assert t.quitting is True
        assert t.icon.paradas == 1
        assert saiu == [1]

    def test_abrir_mostra_e_restaura_a_janela(self, spectra):
        j = JanelaQueAnota()
        Tray(j, spectra, lambda: None)._mostrar()
        assert j.chamadas == ["show", "restore"]
        Tray(JanelaQueAnota(quebra=True), spectra, lambda: None)._mostrar()

    def test_sem_icone_o_x_fecha_de_verdade(self, spectra, monkeypatch):
        monkeypatch.setattr(tray_mod, "sessao_encerrando", lambda: False)
        t = Tray(JanelaFalsa(), spectra, lambda: None)
        assert t.ao_fechar() is True
        assert t.quitting is True
        assert t.window.escondida is False

    def test_depois_de_sair_o_x_nao_esconde_mais(self, spectra, monkeypatch):
        monkeypatch.setattr(tray_mod, "sessao_encerrando", lambda: False)
        t = Tray(JanelaFalsa(), spectra, lambda: None)
        t.icon = IconeFalso()
        t.quitting = True
        assert t.ao_fechar() is True
        assert t.window.escondida is False

    def test_aviso_que_nao_sai_tenta_de_novo_na_proxima(self, spectra,
                                                         monkeypatch):
        monkeypatch.setattr(tray_mod, "sessao_encerrando", lambda: False)
        t = Tray(JanelaFalsa(), spectra, lambda: None)
        t.icon = IconeQueAnota()
        assert t.ao_fechar() is False
        assert "aviso_bandeja" not in spectra.config

    def test_sem_conexao_o_botao_de_luz_nao_faz_nada(self, spectra, monkeypatch):
        chamadas = []
        monkeypatch.setattr(spectra, "update_settings", chamadas.append)
        r, spectra.renderer = spectra.renderer, None
        try:
            t = Tray(None, spectra, lambda: None)
            t._alternar_luz()
            assert t._luz_label() == "Apagar LEDs"
        finally:
            spectra.renderer = r
        assert chamadas == []

    def test_brilho_ilegivel_conta_como_aceso(self, spectra):
        spectra.renderer.settings["brightness"] = "x"
        assert Tray(None, spectra, lambda: None)._apagado() is False

    def test_tirar_da_bandeja_engole_erro(self, spectra):
        t = Tray(None, spectra, lambda: None)
        t.icon = IconeQueAnota(quebra=True)
        t.stop()
        assert t.icon.paradas == 1


class TestCamadasPelaInterface:

    def test_tirar_a_camada_de_audio_solta_a_captura(self, spectra):
        fonte = FonteQueAnota()
        spectra.audio = fonte
        spectra.set_layers([{"effect": "static", "id": "s"},
                            {"effect": "audio_vu", "id": "a"}])
        spectra.remove_layer("a")
        assert [l.id for l in spectra.renderer.layers] == ["s"]
        assert fonte.paradas == 1

    def test_mudar_o_alvo_vale_no_quadro_seguinte(self, spectra):
        ram = spectra.state()["devices"][1]["key"]
        spectra.set_layers([{"effect": "static", "id": "c",
                             "params": {"color": "#ff0000"}}])
        r = spectra.renderer
        assert r.render_once(1 / 60)[:, 0].all()
        spectra.update_layer("c", {"targets": [ram]})
        q = r.render_once(1 / 60)
        assert int((q[:, 0] > 0).sum()) == 3
        spectra.update_layer("c", {"targets": None})
        assert r.render_once(1 / 60)[:, 0].all()

    def test_blend_e_nome_mudam_sem_trocar_o_resto(self, spectra):
        spectra.set_layers([{"effect": "static", "id": "c",
                             "params": {"color": "#00ff00"}}])
        out = spectra.update_layer("c", {"blend": "add", "name": "Verde"})
        assert (out["blend"], out["name"]) == ("add", "Verde")
        assert out["params"] == {"color": "#00ff00"}

    def test_trocar_de_efeito_limpa_parametros_e_memoria(self, spectra):
        spectra.set_layers([{"effect": "rainbow_wave", "id": "c",
                             "params": {"speed": 0.9}}])
        camada = spectra.renderer.get_layer("c")
        camada.state["fase"] = 3.0
        spectra.update_layer("c", {"effect": "static"})
        assert camada.params == {} and camada.state == {}

    def test_camada_que_nao_existe(self, spectra):
        assert spectra.update_layer("nada", {"opacity": 0.2}) is None


class TestVigiaDaConexao:

    def _sem_reconectar(self, spectra, monkeypatch):
        tentativas = []
        monkeypatch.setattr(spectra, "_connect",
                            lambda exclusive_pass, pode_subir=True:
                            tentativas.append(1) or True)
        return tentativas

    def test_conexao_saudavel_nao_reconecta(self, spectra, monkeypatch):
        tentativas = self._sem_reconectar(spectra, monkeypatch)
        spectra.renderer.start()
        try:
            spectra._watchdog_stop = ParadaDepoisDe(2)
            spectra._watchdog_loop()
        finally:
            spectra.renderer.stop()
        assert tentativas == []

    @pytest.mark.parametrize("motivo", ["assistente", "reparo", "conectando"])
    def test_quem_mexe_na_conexao_de_proposito_segura_o_vigia(
            self, spectra, monkeypatch, motivo):
        tentativas = self._sem_reconectar(spectra, monkeypatch)
        if motivo == "assistente":
            spectra._probe_session = {"sizes": {}, "commits": {}}
        elif motivo == "reparo":
            spectra._reparando = True
        else:
            spectra.connecting = True
        spectra._watchdog_stop = ParadaDepoisDe(2)
        spectra._watchdog_loop()
        assert tentativas == []
        spectra._probe_session = None

    def test_vigia_reconecta_sem_abrir_o_openrgb(self, spectra, monkeypatch):
        pedidos = []
        monkeypatch.setattr(spectra, "_connect",
                            lambda exclusive_pass, pode_subir=True:
                            pedidos.append(pode_subir) or False)
        spectra.renderer.connection_lost = True
        spectra._watchdog_stop = ParadaDepoisDe(2)
        spectra._watchdog_loop()
        assert pedidos == [False, False]

    def test_sem_motor_so_espera(self, spectra, monkeypatch):
        tentativas = self._sem_reconectar(spectra, monkeypatch)
        r, spectra.renderer = spectra.renderer, None
        try:
            spectra._watchdog_stop = ParadaDepoisDe(2)
            spectra._watchdog_loop()
        finally:
            spectra.renderer = r
        assert tentativas == []

    def test_reconexao_conta_e_avisa(self, spectra, monkeypatch):
        tentativas = self._sem_reconectar(spectra, monkeypatch)
        spectra._watchdog_stop = ParadaDepoisDe(1)
        spectra._watchdog_loop()
        assert tentativas == [1]
        assert spectra.reconnects == 1
        assert spectra.status_msg == "reconectado (1x)"

    def test_gravacao_que_falha_nao_mata_o_vigia(self, spectra, monkeypatch):
        tentativas = self._sem_reconectar(spectra, monkeypatch)

        def cheio():
            raise OSError("disco cheio")

        monkeypatch.setattr(spectra, "save_config", cheio)
        spectra._gravar_pendente = True
        spectra._watchdog_stop = ParadaDepoisDe(2)
        spectra._watchdog_loop()
        assert len(tentativas) == 2

    def test_vigia_sobe_uma_vez_so(self, spectra):
        spectra.start_watchdog()
        t = spectra._watchdog
        try:
            spectra.start_watchdog()
            assert spectra._watchdog is t
            assert t.is_alive()
        finally:
            spectra._watchdog_stop.set()
            t.join(2)
        assert not t.is_alive()


class TestFalhasDoServidorNoMeio:
    """O OpenRGB recusando um pedido no meio de uma operacao."""

    def _recusa(self, *a, **k):
        raise OpenRGBError("dispositivo nao respondeu")

    def test_contagem_salva_recusada_nao_recarrega(self, spectra, monkeypatch,
                                                   sem_espera):
        key = spectra.state()["devices"][0]["key"]
        spectra.config["zone_sizes"] = {f"{key}:0": 20}
        monkeypatch.setattr(spectra.client, "resize_zone", self._recusa)
        monkeypatch.setattr(spectra.client, "load_devices",
                            lambda: pytest.fail("recarregou sem ter mudado"))
        devices = list(spectra.renderer.all_devices)
        spectra._apply_zone_sizes(devices)
        assert devices == spectra.renderer.all_devices
        assert sem_espera.esperas == []

    def test_recarga_que_falha_mantem_a_lista_de_antes(self, spectra,
                                                       monkeypatch, sem_espera):
        key = spectra.state()["devices"][0]["key"]
        spectra.config["zone_sizes"] = {f"{key}:0": 20}
        monkeypatch.setattr(spectra.client, "load_devices", self._recusa)
        devices = list(spectra.renderer.all_devices)
        spectra._apply_zone_sizes(devices)
        assert len(devices) == 2

    def test_recarga_depois_de_mudar_a_contagem(self, spectra, monkeypatch,
                                                sem_espera):
        key = spectra.state()["devices"][0]["key"]
        monkeypatch.setattr(spectra.client, "load_devices", self._recusa)
        r = spectra.resize_zones([(key, 0, 20)])
        assert r == {"ok": False, "error": "dispositivo nao respondeu"}

    def test_apagar_antes_de_diminuir_pode_falhar(self, spectra, monkeypatch,
                                                  sem_espera):
        key = spectra.state()["devices"][0]["key"]
        monkeypatch.setattr(spectra.client, "update_zone_leds", self._recusa)
        assert spectra.resize_zones([(key, 0, 4)])["ok"] is True
        assert _conta(spectra, 0, 0) == 4

    def test_brilho_com_render_pausado_e_servidor_caido(self, spectra,
                                                        monkeypatch):
        r = spectra.renderer
        r.frame = r.render_once(1 / 60)
        r.settings["paused"] = True
        monkeypatch.setattr(spectra.client, "update_leds", self._recusa)

        def teclado_quebrado(q):
            raise RuntimeError("teclado sumiu")

        r.ambiente = teclado_quebrado
        spectra.update_settings({"brightness": 0.5})
        assert r.settings["brightness"] == 0.5
        assert spectra.config["brilho_aceso"] == 0.5

    def test_desligar_dispositivo_com_servidor_caido(self, spectra, monkeypatch):
        key = spectra.state()["devices"][1]["key"]
        monkeypatch.setattr(spectra.client, "update_leds", self._recusa)
        spectra.update_settings({"enabled_devices": {key: False}})
        assert spectra.config["enabled_devices"] == {key: False}

    def test_passo_do_assistente_recusado_volta_como_frase(self, spectra,
                                                           monkeypatch,
                                                           sem_espera):
        key = spectra.state()["devices"][0]["key"]
        spectra.probe_start(key, 0, 16)
        monkeypatch.setattr(spectra.client, "update_zone_leds", self._recusa)
        assert spectra.probe_paint(4) == {"ok": False,
                                          "error": "dispositivo nao respondeu"}
        spectra.probe_finish()


class TestAssistenteEmAndamento:

    @pytest.fixture
    def chave(self, spectra, sem_espera):
        return spectra.state()["devices"][0]["key"]

    def test_segunda_zona_usa_a_mesma_sessao(self, spectra, chave):
        spectra.probe_start(chave, 0, 16)
        sessao = spectra._probe_session
        spectra.probe_stop(commit=9)
        assert spectra.probe_start(chave, 1, 64)["probe_max"] == 16
        assert spectra._probe_session is sessao
        spectra.probe_stop(commit=5)
        assert spectra.probe_finish()["applied"] == {f"{chave}:0": 9,
                                                     f"{chave}:1": 5}

    def test_dispositivo_que_sumiu_no_meio(self, spectra, chave):
        spectra.probe_start(chave, 0, 16)
        spectra._probe["device"] = "sumiu#1"
        assert spectra.probe_paint(2) == {"ok": False, "error": "device sumiu"}
        spectra.probe_finish()


class TestSemConexaoAinda:
    """O estado e as consultas antes da primeira conexao com o OpenRGB."""

    @pytest.fixture
    def sem_motor(self, spectra):
        r, spectra.renderer = spectra.renderer, None
        yield spectra
        spectra.renderer = r

    def test_estado_vem_vazio_e_serializavel(self, sem_motor):
        st = sem_motor.state()
        assert (st["devices"], st["layers"]) == ([], [])
        assert "canvas" not in st
        json.dumps(st)

    def test_consultas_nao_quebram(self, sem_motor):
        assert sem_motor.preview() == []
        assert sem_motor.resizable_zones() == []
        assert sem_motor.live_sources() == {}
        assert sem_motor.identify_zone("x", 0)["ok"] is False


class TestFontesNoEstado:

    def test_audio_ligado_mostra_o_dispositivo(self, spectra):
        spectra.audio = types.SimpleNamespace(running=True, error=None,
                                              device_name="Caixa [Loopback]")
        spectra.screen = types.SimpleNamespace(running=False, error="sem dxcam",
                                               actual_fps=29.94)
        src = spectra.state()["sources"]
        assert src["audio"]["device_name"] == "Caixa [Loopback]"
        assert src["screen"] == {"running": False, "error": "sem dxcam",
                                 "config": {"output": 0, "fps": 30}, "fps": 29.9}

    def test_trocar_para_dispositivo_que_abre(self, spectra, monkeypatch):
        monkeypatch.setattr(app_mod, "AudioSource",
                            lambda *a, **k: FonteQueAnota())
        spectra.set_layers([{"effect": "audio_vu"}])
        r = spectra.set_source_config("audio", {"device": 2})
        assert r == {"ok": True, "running": True, "em_uso": True}

    def test_preset_que_nao_existe(self, spectra):
        antes = [l.id for l in spectra.renderer.layers]
        assert spectra.apply_preset("nao_existe") == {
            "ok": False, "error": "preset desconhecido"}
        assert [l.id for l in spectra.renderer.layers] == antes

    @pytest.mark.parametrize("nome", ["!!!", "   ", "../"])
    def test_nome_de_perfil_sem_letra_e_recusado(self, spectra, tmp_path, nome):
        assert spectra.save_profile(nome) == {"ok": False, "error": "nome invalido"}
        assert list((tmp_path / "profiles").iterdir()) == []

    @pytest.mark.parametrize("nome", [None, 3, "", "  "])
    def test_nome_de_perfil_que_nao_e_texto(self, spectra, nome):
        assert spectra.load_profile(nome) is False
        assert spectra.delete_profile(nome) is False


class TestRecuperacaoNaAbertura:
    """O logon pode encontrar um SDK atrasado, vazio ou travado."""

    def test_primeira_falha_mantem_o_vigia_tentando(self, spectra, monkeypatch):
        b = _app_novo(monkeypatch, _bancada())
        iniciados = []
        monkeypatch.setattr(b, "start_watchdog", lambda: iniciados.append(1))

        def recusa():
            raise ConnectionRefusedError("SDK ainda nao abriu")

        monkeypatch.setattr(b.client, "connect", recusa)
        assert b.connect() is False
        assert b.renderer is None and b._primeira_conexao_pendente
        assert iniciados == [1]

        pedidos = []
        monkeypatch.setattr(b, "connect", lambda **kw: pedidos.append(kw) or False)
        b._watchdog_stop = ParadaDepoisDe(3)
        b._watchdog_loop()
        assert pedidos == [{"pode_subir": True}] * 3

    def test_lista_vazia_nao_vira_conexao_saudavel(self, spectra, monkeypatch,
                                                   sem_espera):
        b = _app_novo(monkeypatch, [])
        assert b.connect() is False
        assert b.renderer is None
        assert b.connected is False
        assert b._primeira_conexao_pendente is True
        assert "nao encontrou dispositivos" in b.erro_conexao
        # Quando a deteccao termina, a proxima tentativa monta a cena.
        b.client.devices = _bancada()
        try:
            assert b.connect() is True
            assert b.renderer.canvas.n == 15
            assert b._primeira_conexao_pendente is False
        finally:
            b.renderer.stop()

    def _servidor_travado(self, spectra, monkeypatch, tmp_path):
        from spectra.core import admin
        b = _app_novo(monkeypatch, _bancada())
        b.config["openrgb_exe"] = _exe_openrgb(tmp_path)
        rodando = [True]
        chamadas = []
        monkeypatch.setattr(admin, "openrgb_rodando", lambda: rodando[0])

        def encerra():
            chamadas.append("encerrar")
            rodando[0] = False
            return True

        monkeypatch.setattr(admin, "encerrar_openrgb", encerra)
        monkeypatch.setattr(b, "_start_openrgb",
                            lambda: chamadas.append("iniciar") or True)
        monkeypatch.setattr(b, "_esperar_porta", lambda wait: True)
        return b, rodando, chamadas

    @pytest.mark.skipif(sys.platform != "win32", reason="recuperacao automatica de processo Windows")
    def test_sdk_travado_reinicia_uma_vez_e_restaura_a_cena(
            self, spectra, monkeypatch, tmp_path):
        b, rodando, chamadas = self._servidor_travado(spectra, monkeypatch, tmp_path)

        def conecta():
            chamadas.append("conectar")
            if rodando[0]:
                raise OpenRGBError("SDK sem resposta")

        monkeypatch.setattr(b.client, "connect", conecta)
        try:
            assert b.connect() is True
            assert chamadas == ["conectar", "encerrar", "iniciar", "conectar"]
            assert b.renderer.canvas.n == 15
            assert b._recuperacao_inicial_tentada is True
        finally:
            b.renderer.stop()

    @pytest.mark.skipif(sys.platform != "win32", reason="recuperacao automatica de processo Windows")
    def test_instancia_que_nao_abriu_a_porta_tambem_e_recuperada(
            self, spectra, monkeypatch, tmp_path):
        b, rodando, chamadas = self._servidor_travado(spectra, monkeypatch, tmp_path)
        monkeypatch.setattr(b, "ensure_openrgb", lambda **kw: False)
        monkeypatch.setattr(b.client, "connect", lambda: (
            (_ for _ in ()).throw(ConnectionRefusedError("sem SDK"))
            if rodando[0] else None))
        try:
            assert b.connect() is True
            assert chamadas == ["encerrar", "iniciar"]
        finally:
            b.renderer.stop()

    @pytest.mark.skipif(sys.platform != "win32", reason="recuperacao automatica de processo Windows")
    def test_segunda_falha_nao_reinicia_sem_fim(self, spectra, monkeypatch,
                                               tmp_path):
        b, rodando, chamadas = self._servidor_travado(spectra, monkeypatch, tmp_path)

        def recusa():
            raise OpenRGBError("ainda indisponivel")

        monkeypatch.setattr(b.client, "connect", recusa)
        assert b.connect() is False
        rodando[0] = True
        assert b.connect() is False
        assert chamadas == ["encerrar", "iniciar"]

    @pytest.mark.parametrize("mudanca", ["remoto", "outra_porta", "manual",
                                          "sem_exe", "ja_conectado"])
    def test_recuperacao_respeita_o_escopo_local(self, spectra, monkeypatch,
                                                tmp_path, mudanca):
        b, _, chamadas = self._servidor_travado(spectra, monkeypatch, tmp_path)
        if mudanca == "remoto":
            b.host = "192.0.2.1"
        elif mudanca == "outra_porta":
            b.port = 7777
        elif mudanca == "manual":
            b.config["autostart_openrgb"] = False
        elif mudanca == "sem_exe":
            b.config.pop("openrgb_exe")
        elif mudanca == "ja_conectado":
            b.renderer = spectra.renderer
        assert b._recuperar_openrgb_inicial(True) is False
        assert chamadas == []

    def test_recusa_ao_fechar_nao_abre_segundo_processo(self, spectra,
                                                       monkeypatch, tmp_path):
        from spectra.core import admin
        b, _, chamadas = self._servidor_travado(spectra, monkeypatch, tmp_path)
        monkeypatch.setattr(admin, "encerrar_openrgb", lambda: False)
        assert b._recuperar_openrgb_inicial(True) is False
        assert chamadas == []

    def test_processo_que_demora_a_sair_nao_ganha_duplicata(self, spectra,
                                                          monkeypatch, tmp_path):
        from spectra.core import admin
        b, _, chamadas = self._servidor_travado(spectra, monkeypatch, tmp_path)
        monkeypatch.setattr(admin, "encerrar_openrgb", lambda: True)
        tempos = iter([0.0, 11.0])
        monkeypatch.setattr(app_mod, "time", types.SimpleNamespace(
            monotonic=lambda: next(tempos)))
        assert b._recuperar_openrgb_inicial(True) is False
        assert chamadas == []

    @pytest.mark.skipif(sys.platform != "win32", reason="tarefa agendada do Windows")
    def test_servidor_elevado_pode_ser_encerrado_pela_propria_tarefa(
            self, spectra, monkeypatch, tmp_path):
        from spectra.core import admin
        b, rodando, chamadas = self._servidor_travado(spectra, monkeypatch, tmp_path)
        monkeypatch.setattr(admin, "encerrar_openrgb", lambda: False)
        monkeypatch.setattr(admin, "tarefa_existe", lambda nome: True)

        def encerra_tarefa(nome):
            chamadas.append(("encerrar_tarefa", nome))
            rodando[0] = False
            return True

        monkeypatch.setattr(admin, "encerrar_tarefa", encerra_tarefa)
        assert b._recuperar_openrgb_inicial(True) is True
        assert chamadas == [("encerrar_tarefa", app_mod.OPENRGB_TASK), "iniciar"]

    def test_reconexao_para_o_render_antes_de_trocar_o_socket(self, spectra,
                                                             monkeypatch):
        r = spectra.renderer
        r.start()
        observados = []
        monkeypatch.setattr(spectra, "ensure_openrgb", lambda **kw: True)
        monkeypatch.setattr(spectra, "start_watchdog", lambda: None)
        monkeypatch.setattr(spectra, "_liga_teclado", lambda: None)
        monkeypatch.setattr(spectra.client, "connect", lambda: observados.append(
            r._thread.is_alive()))
        assert spectra.connect() is True
        assert observados == [False]

    def test_encerramento_nao_reabre_vigia_nem_servidor(self, spectra, monkeypatch):
        b = _app_novo(monkeypatch, _bancada())
        b._encerrando = True
        monkeypatch.setattr(b, "_connect", lambda *a: pytest.fail("reconectou"))
        assert b.connect() is False
        app_mod.SpectraApp.start_watchdog(b)
        assert b._watchdog is None
