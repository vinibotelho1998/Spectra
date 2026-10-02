"""Registro de efeitos e os descritores de parametro.

Um efeito e uma funcao `(ctx, params, state) -> array (n, 3)` decorada
com `@effect`, que a registra e declara os parametros que a interface
deve desenhar. Os descritores, `num`, `color`, `palette` e companhia,
existem para que a tela de ajustes seja gerada a partir do codigo, e nao
mantida em paralelo com ele.

`state` e um dicionario que sobrevive entre quadros, onde os efeitos com
memoria guardam particula, grade de simulacao e afins. Ele e zerado
quando a camada troca de efeito.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

EFFECTS: dict[str, "EffectDef"] = {}
CATEGORY_ORDER = [
    "Basicos", "Fluxo", "Geometricos", "Pixel", "Ondas", "Ruido", "Particulas", "Simulacao",
    "Audio", "Sensores", "Tela",
]


@dataclass
class EffectDef:
    """Um efeito registrado, com os metadados que a interface precisa."""

    id: str
    label: str
    category: str
    description: str
    params: list
    fn: Callable
    needs: tuple = ()

    def defaults(self) -> dict:
        """Dicionario com o valor padrao de cada parametro."""
        return {q["name"]: deepcopy(q["default"]) for q in self.params}

    def to_json(self) -> dict:
        """Descreve o efeito no formato que a interface consome."""
        return {"id": self.id, "label": self.label, "category": self.category,
                "description": self.description, "params": self.params,
                "needs": list(self.needs)}


def effect(id: str, label: str, category: str = "Basicos",
           description: str = "", params: list | None = None,
           needs: tuple = ()):
    """Registra a funcao como efeito e declara os parametros dela.

    `needs` lista as fontes externas exigidas, como audio, sensores ou tela,
    para que a interface avise quando a fonte esta indisponivel em vez de
    mostrar um efeito que so ficaria preto.
    """
    def deco(fn):
        EFFECTS[id] = EffectDef(id, label, category, description,
                                list(params or []), fn, needs)
        return fn
    return deco


def num(name, label, default, lo=0.0, hi=1.0, step=0.01, unit=""):
    """Descreve um parametro de ponto flutuante com faixa e passo."""
    return {"name": name, "label": label, "type": "float", "default": default,
            "min": lo, "max": hi, "step": step, "unit": unit}


def integer(name, label, default, lo=1, hi=100, step=1, unit=""):
    """Descreve um parametro inteiro com faixa e passo."""
    return {"name": name, "label": label, "type": "int", "default": default,
            "min": lo, "max": hi, "step": step, "unit": unit}


def color(name, label, default="#ff2d55"):
    """Descreve um parametro de cor unica."""
    return {"name": name, "label": label, "type": "color", "default": default}


def colors(name, label, default=None):
    """Descreve um parametro de lista de cores."""
    return {"name": name, "label": label, "type": "colors",
            "default": list(default or ["#ff0040", "#00d4ff", "#7cff00"])}


def palette(name="palette", label="Paleta", default="rainbow"):
    """Descreve um parametro de paleta."""
    return {"name": name, "label": label, "type": "palette", "default": default}


def boolean(name, label, default=False):
    """Descreve um parametro de liga e desliga."""
    return {"name": name, "label": label, "type": "bool", "default": default}


def choice(name, label, default, options):
    """Descreve um parametro de escolha entre opcoes fixas."""
    return {"name": name, "label": label, "type": "select", "default": default,
            "options": [{"value": v, "label": l} for v, l in options]}


def SPEED(default=0.5, lo=-3.0, hi=3.0):
    """Parametro de velocidade, aceitando negativo para inverter o sentido."""
    return num("speed", "Velocidade", default, lo, hi, 0.01, "x")


def SCALE(default=1.0, lo=0.1, hi=8.0):
    """Parametro de escala espacial do padrao."""
    return num("scale", "Escala", default, lo, hi, 0.05, "x")


def ANGLE(default=0.0):
    """Parametro de angulo em graus."""
    return num("angle", "Angulo", default, 0.0, 360.0, 1.0, "graus")


def INTENSITY(default=1.0):
    """Parametro de intensidade, com folga acima de 1 para estourar de proposito."""
    return num("intensity", "Intensidade", default, 0.0, 2.0, 0.01)


def SOURCE_AXIS(default="x"):
    """Parametro que escolhe sobre qual eixo o efeito corre."""
    return choice("axis", "Eixo", default, [
        ("x", "Horizontal"), ("y", "Vertical"), ("radius", "Radial"),
        ("angle", "Angular"), ("piece", "Ao longo de cada peca"),
        ("strip", "Ao longo do dispositivo"),
    ])


def SCOPE(default="all"):
    """Parametro que limita o efeito a um tipo de peca.

    O rotulo nao pode ser "Aplicar em": esse ja e o campo dos alvos da
    camada, no mesmo painel, e os dois lado a lado confundiam.
    """
    return choice("scope", "Tipo de peca", default, [
        ("all", "Tudo"), ("strips", "So nas fitas"), ("fans", "So nos fans"),
    ])


def apply_scope(ctx, out, p):
    """Zera a saida fora das pecas escolhidas pelo parametro de escopo."""
    scope = p.get("scope", "all")
    if scope == "strips":
        return out * ctx.is_strip[:, None]
    if scope == "fans":
        return out * ctx.is_fan[:, None]
    return out


def axis_values(ctx, p):
    """Devolve o array de coordenadas do eixo escolhido."""
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
    """Busca um efeito pelo id, devolvendo None se nao existir."""
    return EFFECTS.get(effect_id)


def catalog() -> list:
    """Agrupa os efeitos por categoria, na ordem em que a interface mostra.

    Categoria fora da ordem conhecida cai num grupo Outros, para que nenhum
    efeito registrado suma da tela sem aviso.
    """
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
