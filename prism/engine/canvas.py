"""Mapa espacial dos LEDs do gabinete.

O motor do Prism trata iluminacao como imagem, nao como lista de canais.
Cada LED vira um ponto (x, y) no quadrado unitario e todo efeito e uma
funcao f(x, y, t) avaliada de uma vez em numpy. Isso e o que permite uma
onda atravessar o gabinete inteiro passando pelos fans, pelas fitas e
pela memoria como se fossem um so display.

Alem das coordenadas do gabinete, o canvas deriva coordenadas locais por
peca: `piece01` ao longo de cada peca, `piece_u` e `piece_v` para as
fitas de cabo que tem varias lanes lado a lado, e `piece_pos` inteiro
para os efeitos que precisam acender um LED exato sem borrar no vizinho.
"""

from __future__ import annotations

import hashlib
import math

import numpy as np


def device_key(dev) -> str:
    """Identidade estavel de um dispositivo, para casar com a configuracao salva.

    O indice que o OpenRGB da muda conforme a ordem de deteccao, entao a
    chave usa nome mais um hash curto do serial ou da porta. O serial vai
    picotado porque a configuracao e gravada em disco.
    """
    tail = dev.serial.strip() if dev.serial.strip() else dev.location
    if tail:
        tail = hashlib.sha1(tail.encode("utf-8", "replace")).hexdigest()[:8]
    return f"{dev.name}#{tail}" if tail else dev.name


def shape_point(n: int, g: dict) -> np.ndarray:
    """Empilha todos os LEDs num ponto so, para zona de LED unico."""
    x, y = float(g.get("x", 0.5)), float(g.get("y", 0.5))
    return np.tile(np.array([[x, y]], dtype=np.float32), (n, 1))


def shape_line(n: int, g: dict) -> np.ndarray:
    """Distribui os LEDs por igual num segmento de reta."""
    x1, y1 = float(g.get("x1", 0.1)), float(g.get("y1", 0.5))
    x2, y2 = float(g.get("x2", 0.9)), float(g.get("y2", 0.5))
    if n == 1:
        return np.array([[(x1 + x2) / 2, (y1 + y2) / 2]], dtype=np.float32)
    t = np.linspace(0.0, 1.0, n, dtype=np.float32)
    return np.stack([x1 + (x2 - x1) * t, y1 + (y2 - y1) * t], axis=-1).astype(np.float32)


def shape_ring(n: int, g: dict) -> np.ndarray:
    """Distribui os LEDs num arco, que e o formato de um fan.

    Quando o arco fecha os 360 graus, o ultimo ponto nao repete o primeiro.
    """
    cx, cy = float(g.get("cx", 0.5)), float(g.get("cy", 0.5))
    rad = float(g.get("radius", 0.12))
    a0 = math.radians(float(g.get("start_deg", 0.0)))
    a1 = math.radians(float(g.get("end_deg", 360.0)))
    if n == 1:
        return np.array([[cx, cy]], dtype=np.float32)
    full = abs((a1 - a0) - 2 * math.pi) < 1e-6
    ang = np.linspace(a0, a1, n, endpoint=not full, dtype=np.float32)
    return np.stack([cx + rad * np.cos(ang), cy + rad * np.sin(ang)],
                    axis=-1).astype(np.float32)


def shape_grid(n: int, g: dict) -> np.ndarray:
    """Distribui os LEDs numa matriz, preenchendo linha por linha."""
    x, y = float(g.get("x", 0.1)), float(g.get("y", 0.1))
    w, h = float(g.get("w", 0.8)), float(g.get("h", 0.3))
    cols = int(g.get("cols", 0)) or max(1, int(round(math.sqrt(max(n, 1)))))
    rows = int(g.get("rows", 0)) or max(1, math.ceil(n / cols))
    out = np.zeros((n, 2), dtype=np.float32)
    for i in range(n):
        r, c = divmod(i, cols)
        fx = c / max(cols - 1, 1)
        fy = r / max(rows - 1, 1)
        out[i] = (x + w * fx, y + h * fy)
    return out


def shape_serpentine(n: int, g: dict) -> np.ndarray:
    """Igual a matriz, mas invertendo o sentido das linhas impares.

    E como a fita costuma ser dobrada em painel: ela sobe, desce e volta,
    entao o indice do LED serpenteia em vez de voltar para a margem.
    """
    grid = shape_grid(n, g)
    cols = int(g.get("cols", 0)) or max(1, int(round(math.sqrt(max(n, 1)))))
    order = np.arange(n)
    rows_i, cols_i = np.divmod(order, cols)
    flipped = np.where(rows_i % 2 == 1, rows_i * cols + (cols - 1 - cols_i), order)
    return grid[np.clip(flipped, 0, n - 1)]


