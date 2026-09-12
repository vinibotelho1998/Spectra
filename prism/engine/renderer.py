"""Pilha de camadas, composicao e o laco que empurra quadro para o hardware.

O renderizador roda numa thread propria a taxa configurada. A cada
quadro ele avalia cada camada ligada, compoe uma sobre a outra pelo modo
de blend, aplica brilho e gama e manda os bytes para o OpenRGB.

Duas decisoes de robustez moram aqui. Efeito que levanta excecao e
desligado e registrado em vez de derrubar a thread, porque perder o laco
de render deixa a iluminacao travada no ultimo quadro. Ja perda de
conexao levanta, marca `connection_lost` e para o laco, porque nesse
caso insistir nao adianta e quem observa precisa saber para reconectar.
"""

from __future__ import annotations

import threading
import time
import uuid

import numpy as np

from .. import effects as fx
from ..core.protocol import OpenRGBError
from . import blend
from .canvas import Canvas, device_key
from .context import RenderContext


class Layer:
    """Uma camada da cena: um efeito com parametros, blend e alvo.

    `targets` limita a camada a dispositivos ou zonas especificas, o que
    permite montar cena com efeito diferente em cada peca. `state` e a
    memoria do efeito entre quadros, zerada quando o canvas e remontado.
    """

    def __init__(self, effect_id: str, params: dict | None = None,
                 blend_mode: str = "normal", opacity: float = 1.0,
                 enabled: bool = True, targets=None, name: str = "",
                 id: str | None = None):
        self.id = id or uuid.uuid4().hex[:8]
        self.effect_id = effect_id
        self.params = dict(params or {})
        self.blend = blend_mode
        self.opacity = float(opacity)
        self.enabled = bool(enabled)
        self.targets = list(targets) if targets else []
        self.name = name
        self.state: dict = {}
        self._mask = None
        self._mask_key = None

    def resolved_params(self) -> dict:
        """Junta os parametros salvos sobre os padroes do efeito.

        Parametro ausente ou nulo cai no padrao, para que cena antiga continue
        abrindo depois de um efeito ganhar parametro novo.
        """
        d = fx.get(self.effect_id)
        p = d.defaults() if d else {}
        p.update({k: v for k, v in self.params.items() if v is not None})
        return p

    def mask_for(self, canvas: Canvas):
        """Mascara booleana dos LEDs que esta camada pode pintar.

        Devolve None quando a camada vale para o gabinete inteiro, o que deixa o
        caminho comum sem custo. O resultado fica em cache por canvas, porque
        isso seria refeito sessenta vezes por segundo a toa.
        """
        if not self.targets:
            return None
        key = (id(canvas), tuple(sorted(self.targets)))
        if self._mask_key == key:
            return self._mask
        m = np.zeros(canvas.n, dtype=bool)
        for dev, (_di, start, count) in zip(canvas.devices, canvas.slices):
            k = device_key(dev)
            if k in self.targets:
                m[start:start + count] = True
        for zi in canvas.zone_info:
            tag = f"{zi['device_key']}:{zi['zone_index']}"
            if tag in self.targets:
                m[zi["start"]:zi["start"] + zi["count"]] = True
        self._mask, self._mask_key = m, key
        return m

    def to_json(self) -> dict:
        """Descreve a camada para salvar em disco e mostrar na interface."""
        return {"id": self.id, "effect": self.effect_id, "params": self.params,
                "blend": self.blend, "opacity": self.opacity,
                "enabled": self.enabled, "targets": self.targets,
                "name": self.name}

    @staticmethod
    def from_json(d: dict) -> "Layer":
        """Remonta uma camada a partir do que foi salvo, com padroes tolerantes."""
        return Layer(d.get("effect", "static"), d.get("params"),
                     d.get("blend", "normal"), d.get("opacity", 1.0),
                     d.get("enabled", True), d.get("targets"),
                     d.get("name", ""), d.get("id"))


