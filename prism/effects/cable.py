"""Efeitos para as fitas largas que cobrem cabo, tratadas como matriz.

Essas fitas tem varias laminas paralelas ao longo do cabo, e e a largura
delas que rende. Aqui os efeitos usam `piece_u` e `piece_v`, as
coordenadas 2D da peca, para atravessar o cabo na diagonal, disputar
territorio entre as pontas e desenhar espectro de audio de verdade.
"""

from __future__ import annotations

import numpy as np

from ..engine import palette as pal
from .base import (INTENSITY, SCOPE, SPEED, apply_scope, boolean, color,
                   effect, integer, num, palette)


def LANE_PHASE(default=0.5):
    """Parametro que defasa o padrao entre as laminas da fita de cabo."""
    return num("lane_phase", "Defasagem entre laminas", default, -2.0, 2.0, 0.01)


@effect("cb_cross", "Cross Over", "Geometricos",
        "Dois feixes diagonais atravessando o cabo em sentidos opostos e se "
        "cruzando no meio. So faz sentido com laminas: e o efeito que mais "
        "mostra a largura da fita.",
        [color("a", "Cor A", "#ff2d55"), color("b", "Cor B", "#00d9ff"),
         SPEED(0.5), num("width", "Espessura", 0.18, 0.02, 0.8),
         num("slant", "Inclinacao", 1.0, -3.0, 3.0, 0.05),
         color("bg", "Fundo", "#000000"), SCOPE(), INTENSITY()])
def _cb_cross(ctx, p, st):
    ph = ctx.t * p["speed"]
    da = (ctx.piece_u + ctx.piece_v * p["slant"] - ph) % 1.0
    db = (ctx.piece_u - ctx.piece_v * p["slant"] + ph) % 1.0
    w = max(p["width"], 1e-4)
    ma = np.clip(1.0 - da / w, 0.0, 1.0) ** 2
    mb = np.clip(1.0 - db / w, 0.0, 1.0) ** 2
    ca = np.array(pal.hex_to_rgb(p["a"]), dtype=np.float32)
    cb = np.array(pal.hex_to_rgb(p["b"]), dtype=np.float32)
    bg = np.array(pal.hex_to_rgb(p["bg"]), dtype=np.float32)
    out = bg + ca * ma[:, None] + cb * mb[:, None]
    return apply_scope(ctx, np.clip(out, 0, 1), p) * p["intensity"]


@effect("cb_parallel", "Paralelo", "Geometricos",
        "As laminas acendem uma depois da outra, atravessando a largura do "
        "cabo. Cada lamina com sua cor.",
        [palette("palette", "Paleta", "rainbow"), SPEED(0.35),
         num("duty", "Laminas acesas", 0.3, 0.05, 1.0),
         boolean("along", "Correr no comprimento tambem", False),
         color("bg", "Fundo", "#000000"), SCOPE(), INTENSITY()])
def _cb_parallel(ctx, p, st):
    ph = (ctx.piece_v - ctx.t * p["speed"]) % 1.0
    m = (ph < p["duty"]).astype(np.float32)
    if p["along"]:
        m = m * (0.35 + 0.65 * ((ctx.piece_u - ctx.t * p["speed"] * 2) % 1.0))
    cols = pal.sample(p["palette"], ctx.piece_v + ctx.t * 0.08)
    bg = np.array(pal.hex_to_rgb(p["bg"]), dtype=np.float32)
    return apply_scope(ctx, np.clip(bg + cols * m[:, None], 0, 1), p) * p["intensity"]


@effect("cb_wave", "Onda no Cabo", "Geometricos",
        "Uma onda percorre o comprimento, com cada lamina defasada da "
        "anterior: a crista atravessa o cabo na diagonal.",
        [palette("palette", "Paleta", "ocean"), SPEED(0.4),
         num("freq", "Ondas", 1.5, 0.25, 8.0, 0.05),
         LANE_PHASE(0.5), SCOPE(), INTENSITY()])
def _cb_wave(ctx, p, st):
    t = (ctx.piece_u * p["freq"] + ctx.piece_v * p["lane_phase"]
         - ctx.t * p["speed"])
    return apply_scope(ctx, pal.sample(p["palette"], t), p) * p["intensity"]


