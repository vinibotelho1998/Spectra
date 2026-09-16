"""Captura da tela para os efeitos de luz ambiente.

Usa a duplicacao de area de trabalho do Windows, que entrega o quadro ja
pronto pela placa de video, sem custo de composicao. O quadro e reduzido
para uma grade pequena logo na entrada, porque nenhum efeito precisa de
mais resolucao que isso e o gabinete tem dezenas de LEDs, nao milhoes de
pixels.
"""

from __future__ import annotations

import threading
import time

import numpy as np


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

    @staticmethod
    def list_outputs():
        """Lista os monitores que dao para capturar."""
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
            return True
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

    def stop(self):
        """Fecha a captura."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.5)
        try:
            if self._cam:
                self._cam.stop()
                del self._cam
        except Exception:
            pass
        self._cam = None
        self.state.enabled = False

    @property
    def running(self) -> bool:
        """Diz se a captura esta ativa."""
        return self._cam is not None

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
