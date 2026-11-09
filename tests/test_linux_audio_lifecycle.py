"""Ciclos de captura Linux com bloqueio do servidor de áudio simulado."""
import sys
import threading
from types import SimpleNamespace

from spectra.engine.context import AudioState
from spectra.sources.audio import AudioSource


def test_nao_religa_enquanto_gravacao_antiga_esta_encerrando(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    entered = threading.Event()
    release = threading.Event()
    class Recorder:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def record(self, **_):
            entered.set()
            release.wait(5)
            return [[0.5, 0.5]] * 1024
    mic = SimpleNamespace(name="Monitor", id="sink.monitor", channels=2,
                          isloopback=True, recorder=lambda **_: Recorder())
    monkeypatch.setitem(sys.modules, "soundcard", SimpleNamespace(
        all_microphones=lambda **_: [mic],
        default_speaker=lambda: SimpleNamespace(id="sink")))
    source = AudioSource(AudioState())
    try:
        assert source.start()
        assert entered.wait(1)
        source.stop()
        assert source._thread.is_alive()
        assert not source.start()
        assert source._stop.is_set()
        assert "encerrando" in source.error
    finally:
        release.set()
        source._thread.join(2)
    assert not source.state.enabled
    assert source.state.level == 0.0
    assert not source.running