@effect("cb_ripple", "Ondulacao no Cabo", "Geometricos",
        "Aneis se expandindo a partir de um ponto do cabo, atravessando "
        "laminas e comprimento ao mesmo tempo.",
        [palette("palette", "Paleta", "ice"), SPEED(0.5),
         num("cu", "Centro no comprimento", 0.5, 0.0, 1.0),
         num("cv", "Centro na largura", 0.5, 0.0, 1.0),
         num("freq", "Frequencia", 3.0, 0.5, 15.0, 0.1),
         num("aspect", "Proporcao", 3.0, 0.2, 10.0, 0.1),
         SCOPE(), INTENSITY()])
def _cb_ripple(ctx, p, st):
    du = (ctx.piece_u - p["cu"]) * p["aspect"]
    dv = ctx.piece_v - p["cv"]
    d = np.sqrt(du * du + dv * dv)
    return apply_scope(ctx, pal.sample(p["palette"],
                                       d * p["freq"] - ctx.t * p["speed"]),
                       p) * p["intensity"]


@effect("cb_bullets", "Projeteis", "Geometricos",
        "Cada lamina dispara um ponto que corre ate o fim e fica acumulado, "
        "ate a fita encher. Depois esvazia.",
        [palette("palette", "Paleta", "neon"), SPEED(0.9),
         num("stack_time", "Tempo de enchimento", 6.0, 1.0, 30.0, 0.5, "s"),
         num("size", "Tamanho", 0.1, 0.02, 0.5),
         LANE_PHASE(0.25), color("bg", "Fundo", "#000000"),
         SCOPE(), INTENSITY()])
def _cb_bullets(ctx, p, st):
    ciclo = (ctx.t / max(p["stack_time"], 0.1)) % 2.0
    nivel = ciclo if ciclo <= 1.0 else 2.0 - ciclo
    empilhado = ctx.piece_u >= (1.0 - nivel)

    ph = (ctx.t * p["speed"] + ctx.piece_v * p["lane_phase"]) % 1.0
    alvo = (1.0 - nivel) * ph
    d = np.abs(ctx.piece_u - alvo)
    bala = np.clip(1.0 - d / max(p["size"], 1e-4), 0.0, 1.0) ** 2
    bala = np.where(ctx.piece_u < (1.0 - nivel), bala, 0.0)

    m = np.maximum(empilhado.astype(np.float32), bala)
    cols = pal.sample(p["palette"], ctx.piece_v * 0.5 + ctx.t * 0.05)
    bg = np.array(pal.hex_to_rgb(p["bg"]), dtype=np.float32)
    return apply_scope(ctx, np.clip(bg + cols * m[:, None], 0, 1), p) * p["intensity"]


@effect("cb_drizzle", "Chuva no Cabo", "Geometricos",
        "Gotas caem por laminas diferentes em tempos diferentes, deixando "
        "boa parte do cabo escura.",
        [palette("palette", "Paleta", "ice"), SPEED(0.8),
         num("length", "Rastro", 0.25, 0.05, 1.0),
         num("density", "Densidade", 0.5, 0.05, 1.0),
         integer("drops", "Gotas por lamina", 1, 1, 4),
         boolean("up", "Subir", False), SCOPE(), INTENSITY()])
def _cb_drizzle(ctx, p, st):
    lanes = np.maximum(ctx.piece_lanes, 1)
    if st.get("_n") != ctx.n:
        st["_n"] = ctx.n
        st["off"] = ctx.rng.random(ctx.n).astype(np.float32)
        st["spd"] = (0.6 + ctx.rng.random(ctx.n).astype(np.float32) * 0.8)
        st["on"] = ctx.rng.random(ctx.n).astype(np.float32)

    u = 1.0 - ctx.piece_u if p["up"] else ctx.piece_u
    lvl = np.zeros(ctx.n, dtype=np.float32)
    for k in range(int(p["drops"])):
        ph = (ctx.t * p["speed"] * st["spd"] + st["off"] + k / p["drops"]) % 1.0
        d = (u - ph) % 1.0
        v = np.clip(1.0 - d / max(p["length"], 1e-4), 0.0, 1.0) ** 2
        lvl = np.maximum(lvl, v)
    lvl = np.where(st["on"] < p["density"], lvl, 0.0)
    cols = pal.sample(p["palette"], ctx.piece_v * 0.3 + ctx.t * 0.05)
    return apply_scope(ctx, cols * lvl[:, None], p) * p["intensity"]


