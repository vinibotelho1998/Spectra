from __future__ import annotations

import numpy as np

from ..engine import palette as pal
from ..engine.noise import turbulence3
from .base import (ANGLE, INTENSITY, SOURCE_AXIS, SPEED, axis_values, boolean,
                   choice, color, effect, integer, num, palette)


@effect("audio_vu", "VU Meter", "Audio",
        "O volume preenche o gabinete como uma barra.",
        [palette("palette", "Paleta", "thermal"), SOURCE_AXIS(),
         num("gain", "Ganho", 1.0, 0.1, 6.0, 0.05, "x"),
         num("attack", "Ataque", 0.6, 0.02, 1.0),
         num("release", "Queda", 0.12, 0.01, 1.0),
         boolean("mirror", "Espelhado", False),
         color("bg", "Fundo", "#000000"), INTENSITY()],
        needs=("audio",))
def _audio_vu(ctx, p, st):
    target = min(1.0, ctx.audio.level * p["gain"])
    cur = st.get("lvl", 0.0)
    k = p["attack"] if target > cur else p["release"]
    cur = cur + (target - cur) * k
    st["lvl"] = cur

    u = axis_values(ctx, p)
    if p["mirror"]:
        u = np.abs(u - 0.5) * 2.0
    filled = u <= cur
    out = np.tile(np.array(pal.hex_to_rgb(p["bg"]), dtype=np.float32), (ctx.n, 1))
    if filled.any():
        out[filled] = pal.sample_clamped(p["palette"], u[filled])
    return out * p["intensity"]


@effect("audio_spectrum", "Espectro", "Audio",
        "Cada regiao do gabinete responde a uma faixa de frequencia.",
        [palette("palette", "Paleta", "turbo"), SOURCE_AXIS(),
         num("gain", "Ganho", 1.4, 0.1, 8.0, 0.05, "x"),
         num("smooth", "Suavizacao", 0.35, 0.0, 0.95),
         boolean("mirror", "Espelhado", True),
         boolean("color_by_band", "Cor pela banda", True), INTENSITY()],
        needs=("audio",))
def _audio_spectrum(ctx, p, st):
    u = axis_values(ctx, p)
    if p["mirror"]:
        u = np.abs(u - 0.5) * 2.0
    mag = np.clip(ctx.audio.band_at(u) * p["gain"], 0.0, 1.0)
    prev = st.get("mag")
    if prev is not None and len(prev) == len(mag):
        mag = prev * p["smooth"] + mag * (1.0 - p["smooth"])
    st["mag"] = mag
    tone = u if p["color_by_band"] else mag
    return pal.sample_clamped(p["palette"], tone) * mag[:, None] * p["intensity"]


@effect("audio_bass_pulse", "Pulso de Grave", "Audio",
        "O gabinete inteiro pulsa no bumbo. Decaimento configuravel.",
        [color("color", "Cor", "#ff0055"), color("bg", "Fundo", "#050014"),
         num("gain", "Ganho", 1.6, 0.1, 8.0, 0.05, "x"),
         num("decay", "Decaimento", 6.0, 0.5, 30.0, 0.5, "/s"),
         num("threshold", "Limiar", 0.25, 0.0, 1.0),
         boolean("from_center", "Expandir do centro", True), INTENSITY()],
        needs=("audio",))
def _audio_bass_pulse(ctx, p, st):
    lvl = float(st.get("lvl", 0.0)) * float(np.exp(-p["decay"] * ctx.dt))
    b = ctx.audio.bass * p["gain"]
    if b > p["threshold"]:
        lvl = max(lvl, min(1.0, b))
    st["lvl"] = lvl
    fg = np.array(pal.hex_to_rgb(p["color"]), dtype=np.float32)
    bg = np.array(pal.hex_to_rgb(p["bg"]), dtype=np.float32)
    if p["from_center"]:
        m = np.clip(1.0 - np.abs(ctx.radius / 1.42 - (1.0 - lvl)) * 4.0, 0.0, 1.0) * lvl
        m = np.maximum(m, np.clip(lvl * 1.4 - ctx.radius / 1.42, 0.0, 1.0))[:, None]
    else:
        m = np.full((ctx.n, 1), lvl, dtype=np.float32)
    return (bg * (1 - m) + fg * m) * p["intensity"]


