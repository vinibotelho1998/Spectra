import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spectra.app import SpectraApp
from spectra.core import protocol

COUNT = {"UPDATE_MODE": 0, "RESIZEZONE": 0, "UPDATE_LEDS": 0,
         "UPDATE_ZONE_LEDS": 0, "SET_CUSTOM_MODE": 0, "load_devices": 0}
NAMES = {protocol.UPDATE_MODE: "UPDATE_MODE",
         protocol.RESIZEZONE: "RESIZEZONE",
         protocol.UPDATE_LEDS: "UPDATE_LEDS",
         protocol.UPDATE_ZONE_LEDS: "UPDATE_ZONE_LEDS",
         protocol.SET_CUSTOM_MODE: "SET_CUSTOM_MODE"}


def instrument(client):
    real_send = client._send
    real_load = client.load_devices

    def send(dev, cmd, data=b""):
        n = NAMES.get(cmd)
        if n:
            COUNT[n] += 1
        return real_send(dev, cmd, data)

    def load():
        COUNT["load_devices"] += 1
        return real_load()

    client._send = send
    client.load_devices = load


def main():
    app = SpectraApp()
    if not app.connect():
        print(f"FALHA: {app.status_msg}")
        return 1
    antes = {f"{z['device']}:{z['zone']}": z["count"]
             for z in app.resizable_zones()}
    print(f"conectado | {len(app.renderer.all_devices)} devices | "
          f"headers: {list(antes.values())}")

    instrument(app.client)
    for k in COUNT:
        COUNT[k] = 0

    t0 = time.perf_counter()
    r = app.probe_multi_start(120)
    t_open = time.perf_counter() - t0
    print(f"\nabrir assistente: {t_open:.2f}s  ok={r.get('ok')}")
    abrir = dict(COUNT)
    for k, v in abrir.items():
        print(f"   {k:18} {v}")

    for k in COUNT:
        COUNT[k] = 0
    zs = app.resizable_zones()
    t0 = time.perf_counter()
    for i in range(7):
        app.probe_multi_paint([
            {"device": z["device"], "zone": z["zone"], "index": 60 - i * 7,
             "color": "#ff0000", "tail": True} for z in zs])
    t_round = time.perf_counter() - t0
    print(f"\n7 rodadas de pergunta: {t_round:.2f}s")
    for k, v in COUNT.items():
        if v:
            print(f"   {k:18} {v}")
    rodadas = dict(COUNT)

    for k in COUNT:
        COUNT[k] = 0
    t0 = time.perf_counter()
    app.probe_finish()
    t_close = time.perf_counter() - t0
    print(f"\nfechar assistente: {t_close:.2f}s")
    fechar = dict(COUNT)
    for k, v in fechar.items():
        print(f"   {k:18} {v}")

    total_modo = (abrir["UPDATE_MODE"] + rodadas["UPDATE_MODE"]
                  + fechar["UPDATE_MODE"])
    print(f"\nTROCAS DE MODO NO CICLO INTEIRO: {total_modo}")
    print(f"tempo total abrir+fechar: {t_open + t_close:.2f}s")
    print(f"headers depois: {[z['count'] for z in app.resizable_zones()]}")

    app.shutdown(blank=False)
    return 0 if total_modo <= 6 else 1


if __name__ == "__main__":
    sys.exit(main())
