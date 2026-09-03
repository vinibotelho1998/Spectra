from __future__ import annotations

import numpy as np

from ..engine import palette as pal
from .base import (INTENSITY, SPEED, boolean, choice, color, effect, integer,
                   num, palette)


def _blobs(ctx, px, py, radius, cols, softness=2.0):
    if len(px) == 0:
        return np.zeros((ctx.n, 3), dtype=np.float32)
    dx = ctx.x[:, None] - px[None, :]
    dy = ctx.y[:, None] - py[None, :]
    d = np.sqrt(dx * dx + dy * dy)
    r = np.maximum(np.asarray(radius, dtype=np.float32), 1e-4)
    m = np.clip(1.0 - d / r, 0.0, 1.0) ** softness
    return np.clip(m @ cols, 0.0, 1.0).astype(np.float32)


def _respawn_state(st, key, k, rng_seed):
    if st.get(key) != k:
        st[key] = k
        st["rng"] = np.random.default_rng(rng_seed)
        return True
    return False


@effect("twinkle", "Cintilar", "Particulas",
        "LEDs individuais acendem e apagam em tempos aleatorios.",
        [palette("palette", "Paleta", "ice"), num("rate", "Nascimentos", 6.0, 0.2, 60.0, 0.2, "/s"),
         num("decay", "Decaimento", 1.8, 0.1, 10.0, 0.05, "/s"),
         num("density", "Densidade", 0.25, 0.01, 1.0), INTENSITY()])
def _twinkle(ctx, p, st):
    lvl = st.get("lvl")
    if lvl is None or len(lvl) != ctx.n:
        lvl = np.zeros(ctx.n, dtype=np.float32)
        st["hue"] = ctx.rng.random(ctx.n).astype(np.float32)
    lvl *= np.exp(-p["decay"] * ctx.dt)
    born = ctx.rng.random(ctx.n) < (p["rate"] * ctx.dt * p["density"])
    if born.any():
        lvl[born] = 1.0
        st["hue"][born] = ctx.rng.random(int(born.sum())).astype(np.float32)
    st["lvl"] = lvl
    return pal.sample(p["palette"], st["hue"]) * lvl[:, None] * p["intensity"]


@effect("rain", "Chuva", "Particulas",
        "Gotas caindo com rastro, respeitando a altura real de cada LED.",
        [color("color", "Cor", "#4fc3f7"), integer("drops", "Gotas", 14, 1, 80),
         SPEED(1.0, 0.05, 5.0), num("length", "Rastro", 0.18, 0.02, 0.6),
         num("width", "Espessura", 0.05, 0.01, 0.3),
         boolean("up", "Cair para cima", False), INTENSITY()])
def _rain(ctx, p, st):
    k = int(p["drops"])
    if _respawn_state(st, "_k", k, 424242):
        r = st["rng"]
        st["px"] = r.random(k).astype(np.float32)
        st["py"] = r.random(k).astype(np.float32)
        st["sp"] = (0.4 + r.random(k).astype(np.float32) * 0.8)
    d = -1.0 if p["up"] else 1.0
    st["py"] = st["py"] + st["sp"] * p["speed"] * ctx.dt * d
    if p["up"]:
        gone = st["py"] < -p["length"]
    else:
        gone = st["py"] > 1.0 + p["length"]
    if gone.any():
        m = int(gone.sum())
        st["py"][gone] = (1.0 + p["length"]) if p["up"] else -p["length"]
        st["px"][gone] = st["rng"].random(m).astype(np.float32)
        st["sp"][gone] = 0.4 + st["rng"].random(m).astype(np.float32) * 0.8

    dx = np.abs(ctx.x[:, None] - st["px"][None, :])
    dy = ctx.y[:, None] - st["py"][None, :]
    if p["up"]:
        dy = -dy
    tail = np.clip(1.0 + dy / max(p["length"], 1e-4), 0.0, 1.0) * (dy <= 0)
    across = np.clip(1.0 - dx / max(p["width"], 1e-4), 0.0, 1.0)
    m = (tail ** 2) * across
    c = np.array(pal.hex_to_rgb(p["color"]), dtype=np.float32)
    return np.clip(m.sum(axis=1)[:, None] * c, 0.0, 1.0) * p["intensity"]


@effect("snow", "Neve", "Particulas",
        "Flocos caindo devagar, com deriva lateral.",
        [color("color", "Cor", "#e8f4ff"), integer("flakes", "Flocos", 20, 1, 90),
         SPEED(0.35, 0.02, 3.0), num("size", "Tamanho", 0.06, 0.01, 0.3),
         num("drift", "Deriva", 0.12, 0.0, 0.6), INTENSITY()])
