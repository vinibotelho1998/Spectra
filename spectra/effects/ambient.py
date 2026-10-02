"""Padroes espaciais suaves, sem fontes externas nem simulacao acumulada.

O movimento depende so do relogio e da velocidade. Pausar a velocidade
congela inclusive a cor, e cada efeito funciona em fans, fitas e matrizes.
"""

from __future__ import annotations

import numpy as np

from ..engine import palette as pal
from .base import (ANGLE, INTENSITY, SCALE, SCOPE, SPEED, apply_scope,
                   effect, integer, num, palette)

TAU = 2.0 * np.pi


def _finish(ctx, p, phase, light=1.0):
    color = pal.sample_clamped(p["palette"], phase)
    light = np.asarray(light, dtype=np.float32)
    if light.ndim:
        light = light[:, None]
    return apply_scope(ctx, np.clip(color * light * p["intensity"], 0, 1), p)


def _axes(ctx, angle):
    a = np.radians(np.float32(angle))
    x, y = ctx.x - 0.5, ctx.y - 0.5
    return x * np.cos(a) + y * np.sin(a), -x * np.sin(a) + y * np.cos(a)


@effect("silk", "Seda", "Ondas",
        "Dobras largas de tecido com reflexos suaves percorrendo a superficie.",
        [palette(default="vaporwave"), SPEED(0.16), SCALE(2.0), ANGLE(30),
         num("fold", "Profundidade das dobras", 0.45, 0, 1), SCOPE(), INTENSITY()])
def _silk(ctx, p, st):
    u, v = _axes(ctx, p["angle"])
    t = ctx.t * p["speed"]
    fold = u * p["scale"] + np.sin(v * 5.0 + t) * p["fold"]
    phase = 0.5 + 0.5 * np.sin(fold * TAU - t)
    light = 0.28 + 0.72 * (0.5 + 0.5 * np.cos(fold * TAU - t + 0.7)) ** 2
    return _finish(ctx, p, phase, light)


@effect("prism", "Prisma", "Geometricos",
        "Feixes largos se cruzam e dispersam a paleta enquanto giram devagar.",
        [palette(default="rainbow"), SPEED(0.12), integer("beams", "Feixes", 3, 2, 8),
         num("width", "Largura", 0.22, 0.04, 0.6), SCOPE(), INTENSITY()])
def _prism(ctx, p, st):
    out = ctx.zeros()
    t = ctx.t * p["speed"]
    for i in range(p["beams"]):
        u, v = _axes(ctx, np.degrees(t) + i * 180.0 / p["beams"])
        beam = np.exp(-((u + 0.12 * np.sin(t + i)) / p["width"]) ** 2)
        color = pal.sample(p["palette"], v + i / p["beams"] + t * 0.08)
        out += color * beam[:, None] / np.sqrt(p["beams"])
    return apply_scope(ctx, np.clip(out * p["intensity"], 0, 1), p)


@effect("dunes", "Dunas", "Ondas",
        "Cristas de areia ondulam sobre um gradiente iluminado por luz rasante.",
        [palette(default="sunset"), SPEED(0.14), SCALE(2.2), ANGLE(15),
         num("relief", "Relevo", 0.6, 0, 1), SCOPE(), INTENSITY()])
def _dunes(ctx, p, st):
    u, v = _axes(ctx, p["angle"])
    t = ctx.t * p["speed"]
    ridge = v * p["scale"] * TAU + np.sin(u * 4.0 + t) * p["relief"] * 2.0 - t
    phase = 0.5 + 0.35 * np.sin(ridge) + 0.15 * np.sin(ridge * 0.5 + u)
    light = 0.4 + 0.6 * (0.5 + 0.5 * np.cos(ridge))
    return _finish(ctx, p, phase, light)


@effect("eclipse", "Eclipse", "Geometricos",
        "Uma sombra atravessa um halo luminoso com bordas macias.",
        [palette(default="fire"), SPEED(0.18),
         num("radius", "Raio do halo", 0.32, 0.1, 0.7),
         num("softness", "Suavidade", 0.09, 0.02, 0.25), SCOPE(), INTENSITY()])
