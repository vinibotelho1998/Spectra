"""Paletas de cor e conversao entre espacos.

As paletas viram uma tabela de consulta interpolada uma vez e reusada,
porque amostrar paleta e a operacao mais repetida do motor: acontece uma
vez por LED por quadro, sessenta vezes por segundo.
"""

from __future__ import annotations

import numpy as np


def hsv_to_rgb(h, s, v):
    """Converte HSV em RGB, vetorizado.

    O matiz da a volta sozinho, entao pode passar de 1 ou vir negativo.
    """
    h = np.asarray(h, dtype=np.float32) % 1.0
    s = np.clip(np.asarray(s, dtype=np.float32), 0.0, 1.0)
    v = np.clip(np.asarray(v, dtype=np.float32), 0.0, 1.0)
    h6 = h * 6.0
    i = np.floor(h6).astype(np.int32)
    f = h6 - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    i = i % 6
    r = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5],
                  [v, q, p, p, t, v])
    g = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5],
                  [t, v, v, q, p, p])
    b = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5],
                  [p, p, t, v, v, q])
    return np.stack([r, g, b], axis=-1).astype(np.float32)


def rgb_to_hsv(rgb):
    """Converte RGB em HSV, devolvendo os tres canais separados."""
    rgb = np.asarray(rgb, dtype=np.float32)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = np.max(rgb, axis=-1)
    mn = np.min(rgb, axis=-1)
    d = mx - mn
    h = np.zeros_like(mx)
    nz = d > 1e-6
    h = np.where(nz & (mx == r), ((g - b) / np.where(nz, d, 1)) % 6.0, h)
    h = np.where(nz & (mx == g), ((b - r) / np.where(nz, d, 1)) + 2.0, h)
    h = np.where(nz & (mx == b), ((r - g) / np.where(nz, d, 1)) + 4.0, h)
    h = (h / 6.0) % 1.0
    s = np.where(mx > 1e-6, d / np.where(mx > 1e-6, mx, 1), 0.0)
    return h.astype(np.float32), s.astype(np.float32), mx.astype(np.float32)


def hex_to_rgb(s: str):
    """Le uma cor hexadecimal, aceitando forma curta e sem cerquilha."""
    s = s.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    return (int(s[0:2], 16) / 255.0, int(s[2:4], 16) / 255.0, int(s[4:6], 16) / 255.0)


def rgb_to_hex(c) -> str:
    """Escreve uma cor em hexadecimal, saturando o que passar da faixa."""
    return "#%02x%02x%02x" % tuple(int(round(max(0.0, min(1.0, v)) * 255)) for v in c)


PALETTES: dict[str, list[str]] = {
    "rainbow":     ["#ff0000", "#ffff00", "#00ff00", "#00ffff", "#0000ff", "#ff00ff", "#ff0000"],
    "fire":        ["#000000", "#3d0707", "#a01a00", "#ff5a00", "#ffb400", "#ffe89a", "#ffffff"],
    "ice":         ["#000814", "#001d3d", "#0055a4", "#00a6fb", "#8ae1ff", "#ffffff"],
    "aurora":      ["#01030a", "#04303a", "#0a8a5f", "#4ce08a", "#9df5c0", "#b98cff", "#3a1d6e"],
    "sunset":      ["#12043a", "#5b1179", "#c22e63", "#ff6b35", "#ffc15e", "#fff3b0"],
    "ocean":       ["#03045e", "#0077b6", "#00b4d8", "#48cae4", "#90e0ef", "#caf0f8"],
    "forest":      ["#04160a", "#0b3d20", "#1d7a3c", "#5cb85c", "#a7e05c", "#e8f7a5"],
    "neon":        ["#ff006e", "#fb5607", "#ffbe0b", "#8338ec", "#3a86ff", "#ff006e"],
    "cyberpunk":   ["#0d0221", "#26034f", "#7b2cbf", "#e0218a", "#00f5d4", "#0d0221"],
    "vaporwave":   ["#2d00f7", "#8900f2", "#bc00dd", "#f20089", "#ff4d9d", "#01c5c4"],
    "lava":        ["#0b0000", "#4a0000", "#9d0208", "#e85d04", "#ffba08", "#fff0a0"],
    "toxic":       ["#0a1a00", "#1f4d00", "#5ca904", "#a8e10c", "#e4ff1a", "#f7ffb0"],
    "magma":       ["#000004", "#3b0f70", "#8c2981", "#de4968", "#fe9f6d", "#fcfdbf"],
    "viridis":     ["#440154", "#414487", "#2a788e", "#22a884", "#7ad151", "#fde725"],
    "plasma":      ["#0d0887", "#6a00a8", "#b12a90", "#e16462", "#fca636", "#f0f921"],
    "turbo":       ["#30123b", "#4145ab", "#1ddfa3", "#a4fc3b", "#fb8022", "#7a0403"],
    "candy":       ["#ff9ff3", "#feca57", "#ff6b6b", "#48dbfb", "#1dd1a1", "#ff9ff3"],
    "gold":        ["#1a1000", "#5c3d00", "#b8860b", "#ffd700", "#fff4c2", "#ffffff"],
    "police":      ["#ff0000", "#ff0000", "#000000", "#0000ff", "#0000ff", "#000000"],
    "mono_red":    ["#000000", "#440000", "#aa0000", "#ff0000", "#ff8888", "#ffffff"],
    "mono_green":  ["#000000", "#004400", "#00aa00", "#00ff00", "#88ff88", "#ffffff"],
    "mono_blue":   ["#000000", "#000844", "#0033aa", "#0066ff", "#88bbff", "#ffffff"],
    "mono_purple": ["#000000", "#25003f", "#5a00a0", "#9d00ff", "#d08bff", "#ffffff"],
    "mono_cyan":   ["#000000", "#003b3b", "#009e9e", "#00ffff", "#a0ffff", "#ffffff"],
    "white":       ["#000000", "#404040", "#808080", "#c0c0c0", "#ffffff"],
    "thermal":     ["#0000ff", "#00ffff", "#00ff00", "#ffff00", "#ff8000", "#ff0000"],
}