def _snow(ctx, p, st):
    k = int(p["flakes"])
    if _respawn_state(st, "_k", k, 90210):
        r = st["rng"]
        st["px"] = r.random(k).astype(np.float32)
        st["py"] = r.random(k).astype(np.float32)
        st["ph"] = r.random(k).astype(np.float32) * 6.28
        st["sp"] = 0.5 + r.random(k).astype(np.float32)
    st["py"] = st["py"] + st["sp"] * p["speed"] * ctx.dt
    gone = st["py"] > 1.0 + p["size"]
    if gone.any():
        st["py"][gone] = -p["size"]
        st["px"][gone] = st["rng"].random(int(gone.sum())).astype(np.float32)
    x = st["px"] + p["drift"] * np.sin(ctx.t * 0.8 + st["ph"])
    c = np.array(pal.hex_to_rgb(p["color"]), dtype=np.float32)
    cols = np.tile(c, (k, 1))
    return _blobs(ctx, x, st["py"], p["size"], cols) * p["intensity"]


@effect("fireflies", "Vagalumes", "Particulas",
        "Pontos que vagam devagar e pulsam fora de fase.",
        [palette("palette", "Paleta", "toxic"), integer("count", "Quantidade", 10, 1, 50),
         SPEED(0.25, 0.02, 2.0), num("size", "Tamanho", 0.1, 0.02, 0.4),
         num("blink", "Pulsacao", 1.2, 0.0, 5.0, 0.05, "Hz"), INTENSITY()])
def _fireflies(ctx, p, st):
    k = int(p["count"])
    if _respawn_state(st, "_k", k, 5150):
        r = st["rng"]
        st["px"] = r.random(k).astype(np.float32)
        st["py"] = r.random(k).astype(np.float32)
        st["ph"] = r.random(k).astype(np.float32) * 6.28
        st["hue"] = r.random(k).astype(np.float32)
        st["ang"] = r.random(k).astype(np.float32) * 6.28
    st["ang"] = st["ang"] + (np.random.random(k).astype(np.float32) - 0.5) * 2.0 * ctx.dt
    st["px"] = np.clip(st["px"] + np.cos(st["ang"]) * p["speed"] * ctx.dt, 0.0, 1.0)
    st["py"] = np.clip(st["py"] + np.sin(st["ang"]) * p["speed"] * ctx.dt, 0.0, 1.0)
    puls = 0.35 + 0.65 * (np.sin(ctx.t * p["blink"] * 6.28 + st["ph"]) * 0.5 + 0.5)
    cols = pal.sample(p["palette"], st["hue"]) * puls[:, None]
    return _blobs(ctx, st["px"], st["py"], p["size"], cols) * p["intensity"]


@effect("meteor", "Meteoros", "Particulas",
        "Riscos atravessando o canvas em diagonal, com cauda que apaga.",
        [palette("palette", "Paleta", "sunset"), integer("count", "Meteoros", 4, 1, 20),
         SPEED(0.8, 0.05, 4.0), num("length", "Cauda", 0.3, 0.05, 1.0),
         num("width", "Espessura", 0.06, 0.01, 0.3),
         num("angle", "Angulo", 35.0, 0.0, 360.0, 1.0, "graus"), INTENSITY()])
def _meteor(ctx, p, st):
    k = int(p["count"])
    if _respawn_state(st, "_k", k, 7777):
        r = st["rng"]
        st["t0"] = r.random(k).astype(np.float32)
        st["off"] = r.random(k).astype(np.float32)
        st["hue"] = r.random(k).astype(np.float32)
        st["sp"] = 0.6 + r.random(k).astype(np.float32) * 0.8
    a = np.radians(p["angle"], dtype=np.float32)
    ux, uy = np.cos(a), np.sin(a)
    along = ctx.x * ux + ctx.y * uy
    perp = -ctx.x * uy + ctx.y * ux
    lo, hi = float(along.min()), float(along.max())
    span = max(hi - lo, 1e-6)
    plo, phi = float(perp.min()), float(perp.max())

    out = np.zeros((ctx.n, 3), dtype=np.float32)
    for i in range(k):
        ph = (ctx.t * p["speed"] * st["sp"][i] + st["t0"][i]) % 1.4
        head = lo - p["length"] * span + ph * span * (1.0 + 2 * p["length"])
        lane = plo + st["off"][i] * max(phi - plo, 1e-6)
        d_along = along - head
        d_perp = np.abs(perp - lane)
        tail = np.clip(1.0 + d_along / max(p["length"] * span, 1e-4), 0.0, 1.0)
        tail = np.where(d_along <= 0, tail, 0.0) ** 2
        across = np.clip(1.0 - d_perp / max(p["width"], 1e-4), 0.0, 1.0)
        c = pal.sample(p["palette"], st["hue"][i])
        out += c * (tail * across)[:, None]
    return np.clip(out, 0.0, 1.0) * p["intensity"]


