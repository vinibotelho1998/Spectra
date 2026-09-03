from __future__ import annotations

import numpy as np


def _lum(c):
    return (c[:, 0] * 0.2126 + c[:, 1] * 0.7152 + c[:, 2] * 0.0722)[:, None]


def normal(base, top):
    return top


def add(base, top):
    return base + top


def screen(base, top):
    return 1.0 - (1.0 - base) * (1.0 - top)


def multiply(base, top):
    return base * top


def overlay(base, top):
    return np.where(base < 0.5, 2 * base * top, 1.0 - 2 * (1 - base) * (1 - top))


def soft_light(base, top):
    return (1 - 2 * top) * base * base + 2 * top * base


def lighten(base, top):
    return np.maximum(base, top)


def darken(base, top):
    return np.minimum(base, top)


def difference(base, top):
    return np.abs(base - top)


def subtract(base, top):
    return base - top


def mask(base, top):
    return base * _lum(top)


def alpha_over(base, top):
    a = _lum(top)
    return base * (1.0 - a) + top * a


MODES = {
    "normal": normal,
    "add": add,
    "screen": screen,
    "multiply": multiply,
    "overlay": overlay,
    "soft_light": soft_light,
    "lighten": lighten,
    "darken": darken,
    "difference": difference,
    "subtract": subtract,
    "mask": mask,
    "alpha_over": alpha_over,
}

LABELS = [
    ("normal", "Normal"), ("alpha_over", "Sobrepor"), ("add", "Somar"),
    ("screen", "Clarear (screen)"), ("multiply", "Multiplicar"),
    ("overlay", "Sobreposicao"), ("soft_light", "Luz suave"),
    ("lighten", "Mais claro"), ("darken", "Mais escuro"),
    ("difference", "Diferenca"), ("subtract", "Subtrair"),
    ("mask", "Mascara"),
]


def apply(name, base, top, opacity=1.0):
    fn = MODES.get(name, normal)
    out = fn(base, top)
    if opacity < 1.0:
        out = base * (1.0 - opacity) + out * opacity
    return out
