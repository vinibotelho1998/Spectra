import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spectra.app import SpectraApp


def openrgb_vivo() -> bool:
    r = subprocess.run(["tasklist", "/fi", "IMAGENAME eq OpenRGB.exe", "/nh"],
                       capture_output=True, text=True, timeout=15)
    return "OpenRGB.exe" in r.stdout


def matar_openrgb() -> bool:
    subprocess.run(["schtasks", "/end", "/tn", "Spectra - OpenRGB SDK Server"],
                   capture_output=True, timeout=15)
    for _ in range(20):
        if not openrgb_vivo():
            return True
        time.sleep(0.5)
    subprocess.run(["taskkill", "/F", "/IM", "OpenRGB.exe"],
                   capture_output=True, timeout=15)
    for _ in range(10):
        if not openrgb_vivo():
            return True
        time.sleep(0.5)
    return False


def main():
    app = SpectraApp()
    if not app.connect():
        print(f"FALHA inicial: {app.status_msg}")
        return 1
    time.sleep(2.0)
    fps0 = app.renderer.fps_actual
    print(f"1. conectado | {len(app.renderer.canvas.devices)} devices | "
          f"{app.renderer.canvas.n} leds | {fps0:.1f} fps")

    print("\n2. matando o OpenRGB no meio do render...")
    if not matar_openrgb():
        print("   FALHA: nao consegui derrubar o OpenRGB (roda elevado?)")
        app.shutdown()
        return 1
    print("   OpenRGB encerrado, confirmado")

    for _ in range(40):
        time.sleep(0.25)
        if app.renderer.connection_lost:
            break
    print(f"   perdeu a conexao: {app.renderer.connection_lost} "
          f"(status: {app.status_msg})")
    if not app.renderer.connection_lost:
        print("   FALHA: o render nao percebeu a queda")
        app.shutdown()
        return 1

    print("\n3. esperando o vigia reconectar (ate 90s)...")
    t0 = time.perf_counter()
    ok = False
    for _ in range(180):
        time.sleep(0.5)
        if app.connected and app.renderer._thread and app.renderer._thread.is_alive():
            if not app.renderer.connection_lost:
                ok = True
                break
    dt = time.perf_counter() - t0

    if not ok:
        print(f"   FALHA: nao reconectou em {dt:.0f}s (status: {app.status_msg})")
        app.shutdown()
        return 1

    time.sleep(3.0)
    print(f"   RECONECTOU em {dt:.0f}s | status: {app.status_msg}")
    print(f"   reconexoes: {app.reconnects} | fps: {app.renderer.fps_actual:.1f} | "
          f"devices: {len(app.renderer.canvas.devices)} | "
          f"leds: {app.renderer.canvas.n}")

    dram = [d for d in app.renderer.all_devices if d.type_name == "DRAM"]
    print(f"   RAM detectada apos reconectar: {len(dram)} pente(s) "
          f"-> {'ELEVADO ok' if dram else 'SEM privilegio'}")

    bom = app.renderer.fps_actual > 5 and app.renderer.canvas.n > 0
    app.shutdown()
    print("\n" + ("TESTE OK" if bom else "TESTE FALHOU"))
    return 0 if bom else 1


if __name__ == "__main__":
    sys.exit(main())
