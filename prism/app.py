from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time

import numpy as np

from . import effects as fx
from .core.protocol import OpenRGBClient, OpenRGBError
from .engine import blend
from .engine.canvas import device_key
from .engine.palette import PALETTE_NAMES, hex_to_rgb, palette_preview
from .engine.renderer import Layer, Renderer
from . import presets as ps
from .sources.audio import AudioSource
from .sources.screen import ScreenSource
from .sources.sensors import SensorSource


def _app_root() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _config_root() -> str:
    if getattr(sys, "frozen", False):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "DBXPrism")
    return os.path.join(ROOT, "config")


ROOT = _app_root()
CONFIG_DIR = _config_root()
PROFILES_DIR = os.path.join(CONFIG_DIR, "profiles")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

OPENRGB_CANDIDATES = [
    r"C:\Program Files\OpenRGB\OpenRGB.exe",
    r"C:\Program Files (x86)\OpenRGB\OpenRGB.exe",
]
OPENRGB_TASK = "DBX Prism - OpenRGB SDK Server"

CASE_SPOTS = {
    "topo_esq":     (0.22, 0.10), "topo_centro": (0.50, 0.10),
    "topo_dir":     (0.78, 0.10),
    "frente_cima":  (0.12, 0.28), "frente_meio": (0.12, 0.50),
    "frente_baixo": (0.12, 0.74),
    "traseira":     (0.88, 0.30),
    "ram":          (0.50, 0.20),
    "placa_mae":    (0.50, 0.42),
    "meio":         (0.50, 0.50),
    "gpu":          (0.50, 0.64),
    "lateral":      (0.50, 0.80),
    "base_esq":     (0.28, 0.90), "base_centro": (0.50, 0.90),
    "base_dir":     (0.72, 0.90),
}

CASE_SPOT_LABELS = [
    ("topo_esq", "Topo esquerda"), ("topo_centro", "Topo centro"),
    ("topo_dir", "Topo direita"),
    ("frente_cima", "Frente cima"), ("frente_meio", "Frente meio"),
    ("frente_baixo", "Frente baixo"),
    ("traseira", "Traseira"), ("ram", "Perto da RAM"),
    ("placa_mae", "Placa-mae"), ("meio", "Meio"),
    ("gpu", "GPU / cabo da GPU"), ("lateral", "Lateral"),
    ("base_esq", "Base esquerda"), ("base_centro", "Base centro"),
    ("base_dir", "Base direita"),
]

DEFAULT_SCENE = {
    "layers": [{"effect": "rainbow_wave", "params": {"speed": 0.35},
                "blend": "normal", "opacity": 1.0, "enabled": True,
                "name": "Onda base"}],
    "settings": {"brightness": 1.0, "gamma": 2.2, "fps": 60, "smoothing": 0.0},
}


