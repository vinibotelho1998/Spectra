"""Ruido coerente, base dos efeitos organicos.

Ruido de valor em tres dimensoes, com a terceira usada como tempo: isso
faz o padrao evoluir continuamente em vez de deslizar rigido pela tela.
A tabela de permutacao e semeada fixa, para que o mesmo instante da mesma
cena renderize sempre igual.
"""

from __future__ import annotations

import numpy as np

_PERM_SIZE = 256
_rng = np.random.default_rng(1337)
_PERM = _rng.permutation(_PERM_SIZE).astype(np.int32)
_PERM = np.concatenate([_PERM, _PERM])
_GRAD = _rng.random(_PERM_SIZE * 2).astype(np.float32)


def _fade(t):
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def value_noise3(x, y, z):
    """Ruido de valor em 3D, interpolado com a curva suave de Perlin.

    Devolve valores aproximadamente em 0 a 1, vetorizado sobre arrays.
    """
    x = np.asarray(x, dtype=np.float32)
    y = np.asarray(y, dtype=np.float32)
    z = np.asarray(z, dtype=np.float32)

    xi = np.floor(x).astype(np.int32)
    yi = np.floor(y).astype(np.int32)
    zi = np.floor(z).astype(np.int32)
    xf, yf, zf = x - xi, y - yi, z - zi
    u, v, w = _fade(xf), _fade(yf), _fade(zf)

    xi &= 255
    yi &= 255
    zi &= 255
    xi1 = (xi + 1) & 255
    yi1 = (yi + 1) & 255
    zi1 = (zi + 1) & 255

    def h(a, b, c):
        return _GRAD[(_PERM[(_PERM[a] + b) & 255] + c) & 255]

    c000 = h(xi, yi, zi)
    c100 = h(xi1, yi, zi)
    c010 = h(xi, yi1, zi)
    c110 = h(xi1, yi1, zi)
    c001 = h(xi, yi, zi1)
    c101 = h(xi1, yi, zi1)
    c011 = h(xi, yi1, zi1)
    c111 = h(xi1, yi1, zi1)

    x00 = c000 + u * (c100 - c000)
    x10 = c010 + u * (c110 - c010)
    x01 = c001 + u * (c101 - c001)
    x11 = c011 + u * (c111 - c011)
    y0 = x00 + v * (x10 - x00)
    y1 = x01 + v * (x11 - x01)
    return (y0 + w * (y1 - y0)).astype(np.float32)


def fbm3(x, y, z, octaves: int = 4, lacunarity: float = 2.0,
         gain: float = 0.5) -> np.ndarray:
    """Soma varias oitavas de ruido, cada uma menor e mais fina que a anterior.

    E o que da aparencia de nuvem e fumaca: uma oitava so fica lisa demais
    para parecer natural.
    """
    total = np.zeros(np.broadcast(x, y, z).shape, dtype=np.float32)
    amp = 1.0
    freq = 1.0
    norm = 0.0
    for _ in range(max(1, octaves)):
        total += amp * value_noise3(x * freq, y * freq, z * freq)
        norm += amp
        amp *= gain
        freq *= lacunarity
    return (total / max(norm, 1e-6)).astype(np.float32)


def turbulence3(x, y, z, octaves: int = 4) -> np.ndarray:
    """Como o fbm, mas somando o valor absoluto de cada oitava.

    O dobramento no zero cria vincos e filamentos, o desenho de chama e de
    agua revolta.
    """
    total = np.zeros(np.broadcast(x, y, z).shape, dtype=np.float32)
    amp = 1.0
    freq = 1.0
    norm = 0.0
    for _ in range(max(1, octaves)):
        total += amp * np.abs(value_noise3(x * freq, y * freq, z * freq) - 0.5) * 2.0
        norm += amp
        amp *= 0.5
        freq *= 2.0
    return (total / max(norm, 1e-6)).astype(np.float32)


def curl_offset(x, y, t, scale: float = 1.0, eps: float = 0.05):
    """Deslocamento perpendicular ao gradiente do ruido, aproximado.

    Campo assim nao tem fonte nem sumidouro, entao o que anda sobre ele gira
    e se enrola sem acumular num ponto, que e o movimento de fluido.
    """
    n1 = value_noise3((x + eps) * scale, y * scale, t)
    n2 = value_noise3((x - eps) * scale, y * scale, t)
    n3 = value_noise3(x * scale, (y + eps) * scale, t)
    n4 = value_noise3(x * scale, (y - eps) * scale, t)
    dx = (n1 - n2) / (2 * eps)
    dy = (n3 - n4) / (2 * eps)
    return dy, -dx