def _grid_of(g: dict, n: int):
    shape = g.get("shape")
    if shape == "cable":
        lanes = max(int(g.get("lanes", 12)), 1)
        return (lanes, max(1, int(round(n / lanes))), g.get("order", "lane"))
    if shape in ("grid", "serpentine"):
        cols = int(g.get("cols", 0)) or max(1, int(round(math.sqrt(max(n, 1)))))
        rows = int(g.get("rows", 0)) or max(1, math.ceil(n / cols))
        return (rows, cols, "along")
    return None


def shape_cable(n: int, g: dict) -> np.ndarray:
    """Distribui os LEDs numa fita larga de cabo, com varias lanes paralelas.

    A fita que cobre o cabo de forca tem varias fileiras lado a lado, e e a
    largura dela que da o efeito bonito. `lanes` diz quantas fileiras, e
    `order` diz se o indice do LED corre ao longo do cabo ou atravessando.
    """
    lanes = max(int(g.get("lanes", 12)), 1)
    x1, y1 = float(g.get("x1", 0.15)), float(g.get("y1", 0.40))
    x2, y2 = float(g.get("x2", 0.85)), float(g.get("y2", 0.40))
    largura = float(g.get("width", 0.16))
    per = max(1, int(round(n / lanes)))

    dx, dy = x2 - x1, y2 - y1
    comp = math.hypot(dx, dy) or 1.0
    ux, uy = dx / comp, dy / comp
    px, py = -uy, ux

    out = np.zeros((n, 2), dtype=np.float32)
    for i in range(n):
        if g.get("order") == "along":
            lane, pos = i % lanes, i // lanes
        else:
            lane, pos = i // per, i % per
        lane = min(lane, lanes - 1)
        fl = (lane / max(lanes - 1, 1)) - 0.5
        fp = pos / max(per - 1, 1)
        if g.get("serpentine") and lane % 2 == 1:
            fp = 1.0 - fp
        out[i] = (x1 + dx * fp + px * largura * fl,
                  y1 + dy * fp + py * largura * fl)
    return out


def shape_multi(n: int, g: dict) -> np.ndarray:
    """Monta uma zona a partir de varias pecas em sequencia.

    Serve para o header onde varios fans dividem o mesmo canal ARGB: cada
    peca vira uma unidade propria para os efeitos que trabalham por peca.
    O que sobrar de LED sem peca declarada vira uma linha no rodape.
    """
    parts = g.get("parts") or []
    out = []
    used = 0
    for p in parts:
        c = min(int(p.get("count", 0)), n - used)
        if c <= 0:
            continue
        fn = SHAPES.get(p.get("shape", "ring"), shape_ring)
        pts = fn(c, p)
        if p.get("reverse"):
            pts = pts[::-1].copy()
        out.append(pts)
        used += c
        if used >= n:
            break
    if used < n:
        out.append(shape_line(n - used, {"x1": 0.05, "y1": 0.98,
                                         "x2": 0.95, "y2": 0.98}))
    return (np.concatenate(out, axis=0).astype(np.float32) if out
            else np.zeros((n, 2), dtype=np.float32))


SHAPES = {
    "point": shape_point,
    "line": shape_line,
    "ring": shape_ring,
    "grid": shape_grid,
    "serpentine": shape_serpentine,
    "cable": shape_cable,
    "multi": shape_multi,
}


_AUTO_BANDS = {
    "Cooler":        (0.06, 0.50),
    "DRAM":          (0.20, 0.62),
    "Motherboard":   (0.42, 0.50),
    "GPU":           (0.60, 0.50),
    "Storage":       (0.74, 0.50),
    "LED Strip":     (0.50, 0.08),
    "Case":          (0.50, 0.92),
    "Keyboard":      (0.90, 0.35),
    "Mouse":         (0.90, 0.72),
    "Mousemat":      (0.96, 0.50),
    "Headset":       (0.84, 0.88),
    "Headset Stand": (0.84, 0.12),
}


