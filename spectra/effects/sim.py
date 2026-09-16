"""Efeitos de simulacao rodando sobre uma grade propria.

Jogo da vida, automato celular, difusao de calor, equacao de onda e
cardume. A grade evolui a cada quadro e depois e amostrada nas posicoes
dos LEDs, entao o padrao existe independente de onde o hardware esta.
"""

from __future__ import annotations

import numpy as np

from ..engine import palette as pal
from .base import (INTENSITY, SPEED, boolean, choice, color, effect, integer,
                   num, palette)


def _sample_grid(grid, ctx):
    h, w = grid.shape[:2]
    fx = np.clip(ctx.x, 0.0, 1.0) * (w - 1)
    fy = np.clip(ctx.y, 0.0, 1.0) * (h - 1)
    x0 = np.floor(fx).astype(np.int32)
    y0 = np.floor(fy).astype(np.int32)
    x1 = np.minimum(x0 + 1, w - 1)
    y1 = np.minimum(y0 + 1, h - 1)
    ax = fx - x0
    ay = fy - y0
    top = grid[y0, x0] * (1 - ax) + grid[y0, x1] * ax
    bot = grid[y1, x0] * (1 - ax) + grid[y1, x1] * ax
    return (top * (1 - ay) + bot * ay).astype(np.float32)


def _laplacian(a):
    return (np.roll(a, 1, 0) + np.roll(a, -1, 0) +
            np.roll(a, 1, 1) + np.roll(a, -1, 1) - 4.0 * a)


def _tick(st, ctx, hz):
    st["acc"] = st.get("acc", 0.0) + ctx.dt
    step = 1.0 / max(hz, 0.01)
    n = 0
    while st["acc"] >= step and n < 8:
        st["acc"] -= step
        n += 1
    return n


@effect("life", "Game of Life", "Simulacao",
        "Automato de Conway. As celulas vivas brilham e o rastro esfria devagar.",
        [palette("palette", "Paleta", "toxic"), num("hz", "Geracoes", 6.0, 0.5, 30.0, 0.5, "/s"),
         integer("size", "Resolucao", 32, 8, 96, 1, "px"),
         num("fade", "Rastro", 0.85, 0.0, 0.99),
         num("seed", "Densidade inicial", 0.35, 0.05, 0.9), INTENSITY()])
def _life(ctx, p, st):
    n = int(p["size"])
    if st.get("_n") != n:
        st["_n"] = n
        st["g"] = (ctx.rng.random((n, n)) < p["seed"]).astype(np.float32)
        st["heat"] = np.zeros((n, n), dtype=np.float32)
        st["stale"] = 0
    for _ in range(_tick(st, ctx, p["hz"])):
        g = st["g"]
        nb = sum(np.roll(np.roll(g, dy, 0), dx, 1)
                 for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dy or dx))
        new = ((nb == 3) | ((g == 1) & (nb == 2))).astype(np.float32)
        if np.array_equal(new, g) or new.sum() < n:
            st["stale"] += 1
            if st["stale"] > 2:
                new = (ctx.rng.random((n, n)) < p["seed"]).astype(np.float32)
                st["stale"] = 0
        else:
            st["stale"] = 0
        st["g"] = new
        st["heat"] = np.maximum(st["heat"] * p["fade"], new)
    v = _sample_grid(st["heat"], ctx)
    return pal.sample_clamped(p["palette"], v) * p["intensity"]


@effect("gray_scott", "Reacao-Difusao", "Simulacao",
        "Padroes de Turing: manchas e labirintos que crescem sozinhos.",
        [palette("palette", "Paleta", "magma"), integer("size", "Resolucao", 48, 16, 96, 1, "px"),
         num("feed", "Alimentacao", 0.055, 0.01, 0.09, 0.001),
         num("kill", "Remocao", 0.062, 0.03, 0.075, 0.001),
         integer("steps", "Passos por frame", 6, 1, 30), INTENSITY()])
