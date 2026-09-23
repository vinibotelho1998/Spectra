"""Testes das fontes externas que nao dependem do aparelho.

Nenhum abre captura de verdade: exercitam so o ciclo de vida das threads,
com a camera e a biblioteca de audio trocadas por falsas.
"""
from __future__ import annotations

import sys
import threading
import time
import types

import numpy as np

from spectra.engine.context import AudioState, ScreenState
from spectra.sources.audio import AudioSource
from spectra.sources.screen import ScreenSource


class TestAudio:

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