@effect("cb_transfer", "Transferencia", "Geometricos",
        "A cor passa de uma lamina para a seguinte, como se escorresse pela "
        "largura do cabo.",
        [palette("palette", "Paleta", "sunset"), SPEED(0.3),
         num("spread", "Espalhamento", 1.0, 0.1, 4.0, 0.05),
         num("soft", "Suavidade", 0.35, 0.02, 1.0),
         SCOPE(), INTENSITY()])
def _cb_transfer(ctx, p, st):
    ph = (ctx.piece_v * p["spread"] - ctx.t * p["speed"]) % 1.0
    m = np.exp(-((ph - 0.5) / max(p["soft"], 1e-3)) ** 2)
    cols = pal.sample(p["palette"], ctx.piece_v * 0.4 + ctx.t * 0.06)
    return apply_scope(ctx, cols * m[:, None], p) * p["intensity"]


@effect("cb_contest", "Disputa", "Geometricos",
        "Duas frentes correm das pontas para o centro do cabo e recuam, "
        "disputando o territorio.",
        [color("a", "Cor A", "#ff0040"), color("b", "Cor B", "#00d4ff"),
         SPEED(0.35), num("edge", "Nitidez da divisa", 0.06, 0.0, 0.5),
         LANE_PHASE(0.2), SCOPE(), INTENSITY()])
def _cb_contest(ctx, p, st):
    ciclo = (ctx.t * p["speed"] + ctx.piece_v * p["lane_phase"]) % 2.0
    frente = np.where(ciclo <= 1.0, ciclo, 2.0 - ciclo)
    m = np.clip((ctx.piece_u - frente) / max(p["edge"], 1e-4) * 0.5 + 0.5, 0.0, 1.0)
    ca = np.array(pal.hex_to_rgb(p["a"]), dtype=np.float32)
    cb = np.array(pal.hex_to_rgb(p["b"]), dtype=np.float32)
    return apply_scope(ctx, ca * (1 - m[:, None]) + cb * m[:, None], p) * p["intensity"]


@effect("cb_lane_chase", "Lamina a Lamina", "Geometricos",
        "Uma lamina inteira acende por vez, correndo pela largura do cabo. "
        "Bem marcado, quase um contador.",
        [palette("palette", "Paleta", "cyberpunk"), SPEED(3.0),
         integer("lit", "Laminas acesas", 1, 1, 8),
         num("fade", "Rastro", 0.5, 0.0, 0.98),
         color("bg", "Fundo", "#000000"), SCOPE(), INTENSITY()])
