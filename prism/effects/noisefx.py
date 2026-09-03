from __future__ import annotations

import numpy as np

from ..engine import palette as pal
from ..engine.noise import curl_offset, fbm3, turbulence3, value_noise3
from .base import (ANGLE, INTENSITY, SCALE, SPEED, boolean, choice, color,
                   effect, integer, num, palette)


def _smoothstep(a, b, x):
    t = np.clip((x - a) / max(b - a, 1e-6), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


@effect("plasma", "Plasma", "Ruido",
        "O plasma classico de demoscene: senoides cruzadas em movimento.",
        [palette("palette", "Paleta", "plasma"), SPEED(0.4), SCALE(3.0, 0.5, 20.0),
         num("warp", "Distorcao", 0.5, 0.0, 2.0), INTENSITY()])
def _plasma(ctx, p, st):
    s = p["scale"]
    t = ctx.t * p["speed"]
    x, y = ctx.x * s, ctx.y * s
    v = (np.sin(x + t)
         + np.sin(y * 0.9 - t * 0.7)
         + np.sin((x + y) * 0.7 + t * 1.3)
         + np.sin(np.sqrt(x * x + y * y) * p["warp"] * 2.0 + t))
    return pal.sample(p["palette"], v / 8.0 + 0.5) * p["intensity"]


@effect("perlin_field", "Campo de Ruido", "Ruido",
        "fbm puro rolando pelo canvas -- nuvem lenta e nunca repetida.",
        [palette("palette", "Paleta", "aurora"), SPEED(0.15), SCALE(2.5, 0.3, 15.0),
         integer("octaves", "Oitavas", 4, 1, 7),
         num("contrast", "Contraste", 1.0, 0.2, 4.0, 0.05), INTENSITY()])
def _perlin_field(ctx, p, st):
    s = p["scale"]
    v = fbm3(ctx.x * s, ctx.y * s, np.float32(ctx.t * p["speed"]),
             octaves=int(p["octaves"]))
    v = np.clip((v - 0.5) * p["contrast"] + 0.5, 0.0, 1.0)
    return pal.sample(p["palette"], v) * p["intensity"]


@effect("fire", "Fogo", "Ruido",
        "Chama subindo, mais quente embaixo. Turbulencia da o bruxuleio.",
        [palette("palette", "Paleta", "fire"), SPEED(1.0), SCALE(3.5, 0.5, 15.0),
         num("height", "Altura da chama", 0.7, 0.1, 1.0),
         num("hunger", "Voracidade", 1.0, 0.2, 3.0, 0.05),
         boolean("invert", "Chama para baixo", False), INTENSITY()])
def _fire(ctx, p, st):
    y = 1.0 - ctx.y if p["invert"] else ctx.y
    s = p["scale"]
    n = turbulence3(ctx.x * s, y * s * 1.5 - ctx.t * p["speed"] * 2.0,
                    np.float32(ctx.t * p["speed"] * 0.3), octaves=4)
    base = _smoothstep(1.0 - p["height"], 1.0, y)
    heat = np.clip(base * (0.45 + 0.85 * n) * p["hunger"], 0.0, 1.0)
    return pal.sample_clamped(p["palette"], heat) * p["intensity"]


@effect("water", "Agua", "Ruido",
        "Causticas de piscina: linhas de luz que se cruzam e escorregam.",
        [palette("palette", "Paleta", "ice"), SPEED(0.35), SCALE(4.0, 0.5, 20.0),
         num("sharp", "Nitidez", 2.5, 0.5, 8.0, 0.1), INTENSITY()])
def _water(ctx, p, st):
    s = p["scale"]
    t = np.float32(ctx.t * p["speed"])
    n1 = value_noise3(ctx.x * s, ctx.y * s, t)
    n2 = value_noise3(ctx.y * s * 1.3 + 5.0, ctx.x * s * 1.1, t * 1.4)
    c = (1.0 - np.abs(n1 - 0.5) * 2.0) * (1.0 - np.abs(n2 - 0.5) * 2.0)
    c = np.clip(c, 0.0, 1.0) ** p["sharp"]
    return pal.sample_clamped(p["palette"], c) * p["intensity"]


@effect("aurora", "Aurora Boreal", "Ruido",
        "Cortinas verticais ondulando, com o dominio dobrado por curl.",
        [palette("palette", "Paleta", "aurora"), SPEED(0.2), SCALE(2.0, 0.3, 10.0),
         num("curl", "Ondulacao", 0.35, 0.0, 1.5),
         num("bands", "Cortinas", 3.0, 0.5, 12.0, 0.1), INTENSITY()])
def _aurora(ctx, p, st):
    t = np.float32(ctx.t * p["speed"])
    ox, oy = curl_offset(ctx.x, ctx.y, t, scale=p["scale"])
    x = ctx.x + ox * p["curl"]
    y = ctx.y + oy * p["curl"] * 0.4
    veil = np.sin((x * p["bands"] + t) * np.pi) * 0.5 + 0.5
    fade = _smoothstep(1.0, 0.15, y)
    v = np.clip(veil * fade * 1.3, 0.0, 1.0)
    return pal.sample_clamped(p["palette"], v) * p["intensity"]


@effect("nebula", "Nebulosa", "Ruido",
        "Nuvens de gas sobrepostas em duas escalas, com brilho pontual.",
        [palette("palette", "Paleta", "cyberpunk"), SPEED(0.08), SCALE(1.8, 0.2, 8.0),
         num("density", "Densidade", 1.0, 0.2, 3.0, 0.05),
         num("stars", "Estrelas", 0.3, 0.0, 1.0), INTENSITY()])
def _nebula(ctx, p, st):
    t = np.float32(ctx.t * p["speed"])
    s = p["scale"]
    big = fbm3(ctx.x * s, ctx.y * s, t, octaves=5)
    fine = fbm3(ctx.x * s * 3.7 + 11.0, ctx.y * s * 3.7, t * 1.7, octaves=3)
    v = np.clip((big * 0.7 + fine * 0.3) * p["density"], 0.0, 1.0)
    out = pal.sample_clamped(p["palette"], v)
    if p["stars"] > 0:
        sp = value_noise3(ctx.x * 90.0, ctx.y * 90.0, np.float32(0.0))
        twinkle = 0.6 + 0.4 * np.sin(ctx.t * 3.0 + sp * 30.0)
        mask = np.clip((sp - 0.93) / 0.07, 0.0, 1.0) * twinkle * p["stars"]
        out = np.clip(out + mask[:, None], 0.0, 1.0)
    return out * p["intensity"]


@effect("lavalamp", "Lava Lamp", "Ruido",
        "Bolhas metaball subindo e descendo, fundindo quando se aproximam.",
        [palette("palette", "Paleta", "lava"), SPEED(0.25),
         integer("blobs", "Bolhas", 5, 1, 16),
         num("size", "Tamanho", 0.22, 0.05, 0.6),
         num("threshold", "Limiar", 0.55, 0.1, 1.5, 0.01), INTENSITY()])
def _lavalamp(ctx, p, st):
    k = int(p["blobs"])
    if st.get("_k") != k:
        st["_k"] = k
        r = np.random.default_rng(k * 7919)
        st["phase"] = r.random(k).astype(np.float32) * 2 * np.pi
        st["px"] = r.random(k).astype(np.float32)
        st["rate"] = (0.5 + r.random(k).astype(np.float32)) * 0.7
    t = ctx.t * p["speed"]
    field = np.zeros(ctx.n, dtype=np.float32)
    for i in range(k):
        py = 0.5 + 0.42 * np.sin(t * st["rate"][i] + st["phase"][i])
        px = st["px"][i] + 0.08 * np.sin(t * 0.6 + st["phase"][i] * 1.7)
        d2 = (ctx.x - px) ** 2 + (ctx.y - py) ** 2
        field += (p["size"] ** 2) / (d2 + 1e-4)
    v = _smoothstep(p["threshold"], p["threshold"] * 2.2, field)
    return pal.sample_clamped(p["palette"], v) * p["intensity"]


@effect("marble", "Marmore", "Ruido",
        "Veios de pedra: senoide distorcida por turbulencia.",
        [palette("palette", "Paleta", "gold"), SPEED(0.1), SCALE(3.0, 0.3, 12.0),
         num("veins", "Veios", 4.0, 0.5, 20.0, 0.1),
         num("distort", "Distorcao", 1.2, 0.0, 4.0, 0.05), INTENSITY()])
def _marble(ctx, p, st):
    s = p["scale"]
    t = np.float32(ctx.t * p["speed"])
    turb = turbulence3(ctx.x * s, ctx.y * s, t, octaves=5)
    v = np.sin((ctx.x * p["veins"] + turb * p["distort"]) * np.pi) * 0.5 + 0.5
    return pal.sample_clamped(p["palette"], v) * p["intensity"]


@effect("warp", "Dobra", "Ruido",
        "O gradiente e distorcido por ruido antes de ser amostrado.",
        [palette("palette", "Paleta", "viridis"), SPEED(0.2), SCALE(2.0, 0.2, 10.0),
         num("amount", "Dobra", 0.6, 0.0, 2.5, 0.02),
         integer("passes", "Passes", 2, 1, 4), INTENSITY()])
def _warp(ctx, p, st):
    x, y = ctx.x.copy(), ctx.y.copy()
    t = np.float32(ctx.t * p["speed"])
    s = p["scale"]
    for i in range(int(p["passes"])):
        nx = fbm3(x * s, y * s, t + i * 3.1, octaves=3) - 0.5
        ny = fbm3(x * s + 7.0, y * s + 7.0, t + i * 3.1, octaves=3) - 0.5
        x = x + nx * p["amount"]
        y = y + ny * p["amount"]
    return pal.sample(p["palette"], x + y * 0.5 - t) * p["intensity"]


@effect("smoke", "Fumaca", "Ruido",
        "Densidade cinzenta subindo e se dissipando.",
        [color("color", "Cor", "#9fb3c8"), SPEED(0.4), SCALE(3.0, 0.5, 12.0),
         num("density", "Densidade", 0.8, 0.1, 2.0, 0.02), INTENSITY()])
def _smoke(ctx, p, st):
    s = p["scale"]
    n = fbm3(ctx.x * s, ctx.y * s * 1.4 - ctx.t * p["speed"],
             np.float32(ctx.t * p["speed"] * 0.2), octaves=4)
    fade = _smoothstep(0.0, 0.9, ctx.y)
    v = np.clip((n - 0.35) * 2.2 * p["density"] * fade, 0.0, 1.0)
    c = np.array(pal.hex_to_rgb(p["color"]), dtype=np.float32)
    return (c[None, :] * v[:, None]) * p["intensity"]


@effect("voronoi", "Voronoi", "Ruido",
        "Celulas que se movem e se empurram, cada uma com sua cor.",
        [palette("palette", "Paleta", "candy"), SPEED(0.2),
         integer("cells", "Celulas", 8, 2, 40),
         num("edge", "Realce da borda", 0.3, 0.0, 1.0), INTENSITY()])
def _voronoi(ctx, p, st):
    k = int(p["cells"])
    if st.get("_k") != k:
        st["_k"] = k
        r = np.random.default_rng(k * 104729)
        st["seed"] = r.random((k, 2)).astype(np.float32)
        st["vel"] = (r.random((k, 2)).astype(np.float32) - 0.5) * 0.3
        st["hue"] = r.random(k).astype(np.float32)
    t = ctx.t * p["speed"]
    px = st["seed"][:, 0] + 0.18 * np.sin(t * st["vel"][:, 0] * 6.0 + st["hue"] * 9.0)
    py = st["seed"][:, 1] + 0.18 * np.cos(t * st["vel"][:, 1] * 6.0 + st["hue"] * 5.0)
    d = np.sqrt((ctx.x[:, None] - px[None, :]) ** 2 +
                (ctx.y[:, None] - py[None, :]) ** 2)
    order = np.argsort(d, axis=1)
    nearest = order[:, 0]
    out = pal.sample(p["palette"], st["hue"][nearest] + t * 0.1)
    if p["edge"] > 0 and k > 1:
        d0 = np.take_along_axis(d, order[:, :1], axis=1)[:, 0]
        d1 = np.take_along_axis(d, order[:, 1:2], axis=1)[:, 0]
        border = _smoothstep(0.0, 0.06, d1 - d0)
        out = out * (border * p["edge"] + (1.0 - p["edge"]))[:, None]
    return out * p["intensity"]
