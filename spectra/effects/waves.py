"""Efeitos de onda: padrao periodico varrendo o gabinete.

Todos derivam de uma fase que corre no tempo sobre um eixo escolhido,
seja horizontal, vertical, radial ou angular, e mudam no formato da onda
e no recorte das bordas.
"""

from __future__ import annotations

import numpy as np

from ..engine import palette as pal
from .base import (ANGLE, INTENSITY, SCALE, SOURCE_AXIS, SPEED, axis_values,
                   boolean, choice, color, effect, integer, num, palette)


@effect("rainbow_wave", "Onda Arco-Iris", "Ondas",
        "A paleta viajando num angulo qualquer -- o classico, mas espacial.",
        [palette(), SPEED(0.35), ANGLE(0.0),
         num("repeat", "Repeticoes", 1.0, 0.25, 8.0, 0.25, "x"), INTENSITY()])
def _rainbow_wave(ctx, p, st):
    u = ctx.rotated(p["angle"])
    return pal.sample(p["palette"], u * p["repeat"] - ctx.t * p["speed"]) * p["intensity"]


@effect("wave_bar", "Barra Viajante", "Ondas",
        "Uma faixa de cor deslizando sobre o fundo.",
        [color("color", "Cor", "#00e5ff"), color("bg", "Fundo", "#000000"),
         SPEED(0.6), ANGLE(0.0), num("width", "Largura", 0.18, 0.02, 1.0),
         boolean("bounce", "Vai e volta", False), INTENSITY()])
def _wave_bar(ctx, p, st):
    if ctx.n == 0:
        return ctx.zeros()
    u = ctx.rotated(p["angle"])
    lo, hi = float(u.min()), float(u.max())
    span = max(hi - lo, 1e-6)
    if p["bounce"]:
        ph = (ctx.t * p["speed"]) % 2.0
        ph = ph if ph <= 1.0 else 2.0 - ph
    else:
        ph = (ctx.t * p["speed"]) % 1.0
    center = lo + ph * span
    d = np.abs(u - center) / max(p["width"] * span, 1e-6)
    m = np.clip(1.0 - d, 0.0, 1.0)[:, None] ** 2
    fg = np.array(pal.hex_to_rgb(p["color"]), dtype=np.float32)
    bg = np.array(pal.hex_to_rgb(p["bg"]), dtype=np.float32)
    return (bg * (1 - m) + fg * m) * p["intensity"]


@effect("ripple", "Ondulacao", "Ondas",
        "Aneis concentricos saindo de um ponto do gabinete.",
        [palette("palette", "Paleta", "ocean"), SPEED(0.5),
         num("cx", "Centro X", 0.5, 0.0, 1.0), num("cy", "Centro Y", 0.5, 0.0, 1.0),
         num("freq", "Frequencia", 3.0, 0.5, 20.0, 0.1), INTENSITY()])
def _ripple(ctx, p, st):
    d = np.sqrt((ctx.x - p["cx"]) ** 2 + (ctx.y - p["cy"]) ** 2)
    return pal.sample(p["palette"], d * p["freq"] - ctx.t * p["speed"]) * p["intensity"]


@effect("scan", "Scanner", "Ondas",
        "Feixe com rastro correndo pelo eixo, estilo Kitt.",
        [color("color", "Cor", "#ff1744"), SPEED(0.8), ANGLE(0.0),
         num("width", "Largura do feixe", 0.08, 0.01, 0.5),
         num("tail", "Rastro", 0.25, 0.0, 1.0), INTENSITY()])
def _scan(ctx, p, st):
    if ctx.n == 0:
        return ctx.zeros()
    u = ctx.rotated(p["angle"])
    lo, hi = float(u.min()), float(u.max())
    span = max(hi - lo, 1e-6)
    ph = (ctx.t * p["speed"]) % 2.0
    fwd = ph <= 1.0
    ph = ph if fwd else 2.0 - ph
    center = lo + ph * span
    delta = (u - center) / span
    behind = delta > 0 if fwd else delta < 0
    d = np.abs(delta)
    core = np.clip(1.0 - d / max(p["width"], 1e-6), 0.0, 1.0) ** 2
    tail = np.where(behind, np.clip(1.0 - d / max(p["tail"], 1e-6), 0.0, 1.0) ** 3, 0.0)
    m = np.maximum(core, tail * 0.6)[:, None]
    c = np.array(pal.hex_to_rgb(p["color"]), dtype=np.float32)
    return c * m * p["intensity"]