@effect("confetti", "Confete", "Particulas",
        "Explosoes de pontos coloridos que somem rapido.",
        [palette("palette", "Paleta", "candy"), num("rate", "Nascimentos", 25.0, 1.0, 200.0, 1.0, "/s"),
         num("life", "Duracao", 0.8, 0.1, 5.0, 0.05, "s"),
         num("size", "Tamanho", 0.07, 0.01, 0.3),
         integer("max", "Maximo simultaneo", 40, 4, 200), INTENSITY()])
def _confetti(ctx, p, st):
    k = int(p["max"])
    if _respawn_state(st, "_k", k, 31415):
        st["px"] = np.zeros(k, dtype=np.float32)
        st["py"] = np.zeros(k, dtype=np.float32)
        st["life"] = np.zeros(k, dtype=np.float32)
        st["hue"] = np.zeros(k, dtype=np.float32)
    st["life"] = np.maximum(st["life"] - ctx.dt, 0.0)
    dead = np.flatnonzero(st["life"] <= 0.0)
    n_new = int(min(len(dead), np.random.poisson(max(p["rate"] * ctx.dt, 0.0))))
    if n_new:
        pick = dead[:n_new]
        r = st["rng"]
        st["px"][pick] = r.random(n_new).astype(np.float32)
        st["py"][pick] = r.random(n_new).astype(np.float32)
        st["life"][pick] = p["life"]
        st["hue"][pick] = r.random(n_new).astype(np.float32)
    alive = st["life"] > 0
    if not alive.any():
        return ctx.zeros()
    fade = (st["life"][alive] / max(p["life"], 1e-4)) ** 0.6
    cols = pal.sample(p["palette"], st["hue"][alive]) * fade[:, None]
    return _blobs(ctx, st["px"][alive], st["py"][alive], p["size"], cols) * p["intensity"]


@effect("lightning", "Raios", "Particulas",
        "Escuridao com clarões repentinos e ramificados.",
        [color("color", "Cor", "#dbeaff"), num("rate", "Raios", 0.6, 0.05, 8.0, 0.05, "/s"),
         num("decay", "Decaimento", 9.0, 1.0, 40.0, 0.5, "/s"),
         num("width", "Espessura", 0.14, 0.02, 0.6),
         color("ambient", "Ambiente", "#050912"), INTENSITY()])
def _lightning(ctx, p, st):
    lvl = float(st.get("lvl", 0.0)) * float(np.exp(-p["decay"] * ctx.dt))
    if np.random.random() < p["rate"] * ctx.dt:
        lvl = 1.0
        st["bx"] = float(np.random.random())
        st["flick"] = float(np.random.random())
    st["lvl"] = lvl
    amb = np.array(pal.hex_to_rgb(p["ambient"]), dtype=np.float32)
    out = np.tile(amb, (ctx.n, 1))
    if lvl > 0.01:
        bx = float(st.get("bx", 0.5))
        jitter = 0.06 * np.sin(ctx.y * 18.0 + st.get("flick", 0.0) * 30.0)
        d = np.abs(ctx.x - (bx + jitter))
        m = np.clip(1.0 - d / max(p["width"], 1e-4), 0.0, 1.0) ** 2
        c = np.array(pal.hex_to_rgb(p["color"]), dtype=np.float32)
        glow = lvl * 0.25
        out = out + c * (m * lvl)[:, None] + c * glow
    return np.clip(out, 0.0, 1.0) * p["intensity"]


@effect("bubbles", "Bolhas", "Particulas",
        "Bolhas subindo com aneis de contorno.",
        [palette("palette", "Paleta", "ocean"), integer("count", "Bolhas", 12, 1, 60),
         SPEED(0.35, 0.02, 3.0), num("size", "Tamanho", 0.09, 0.02, 0.4),
         num("ring", "Contorno", 0.5, 0.0, 1.0), INTENSITY()])
