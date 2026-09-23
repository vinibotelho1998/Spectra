"""Servidor HTTP local que serve a interface e a API do app.

A interface e web, rodando dentro de uma janela nativa. O servidor
escuta so em 127.0.0.1, entao nada disso fica exposto na rede.
"""

from __future__ import annotations

import json
import mimetypes
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__
from . import effects as fx
from .app import ROOT, SpectraApp

UI_DIR = os.path.join(ROOT, "ui")
ASSETS_DIR = os.path.join(ROOT, "assets")

HOSTS_LOCAIS = {"127.0.0.1", "localhost", "[::1]"}

# Rotas que mexem na cena ou no hardware e so fazem sentido com o
# renderizador de pe. Antes da primeira conexao elas estouravam com
# "'NoneType' object has no attribute", que ia direto para a tela.
PRECISA_MOTOR = {
    "/api/layers", "/api/layer/add", "/api/layer/update", "/api/layer/remove",
    "/api/layer/reorder", "/api/zone/geometry", "/api/zone/resize",
    "/api/layout", "/api/layout/reset", "/api/probe/start",
    "/api/probe/paint", "/api/probe/stop", "/api/probe/commit",
    "/api/probe/multi/start", "/api/probe/multi/paint", "/api/probe/split",
    "/api/probe/isolate", "/api/zone/identify", "/api/zone/plan",
    "/api/preset/apply", "/api/profile/save", "/api/profile/load",
}


def _host_estranho(headers) -> bool:
    """Diz se o pedido chegou por um nome que nao e o loopback.

    Um site pode apontar o proprio dominio para 127.0.0.1 depois de a pagina
    carregar. Dai em diante o navegador manda pedido para ca com `Origin` e
    `Host` do site, que batem entre si, e a conferencia de origem sozinha
    deixa passar. O `Host` com o nome do site e o que denuncia.
    """
    host = (headers.get("Host") or "").strip().lower()
    if not host:
        return False
    if host.startswith("["):
        nome = host.split("]", 1)[0] + "]"
    else:
        nome = host.rsplit(":", 1)[0]
    return nome not in HOSTS_LOCAIS


