from __future__ import annotations

import ctypes
import subprocess
from ctypes import wintypes

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

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]

ERROR_ALREADY_EXISTS = 183
_mutex = None


def acquire_single_instance(name: str = "Global\\DBXPrism_SingleInstance") -> bool:
    global _mutex
    _mutex = kernel32.CreateMutexW(None, False, name)
    if not _mutex:
        return True
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


def focus_existing_window(title: str = "DBX Prism") -> bool:
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
                           creationflags=0x08000000)
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


def scan() -> list:
    achados = []
    for pid, base, nome in _listar_processos():
        if base in PROTEGIDOS:
            continue
        rotulo = CONCORRENTES.get(base)
        if rotulo is None:
            for chave, r in CONCORRENTES.items():
                if base.startswith(chave):
                    rotulo = r
                    break
        if rotulo:
            achados.append({"pid": pid, "processo": nome, "rotulo": rotulo})
    return achados


def enforce() -> dict:
    alvos = scan()
    fechados, falhou = [], []
    for a in alvos:
        try:
            r = subprocess.run(["taskkill", "/PID", str(a["pid"]), "/T", "/F"],
                               capture_output=True, text=True, timeout=15,
                               creationflags=0x08000000)
            (fechados if r.returncode == 0 else falhou).append(a)
        except Exception:
            falhou.append(a)
    return {"fechados": fechados, "falhou": falhou,
            "total": len(alvos)}


def minimize_openrgb() -> bool:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    psapi_ok = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        if "OpenRGB" in buf.value:
            user32.ShowWindow(hwnd, 6)
            psapi_ok.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return bool(psapi_ok)