PALETTE_NAMES = list(PALETTES.keys())

_CACHE: dict[tuple, np.ndarray] = {}
_LUT_SIZE = 512


def _stops_to_lut(stops: tuple) -> np.ndarray:
    cols = np.array([hex_to_rgb(s) if isinstance(s, str) else s for s in stops],
                    dtype=np.float32)
    if len(cols) == 1:
        return np.repeat(cols, _LUT_SIZE, axis=0)
    src = np.linspace(0.0, 1.0, len(cols), dtype=np.float32)
    dst = np.linspace(0.0, 1.0, _LUT_SIZE, dtype=np.float32)
    lut = np.stack([np.interp(dst, src, cols[:, ch]) for ch in range(3)], axis=-1)
    return lut.astype(np.float32)


def get_lut(palette) -> np.ndarray:
    """Devolve a tabela de consulta de uma paleta, montando na primeira vez.

    Aceita nome do catalogo ou lista de paradas. Nome desconhecido cai no
    arco-iris em vez de estourar.
    """
    if isinstance(palette, str):
        stops = tuple(PALETTES.get(palette, PALETTES["rainbow"]))
    else:
        stops = tuple(palette) if palette else tuple(PALETTES["rainbow"])
    lut = _CACHE.get(stops)
    if lut is None:
        lut = _stops_to_lut(stops)
        _CACHE[stops] = lut
    return lut


def sample(palette, t) -> np.ndarray:
    """Amostra a paleta ciclicamente, dando a volta fora de 0 a 1.

    E o que se quer em efeito que corre sem parar, onde a cor precisa emendar
    do fim para o comeco sem costura visivel.
    """
    lut = get_lut(palette)
    idx = (np.asarray(t, dtype=np.float32) % 1.0) * (_LUT_SIZE - 1)
    i0 = idx.astype(np.int32)
    i1 = (i0 + 1) % _LUT_SIZE
    f = (idx - i0)[..., None]
    return (lut[i0] * (1.0 - f) + lut[i1] * f).astype(np.float32)


def sample_clamped(palette, t) -> np.ndarray:
    """Amostra a paleta grudando nas pontas fora de 0 a 1.

    E o que se quer quando a posicao representa uma medida, como temperatura
    ou nivel de audio, e passar do teto deve manter a cor do teto.
    """
    lut = get_lut(palette)
    idx = np.clip(np.asarray(t, dtype=np.float32), 0.0, 1.0) * (_LUT_SIZE - 1)
    i0 = np.floor(idx).astype(np.int32)
    i1 = np.minimum(i0 + 1, _LUT_SIZE - 1)
    f = (idx - i0)[..., None]
    return (lut[i0] * (1.0 - f) + lut[i1] * f).astype(np.float32)


def palette_preview(name: str, n: int = 24) -> list[str]:
    """Devolve n cores em hexadecimal, para a interface desenhar a amostra."""
    cols = sample_clamped(name, np.linspace(0.0, 1.0, n))
    return [rgb_to_hex(c) for c in cols]
