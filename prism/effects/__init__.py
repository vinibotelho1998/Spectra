from . import (basic, cable, flow, noisefx, particles,
               pixel, reactive, sim, waves)
from .base import EFFECTS, catalog, effect, get

__all__ = ["EFFECTS", "catalog", "effect", "get"]


def count() -> int:
    return len(EFFECTS)
