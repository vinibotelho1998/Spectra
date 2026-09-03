"""Efeitos de base: cor chapada, respiracao, arco-iris e alternancia.

Sao os que qualquer software de RGB faz. Estao aqui para servirem de
fundo nas cenas de varias camadas e como ponto de partida de ajuste.
"""

from __future__ import annotations

import numpy as np

from ..engine import palette as pal
from ..engine.noise import value_noise3
from .base import (ANGLE, INTENSITY, SOURCE_AXIS, SPEED, axis_values, boolean,
                   choice, color, colors, effect, integer, num, palette)


@effect("static", "Cor Solida", "Basicos",
        "Uma cor fixa em todos os LEDs.",
        [color("color", "Cor", "#ff2d55"), INTENSITY()])
def _static(ctx, p, st):
    c = np.array(pal.hex_to_rgb(p["color"]), dtype=np.float32) * p["intensity"]
    return np.tile(c, (ctx.n, 1))


@effect("gradient", "Gradiente", "Basicos",
        "Paleta esticada ao longo de um eixo do gabinete.",
        [palette(), SOURCE_AXIS(), ANGLE(), num("offset", "Deslocamento", 0.0, 0.0, 1.0),
         num("repeat", "Repeticoes", 1.0, 0.25, 8.0, 0.25, "x"), INTENSITY()])
def _gradient(ctx, p, st):
    u = ctx.rotated(p["angle"]) if p["axis"] == "x" and p["angle"] else axis_values(ctx, p)
    t = u * p["repeat"] + p["offset"]
    return pal.sample(p["palette"], t) * p["intensity"]


@effect("breathing", "Respiracao", "Basicos",
        "Brilho subindo e descendo suavemente.",
        [color("color", "Cor", "#00d4ff"), SPEED(0.4),
         num("floor", "Brilho minimo", 0.02, 0.0, 1.0), INTENSITY()])
def _breathing(ctx, p, st):
    b = np.sin(ctx.t * p["speed"] * np.pi) ** 2
    b = p["floor"] + (1.0 - p["floor"]) * b
    c = np.array(pal.hex_to_rgb(p["color"]), dtype=np.float32)
    return np.tile(c * b * p["intensity"], (ctx.n, 1))


@effect("color_cycle", "Ciclo de Cor", "Basicos",
        "Todos os LEDs juntos percorrendo a paleta.",
        [palette(), SPEED(0.2), INTENSITY()])
def _color_cycle(ctx, p, st):
    c = pal.sample(p["palette"], np.float32(ctx.t * p["speed"]))
    return np.tile(c, (ctx.n, 1)) * p["intensity"]


@effect("strobe", "Strobo", "Basicos",
        "Piscada dura, com controle de duty cycle.",
        [color("color", "Cor", "#ffffff"), num("hz", "Frequencia", 8.0, 0.5, 30.0, 0.5, "Hz"),
         num("duty", "Duty", 0.15, 0.02, 0.98), INTENSITY()])
def _strobe(ctx, p, st):
    on = (ctx.t * p["hz"]) % 1.0 < p["duty"]
    c = np.array(pal.hex_to_rgb(p["color"]), dtype=np.float32) * (1.0 if on else 0.0)
    return np.tile(c * p["intensity"], (ctx.n, 1))


@effect("random_leds", "Aleatorio", "Basicos",
        "Cada LED sorteia uma cor da paleta e troca no ritmo escolhido.",
        [palette(), num("hz", "Trocas por segundo", 4.0, 0.2, 30.0, 0.2, "Hz"),
         num("fade", "Suavizacao", 0.6, 0.0, 0.99), INTENSITY()])
def _random_leds(ctx, p, st):
    step = int(ctx.t * p["hz"])
    if st.get("_step") != step or st.get("_n") != ctx.n:
        st["_step"] = step
        st["_n"] = ctx.n
        st["target"] = pal.sample(p["palette"], ctx.rng.random(ctx.n).astype(np.float32))
    cur = st.get("cur")
    if cur is None or len(cur) != ctx.n:
        cur = np.zeros((ctx.n, 3), dtype=np.float32)
    k = 1.0 - p["fade"]
    cur = cur + (st["target"] - cur) * k
    st["cur"] = cur
    return cur * p["intensity"]