def _eclipse(ctx, p, st):
    t = ctx.t * p["speed"]
    x, y = ctx.x - 0.5, ctx.y - 0.5
    r = np.hypot(x, y)
    halo = np.exp(-((r - p["radius"]) / p["softness"]) ** 2)
    shadow_r = np.hypot(x - np.sin(t) * 0.45, y - np.cos(t * 0.7) * 0.12)
    shadow = np.clip((shadow_r - p["radius"] * 0.78) / p["softness"], 0, 1)
    return _finish(ctx, p, np.clip(r / p["radius"], 0, 1), halo * shadow)


@effect("lotus", "Lotus", "Geometricos",
        "Petalas de luz se abrem e giram em torno do centro do gabinete.",
        [palette(default="cyberpunk"), SPEED(0.15), integer("petals", "Petalas", 5, 3, 12),
         num("width", "Espessura", 0.12, 0.03, 0.35), SCOPE(), INTENSITY()])
def _lotus(ctx, p, st):
    t = ctx.t * p["speed"]
    x, y = ctx.x - 0.5, ctx.y - 0.5
    r, a = np.hypot(x, y), np.arctan2(y, x)
    petals = 0.22 + 0.16 * np.cos(a * p["petals"] - t)
    petals *= 0.9 + 0.1 * np.sin(t)
    light = np.exp(-((r - petals) / p["width"]) ** 2)
    return _finish(ctx, p, 0.5 + 0.5 * np.sin(a - t * 0.4), light)


@effect("lissajous", "Lissajous", "Geometricos",
        "Um fio luminoso desenha lacos entrelacados em movimento continuo.",
        [palette(default="neon"), SPEED(0.22),
         integer("loops", "Lacos", 3, 1, 6),
         num("width", "Espessura", 0.075, 0.02, 0.2), SCOPE(), INTENSITY()])
def _lissajous(ctx, p, st):
    t = ctx.t * p["speed"]
    # Distancia a segmentos, em vez de pontos, mantem o fio continuo mesmo
    # com poucos LEDs. Acumular segmento a segmento limita a memoria.
    distance = np.full(ctx.n, np.inf, dtype=np.float32)
    phase = np.zeros(ctx.n, dtype=np.float32)
    angles = np.linspace(0.0, TAU, 97, dtype=np.float32)
    xs = 0.5 + 0.4 * np.sin(angles * p["loops"] + t)
    ys = 0.5 + 0.4 * np.sin(angles * (p["loops"] + 1))
    for i in range(len(angles) - 1):
        dx, dy = xs[i + 1] - xs[i], ys[i + 1] - ys[i]
        u = np.clip(((ctx.x - xs[i]) * dx + (ctx.y - ys[i]) * dy)
                    / max(float(dx * dx + dy * dy), 1e-9), 0, 1)
        d = (ctx.x - xs[i] - u * dx) ** 2 + (ctx.y - ys[i] - u * dy) ** 2
        nearer = d < distance
        phase[nearer] = (i + u[nearer]) / (len(angles) - 1)
        distance = np.minimum(distance, d)
    color = pal.sample(p["palette"], phase + t * 0.05)
    light = np.exp(-distance / p["width"] ** 2)
    return apply_scope(ctx, np.clip(color * light[:, None] * p["intensity"], 0, 1), p)


@effect("woven", "Trama", "Geometricos",
        "Fios de duas direcoes se alternam por cima e por baixo como tecido.",
        [palette(default="ice"), SPEED(0.12), SCALE(3.0), ANGLE(35),
         num("width", "Espessura dos fios", 0.35, 0.08, 0.8), SCOPE(), INTENSITY()])
def _woven(ctx, p, st):
    u, v = _axes(ctx, p["angle"])
    t = ctx.t * p["speed"]
    u, v = u * p["scale"] - t * 0.2, v * p["scale"] + t * 0.15
    a = np.exp(-(np.sin(u * np.pi) / p["width"]) ** 2)
    b = np.exp(-(np.sin(v * np.pi) / p["width"]) ** 2)
    over = 0.5 + 0.5 * np.cos(u * np.pi) * np.cos(v * np.pi)
    phase = np.divide(a * over, a * over + b * (1 - over) + 1e-6)
    return _finish(ctx, p, 0.15 + 0.7 * phase, np.maximum(a, b) * 0.9 + 0.05)


