import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from spectra import __version__

TITULO = f"Spectra {__version__}"
u = ctypes.WinDLL("user32", use_last_error=True)
u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                           wintypes.LPARAM]
WM_CLOSE = 0x0010


def janelas(titulo=TITULO):
    achados = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        buf = ctypes.create_unicode_buffer(300)
        u.GetWindowTextW(h, buf, 300)
        if buf.value == titulo:
            achados.append((h, bool(u.IsWindowVisible(h))))
        return True

    u.EnumWindows(cb, 0)
    return achados


def janelas_classe(prefixo):
    achados = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        buf = ctypes.create_unicode_buffer(300)
        u.GetClassNameW(h, buf, 300)
        if buf.value.startswith(prefixo):
            achados.append(h)
        return True

    u.EnumWindows(cb, 0)
    return achados


def visiveis():
    return [h for h, v in janelas() if v]


def servidor_no_ar():
    import socket
    try:
        with socket.create_connection(("127.0.0.1", 7311), timeout=1):
            return True
    except OSError:
        return False


def main():
    subprocess.run(["taskkill", "/F", "/IM", "pythonw.exe", "/FI",
                    "WINDOWTITLE eq *"], capture_output=True)
    time.sleep(2)

    exe = os.path.join(RAIZ, ".venv", "Scripts", "pythonw.exe")
    proc = subprocess.Popen([exe, os.path.join(RAIZ, "run.py")],
                            creationflags=0x00000008 | 0x00000200)
    print("app lancado, esperando a janela...")

    for _ in range(60):
        time.sleep(1)
        if visiveis():
            break
    vis = visiveis()
    print(f"1. janelas '{TITULO}' visiveis: {len(vis)}  (todas: {len(janelas())})")
    if not vis:
        print("   FALHA: a janela nao apareceu")
        return 1
    print(f"2. servidor no ar: {servidor_no_ar()}")

    tray_ok = False
    for _ in range(30):
        if any(True for _ in janelas_classe("spectra")):
            tray_ok = True
            break
        time.sleep(0.5)
    print(f"3. icone de bandeja ativo: {tray_ok}")

    print("4. mandando WM_CLOSE...")
    u.SendMessageW(vis[0], WM_CLOSE, 0, 0)
    time.sleep(4)

    ainda = visiveis()
    vivo = servidor_no_ar()
    print(f"5. janelas visiveis apos fechar: {len(ainda)}  (esperado 0)")
    print(f"6. servidor AINDA no ar: {vivo}  (esperado True = so minimizou)")

    ok = (len(ainda) == 0) and vivo and tray_ok
    print("\n" + ("TESTE OK: fechar minimiza, o app continua rodando"
                  if ok else "TESTE FALHOU"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
