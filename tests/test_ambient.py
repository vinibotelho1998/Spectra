"""Controles e continuidade dos novos efeitos espaciais, sem hardware."""
from __future__ import annotations

import numpy as np
import pytest

from spectra.effects import get
from spectra.engine.canvas import Canvas
from spectra.engine.context import RenderContext
from fakes import FakeDevice, FakeZone

EFFECTS = ("silk", "prism", "dunes", "eclipse", "lotus", "lissajous",
           "woven", "tidal", "helix", "constellation")


@pytest.mark.parametrize("eid", EFFECTS)
def test_velocidade_zero_congela_movimento_e_cor(eid, ctx):
    d = get(eid)
    params = dict(d.defaults(), speed=0.0)
    first = d.fn(ctx, params, {})
    ctx.t = 234.5
    np.testing.assert_array_equal(first, d.fn(ctx, params, {}))


@pytest.mark.parametrize("eid", EFFECTS)
def test_padrao_tem_movimento_visivel(eid, ctx):
    d = get(eid)
    first = d.fn(ctx, d.defaults(), {})
    ctx.t = 4.0
    second = d.fn(ctx, d.defaults(), {})
    assert np.max(np.abs(first - second)) > 0.02


@pytest.mark.parametrize("eid", EFFECTS)
def test_velocidade_negativa_inverte_o_tempo(eid, ctx):
    d = get(eid)
    params = dict(d.defaults(), speed=-0.5)
    ctx.t = 3.0
    reverse = d.fn(ctx, params, {})
    params["speed"] = 0.5
    ctx.t = -3.0
    np.testing.assert_allclose(reverse, d.fn(ctx, params, {}), atol=1e-6)


@pytest.mark.parametrize("eid", EFFECTS)
def test_funciona_com_apenas_um_led(eid):
    ctx = RenderContext(Canvas([FakeDevice(0, "Logo", "Mouse",
                                          [FakeZone(0, "Logo", 1, type=0)])]))
    d = get(eid)
    for t in (0.0, 1.0, 9999.0):
        ctx.t = t
        out = d.fn(ctx, d.defaults(), {})
        assert out.shape == (1, 3)
        assert out.dtype == np.float32
        assert np.isfinite(out).all()
        assert np.all((out >= 0) & (out <= 1))


@pytest.mark.parametrize("eid", EFFECTS)
def test_intensidade_zero_apaga_todo_o_efeito(eid, ctx):
    d = get(eid)
    ctx.t = 2.3
    out = d.fn(ctx, dict(d.defaults(), intensity=0.0), {})
    assert not out.any()