@effect("audio_scope", "Osciloscopio", "Audio",
        "A forma de onda desenhada como uma linha atravessando o canvas.",
        [palette("palette", "Paleta", "neon"),
         num("gain", "Ganho", 1.0, 0.1, 6.0, 0.05, "x"),
         num("thickness", "Espessura", 0.12, 0.02, 0.6),
         ANGLE(0.0), INTENSITY()],
        needs=("audio",))
def _audio_scope(ctx, p, st):
    wf = ctx.audio.waveform
    a = np.radians(p["angle"], dtype=np.float32)
    u = ctx.x * np.cos(a) + ctx.y * np.sin(a)
    v = -ctx.x * np.sin(a) + ctx.y * np.cos(a)
    idx = np.clip(u, 0.0, 1.0) * (len(wf) - 1)
    i0 = np.floor(idx).astype(np.int32)
    i1 = np.minimum(i0 + 1, len(wf) - 1)
    f = idx - i0
    amp = (wf[i0] * (1 - f) + wf[i1] * f) * p["gain"]
    d = np.abs(v - (0.5 + amp * 0.45))
    m = np.clip(1.0 - d / max(p["thickness"], 1e-4), 0.0, 1.0) ** 2
    return pal.sample(p["palette"], u + ctx.t * 0.1) * m[:, None] * p["intensity"]


@effect("audio_fire", "Fogo Sonoro", "Audio",
        "Fogo cuja altura e voracidade sao comandadas pelo grave.",
        [palette("palette", "Paleta", "fire"), num("gain", "Ganho", 1.8, 0.1, 8.0, 0.05, "x"),
         num("scale", "Escala", 3.5, 0.5, 15.0, 0.05, "x"),
         num("base", "Altura minima", 0.25, 0.0, 1.0),
         num("smooth", "Suavizacao", 0.6, 0.0, 0.95), INTENSITY()],
        needs=("audio",))
def _audio_fire(ctx, p, st):
    drive = min(1.0, (ctx.audio.bass * 0.7 + ctx.audio.level * 0.3) * p["gain"])
    cur = st.get("drive", 0.0) * p["smooth"] + drive * (1.0 - p["smooth"])
    st["drive"] = cur
    height = p["base"] + (1.0 - p["base"]) * cur
    s = p["scale"]
    n = turbulence3(ctx.x * s, ctx.y * s * 1.5 - ctx.t * 2.5,
                    np.float32(ctx.t * 0.4), octaves=4)
    t = np.clip((ctx.y - (1.0 - height)) / max(height, 1e-4), 0.0, 1.0)
    heat = np.clip(t * (0.4 + 1.0 * n) * (0.5 + cur), 0.0, 1.0)
    return pal.sample_clamped(p["palette"], heat) * p["intensity"]


@effect("audio_ripple", "Ondas na Batida", "Audio",
        "Cada batida solta um anel que se expande pelo gabinete.",
        [palette("palette", "Paleta", "cyberpunk"),
         num("threshold", "Limiar da batida", 0.5, 0.05, 1.0),
         SPEED(0.8, 0.1, 4.0), num("width", "Espessura", 0.12, 0.02, 0.5),
         integer("max", "Aneis simultaneos", 6, 1, 20),
         num("fade", "Duracao", 1.6, 0.2, 6.0, 0.05, "s"), INTENSITY()],
        needs=("audio",))
def _audio_ripple(ctx, p, st):
    k = int(p["max"])
    if st.get("_k") != k:
        st["_k"] = k
        st["age"] = np.full(k, 1e9, dtype=np.float32)
        st["cx"] = np.zeros(k, dtype=np.float32)
        st["cy"] = np.zeros(k, dtype=np.float32)
        st["hue"] = np.zeros(k, dtype=np.float32)
    st["age"] += ctx.dt
    if ctx.audio.beat > p["threshold"]:
        i = int(np.argmax(st["age"]))
        if st["age"][i] > 0.12:
            st["age"][i] = 0.0
            st["cx"][i] = ctx.rng.random()
            st["cy"][i] = ctx.rng.random()
            st["hue"][i] = ctx.rng.random()
    out = np.zeros((ctx.n, 3), dtype=np.float32)
    for i in range(k):
        age = st["age"][i]
        if age > p["fade"]:
            continue
        r = age * p["speed"]
        d = np.sqrt((ctx.x - st["cx"][i]) ** 2 + (ctx.y - st["cy"][i]) ** 2)
        m = np.clip(1.0 - np.abs(d - r) / max(p["width"], 1e-4), 0.0, 1.0) ** 2
        m = m * (1.0 - age / p["fade"])
        out += pal.sample(p["palette"], st["hue"][i]) * m[:, None]
    return np.clip(out, 0.0, 1.0) * p["intensity"]