def _port_open(host="127.0.0.1", port=6742, timeout=0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class PrismApp:
    def __init__(self, host="127.0.0.1", port=6742):
        os.makedirs(PROFILES_DIR, exist_ok=True)
        self.host, self.port = host, port
        self.client = OpenRGBClient(host, port, name="DBX Prism")
        self.renderer: Renderer | None = None
        self.config = self._load_config()
        self.audio = None
        self.screen = None
        self.sensors = None
        self.status_msg = "iniciando"
        self.connected = False
        self._lock = threading.RLock()
        self._watchdog = None
        self._watchdog_stop = threading.Event()
        self.reconnects = 0
        self.last_exclusive = None
        self.last_error_exclusive = None

    def _load_config(self) -> dict:
        base = {"layout": {}, "enabled_devices": {}, "zone_sizes": {},
                "settings": dict(DEFAULT_SCENE["settings"]),
                "sources": {"audio": {"device": None}, "screen": {"output": 0, "fps": 30}},
                "autostart_openrgb": True, "last_profile": None,
                "exclusive_mode": True}
        if os.path.isfile(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, encoding="utf-8") as f:
                    base.update(json.load(f))
            except Exception:
                pass
        return base

    def save_config(self):
        with self._lock:
            if self.renderer:
                self.config["settings"] = {
                    k: self.renderer.settings[k]
                    for k in ("brightness", "gamma", "fps", "smoothing")}
                self.config["enabled_devices"] = self.renderer.settings["enabled_devices"]
            tmp = CONFIG_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            os.replace(tmp, CONFIG_FILE)

    def ensure_openrgb(self, wait: float = 25.0) -> bool:
        if _port_open(self.host, self.port):
            return True
        if not self.config.get("autostart_openrgb"):
            return False
        self.status_msg = "subindo o servidor OpenRGB"
        started = False
        try:
            r = subprocess.run(
                ["schtasks", "/run", "/tn", OPENRGB_TASK],
                capture_output=True, timeout=10,
                creationflags=0x08000000)
            started = r.returncode == 0
        except Exception:
            started = False

        if not started:
            exe = next((p for p in OPENRGB_CANDIDATES if os.path.isfile(p)), None)
            if not exe:
                self.status_msg = "OpenRGB nao encontrado"
                return False
            try:
                subprocess.Popen(
                    [exe, "--server", "--startminimized"],
                    creationflags=0x00000008 | 0x00000200,
                    close_fds=True)
            except Exception as exc:
                self.status_msg = f"falha ao iniciar OpenRGB: {exc}"
                return False
        deadline = time.time() + wait
        while time.time() < deadline:
            if _port_open(self.host, self.port):
                return True
            time.sleep(0.5)
        self.status_msg = "OpenRGB nao respondeu a tempo"
        return False

    def enforce_exclusive(self) -> dict:
        from .core import exclusive
        if not self.config.get("exclusive_mode", True):
            return {"ok": True, "skipped": True, "fechados": [], "falhou": []}
        r = exclusive.enforce()
        r["openrgb_minimizado"] = exclusive.minimize_openrgb()
        r["ok"] = True
        self.last_exclusive = r
        if r["fechados"]:
            nomes = sorted({c["rotulo"] for c in r["fechados"]})
            self.status_msg = "fechei: " + ", ".join(nomes)
        return r

    def connect(self, exclusive_pass: bool = False) -> bool:
        if exclusive_pass:
            try:
                self.enforce_exclusive()
            except Exception as exc:
                self.last_error_exclusive = str(exc)
        self.ensure_openrgb()
        try:
            self.client.close()
            self.client.connect()
            devices = self.client.load_devices()
            espera = 0.0
            while not devices and espera < 20.0:
                self.status_msg = "OpenRGB detectando hardware"
                time.sleep(1.5)
                espera += 1.5
                devices = self.client.load_devices()
        except (OpenRGBError, OSError) as exc:
            self.connected = False
            self.status_msg = f"sem conexao com o OpenRGB: {exc}"
            return False

        self.connected = True
        self.status_msg = "conectado"
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

    def start_watchdog(self):
        if self._watchdog and self._watchdog.is_alive():
            return
        self._watchdog_stop.clear()
        self._watchdog = threading.Thread(target=self._watchdog_loop,
                                          name="prism-watchdog", daemon=True)
        self._watchdog.start()

    def _watchdog_loop(self):
        delay = 2.0
        while not self._watchdog_stop.wait(delay):
            r = self.renderer
            if r is None:
                continue
            if getattr(self, "_probe_session", None) is not None:
                delay = 2.0
                continue
            alive = bool(r._thread and r._thread.is_alive())
            if self.connected and alive and not r.connection_lost:
                delay = 2.0
                continue

            self.connected = False
            self.status_msg = "conexao com o OpenRGB caiu; reconectando"
            if self.connect():
                self.reconnects += 1
                self.status_msg = f"reconectado ({self.reconnects}x)"
                delay = 2.0
            else:
                delay = min(delay * 1.7, 20.0)

    def _apply_zone_sizes(self, devices):
        sizes = self.config.get("zone_sizes") or {}
        changed = False
        for dev in devices:
            key = device_key(dev)
            for zone in dev.zones:
                want = sizes.get(f"{key}:{zone.index}")
                if want is None or int(want) == zone.leds_count:
                    continue
                if zone.leds_min == zone.leds_max:
                    continue
                try:
                    self.client.resize_zone(dev.index, zone.index, int(want))
                    changed = True
                except OpenRGBError:
                    pass
        if changed:
            time.sleep(0.6)
            try:
                devices[:] = self.client.load_devices()
            except OpenRGBError:
                pass

    def _load_startup_scene(self):
        name = self.config.get("last_profile")
        if name and self.load_profile(name, apply_only=True):
            return
        self.renderer.load_scene(DEFAULT_SCENE)

    def shutdown(self, blank=True):
        self._watchdog_stop.set()
        try:
            self.save_config()
        except Exception:
            pass
        for src in (self.audio, self.screen, self.sensors):
            if src:
                try:
                    src.stop()
                except Exception:
                    pass
        if self.renderer:
            self.renderer.stop()
            if blank:
                self.renderer.blank()
        self.client.close()

    def _needed_sources(self) -> set:
        need = set()
        if not self.renderer:
            return need
        for layer in self.renderer.layers:
            if not layer.enabled:
                continue
            d = fx.get(layer.effect_id)
            if d:
                need.update(d.needs)
        return need

    def _sync_sources(self):
        need = self._needed_sources()
        ctx = self.renderer.ctx

        if "audio" in need:
            if self.audio is None:
                dev = (self.config.get("sources", {}).get("audio") or {}).get("device")
                self.audio = AudioSource(ctx.audio, device_index=dev)
            if not self.audio.running:
                self.audio.start()
        elif self.audio and self.audio.running:
            self.audio.stop()

        if "screen" in need:
            cfg = (self.config.get("sources", {}).get("screen") or {})
            if self.screen is None:
                self.screen = ScreenSource(ctx.screen,
                                           output_idx=cfg.get("output", 0),
                                           fps=cfg.get("fps", 30))
            if not self.screen.running:
                self.screen.start()
        elif self.screen and self.screen.running:
            self.screen.stop()

        if "sensors" in need:
            if self.sensors is None:
                self.sensors = SensorSource(ctx.sensors)
            if not self.sensors.running:
                self.sensors.start()
        elif self.sensors and self.sensors.running:
            self.sensors.stop()

    def set_layers(self, layers_json):
        with self._lock:
            self.renderer.set_layers([Layer.from_json(d) for d in layers_json])
            self._sync_sources()

    def add_layer(self, effect_id: str, **kw):
        with self._lock:
            d = fx.get(effect_id)
            layer = Layer(effect_id, kw.get("params"), kw.get("blend", "normal"),
                          kw.get("opacity", 1.0), True, kw.get("targets"),
                          kw.get("name") or (d.label if d else effect_id))
            self.renderer.add_layer(layer)
            self._sync_sources()
            return layer.to_json()

    def update_layer(self, layer_id: str, patch: dict):
        with self._lock:
            layer = self.renderer.get_layer(layer_id)
            if not layer:
                return None
            if "effect" in patch and patch["effect"] != layer.effect_id:
                layer.effect_id = patch["effect"]
                layer.params = {}
                layer.state.clear()
            if "params" in patch:
                layer.params.update(patch["params"])
            for k, attr in (("blend", "blend"), ("opacity", "opacity"),
                            ("enabled", "enabled"), ("name", "name")):
                if k in patch:
                    setattr(layer, attr, patch[k])
            if "targets" in patch:
                layer.targets = list(patch["targets"] or [])
                layer._mask_key = None
            self._sync_sources()
            return layer.to_json()

    def remove_layer(self, layer_id: str):
        with self._lock:
            self.renderer.remove_layer(layer_id)
            self._sync_sources()

    def reorder_layers(self, order):
        with self._lock:
            by_id = {l.id: l for l in self.renderer.layers}
            self.renderer.layers = [by_id[i] for i in order if i in by_id]

    def update_settings(self, patch: dict):
        with self._lock:
            for k in ("brightness", "gamma", "fps", "smoothing", "paused"):
                if k in patch:
                    self.renderer.settings[k] = patch[k]
            if "enabled_devices" in patch:
                self.renderer.settings["enabled_devices"] = patch["enabled_devices"]
                self.config["enabled_devices"] = patch["enabled_devices"]
                self.renderer.rebuild()
                self.renderer.arm_direct()
            self.save_config()

    def set_zone_geometry(self, device_key_: str, zone_index: int, geometry: dict):
        with self._lock:
            layout = self.config.setdefault("layout", {})
            dev = layout.setdefault(device_key_, {}).setdefault("zones", {})
            dev[str(zone_index)] = geometry
            self.renderer.layout_config = layout
            self.renderer.rebuild()
            self.save_config()

    def reset_layout(self):
        with self._lock:
            self.config["layout"] = {}
            self.renderer.layout_config = {}
            self.renderer.rebuild()
            self.save_config()

    def resize_zones(self, changes, persist: bool = True):
        with self._lock:
            touched = False
            for device_key_, zone_index, size in changes:
                dev = next((d for d in self.renderer.all_devices
                            if device_key(d) == device_key_), None)
                if dev is None:
                    continue
                zone = next((z for z in dev.zones if z.index == zone_index), None)
                if zone is None or zone.leds_count == int(size):
                    continue

                if zone.leds_count > int(size):
                    try:
                        self.client.update_zone_leds(
                            dev.index, zone_index,
                            b"\x00\x00\x00\x00" * zone.leds_count,
                            zone.leds_count)
                    except OpenRGBError:
                        pass
                try:
                    self.client.resize_zone(dev.index, zone_index, int(size))
                    touched = True
                except OpenRGBError as exc:
                    return {"ok": False, "error": str(exc)}
                if persist:
                    self.config.setdefault("zone_sizes", {})[
                        f"{device_key_}:{zone_index}"] = int(size)

            if persist:
                self.save_config()
            if not touched:
                return {"ok": True, "changed": False}

            time.sleep(0.6)
            try:
                devices = self.client.load_devices()
            except OpenRGBError as exc:
                return {"ok": False, "error": str(exc)}
            self.renderer.set_devices(devices)
            self.renderer.arm_direct()
            return {"ok": True, "changed": True}

    def resize_zone(self, device_key_: str, zone_index: int, size: int,
                    persist: bool = True):
        return self.resize_zones([(device_key_, zone_index, size)], persist)

    def _probe_open_session(self, probe_max: int):
        sess = {"sizes": {}, "commits": {},
                "was_paused": bool(self.renderer.settings.get("paused"))}
        self.renderer.settings["paused"] = True
        time.sleep(0.08)

        changes = []
        for z in self.resizable_zones():
            sess["sizes"][f"{z['device']}:{z['zone']}"] = z["count"]
            changes.append((z["device"], z["zone"],
                            int(min(z["max"], max(probe_max, 1)))))
        self.resize_zones(changes, persist=False)

        self.renderer.blank()
        self._probe_session = sess
        return sess

    def probe_start(self, device_key_: str, zone_index: int,
                    probe_max: int = 256):
        with self._lock:
            dev = next((d for d in self.renderer.all_devices
                        if device_key(d) == device_key_), None)
            if dev is None:
                return {"ok": False, "error": "device nao encontrado"}
            zone = next((z for z in dev.zones if z.index == zone_index), None)
            if zone is None:
                return {"ok": False, "error": "zona nao encontrada"}
            if zone.leds_min == zone.leds_max:
                return {"ok": False, "error": "esta zona tem tamanho fixo"}

            if getattr(self, "_probe_session", None) is None:
                self._probe_open_session(probe_max)
            else:
                self.renderer.blank()

            zone = next(z for z in next(
                d for d in self.renderer.all_devices
                if device_key(d) == device_key_).zones if z.index == zone_index)
            n = zone.leds_count
            if n == 0:
                return {"ok": False, "error": "nao consegui expandir esta zona"}

            self._probe = {"device": device_key_, "zone": zone_index, "n": n}
            self.probe_paint(1, "fill")
            return {"ok": True, "probe_max": n}

    def probe_paint(self, count: int, mode: str = "fill"):
        pr = getattr(self, "_probe", None)
        if not pr:
            return {"ok": False, "error": "nenhuma descoberta em andamento"}
        dev = next((d for d in self.renderer.all_devices
                    if device_key(d) == pr["device"]), None)
        if dev is None:
            return {"ok": False, "error": "device sumiu"}
        zone = next((z for z in dev.zones if z.index == pr["zone"]), None)
        if zone is None or zone.leds_count == 0:
            return {"ok": False, "error": "zona sem leds"}

        n = zone.leds_count
        k = int(max(0, min(count, n)))
        buf = np.zeros((n, 4), dtype=np.uint8)
        if mode == "dot":
            if k > 0:
                buf[k - 1, :3] = (255, 255, 255)
        elif mode == "ruler":
            for i in range(n):
                if i % 10 == 9:
                    buf[i, :3] = (255, 255, 255)
                else:
                    buf[i, :3] = (0, 140, 255) if (i // 10) % 2 == 0 else (255, 60, 0)
        else:
            if k > 0:
                buf[:k, :3] = (0, 110, 255)
                buf[k - 1, :3] = (255, 255, 255)
        try:
            self.client.update_zone_leds(dev.index, zone.index, buf.tobytes(), n)
        except OpenRGBError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "count": k, "of": n}

    def probe_stop(self, commit=None):
        with self._lock:
            pr = getattr(self, "_probe", None)
            if not pr:
                return {"ok": False, "error": "nenhuma descoberta em andamento"}
            sess = getattr(self, "_probe_session", None)
            if sess is not None and commit:
                sess["commits"][f"{pr['device']}:{pr['zone']}"] = int(commit)
            self._probe = None
            if sess is not None:
                self.renderer.blank()
            return {"ok": True, "committed": int(commit) if commit else None}

    def probe_commit(self, device_key_: str, zone_index: int, count: int):
        with self._lock:
            sess = getattr(self, "_probe_session", None)
            if sess is None:
                return {"ok": False, "error": "nenhuma sondagem em andamento"}
            sess["commits"][f"{device_key_}:{zone_index}"] = int(count)
            return {"ok": True}

    def probe_finish(self):
        with self._lock:
            sess = getattr(self, "_probe_session", None)
            self._probe = None
            if sess is None:
                return {"ok": True, "applied": {}}
            self._probe_session = None

            applied = {}
            keep, restore = [], []
            for key, before in sess["sizes"].items():
                dev_key, _, zi = key.rpartition(":")
                new = sess["commits"].get(key)
                if new is not None:
                    keep.append((dev_key, int(zi), int(new)))
                    applied[key] = int(new)
                else:
                    restore.append((dev_key, int(zi), int(before)))
            if keep:
                self.resize_zones(keep, persist=True)
            if restore:
                self.resize_zones(restore, persist=False)

            self.renderer.blank()
            self.renderer.settings["paused"] = sess["was_paused"]
            return {"ok": True, "applied": applied}

    def set_source_config(self, kind: str, cfg: dict):
        with self._lock:
            self.config.setdefault("sources", {})[kind] = cfg
            self.save_config()
            src = {"audio": self.audio, "screen": self.screen}.get(kind)
            if src:
                src.stop()
            if kind == "audio":
                self.audio = None
            elif kind == "screen":
                self.screen = None
            self._sync_sources()

    def apply_preset(self, preset_id: str):
        p = ps.by_id(preset_id)
        if p is None:
            return {"ok": False, "error": "preset desconhecido"}
        with self._lock:
            self.renderer.load_scene(p.scene())
            self.config["last_preset"] = preset_id
            self._sync_sources()
            self.save_config()
        return {"ok": True, "name": p.name, "needs": list(p.needs)}

    def setup_todo(self) -> list:
        return [z for z in self.resizable_zones() if z["count"] == 0]

    def resizable_zones(self) -> list:
        out = []
        if not self.renderer:
            return out
        for dev in self.renderer.all_devices:
            key = device_key(dev)
            for z in dev.zones:
                if z.leds_min != z.leds_max:
                    out.append({"device": key, "device_name": dev.name,
                                "zone": z.index, "zone_name": z.name,
                                "count": z.leds_count,
                                "max": min(z.leds_max, 512)})
        return out

    def _find_zone(self, device_key_: str, zone_index: int):
        dev = next((d for d in self.renderer.all_devices
                    if device_key(d) == device_key_), None)
        if dev is None:
            return None, None
        zone = next((z for z in dev.zones if z.index == zone_index), None)
        return dev, zone

    def _paint_zone(self, dev, zone, buf) -> bool:
        try:
            self.client.update_zone_leds(dev.index, zone.index, buf.tobytes(),
                                         zone.leds_count)
            return True
        except OpenRGBError:
            return False

    def probe_multi_start(self, probe_max: int = 256):
        with self._lock:
            if getattr(self, "_probe_session", None) is None:
                self._probe_open_session(probe_max)
            else:
                self.renderer.blank()
            zones = []
            for z in self.resizable_zones():
                zones.append({"device": z["device"], "zone": z["zone"],
                              "zone_name": z["zone_name"],
                              "device_name": z["device_name"],
                              "max": z["count"]})
            if not zones:
                return {"ok": False, "error": "nenhum header ajustavel"}
            return {"ok": True, "zones": zones}

    def probe_multi_paint(self, items):
        with self._lock:
            if getattr(self, "_probe_session", None) is None:
                return {"ok": False, "error": "nenhuma sondagem em andamento"}
            self.renderer.blank()
            painted = []
            for it in items or []:
                dev, zone = self._find_zone(it["device"], int(it["zone"]))
                if dev is None or zone is None or zone.leds_count == 0:
                    continue
                idx = int(it["index"]) - 1
                if not (0 <= idx < zone.leds_count):
                    continue
                r, g, b = (int(v * 255) for v in hex_to_rgb(it.get("color", "#ffffff")))
                buf = np.zeros((zone.leds_count, 4), dtype=np.uint8)
                if it.get("tail", True):
                    buf[idx:, :3] = (r, g, b)
                else:
                    buf[idx, :3] = (r, g, b)
                if self._paint_zone(dev, zone, buf):
                    painted.append({"zone": zone.name, "index": idx + 1})
            return {"ok": True, "painted": painted}

    def probe_split_preview(self, device_key_: str, zone_index: int,
                            seg_size: int, total: int):
        with self._lock:
            dev, zone = self._find_zone(device_key_, zone_index)
            if dev is None or zone is None:
                return {"ok": False, "error": "zona nao encontrada"}
            self.renderer.blank()
            palette = [(255, 40, 90), (0, 190, 255), (140, 255, 40),
                       (255, 190, 0), (170, 90, 255), (0, 255, 190)]
            buf = np.zeros((zone.leds_count, 4), dtype=np.uint8)
            seg_size = max(1, int(seg_size))
            n = min(int(total), zone.leds_count)
            for i in range(n):
                buf[i, :3] = palette[(i // seg_size) % len(palette)]
            self._paint_zone(dev, zone, buf)
            return {"ok": True, "segments": (n + seg_size - 1) // seg_size}

    def probe_isolate(self, device_key_: str, zone_index: int, start: int,
                      count: int, color: str = "#ffffff"):
        with self._lock:
            dev, zone = self._find_zone(device_key_, zone_index)
            if dev is None or zone is None:
                return {"ok": False, "error": "zona nao encontrada"}
            self.renderer.blank()
            r, g, b = (int(v * 255) for v in hex_to_rgb(color))
            buf = np.zeros((zone.leds_count, 4), dtype=np.uint8)
            a = max(0, int(start))
            z = min(zone.leds_count, a + max(1, int(count)))
            buf[a:z, :3] = (r, g, b)
            self._paint_zone(dev, zone, buf)
            return {"ok": True, "lit": z - a}

    def set_zone_plan(self, device_key_: str, zone_index: int, parts):
        with self._lock:
            geo_parts = []
            spots_used = {}
            for p in parts or []:
                cnt = int(p.get("count", 0))
                if cnt <= 0:
                    continue
                spot = p.get("spot", "meio")
                x, y = CASE_SPOTS.get(spot, CASE_SPOTS["meio"])
                k = spots_used.get(spot, 0)
                spots_used[spot] = k + 1
                if k:
                    x = min(0.96, max(0.04, x + 0.16 * (1 if k % 2 else -1) * ((k + 1) // 2)))

                if p.get("kind") == "cable":
                    vertical = spot.startswith("frente") or spot == "traseira"
                    comp = 0.30
                    if vertical:
                        geo_parts.append({
                            "shape": "cable", "kind": "strip", "count": cnt,
                            "lanes": int(p.get("lanes", 12)),
                            "x1": x, "y1": max(0.03, y - comp),
                            "x2": x, "y2": min(0.97, y + comp),
                            "width": 0.14, "order": p.get("order", "lane")})
                    else:
                        geo_parts.append({
                            "shape": "cable", "kind": "strip", "count": cnt,
                            "lanes": int(p.get("lanes", 12)),
                            "x1": max(0.03, x - comp), "y1": y,
                            "x2": min(0.97, x + comp), "y2": y,
                            "width": 0.14, "order": p.get("order", "lane")})
                elif p.get("kind") == "strip":
                    vertical = spot.startswith("frente") or spot == "traseira"
                    if vertical:
                        geo_parts.append({"shape": "line", "kind": "strip",
                                          "count": cnt,
                                          "x1": x, "y1": max(0.03, y - 0.26),
                                          "x2": x, "y2": min(0.97, y + 0.26),
                                          "reverse": bool(p.get("reverse"))})
                    else:
                        geo_parts.append({"shape": "line", "kind": "strip",
                                          "count": cnt,
                                          "x1": max(0.03, x - 0.3), "y1": y,
                                          "x2": min(0.97, x + 0.3), "y2": y,
                                          "reverse": bool(p.get("reverse"))})
                else:
                    geo_parts.append({"shape": "ring", "kind": "fan",
                                      "count": cnt,
                                      "cx": x, "cy": y, "radius": 0.1,
                                      "start_deg": -90.0, "end_deg": 270.0,
                                      "reverse": bool(p.get("reverse"))})

            geo = ({"shape": "multi", "parts": geo_parts} if len(geo_parts) > 1
                   else (dict(geo_parts[0]) if geo_parts else None))
            if geo is None:
                return {"ok": False, "error": "plano vazio"}
            geo.pop("count", None)
            self.set_zone_geometry(device_key_, zone_index, geo)
            return {"ok": True, "geometry": geo}

    def list_profiles(self):
        out = []
        for fn in sorted(os.listdir(PROFILES_DIR)):
            if fn.endswith(".json"):
                out.append(fn[:-5])
        return out

    def save_profile(self, name: str):
        safe = "".join(c for c in name if c.isalnum() or c in " _-").strip()
        if not safe:
            return {"ok": False, "error": "nome invalido"}
        path = os.path.join(PROFILES_DIR, safe + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.renderer.scene_json(), f, indent=2, ensure_ascii=False)
        self.config["last_profile"] = safe
        self.save_config()
        return {"ok": True, "name": safe}

    def load_profile(self, name: str, apply_only=False):
        path = os.path.join(PROFILES_DIR, name + ".json")
        if not os.path.isfile(path):
            return False
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return False
        self.renderer.load_scene(data)
        if not apply_only:
            self.config["last_profile"] = name
            self.save_config()
        self._sync_sources()
        return True

    def delete_profile(self, name: str):
        path = os.path.join(PROFILES_DIR, name + ".json")
        if os.path.isfile(path):
            os.remove(path)
            return True
        return False

    def catalog(self):
        return {
            "effects": fx.catalog(),
            "blends": [{"value": v, "label": l} for v, l in blend.LABELS],
            "palettes": [{"name": n, "colors": palette_preview(n)}
                         for n in PALETTE_NAMES],
            "presets": ps.catalog(),
            "spots": [{"value": v, "label": l} for v, l in CASE_SPOT_LABELS],
        }

    def state(self) -> dict:
        r = self.renderer
        out = {
            "connected": self.connected,
            "status": self.status_msg,
            "protocol": self.client.protocol,
            "profiles": self.list_profiles(),
            "last_profile": self.config.get("last_profile"),
        }
        if not r:
            out["devices"] = []
            out["layers"] = []
            return out
        out.update({
            "layers": [l.to_json() for l in r.layers],
            "settings": {k: v for k, v in r.settings.items() if k != "enabled_devices"},
            "enabled_devices": r.settings.get("enabled_devices", {}),
            "fps": round(r.fps_actual, 1),
            "last_error": r.last_error,
            "reconnects": self.reconnects,
            "exclusive": self.last_exclusive,
            "exclusive_mode": self.config.get("exclusive_mode", True),
            "connection_lost": r.connection_lost,
            "canvas": r.canvas.to_json(),
            "devices": [
                dict(d.to_json(), key=device_key(d),
                     direct_ok=r.direct_ok.get(d.index),
                     active=any(dd.index == d.index for dd in r.canvas.devices))
                for d in r.all_devices
            ],
            "sources": {
                "audio": self._src_status(self.audio, "audio"),
                "screen": self._src_status(self.screen, "screen"),
                "sensors": (self.sensors.status() if self.sensors
                            else {"running": False}),
            },
            "needed": sorted(self._needed_sources()),
            "setup_todo": self.setup_todo(),
            "zones_resizable": self.resizable_zones(),
            "last_preset": self.config.get("last_preset"),
            "sensor_values": {
                k: round(getattr(r.ctx.sensors, k), 1)
                for k in ("cpu_temp", "gpu_temp", "cpu_load", "gpu_load",
                          "ram_load", "fan_rpm")
            },
        })
        return out

    def _src_status(self, src, kind) -> dict:
        cfg = (self.config.get("sources") or {}).get(kind) or {}
        if src is None:
            return {"running": False, "config": cfg}
        d = {"running": src.running, "error": src.error, "config": cfg}
        if kind == "audio":
            d["device_name"] = src.device_name
        else:
            d["fps"] = round(getattr(src, "actual_fps", 0.0), 1)
        return d

    def preview(self):
        r = self.renderer
        if not r or r.frame is None:
            return []
        rgba = r.to_wire(r.frame)[:, :3]
        return ["#%02x%02x%02x" % tuple(int(v) for v in c) for c in rgba]