class Renderer:
    """Compoe as camadas e mantem o hardware pintado.

    Guarda a pilha de camadas, o canvas derivado dos dispositivos ligados e
    as configuracoes de saida. O acesso e protegido por lock reentrante,
    porque a interface mexe na cena enquanto a thread de render le.
    """

    def __init__(self, client, devices, layout_config=None, settings=None):
        self.client = client
        self.all_devices = devices
        self.layout_config = layout_config or {}
        self.settings = {
            "brightness": 1.0,
            "gamma": 2.2,
            "fps": 60,
            "smoothing": 0.0,
            "enabled_devices": {},
            "paused": False,
        }
        if settings:
            self.settings.update(settings)

        self.layers: list[Layer] = []
        self.canvas = None
        self.ctx = None
        self.frame = None
        self._prev = None
        self._lock = threading.RLock()
        self._thread = None
        self._stop = threading.Event()
        self.fps_actual = 0.0
        self.last_error = None
        self.connection_lost = False
        self.direct_ok: dict[int, bool] = {}
        self.rebuild()

    def rebuild(self):
        """Remonta o canvas e o contexto a partir dos dispositivos atuais.

        Zera a memoria das camadas, ja que o estado guardado tem o tamanho do
        canvas antigo.
        """
        with self._lock:
            self.canvas = Canvas(self.all_devices, self.layout_config,
                                 self.settings.get("enabled_devices"))
            self.ctx = RenderContext(self.canvas)
            self._prev = None
            for l in self.layers:
                l._mask_key = None
                l.state.clear()

    def set_devices(self, devices):
        """Troca a lista de dispositivos e remonta o canvas."""
        with self._lock:
            self.all_devices = devices
            self.rebuild()

    def arm_direct(self, force: bool = False):
        """Coloca cada dispositivo no modo de pintura por LED.

        Por padrao pula quem ja esta no modo certo. Isso importa: mandar troca
        de modo para um dispositivo que ja esta nele faz o controlador reaplicar
        a configuracao e piscar visivelmente. Com `force` a troca vai de novo,
        para retomar depois de outro programa ter mexido no hardware.
        """
        for dev in self.canvas.devices:
            m = dev.direct_mode()
            if not force and m is not None and dev.active_mode == m.index:
                self.direct_ok[dev.index] = True
                continue
            try:
                self.direct_ok[dev.index] = self.client.set_direct_mode(dev.index)
            except OpenRGBError as exc:
                self.direct_ok[dev.index] = False
                self.last_error = str(exc)

    def set_layers(self, layers):
        """Troca a pilha de camadas inteira."""
        with self._lock:
            self.layers = list(layers)

    def add_layer(self, layer: Layer):
        """Empilha uma camada nova por cima."""
        with self._lock:
            self.layers.append(layer)
            return layer

    def remove_layer(self, layer_id: str):
        """Tira uma camada pelo id."""
        with self._lock:
            self.layers = [l for l in self.layers if l.id != layer_id]

    def get_layer(self, layer_id: str):
        """Busca uma camada pelo id, devolvendo None se nao existir."""
        for l in self.layers:
            if l.id == layer_id:
                return l
        return None

    def render_once(self, dt: float) -> np.ndarray:
        """Avalia e compoe um quadro, sem mandar para o hardware.

        Efeito que levantar excecao e desligado e o erro fica em `last_error`,
        para que uma camada defeituosa nao derrube a cena inteira. Saida com
        formato errado e descartada.
        """
        ctx = self.ctx
        ctx.dt = dt
        ctx.frame += 1
        n = self.canvas.n
        out = np.zeros((n, 3), dtype=np.float32)
        if n == 0:
            return out

        for layer in self.layers:
            if not layer.enabled or layer.opacity <= 0.0:
                continue
            d = fx.get(layer.effect_id)
            if d is None:
                continue
            try:
                top = d.fn(ctx, layer.resolved_params(), layer.state)
            except Exception as exc:
                self.last_error = f"{layer.effect_id}: {exc}"
                layer.enabled = False
                continue
            top = np.nan_to_num(np.asarray(top, dtype=np.float32), nan=0.0)
            if top.shape != (n, 3):
                continue
            mask = layer.mask_for(self.canvas)
            if mask is None:
                out = blend.apply(layer.blend, out, top, layer.opacity)
            else:
                sub = blend.apply(layer.blend, out[mask], top[mask], layer.opacity)
                out[mask] = sub
        return np.clip(out, 0.0, 1.0)

    def to_wire(self, frame: np.ndarray) -> np.ndarray:
        """Converte o quadro para os bytes que o OpenRGB espera.

        Aplica brilho e correcao de gama antes de discretizar em 8 bits. A gama
        importa mais aqui do que em tela: LED responde de forma bem linear a
        corrente, entao sem correcao a metade da escala parece clara demais.
        """
        b = float(self.settings["brightness"])
        g = float(self.settings["gamma"])
        v = np.clip(frame * b, 0.0, 1.0)
        if g and abs(g - 1.0) > 1e-3:
            v = np.power(v, g, dtype=np.float32)
        rgba = np.zeros((len(v), 4), dtype=np.uint8)
        rgba[:, :3] = np.round(v * 255.0).astype(np.uint8)
        return rgba

    def push(self, frame: np.ndarray):
        """Manda o quadro para cada dispositivo, fatiado pelas faixas do canvas.

        Deixa `OpenRGBError` subir, porque perda de conexao precisa parar o laco
        em vez de virar quadro perdido em silencio.
        """
        rgba = self.to_wire(frame)
        raw = rgba.tobytes()
        for dev_index, start, count in self.canvas.slices:
            chunk = raw[start * 4:(start + count) * 4]
            try:
                self.client.update_leds(dev_index, chunk, count)
            except OpenRGBError as exc:
                self.last_error = str(exc)
                raise

    def cor_da_cena(self, frame: np.ndarray, niveis: int = 4) -> tuple:
        """Resume o quadro em cor e brilho, para hardware de cor unica.

        Devolve `(r, g, b, brilho)`, com o brilho na escala de `niveis` que
        esse hardware costuma ter.

        Duas decisoes moram aqui. A cor sai so do quarto mais claro do
        quadro, porque a media pura de uma cena com poucos LEDs acesos
        tende ao preto e apagaria o destino enquanto o gabinete brilha. E o
        tom vai normalizado, com o canal mais forte no topo da escala,
        deixando a intensidade por conta do campo de brilho: espremer as
        duas coisas nos oito bits de cor daria um tom certo e escuro demais
        para se enxergar.
        """
        preto = (0, 0, 0, 0)
        if frame is None or len(frame) == 0:
            return preto
        lum = frame @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
        if float(lum.max()) <= 1e-4:
            return preto

        # O tom sai do LED mais claro, nao de uma media. Cena de duas cores
        # tem media cinza: o Cross Over, que e ciano contra rosa, viraria
        # branco e nao diria nada sobre o que esta na tela. O mais claro
        # devolve uma cor que existe mesmo na cena.
        tom_bruto = frame[int(np.argmax(lum))]
        pico = float(tom_bruto.max())
        if pico <= 1e-4:
            return preto
        tom = np.clip(tom_bruto / pico, 0.0, 1.0)

        # A intensidade, essa sim, vem do conjunto: o quarto mais claro diz
        # se a cena esta acesa ou quase apagada.
        corte = float(np.quantile(lum, 0.75))
        forte = lum[lum >= corte]
        energia = min(1.0, float(forte.mean() if len(forte) else lum.mean())
                      * float(self.settings["brightness"]))
        brilho = int(round(energia ** 0.5 * niveis))
        if brilho <= 0:
            return preto
        r, g, b = (int(round(v * 255.0)) for v in tom)
        return (r, g, b, brilho)

    def blank(self):
        """Apaga tudo, engolindo erro de conexao por ser usado no encerramento."""
        if self.canvas is None or self.canvas.n == 0:
            return
        try:
            self.push(np.zeros((self.canvas.n, 3), dtype=np.float32))
        except OpenRGBError:
            pass

    def start(self):
        """Sobe a thread de render, se ainda nao estiver rodando."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="prism-render",
                                        daemon=True)
        self._thread.start()

    def stop(self):
        """Pede parada da thread de render e espera ela sair."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _loop(self):
        t_prev = time.perf_counter()
        t0 = t_prev
        acc_frames = 0
        acc_time = 0.0
        while not self._stop.is_set():
            target_dt = 1.0 / max(int(self.settings.get("fps", 60)), 1)
            now = time.perf_counter()
            dt = now - t_prev
            t_prev = now

            with self._lock:
                if self.settings.get("paused"):
                    time.sleep(0.05)
                    continue
                self.ctx.t = now - t0
                frame = self.render_once(min(dt, 0.25))
                sm = float(self.settings.get("smoothing", 0.0))
                if sm > 0.0 and self._prev is not None and self._prev.shape == frame.shape:
                    frame = self._prev * sm + frame * (1.0 - sm)
                self._prev = frame
                self.frame = frame
                try:
                    self.push(frame)
                except OpenRGBError:
                    self.connection_lost = True
                    self._stop.set()
                    break

            acc_frames += 1
            acc_time += dt
            if acc_time >= 0.5:
                self.fps_actual = acc_frames / acc_time
                acc_frames, acc_time = 0, 0.0

            sleep = target_dt - (time.perf_counter() - now)
            if sleep > 0:
                time.sleep(sleep)

    def scene_json(self) -> dict:
        """Descreve a cena inteira, camadas e configuracoes, para salvar."""
        return {"layers": [l.to_json() for l in self.layers],
                "settings": {k: v for k, v in self.settings.items()}}

    def load_scene(self, data: dict):
        """Carrega uma cena salva por cima da atual."""
        with self._lock:
            self.layers = [Layer.from_json(d) for d in data.get("layers", [])]
            s = data.get("settings") or {}
            for k in ("brightness", "gamma", "fps", "smoothing"):
                if k in s:
                    self.settings[k] = s[k]
