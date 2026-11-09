"""Captura da tela para os efeitos de luz ambiente.

Usa a duplicacao de area de trabalho do Windows, que entrega o quadro ja
pronto pela placa de video, sem custo de composicao. O quadro e reduzido
para uma grade pequena logo na entrada, porque nenhum efeito precisa de
mais resolucao que isso e o gabinete tem dezenas de LEDs, nao milhoes de
pixels.
"""

from __future__ import annotations

import threading
import os
import uuid
import sys
import time

import numpy as np


def _wayland():
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    return session == "wayland" if session else bool(os.environ.get("WAYLAND_DISPLAY"))


class _PortalDenied(RuntimeError):
    """A pessoa recusou ou cancelou o pedido do portal."""


class _PortalCapture:
    """Sessao ScreenCast do portal e stream PipeWire; so captura com consentimento.

    Requer PyGObject, introspeccao GStreamer e plugin pipewiresrc. O seletor
    de monitor pertence ao compositor; nao se pode enumerar monitores antes
    de autorizar. Cada nova sessao pede permissao novamente.
    """
    def __init__(self, stop, grid, fps):
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gio, GLib, Gst
        self.Gio, self.GLib, self.Gst = Gio, GLib, Gst
        self.stop, self.grid, self.fps = stop, grid, fps
        self.session = self.pipeline = self.bus = self.fd = None
        self.context = GLib.MainContext.new()

    def _request(self, method, make_args):
        Gio, GLib = self.Gio, self.GLib
        token = "spectra_" + uuid.uuid4().hex
        expected = "/org/freedesktop/portal/desktop/request/" + self.bus.get_unique_name()[1:].replace(".", "_") + "/" + token
        response = []
        def on_response(conn, sender, path, interface, signal, params):
            if path == expected:
                response.append(params.unpack())
        sub = self.bus.signal_subscribe("org.freedesktop.portal.Desktop",
            "org.freedesktop.portal.Request", "Response", expected, None,
            Gio.DBusSignalFlags.NONE, on_response)
        path = None
        try:
            path = self.bus.call_sync("org.freedesktop.portal.Desktop",
                "/org/freedesktop/portal/desktop", "org.freedesktop.portal.ScreenCast",
                method, make_args(token), None, Gio.DBusCallFlags.NONE, 10000, None).unpack()[0]
            if path != expected:
                raise RuntimeError("portal retornou identificador de requisicao inesperado")
            deadline = time.monotonic() + 120
            while not response and not self.stop.is_set() and time.monotonic() < deadline:
                while self.context.pending():
                    self.context.iteration(False)
                self.stop.wait(0.05)
            if not response:
                try:
                    self.bus.call_sync("org.freedesktop.portal.Desktop", path,
                        "org.freedesktop.portal.Request", "Close", None, None,
                        Gio.DBusCallFlags.NONE, 1000, None)
                except Exception:
                    pass
                if self.stop.is_set():
                    raise RuntimeError("captura cancelada")
                raise _PortalDenied("permissao de captura expirou; altere a fonte de tela para tentar novamente")
            code, result = response[0]
            if code:
                raise _PortalDenied("compartilhamento de tela recusado ou cancelado; altere a fonte de tela para tentar novamente")
            return result
        finally:
            self.bus.signal_unsubscribe(sub)

    def run(self, on_frame, on_ready):
        Gio, GLib, Gst = self.Gio, self.GLib, self.Gst
        self.context.push_thread_default()
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            def opt(token):
                return {"handle_token": GLib.Variant("s", token)}
            result = self._request("CreateSession", lambda token: GLib.Variant("(a{sv})", ({
                **opt(token), "session_handle_token": GLib.Variant("s", "spectra_" + uuid.uuid4().hex)},)))
            self.session = result["session_handle"]
            self._request("SelectSources", lambda token: GLib.Variant("(oa{sv})", (self.session, {
                **opt(token), "types": GLib.Variant("u", 1), "multiple": GLib.Variant("b", False)})))
            result = self._request("Start", lambda token: GLib.Variant("(osa{sv})", (self.session, "", opt(token))))
            streams = result.get("streams", [])
            if not streams:
                raise RuntimeError("o portal nao forneceu uma tela")
            node = int(streams[0][0])
            value, fds = self.bus.call_with_unix_fd_list_sync("org.freedesktop.portal.Desktop",
                "/org/freedesktop/portal/desktop", "org.freedesktop.portal.ScreenCast",
                "OpenPipeWireRemote", GLib.Variant("(oa{sv})", (self.session, {})),
                None, Gio.DBusCallFlags.NONE, 10000, None, None)
            self.fd = fds.get(value.unpack()[0])
            Gst.init(None)
            h, w = self.grid
            self.pipeline = Gst.parse_launch(
                f"pipewiresrc fd={self.fd} path={node} ! videoconvert ! videoscale ! "
                f"video/x-raw,format=RGB,width={w},height={h} ! appsink name=sink sync=false max-buffers=1 drop=true")
            sink = self.pipeline.get_by_name("sink")
            if self.pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
                raise RuntimeError("nao consegui iniciar o stream PipeWire")
            on_ready()
            bus = self.pipeline.get_bus()
            while not self.stop.is_set():
                sample = sink.emit("try-pull-sample", 200 * Gst.MSECOND)
                if sample is not None:
                    buf = sample.get_buffer()
                    data = buf.extract_dup(0, buf.get_size())
                    # RGB no GStreamer tem cada linha alinhada a 4 bytes.
                    stride = (w * 3 + 3) & ~3
                    if len(data) < stride * h:
                        raise RuntimeError("quadro PipeWire incompleto")
                    frame = np.frombuffer(data, dtype=np.uint8).reshape(h, stride)[:, :w * 3].reshape(h, w, 3)
                    on_frame(frame)
                message = bus.timed_pop_filtered(0, Gst.MessageType.ERROR | Gst.MessageType.EOS)
                if message:
                    if message.type == Gst.MessageType.ERROR:
                        err, _ = message.parse_error()
                        raise RuntimeError(str(err))
                    raise RuntimeError("compartilhamento de tela encerrado")
                while self.context.pending():
                    self.context.iteration(False)
        finally:
            if self.pipeline is not None:
                self.pipeline.set_state(Gst.State.NULL)
            if self.fd is not None:
                os.close(self.fd)
            if self.session and self.bus:
                try:
                    self.bus.call_sync("org.freedesktop.portal.Desktop", self.session,
                        "org.freedesktop.portal.Session", "Close", None, None,
                        Gio.DBusCallFlags.NONE, 1000, None)
                except Exception:
                    pass
            self.context.pop_thread_default()