@effect("audio_hue", "Cor pelo Timbre", "Audio",
        "O centroide espectral vira matiz e o volume vira brilho: som grave "
        "puxa para um lado da paleta, agudo para o outro.",
        [palette("palette", "Paleta", "rainbow"),
         num("gain", "Ganho", 1.2, 0.1, 6.0, 0.05, "x"),
         num("smooth", "Suavizacao", 0.85, 0.0, 0.98),
         num("spread", "Espalhamento", 0.25, 0.0, 1.0),
         num("floor", "Brilho minimo", 0.05, 0.0, 1.0), INTENSITY()],
        needs=("audio",))
def _audio_hue(ctx, p, st):
    h = st.get("h", 0.5) * p["smooth"] + ctx.audio.centroid * (1.0 - p["smooth"])
    v = st.get("v", 0.0) * p["smooth"] + min(1.0, ctx.audio.level * p["gain"]) * (1.0 - p["smooth"])
    st["h"], st["v"] = h, v
    tone = h + ctx.x * p["spread"]
    b = p["floor"] + (1.0 - p["floor"]) * v
    return pal.sample(p["palette"], tone) * b * p["intensity"]


@effect("audio_sparkle", "Faiscas na Batida", "Audio",
        "Batidas espalham faiscas; quanto mais forte, mais faiscas.",
        [palette("palette", "Paleta", "candy"),
         num("gain", "Ganho", 1.0, 0.1, 6.0, 0.05, "x"),
         num("decay", "Decaimento", 4.0, 0.5, 20.0, 0.5, "/s"),
         num("density", "Densidade", 0.35, 0.02, 1.0), INTENSITY()],
        needs=("audio",))
def _audio_sparkle(ctx, p, st):
    lvl = st.get("lvl")
    if lvl is None or len(lvl) != ctx.n:
        lvl = np.zeros(ctx.n, dtype=np.float32)
        st["hue"] = np.zeros(ctx.n, dtype=np.float32)
    lvl *= float(np.exp(-p["decay"] * ctx.dt))
    drive = ctx.audio.beat * p["gain"]
    if drive > 0.2:
        born = ctx.rng.random(ctx.n) < (p["density"] * drive)
        if born.any():
            lvl[born] = np.minimum(1.0, drive)
            st["hue"][born] = ctx.rng.random(int(born.sum())).astype(np.float32)
    st["lvl"] = lvl
    return pal.sample(p["palette"], st["hue"]) * lvl[:, None] * p["intensity"]


@effect("temp_gradient", "Cor por Temperatura", "Sensores",
        "A cor sai da paleta conforme a temperatura escolhida: frio -> quente.",
        [palette("palette", "Paleta", "thermal"),
         choice("sensor", "Sensor", "cpu_temp",
                [("cpu_temp", "Temp. CPU"), ("gpu_temp", "Temp. GPU"),
                 ("cpu_load", "Uso CPU"), ("gpu_load", "Uso GPU"),
                 ("ram_load", "Uso RAM")]),
         num("lo", "Valor minimo", 35.0, 0.0, 120.0, 1.0),
         num("hi", "Valor maximo", 85.0, 0.0, 120.0, 1.0),
         num("smooth", "Suavizacao", 0.9, 0.0, 0.99),
         num("spread", "Espalhamento", 0.0, 0.0, 1.0), INTENSITY()],
        needs=("sensors",))
def _temp_gradient(ctx, p, st):
    v = ctx.sensors.normalized(p["sensor"], p["lo"], p["hi"])
    cur = st.get("v", v) * p["smooth"] + v * (1.0 - p["smooth"])
    st["v"] = cur
    t = np.clip(cur + (ctx.x - 0.5) * p["spread"], 0.0, 1.0)
    return pal.sample_clamped(p["palette"], t) * p["intensity"]


