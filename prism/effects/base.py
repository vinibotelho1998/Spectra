from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

EFFECTS: dict[str, "EffectDef"] = {}
CATEGORY_ORDER = [
    "Basicos", "Fluxo", "Geometricos", "Pixel", "Ondas", "Ruido", "Particulas", "Simulacao",
    "Audio", "Sensores", "Tela",
]


@dataclass
class EffectDef:
    id: str
    label: str
    category: str
    description: str
    params: list
    fn: Callable
    needs: tuple = ()

    def defaults(self) -> dict:
        return {q["name"]: q["default"] for q in self.params}

    def to_json(self) -> dict:
        return {"id": self.id, "label": self.label, "category": self.category,
                "description": self.description, "params": self.params,
                "needs": list(self.needs)}


def effect(id: str, label: str, category: str = "Basicos",
           description: str = "", params: list | None = None,
           needs: tuple = ()):
    def deco(fn):
        EFFECTS[id] = EffectDef(id, label, category, description,
                                list(params or []), fn, needs)
        return fn
    return deco


def num(name, label, default, lo=0.0, hi=1.0, step=0.01, unit=""):
    return {"name": name, "label": label, "type": "float", "default": default,
            "min": lo, "max": hi, "step": step, "unit": unit}


def integer(name, label, default, lo=1, hi=100, step=1, unit=""):
    return {"name": name, "label": label, "type": "int", "default": default,
            "min": lo, "max": hi, "step": step, "unit": unit}


def color(name, label, default="#ff2d55"):
    return {"name": name, "label": label, "type": "color", "default": default}


def colors(name, label, default=None):
    return {"name": name, "label": label, "type": "colors",
            "default": list(default or ["#ff0040", "#00d4ff", "#7cff00"])}


def palette(name="palette", label="Paleta", default="rainbow"):
    return {"name": name, "label": label, "type": "palette", "default": default}


def boolean(name, label, default=False):
    return {"name": name, "label": label, "type": "bool", "default": default}


def choice(name, label, default, options):
    return {"name": name, "label": label, "type": "select", "default": default,
            "options": [{"value": v, "label": l} for v, l in options]}


def SPEED(default=0.5, lo=-3.0, hi=3.0):
    return num("speed", "Velocidade", default, lo, hi, 0.01, "x")


def SCALE(default=1.0, lo=0.1, hi=8.0):
    return num("scale", "Escala", default, lo, hi, 0.05, "x")


def ANGLE(default=0.0):
    return num("angle", "Angulo", default, 0.0, 360.0, 1.0, "graus")


def INTENSITY(default=1.0):
    return num("intensity", "Intensidade", default, 0.0, 2.0, 0.01)


def SOURCE_AXIS(default="x"):
    return choice("axis", "Eixo", default, [
        ("x", "Horizontal"), ("y", "Vertical"), ("radius", "Radial"),
        ("angle", "Angular"), ("piece", "Ao longo de cada peca"),
        ("strip", "Ao longo do dispositivo"),
    ])


def SCOPE(default="all"):
    return choice("scope", "Aplicar em", default, [
        ("all", "Tudo"), ("strips", "So nas fitas"), ("fans", "So nos fans"),
    ])


def apply_scope(ctx, out, p):
    scope = p.get("scope", "all")
    if scope == "strips":
        return out * ctx.is_strip[:, None]
    if scope == "fans":
        return out * ctx.is_fan[:, None]
    return out


def axis_values(ctx, p):
    a = p.get("axis", "x")
    if a == "y":
        return ctx.y
    if a == "radius":
        return ctx.radius
    if a == "angle":
        return ctx.angle01
    if a == "piece":
        return ctx.piece01
    if a == "strip":
        return ctx.strip01
    return ctx.x


def get(effect_id: str) -> EffectDef | None:
    return EFFECTS.get(effect_id)


def catalog() -> list:
    out = []
    for cat in CATEGORY_ORDER:
        items = [e.to_json() for e in EFFECTS.values() if e.category == cat]
        if items:
            out.append({"category": cat, "effects": items})
    resto = [e.to_json() for e in EFFECTS.values()
             if e.category not in CATEGORY_ORDER]
    if resto:
        out.append({"category": "Outros", "effects": resto})
    return out
