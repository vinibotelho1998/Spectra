from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.request
import webbrowser

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

from spectra import __version__
from spectra.app import SpectraApp
from spectra.core import exclusive
from spectra.server import serve

TITULO = f"Spectra {__version__}"


def main() -> int:
    ap = argparse.ArgumentParser(prog="spectra")
    ap.add_argument("--port", type=int, default=7311, help="porta da UI local")
    ap.add_argument("--orgb-port", type=int, default=6742, help="porta do OpenRGB")
    ap.add_argument("--browser", action="store_true", help="abrir no navegador")
    ap.add_argument("--headless", action="store_true", help="sem interface")
    ap.add_argument("--keep-leds", action="store_true",
                    help="nao apagar os LEDs ao sair")
    ap.add_argument("--allow-multiple", action="store_true",
                    help="permitir mais de uma instancia (so para depurar)")
    ap.add_argument("--bandeja", action="store_true",
                    help="abrir direto na bandeja, sem mostrar a janela")
    args = ap.parse_args()

    if not args.allow_multiple and not exclusive.acquire_single_instance():
        if args.bandeja:
            # o inicio com o Windows achou o app ja aberto: nada a mostrar
            return 0
        print("[spectra] ja ha uma instancia rodando; trazendo para a frente")
        if not pedir_janela(args.port):
            exclusive.focus_existing_window(TITULO)
        return 0

    app = SpectraApp(port=args.orgb_port)
    app.status_msg = "conectando ao OpenRGB"

    try:
        httpd = serve(app, port=args.port)
    except OSError as exc:
        print(f"[spectra] nao consegui abrir a porta {args.port}: {exc}")
        app.shutdown()
        return 1

    url = f"http://127.0.0.1:{args.port}/"
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    print(f"[spectra] interface em {url}")

    threading.Thread(target=connect_in_background, args=(app,),
                     name="spectra-connect", daemon=True).start()

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
            code = run_window(url, app, bandeja=args.bandeja)
    except KeyboardInterrupt:
        pass
    finally:
        print("[spectra] encerrando")
        httpd.shutdown()
        app.shutdown(blank=not args.keep_leds)
    return code


def pedir_janela(porta: int) -> bool:
    """Pede a instancia que ja esta rodando para mostrar a janela dela.

    Fechar a janela so a esconde na bandeja, e uma janela escondida o Windows
    nao traz para a frente pelo titulo: abrir o atalho de novo nao fazia
    nada. Pela API local a primeira instancia mostra a propria janela.
    """
    try:
        # quem foi aberto pela pessoa pode ceder o primeiro plano; sem isso o
        # Windows mostra a janela da outra instancia atras das demais
        import ctypes
        ctypes.windll.user32.AllowSetForegroundWindow(-1)
    except Exception:
        pass
    pedido = urllib.request.Request(
        f"http://127.0.0.1:{porta}/api/janela/mostrar", data=b"{}",
        headers={"Content-Type": "application/json"}, method="POST")
    # sem proxy: um proxy do sistema desviaria ate o pedido para o loopback
    abridor = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with abridor.open(pedido, timeout=2.0) as r:
            return bool(json.loads(r.read().decode("utf-8") or "{}").get("ok"))
    except (OSError, ValueError):
        return False


def connect_in_background(app: SpectraApp) -> None:
    """Conecta no OpenRGB sem segurar a janela.

    Subir o servidor e detectar hardware pode levar mais de vinte segundos;
    a janela abre na hora mostrando "conectando" em vez de parecer que o
    programa nao abriu.
    """
    ok = app.connect(exclusive_pass=True)
    print(f"[spectra] {app.status_msg}")
    if ok:
        r = app.renderer
        print(f"[spectra] {len(r.canvas.devices)} device(s), {r.canvas.n} leds, "
              f"protocolo v{app.client.protocol}")
        for d in r.canvas.devices:
            flag = "direct" if r.direct_ok.get(d.index) else "SEM DIRECT"
            print(f"        - {d.name} ({d.led_count} leds, {flag})")
    else:
        print("[spectra] seguindo sem hardware; a UI sobe mesmo assim")


def ligar_desligamento(window, tray) -> bool:
    """Liga na janela nativa o tratador que deixa o Windows desligar.

    Vem depois do tratador do pywebview na fila do evento, entao a decisao
    dele e a que vale quando o motivo do fechamento e o desligamento.
    """
    try:
        window.native.FormClosing += tray.ao_fechar_form
    except Exception as exc:
        print(f"[spectra] sem tratador de desligamento: {exc}")
        return False
    return True


def run_window(url: str, app: SpectraApp, bandeja: bool = False) -> int:
    try:
        import webview
    except Exception as exc:
        print(f"[spectra] pywebview indisponivel ({exc}); abrindo no navegador")
        webbrowser.open(url)
        while True:
            time.sleep(1)

    from spectra.tray import Tray, set_window_icon

    def encerrar():
        try:
            tray.window.destroy()
        except Exception:
            pass

    # A bandeja sobe antes da janela: so com ela no ar da para abrir a
    # janela escondida, senao nao haveria como mostrar o app depois.
    tray = Tray(None, app, encerrar)
    if not tray.start():
        print("[spectra] bandeja indisponivel; fechar a janela vai encerrar")

    window = webview.create_window(
        TITULO, url, width=1420, height=900, min_size=(1060, 680),
        background_color="#07090d", hidden=bool(bandeja and tray.icon))
    tray.window = window
    app.ao_mostrar_janela = tray._mostrar

    window.events.closing += tray.ao_fechar
    window.events.before_show += lambda window: ligar_desligamento(window, tray)
    window.events.loaded += lambda: set_window_icon(TITULO)

    try:
        webview.start(gui="edgechromium")
    except Exception as exc:
        print(f"[spectra] falha ao abrir a janela ({exc}); abrindo no navegador")
        webbrowser.open(url)
        while True:
            time.sleep(1)
    finally:
        tray.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
