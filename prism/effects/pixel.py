from __future__ import annotations

import numpy as np

from ..engine import palette as pal
from .base import (INTENSITY, SCOPE, SPEED, apply_scope, boolean, color,
                   effect, integer, num, palette)


def _head(ctx, speed):
    return np.floor(ctx.t * speed * ctx.piece_len).astype(np.int64)


def _dist(ctx, head):
    n = np.maximum(ctx.piece_len, 1)
    return (ctx.piece_pos.astype(np.int64) - head) % n


@effect("px_chase", "Ponto Fino", "Pixel",
        "Poucos LEDs acesos correndo pela fita, o resto apagado. Borda seca, "
        "sem degrade -- e o que rende numa fita de cabo.",
        [palette("palette", "Paleta", "rainbow"), SPEED(0.6),
         integer("width", "LEDs acesos", 2, 1, 12, 1, "leds"),
         integer("heads", "Pontos", 1, 1, 8),
         num("spread", "Cor ao longo", 0.15, 0.0, 1.0),
         color("bg", "Fundo", "#000000"), SCOPE(), INTENSITY()])
def _px_chase(ctx, p, st):
    n = np.maximum(ctx.piece_len, 1)
    head = _head(ctx, p["speed"])
    lit = np.zeros(ctx.n, dtype=bool)
    for k in range(int(p["heads"])):
        off = (n * k) // max(int(p["heads"]), 1)
        d = (ctx.piece_pos.astype(np.int64) - head - off) % n
        lit |= d < int(p["width"])
    out = np.tile(np.array(pal.hex_to_rgb(p["bg"]), dtype=np.float32), (ctx.n, 1))
    tone = ctx.piece01 * p["spread"] + ctx.t * 0.12
    cols = pal.sample(p["palette"], tone)
    out[lit] = cols[lit]
    return apply_scope(ctx, out, p) * p["intensity"]


@effect("px_marching", "Tracejado", "Pixel",
        "Um LED aceso a cada N, e o padrao inteiro desliza. Marca as laminas "
        "da fita uma a uma.",
        [palette("palette", "Paleta", "cyberpunk"), SPEED(0.4),
         integer("spacing", "Espacamento", 4, 2, 24, 1, "leds"),
         integer("width", "LEDs acesos", 1, 1, 8, 1, "leds"),
         num("spread", "Cor ao longo", 0.4, 0.0, 2.0),
         color("bg", "Fundo", "#000000"), SCOPE(), INTENSITY()])
def _px_marching(ctx, p, st):
    sp = max(int(p["spacing"]), 1)
    shift = np.floor(ctx.t * p["speed"] * sp * 2.0).astype(np.int64)
    lit = ((ctx.piece_pos.astype(np.int64) + shift) % sp) < int(p["width"])
    out = np.tile(np.array(pal.hex_to_rgb(p["bg"]), dtype=np.float32), (ctx.n, 1))
    cols = pal.sample(p["palette"], ctx.piece01 * p["spread"] + ctx.t * 0.1)
    out[lit] = cols[lit]
    return apply_scope(ctx, out, p) * p["intensity"]


@effect("px_comet", "Cometa Fino", "Pixel",
        "Cabeca de 1 LED com rastro curto que apaga em degraus inteiros, nao "
        "num degrade continuo.",
        [palette("palette", "Paleta", "ice"), SPEED(0.7),
         integer("tail", "Rastro", 4, 1, 24, 1, "leds"),
         integer("heads", "Cometas", 1, 1, 6),
         num("gamma", "Queda do rastro", 1.6, 0.4, 4.0, 0.05),
         SCOPE(), INTENSITY()])
def _px_comet(ctx, p, st):
    n = np.maximum(ctx.piece_len, 1)
    head = _head(ctx, p["speed"])
    tail = max(int(p["tail"]), 1)
    lvl = np.zeros(ctx.n, dtype=np.float32)
    for k in range(int(p["heads"])):
        off = (n * k) // max(int(p["heads"]), 1)
        d = (ctx.piece_pos.astype(np.int64) - head - off) % n
        base = np.clip(1.0 - d / tail, 0.0, 1.0)
        lvl = np.maximum(lvl, (base ** p["gamma"]).astype(np.float32))
    cols = pal.sample(p["palette"], ctx.piece01 * 0.3 + ctx.t * 0.08)
    return apply_scope(ctx, cols * lvl[:, None], p) * p["intensity"]