def _gray_scott(ctx, p, st):
    n = int(p["size"])
    if st.get("_n") != n:
        st["_n"] = n
        st["a"] = np.ones((n, n), dtype=np.float32)
        st["b"] = np.zeros((n, n), dtype=np.float32)
        r = np.random.default_rng(4242)
        for _ in range(6):
            cy, cx = r.integers(4, n - 4, 2)
            st["b"][cy - 2:cy + 3, cx - 2:cx + 3] = 1.0
    a, b = st["a"], st["b"]
    da, db, dt = 1.0, 0.5, 1.0
    f, k = p["feed"], p["kill"]
    for _ in range(int(p["steps"])):
        abb = a * b * b
        a = a + (da * _laplacian(a) - abb + f * (1.0 - a)) * dt
        b = b + (db * _laplacian(b) + abb - (k + f) * b) * dt
        np.clip(a, 0.0, 1.0, out=a)
        np.clip(b, 0.0, 1.0, out=b)
    st["a"], st["b"] = a, b
    v = _sample_grid(b * 4.0, ctx)
    return pal.sample_clamped(p["palette"], np.clip(v, 0.0, 1.0)) * p["intensity"]


@effect("wave_eq", "Fisica de Ondas", "Simulacao",
        "Equacao da onda 2D de verdade: pancadas geram ondas que refletem e somam.",
        [palette("palette", "Paleta", "ocean"), integer("size", "Resolucao", 48, 16, 96, 1, "px"),
         num("damping", "Amortecimento", 0.996, 0.9, 1.0, 0.001),
         num("rate", "Pancadas", 1.5, 0.0, 20.0, 0.1, "/s"),
         num("force", "Forca", 1.0, 0.1, 4.0, 0.05),
         boolean("on_beat", "Disparar na batida", False), INTENSITY(),
         num("gain", "Ganho visual", 3.0, 0.2, 12.0, 0.1)])
def _wave_eq(ctx, p, st):
    n = int(p["size"])
    if st.get("_n") != n:
        st["_n"] = n
        st["u"] = np.zeros((n, n), dtype=np.float32)
        st["v"] = np.zeros((n, n), dtype=np.float32)
    u, v = st["u"], st["v"]
    hit = ctx.rng.random() < p["rate"] * ctx.dt
    if p["on_beat"] and ctx.audio.enabled and ctx.audio.beat > 0.75:
        hit = True
    if hit:
        cy, cx = ctx.rng.integers(3, n - 3, 2)
        u[cy - 1:cy + 2, cx - 1:cx + 2] += p["force"]
    v = (v + _laplacian(u) * 0.22) * p["damping"]
    u = (u + v) * p["damping"]
    st["u"], st["v"] = u, v
    val = _sample_grid(u, ctx) * p["gain"] * 0.5 + 0.5
    return pal.sample_clamped(p["palette"], np.clip(val, 0.0, 1.0)) * p["intensity"]


@effect("boids", "Cardume", "Simulacao",
        "Bando com separacao, alinhamento e coesao -- movimento coletivo real.",
        [palette("palette", "Paleta", "neon"), integer("count", "Individuos", 24, 4, 90),
         SPEED(0.35, 0.05, 2.0), num("size", "Tamanho", 0.09, 0.02, 0.35),
         num("cohesion", "Coesao", 0.6, 0.0, 2.0, 0.02),
         num("separation", "Separacao", 0.9, 0.0, 3.0, 0.02),
         num("alignment", "Alinhamento", 0.7, 0.0, 2.0, 0.02), INTENSITY()])