def auto_placement(dev, zone, slot: int, zi: int = 0, zn: int = 1) -> dict:
    """Chuta um lugar no gabinete para uma zona ainda nao configurada.

    A posicao sai do tipo do dispositivo, e `zi` com `zn` espalham as zonas
    irmas em vez de empilhar todas no mesmo ponto. Sem esse espalhamento,
    os seis fans de um mesmo header cairiam sobre a mesma coordenada e todo
    efeito espacial viraria uma cor chapada.
    """
    band = _AUTO_BANDS.get(dev.type_name)
    y = band[0] if band else min(0.05 + 0.08 * slot, 0.95)
    xc = band[1] if band else 0.5

    off = 0.0 if zn <= 1 else (zi - (zn - 1) / 2.0) / max((zn - 1) / 2.0, 1e-6)

    if zone.leds_count <= 1:
        return {"shape": "point",
                "x": min(0.95, max(0.05, xc + off * 0.34)),
                "y": min(0.97, max(0.03, y))}

    if zone.matrix_width and zone.matrix_height:
        return {"shape": "grid", "x": max(0.02, xc - 0.4),
                "y": min(0.9, max(0.02, y + off * 0.12)),
                "w": 0.8, "h": 0.2, "cols": zone.matrix_width,
                "rows": zone.matrix_height}

    if zone.leds_count in (8, 12, 16, 18, 20, 24):
        radius = 0.15 if zn <= 1 else min(0.15, 0.40 / zn)
        return {"shape": "ring",
                "cx": min(1.0 - radius, max(radius, 0.5 + off * (0.5 - radius))),
                "cy": min(1.0 - radius, max(radius, y)),
                "radius": radius, "start_deg": -90.0, "end_deg": 270.0}

    yy = min(0.97, max(0.03, y + off * 0.16))
    return {"shape": "line", "x1": 0.04, "y1": yy, "x2": 0.96, "y2": yy}


