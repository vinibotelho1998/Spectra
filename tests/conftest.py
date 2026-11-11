from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fakes import bancada

from spectra.core import mystique
from spectra.engine.canvas import Canvas
from spectra.engine.context import RenderContext


@pytest.fixture(autouse=True)
def cooler_isolado(tmp_path, monkeypatch):
    """Arquivos do servico do visor numa pasta temporaria, em todo teste.

    Sem isso a suite leria o estado do cooler de verdade da maquina e um
    teste da chave do anel gravaria no controle real dele.
    """
    pasta = tmp_path / "deepcool"
    monkeypatch.setattr(mystique, "caminho_estado", lambda: str(pasta / "status.json"))
    monkeypatch.setattr(mystique, "CONTROLE", str(pasta / "control.json"))
    return pasta


@pytest.fixture
def devices():
    return bancada()


@pytest.fixture
def canvas(devices):
    return Canvas(devices)


@pytest.fixture
def ctx(canvas):
    c = RenderContext(canvas)
    c.audio.enabled = True
    c.audio.level = 0.5
    c.audio.peak = 0.8
    c.audio.bass = 0.7
    c.audio.mid = 0.4
    c.audio.treble = 0.3
    c.audio.beat = 0.9
    c.audio.centroid = 0.4
    c.audio.bands = np.abs(np.sin(np.linspace(0, 6, 24))).astype(np.float32)
    c.audio.waveform = np.sin(np.linspace(0, 20, 128)).astype(np.float32)
    c.sensors.enabled = True
    c.sensors.cpu_temp = 62.0
    c.sensors.gpu_temp = 71.0
    c.sensors.cpu_load = 45.0
    c.sensors.gpu_load = 88.0
    c.sensors.ram_load = 55.0
    c.sensors.fan_rpm = 1200.0
    c.screen.enabled = True
    rng = np.random.default_rng(7)
    c.screen.image = rng.random((36, 64, 3)).astype(np.float32)
    c.screen.average = np.array([0.3, 0.5, 0.7], dtype=np.float32)
    c.screen.dominant = np.array([0.8, 0.2, 0.4], dtype=np.float32)
    return c
