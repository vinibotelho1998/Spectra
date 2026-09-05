from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import webbrowser

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

from prism.app import PrismApp
from prism.core import exclusive
from prism.server import serve

TITULO = "DBX Prism"


def main() -> int:
    ap = argparse.ArgumentParser(prog="prism")
    ap.add_argument("--port", type=int, default=7311, help="porta da UI local")
    ap.add_argument("--orgb-port", type=int, default=6742, help="porta do OpenRGB")
    ap.add_argument("--browser", action="store_true", help="abrir no navegador")
    ap.add_argument("--headless", action="store_true", help="sem interface")
    ap.add_argument("--keep-leds", action="store_true",
                    help="nao apagar os LEDs ao sair")
    ap.add_argument("--allow-multiple", action="store_true",
                    help="permitir mais de uma instancia (so para depurar)")
    args = ap.parse_args()

    if not args.allow_multiple and not exclusive.acquire_single_instance():
        print("[prism] ja ha uma instancia rodando; trazendo para a frente")
        exclusive.focus_existing_window(TITULO)
        return 0

    app = PrismApp(port=args.orgb_port)
    app.status_msg = "conectando ao OpenRGB"

    try:
        httpd = serve(app, port=args.port)
    except OSError as exc:
        print(f"[prism] nao consegui abrir a porta {args.port}: {exc}")
        app.shutdown()
        return 1

    url = f"http://127.0.0.1:{args.port}/"
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    print(f"[prism] interface em {url}")

    threading.Thread(target=connect_in_background, args=(app,),
                     name="prism-connect", daemon=True).start()

    code = 0
    try:
        if args.headless:
            while True:
                time.sleep(1)
        elif args.browser:
            webbrowser.open(url)
            while True:
                time.sleep(1)
        else:
            code = run_window(url, app)
    except KeyboardInterrupt:
        pass
    finally:
        print("[prism] encerrando")
        httpd.shutdown()
        app.shutdown(blank=not args.keep_leds)
    return code


def connect_in_background(app: PrismApp) -> None:
    """Conecta no OpenRGB sem segurar a janela.

    Subir o servidor e detectar hardware pode levar mais de vinte segundos;
    a janela abre na hora mostrando "conectando" em vez de parecer que o
    programa nao abriu.
    """
    ok = app.connect(exclusive_pass=True)
    print(f"[prism] {app.status_msg}")
    if ok:
        r = app.renderer
        print(f"[prism] {len(r.canvas.devices)} device(s), {r.canvas.n} leds, "
              f"protocolo v{app.client.protocol}")
        for d in r.canvas.devices:
            flag = "direct" if r.direct_ok.get(d.index) else "SEM DIRECT"
            print(f"        - {d.name} ({d.led_count} leds, {flag})")
    else:
        print("[prism] seguindo sem hardware; a UI sobe mesmo assim")


def run_window(url: str, app: PrismApp) -> int:
    try:
        import webview
    except Exception as exc:
        print(f"[prism] pywebview indisponivel ({exc}); abrindo no navegador")
        webbrowser.open(url)
        while True:
            time.sleep(1)

    from prism.tray import Tray, set_window_icon

    window = webview.create_window(
        TITULO, url, width=1420, height=900, min_size=(1060, 680),
        background_color="#07090d")

    estado = {"sair": False}

    def encerrar():
        estado["sair"] = True
        try:
            window.destroy()
        except Exception:
            pass

    tray = Tray(window, app, encerrar)
    if not tray.start():
        print("[prism] bandeja indisponivel; fechar a janela vai encerrar")

    def ao_fechar():
        if estado["sair"] or not tray.icon:
            return True
        window.hide()
        return False

    window.events.closing += ao_fechar
    window.events.loaded += lambda: set_window_icon(TITULO)

    try:
        webview.start(gui="edgechromium")
    except Exception as exc:
        print(f"[prism] falha ao abrir a janela ({exc}); abrindo no navegador")
        webbrowser.open(url)
        while True:
            time.sleep(1)
    finally:
        tray.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
