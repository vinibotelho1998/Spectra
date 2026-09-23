"""Testes da varredura de concorrentes.

A lista de processos e o caminho de cada executavel vem de funcoes falsas:
nada aqui lista processo de verdade nem chega perto de fechar um.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

exclusive = pytest.importorskip("spectra.core.exclusive",
                                reason="modulo so existe no Windows")


def _console_falso(monkeypatch, saida: bytes):
    """Troca tasklist e taskkill por um processo que so escreve estes bytes."""
    real = subprocess.run
    codigo = "import sys; sys.stdout.buffer.write(%r)" % (saida,)

    def falso(args, **kw):
        return real([sys.executable, "-c", codigo], **kw)

    monkeypatch.setattr(subprocess, "run", falso)


def _maquina(monkeypatch, processos, caminhos):
    monkeypatch.setattr(exclusive, "_listar_processos", lambda: processos)
    monkeypatch.setattr(exclusive, "_caminho_exe",
                        lambda pid: caminhos.get(pid, ""), raising=False)


class TestVarredura:

    def test_compilador_gnu_nao_passa_por_gigabyte(self, monkeypatch):
        _maquina(monkeypatch,
                 [(10, "gcc", "gcc.exe"), (11, "gcc-ar", "gcc-ar.exe")],
                 {10: r"C:\msys64\ucrt64\bin\gcc.exe",
                  11: r"C:\msys64\ucrt64\bin\gcc-ar.exe"})
        assert exclusive.scan() == []

    def test_control_center_da_gigabyte_continua_na_lista(self, monkeypatch):
        _maquina(monkeypatch, [(20, "gcc", "GCC.exe")],
                 {20: r"C:\Program Files\GIGABYTE\Control Center\GCC.exe"})
        achados = exclusive.scan()
        assert [a["pid"] for a in achados] == [20]
        assert achados[0]["rotulo"] == "GIGABYTE Control Center"

    def test_caminho_ilegivel_nao_fecha_nome_ambiguo(self, monkeypatch):
        _maquina(monkeypatch, [(30, "gcc", "gcc.exe")], {})
        assert exclusive.scan() == []

    def test_viper4windows_de_audio_nao_passa_por_patriot(self, monkeypatch):
        _maquina(monkeypatch,
                 [(70, "viper4windowsctrlpanel", "ViPER4WindowsCtrlPanel.exe"),
                  (71, "viper4windowsservice", "ViPER4WindowsService.exe")],
                 {70: r"C:\Program Files\ViPER4Windows\ViPER4WindowsCtrlPanel.exe",
                  71: r"C:\Program Files\ViPER4Windows\ViPER4WindowsService.exe"})
        assert exclusive.scan() == []

    def test_viper_rgb_da_patriot_continua_na_lista(self, monkeypatch):
        _maquina(monkeypatch, [(72, "viper rgb", "Viper RGB.exe")],
                 {72: r"C:\Program Files (x86)\Patriot\Viper RGB\Viper RGB.exe"})
        assert [a["rotulo"] for a in exclusive.scan()] == ["Patriot Viper RGB"]

    def test_nome_inequivoco_nao_depende_do_caminho(self, monkeypatch):
        _maquina(monkeypatch,
                 [(40, "icue", "iCUE.exe"), (41, "signalrgb", "SignalRgb.exe")],
                 {})
        assert {a["rotulo"] for a in exclusive.scan()} == {"Corsair iCUE",
                                                           "SignalRGB"}

    def test_prefixo_com_versao_continua_casando(self, monkeypatch):
        _maquina(monkeypatch, [(50, "mysticlight3", "MysticLight3.exe")], {})
        assert [a["rotulo"] for a in exclusive.scan()] == ["MSI Mystic Light"]

    def test_protegidos_nunca_entram(self, monkeypatch):
        _maquina(monkeypatch,
                 [(60, "openrgb", "OpenRGB.exe"), (61, "python", "python.exe")],
                 {})
        assert exclusive.scan() == []


class TestSaidaDoConsole:
    """tasklist escreve na pagina OEM quando a saida vai para um pipe."""

    def test_nome_com_letra_fora_da_pagina_ansi_nao_esvazia_a_lista(self, monkeypatch):
        # 0x81 e o u com trema na pagina OEM e nao existe na ANSI
        _console_falso(monkeypatch, b'"iCUE.exe","12"\r\n"Gr\x81n.exe","13"\r\n')
        procs = exclusive._listar_processos()
        assert (12, "icue", "iCUE.exe") in procs
        assert (13, "grün", "Grün.exe") in procs

    def test_aviso_de_nenhuma_tarefa_em_outro_idioma_nao_quebra(self, monkeypatch):
        admin = pytest.importorskip("spectra.core.admin")
        _console_falso(monkeypatch, b"INFORMATION: Es werden keine Aufgaben mit "
                                    b"den angegebenen Kriterien ausgef\x81hrt.\r\n")
        assert admin._pids_openrgb() == []

    def test_processo_do_openrgb_continua_sendo_achado(self, monkeypatch):
        admin = pytest.importorskip("spectra.core.admin")
        _console_falso(monkeypatch, b'"OpenRGB.exe","4321"\r\n')
        assert admin._pids_openrgb() == [4321]


class User32Falso:
    """Area de trabalho de mentira: cada janela com processo dono e titulo."""

    def __init__(self, janelas):
        self.janelas = janelas
        self.minimizadas = []

        def dono(hwnd, ref):
            ref._obj.value = self.janelas[hwnd][0]
            return 1

        self.GetWindowThreadProcessId = dono

    def EnumWindows(self, cb, _lparam):
        for hwnd in self.janelas:
            if not cb(hwnd, 0):
                break
        return 1

    def IsWindowVisible(self, _hwnd):
        return 1

    def GetWindowTextW(self, hwnd, buf, _n):
        buf.value = self.janelas[hwnd][1]
        return len(buf.value)

    def ShowWindow(self, hwnd, _cmd):
        self.minimizadas.append(hwnd)
        return 1


class TestMinimizarOpenRGB:
    """Nenhuma janela de verdade: a user32 e trocada por uma falsa."""

    def _desktop(self, monkeypatch, processos, janelas):
        import ctypes
        falso = User32Falso(janelas)
        real = ctypes.WinDLL
        monkeypatch.setattr(ctypes, "WinDLL", lambda nome, **kw: (
            falso if nome == "user32" else real(nome, **kw)))
        monkeypatch.setattr(exclusive, "_listar_processos", lambda: processos)
        return falso

    def test_so_minimiza_a_janela_do_proprio_openrgb(self, monkeypatch):
        u = self._desktop(monkeypatch,
                          [(100, "openrgb", "OpenRGB.exe"),
                           (200, "msedge", "msedge.exe")],
                          {11: (200, "OpenRGB - pagina do projeto - Edge"),
                           12: (100, "OpenRGB 0.9"),
                           13: (200, "Outra coisa")})
        assert exclusive.minimize_openrgb() is True
        assert u.minimizadas == [12]

    def test_sem_processo_do_openrgb_nao_mexe_em_janela(self, monkeypatch):
        u = self._desktop(monkeypatch, [(200, "explorer", "explorer.exe")],
                          {21: (200, "OpenRGB")})
        assert exclusive.minimize_openrgb() is False
        assert u.minimizadas == []
