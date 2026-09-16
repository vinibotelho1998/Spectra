"""Sobe a interface com dispositivos falsos, sem OpenRGB nem hardware.

Serve para mexer na interface sem tocar nos LEDs de verdade e sem fechar
outro software de RGB. A configuracao vai para `config/uidev`, separada
da configuracao real do app.

    python tools/uidev.py                  # http://127.0.0.1:7333/
    python tools/uidev.py --browser        # abre no navegador padrao
    python tools/uidev.py --zero           # headers ARGB com 0 LEDs (primeira execucao)
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import webbrowser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from spectra import app as app_mod
from spectra.core.protocol import MODE_FLAG_HAS_PER_LED_COLOR, Device, Mode, Zone
from spectra.engine.renderer import Renderer
from spectra.server import serve


def mode(i, name, flags=0):
    return Mode(i, name, i, flags, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, [])


def zone(i, name, count, ztype=1, resizable=False):
    lo, hi = (0, 512) if resizable else (count, count)
    return Zone(i, name, ztype, lo, hi, count)


def refresh_leds(d: Device):
    acc, leds = 0, []
    for z in d.zones:
        z.start_idx = acc
        acc += z.leds_count
        leds += [f"{z.name} LED {i + 1}" for i in range(z.leds_count)]
    d.leds = leds
    d.colors = [(0, 0, 0)] * len(leds)


def device(index, dtype, name, vendor, zones, serial="", location="",
           has_direct=True):
    modes = ([mode(0, "Direct", MODE_FLAG_HAS_PER_LED_COLOR),
              mode(1, "Static"), mode(2, "Off")]
             if has_direct else [mode(0, "Static"), mode(1, "Off")])
    d = Device(index, dtype, name, vendor, f"{name} (bancada)", "1.0",
               serial, location, modes, 1, zones, [], [])
    refresh_leds(d)
    return d


def bancada(zero=False):
    n = (lambda c: 0 if zero else c)
    return [
        device(0, 0, "X870M AORUS ELITE WIFI7", "GIGABYTE", [
            zone(0, "ARGB_V2_1", n(22), resizable=True),
            zone(1, "ARGB_V2_2", n(6), resizable=True),
            zone(2, "ARGB_V2_3", n(29), resizable=True),
            zone(3, "Chipset", 1, ztype=0),
        ], serial="MB-0001"),
        device(1, 1, "Corsair Vengeance RGB", "Corsair", [
            zone(0, "DIMM A2", 10), zone(1, "DIMM B2", 10),
        ], serial="RAM-0001"),
        device(2, 2, "ASUS TUF RTX 4070", "ASUS", [zone(0, "GPU", 6)],
               location="I2C 0x67"),
        device(3, 6, "Logitech G Pro", "Logitech", [
            zone(0, "Logo", 1, ztype=0), zone(1, "Scroll", 1, ztype=0),
        ], serial="MOUSE-1", has_direct=False),
    ]


class FakeClient:
    """Cliente que aceita tudo e guarda o ultimo quadro de cada dispositivo."""

    def __init__(self, devices):
        self.devices = devices
        self.protocol = 5
        self.frames = 0
        self.last = {}

    def connect(self, timeout=4.0):
        pass

    def close(self):
        pass

    @property
    def connected(self):
        return True

    def controller_count(self):
        return len(self.devices)

    def load_devices(self):
        return list(self.devices)

    def set_direct_mode(self, i):
        d = self.devices[i]
        m = d.direct_mode()
        if m is None:
            return False
        d.active_mode = m.index
        return True

    def update_leds(self, i, colors, count):
        self.frames += 1
        self.last[i] = colors

    def update_zone_leds(self, i, zi, colors, count):
        self.last[(i, zi)] = colors

    def resize_zone(self, i, zi, size):
        d = self.devices[i]
        z = d.zones[zi]
        z.leds_count = max(z.leds_min, min(z.leds_max, int(size)))
        refresh_leds(d)


class DevApp(app_mod.SpectraApp):
    """SpectraApp que conecta numa bancada falsa em vez do OpenRGB."""

    def __init__(self, devices):
        super().__init__()
        self.client = FakeClient(devices)

    def ensure_openrgb(self, wait=0.0):
        return True

    def enforce_exclusive(self):
        return {"ok": True, "skipped": True, "fechados": [], "falhou": []}

    def connect(self, exclusive_pass=False):
        devices = self.client.load_devices()
        self.connected = True
        self.status_msg = "bancada falsa, sem hardware"
        self._apply_zone_sizes(devices)
        settings = dict(self.config.get("settings") or {})
        settings["enabled_devices"] = self.config.get("enabled_devices") or {}
        if self.renderer is None:
            self.renderer = Renderer(self.client, devices,
                                     self.config.get("layout"), settings)
            self._load_startup_scene()
        else:
            self.renderer.client = self.client
            self.renderer.layout_config = self.config.get("layout") or {}
            self.renderer.settings.update(settings)
            self.renderer.set_devices(devices)
        self.renderer.connection_lost = False
        self.renderer.arm_direct()
        self.renderer.start()
        self._sync_sources()
        self.start_watchdog()
        return True


def isolate_config(path):
    os.makedirs(os.path.join(path, "profiles"), exist_ok=True)
    app_mod.CONFIG_DIR = path
    app_mod.PROFILES_DIR = os.path.join(path, "profiles")
    app_mod.CONFIG_FILE = os.path.join(path, "config.json")


def main():
    ap = argparse.ArgumentParser(prog="uidev")
    ap.add_argument("--port", type=int, default=7333)
    ap.add_argument("--browser", action="store_true")
    ap.add_argument("--zero", action="store_true",
                    help="headers ARGB comecam com 0 LEDs, como na primeira execucao")
    ap.add_argument("--config", default=os.path.join(ROOT, "config", "uidev"))
    args = ap.parse_args()

    isolate_config(args.config)
    app = DevApp(bancada(zero=args.zero))
    app.connect()
    httpd = serve(app, port=args.port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{args.port}/"
    print(f"[uidev] {app.renderer.canvas.n} leds falsos em {url}", flush=True)
    if args.browser:
        webbrowser.open(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()
        app.shutdown(blank=False)


if __name__ == "__main__":
    main()