@effect("load_bar", "Barra de Carga", "Sensores",
        "Preenche o gabinete proporcionalmente ao uso de CPU/GPU.",
        [palette("palette", "Paleta", "thermal"),
         choice("sensor", "Sensor", "cpu_load",
                [("cpu_load", "Uso CPU"), ("gpu_load", "Uso GPU"),
                 ("ram_load", "Uso RAM"), ("cpu_temp", "Temp. CPU"),
                 ("gpu_temp", "Temp. GPU")]),
         num("lo", "Valor minimo", 0.0, 0.0, 120.0, 1.0),
         num("hi", "Valor maximo", 100.0, 1.0, 120.0, 1.0),
         SOURCE_AXIS("y"), num("smooth", "Suavizacao", 0.85, 0.0, 0.99),
         color("bg", "Fundo", "#04070d"), INTENSITY()],
        needs=("sensors",))
def _load_bar(ctx, p, st):
    v = ctx.sensors.normalized(p["sensor"], p["lo"], p["hi"])
    cur = st.get("v", v) * p["smooth"] + v * (1.0 - p["smooth"])
    st["v"] = cur
    u = axis_values(ctx, p)
    if p["axis"] == "y":
        u = 1.0 - u
    out = np.tile(np.array(pal.hex_to_rgb(p["bg"]), dtype=np.float32), (ctx.n, 1))
    filled = u <= cur
    if filled.any():
        out[filled] = pal.sample_clamped(p["palette"], u[filled] / max(cur, 1e-4))
    return out * p["intensity"]


@effect("thermal_alarm", "Alarme Termico", "Sensores",
        "Fica calmo abaixo do limite e pulsa forte quando passa dele.",
        [color("ok", "Cor normal", "#00c2ff"), color("alarm", "Cor de alarme", "#ff1100"),
         choice("sensor", "Sensor", "cpu_temp",
                [("cpu_temp", "Temp. CPU"), ("gpu_temp", "Temp. GPU"),
                 ("cpu_load", "Uso CPU"), ("gpu_load", "Uso GPU")]),
         num("threshold", "Limite", 80.0, 0.0, 120.0, 1.0),
         num("window", "Faixa de transicao", 10.0, 1.0, 40.0, 1.0),
         num("hz", "Pulsacao no alarme", 3.0, 0.2, 12.0, 0.1, "Hz"), INTENSITY()],
        needs=("sensors",))
def _thermal_alarm(ctx, p, st):
    v = ctx.sensors.value(p["sensor"])
    heat = np.clip((v - (p["threshold"] - p["window"])) / max(p["window"], 1e-4), 0.0, 1.0)
    puls = 0.5 + 0.5 * np.sin(ctx.t * p["hz"] * 6.283)
    mix = heat * (0.45 + 0.55 * puls)
    ok = np.array(pal.hex_to_rgb(p["ok"]), dtype=np.float32)
    al = np.array(pal.hex_to_rgb(p["alarm"]), dtype=np.float32)
    c = ok * (1 - mix) + al * mix
    return np.tile(c, (ctx.n, 1)) * p["intensity"]


@effect("dual_sensor", "CPU vs GPU", "Sensores",
        "Divide o canvas: um lado mostra a CPU, o outro a GPU.",
        [palette("palette", "Paleta", "thermal"),
         choice("split", "Divisao", "x", [("x", "Esquerda/Direita"), ("y", "Cima/Baixo")]),
         num("lo", "Temp. minima", 35.0, 0.0, 120.0, 1.0),
         num("hi", "Temp. maxima", 85.0, 0.0, 120.0, 1.0),
         num("blend", "Suavidade da divisa", 0.08, 0.0, 0.5), INTENSITY()],
        needs=("sensors",))
def _dual_sensor(ctx, p, st):
    a = ctx.sensors.normalized("cpu_temp", p["lo"], p["hi"])
    b = ctx.sensors.normalized("gpu_temp", p["lo"], p["hi"])
    u = ctx.x if p["split"] == "x" else ctx.y
    m = np.clip((u - 0.5) / max(p["blend"], 1e-4) * 0.5 + 0.5, 0.0, 1.0)
    t = a * (1 - m) + b * m
    return pal.sample_clamped(p["palette"], t) * p["intensity"]


