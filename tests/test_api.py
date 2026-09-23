"""Cobre a camada que a interface consome: estado, quadro e as rotas de escrita.

Estes testes montam um `SpectraApp` sobre um cliente falso, sem OpenRGB e sem
hardware, e com a configuracao apontada para um diretorio temporario, para que
rodar a suite nunca toque na configuracao real de quem esta desenvolvendo.
"""

from __future__ import annotations

import json
import threading
import time
import types

import numpy as np
import pytest

from spectra import app as app_mod
from spectra import server as server_mod
from spectra.core.protocol import MODE_FLAG_HAS_PER_LED_COLOR, Device, Mode, Zone
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
            spectra.save_profile("Noite")
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
        monkeypatch.setattr(com_teclado, "_connect", lambda exclusive_pass: True)
        com_teclado._watchdog_stop = ParadaDepoisDe(1)
        com_teclado._watchdog_loop()
        assert t.conectado is True
        assert com_teclado.renderer.ambiente is not None


class TestConexao:

    def test_duas_tentativas_ao_mesmo_tempo_viram_fila(self, spectra, monkeypatch):
        dentro, maximo = [0], [0]
        conta = threading.Lock()

        def falso(exclusive_pass):
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

    def test_pausar_pela_bandeja_apaga_mesmo_com_quadro_em_andamento(
            self, spectra, monkeypatch):
        lento = QuadroLento(monkeypatch, spectra)
        r = spectra.renderer
        r.start()
        try:
            assert lento.dentro.wait(2)
            threading.Timer(0.1, lento.solta.set).start()
            Tray(None, spectra, lambda: None)._alternar_pausa()
            time.sleep(0.1)
        finally:
            lento.solta.set()
            r.stop()
        assert r.settings["paused"] is True
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

        def quebra(exclusive_pass):
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
