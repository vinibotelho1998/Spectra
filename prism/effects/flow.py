from __future__ import annotations

import numpy as np

from ..engine import palette as pal
from .base import (INTENSITY, SPEED, boolean, choice, color, colors, effect,
                   integer, num, palette)


def PHASE(default=0.0):
    return num("phase", "Defasagem entre pecas", default, 0.0, 1.0, 0.01)


def _chain(ctx):
    n = max(ctx.piece_count, 1)
    return (ctx.piece_index.astype(np.float32) + ctx.piece01) / n


@effect("runway", "Pista", "Fluxo",
        "Faixas de cor correndo do inicio ao fim de cada fita e dando a volta "
        "em cada fan. E o efeito assinatura das fitas de cabo.",
        [palette("palette", "Paleta", "rainbow"), SPEED(0.5),
         num("bands", "Faixas por peca", 2.0, 0.25, 12.0, 0.25),
         PHASE(0.0), boolean("reverse", "Inverter sentido", False), INTENSITY()])
def _runway(ctx, p, st):
    d = -1.0 if p["reverse"] else 1.0
    u = ctx.piece01 * p["bands"] + ctx.piece_id * p["phase"] * p["bands"]
    return pal.sample(p["palette"], u - ctx.t * p["speed"] * d) * p["intensity"]


@effect("neon_flow", "Fluxo Neon", "Fluxo",
        "Um ponto brilhante percorre cada peca deixando um rastro que apaga. "
        "Nitido, com fundo escuro -- o look de tubo de neon.",
        [color("color", "Cor", "#00e5ff"), color("bg", "Fundo", "#03060c"),
         SPEED(0.6), num("tail", "Rastro", 0.35, 0.05, 1.0),
         integer("heads", "Pontos por peca", 1, 1, 6),
         PHASE(0.25), boolean("reverse", "Inverter sentido", False), INTENSITY()])
def _neon_flow(ctx, p, st):
    d = -1.0 if p["reverse"] else 1.0
    fg = np.array(pal.hex_to_rgb(p["color"]), dtype=np.float32)
    bg = np.array(pal.hex_to_rgb(p["bg"]), dtype=np.float32)
    m = np.zeros(ctx.n, dtype=np.float32)
    for k in range(int(p["heads"])):
        ph = (ctx.t * p["speed"] * d + ctx.piece_id * p["phase"]
              + k / max(p["heads"], 1))
        delta = (ctx.piece01 - ph) % 1.0
        m = np.maximum(m, np.clip(1.0 - delta / max(p["tail"], 1e-4), 0.0, 1.0) ** 2)
    m = m[:, None]
    return (bg * (1 - m) + fg * m) * p["intensity"]


@effect("dual_stream", "Fluxo Duplo", "Fluxo",
        "Duas cores correndo em sentidos opostos dentro da mesma peca, se "
        "cruzando no meio.",
        [color("a", "Cor A", "#ff2d55"), color("b", "Cor B", "#00d9ff"),
         SPEED(0.45), num("width", "Largura", 0.3, 0.05, 1.0),
         PHASE(0.0), color("bg", "Fundo", "#03060c"), INTENSITY()])
def _dual_stream(ctx, p, st):
    ph = ctx.t * p["speed"] + ctx.piece_id * p["phase"]
    da = (ctx.piece01 - ph) % 1.0
    db = (ctx.piece01 + ph) % 1.0
    ma = np.clip(1.0 - da / max(p["width"], 1e-4), 0.0, 1.0) ** 2
    mb = np.clip(1.0 - db / max(p["width"], 1e-4), 0.0, 1.0) ** 2
    ca = np.array(pal.hex_to_rgb(p["a"]), dtype=np.float32)
    cb = np.array(pal.hex_to_rgb(p["b"]), dtype=np.float32)
    bg = np.array(pal.hex_to_rgb(p["bg"]), dtype=np.float32)
    out = bg + ca * ma[:, None] + cb * mb[:, None]
    return np.clip(out, 0.0, 1.0) * p["intensity"]


@effect("stack", "Empilhar", "Fluxo",
        "LEDs viajam ate o fim da peca e vao se acumulando, ate encher. Depois "
        "esvazia e recomeca.",
        [palette("palette", "Paleta", "ocean"), SPEED(0.8),
         color("bg", "Fundo", "#03060c"), PHASE(0.15),
         boolean("reverse", "Encher pelo outro lado", False), INTENSITY()])
