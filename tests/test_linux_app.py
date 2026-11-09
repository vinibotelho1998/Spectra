"""Caminhos de configuracao e inicializacao do OpenRGB no Linux."""
import os
import sys
import types
from unittest.mock import patch

import pytest
from spectra import app as app_module


@pytest.fixture
def aplicativo(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, 'CONFIG_FILE', str(tmp_path / 'config.json'))
    monkeypatch.setattr(app_module, 'CONFIG_DIR', str(tmp_path))
    monkeypatch.setattr(app_module, 'PROFILES_DIR', str(tmp_path / 'profiles'))
    monkeypatch.setattr(app_module.sys, 'platform', 'linux')
    return app_module.SpectraApp()


def test_config_usa_xdg(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module.sys, 'platform', 'linux')
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    assert app_module._config_root() == str(tmp_path / 'spectra')


def test_openrgb_path_e_appimage(aplicativo, tmp_path, monkeypatch):
    exe = tmp_path / 'OpenRGB.AppImage'
    exe.write_text('#!/bin/sh\n')
    assert not aplicativo.set_openrgb_exe(str(exe))['ok']
    exe.chmod(0o755)
    outro = tmp_path / 'outro'
    outro.write_text('#!/bin/sh\n')
    outro.chmod(0o755)
    assert not aplicativo.set_openrgb_exe(str(outro))['ok']
    assert aplicativo.set_openrgb_exe(str(exe))['ok']
    assert aplicativo._openrgb_exe() == str(exe)
    with patch('spectra.app.subprocess.Popen') as launch:
        assert aplicativo._start_openrgb()
        assert launch.call_args.args[0] == [str(exe), '--server', '--server-port', '6742']
        assert launch.call_args.kwargs['start_new_session'] is True
    aplicativo.config.pop('openrgb_exe')
    monkeypatch.setattr(app_module.shutil, 'which', lambda x: '/usr/bin/openrgb' if x == 'openrgb' else None)
    assert aplicativo._openrgb_exe() == '/usr/bin/openrgb'


def test_servidor_local_usa_porta_configurada(aplicativo, monkeypatch):
    aplicativo.port = 6743
    monkeypatch.setattr(aplicativo, '_openrgb_exe', lambda: '/usr/bin/openrgb')
    with patch('spectra.app.subprocess.Popen') as launch:
        assert aplicativo._start_openrgb()
        assert launch.call_args.args[0] == ['/usr/bin/openrgb', '--server', '--server-port', '6743']


def test_servidor_remoto_nao_inicia_processo_local(aplicativo, monkeypatch):
    aplicativo.host = '192.0.2.10'
    monkeypatch.setattr(app_module, '_port_open', lambda *a, **k: False)
    with patch.object(aplicativo, '_start_openrgb') as launch:
        assert not aplicativo.ensure_openrgb()
        launch.assert_not_called()


def test_elevacao_linux_nao_oferece_tarefa_windows(aplicativo):
    assert aplicativo.check_elevacao()['servidor_elevado'] is None
    assert not aplicativo.reparar_elevacao()['ok']


def test_falha_criacao_janela_abre_navegador_e_fecha_bandeja(aplicativo, monkeypatch):
    import run
    from spectra import tray as tray_module

    eventos = []
    class TrayFalsa:
        icon = object()
        def __init__(self, *args): pass
        def start(self): return True
        def stop(self): eventos.append('bandeja parada')
        def _mostrar(self): pass

    def falhar(*args, **kwargs):
        raise RuntimeError('GTK indisponivel')

    monkeypatch.setitem(sys.modules, 'webview', types.SimpleNamespace(create_window=falhar))
    monkeypatch.setattr(tray_module, 'Tray', TrayFalsa)
    monkeypatch.setattr(run.webbrowser, 'open', lambda url: eventos.append(url))
    monkeypatch.setattr(run.time, 'sleep', lambda _: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        run.run_window('http://127.0.0.1:7311/', aplicativo)
    assert eventos[0:2] == ['bandeja parada', 'http://127.0.0.1:7311/']
    assert aplicativo.ao_mostrar_janela is None


def test_identidade_da_janela_linux_corresponde_ao_desktop(monkeypatch):
    import sys
    import types
    import run
    calls = []
    gi = types.ModuleType('gi')
    gi.require_version = lambda *args: calls.append(('version', *args))
    repository = types.ModuleType('gi.repository')
    repository.GLib = types.SimpleNamespace(
        set_prgname=lambda value: calls.append(('prgname', value)),
        set_application_name=lambda value: calls.append(('name', value)))
    repository.Gdk = types.SimpleNamespace(
        set_program_class=lambda value: calls.append(('class', value)))
    monkeypatch.setitem(sys.modules, 'gi', gi)
    monkeypatch.setitem(sys.modules, 'gi.repository', repository)
    assert run.configurar_identidade_linux()
    assert ('prgname', 'spectra') in calls
    assert ('class', 'spectra') in calls