class ScreenSource:
    """Captura a tela e mantem o `ScreenState` atualizado.

    Roda em thread propria e degrada em silencio quando a captura nao esta
    disponivel.
    """

    def __init__(self, state, output_idx: int = 0, fps: int = 30,
                 grid=(36, 64)):
        self.state = state
        self.output_idx = int(output_idx)
        self.fps = int(fps)
        self.h, self.w = grid
        self._cam = None
        self._thread = None
        self._stop = threading.Event()
        self.error = None
        self.actual_fps = 0.0
        self._portal_denied = False

    @staticmethod
    def list_outputs():
        """Lista os monitores que dao para capturar."""
        if sys.platform.startswith("linux"):
            if _wayland():
                return [{"index": 0, "name": "Escolher tela no portal do sistema"}], None
            try:
                import mss
                with mss.mss() as capture:
                    return [{"index": i, "name": f"Monitor {i + 1} ({m['width']}x{m['height']})"}
                            for i, m in enumerate(capture.monitors[1:])], None
            except Exception as exc:
                return [], f"captura X11 indisponivel: {exc}"
        try:
            import dxcam
        except Exception as exc:
            return [], str(exc)
        try:
            info = dxcam.output_info()
        except Exception as exc:
            return [], str(exc)
        outs = []
        for line in str(info).strip().splitlines():
            line = line.strip()
            if line:
                outs.append({"index": len(outs), "name": line})
        return outs, None

    def start(self) -> bool:
        """Abre a captura e comeca a alimentar o estado.

        Devolve False quando a captura nao esta disponivel nesta maquina.
        """
        if self._thread and self._thread.is_alive():
            if self._stop.is_set():
                self.error = "a captura anterior ainda esta encerrando"
                return False
            return True
        if self._cam is not None:
            # A leitura morreu e deixou a camera para tras. Sem fechar, o
            # dxcam devolveria a mesma instancia e recusaria o novo start se
            # ela ainda estivesse capturando.
            self.stop()
        if sys.platform.startswith("linux"):
            if _wayland():
                return self._start_wayland()
            return self._start_linux()
        try:
            import dxcam
        except Exception as exc:
            self.error = f"dxcam indisponivel: {exc}"
            return False
        try:
            self._cam = dxcam.create(output_idx=self.output_idx,
                                     output_color="RGB",
                                     processor_backend="numpy")
            if self._cam is None:
                raise RuntimeError(f"saida {self.output_idx} nao pode ser capturada")
            self._cam.start(target_fps=self.fps, video_mode=True)
        except Exception as exc:
            self.error = str(exc)
            self._cam = None
            return False
        self.error = None
        self._stop.clear()
        self.state.enabled = True
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="spectra-screen")
        self._thread.start()
        return True

    def _start_wayland(self):
        if self._portal_denied:
            return False
        try:
            capture = _PortalCapture(self._stop, (self.h, self.w), self.fps)
        except Exception as exc:
            self.error = f"captura Wayland requer PyGObject, GStreamer e PipeWire: {exc}"
            return False
        self._stop.clear()
        self.error = None
        self._cam = capture
        count, started, last_frame = 0, time.perf_counter(), 0.0
        def frame(img):
            nonlocal count, started, last_frame
            now = time.perf_counter()
            if now - last_frame < 1 / max(self.fps, 1):
                return
            last_frame = now
            count += 1
            if now - started >= 1:
                self.actual_fps, count, started = count / (now - started), 0, now
            small = (img / 255.0).astype(np.float32)
            self.state.image = small
            self.state.average = small.reshape(-1, 3).mean(axis=0).astype(np.float32)
            self.state.dominant = self._dominant(small).astype(np.float32)
        def capture_loop():
            try:
                capture.run(frame, lambda: setattr(self.state, "enabled", True))
            except Exception as exc:
                if not self._stop.is_set():
                    if isinstance(exc, _PortalDenied):
                        self._portal_denied = True
                    self.error = f"captura Wayland indisponivel: {exc}"
            finally:
                self.state.enabled = False
                self._cam = None
        self._thread = threading.Thread(target=capture_loop, daemon=True, name="spectra-screen-portal")
        self._thread.start()
        return True

    def _start_linux(self):
        self.error = None
        self._stop.clear()
        ready = threading.Event()
        def capture():
            try:
                import mss
                with mss.mss() as cam:
                    monitors = cam.monitors[1:]
                    if not 0 <= self.output_idx < len(monitors):
                        raise RuntimeError(f"monitor {self.output_idx} nao encontrado")
                    monitor = monitors[self.output_idx]
                    self._cam = cam
                    self.state.enabled = True
                    ready.set()
                    count, start = 0, time.perf_counter()
                    while not self._stop.is_set():
                        t = time.perf_counter()
                        frame = np.asarray(cam.grab(monitor))[:, :, :3][:, :, ::-1]
                        small = self._downscale(frame)
                        self.state.image = small
                        self.state.average = small.reshape(-1, 3).mean(axis=0).astype(np.float32)
                        self.state.dominant = self._dominant(small).astype(np.float32)
                        count += 1
                        elapsed = time.perf_counter() - start
                        if elapsed >= 1:
                            self.actual_fps, count, start = count / elapsed, 0, time.perf_counter()
                        self._stop.wait(max(0, 1 / max(self.fps, 1) - (time.perf_counter() - t)))
            except Exception as exc:
                self.error = f"captura X11 indisponivel: {exc}"
            finally:
                self.state.enabled = False
                self._cam = None
                ready.set()
        self._thread = threading.Thread(target=capture, daemon=True, name="spectra-screen")
        self._thread.start()
        if not ready.wait(5):
            self.error = "a captura de tela nao iniciou"
            self._stop.set()
            return False
        return self.running

    def stop(self):
        """Fecha a captura."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.5)
        try:
            if self._cam and not sys.platform.startswith("linux"):
                self._cam.stop()
                del self._cam
        except Exception:
            pass
        self._cam = None
        self.state.enabled = False

    @property
    def running(self) -> bool:
        """Diz se a captura esta ativa.

        Conta a thread de leitura tambem: com ela morta a camera ainda
        existe, mas nenhum quadro novo chega ao estado.
        """
        return (self._cam is not None and self._thread is not None
                and self._thread.is_alive())

    def _downscale(self, img: np.ndarray) -> np.ndarray:
        ih, iw = img.shape[:2]
        bh, bw = max(ih // self.h, 1), max(iw // self.w, 1)
        crop = img[:self.h * bh, :self.w * bw]
        if crop.size == 0:
            return np.zeros((self.h, self.w, 3), dtype=np.float32)
        small = crop.reshape(self.h, bh, self.w, bw, 3).mean(axis=(1, 3))
        return (small / 255.0).astype(np.float32)

    @staticmethod
    def _dominant(small: np.ndarray) -> np.ndarray:
        mx = small.max(axis=2)
        mn = small.min(axis=2)
        sat = np.where(mx > 1e-4, (mx - mn) / np.maximum(mx, 1e-4), 0.0)
        w = (sat ** 1.5) * (mx ** 0.6) + 1e-4
        tot = w.sum()
        if tot <= 1e-6:
            return small.reshape(-1, 3).mean(axis=0)
        return (small * w[..., None]).reshape(-1, 3).sum(axis=0) / tot

    def _loop(self):
        n, t0 = 0, time.perf_counter()
        while not self._stop.is_set():
            try:
                frame = self._cam.get_latest_frame()
            except Exception as exc:
                self.error = str(exc)
                break
            if frame is None:
                # Erro na thread da camera encerra a captura, e ela nao volta
                # sozinha: dali em diante so vem nada. Insistir deixava a
                # fonte marcada como ativa com a imagem congelada, sem erro
                # nenhum na interface. Nada com a captura de pe e so a troca
                # de resolucao, que passa no quadro seguinte.
                if not getattr(self._cam, "is_capturing", True):
                    self.error = "a captura de tela parou"
                    break
                time.sleep(0.005)
                continue
            small = self._downscale(frame)
            self.state.image = small
            self.state.average = small.reshape(-1, 3).mean(axis=0).astype(np.float32)
            self.state.dominant = self._dominant(small).astype(np.float32)
            n += 1
            dt = time.perf_counter() - t0
            if dt >= 1.0:
                self.actual_fps = n / dt
                n, t0 = 0, time.perf_counter()