def _bubbles(ctx, p, st):
    k = int(p["count"])
    if _respawn_state(st, "_k", k, 2718):
        r = st["rng"]
        st["px"] = r.random(k).astype(np.float32)
        st["py"] = r.random(k).astype(np.float32)
        st["sp"] = 0.5 + r.random(k).astype(np.float32)
        st["hue"] = r.random(k).astype(np.float32)
        st["ph"] = r.random(k).astype(np.float32) * 6.28
    st["py"] = st["py"] - st["sp"] * p["speed"] * ctx.dt
    gone = st["py"] < -p["size"]
    if gone.any():
        st["py"][gone] = 1.0 + p["size"]
        st["px"][gone] = st["rng"].random(int(gone.sum())).astype(np.float32)
    x = st["px"] + 0.04 * np.sin(ctx.t * 1.5 + st["ph"])
    dx = ctx.x[:, None] - x[None, :]
    dy = ctx.y[:, None] - st["py"][None, :]
    d = np.sqrt(dx * dx + dy * dy) / max(p["size"], 1e-4)
    disc = np.clip(1.0 - d, 0.0, 1.0)
    shell = np.clip(1.0 - np.abs(d - 0.8) / 0.25, 0.0, 1.0)
    m = disc * (1.0 - p["ring"]) + shell * p["ring"]
    cols = pal.sample(p["palette"], st["hue"])
    return np.clip(m @ cols, 0.0, 1.0) * p["intensity"]


@effect("fireworks", "Fogos", "Particulas",
        "Foguete sobe, explode e as faiscas caem com gravidade.",
        [palette("palette", "Paleta", "neon"), num("rate", "Lançamentos", 0.8, 0.05, 6.0, 0.05, "/s"),
         integer("sparks", "Faiscas", 24, 4, 80),
         num("gravity", "Gravidade", 0.5, 0.0, 2.0, 0.02),
         num("life", "Duracao", 1.4, 0.2, 5.0, 0.05, "s"),
         num("size", "Tamanho", 0.06, 0.01, 0.25), INTENSITY()])
def _fireworks(ctx, p, st):
    k = int(p["sparks"])
    if _respawn_state(st, "_k", k, 1123):
        for key in ("px", "py", "vx", "vy", "life"):
            st[key] = np.zeros(k, dtype=np.float32)
        st["hue"] = 0.0

    st["life"] = np.maximum(st["life"] - ctx.dt, 0.0)
    live = st["life"] > 0
    if live.any():
        st["vy"][live] += p["gravity"] * ctx.dt
        st["px"][live] += st["vx"][live] * ctx.dt
        st["py"][live] += st["vy"][live] * ctx.dt

    if not live.any() and np.random.random() < p["rate"] * ctx.dt * 6.0:
        r = st["rng"]
        cx = 0.2 + r.random() * 0.6
        cy = 0.2 + r.random() * 0.4
        ang = r.random(k).astype(np.float32) * 6.283
        spd = (0.15 + r.random(k).astype(np.float32) * 0.35)
        st["px"][:] = cx
        st["py"][:] = cy
        st["vx"][:] = np.cos(ang) * spd
        st["vy"][:] = np.sin(ang) * spd
        st["life"][:] = p["life"] * (0.6 + r.random(k).astype(np.float32) * 0.4)
        st["hue"] = float(r.random())
        live = st["life"] > 0

    if not live.any():
        return ctx.zeros()
    fade = (st["life"][live] / max(p["life"], 1e-4)) ** 0.8
    base = pal.sample(p["palette"], np.float32(st["hue"]))
    cols = np.tile(base, (int(live.sum()), 1)) * fade[:, None]
    return _blobs(ctx, st["px"][live], st["py"][live], p["size"], cols) * p["intensity"]


@effect("comet", "Cometa", "Particulas",
        "Um corpo em orbita deixando rastro que se apaga.",
        [palette("palette", "Paleta", "ice"), SPEED(0.5), integer("trail", "Rastro", 18, 2, 60),
         num("radius", "Raio da orbita", 0.32, 0.05, 0.7),
         num("size", "Tamanho", 0.09, 0.02, 0.35), INTENSITY()])
def _comet(ctx, p, st):
    k = int(p["trail"])
    lag = np.arange(k, dtype=np.float32) * 0.05
    a = ctx.t * p["speed"] * 2.0 - lag
    px = 0.5 + p["radius"] * np.cos(a)
    py = 0.5 + p["radius"] * np.sin(a) * 0.8
    fade = (1.0 - np.arange(k, dtype=np.float32) / k) ** 2
    cols = pal.sample(p["palette"], np.linspace(0, 0.3, k) + ctx.t * 0.05) * fade[:, None]
    sizes = p["size"] * (0.35 + 0.65 * fade)
    dx = ctx.x[:, None] - px[None, :]
    dy = ctx.y[:, None] - py[None, :]
    d = np.sqrt(dx * dx + dy * dy)
    m = np.clip(1.0 - d / np.maximum(sizes[None, :], 1e-4), 0.0, 1.0) ** 2
    return np.clip(m @ cols, 0.0, 1.0) * p["intensity"]