@effect("px_sparkle", "Faisca Fina", "Pixel",
        "LEDs isolados acendem e apagam secamente. Densidade baixa deixa a "
        "fita quase toda escura, com pontos vivos.",
        [palette("palette", "Paleta", "candy"),
         num("rate", "Nascimentos", 8.0, 0.2, 60.0, 0.2, "/s"),
         num("hold", "Duracao", 0.12, 0.02, 2.0, 0.01, "s"),
         num("density", "Densidade", 0.12, 0.01, 1.0),
         boolean("fade", "Apagar suave", False),
         SCOPE(), INTENSITY()])
def _px_sparkle(ctx, p, st):
    lvl = st.get("lvl")
    if lvl is None or len(lvl) != ctx.n:
        lvl = np.zeros(ctx.n, dtype=np.float32)
        st["hue"] = ctx.rng.random(ctx.n).astype(np.float32)
    if p["fade"]:
        lvl = lvl * float(np.exp(-ctx.dt / max(p["hold"], 1e-3)))
    else:
        age = st.get("age")
        if age is None or len(age) != ctx.n:
            age = np.zeros(ctx.n, dtype=np.float32)
        age += ctx.dt
        lvl = np.where(age < p["hold"], lvl, 0.0)
        st["age"] = age
    born = ctx.rng.random(ctx.n) < (p["rate"] * ctx.dt * p["density"])
    if born.any():
        lvl[born] = 1.0
        st["hue"][born] = ctx.rng.random(int(born.sum())).astype(np.float32)
        if not p["fade"]:
            st["age"][born] = 0.0
    st["lvl"] = lvl
    cols = pal.sample(p["palette"], st["hue"])
    return apply_scope(ctx, cols * lvl[:, None], p) * p["intensity"]


@effect("px_matrix", "Codigo", "Pixel",
        "Pontos caindo pela fita como chuva de codigo: cabeca clara, rastro "
        "curto, muita fita apagada entre eles.",
        [color("color", "Cor", "#00ff6a"), color("head", "Cor da cabeca", "#c8ffe0"),
         SPEED(0.9), integer("tail", "Rastro", 5, 1, 20, 1, "leds"),
         num("rate", "Novos fluxos", 1.6, 0.1, 12.0, 0.1, "/s"),
         integer("max", "Fluxos simultaneos", 4, 1, 16),
         SCOPE(), INTENSITY()])
def _px_matrix(ctx, p, st):
    k = int(p["max"])
    if st.get("_k") != k:
        st["_k"] = k
        st["pos"] = np.full(k, -999.0, dtype=np.float32)
        st["piece"] = np.zeros(k, dtype=np.int32)
    npieces = max(ctx.piece_count, 1)
    st["pos"] += p["speed"] * 20.0 * ctx.dt

    livres = np.flatnonzero(st["pos"] > 400)
    if len(livres) == 0:
        livres = np.flatnonzero(st["pos"] < -900)
    if len(livres) and ctx.rng.random() < p["rate"] * ctx.dt:
        i = int(livres[0])
        st["pos"][i] = 0.0
        st["piece"][i] = ctx.rng.integers(0, npieces)

    lvl = np.zeros(ctx.n, dtype=np.float32)
    ishead = np.zeros(ctx.n, dtype=bool)
    tail = max(int(p["tail"]), 1)
    for i in range(k):
        if st["pos"][i] < 0:
            continue
        mask = ctx.piece_index == st["piece"][i]
        if not mask.any():
            continue
        d = ctx.piece_pos.astype(np.float32) - st["pos"][i]
        vis = mask & (d <= 0) & (d > -tail)
        lvl = np.where(vis, np.maximum(lvl, 1.0 + d / tail), lvl)
        ishead |= mask & (np.abs(d) < 1.0)
        if st["pos"][i] > ctx.piece_len.max() + tail:
            st["pos"][i] = 999

    base = np.array(pal.hex_to_rgb(p["color"]), dtype=np.float32)
    hd = np.array(pal.hex_to_rgb(p["head"]), dtype=np.float32)
    out = base[None, :] * lvl[:, None]
    out[ishead] = hd
    return apply_scope(ctx, np.clip(out, 0, 1), p) * p["intensity"]