@effect("spiral", "Espiral", "Ondas",
        "Braços de cor girando a partir do centro.",
        [palette("palette", "Paleta", "cyberpunk"), SPEED(0.3),
         integer("arms", "Bracos", 3, 1, 12), num("twist", "Torcao", 2.0, -8.0, 8.0, 0.1),
         num("cx", "Centro X", 0.5, 0.0, 1.0), num("cy", "Centro Y", 0.5, 0.0, 1.0),
         INTENSITY()])
def _spiral(ctx, p, st):
    dx = ctx.x - p["cx"]
    dy = ctx.y - p["cy"]
    r = np.sqrt(dx * dx + dy * dy)
    a = np.arctan2(dy, dx) / (2 * np.pi)
    t = a * p["arms"] + r * p["twist"] - ctx.t * p["speed"]
    return pal.sample(p["palette"], t) * p["intensity"]


@effect("pinwheel", "Catavento", "Ondas",
        "Setores girando em torno de um ponto.",
        [palette("palette", "Paleta", "neon"), SPEED(0.25),
         integer("blades", "Pas", 6, 2, 24),
         num("cx", "Centro X", 0.5, 0.0, 1.0), num("cy", "Centro Y", 0.5, 0.0, 1.0),
         num("sharp", "Nitidez", 0.5, 0.0, 1.0), INTENSITY()])
def _pinwheel(ctx, p, st):
    a = np.arctan2(ctx.y - p["cy"], ctx.x - p["cx"]) / (2 * np.pi)
    t = (a * p["blades"] - ctx.t * p["speed"] * p["blades"]) % 1.0
    if p["sharp"] > 0:
        k = 1.0 + p["sharp"] * 12.0
        t = np.clip((t - 0.5) * k + 0.5, 0.0, 1.0)
    return pal.sample(p["palette"], t) * p["intensity"]


@effect("interference", "Interferencia", "Ondas",
        "Duas fontes de onda somadas -- gera padroes que nunca se repetem igual.",
        [palette("palette", "Paleta", "ocean"), SPEED(0.5),
         num("freq", "Frequencia", 6.0, 1.0, 30.0, 0.5),
         num("ax", "Fonte A X", 0.2, 0.0, 1.0), num("ay", "Fonte A Y", 0.3, 0.0, 1.0),
         num("bx", "Fonte B X", 0.8, 0.0, 1.0), num("by", "Fonte B Y", 0.7, 0.0, 1.0),
         boolean("orbit", "Fontes orbitando", True), INTENSITY()])
def _interference(ctx, p, st):
    ax, ay, bx, by = p["ax"], p["ay"], p["bx"], p["by"]
    if p["orbit"]:
        w = ctx.t * p["speed"] * 0.7
        ax += 0.15 * np.cos(w)
        ay += 0.15 * np.sin(w)
        bx += 0.15 * np.cos(-w * 1.3)
        by += 0.15 * np.sin(-w * 1.3)
    d1 = np.sqrt((ctx.x - ax) ** 2 + (ctx.y - ay) ** 2)
    d2 = np.sqrt((ctx.x - bx) ** 2 + (ctx.y - by) ** 2)
    w1 = np.sin((d1 * p["freq"] - ctx.t * p["speed"]) * 2 * np.pi)
    w2 = np.sin((d2 * p["freq"] - ctx.t * p["speed"]) * 2 * np.pi)
    v = (w1 + w2) * 0.25 + 0.5
    return pal.sample(p["palette"], v) * p["intensity"]


@effect("moire", "Moire", "Ondas",
        "Duas grades levemente desalinhadas girando uma sobre a outra.",
        [palette("palette", "Paleta", "vaporwave"), SPEED(0.15),
         num("freq", "Densidade", 12.0, 2.0, 60.0, 0.5),
         num("delta", "Desalinho", 0.06, 0.0, 0.5, 0.005), INTENSITY()])
def _moire(ctx, p, st):
    a1 = ctx.t * p["speed"]
    a2 = a1 + p["delta"] * np.pi
    u1 = ctx.x * np.cos(a1) + ctx.y * np.sin(a1)
    u2 = ctx.x * np.cos(a2) + ctx.y * np.sin(a2)
    g = np.sin(u1 * p["freq"] * np.pi) * np.sin(u2 * p["freq"] * np.pi)
    return pal.sample(p["palette"], g * 0.5 + 0.5) * p["intensity"]


@effect("checker", "Xadrez", "Ondas",
        "Tabuleiro alternando cores, com opcao de deslizar.",
        [color("a", "Cor A", "#ff0066"), color("b", "Cor B", "#00ccff"),
         num("size", "Tamanho", 0.15, 0.02, 0.5), SPEED(0.2),
         num("blend", "Suavidade", 0.15, 0.0, 1.0), INTENSITY()])