@effect("ambilight", "Ambilight", "Tela",
        "Projeta a tela no gabinete: cada LED pega a cor da regiao da tela que "
        "corresponde a posicao fisica dele.",
        [num("saturation", "Saturacao", 1.35, 0.0, 3.0, 0.05, "x"),
         num("gamma", "Gamma", 0.85, 0.3, 2.5, 0.05),
         num("smooth", "Suavizacao", 0.35, 0.0, 0.95),
         num("zoom", "Zoom", 1.0, 0.3, 3.0, 0.05, "x"),
         boolean("edges", "So as bordas", False),
         num("edge_depth", "Profundidade da borda", 0.18, 0.02, 0.5),
         INTENSITY()],
        needs=("screen",))
def _ambilight(ctx, p, st):
    z = p["zoom"]
    x = np.clip((ctx.x - 0.5) / max(z, 1e-3) + 0.5, 0.0, 1.0)
    y = np.clip((ctx.y - 0.5) / max(z, 1e-3) + 0.5, 0.0, 1.0)
    if p["edges"]:
        d = p["edge_depth"]
        x = np.where(x < 0.5, x * d * 2.0, 1.0 - (1.0 - x) * d * 2.0)
        y = np.where(y < 0.5, y * d * 2.0, 1.0 - (1.0 - y) * d * 2.0)
    c = ctx.screen.sample(x, y)

    if p["saturation"] != 1.0:
        h, s, v = pal.rgb_to_hsv(c)
        c = pal.hsv_to_rgb(h, np.clip(s * p["saturation"], 0.0, 1.0), v)
    if p["gamma"] != 1.0:
        c = np.power(np.clip(c, 0.0, 1.0), p["gamma"], dtype=np.float32)

    prev = st.get("prev")
    if prev is not None and prev.shape == c.shape and p["smooth"] > 0:
        c = prev * p["smooth"] + c * (1.0 - p["smooth"])
    st["prev"] = c
    return c * p["intensity"]


@effect("screen_average", "Cor Media da Tela", "Tela",
        "Uma cor so, tirada da media da tela. Bom para iluminacao de fundo.",
        [num("saturation", "Saturacao", 1.5, 0.0, 3.0, 0.05, "x"),
         num("smooth", "Suavizacao", 0.85, 0.0, 0.98),
         num("boost", "Realce", 1.2, 0.2, 4.0, 0.05, "x"),
         boolean("dominant", "Usar cor dominante", True), INTENSITY()],
        needs=("screen",))
def _screen_average(ctx, p, st):
    c = ctx.screen.dominant if p["dominant"] else ctx.screen.average
    c = np.asarray(c, dtype=np.float32).copy()
    h, s, v = pal.rgb_to_hsv(c[None, :])
    c = pal.hsv_to_rgb(h, np.clip(s * p["saturation"], 0, 1),
                       np.clip(v * p["boost"], 0, 1))[0]
    prev = st.get("prev")
    if prev is not None:
        c = prev * p["smooth"] + c * (1.0 - p["smooth"])
    st["prev"] = c
    return np.tile(c, (ctx.n, 1)) * p["intensity"]


@effect("screen_mood", "Clima da Tela", "Tela",
        "Extrai o tom dominante da tela e o espalha num gradiente vivo, em vez "
        "de copiar a imagem.",
        [SPEED(0.15), num("saturation", "Saturacao", 1.6, 0.0, 3.0, 0.05, "x"),
         num("spread", "Espalhamento", 0.25, 0.0, 1.0),
         num("smooth", "Suavizacao", 0.9, 0.0, 0.98), ANGLE(0.0), INTENSITY()],
        needs=("screen",))
def _screen_mood(ctx, p, st):
    c = np.asarray(ctx.screen.dominant, dtype=np.float32)
    h, s, v = pal.rgb_to_hsv(c[None, :])
    hh = float(st.get("h", float(h[0])) * p["smooth"] + float(h[0]) * (1 - p["smooth"]))
    vv = float(st.get("v", float(v[0])) * p["smooth"] + float(v[0]) * (1 - p["smooth"]))
    st["h"], st["v"] = hh, vv
    u = ctx.rotated(p["angle"])
    hue = hh + u * p["spread"] + ctx.t * p["speed"] * 0.1
    sat = np.clip(float(s[0]) * p["saturation"], 0.0, 1.0)
    return pal.hsv_to_rgb(hue, np.full(ctx.n, sat, dtype=np.float32),
                          np.full(ctx.n, max(vv, 0.05), dtype=np.float32)) * p["intensity"]