@effect("px_scan", "Varredura Fina", "Pixel",
        "Uma linha de 1-2 LEDs varrendo a fita de ponta a ponta, com rastro "
        "curto e o resto totalmente escuro.",
        [color("color", "Cor", "#ffffff"), SPEED(0.5),
         integer("width", "Espessura", 1, 1, 6, 1, "leds"),
         integer("tail", "Rastro", 3, 0, 20, 1, "leds"),
         boolean("bounce", "Vai e volta", True),
         color("bg", "Fundo", "#000000"), SCOPE(), INTENSITY()])
def _px_scan(ctx, p, st):
    n = np.maximum(ctx.piece_len, 1).astype(np.float32)
    if p["bounce"]:
        cyc = (ctx.t * p["speed"]) % 2.0
        ph = cyc if cyc <= 1.0 else 2.0 - cyc
    else:
        ph = (ctx.t * p["speed"]) % 1.0
    head = np.floor(ph * (n - 1))
    d = ctx.piece_pos.astype(np.float32) - head
    core = np.abs(d) < p["width"]
    lvl = core.astype(np.float32)
    if p["tail"] > 0:
        atras = (d < 0) & (d > -float(p["tail"]))
        lvl = np.maximum(lvl, np.where(atras, 1.0 + d / float(p["tail"]), 0.0))
    fg = np.array(pal.hex_to_rgb(p["color"]), dtype=np.float32)
    bg = np.array(pal.hex_to_rgb(p["bg"]), dtype=np.float32)
    out = bg[None, :] + fg[None, :] * lvl[:, None]
    return apply_scope(ctx, np.clip(out, 0, 1), p) * p["intensity"]


@effect("px_split", "Abertura", "Pixel",
        "Dois LEDs saem do centro da fita para as pontas e voltam.",
        [palette("palette", "Paleta", "neon"), SPEED(0.5),
         integer("width", "LEDs acesos", 1, 1, 6, 1, "leds"),
         integer("tail", "Rastro", 3, 0, 16, 1, "leds"),
         color("bg", "Fundo", "#000000"), SCOPE(), INTENSITY()])
def _px_split(ctx, p, st):
    n = np.maximum(ctx.piece_len, 1).astype(np.float32)
    meio = (n - 1) / 2.0
    cyc = (ctx.t * p["speed"]) % 2.0
    ph = cyc if cyc <= 1.0 else 2.0 - cyc
    raio = ph * meio
    d = np.abs(ctx.piece_pos.astype(np.float32) - meio) - raio
    lvl = (np.abs(d) < p["width"]).astype(np.float32)
    if p["tail"] > 0:
        dentro = (d < 0) & (d > -float(p["tail"]))
        lvl = np.maximum(lvl, np.where(dentro, 1.0 + d / float(p["tail"]), 0.0))
    cols = pal.sample(p["palette"], np.float32(ph) + ctx.piece_id * 0.1)
    bg = np.array(pal.hex_to_rgb(p["bg"]), dtype=np.float32)
    out = bg[None, :] + cols * lvl[:, None]
    return apply_scope(ctx, np.clip(out, 0, 1), p) * p["intensity"]


@effect("px_pairs", "Pares Cruzados", "Pixel",
        "Dois pontos correndo em sentidos opostos dentro da fita, cruzando.",
        [color("a", "Cor A", "#ff2d55"), color("b", "Cor B", "#00d9ff"),
         SPEED(0.5), integer("width", "LEDs acesos", 2, 1, 8, 1, "leds"),
         color("bg", "Fundo", "#000000"), SCOPE(), INTENSITY()])
