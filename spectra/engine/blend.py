"""Modos de composicao entre camadas.

Cada funcao recebe dois arrays (n, 3) em ponto flutuante, a base ja
composta e o topo da camada nova, e devolve a mistura. Nenhuma satura o
resultado: o corte para 0 a 1 acontece uma vez so, na saida do
renderizador, para que somas intermediarias nao percam informacao.
"""

from __future__ import annotations

import numpy as np


def _lum(c):
    return (c[:, 0] * 0.2126 + c[:, 1] * 0.7152 + c[:, 2] * 0.0722)[:, None]


def normal(base, top):
    """Substitui a base pelo topo."""
    return top


def add(base, top):
    """Soma os dois, que e o modo natural para luz sobre luz."""
    return base + top


def screen(base, top):
    """Clareia sem estourar, invertendo, multiplicando e invertendo de volta."""
    return 1.0 - (1.0 - base) * (1.0 - top)


def multiply(base, top):
    """Multiplica os dois, escurecendo."""
    return base * top


def overlay(base, top):
    """Multiplica onde a base e escura e clareia onde e clara."""
    return np.where(base < 0.5, 2 * base * top, 1.0 - 2 * (1 - base) * (1 - top))


def soft_light(base, top):
    """Clareia ou escurece de leve, conforme o topo."""
    return (1 - 2 * top) * base * base + 2 * top * base


def lighten(base, top):
    """Fica com o mais claro dos dois, canal a canal."""
    return np.maximum(base, top)


def darken(base, top):
    """Fica com o mais escuro dos dois, canal a canal."""
    return np.minimum(base, top)


def difference(base, top):
    """Distancia absoluta entre os dois."""
    return np.abs(base - top)


def subtract(base, top):
    """Subtrai o topo da base."""
    return base - top


def mask(base, top):
    """Usa o brilho do topo como mascara sobre a base."""
    return base * _lum(top)


def alpha_over(base, top):
    """Sobrepoe usando o brilho do topo como canal alfa."""
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
    ("normal", "Normal"), ("alpha_over", "Por cima, preto transparente"),
    ("add", "Somar"),
    ("screen", "Clarear (screen)"), ("multiply", "Multiplicar"),
    ("overlay", "Sobreposicao"), ("soft_light", "Luz suave"),
    ("lighten", "Mais claro"), ("darken", "Mais escuro"),
    ("difference", "Diferenca"), ("subtract", "Subtrair"),
    ("mask", "Mascara"),
]


def apply(name, base, top, opacity=1.0):
    """Aplica um modo pelo nome, misturando pela opacidade.

    Modo desconhecido cai no normal, para que uma cena salva com um modo que
    nao existe mais ainda abra.
    """
    fn = MODES.get(name, normal)
    out = fn(base, top)
    if opacity < 1.0:
        out = base * (1.0 - opacity) + out * opacity
    return out
