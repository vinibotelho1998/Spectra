"""Testes das fontes externas que nao dependem do aparelho.

Nenhum abre captura de verdade: exercitam so o ciclo de vida das threads,
com a camera e a biblioteca de audio trocadas por falsas.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import types

import numpy as np
import pytest

from spectra.engine.context import AudioState, ScreenState, SensorState
from spectra.sources import sensors as sensors_mod
from spectra.sources.audio import BANDS, CHUNK, AudioSource
from spectra.sources.screen import ScreenSource
from spectra.sources.sensors import SensorSource, _LhmBackend


class TestAudio:

    @pytest.fixture(autouse=True)
    def plataforma_windows(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")

    def test_parar_espera_o_laco_de_decaimento(self):
        # vivo depois do stop, o laco faria o start seguinte achar que a
        # captura continuava de pe, ou somaria dois lacos decaindo a batida
        a = AudioSource(AudioState())
        a._thread = threading.Thread(target=a._decay_loop, daemon=True)
        a._thread.start()
        a.stop()
        assert not a._thread.is_alive()
        assert a.running is False

    def test_parar_sem_ter_ligado_nao_quebra(self):
        a = AudioSource(AudioState())
        a.stop()
        assert a.running is False

    def test_listar_sem_dispositivo_devolve_o_erro(self, monkeypatch):
        # sem placa de som a inicializacao do PortAudio ja falha
        falso = types.ModuleType("pyaudiowpatch")

        def sem_audio():
            raise OSError("nenhum dispositivo de audio")

        falso.PyAudio = sem_audio
        monkeypatch.setitem(sys.modules, "pyaudiowpatch", falso)
        devs, erro = AudioSource.list_devices()
        assert devs == []
        assert "nenhum dispositivo" in erro

    def _biblioteca(self, monkeypatch, dispositivos):
        """Biblioteca de audio falsa que anota qual dispositivo foi aberto."""
        abertos = []

        class Fluxo:
            def start_stream(self):
                pass

            def stop_stream(self):
                pass

            def close(self):
                pass

        class PyAudio:
            def get_loopback_device_info_generator(self):
                return iter(dispositivos)

            def get_device_info_by_index(self, i):
                return next(d for d in dispositivos if d["index"] == i)

            def open(self, **kw):
                abertos.append(kw["input_device_index"])
                return Fluxo()

            def terminate(self):
                pass

        falso = types.ModuleType("pyaudiowpatch")
        falso.PyAudio = PyAudio
        falso.paFloat32, falso.paContinue, falso.paWASAPI = 1, 0, 13
        monkeypatch.setitem(sys.modules, "pyaudiowpatch", falso)
        return abertos

    @staticmethod
    def _disp(i, nome):
        return {"index": i, "name": nome, "defaultSampleRate": 48000,
                "maxInputChannels": 2}

    def test_dispositivo_salvo_e_achado_pelo_nome(self, monkeypatch):
        # plugar um fone renumera tudo: o indice salvo passa a ser outro
        abertos = self._biblioteca(monkeypatch, [
            self._disp(7, "Fone [Loopback]"), self._disp(9, "Caixa [Loopback]")])
        a = AudioSource(AudioState(), device_index=7,
                        device_name="Caixa [Loopback]")
        try:
            assert a.start() is True
            assert abertos == [9]
            assert a.device_name == "Caixa [Loopback]"
        finally:
            a.stop()

    def test_dispositivo_que_sumiu_nao_abre_outro_no_lugar(self, monkeypatch):
        abertos = self._biblioteca(monkeypatch, [self._disp(7, "Fone [Loopback]")])
        a = AudioSource(AudioState(), device_index=7,
                        device_name="Caixa [Loopback]")
        assert a.start() is False
        assert abertos == []
        assert "Caixa [Loopback]" in a.error


class CameraParada:
    """Camera cuja thread de captura morreu: dali em diante so vem nada."""

    is_capturing = False

    def get_latest_frame(self):
        return None


class CameraTrocandoResolucao:
    """Devolve nada uma vez com a captura de pe, como na troca de resolucao."""

    is_capturing = True

    def __init__(self):
        self.chamadas = 0
        self.entregou = threading.Event()

    def get_latest_frame(self):
        self.chamadas += 1
        if self.chamadas == 1:
            return None
        self.entregou.set()
        time.sleep(0.01)
        return np.full((72, 128, 3), 255, dtype=np.uint8)


class CameraQueSegueCapturando:
    """Camera ainda capturando, que recusa um segundo start como o dxcam."""

    def __init__(self):
        self.is_capturing = True
        self.paradas = 0

    def start(self, **_kw):
        if self.is_capturing:
            raise RuntimeError("Capture is already running. Call stop() first.")
        self.is_capturing = True

    def stop(self):
        self.paradas += 1
        self.is_capturing = False

    def get_latest_frame(self):
        time.sleep(0.01)
        return None


def _dxcam_falso(monkeypatch, velha):
    """Devolve a mesma camera enquanto ela nao for parada, como a fabrica do dxcam."""
    falso = types.ModuleType("dxcam")

    def create(**_kw):
        if velha.paradas == 0:
            return velha
        nova = CameraQueSegueCapturando()
        nova.is_capturing = False
        return nova

    falso.create = create
    monkeypatch.setitem(sys.modules, "dxcam", falso)


def _rodar(fonte, camera):
    fonte._cam = camera
    fonte._thread = threading.Thread(target=fonte._loop, daemon=True)
    fonte._thread.start()


class TestTela:

    @pytest.fixture(autouse=True)
    def plataforma_windows(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")

    def test_captura_que_morreu_nao_fica_marcada_como_ativa(self):
        s = ScreenSource(ScreenState())
        _rodar(s, CameraParada())
        try:
            s._thread.join(1.0)
            assert not s._thread.is_alive()
            assert s.running is False
            assert s.error
        finally:
            s._stop.set()

    def test_quadro_vazio_com_a_captura_de_pe_nao_encerra(self):
        st = ScreenState()
        s = ScreenSource(st)
        cam = CameraTrocandoResolucao()
        _rodar(s, cam)
        try:
            assert cam.entregou.wait(1.0)
            assert s.running is True
        finally:
            s._stop.set()
            s._thread.join(1.0)
        assert s.error is None
        assert np.allclose(st.average, 1.0)

    def test_religar_depois_que_a_leitura_morreu_fecha_a_camera_velha(
            self, monkeypatch):
        # a leitura saiu por erro com a camera ainda capturando; sem fechar a
        # velha, o dxcam a devolveria de novo e o start seria recusado
        s = ScreenSource(ScreenState())
        velha = CameraQueSegueCapturando()
        s._cam = velha
        s._thread = threading.Thread(target=lambda: None)
        s._thread.start()
        s._thread.join()
        _dxcam_falso(monkeypatch, velha)
        try:
            assert s.start() is True
            assert velha.paradas == 1
            assert s._cam is not velha
            assert s.running is True
        finally:
            s._stop.set()
            s._thread.join(1.0)

    def test_saida_que_nao_pode_ser_capturada_nao_liga(self, monkeypatch):
        falso = types.ModuleType("dxcam")
        falso.create = lambda **_kw: None
        monkeypatch.setitem(sys.modules, "dxcam", falso)
        st = ScreenState()
        s = ScreenSource(st, output_idx=2)
        assert s.start() is False
        assert "saida 2" in s.error
        assert s._cam is None
        assert st.enabled is False

    def test_sem_a_biblioteca_de_captura_avisa(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "dxcam", None)
        s = ScreenSource(ScreenState())
        assert s.start() is False
        assert "dxcam indisponivel" in s.error

    def test_lista_os_monitores_um_por_linha(self, monkeypatch):
        falso = types.ModuleType("dxcam")
        falso.output_info = lambda: "Monitor 1: 1920x1080\n\n  Monitor 2: 2560x1440 \n"
        monkeypatch.setitem(sys.modules, "dxcam", falso)
        saidas, erro = ScreenSource.list_outputs()
        assert erro is None
        assert saidas == [{"index": 0, "name": "Monitor 1: 1920x1080"},
                          {"index": 1, "name": "Monitor 2: 2560x1440"}]

    def test_listar_com_falha_devolve_o_erro(self, monkeypatch):
        falso = types.ModuleType("dxcam")

        def quebra():
            raise OSError("sem placa de video")

        falso.output_info = quebra
        monkeypatch.setitem(sys.modules, "dxcam", falso)
        assert ScreenSource.list_outputs() == ([], "sem placa de video")


class TestReducaoDaTela:
    """A tela chega em resolucao cheia e vira uma grade pequena na entrada."""

    def test_metade_vermelha_continua_metade_vermelha(self):
        img = np.zeros((1080, 1920, 3), dtype=np.uint8)
        img[:, :960] = (255, 0, 0)
        small = ScreenSource(ScreenState())._downscale(img)
        assert small.shape == (36, 64, 3)
        assert small.dtype == np.float32
        assert np.allclose(small[:, :32], (1.0, 0.0, 0.0))
        assert np.allclose(small[:, 32:], 0.0)

    def test_resolucao_que_nao_divide_certo_ainda_cabe_na_grade(self):
        img = np.full((1050, 1680, 3), 128, dtype=np.uint8)
        small = ScreenSource(ScreenState())._downscale(img)
        assert small.shape == (36, 64, 3)
        assert np.allclose(small, 128 / 255.0)

    def test_linha_de_cima_fica_em_cima(self):
        img = np.zeros((720, 1280, 3), dtype=np.uint8)
        img[:20, :, 2] = 255
        small = ScreenSource(ScreenState())._downscale(img)
        assert small[0, :, 2].min() == pytest.approx(1.0)
        assert small[1:, :, 2].max() == 0.0

    def test_dominante_prefere_a_cor_viva_ao_fundo_lavado(self):
        # tela quase toda cinza com uma faixa vermelha: a media sai cinza,
        # e o Ambilight pintaria o gabinete de cinza
        small = np.full((36, 64, 3), 0.5, dtype=np.float32)
        small[:, :8] = (0.9, 0.05, 0.05)
        dom = ScreenSource._dominant(small)
        media = small.reshape(-1, 3).mean(axis=0)
        assert dom[0] > 0.8 and dom[1] < 0.2 and dom[2] < 0.2
        assert media[0] < 0.6

    def test_tela_preta_devolve_preto(self):
        dom = ScreenSource._dominant(np.zeros((36, 64, 3), dtype=np.float32))
        assert np.allclose(dom, 0.0)


class _Pa:
    """Modulo de audio falso so com o que o callback consulta."""

    paContinue = 0
    paFloat32 = 1
    paWASAPI = 13


def _analisador(monkeypatch, canais=2, agc=True):
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", _Pa)
    a = AudioSource(AudioState())
    a._rate = 48000
    a._channels = canais
    a.agc_enabled = agc
    a._build_bands()
    return a


def _tom(freq, amp=0.5, n=CHUNK, rate=48000, inicio=0):
    t = (np.arange(n) + inicio) / rate
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _toca(a, amostras):
    return a._callback(np.ascontiguousarray(amostras, dtype=np.float32).tobytes(),
                       len(amostras), None, 0)


def _toca_tom(a, freq, vezes=4, amp=0.5, canais=None):
    for k in range(vezes):
        mono = _tom(freq, amp, inicio=k * CHUNK)
        if canais is None:
            _toca(a, mono)
        else:
            _toca(a, canais(mono).reshape(-1))


class TestAnaliseDeAudio:

    def test_silencio_nao_acende_nada(self, monkeypatch):
        a = _analisador(monkeypatch)
        _toca(a, np.zeros(2 * CHUNK, dtype=np.float32))
        s = a.state
        assert s.level == 0.0
        assert s.beat == 0.0
        assert not s.bands.any()

    @pytest.mark.parametrize("freq", [60, 1000, 8000])
    def test_tom_acende_a_banda_da_sua_frequencia(self, monkeypatch, freq):
        a = _analisador(monkeypatch, canais=1)
        _toca_tom(a, freq)
        bordas = np.geomspace(30.0, 16000.0, BANDS + 1)
        esperada = int(np.searchsorted(bordas, freq)) - 1
        assert int(np.argmax(a.state.bands)) == esperada

    def test_grave_e_agudo_vao_para_o_lugar_certo(self, monkeypatch):
        grave = _analisador(monkeypatch, canais=1)
        _toca_tom(grave, 60)
        agudo = _analisador(monkeypatch, canais=1)
        _toca_tom(agudo, 8000)
        assert grave.state.bass > grave.state.treble
        assert agudo.state.treble > agudo.state.bass
        assert agudo.state.centroid > grave.state.centroid

    def test_placa_de_seis_canais_le_o_par_da_frente(self, monkeypatch):
        # os canais traseiros vem quase mudos: somar todos afogaria o sinal
        estereo = _analisador(monkeypatch, canais=2)
        _toca_tom(estereo, 440, canais=lambda m: np.stack([m, m], axis=1))
        seis = _analisador(monkeypatch, canais=6)
        _toca_tom(seis, 440, canais=lambda m: np.stack(
            [m, m] + [np.zeros_like(m)] * 4, axis=1))
        assert seis.state.level > 0.5
        assert seis.state.level == pytest.approx(estereo.state.level, rel=1e-5)

    def test_so_os_canais_de_tras_nao_contam(self, monkeypatch):
        seis = _analisador(monkeypatch, canais=6)
        _toca_tom(seis, 440, canais=lambda m: np.stack(
            [np.zeros_like(m)] * 2 + [m] * 4, axis=1))
        assert seis.state.level == 0.0

    def test_ganho_automatico_levanta_musica_baixa(self, monkeypatch):
        # o teto do ganho cede devagar: uns vinte segundos de musica baixa
        com = _analisador(monkeypatch, canais=1, agc=True)
        _toca_tom(com, 1000, amp=0.01, vezes=1000)
        sem = _analisador(monkeypatch, canais=1, agc=False)
        _toca_tom(sem, 1000, amp=0.01, vezes=1000)
        assert com.state.bands.max() > 0.9
        assert sem.state.bands.max() < 0.3

    def test_ataque_de_grave_depois_do_silencio_e_batida(self, monkeypatch):
        a = _analisador(monkeypatch, canais=1)
        for _ in range(5):
            _toca(a, np.zeros(CHUNK, dtype=np.float32))
        assert a.state.beat == 0.0
        _toca_tom(a, 60, vezes=2)
        assert a.state.beat == 1.0

    def test_grave_constante_nao_vira_batida_a_cada_quadro(self, monkeypatch):
        a = _analisador(monkeypatch, canais=1)
        _toca_tom(a, 60, vezes=80)
        a.state.beat = 0.0
        _toca_tom(a, 60, vezes=1)
        assert a.state.beat == 0.0

    def test_forma_de_onda_mantem_o_tamanho_e_a_faixa(self, monkeypatch):
        a = _analisador(monkeypatch, canais=1)
        _toca(a, np.full(CHUNK, 3.0, dtype=np.float32))
        assert len(a.state.waveform) == 128
        assert a.state.waveform.max() <= 1.0

    def test_pacote_vazio_nao_mexe_no_estado(self, monkeypatch):
        a = _analisador(monkeypatch)
        assert _toca(a, np.zeros(0, dtype=np.float32)) == (None, _Pa.paContinue)
        assert a.state.level == 0.0
        assert a.error is None

    def test_erro_na_analise_nao_para_a_captura(self, monkeypatch):
        a = _analisador(monkeypatch, canais=1)
        a._band_idx = None
        assert _toca(a, _tom(440)) == (None, _Pa.paContinue)
        assert a.error

    def test_bandas_cobrem_ao_menos_um_ponto_do_espectro(self, monkeypatch):
        a = _analisador(monkeypatch)
        assert len(a._band_idx) == BANDS
        assert all(b > a_ for a_, b in a._band_idx)
        inicios = [a_ for a_, _b in a._band_idx]
        assert inicios == sorted(inicios)

    def test_batida_decai_ate_zerar(self):
        a = AudioSource(AudioState())
        a.state.beat = 1.0
        a._thread = threading.Thread(target=a._decay_loop, daemon=True)
        a._thread.start()
        try:
            fim = time.monotonic() + 2.0
            while a.state.beat != 0.0 and time.monotonic() < fim:
                time.sleep(0.02)
        finally:
            a.stop()
        assert a.state.beat == 0.0


class TestDispositivoDeAudio:

    @pytest.fixture(autouse=True)
    def plataforma_windows(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")

    def _biblioteca(self, monkeypatch, saida, loopbacks, erro_na_lista=None):
        abertos = []
        terminados = []

        class Fluxo:
            def start_stream(self):
                pass

            def stop_stream(self):
                pass

            def close(self):
                pass

        class PyAudio:
            def get_host_api_info_by_type(self, tipo):
                return {"defaultOutputDevice": saida["index"]}

            def get_device_info_by_index(self, i):
                return saida

            def get_loopback_device_info_generator(self):
                if erro_na_lista:
                    raise erro_na_lista
                return iter(loopbacks)

            def open(self, **kw):
                abertos.append(kw)
                return Fluxo()

            def terminate(self):
                terminados.append(1)

        falso = types.ModuleType("pyaudiowpatch")
        falso.PyAudio = PyAudio
        falso.paFloat32, falso.paContinue, falso.paWASAPI = 1, 0, 13
        monkeypatch.setitem(sys.modules, "pyaudiowpatch", falso)
        return abertos, terminados

    @staticmethod
    def _disp(i, nome, canais=2, loopback=False):
        return {"index": i, "name": nome, "defaultSampleRate": 44100.0,
                "maxInputChannels": canais, "isLoopbackDevice": loopback}

    def test_sem_escolha_abre_o_loopback_da_saida_padrao(self, monkeypatch):
        abertos, _ = self._biblioteca(
            monkeypatch, self._disp(3, "Caixa"),
            [self._disp(8, "Fone [Loopback]"),
             self._disp(9, "Caixa [Loopback]", canais=6)])
        a = AudioSource(AudioState())
        try:
            assert a.start() is True
            assert abertos[0]["input_device_index"] == 9
            assert abertos[0]["channels"] == 6
            assert abertos[0]["rate"] == 44100
            assert a.device_name == "Caixa [Loopback]"
            assert a.state.enabled is True
        finally:
            a.stop()
        assert a.state.enabled is False

    def test_saida_padrao_que_ja_e_loopback_e_usada_direto(self, monkeypatch):
        abertos, _ = self._biblioteca(
            monkeypatch, self._disp(4, "Caixa [Loopback]", loopback=True), [])
        a = AudioSource(AudioState())
        try:
            assert a.start() is True
            assert abertos[0]["input_device_index"] == 4
        finally:
            a.stop()

    def test_saida_sem_loopback_nao_liga_e_diz_por_que(self, monkeypatch):
        abertos, terminados = self._biblioteca(
            monkeypatch, self._disp(3, "Caixa"), [self._disp(8, "Fone [Loopback]")])
        a = AudioSource(AudioState())
        assert a.start() is False
        assert "loopback" in a.error
        assert abertos == []
        assert terminados == [1]
        assert a.running is False

    def test_lista_os_loopbacks_e_solta_a_biblioteca(self, monkeypatch):
        _, terminados = self._biblioteca(
            monkeypatch, self._disp(3, "Caixa"),
            [self._disp(9, "Caixa [Loopback]", canais=6)])
        devs, erro = AudioSource.list_devices()
        assert erro is None
        assert devs == [{"index": 9, "name": "Caixa [Loopback]", "channels": 6,
                         "rate": 44100, "loopback": True}]
        assert terminados == [1]

    def test_falha_ao_listar_devolve_o_erro_e_solta(self, monkeypatch):
        _, terminados = self._biblioteca(
            monkeypatch, self._disp(3, "Caixa"), [],
            erro_na_lista=OSError("WASAPI indisponivel"))
        assert AudioSource.list_devices() == ([], "WASAPI indisponivel")
        assert terminados == [1]


class Leitura:
    """Um sensor como a biblioteca .NET entrega."""

    def __init__(self, nome, tipo, valor):
        self.Name, self.SensorType, self.Value = nome, tipo, valor


class Peca:
    """Um hardware da biblioteca, com os sensores e as sub pecas dele."""

    def __init__(self, tipo, leituras, subs=(), quebra=False):
        self.HardwareType = tipo
        self.Sensors = leituras
        self.SubHardware = list(subs)
        self.atualizacoes = 0
        self.quebra = quebra

    def Update(self):
        if self.quebra:
            raise RuntimeError("leitura do SMBus falhou")
        self.atualizacoes += 1


def _backend(pecas):
    b = _LhmBackend("nao usado")
    b.computer = types.SimpleNamespace(Hardware=pecas)
    return b


class TestLeituraDosSensores:

    def test_temperatura_da_cpu_e_o_maior_entre_pacote_e_tctl(self):
        d = _backend([Peca("Cpu", [
            Leitura("CPU Package", "Temperature", 70.0),
            Leitura("Core (Tctl/Tdie)", "Temperature", 65.0),
            Leitura("Core #1", "Temperature", 90.0)])]).read()
        assert d["cpu_temp"] == 70.0
        assert d["Cpu/Core #1/Temperature"] == 90.0

    def test_temperatura_da_gpu_pega_o_ponto_mais_quente(self):
        d = _backend([Peca("GpuNvidia", [
            Leitura("GPU Hot Spot", "Temperature", 72.0),
            Leitura("GPU Core", "Temperature", 60.0),
            Leitura("GPU Memory Junction", "Temperature", 95.0)])]).read()
        assert d["gpu_temp"] == 72.0

    def test_cargas_vao_cada_uma_para_o_seu_nome(self):
        d = _backend([
            Peca("Cpu", [Leitura("CPU Total", "Load", 45.0),
                         Leitura("CPU Core #1", "Load", 99.0)]),
            Peca("GpuAmd", [Leitura("GPU Core", "Load", 88.0)]),
            Peca("Memory", [Leitura("Memory", "Load", 55.0)]),
        ]).read()
        assert (d["cpu_load"], d["gpu_load"], d["ram_load"]) == (45.0, 88.0, 55.0)

    def test_fan_da_placa_mae_vem_da_sub_peca(self):
        # na placa-mae os fans ficam no chip de monitoramento, uma sub peca
        chip = Peca("SuperIO", [Leitura("Fan #1", "Fan", 1450.0),
                                Leitura("Fan #2", "Fan", 800.0)])
        placa = Peca("Motherboard", [], subs=[chip])
        d = _backend([placa]).read()
        assert d["fan_rpm"] == 1450.0
        assert chip.atualizacoes == 1 and placa.atualizacoes == 1

    def test_sensor_sem_valor_e_ignorado(self):
        d = _backend([Peca("Cpu", [Leitura("CPU Package", "Temperature", None),
                                   Leitura("CPU Total", "Load", 20.0)])]).read()
        assert "cpu_temp" not in d
        assert d["cpu_load"] == 20.0

    def test_erro_no_meio_devolve_o_que_leu_e_anota(self):
        b = _backend([Peca("Cpu", [Leitura("CPU Total", "Load", 30.0)]),
                      Peca("Storage", [], quebra=True)])
        d = b.read()
        assert d["cpu_load"] == 30.0
        assert "SMBus" in b.error

    def test_sem_a_biblioteca_aberta_nao_le_nada(self):
        assert _LhmBackend("nao usado").read() == {}

    def test_dll_ausente_diz_a_pasta_onde_procurou(self, tmp_path):
        b = _LhmBackend(str(tmp_path / "vendor" / "LibreHardwareMonitorLib.dll"))
        assert b.open() is False
        assert str(tmp_path / "vendor") in b.error
        assert b.computer is None

    def test_fechar_com_erro_da_biblioteca_nao_escapa(self):
        def quebra():
            raise RuntimeError("ja fechado")

        b = _backend([])
        b.computer.Close = quebra
        b.close()
        assert b.computer is None


def _psutil_falso(monkeypatch, cpu=37.0, ram=61.0, quebra=False):
    falso = types.ModuleType("psutil")

    def cpu_percent(interval=None):
        if quebra:
            raise OSError("sem contador de desempenho")
        return cpu

    falso.cpu_percent = cpu_percent
    falso.virtual_memory = lambda: types.SimpleNamespace(percent=ram)
    monkeypatch.setitem(sys.modules, "psutil", falso)


class UmaVolta:
    """Evento de parada que libera uma volta so do laco."""

    def __init__(self):
        self.voltas = 0

    def is_set(self):
        return self.voltas > 0

    def wait(self, _timeout):
        self.voltas += 1

    def set(self):
        self.voltas += 1

    def clear(self):
        pass


class TestFonteDeSensores:

    @pytest.fixture(autouse=True)
    def plataforma_windows(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")

    def test_sem_dll_segue_com_uso_de_cpu_e_ram(self, monkeypatch, tmp_path):
        _psutil_falso(monkeypatch)
        st = SensorState()
        s = SensorSource(st, interval=0.01, dll_path=str(tmp_path / "x.dll"))
        try:
            assert s.start() is True
            fim = time.monotonic() + 2.0
            while not s.available and time.monotonic() < fim:
                time.sleep(0.01)
            assert s.available == ["cpu_load", "ram_load"]
            assert (st.cpu_load, st.ram_load) == (37.0, 61.0)
            assert st.enabled is True
            assert s.status()["dll_present"] is False
        finally:
            s.stop()
        assert st.enabled is False
        assert s.running is False

    def test_sem_nada_para_ler_nao_liga(self, monkeypatch, tmp_path):
        _psutil_falso(monkeypatch, quebra=True)
        st = SensorState()
        s = SensorSource(st, dll_path=str(tmp_path / "x.dll"))
        assert s.start() is False
        assert "LibreHardwareMonitorLib.dll" in s.error
        assert st.enabled is False
        assert s.running is False

    def test_com_a_biblioteca_as_temperaturas_chegam_ao_estado(self, monkeypatch):
        _psutil_falso(monkeypatch)
        st = SensorState()
        s = SensorSource(st)
        s.psutil_ok = s.lhm_ok = True
        s.lhm.read = lambda: {"cpu_temp": 66.0, "gpu_temp": 70.0,
                              "fan_rpm": 900.0, "cpu_load": 12.0}
        s._stop = UmaVolta()
        s._loop()
        assert (st.cpu_temp, st.gpu_temp, st.fan_rpm) == (66.0, 70.0, 900.0)
        # com o psutil de pe, o uso da CPU e o dele
        assert st.cpu_load == 37.0
        assert s.available == ["cpu_load", "cpu_temp", "fan_rpm", "gpu_temp",
                               "ram_load"]
        assert st.extra["cpu_temp"] == 66.0

    def test_sem_psutil_o_uso_da_cpu_vem_da_biblioteca(self):
        st = SensorState()
        s = SensorSource(st)
        s.lhm_ok = True
        s.lhm.read = lambda: {"cpu_load": 12.0}
        s._stop = UmaVolta()
        s._loop()
        assert st.cpu_load == 12.0
        assert s.available == ["cpu_load"]

    def test_leitura_que_some_sai_da_lista_do_que_ha(self):
        st = SensorState()
        s = SensorSource(st)
        s.lhm_ok = True
        s.lhm.read = lambda: {}
        s.available = ["cpu_temp"]
        s._stop = UmaVolta()
        s._loop()
        assert s.available == []

    def test_caminho_padrao_da_dll_fica_na_vendor(self):
        assert sensors_mod.VENDOR_DLL.endswith(
            "vendor" + os.sep + "LibreHardwareMonitorLib.dll")

    def test_psutil_que_falha_no_meio_nao_derruba_a_leitura(self, monkeypatch):
        _psutil_falso(monkeypatch, quebra=True)
        st = SensorState()
        s = SensorSource(st)
        s.psutil_ok = s.lhm_ok = True
        s.lhm.read = lambda: {"cpu_temp": 50.0}
        s._stop = UmaVolta()
        s._loop()
        assert st.cpu_temp == 50.0
        assert s.available == ["cpu_temp"]


class TestPonteComABiblioteca:
    """A ponte .NET trocada por modulos falsos: nada de CLR de verdade."""

    def _clr(self, monkeypatch, erro=None):
        referencias = []
        clr = types.ModuleType("clr")

        def add_reference(caminho):
            if erro:
                raise erro
            referencias.append(caminho)

        clr.AddReference = add_reference

        class Computer:
            criados = []

            def __init__(self):
                self.aberto = False
                Computer.criados.append(self)

            def Open(self):
                self.aberto = True

            def Close(self):
                self.aberto = False

        hardware = types.ModuleType("LibreHardwareMonitor.Hardware")
        hardware.Computer = Computer
        pacote = types.ModuleType("LibreHardwareMonitor")
        pacote.Hardware = hardware
        monkeypatch.setitem(sys.modules, "clr", clr)
        monkeypatch.setitem(sys.modules, "LibreHardwareMonitor", pacote)
        monkeypatch.setitem(sys.modules, "LibreHardwareMonitor.Hardware", hardware)
        return referencias, Computer

    def _dll(self, tmp_path):
        dll = tmp_path / "LibreHardwareMonitorLib.dll"
        dll.write_bytes(b"")
        return str(dll)

    def test_liga_todas_as_familias_de_sensor(self, monkeypatch, tmp_path):
        refs, Computer = self._clr(monkeypatch)
        b = _LhmBackend(self._dll(tmp_path))
        assert b.open() is True
        assert refs == [b.dll_path]
        c = Computer.criados[-1]
        assert c.aberto is True
        for familia in ("Cpu", "Gpu", "Memory", "Motherboard", "Controller",
                        "Storage"):
            assert getattr(c, f"Is{familia}Enabled") is True, familia
        assert b.error is None
        b.close()
        assert c.aberto is False
        assert b.computer is None

    def test_biblioteca_que_nao_carrega_vira_erro_legivel(self, monkeypatch,
                                                          tmp_path):
        self._clr(monkeypatch, erro=OSError("arquivo bloqueado pelo Windows"))
        b = _LhmBackend(self._dll(tmp_path))
        assert b.open() is False
        assert b.error == "OSError: arquivo bloqueado pelo Windows"
        assert b.computer is None


class TestCapturaQueQuebra:

    @pytest.fixture(autouse=True)
    def plataforma_windows(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")

    def test_erro_da_camera_encerra_a_leitura_com_o_motivo(self):
        class CameraQuebrada:
            is_capturing = True

            def get_latest_frame(self):
                raise RuntimeError("DXGI_ERROR_ACCESS_LOST")

        s = ScreenSource(ScreenState())
        _rodar(s, CameraQuebrada())
        s._thread.join(1.0)
        assert not s._thread.is_alive()
        assert "ACCESS_LOST" in s.error
        assert s.running is False

    def test_parar_com_camera_que_reclama_nao_escapa(self):
        class CameraTeimosa:
            def stop(self):
                raise RuntimeError("ja parada")

        st = ScreenState()
        st.enabled = True
        s = ScreenSource(st)
        s._cam = CameraTeimosa()
        s.stop()
        assert s._cam is None
        assert st.enabled is False

    def test_audio_sem_a_biblioteca_nao_liga(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "pyaudiowpatch", None)
        a = AudioSource(AudioState())
        assert a.start() is False
        assert "pyaudiowpatch indisponivel" in a.error
        devs, erro = AudioSource.list_devices()
        assert devs == [] and erro


class TestFontesLinux:
    def test_lista_apenas_monitores_de_audio(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        loop = types.SimpleNamespace(name="Saida", channels=2, isloopback=True)
        mic = types.SimpleNamespace(name="Microfone", channels=1, isloopback=False)
        monkeypatch.setitem(sys.modules, "soundcard", types.SimpleNamespace(
            all_microphones=lambda include_loopback: [mic, loop]))
        devices, error = AudioSource.list_devices()
        assert error is None
        assert [d["name"] for d in devices] == ["Saida"]
        assert devices[0]["channels"] == 2

    def test_abre_audio_com_contagem_inteira_de_canais(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        opened = []
        class Recorder:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def record(self, numframes):
                time.sleep(.01)
                return np.zeros((numframes, 2), dtype=np.float32)
        class Monitor:
            name = "Saida"
            channels = 2
            isloopback = True
            def recorder(self, **kwargs):
                opened.append(kwargs)
                return Recorder()
        monitor = Monitor()
        monkeypatch.setitem(sys.modules, "soundcard", types.SimpleNamespace(
            all_microphones=lambda include_loopback: [monitor]))
        source = AudioSource(AudioState(), device_name="Saida")
        try:
            assert source.start(), source.error
            assert opened[0]["channels"] == 2
            assert source.running
        finally:
            source.stop()
        assert not source.running

    def test_audio_padrao_usa_monitor_da_saida_exata(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        opened = []
        class Recorder:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def record(self, numframes):
                time.sleep(.01)
                return np.zeros((numframes, 2), dtype=np.float32)
        class Monitor:
            channels = 2
            isloopback = True
            def __init__(self, id):
                self.id = self.name = id
            def recorder(self, **kwargs):
                opened.append(self.id)
                return Recorder()
        monitors = [Monitor("saida-extra.monitor"), Monitor("saida.monitor")]
        monkeypatch.setitem(sys.modules, "soundcard", types.SimpleNamespace(
            all_microphones=lambda include_loopback: monitors,
            default_speaker=lambda: types.SimpleNamespace(id="saida")))
        source = AudioSource(AudioState())
        try:
            assert source.start(), source.error
            assert opened == ["saida.monitor"]
        finally:
            source.stop()

    def test_audio_padrao_sem_monitor_nao_escolhe_outro(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monitor = types.SimpleNamespace(id="outra.monitor", isloopback=True)
        monkeypatch.setitem(sys.modules, "soundcard", types.SimpleNamespace(
            all_microphones=lambda include_loopback: [monitor],
            default_speaker=lambda: types.SimpleNamespace(id="saida")))
        source = AudioSource(AudioState())
        assert not source.start()
        assert "monitor" in source.error

    def test_audio_escolhido_ausente_nao_troca_para_outro(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setitem(sys.modules, "soundcard", types.SimpleNamespace(
            all_microphones=lambda include_loopback: []))
        source = AudioSource(AudioState(), device_name="Fone")
        assert not source.start()
        assert "Fone" in source.error

    def test_lista_monitores_individuais(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        class FakeCapture:
            monitors = [{"width": 300, "height": 100}, {"width": 100, "height": 100}, {"width": 200, "height": 100}]
            def __enter__(self): return self
            def __exit__(self, *args): pass
        monkeypatch.setitem(sys.modules, "mss", types.SimpleNamespace(mss=FakeCapture))
        devices, error = ScreenSource.list_outputs()
        assert error is None
        assert [d["index"] for d in devices] == [0, 1]
        assert "200x100" in devices[1]["name"]


class TestWayland:
    def test_seletor_portal_em_vez_de_xwayland(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        devices, error = ScreenSource.list_outputs()
        assert error is None
        assert "portal" in devices[0]["name"]

    def test_captura_e_encerramento(self, monkeypatch):
        import spectra.sources.screen as screen
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        class Portal:
            def __init__(self, stop, grid, fps):
                self.stop = stop
            def run(self, frame, ready):
                ready()
                frame(np.full((36, 64, 3), (255, 0, 0), dtype=np.uint8))
                self.stop.wait(1)
        monkeypatch.setattr(screen, "_PortalCapture", Portal)
        state = ScreenState()
        source = ScreenSource(state)
        assert source.start()
        deadline = time.monotonic() + 1
        while state.average[0] < 0.9 and time.monotonic() < deadline:
            time.sleep(.01)
        assert state.enabled
        assert np.allclose(state.average, [1, 0, 0])
        source.stop()
        assert not state.enabled and not source.running

    def test_recusa_de_permissao_nao_ativa_fonte(self, monkeypatch):
        import spectra.sources.screen as screen
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        class Portal:
            def __init__(self, *args): pass
            def run(self, frame, ready): raise screen._PortalDenied("compartilhamento recusado")
        monkeypatch.setattr(screen, "_PortalCapture", Portal)
        state = ScreenState()
        source = ScreenSource(state)
        source.start()
        source._thread.join(1)
        assert not state.enabled and not source.running
        assert "recusado" in source.error
        assert not source.start()

    def test_assinaturas_portal_com_glib(self):
        pytest.importorskip('gi')
        import threading
        from spectra.sources.screen import _PortalCapture
        portal = _PortalCapture(threading.Event(), (36, 64), 30)
        class Bus:
            def call_sync(self, *args): return None
        portal.Gio = types.SimpleNamespace(
            BusType=types.SimpleNamespace(SESSION=1),
            DBusCallFlags=types.SimpleNamespace(NONE=0),
            bus_get_sync=lambda *args: Bus())
        signatures = []
        def request(method, args):
            variant = args('spectra_token')
            signatures.append((method, variant.get_type_string(), variant.unpack()))
            if method == 'CreateSession':
                return {'session_handle': '/org/freedesktop/portal/desktop/session/1_2/spectra_test'}
            if method == 'SelectSources':
                return {}
            raise RuntimeError('fim do teste')
        portal._request = request
        with pytest.raises(RuntimeError, match='fim do teste'):
            portal.run(lambda f: None, lambda: None)
        assert [v[1] for v in signatures] == ['(a{sv})', '(oa{sv})', '(osa{sv})']
        assert signatures[0][2][0]['handle_token'] == 'spectra_token'