def _px_pairs(ctx, p, st):
    n = np.maximum(ctx.piece_len, 1)
    pos = ctx.piece_pos.astype(np.int64)
    h = _head(ctx, p["speed"])
    da = (pos - h) % n
    db = (pos + h) % n
    w = int(p["width"])
    ca = np.array(pal.hex_to_rgb(p["a"]), dtype=np.float32)
    cb = np.array(pal.hex_to_rgb(p["b"]), dtype=np.float32)
    bg = np.array(pal.hex_to_rgb(p["bg"]), dtype=np.float32)
    out = np.tile(bg, (ctx.n, 1))
    out[da < w] = ca
    out[db < w] = cb
    both = (da < w) & (db < w)
    out[both] = np.clip(ca + cb, 0, 1)
    return apply_scope(ctx, out, p) * p["intensity"]


@effect("px_fill", "Enchendo", "Pixel",
        "A fita enche LED a LED ate o fim, esvazia e recomeca. Transicao seca "
        "em cada lamina.",
        [palette("palette", "Paleta", "ocean"), SPEED(0.5),
         boolean("reverse", "Encher pelo outro lado", False),
         boolean("drain", "Esvaziar no fim", True),
         color("bg", "Fundo", "#000000"), SCOPE(), INTENSITY()])
def _px_fill(ctx, p, st):
    n = np.maximum(ctx.piece_len, 1).astype(np.float32)
    cyc = (ctx.t * p["speed"]) % (2.0 if p["drain"] else 1.0)
    nivel = cyc if cyc <= 1.0 else 2.0 - cyc
    pos = ctx.piece_pos.astype(np.float32)
    if p["reverse"]:
        pos = (n - 1) - pos
    lit = pos <= np.floor(nivel * n)
    out = np.tile(np.array(pal.hex_to_rgb(p["bg"]), dtype=np.float32), (ctx.n, 1))
    cols = pal.sample(p["palette"], ctx.piece01 * 0.7 + ctx.t * 0.06)
    out[lit] = cols[lit]
    return apply_scope(ctx, out, p) * p["intensity"]


@effect("px_bars", "Barras", "Pixel",
        "Blocos de LEDs acesos e apagados em tamanhos iguais, deslizando. "
        "Marca bem as laminas da fita.",
        [palette("palette", "Paleta", "vaporwave"), SPEED(0.35),
         integer("on", "LEDs acesos", 3, 1, 20, 1, "leds"),
         integer("off", "LEDs apagados", 5, 1, 30, 1, "leds"),
         num("spread", "Cor por bloco", 0.25, 0.0, 1.0),
         SCOPE(), INTENSITY()])