def _checker(ctx, p, st):
    s = max(p["size"], 1e-3)
    gx = np.sin((ctx.x / s + ctx.t * p["speed"]) * np.pi)
    gy = np.sin((ctx.y / s) * np.pi)
    g = gx * gy
    if p["blend"] > 0:
        m = np.clip(g / max(p["blend"], 1e-3) * 0.5 + 0.5, 0.0, 1.0)
    else:
        m = (g > 0).astype(np.float32)
    ca = np.array(pal.hex_to_rgb(p["a"]), dtype=np.float32)
    cb = np.array(pal.hex_to_rgb(p["b"]), dtype=np.float32)
    return (cb + (ca - cb) * m[:, None]) * p["intensity"]


@effect("chevron", "Chevron", "Ondas",
        "Setas em V correndo pelo canvas.",
        [palette("palette", "Paleta", "sunset"), SPEED(0.4),
         num("freq", "Densidade", 4.0, 0.5, 20.0, 0.1),
         num("skew", "Abertura", 1.0, 0.0, 4.0, 0.05), ANGLE(0.0), INTENSITY()])
def _chevron(ctx, p, st):
    a = np.radians(p["angle"], dtype=np.float32)
    u = ctx.x * np.cos(a) + ctx.y * np.sin(a)
    v = -ctx.x * np.sin(a) + ctx.y * np.cos(a)
    t = (u + np.abs(v - 0.5) * p["skew"]) * p["freq"] - ctx.t * p["speed"]
    return pal.sample(p["palette"], t) * p["intensity"]


@effect("tunnel", "Tunel", "Ondas",
        "Aneis vindo em direcao ao observador, com perspectiva.",
        [palette("palette", "Paleta", "magma"), SPEED(0.7),
         num("cx", "Centro X", 0.5, 0.0, 1.0), num("cy", "Centro Y", 0.5, 0.0, 1.0),
         num("depth", "Profundidade", 0.25, 0.02, 1.0, 0.01), INTENSITY()])
def _tunnel(ctx, p, st):
    d = np.sqrt((ctx.x - p["cx"]) ** 2 + (ctx.y - p["cy"]) ** 2)
    z = p["depth"] / np.maximum(d, 1e-3)
    return pal.sample(p["palette"], z + ctx.t * p["speed"]) * p["intensity"]


@effect("twist", "Torcao", "Ondas",
        "Gradiente que se enrola progressivamente conforme o raio.",
        [palette("palette", "Paleta", "plasma"), SPEED(0.3),
         num("twist", "Torcao", 3.0, -10.0, 10.0, 0.1), INTENSITY()])
def _twist(ctx, p, st):
    a = ctx.angle01 + ctx.radius * p["twist"] * 0.1
    return pal.sample(p["palette"], a - ctx.t * p["speed"]) * p["intensity"]


@effect("sine_grid", "Grade Senoidal", "Ondas",
        "Duas senoides perpendiculares gerando uma malha viva.",
        [palette("palette", "Paleta", "turbo"), SPEED(0.4),
         num("fx", "Freq X", 5.0, 0.5, 30.0, 0.1), num("fy", "Freq Y", 5.0, 0.5, 30.0, 0.1),
         num("phase", "Defasagem", 0.25, 0.0, 1.0), INTENSITY()])
def _sine_grid(ctx, p, st):
    a = np.sin((ctx.x * p["fx"] + ctx.t * p["speed"]) * np.pi)
    b = np.sin((ctx.y * p["fy"] + ctx.t * p["speed"] * p["phase"] * 2.0) * np.pi)
    return pal.sample(p["palette"], (a + b) * 0.25 + 0.5) * p["intensity"]


@effect("orbit", "Orbita", "Ondas",
        "Pontos de luz girando em orbitas concentricas.",
        [palette("palette", "Paleta", "neon"), SPEED(0.5),
         integer("count", "Corpos", 3, 1, 12),
         num("size", "Tamanho", 0.12, 0.02, 0.6),
         num("radius", "Raio", 0.3, 0.05, 0.7), INTENSITY()])
def _orbit(ctx, p, st):
    out = np.zeros((ctx.n, 3), dtype=np.float32)
    for i in range(int(p["count"])):
        frac = i / max(p["count"], 1)
        a = ctx.t * p["speed"] * (1.0 + frac * 0.4) + frac * 2 * np.pi
        px = 0.5 + p["radius"] * np.cos(a)
        py = 0.5 + p["radius"] * np.sin(a)
        d = np.sqrt((ctx.x - px) ** 2 + (ctx.y - py) ** 2)
        m = np.clip(1.0 - d / max(p["size"], 1e-3), 0.0, 1.0) ** 2
        c = pal.sample(p["palette"], np.float32(frac))
        out += c * m[:, None]
    return np.clip(out, 0.0, 1.0) * p["intensity"]
