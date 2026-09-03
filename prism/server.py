from __future__ import annotations

import json
import mimetypes
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import effects as fx
from .app import ROOT, PrismApp

UI_DIR = os.path.join(ROOT, "ui")
ASSETS_DIR = os.path.join(ROOT, "assets")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "DBX-Prism"
    app: PrismApp = None

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False,
                                    default=str).encode("utf-8"))

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def _static(self, rel: str):
        rel = rel.lstrip("/") or "index.html"
        if rel.startswith("assets/"):
            base, rel = ASSETS_DIR, rel[len("assets/"):]
        else:
            base = UI_DIR
        path = os.path.normpath(os.path.join(base, rel))
        if not path.startswith(base) or not os.path.isfile(path):
            return self._send(404, b"nao encontrado", "text/plain; charset=utf-8")
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype)

    def do_GET(self):
        p = self.path.split("?", 1)[0]
        a = self.app
        if p == "/api/state":
            return self._json(a.state())
        if p == "/api/preview":
            return self._json({"colors": a.preview(),
                               "fps": round(a.renderer.fps_actual, 1) if a.renderer else 0})
        if p == "/api/catalog":
            return self._json(a.catalog())
        if p == "/api/audio-devices":
            from .sources.audio import AudioSource
            devs, err = AudioSource.list_devices()
            return self._json({"devices": devs, "error": err})
        if p == "/api/screen-outputs":
            from .sources.screen import ScreenSource
            outs, err = ScreenSource.list_outputs()
            return self._json({"outputs": outs, "error": err})
        if p.startswith("/api/"):
            return self._json({"error": "rota desconhecida"}, 404)
        return self._static(p)

    def do_POST(self):
        p = self.path.split("?", 1)[0]
        a = self.app
        b = self._body()
        try:
            if p == "/api/layers":
                a.set_layers(b.get("layers", []))
            elif p == "/api/layer/add":
                return self._json(a.add_layer(b["effect"], **{
                    k: b[k] for k in ("params", "blend", "opacity", "targets", "name")
                    if k in b}))
            elif p == "/api/layer/update":
                return self._json({"layer": a.update_layer(b["id"], b.get("patch", {}))})
            elif p == "/api/layer/remove":
                a.remove_layer(b["id"])
            elif p == "/api/layer/reorder":
                a.reorder_layers(b.get("order", []))
            elif p == "/api/settings":
                a.update_settings(b)
            elif p == "/api/zone/geometry":
                a.set_zone_geometry(b["device"], int(b["zone"]), b["geometry"])
            elif p == "/api/zone/resize":
                return self._json(a.resize_zone(b["device"], int(b["zone"]),
                                                int(b["size"])))
            elif p == "/api/layout/reset":
                a.reset_layout()
            elif p == "/api/source":
                a.set_source_config(b["kind"], b.get("config", {}))
            elif p == "/api/probe/start":
                return self._json(a.probe_start(b["device"], int(b["zone"]),
                                                int(b.get("max", 256))))
            elif p == "/api/probe/paint":
                return self._json(a.probe_paint(int(b["count"]),
                                                b.get("mode", "fill")))
            elif p == "/api/probe/stop":
                return self._json(a.probe_stop(b.get("commit")))
            elif p == "/api/probe/finish":
                return self._json(a.probe_finish())
            elif p == "/api/probe/commit":
                return self._json(a.probe_commit(b["device"], int(b["zone"]),
                                                 int(b["count"])))
            elif p == "/api/probe/multi/start":
                return self._json(a.probe_multi_start(int(b.get("max", 256))))
            elif p == "/api/probe/multi/paint":
                return self._json(a.probe_multi_paint(b.get("items", [])))
            elif p == "/api/probe/split":
                return self._json(a.probe_split_preview(
                    b["device"], int(b["zone"]), int(b["size"]), int(b["total"])))
            elif p == "/api/probe/isolate":
                return self._json(a.probe_isolate(
                    b["device"], int(b["zone"]), int(b["start"]),
                    int(b["count"]), b.get("color", "#ffffff")))
            elif p == "/api/zone/plan":
                return self._json(a.set_zone_plan(b["device"], int(b["zone"]),
                                                  b.get("parts", [])))
            elif p == "/api/preset/apply":
                return self._json(a.apply_preset(b["id"]))
            elif p == "/api/profile/save":
                return self._json(a.save_profile(b["name"]))
            elif p == "/api/profile/load":
                return self._json({"ok": a.load_profile(b["name"])})
            elif p == "/api/profile/delete":
                return self._json({"ok": a.delete_profile(b["name"])})
            elif p == "/api/exclusive":
                if "enabled" in b:
                    a.config["exclusive_mode"] = bool(b["enabled"])
                    a.save_config()
                return self._json(a.enforce_exclusive())
            elif p == "/api/reconnect":
                return self._json({"ok": a.connect()})
            elif p == "/api/shutdown":
                self._json({"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            else:
                return self._json({"error": "rota desconhecida"}, 404)
        except KeyError as exc:
            return self._json({"error": f"parametro faltando: {exc}"}, 400)
        except Exception as exc:
            return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
        return self._json({"ok": True})


def serve(app: PrismApp, host="127.0.0.1", port=7311):
    Handler.app = app
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    return httpd