def _px_bars(ctx, p, st):
    periodo = max(int(p["on"]) + int(p["off"]), 1)
    shift = np.floor(ctx.t * p["speed"] * periodo * 2.0).astype(np.int64)
    fase = (ctx.piece_pos.astype(np.int64) + shift) % periodo
    lit = fase < int(p["on"])
    bloco = ((ctx.piece_pos.astype(np.int64) + shift) // periodo).astype(np.float32)
    out = np.zeros((ctx.n, 3), dtype=np.float32)
    cols = pal.sample(p["palette"], bloco * p["spread"] + ctx.t * 0.05)
    out[lit] = cols[lit]
    return apply_scope(ctx, out, p) * p["intensity"]


@effect("px_twinkle_gap", "Cintilar Esparso", "Pixel",
        "A fita fica quase toda escura, com poucos LEDs vivos que trocam de "
        "lugar devagar. Discreto e continuo.",
        [palette("palette", "Paleta", "ice"),
         integer("lit", "LEDs vivos por peca", 3, 1, 20, 1, "leds"),
         num("hz", "Trocas", 1.2, 0.05, 12.0, 0.05, "/s"),
         num("fade", "Suavizacao", 0.85, 0.0, 0.98),
         SCOPE(), INTENSITY()])
def _px_twinkle_gap(ctx, p, st):
    passo = int(ctx.t * p["hz"])
    if st.get("_p") != passo or st.get("_n") != ctx.n:
        st["_p"] = passo
        st["_n"] = ctx.n
        alvo = np.zeros(ctx.n, dtype=np.float32)
        for start, count in ctx.canvas.pieces:
            k = min(int(p["lit"]), count)
            if k <= 0:
                continue
            idx = ctx.rng.choice(count, size=k, replace=False)
            alvo[start + idx] = 1.0
        st["alvo"] = alvo
        st["hue"] = ctx.rng.random(ctx.n).astype(np.float32)
    cur = st.get("cur")
    if cur is None or len(cur) != ctx.n:
        cur = np.zeros(ctx.n, dtype=np.float32)
    cur = cur + (st["alvo"] - cur) * (1.0 - p["fade"])
    st["cur"] = cur
    cols = pal.sample(p["palette"], st["hue"])
    return apply_scope(ctx, cols * cur[:, None], p) * p["intensity"]


@effect("px_audio_bars", "Barras de Audio", "Pixel",
        "A fita vira um medidor: os LEDs acendem um a um conforme o volume, "
        "com o topo destacado.",
        [palette("palette", "Paleta", "thermal"),
         num("gain", "Ganho", 1.3, 0.1, 6.0, 0.05, "x"),
         num("attack", "Ataque", 0.7, 0.02, 1.0),
         num("release", "Queda", 0.1, 0.01, 1.0),
         color("peak", "Cor do topo", "#ffffff"),
         boolean("mirror", "Do centro", False),
         SCOPE(), INTENSITY()],
        needs=("audio",))
def _px_audio_bars(ctx, p, st):
    alvo = min(1.0, ctx.audio.level * p["gain"])
    cur = st.get("lvl", 0.0)
    cur = cur + (alvo - cur) * (p["attack"] if alvo > cur else p["release"])
    st["lvl"] = cur

    n = np.maximum(ctx.piece_len, 1).astype(np.float32)
    pos = ctx.piece_pos.astype(np.float32)
    if p["mirror"]:
        pos = np.abs(pos - (n - 1) / 2.0) * 2.0
    topo = np.floor(cur * n)
    lit = pos < topo
    nopico = np.abs(pos - (topo - 1)) < 1.0

    out = np.zeros((ctx.n, 3), dtype=np.float32)
    cols = pal.sample_clamped(p["palette"], pos / np.maximum(n - 1, 1))
    out[lit] = cols[lit]
    out[nopico & lit] = np.array(pal.hex_to_rgb(p["peak"]), dtype=np.float32)
    return apply_scope(ctx, out, p) * p["intensity"]


@effect("px_spectrum", "Espectro Fino", "Pixel",
        "Cada LED da fita e uma faixa de frequencia, com corte seco: parece um "
        "analisador de espectro de barras finas.",
        [palette("palette", "Paleta", "turbo"),
         num("gain", "Ganho", 1.4, 0.1, 8.0, 0.05, "x"),
         num("smooth", "Suavizacao", 0.4, 0.0, 0.95),
         num("threshold", "Corte", 0.25, 0.0, 1.0),
         boolean("mirror", "Espelhado", True),
         SCOPE(), INTENSITY()],
        needs=("audio",))
def _px_spectrum(ctx, p, st):
    u = ctx.piece01
    if p["mirror"]:
        u = np.abs(u - 0.5) * 2.0
    mag = np.clip(ctx.audio.band_at(u) * p["gain"], 0.0, 1.0)
    prev = st.get("mag")
    if prev is not None and len(prev) == len(mag):
        mag = prev * p["smooth"] + mag * (1.0 - p["smooth"])
    st["mag"] = mag
    lit = mag > p["threshold"]
    out = np.zeros((ctx.n, 3), dtype=np.float32)
    cols = pal.sample_clamped(p["palette"], u)
    out[lit] = (cols * mag[:, None])[lit]
    return apply_scope(ctx, out, p) * p["intensity"]
