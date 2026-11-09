import sys
import types

import pytest
from spectra import tray

# No Windows o pystray real usa o backend win32 e ignora os falsos do Linux.
pytestmark = pytest.mark.skipif(sys.platform != 'linux', reason='bandeja do Linux')


class Window:
    def __init__(self): self.calls = []
    def show(self): self.calls.append('show')
    def restore(self): self.calls.append('restore')
    def hide(self): self.calls.append('hide')


class FakeIcon:
    __module__ = 'pystray._appindicator'
    def __init__(self, *args):
        self.visible = False
        self.stopped = False
    def run_detached(self, setup): setup(self)
    def stop(self): self.stopped = True
    def notify(self, *args): pass


class Menu:
    SEPARATOR = object()
    def __init__(self, *items): self.items = items


def test_wayland_sem_watcher_nao_oculta_janela(monkeypatch):
    monkeypatch.setenv('XDG_SESSION_TYPE', 'wayland')
    monkeypatch.setattr(tray, '_status_notifier_disponivel', lambda: False)
    window = Window()
    t = tray.Tray(window, types.SimpleNamespace(config={}), lambda: None)
    assert not t.start()
    assert t.ao_fechar()
    assert not window.calls


def test_wayland_usa_appindicator_no_loop_gtk_e_controles(monkeypatch):
    monkeypatch.setenv('XDG_SESSION_TYPE', 'wayland')
    monkeypatch.delenv('PYSTRAY_BACKEND', raising=False)
    monkeypatch.setattr(tray, '_status_notifier_disponivel', lambda: True)
    monkeypatch.setitem(sys.modules, 'pystray', types.SimpleNamespace(
        Icon=FakeIcon, Menu=Menu, MenuItem=lambda *args, **kwargs: (args, kwargs)))
    window = Window()
    app = types.SimpleNamespace(config={'aviso_bandeja': True})
    closed = []
    t = tray.Tray(window, app, lambda: closed.append(True))
    assert t.start()
    assert t.icon.visible and t._gtk_detached
    assert 'PYSTRAY_BACKEND' not in __import__('os').environ
    assert not t.ao_fechar()
    t._mostrar()
    assert window.calls == ['hide', 'show', 'restore']
    t._sair()
    assert closed == [True] and not t.icon.visible and t.icon.stopped


def test_wayland_rejeita_backend_x11(monkeypatch):
    monkeypatch.setenv('XDG_SESSION_TYPE', 'wayland')
    monkeypatch.setattr(tray, '_status_notifier_disponivel', lambda: True)
    monkeypatch.setitem(sys.modules, 'pystray', types.SimpleNamespace(Icon=object))
    t = tray.Tray(None, None, lambda: None)
    assert not t.start()


def test_wayland_host_desapareceu_fecha_em_vez_de_ocultar(monkeypatch):
    monkeypatch.setenv('XDG_SESSION_TYPE', 'wayland')
    monkeypatch.setattr(tray, '_status_notifier_disponivel', lambda: False)
    window = Window()
    t = tray.Tray(window, types.SimpleNamespace(config={}), lambda: None)
    t.icon = FakeIcon()
    t._gtk_detached = True
    assert t.ao_fechar()
    assert not window.calls
