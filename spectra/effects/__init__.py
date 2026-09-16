"""Catalogo de efeitos.

Importar o pacote registra todos os efeitos dos modulos filhos em
`EFFECTS`, entao basta importar `spectra.effects` para ter o catalogo
completo.
"""

from . import (basic, cable, flow, noisefx, particles,
               pixel, reactive, sim, waves)
from .base import EFFECTS, catalog, effect, get

__all__ = ["EFFECTS", "catalog", "effect", "get"]


def count() -> int:
    """Quantos efeitos estao registrados."""
    return len(EFFECTS)
