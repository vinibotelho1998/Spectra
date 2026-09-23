"""Exclusividade sobre o hardware de iluminacao, no Windows.

Controlador de RGB nao arbitra quem manda nele: ele obedece o ultimo
comando que chegou. Com dois programas escrevendo ao mesmo tempo, o
resultado e a luz piscando entre dois estados dezenas de vezes por
segundo, sem erro em lugar nenhum.

Por isso o Spectra reivindica o hardware para si: um mutex nomeado garante
instancia unica, e o `enforce` fecha os controladores concorrentes
conhecidos. `PROTEGIDOS` blinda o proprio Spectra e o servidor OpenRGB, que
e a camada de que ele depende.
"""

from __future__ import annotations

import ctypes
import subprocess
from ctypes import wintypes

from .admin import SAIDA_CONSOLE

CONCORRENTES = {
    "gcc": "GIGABYTE Control Center",
    "gigabytecontrolcenter": "GIGABYTE Control Center",
    "rgbfusion": "RGB Fusion",
    "gbt_rgb_sync_control": "GIGABYTE RGB Sync",
    "deepcool": "DeepCool",
    "icue": "Corsair iCUE",
    "corsair.service": "Corsair iCUE",
    "mysticlight": "MSI Mystic Light",
    "msi center": "MSI Center",
    "aurasvc": "ASUS Aura",
    "lightingservice": "ASUS Lighting Service",
    "armourycrate.service": "ASUS Armoury Crate",
    "nzxt cam": "NZXT CAM",
    "l-connect 3": "Lian Li L-Connect",
    "lconnect": "Lian Li L-Connect",
    "tt rgb plus": "Thermaltake RGB Plus",
    "masterplus": "Cooler Master MasterPlus",
    "signalrgb": "SignalRGB",
    "viper": "Patriot Viper RGB",
    "openrgb effects": "OpenRGB Effects",
}

PROTEGIDOS = {"openrgb", "python", "pythonw"}

# Nome curto demais para decidir sozinho. `gcc` e o GIGABYTE Control Center,
# mas tambem e o compilador GNU de toda instalacao MinGW e MSYS2, e derrubar
# um build com a arvore de processos junto e pior do que deixar o concorrente
# aberto. `viper` casa por prefixo com o ViPER4Windows, de audio. Para esses,
# o caminho do executavel precisa ter uma das marcas do fabricante.
CONFIRMA_CAMINHO = {"gcc": ("gigabyte",), "viper": ("patriot", "rgb")}

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]

ERROR_ALREADY_EXISTS = 183
_mutex = None


def acquire_single_instance(name: str = "Global\\Spectra_SingleInstance") -> bool:
    """Tenta ficar como unica instancia, via mutex nomeado do Windows.

    Devolve False quando ja existe outra instancia rodando. O mutex fica em
    variavel de modulo de proposito: ele precisa viver enquanto o processo
    viver, e o Windows o libera sozinho no encerramento, mesmo abrupto.
    """
    global _mutex
    _mutex = kernel32.CreateMutexW(None, False, name)
    if not _mutex:
        return True
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


def focus_existing_window(title: str = "Spectra") -> bool:
    """Traz para frente a janela da instancia que ja estava aberta.

    E o que faz o segundo clique no atalho parecer que abriu o programa, em
    vez de nao fazer nada.
    """
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    achou = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        if buf.value == title:
            user32.ShowWindow(hwnd, 9)
            user32.SetForegroundWindow(hwnd)
            achou.append(hwnd)
            return False
        return True

    user32.EnumWindows(cb, 0)
    return bool(achou)


def _listar_processos():
    try:
        r = subprocess.run(["tasklist", "/fo", "csv", "/nh"],
                           capture_output=True, text=True, timeout=15,
                           creationflags=0x08000000, **SAIDA_CONSOLE)
    except Exception:
        return []
    out = []
    for linha in r.stdout.splitlines():
        partes = [p.strip('"') for p in linha.split('","')]
        if len(partes) < 2:
            continue
        nome = partes[0].strip('"')
        try:
            pid = int(partes[1].strip('" '))
        except ValueError:
            continue
        base = nome[:-4].lower() if nome.lower().endswith(".exe") else nome.lower()
        out.append((pid, base, nome))
    return out


def _caminho_exe(pid: int) -> str:
    """Caminho do executavel de um processo, ou vazio se nao der para ler."""
    try:
        import psutil
        return psutil.Process(pid).exe() or ""
    except Exception:
        return ""


def scan() -> list:
    """Lista os processos de software de RGB concorrente que estao rodando.

    Casa por nome exato e por prefixo, porque varios fabricantes sufixam o
    executavel com versao.
    """
    achados = []
    for pid, base, nome in _listar_processos():
        if base in PROTEGIDOS:
            continue
        chave = base if base in CONCORRENTES else None
        if chave is None:
            for c in CONCORRENTES:
                if base.startswith(c):
                    chave = c
                    break
        if chave is None:
            continue
        marcas = CONFIRMA_CAMINHO.get(chave)
        if marcas:
            caminho = _caminho_exe(pid).lower()
            if not any(m in caminho for m in marcas):
                continue
        achados.append({"pid": pid, "processo": nome,
                        "rotulo": CONCORRENTES[chave]})
    return achados


def enforce() -> dict:
    """Fecha os concorrentes encontrados e relata o que caiu.

    Devolve o que foi fechado e o que resistiu. Falha e comum e esperada:
    varios desses programas rodam como servico e exigem privilegio maior do
    que o Spectra costuma ter.
    """
    alvos = scan()
    fechados, falhou = [], []
    for a in alvos:
        try:
            r = subprocess.run(["taskkill", "/PID", str(a["pid"]), "/T", "/F"],
                               capture_output=True, text=True, timeout=15,
                               creationflags=0x08000000, **SAIDA_CONSOLE)
            (fechados if r.returncode == 0 else falhou).append(a)
        except Exception:
            falhou.append(a)
    return {"fechados": fechados, "falhou": falhou,
            "total": len(alvos)}


def minimize_openrgb() -> bool:
    """Minimiza a janela do OpenRGB, se estiver aberta.

    O OpenRGB e a camada que o Spectra usa, entao nao se fecha. Mas a janela
    dele em primeiro plano confunde, e alguns modos da interface dele
    escrevem no hardware junto.

    Vale so para janela de um processo do OpenRGB. Pelo titulo apenas, o
    navegador aberto na pagina do projeto ou uma pasta chamada OpenRGB
    tambem eram minimizados a cada abertura do Spectra.
    """
    pids = {pid for pid, base, _nome in _listar_processos() if base == "openrgb"}
    if not pids:
        return False
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    psapi_ok = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        dono = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(dono))
        if dono.value not in pids:
            return True
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        if "OpenRGB" in buf.value:
            user32.ShowWindow(hwnd, 6)
            psapi_ok.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return bool(psapi_ok)