def _stack(ctx, p, st):
    u = 1.0 - ctx.piece01 if p["reverse"] else ctx.piece01
    cyc = (ctx.t * p["speed"] * 0.35 + ctx.piece_id * p["phase"]) % 2.0
    level = np.where(cyc <= 1.0, cyc, 2.0 - cyc)
    filled = u <= level
    out = np.tile(np.array(pal.hex_to_rgb(p["bg"]), dtype=np.float32), (ctx.n, 1))
    if filled.any():
        out[filled] = pal.sample(p["palette"],
                                 u[filled] * 0.8 + ctx.t * p["speed"] * 0.1)
    return out * p["intensity"]


@effect("bounce", "Vai e Vem", "Fluxo",
        "Uma barra de luz quicando entre as pontas de cada peca.",
        [color("color", "Cor", "#7cff00"), color("bg", "Fundo", "#03060c"),
         SPEED(0.7), num("width", "Largura", 0.22, 0.03, 0.8),
         PHASE(0.3), num("glow", "Brilho residual", 0.25, 0.0, 1.0), INTENSITY()])
def _bounce(ctx, p, st):
    cyc = (ctx.t * p["speed"] + ctx.piece_id * p["phase"]) % 2.0
    pos = np.where(cyc <= 1.0, cyc, 2.0 - cyc)
    d = np.abs(ctx.piece01 - pos)
    m = np.clip(1.0 - d / max(p["width"], 1e-4), 0.0, 1.0) ** 2
    m = np.maximum(m, p["glow"] * np.clip(1.0 - d / 0.6, 0.0, 1.0) ** 3)
    fg = np.array(pal.hex_to_rgb(p["color"]), dtype=np.float32)
    bg = np.array(pal.hex_to_rgb(p["bg"]), dtype=np.float32)
    return np.clip(bg + fg * m[:, None], 0.0, 1.0) * p["intensity"]


@effect("piece_pulse", "Pulso por Peca", "Fluxo",
        "Cada peca pulsa do centro para as pontas, uma depois da outra.",
        [palette("palette", "Paleta", "cyberpunk"), SPEED(0.6),
         num("width", "Espessura", 0.2, 0.03, 0.8),
         PHASE(0.4), color("bg", "Fundo", "#03060c"), INTENSITY()])
def _piece_pulse(ctx, p, st):
    ph = (ctx.t * p["speed"] + ctx.piece_id * p["phase"]) % 1.0
    d = np.abs(np.abs(ctx.piece01 - 0.5) * 2.0 - ph)
    m = np.clip(1.0 - d / max(p["width"], 1e-4), 0.0, 1.0) ** 2
    col = pal.sample(p["palette"], ctx.piece_id + ctx.t * 0.05)
    bg = np.array(pal.hex_to_rgb(p["bg"]), dtype=np.float32)
    return np.clip(bg + col * m[:, None], 0.0, 1.0) * p["intensity"]


@effect("cascade", "Cascata", "Fluxo",
        "As pecas acendem em sequencia, uma apos a outra, e apagam junto.",
        [palette("palette", "Paleta", "sunset"), SPEED(0.5),
         num("hold", "Duracao acesa", 0.35, 0.05, 1.0),
         color("bg", "Fundo", "#03060c"),
         boolean("along", "Correr dentro da peca tambem", True), INTENSITY()])
def _cascade(ctx, p, st):
    ph = (ctx.t * p["speed"] - ctx.piece_id) % 1.0
    lit = np.clip(1.0 - ph / max(p["hold"], 1e-4), 0.0, 1.0)
    if p["along"]:
        lit = lit * np.clip(1.2 - np.abs(ctx.piece01 - (1.0 - ph / max(p["hold"], 1e-4))), 0.0, 1.0)
    col = pal.sample(p["palette"], ctx.piece_id + ctx.t * 0.08)
    bg = np.array(pal.hex_to_rgb(p["bg"]), dtype=np.float32)
    return np.clip(bg + col * lit[:, None], 0.0, 1.0) * p["intensity"]


@effect("snake", "Cobra", "Fluxo",
        "Um corpo de luz percorre TODAS as pecas em sequencia, como se fossem "
        "uma fita so ligada em serie.",
        [palette("palette", "Paleta", "toxic"), SPEED(0.3),
         num("length", "Comprimento", 0.25, 0.02, 1.0),
         color("bg", "Fundo", "#03060c"),
         boolean("reverse", "Inverter sentido", False), INTENSITY()])
def _snake(ctx, p, st):
    d = -1.0 if p["reverse"] else 1.0
    u = _chain(ctx)
    head = (ctx.t * p["speed"] * d) % 1.0
    delta = (u - head) % 1.0
    m = np.clip(1.0 - delta / max(p["length"], 1e-4), 0.0, 1.0) ** 1.5
    col = pal.sample(p["palette"], delta * 2.0 + ctx.t * 0.1)
    bg = np.array(pal.hex_to_rgb(p["bg"]), dtype=np.float32)
    return np.clip(bg + col * m[:, None], 0.0, 1.0) * p["intensity"]