class Handler(BaseHTTPRequestHandler):
    """Rotas da API e arquivos estaticos da interface.

    Os caminhos estaticos sao normalizados e conferidos contra o diretorio
    base, para que pedido com travessia de diretorio nao leia arquivo fora
    da pasta da interface.
    """

    protocol_version = "HTTP/1.1"
    server_version = "Spectra"
    app: SpectraApp = None

    def log_message(self, fmt, *args):
        """Silencia o log por pedido, que so poluiria o console."""
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

    def _foreign(self) -> bool:
        """Diz se o pedido veio de uma pagina de outra origem.

        O servidor so escuta em loopback, mas qualquer site aberto no
        navegador da pessoa tambem alcanca o loopback. Um POST com `Origin`
        diferente da nossa, ou sem JSON, e recusado para que uma pagina
        qualquer nao apague os LEDs nem encerre o app.
        """
        if _host_estranho(self.headers):
            return True
        origin = self.headers.get("Origin")
        if origin:
            host = self.headers.get("Host") or ""
            if origin.split("://", 1)[-1].rstrip("/") != host:
                return True
        ctype = (self.headers.get("Content-Type") or "").lower()
        return "application/json" not in ctype

    def _stream(self):
        """Empurra o quadro atual por Server-Sent Events, a ate 30 por segundo.

        Substitui a interface ficar pedindo `/api/preview` em laco: uma conexao
        so, e um evento apenas quando o quadro muda. Junto vai a leitura das
        fontes ligadas, para os medidores de audio e tela.
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        a = self.app
        last = None
        last_beat = 0.0
        while True:
            now = time.time()
            r = a.renderer
            h = a.preview_hex()
            if h != last or now - last_beat >= 1.0:
                last, last_beat = h, now
                msg = {"h": h,
                       "fps": round(r.fps_actual, 1) if r else 0,
                       "src": a.live_sources()}
                try:
                    self.wfile.write(b"data: " + json.dumps(msg).encode("utf-8")
                                     + b"\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionAbortedError,
                        ConnectionResetError, OSError):
                    return
            time.sleep(1.0 / 30.0)

    def _static(self, rel: str):
        rel = rel.lstrip("/") or "index.html"
        if rel.startswith("assets/"):
            base, rel = ASSETS_DIR, rel[len("assets/"):]
        else:
            base = UI_DIR
        path = os.path.normpath(os.path.join(base, rel))
        # com o separador no fim: sem ele, `../ui2/x` passaria por dentro de `ui`
        if (not path.startswith(os.path.join(os.path.normpath(base), ""))
                or not os.path.isfile(path)):
            return self._send(404, b"nao encontrado", "text/plain; charset=utf-8")
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        with open(path, "rb") as f:
            corpo = f.read()
        # a versao entra na hora de servir, lida do pacote: o numero do topo
        # acompanha o app sem ninguem editar a pagina. A comparacao ignora
        # maiusculas como o disco do Windows, que entrega a mesma pagina
        # para `/INDEX.HTML`
        if os.path.normcase(path) == os.path.normcase(
                os.path.join(os.path.normpath(UI_DIR), "index.html")):
            corpo = corpo.replace(b"{{versao}}", __version__.encode("utf-8"))
        self._send(200, corpo, ctype)

    def do_GET(self):
        """Responde a API de leitura e entrega os arquivos da interface."""
        p = self.path.split("?", 1)[0]
        a = self.app
        if _host_estranho(self.headers):
            return self._send(403, b"host nao permitido",
                              "text/plain; charset=utf-8")
        if p == "/api/state":
            return self._json(a.state())
        if p == "/api/preview":
            return self._json({"hex": a.preview_hex(),
                               "fps": round(a.renderer.fps_actual, 1) if a.renderer else 0,
                               "src": a.live_sources()})
        if p == "/api/stream":
            return self._stream()
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
        """Responde as rotas que mudam estado do app."""
        p = self.path.split("?", 1)[0]
        a = self.app
        if self._foreign():
            return self._json({"error": "origem nao permitida"}, 403)
        if p in PRECISA_MOTOR and a.renderer is None:
            return self._json({"error": "ainda sem conexao com o OpenRGB: "
                                        "nenhum LED esta sob controle"}, 503)
        b = self._body()
        try:
            if p == "/api/layers":
                a.set_layers(b.get("layers", []),
                             b["preset"] if "preset" in b else "keep",
                             b.get("perfil"))
            elif p == "/api/layer/add":
                return self._json(a.add_layer(b["effect"], **{
                    k: b[k] for k in ("params", "blend", "opacity", "targets",
                                      "name", "acima_de")
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
                # o tamanho vai cru: campo vazio chega nulo, e quem responde
                # com a frase certa e a conferencia do app
                return self._json(a.resize_zone(b["device"], int(b["zone"]),
                                                b.get("size")))
            elif p == "/api/layout/reset":
                return self._json({"ok": True, "anterior": a.reset_layout()})
            elif p == "/api/layout":
                return self._json(a.set_layout(b.get("layout")))
            elif p == "/api/source":
                return self._json(a.set_source_config(b["kind"], b.get("config", {})))
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
            elif p == "/api/zone/identify":
                return self._json(a.identify_zone(
                    b["device"], int(b["zone"]),
                    float(b.get("seconds", 1.6)), b.get("color", "#ffffff")))
            elif p == "/api/zone/plan":
                return self._json(a.set_zone_plan(b["device"], int(b["zone"]),
                                                  b.get("parts", [])))
            elif p == "/api/preset/apply":
                return self._json(a.apply_preset(b["id"]))
            elif p == "/api/profile/save":
                return self._json(a.save_profile(b["name"],
                                                 bool(b.get("sobrescrever"))))
            elif p == "/api/profile/load":
                return self._json({"ok": a.load_profile(b["name"])})
            elif p == "/api/profile/delete":
                return self._json({"ok": a.delete_profile(b["name"])})
            elif p == "/api/favoritos":
                return self._json(a.set_favoritos(b.get("ids")))
            elif p == "/api/inventario":
                return self._json(a.set_inventario(b.get("itens")))
            elif p == "/api/janela/mostrar":
                return self._json(a.mostrar_janela())
            elif p == "/api/openrgb/exe":
                return self._json(a.set_openrgb_exe(b.get("path")))
            elif p == "/api/exclusive":
                if "enabled" in b:
                    a.config["exclusive_mode"] = bool(b["enabled"])
                    a.save_config()
                return self._json(a.enforce_exclusive(bool(b.get("forcar"))))
            elif p == "/api/teclado":
                if "enabled" in b:
                    a.config["akko_keyboard"] = bool(b["enabled"])
                    a.save_config()
                    if a.renderer:
                        a._liga_teclado()
                return self._json({"ok": True,
                                   "teclado": a.teclado.to_json() if a.teclado
                                   else None})
            elif p == "/api/elevacao/reparar":
                return self._json(a.reparar_elevacao())
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
            # o nome da excecao nao diz nada a quem usa; o motivo, as vezes diz
            return self._json({"error": f"Nao consegui concluir: {exc}"}, 500)
        return self._json({"ok": True})


def serve(app: SpectraApp, host="127.0.0.1", port=7311):
    """Sobe o servidor numa thread e devolve o endereco da interface."""
    Handler.app = app
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    return httpd