def _cb_lane_chase(ctx, p, st):
    lanes = np.maximum(ctx.piece_lanes, 1)
    ativa = np.floor(ctx.t * p["speed"]).astype(np.int64)
    d = (ctx.piece_lane.astype(np.int64) - ativa) % lanes
    m = np.where(d < int(p["lit"]), 1.0, 0.0).astype(np.float32)
    if p["fade"] > 0:
        m = np.maximum(m, p["fade"] ** np.maximum(d - int(p["lit"]) + 1, 0))
        m = np.where(d < lanes // 2, m, 0.0)
    cols = pal.sample(p["palette"], ctx.piece_v + ctx.t * 0.05)
    bg = np.array(pal.hex_to_rgb(p["bg"]), dtype=np.float32)
    return apply_scope(ctx, np.clip(bg + cols * m[:, None], 0, 1), p) * p["intensity"]


@effect("cb_diagonal", "Diagonal", "Geometricos",
        "Faixas inclinadas deslizando pelo cabo. O angulo controla o quanto "
        "elas se inclinam entre laminas.",
        [palette("palette", "Paleta", "vaporwave"), SPEED(0.4),
         num("bands", "Faixas", 2.0, 0.25, 10.0, 0.25),
         num("slant", "Inclinacao", 1.0, -4.0, 4.0, 0.05),
         num("duty", "Largura acesa", 0.45, 0.05, 1.0),
         boolean("hard", "Borda dura", True), SCOPE(), INTENSITY()])
def _cb_diagonal(ctx, p, st):
    ph = ((ctx.piece_u + ctx.piece_v * p["slant"]) * p["bands"]
          - ctx.t * p["speed"]) % 1.0
    m = (ph < p["duty"]).astype(np.float32) if p["hard"] else \
        np.clip(1.0 - np.abs(ph - p["duty"] / 2) / max(p["duty"], 1e-4), 0, 1)
    cols = pal.sample(p["palette"], ph * 0.3 + ctx.t * 0.07)
    return apply_scope(ctx, cols * m[:, None], p) * p["intensity"]


@effect("cb_twinkle2d", "Cintilar 2D", "Geometricos",
        "LEDs individuais acendem espalhados pela matriz do cabo, sem padrao "
        "de linha. E o que mais 'trata cada LED individualmente'.",
        [palette("palette", "Paleta", "candy"),
         num("rate", "Nascimentos", 14.0, 0.5, 80.0, 0.5, "/s"),
         num("decay", "Decaimento", 2.5, 0.2, 12.0, 0.1, "/s"),
         num("density", "Densidade", 0.2, 0.01, 1.0),
         boolean("by_lane", "Cor por lamina", True),
         SCOPE(), INTENSITY()])
def _cb_twinkle2d(ctx, p, st):
    lvl = st.get("lvl")
    if lvl is None or len(lvl) != ctx.n:
        lvl = np.zeros(ctx.n, dtype=np.float32)
        st["hue"] = ctx.rng.random(ctx.n).astype(np.float32)
    lvl = lvl * float(np.exp(-p["decay"] * ctx.dt))
    born = ctx.rng.random(ctx.n) < (p["rate"] * ctx.dt * p["density"])
    if born.any():
        lvl[born] = 1.0
        st["hue"][born] = ctx.rng.random(int(born.sum())).astype(np.float32)
    st["lvl"] = lvl
    tone = ctx.piece_v if p["by_lane"] else st["hue"]
    cols = pal.sample(p["palette"], tone + ctx.t * 0.05)
    return apply_scope(ctx, cols * lvl[:, None], p) * p["intensity"]


@effect("cb_spiral", "Espiral no Cabo", "Geometricos",
        "A cor gira em torno do eixo do cabo enquanto avanca -- parece uma "
        "helice percorrendo a fita.",
        [palette("palette", "Paleta", "plasma"), SPEED(0.5),
         num("turns", "Voltas", 2.0, 0.25, 10.0, 0.25),
         num("duty", "Largura acesa", 0.4, 0.05, 1.0),
         SCOPE(), INTENSITY()])
def _cb_spiral(ctx, p, st):
    ph = (ctx.piece_v - ctx.piece_u * p["turns"] + ctx.t * p["speed"]) % 1.0
    m = np.clip(1.0 - ph / max(p["duty"], 1e-4), 0.0, 1.0) ** 1.5
    cols = pal.sample(p["palette"], ctx.piece_u * 0.5 + ctx.t * 0.06)
    return apply_scope(ctx, cols * m[:, None], p) * p["intensity"]


@effect("cb_spectrum2d", "Espectro no Cabo", "Geometricos",
        "Cada lamina do cabo e uma faixa de frequencia, e a altura acesa "
        "dentro dela mostra a intensidade. Um analisador de verdade.",
        [palette("palette", "Paleta", "turbo"),
         num("gain", "Ganho", 1.5, 0.1, 8.0, 0.05, "x"),
         num("smooth", "Suavizacao", 0.4, 0.0, 0.95),
         boolean("mirror", "Espelhado", False),
         color("peak", "Cor do topo", "#ffffff"),
         SCOPE(), INTENSITY()],
        needs=("audio",))
def _cb_spectrum2d(ctx, p, st):
    v = ctx.piece_v
    if p["mirror"]:
        v = np.abs(v - 0.5) * 2.0
    mag = np.clip(ctx.audio.band_at(v) * p["gain"], 0.0, 1.0)
    prev = st.get("mag")
    if prev is not None and len(prev) == len(mag):
        mag = prev * p["smooth"] + mag * (1.0 - p["smooth"])
    st["mag"] = mag
    lit = ctx.piece_u <= mag
    topo = np.abs(ctx.piece_u - mag) < 0.08
    out = np.zeros((ctx.n, 3), dtype=np.float32)
    cols = pal.sample_clamped(p["palette"], v)
    out[lit] = cols[lit]
    out[topo & lit] = np.array(pal.hex_to_rgb(p["peak"]), dtype=np.float32)
    return apply_scope(ctx, out, p) * p["intensity"]
