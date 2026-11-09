"""Carga de GPU no Linux, sem hardware ou comandos reais."""
from types import SimpleNamespace
import subprocess

from spectra.sources import sensors
from spectra.engine.context import SensorState


def _amd(root, card, value):
    device = root / card / "device"
    device.mkdir(parents=True)
    (device / "gpu_busy_percent").write_text(value)


def test_amd_multiplas_gpus_ignora_valores_invalidos(tmp_path, monkeypatch):
    _amd(tmp_path, "card0", "25\n")
    _amd(tmp_path, "card1", "81\n")
    _amd(tmp_path, "card2", "101\n")
    _amd(tmp_path, "card3", "N/A\n")
    monkeypatch.setattr(sensors.shutil, "which", lambda _: None)
    assert sensors._linux_gpu_load(str(tmp_path)) == 81


def test_nvidia_usa_maior_valor_e_ignora_leituras_indisponiveis(tmp_path, monkeypatch):
    monkeypatch.setattr(sensors.shutil, "which", lambda _: "/usr/bin/nvidia-smi")
    calls = []
    def run(args, **kw):
        calls.append((args, kw))
        return SimpleNamespace(stdout="10\nN/A\n92\n")
    monkeypatch.setattr(sensors.subprocess, "run", run)
    assert sensors._linux_gpu_load(str(tmp_path)) == 92
    assert calls[0][0][0] == "/usr/bin/nvidia-smi"
    assert calls[0][1]["timeout"] == 0.75
    assert calls[0][1]["check"] is True


def test_nvidia_que_trava_nao_impede_leitura_amd(tmp_path, monkeypatch):
    _amd(tmp_path, "card0", "44")
    monkeypatch.setattr(sensors.shutil, "which", lambda _: "/usr/bin/nvidia-smi")
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("nvidia-smi", .75)
    monkeypatch.setattr(sensors.subprocess, "run", timeout)
    assert sensors._linux_gpu_load(str(tmp_path)) == 44


def test_leitura_desaparecida_nao_permanece_disponivel(monkeypatch):
    source = sensors.SensorSource(SensorState())
    source.linux_sensors = True
    source.available = ["gpu_load"]
    monkeypatch.setattr(sensors, "_linux_gpu_load", lambda: None)
    class OneLoop:
        def __init__(self): self.done = False
        def is_set(self): return self.done
        def wait(self, _): self.done = True
    source._stop = OneLoop()
    source._loop()
    assert "gpu_load" not in source.available


def test_leitura_chega_ao_estado(monkeypatch):
    source = sensors.SensorSource(SensorState())
    source.linux_sensors = True
    monkeypatch.setattr(sensors, "_linux_gpu_load", lambda: 67.0)
    class OneLoop:
        def __init__(self): self.done = False
        def is_set(self): return self.done
        def wait(self, _): self.done = True
    source._stop = OneLoop()
    source._loop()
    assert source.state.gpu_load == 67.0
    assert "gpu_load" in source.available