@effect("chain_rainbow", "Arco-Iris Encadeado", "Fluxo",
        "A paleta percorre todas as pecas em serie, como uma fita unica dando "
        "a volta no gabinete.",
        [palette("palette", "Paleta", "rainbow"), SPEED(0.25),
         num("repeat", "Repeticoes", 1.0, 0.25, 8.0, 0.25), INTENSITY()])
def _chain_rainbow(ctx, p, st):
    return pal.sample(p["palette"],
                      _chain(ctx) * p["repeat"] - ctx.t * p["speed"]) * p["intensity"]


@effect("piece_breathe", "Respiracao Sequencial", "Fluxo",
        "Cada peca respira com um atraso em relacao a anterior -- calmo, mas "
        "com movimento perceptivel.",
        [palette("palette", "Paleta", "ice"), SPEED(0.3), PHASE(0.5),
         num("floor", "Brilho minimo", 0.06, 0.0, 1.0),
         boolean("per_piece_color", "Cor propria por peca", True), INTENSITY()])
def _piece_breathe(ctx, p, st):
    b = np.sin((ctx.t * p["speed"] + ctx.piece_id * p["phase"]) * np.pi) ** 2
    b = p["floor"] + (1.0 - p["floor"]) * b
    tone = ctx.piece_id if p["per_piece_color"] else np.float32(ctx.t * 0.05)
    return pal.sample(p["palette"], tone + ctx.t * 0.03) * b[:, None] * p["intensity"]


@effect("split_run", "Corrida Dividida", "Fluxo",
        "Duas frentes saem do meio de cada peca para as pontas.",
        [palette("palette", "Paleta", "magma"), SPEED(0.5),
         num("width", "Espessura", 0.18, 0.03, 0.8), PHASE(0.2),
         color("bg", "Fundo", "#03060c"), INTENSITY()])
def _split_run(ctx, p, st):
    ph = (ctx.t * p["speed"] + ctx.piece_id * p["phase"]) % 1.0
    d = np.abs(np.abs(ctx.piece01 - 0.5) * 2.0 - ph)
    m = np.clip(1.0 - d / max(p["width"], 1e-4), 0.0, 1.0) ** 2
    col = pal.sample(p["palette"], ph)
    bg = np.array(pal.hex_to_rgb(p["bg"]), dtype=np.float32)
    return np.clip(bg + col * m[:, None], 0.0, 1.0) * p["intensity"]


@effect("piece_chase", "Chase por Peca", "Fluxo",
        "Blocos de cores custom correndo dentro de cada peca.",
        [colors("colors", "Cores", ["#ff0040", "#000000", "#00d4ff", "#000000"]),
         SPEED(0.5), integer("blocks", "Blocos por peca", 4, 1, 24),
         PHASE(0.0), boolean("reverse", "Inverter sentido", False), INTENSITY()])
def _piece_chase(ctx, p, st):
    cols = np.array([pal.hex_to_rgb(c) for c in p["colors"]], dtype=np.float32)
    if len(cols) == 0:
        return ctx.zeros()
    d = -1.0 if p["reverse"] else 1.0
    u = ctx.piece01 * p["blocks"] + ctx.piece_id * p["phase"] * p["blocks"]
    idx = np.floor(u - ctx.t * p["speed"] * p["blocks"] * d).astype(np.int64)
    return cols[idx % len(cols)] * p["intensity"]


@effect("comet_piece", "Cometa por Peca", "Fluxo",
        "Um cometa por peca, todos girando juntos ou defasados.",
        [palette("palette", "Paleta", "neon"), SPEED(0.55),
         num("tail", "Rastro", 0.45, 0.05, 1.0), PHASE(0.33),
         num("floor", "Brilho de fundo", 0.04, 0.0, 0.5), INTENSITY()])
def _comet_piece(ctx, p, st):
    ph = (ctx.t * p["speed"] + ctx.piece_id * p["phase"]) % 1.0
    delta = (ctx.piece01 - ph) % 1.0
    m = np.clip(1.0 - delta / max(p["tail"], 1e-4), 0.0, 1.0) ** 2
    m = np.maximum(m, p["floor"])
    col = pal.sample(p["palette"], delta + ctx.piece_id * 0.2 + ctx.t * 0.05)
    return col * m[:, None] * p["intensity"]