class Canvas:
    """Posicao de cada LED de cada dispositivo, num quadro so.

    Concatena os dispositivos numa lista continua de LEDs e deriva dela os
    arrays que os efeitos consomem: `x` e `y` normalizados, `cx` e `cy`
    centrados em zero, `radius`, `theta` e `angle01` polares, e as
    coordenadas por peca.

    A geometria de cada zona vem da configuracao salva. Faltando, cai no
    `auto_placement`.
    """

    def __init__(self, devices, config: dict | None = None, enabled=None):
        self.config = config or {}
        self.devices = []
        self.slices = []
        self.zone_info = []
        self.pieces = []
        self.piece_kinds = []
        self.piece_grid = []
        chunks = []
        cursor = 0
        slot = 0

        for dev in devices:
            if dev.led_count == 0:
                continue
            key = device_key(dev)
            if enabled is not None and not enabled.get(key, True):
                continue
            dcfg = self.config.get(key, {})
            zcfg = dcfg.get("zones", {})
            dev_pos = []
            live = [z for z in dev.zones if z.leds_count > 0]
            for zi, zone in enumerate(live):
                g = zcfg.get(str(zone.index)) or auto_placement(
                    dev, zone, slot, zi, len(live))
                fn = SHAPES.get(g.get("shape", "line"), shape_line)
                pts = fn(zone.leds_count, g)
                if g.get("reverse"):
                    pts = pts[::-1].copy()

                zone_start = cursor + sum(len(p) for p in dev_pos)
                if g.get("shape") == "multi":
                    off = 0
                    for part in (g.get("parts") or []):
                        c = min(int(part.get("count", 0)), zone.leds_count - off)
                        if c <= 0:
                            continue
                        self.pieces.append((zone_start + off, c))
                        self.piece_kinds.append(part.get("kind"))
                        self.piece_grid.append(_grid_of(part, c))
                        off += c
                    if off < zone.leds_count:
                        self.pieces.append((zone_start + off, zone.leds_count - off))
                        self.piece_kinds.append(None)
                        self.piece_grid.append(None)
                else:
                    self.pieces.append((zone_start, zone.leds_count))
                    self.piece_kinds.append(
                        "fan" if g.get("shape") == "ring" else
                        ("strip" if g.get("shape") in ("line", "serpentine", "cable")
                         else None))
                    self.piece_grid.append(_grid_of(g, zone.leds_count))

                dev_pos.append(pts)
                self.zone_info.append({
                    "device_key": key, "device_index": dev.index,
                    "zone_index": zone.index, "zone_name": zone.name,
                    "count": zone.leds_count, "start": cursor + sum(len(p) for p in dev_pos[:-1]),
                    "geometry": g,
                })
                slot += 1
            if not dev_pos:
                continue
            merged = np.concatenate(dev_pos, axis=0)
            chunks.append(merged)
            self.slices.append((dev.index, cursor, len(merged)))
            self.devices.append(dev)
            cursor += len(merged)

        self.n = cursor
        if self.n == 0:
            self.pos = np.zeros((0, 2), dtype=np.float32)
        else:
            self.pos = np.concatenate(chunks, axis=0)

        self._derive()

    def _derive(self):
        self.x = np.ascontiguousarray(self.pos[:, 0]) if self.n else np.zeros(0, np.float32)
        self.y = np.ascontiguousarray(self.pos[:, 1]) if self.n else np.zeros(0, np.float32)
        self.cx = (self.x - 0.5) * 2.0
        self.cy = (self.y - 0.5) * 2.0
        self.radius = np.sqrt(self.cx ** 2 + self.cy ** 2).astype(np.float32)
        self.theta = np.arctan2(self.cy, self.cx).astype(np.float32)
        self.angle01 = ((self.theta / (2 * math.pi)) % 1.0).astype(np.float32)
        idx = np.zeros(self.n, dtype=np.float32)
        for _di, start, count in self.slices:
            if count > 1:
                idx[start:start + count] = np.linspace(0, 1, count, dtype=np.float32)
        self.strip01 = idx

        p01 = np.zeros(self.n, dtype=np.float32)
        pid = np.zeros(self.n, dtype=np.float32)
        pidx = np.zeros(self.n, dtype=np.int32)
        ppos = np.zeros(self.n, dtype=np.int32)
        plen = np.ones(self.n, dtype=np.int32)
        pstrip = np.zeros(self.n, dtype=bool)
        pfan = np.zeros(self.n, dtype=bool)
        pu = np.zeros(self.n, dtype=np.float32)
        pv = np.full(self.n, 0.5, dtype=np.float32)
        plane = np.zeros(self.n, dtype=np.int32)
        planes = np.ones(self.n, dtype=np.int32)
        npieces = max(len(self.pieces), 1)
        for k, (start, count) in enumerate(self.pieces):
            if count > 1:
                p01[start:start + count] = np.linspace(0, 1, count, dtype=np.float32)
            pid[start:start + count] = k / max(npieces - 1, 1)
            pidx[start:start + count] = k
            ppos[start:start + count] = np.arange(count, dtype=np.int32)
            plen[start:start + count] = count
            kind = self.piece_kinds[k] if k < len(self.piece_kinds) else None
            pstrip[start:start + count] = (kind == "strip")
            pfan[start:start + count] = (kind == "fan")
            grid = self.piece_grid[k] if k < len(self.piece_grid) else None
            idx = np.arange(count)
            if grid:
                lanes, per, ordem = grid
                if ordem == "along":
                    lane, pos = idx % lanes, idx // lanes
                else:
                    lane, pos = idx // max(per, 1), idx % max(per, 1)
                lane = np.minimum(lane, lanes - 1)
                pu[start:start + count] = pos / max(per - 1, 1)
                pv[start:start + count] = lane / max(lanes - 1, 1)
                plane[start:start + count] = lane
                planes[start:start + count] = lanes
            elif count == 1:
                # Peca de um LED nao tem comprimento, entao nao existe
                # coordenada local pra ela. Zerar todas, que era o que
                # acontecia, deixa o LED do mouse, o do chipset e qualquer
                # outro ponto isolado com a mesma fase: eles disparam juntos,
                # fora do compasso do resto, e o efeito vira pisca seco. A
                # posicao no gabinete e a melhor coordenada que sobra, e faz
                # a onda passar por eles na hora certa.
                p01[start] = self.x[start]
                pu[start] = self.x[start]
                pv[start] = self.y[start]
            else:
                pu[start:start + count] = idx / max(count - 1, 1)
        self.piece01 = p01
        self.piece_id = pid
        self.piece_index = pidx
        self.piece_count = len(self.pieces)
        self.piece_pos = ppos
        self.piece_len = plen
        self.is_strip = pstrip
        self.is_fan = pfan
        self.piece_u = pu
        self.piece_v = pv
        self.piece_lane = plane
        self.piece_lanes = planes

    def to_json(self) -> dict:
        """Descreve o mapa no formato que a interface desenha."""
        return {
            "led_count": self.n,
            "zones": self.zone_info,
            "positions": self.pos.tolist(),
            "devices": [
                {"index": d.index, "key": device_key(d), "name": d.name,
                 "type_name": d.type_name, "led_count": d.led_count,
                 "start": s, "count": c}
                for d, (_di, s, c) in zip(self.devices, self.slices)
            ],
        }