@effect("tidal", "Mare", "Ondas",
        "Uma faixa de espuma acompanha o avancar e recuar lento da agua.",
        [palette(default="ocean"), SPEED(0.16), ANGLE(0),
         num("foam", "Espuma", 0.1, 0.02, 0.3), SCOPE(), INTENSITY()])
def _tidal(ctx, p, st):
    u, v = _axes(ctx, p["angle"])
    t = ctx.t * p["speed"]
    shore = v - 0.2 * np.sin(t) - 0.06 * np.sin(u * 9.0 + t * 1.4)
    phase = np.clip(0.45 - shore * 1.3, 0, 1)
    water = 0.18 + 0.55 * np.clip(0.5 - shore * 2.5, 0, 1)
    foam = np.exp(-(shore / p["foam"]) ** 2)
    base = _finish(ctx, p, phase, water)
    out = np.clip(base + foam[:, None] * 0.4 * p["intensity"], 0, 1).astype(np.float32)
    return apply_scope(ctx, out, p)


@effect("helix", "Helice", "Fluxo",
        "Dois fios de cor se trancam ao longo de cada peca com luz e sombra.",
        [palette(default="cyberpunk"), SPEED(0.2),
         num("turns", "Voltas por peca", 2.0, 0.5, 6, 0.1),
         num("phase", "Defasagem entre pecas", 0.2, 0, 1), SCOPE(), INTENSITY()])
def _helix(ctx, p, st):
    t = ctx.t * p["speed"]
    wave = np.sin((ctx.piece01 * p["turns"] + ctx.piece_id * p["phase"] - t) * TAU)
    color_a = pal.sample_clamped(p["palette"], np.full(ctx.n, 0.2, dtype=np.float32))
    color_b = pal.sample_clamped(p["palette"], np.full(ctx.n, 0.8, dtype=np.float32))
    a, b = (0.5 + 0.5 * wave) ** 2, (0.5 - 0.5 * wave) ** 2
    out = color_a * a[:, None] + color_b * b[:, None]
    return apply_scope(ctx, np.clip(out * p["intensity"], 0, 1), p)


@effect("constellation", "Constelacao", "Particulas",
        "Estrelas flutuam ligadas por fios discretos em um ceu escuro.",
        [palette(default="ice"), SPEED(0.1), integer("stars", "Estrelas", 7, 3, 14),
         num("glow", "Halo das estrelas", 0.09, 0.03, 0.25),
         num("links", "Brilho dos fios", 0.2, 0, 0.7), SCOPE(), INTENSITY()])
def _constellation(ctx, p, st):
    t = ctx.t * p["speed"]
    k = np.arange(p["stars"], dtype=np.float32)
    # Frequencias fixas mantem a cena reproduzivel e evitam sorteio por quadro.
    x = 0.5 + 0.4 * np.sin(k * 2.4 + t * (0.3 + k * 0.025))
    y = 0.5 + 0.4 * np.cos(k * 1.7 + t * (0.4 + k * 0.018))
    out = ctx.zeros()
    for i in range(p["stars"]):
        color = pal.sample_clamped(p["palette"], np.float32(0.35 + 0.65 * i / p["stars"]))
        d = (ctx.x - x[i]) ** 2 + (ctx.y - y[i]) ** 2
        light = np.exp(-d / p["glow"] ** 2)
        j = (i + 1) % p["stars"]
        dx, dy = x[j] - x[i], y[j] - y[i]
        u = np.clip(((ctx.x - x[i]) * dx + (ctx.y - y[i]) * dy)
                    / max(float(dx * dx + dy * dy), 1e-6), 0, 1)
        line_d = (ctx.x - x[i] - u * dx) ** 2 + (ctx.y - y[i] - u * dy) ** 2
        light += np.exp(-line_d / 0.018 ** 2) * p["links"]
        out += color * light[:, None]
    return apply_scope(ctx, np.clip(out * p["intensity"], 0, 1), p)
