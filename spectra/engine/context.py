"""O que um efeito enxerga na hora de pintar um quadro.

O `RenderContext` junta as coordenadas do canvas, o relogio da animacao e
as fontes externas: audio, sensores de hardware e captura de tela. Cada
fonte carrega o proprio `enabled`, entao um efeito reativo continua
rodando quando a fonte esta fora, so que sobre valores parados, em vez de
quebrar.

O gerador aleatorio vem semeado de proposito, para que a mesma cena
renderize igual duas vezes e da para reproduzir um quadro na hora de
investigar defeito.
"""

from __future__ import annotations

import numpy as np

N_BANDS = 24


class AudioState:
    """Espectro e dinamica do audio que esta tocando na maquina.

    `bands` traz o espectro ja em escala logaritmica e com ganho automatico,
    `beat` traz a deteccao de ataque, e `centroid` diz se o som esta puxando
    para grave ou agudo.
    """

    def __init__(self, bands: int = N_BANDS):
        self.enabled = False
        self.level = 0.0
        self.peak = 0.0
        self.bass = 0.0
        self.mid = 0.0
        self.treble = 0.0
        self.centroid = 0.5
        self.beat = 0.0
        self.bands = np.zeros(bands, dtype=np.float32)
        self.waveform = np.zeros(128, dtype=np.float32)

    def band_at(self, u):
        """Amostra o espectro em 0 a 1, interpolando entre as bandas vizinhas."""
        u = np.clip(np.asarray(u, dtype=np.float32), 0.0, 1.0)
        idx = u * (len(self.bands) - 1)
        i0 = np.floor(idx).astype(np.int32)
        i1 = np.minimum(i0 + 1, len(self.bands) - 1)
        f = idx - i0
        return self.bands[i0] * (1 - f) + self.bands[i1] * f


class SensorState:
    """Temperatura, carga e rotacao lidas do hardware."""

    def __init__(self):
        self.enabled = False
        self.cpu_temp = 0.0
        self.gpu_temp = 0.0
        self.cpu_load = 0.0
        self.gpu_load = 0.0
        self.ram_load = 0.0
        self.fan_rpm = 0.0
        self.extra: dict[str, float] = {}

    def value(self, name: str) -> float:
        """Le um sensor pelo nome, caindo em zero se ele nao existir."""
        return {
            "cpu_temp": self.cpu_temp, "gpu_temp": self.gpu_temp,
            "cpu_load": self.cpu_load, "gpu_load": self.gpu_load,
            "ram_load": self.ram_load, "fan_rpm": self.fan_rpm,
        }.get(name, self.extra.get(name, 0.0))

    def normalized(self, name: str, lo: float, hi: float) -> float:
        """Mapeia a leitura de um sensor para 0 a 1 dentro da faixa dada.

        Faixa invertida ou degenerada devolve zero em vez de estourar.
        """
        v = self.value(name)
        if hi <= lo:
            return 0.0
        return float(min(1.0, max(0.0, (v - lo) / (hi - lo))))


class ScreenState:
    """Ultimo quadro capturado da tela, reduzido, com media e cor dominante."""

    def __init__(self, h: int = 36, w: int = 64):
        self.enabled = False
        self.image = np.zeros((h, w, 3), dtype=np.float32)
        self.average = np.zeros(3, dtype=np.float32)
        self.dominant = np.zeros(3, dtype=np.float32)

    def sample(self, x, y) -> np.ndarray:
        """Amostra o quadro capturado com interpolacao bilinear.

        E o que faz o efeito de luz ambiente ficar suave: cada LED le a cor da
        regiao da tela que corresponde a posicao dele no gabinete.
        """
        img = self.image
        h, w = img.shape[:2]
        fx = np.clip(np.asarray(x, dtype=np.float32), 0.0, 1.0) * (w - 1)
        fy = np.clip(np.asarray(y, dtype=np.float32), 0.0, 1.0) * (h - 1)
        x0 = np.floor(fx).astype(np.int32)
        y0 = np.floor(fy).astype(np.int32)
        x1 = np.minimum(x0 + 1, w - 1)
        y1 = np.minimum(y0 + 1, h - 1)
        ax = (fx - x0)[..., None]
        ay = (fy - y0)[..., None]
        top = img[y0, x0] * (1 - ax) + img[y0, x1] * ax
        bot = img[y1, x0] * (1 - ax) + img[y1, x1] * ax
        return (top * (1 - ay) + bot * ay).astype(np.float32)


class RenderContext:
    """Contexto de um quadro, entregue a cada efeito.

    Repassa os arrays de coordenada do canvas como propriedade, para que o
    efeito escreva `ctx.x` em vez de `ctx.canvas.x`, e carrega o tempo, o
    passo desde o quadro anterior e as fontes externas.
    """

    def __init__(self, canvas):
        self.canvas = canvas
        self.t = 0.0
        self.dt = 1.0 / 60.0
        self.frame = 0
        self.audio = AudioState()
        self.sensors = SensorState()
        self.screen = ScreenState()
        self.rng = np.random.default_rng(0xC0FFEE)

    @property
    def n(self):
        return self.canvas.n

    @property
    def x(self):
        return self.canvas.x

    @property
    def y(self):
        return self.canvas.y

    @property
    def cx(self):
        return self.canvas.cx

    @property
    def cy(self):
        return self.canvas.cy

    @property
    def radius(self):
        return self.canvas.radius

    @property
    def theta(self):
        return self.canvas.theta

    @property
    def angle01(self):
        return self.canvas.angle01

    @property
    def strip01(self):
        return self.canvas.strip01

    @property
    def piece01(self):
        return self.canvas.piece01

    @property
    def piece_id(self):
        return self.canvas.piece_id

    @property
    def piece_index(self):
        return self.canvas.piece_index

    @property
    def piece_count(self):
        return self.canvas.piece_count

    @property
    def piece_pos(self):
        return self.canvas.piece_pos

    @property
    def piece_len(self):
        return self.canvas.piece_len

    @property
    def is_strip(self):
        return self.canvas.is_strip

    @property
    def is_fan(self):
        return self.canvas.is_fan

    @property
    def piece_u(self):
        return self.canvas.piece_u

    @property
    def piece_v(self):
        return self.canvas.piece_v

    @property
    def piece_lane(self):
        return self.canvas.piece_lane

    @property
    def piece_lanes(self):
        return self.canvas.piece_lanes

    def zeros(self):
        """Um quadro preto, no formato que os efeitos devolvem."""
        return np.zeros((self.n, 3), dtype=np.float32)

    def rotated(self, angle_deg: float):
        """Projeta as coordenadas num eixo girado, em graus.

        E o que da o parametro de angulo para os efeitos direcionais, sem que
        cada um precise refazer a trigonometria.
        """
        a = np.radians(angle_deg, dtype=np.float32)
        return (self.x * np.cos(a) + self.y * np.sin(a)).astype(np.float32)
