"""Icone na bandeja do Windows e o icone da janela.

Fechar a janela manda o Spectra para a bandeja em vez de encerrar, porque
iluminacao e algo que fica ligado enquanto a maquina esta ligada. Sair
de verdade so pelo menu da bandeja.
"""

from __future__ import annotations

import os
import threading

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICONE = os.path.join(RAIZ, "assets", "spectra.ico")
ICONE_PNG = os.path.join(RAIZ, "assets", "spectra.png")


def sessao_encerrando() -> bool:
    """Diz se o Windows esta encerrando a sessao, por desligar ou sair."""
    try:
        import ctypes
        SM_SHUTTINGDOWN = 0x2000
        return bool(ctypes.windll.user32.GetSystemMetrics(SM_SHUTTINGDOWN))
    except Exception:
        return False


class Tray:
    """Icone de bandeja com abrir, apagar os LEDs e sair.

    O menu monta os rotulos por funcao, e nao por texto fixo, para que o
    estado mostrado, LEDs, fps e se esta apagado, esteja certo toda vez que
    o menu abre.
    """

    def __init__(self, window, app, on_quit):
        self.window = window
        self.app = app
        self.on_quit = on_quit
        self.icon = None
        self.quitting = False
        self._thread = None

    def _mostrar(self, *_):
        try:
            self.window.show()
            self.window.restore()
        except Exception:
            pass

    def _apagado(self) -> bool:
        r = getattr(self.app, "renderer", None)
        try:
            return bool(r) and float(r.settings.get("brightness", 1.0)) <= 0.0
        except (TypeError, ValueError):
            return False

    def _luz_label(self, _item=None):
        return "Acender LEDs" if self._apagado() else "Apagar LEDs"

    def _alternar_luz(self, *_):
        """Apaga ou reacende tudo, pelo mesmo caminho do botao da janela.

        Era uma pausa que apagava so o gabinete: o teclado, que recebe cor
        do laco de render, ficava aceso na ultima cor, e a mesma palavra na
        janela congelava em vez de apagar. Pelo brilho zero apaga os dois, e
        acender volta ao brilho de antes.
        """
        if not getattr(self.app, "renderer", None):
            return
        if self._apagado():
            self.app.update_settings({"brightness": self.app._brilho_aceso()})
        else:
            self.app.update_settings({"brightness": 0.0})

    def ao_fechar(self) -> bool:
        """Decide o que o X da janela faz: esconder na bandeja ou fechar.

        Com a sessao do Windows encerrando fecha de verdade. Cancelar o
        fechamento nessa hora fazia o Spectra aparecer como programa que
        impede o desligamento, e os LEDs nao passavam pelo apagar do fim.
        """
        if self.quitting or not self.icon or sessao_encerrando():
            self.quitting = True
            return True
        try:
            self.window.hide()
        except Exception:
            pass
        self._avisa_bandeja()
        return False

    def _avisa_bandeja(self):
        """Na primeira vez que o X esconde a janela, diz onde o app foi parar.

        Sem aviso a janela sumia calada, e quem nao conhece o icone da bandeja
        achava que tinha fechado, com os LEDs ainda acesos.
        """
        cfg = getattr(self.app, "config", None)
        if cfg is None or cfg.get("aviso_bandeja"):
            return
        try:
            self.icon.notify("O Spectra continua aqui na bandeja, com os efeitos "
                             "no ar. Para sair, use o menu deste icone.",
                             "Spectra")
        except Exception:
            return
        cfg["aviso_bandeja"] = True
        try:
            self.app.save_config()
        except Exception:
            pass

    def _sair(self, *_):
        self.quitting = True
        try:
            if self.icon:
                self.icon.stop()
        except Exception:
            pass
        self.on_quit()

    def _status(self, _item=None):
        r = getattr(self.app, "renderer", None)
        if not (self.app.connected and r):
            return "Sem conexao com o OpenRGB"
        return f"{r.canvas.n} LEDs · {r.fps_actual:.0f} fps"

    def start(self) -> bool:
        """Sobe o icone numa thread propria.

        Devolve False quando a bandeja nao esta disponivel, caso em que o app
        segue sem ela em vez de nao abrir.
        """
        try:
            import pystray
            from PIL import Image
        except Exception:
            return False
        try:
            img = Image.open(ICONE_PNG if os.path.isfile(ICONE_PNG) else ICONE)
        except Exception:
            return False

        menu = pystray.Menu(
            pystray.MenuItem("Abrir Spectra", self._mostrar, default=True),
            pystray.MenuItem(self._status, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(self._luz_label, self._alternar_luz),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Sair", self._sair),
        )
        self.icon = pystray.Icon("spectra", img, "Spectra", menu)
        self._thread = threading.Thread(target=self.icon.run, daemon=True,
                                        name="spectra-tray")
        self._thread.start()
        return True

    def stop(self):
        """Tira o icone da bandeja."""
        try:
            if self.icon:
                self.icon.stop()
        except Exception:
            pass


def set_window_icon(titulo: str = "Spectra") -> bool:
    """Aplica o icone do app na janela pelo titulo dela.

    A janela nativa vem do webview e nao expoe o icone, entao ele e
    colocado por mensagem do Windows depois que a janela ja existe.
    """
    if not os.path.isfile(ICONE):
        return False
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return False

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.FindWindowW.restype = wintypes.HWND
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR,
                                  wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                  wintypes.UINT]
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                    wintypes.WPARAM, wintypes.LPARAM]

    hwnd = user32.FindWindowW(None, titulo)
    if not hwnd:
        return False

    IMAGE_ICON, LR_LOADFROMFILE, WM_SETICON = 1, 0x0010, 0x0080
    ok = False
    for wparam, tamanho in ((0, 16), (1, 32)):
        h = user32.LoadImageW(None, ICONE, IMAGE_ICON, tamanho, tamanho,
                              LR_LOADFROMFILE)
        if h:
            user32.SendMessageW(hwnd, WM_SETICON, wparam, h)
            ok = True
    return ok