def _boids(ctx, p, st):
    k = int(p["count"])
    if st.get("_k") != k:
        st["_k"] = k
        r = np.random.default_rng(8080)
        st["pos"] = r.random((k, 2)).astype(np.float32)
        ang = r.random(k).astype(np.float32) * 6.283
        st["vel"] = np.stack([np.cos(ang), np.sin(ang)], axis=1).astype(np.float32)
        st["hue"] = r.random(k).astype(np.float32)

    pos, vel = st["pos"], st["vel"]
    d = pos[:, None, :] - pos[None, :, :]
    dist2 = (d ** 2).sum(-1) + np.eye(k, dtype=np.float32) * 9.0
    near = dist2 < 0.09

    center = np.where(near[..., None], pos[None, :, :], 0.0).sum(1)
    cnt = np.maximum(near.sum(1, keepdims=True), 1)
    coh = center / cnt - pos

    close = dist2 < 0.01
    sep = np.where(close[..., None], d, 0.0).sum(1)

    avg_v = np.where(near[..., None], vel[None, :, :], 0.0).sum(1) / cnt
    ali = avg_v - vel

    vel = vel + (coh * p["cohesion"] + sep * p["separation"] +
                 ali * p["alignment"]) * ctx.dt * 3.0
    vel += (np.clip(0.08 - pos, 0, None) - np.clip(pos - 0.92, 0, None)) * 4.0 * ctx.dt
    spd = np.linalg.norm(vel, axis=1, keepdims=True)
    vel = vel / np.maximum(spd, 1e-5)
    pos = np.clip(pos + vel * p["speed"] * ctx.dt, -0.05, 1.05)
    st["pos"], st["vel"] = pos.astype(np.float32), vel.astype(np.float32)

    dx = ctx.x[:, None] - pos[None, :, 0]
    dy = ctx.y[:, None] - pos[None, :, 1]
    dd = np.sqrt(dx * dx + dy * dy)
    m = np.clip(1.0 - dd / max(p["size"], 1e-4), 0.0, 1.0) ** 2
    cols = pal.sample(p["palette"], st["hue"] + ctx.t * 0.03)
    return np.clip(m @ cols, 0.0, 1.0) * p["intensity"]


@effect("automaton", "Automato 1D", "Simulacao",
        "Regra elementar de Wolfram gerando linhas novas que rolam pelo canvas.",
        [palette("palette", "Paleta", "cyberpunk"),
         integer("rule", "Regra", 30, 0, 255),
         integer("size", "Resolucao", 48, 8, 96, 1, "px"),
         num("hz", "Linhas por segundo", 12.0, 0.5, 60.0, 0.5, "/s"),
         boolean("random_seed", "Semente aleatoria", False), INTENSITY()])
def _automaton(ctx, p, st):
    n = int(p["size"])
    rule = int(p["rule"])
    if st.get("_n") != n or st.get("_rule") != rule:
        st["_n"] = n
        st["_rule"] = rule
        st["g"] = np.zeros((n, n), dtype=np.float32)
        row = np.zeros(n, dtype=np.float32)
        if p["random_seed"]:
            row = (ctx.rng.random(n) < 0.3).astype(np.float32)
        else:
            row[n // 2] = 1.0
        st["row"] = row
    for _ in range(_tick(st, ctx, p["hz"])):
        r = st["row"].astype(np.int32)
        left = np.roll(r, 1)
        right = np.roll(r, -1)
        idx = (left << 2) | (r << 1) | right
        st["row"] = ((rule >> idx) & 1).astype(np.float32)
        st["g"] = np.roll(st["g"], -1, axis=0)
        st["g"][-1] = st["row"]
    v = _sample_grid(st["g"], ctx)
    return pal.sample_clamped(p["palette"], v) * p["intensity"]


@effect("heat_diffusion", "Difusao de Calor", "Simulacao",
        "Fontes quentes aparecem e o calor escoa pela grade.",
        [palette("palette", "Paleta", "thermal"), integer("size", "Resolucao", 40, 12, 96, 1, "px"),
         num("rate", "Fontes", 2.0, 0.0, 20.0, 0.1, "/s"),
         num("diffuse", "Difusao", 0.22, 0.01, 0.24, 0.005),
         num("cool", "Resfriamento", 0.4, 0.0, 3.0, 0.02, "/s"), INTENSITY()])
def _heat(ctx, p, st):
    n = int(p["size"])
    if st.get("_n") != n:
        st["_n"] = n
        st["h"] = np.zeros((n, n), dtype=np.float32)
    h = st["h"]
    if ctx.rng.random() < p["rate"] * ctx.dt:
        cy, cx = ctx.rng.integers(2, n - 2, 2)
        h[cy - 1:cy + 2, cx - 1:cx + 2] = 1.0
    h = h + _laplacian(h) * p["diffuse"]
    h *= float(np.exp(-p["cool"] * ctx.dt))
    st["h"] = np.clip(h, 0.0, 1.0)
    return pal.sample_clamped(p["palette"], _sample_grid(st["h"], ctx)) * p["intensity"]