@effect("chase", "Chase", "Basicos",
        "Blocos de cor correndo ao longo dos LEDs, tipo marquise de teatro.",
        [colors("colors", "Cores", ["#ff0040", "#000000", "#00d4ff", "#000000"]),
         SPEED(1.0), integer("width", "Largura do bloco", 3, 1, 40, 1, "leds"),
         SOURCE_AXIS("strip"), INTENSITY()])
def _chase(ctx, p, st):
    cols = np.array([pal.hex_to_rgb(c) for c in p["colors"]], dtype=np.float32)
    if len(cols) == 0:
        return ctx.zeros()
    u = axis_values(ctx, p)
    span = max(ctx.n, 1) / max(p["width"], 1)
    idx = np.floor(u * span - ctx.t * p["speed"] * 4.0).astype(np.int64)
    return cols[idx % len(cols)] * p["intensity"]


@effect("wipe", "Wipe", "Basicos",
        "Uma cor preenche o gabinete progressivamente e recomeca.",
        [color("color", "Cor", "#7cff00"), color("bg", "Fundo", "#000000"),
         SPEED(0.4), SOURCE_AXIS(), boolean("bounce", "Vai e volta", True),
         num("soft", "Borda suave", 0.05, 0.0, 0.5), INTENSITY()])
def _wipe(ctx, p, st):
    ph = (ctx.t * p["speed"]) % 1.0
    if p["bounce"]:
        ph = (ctx.t * p["speed"]) % 2.0
        ph = ph if ph <= 1.0 else 2.0 - ph
    u = axis_values(ctx, p)
    soft = max(p["soft"], 1e-4)
    m = np.clip((ph - u) / soft + 0.5, 0.0, 1.0)[:, None]
    fg = np.array(pal.hex_to_rgb(p["color"]), dtype=np.float32)
    bg = np.array(pal.hex_to_rgb(p["bg"]), dtype=np.float32)
    return (bg * (1 - m) + fg * m) * p["intensity"]


@effect("police", "Viatura", "Basicos",
        "Alternancia vermelho/azul das duas metades do canvas.",
        [num("hz", "Frequencia", 2.5, 0.2, 12.0, 0.1, "Hz"),
         choice("style", "Estilo", "split",
                [("split", "Metades alternadas"), ("flash", "Flash duplo")]),
         INTENSITY()])
def _police(ctx, p, st):
    ph = (ctx.t * p["hz"]) % 1.0
    red = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    blue = np.array([0.0, 0.15, 1.0], dtype=np.float32)
    out = np.zeros((ctx.n, 3), dtype=np.float32)
    if p["style"] == "split":
        left = ctx.x < 0.5
        a, b = (red, blue) if ph < 0.5 else (blue, red)
        out[left] = a
        out[~left] = b
    else:
        sub = (ph * 4.0) % 1.0 < 0.5
        c = red if ph < 0.5 else blue
        out[:] = c * (1.0 if sub else 0.0)
    return out * p["intensity"]


@effect("candle", "Vela", "Basicos",
        "Tremulacao quente e irregular, cada LED com seu proprio ritmo.",
        [color("color", "Cor", "#ff8a1e"), SPEED(1.0),
         num("depth", "Tremor", 0.55, 0.0, 1.0), INTENSITY()])
def _candle(ctx, p, st):
    seed = np.arange(ctx.n, dtype=np.float32) * 13.7
    f = value_noise3(seed, seed * 0.37, np.float32(ctx.t * p["speed"] * 3.0))
    b = 1.0 - p["depth"] * (1.0 - f)
    c = np.array(pal.hex_to_rgb(p["color"]), dtype=np.float32)
    return (c[None, :] * b[:, None]) * p["intensity"]


@effect("alternating", "Alternado", "Basicos",
        "Cores intercaladas em grupos fixos, com opcao de rolar.",
        [colors("colors", "Cores", ["#ff00aa", "#00ffcc"]),
         integer("group", "Tamanho do grupo", 2, 1, 32, 1, "leds"),
         SPEED(0.0), INTENSITY()])
def _alternating(ctx, p, st):
    cols = np.array([pal.hex_to_rgb(c) for c in p["colors"]], dtype=np.float32)
    if len(cols) == 0:
        return ctx.zeros()
    i = np.arange(ctx.n) + int(ctx.t * p["speed"] * 10.0)
    return cols[(i // max(p["group"], 1)) % len(cols)] * p["intensity"]


@effect("blackout", "Apagado", "Basicos",
        "Zera tudo. Util como camada base ou para desligar rapido.", [])
def _blackout(ctx, p, st):
    return ctx.zeros()
