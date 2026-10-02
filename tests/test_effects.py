from __future__ import annotations

import numpy as np
import pytest

from spectra import effects as fx
from spectra.effects.base import CATEGORY_ORDER
from spectra.engine.canvas import Canvas
from spectra.engine.context import RenderContext

from fakes import bancada

IDS = sorted(fx.EFFECTS)
NUMERICOS = ("float", "int")


def novo_ctx():
    c = RenderContext(Canvas(bancada()))
    c.audio.enabled = True
    c.audio.level = 0.5
    c.audio.peak = 0.8
    c.audio.bass = 0.7
    c.audio.mid = 0.4
    c.audio.treble = 0.3
    c.audio.beat = 0.9
    c.audio.centroid = 0.4
    c.audio.bands = np.abs(np.sin(np.linspace(0, 6, 24))).astype(np.float32)
    c.audio.waveform = np.sin(np.linspace(0, 20, 128)).astype(np.float32)
    c.sensors.enabled = True
    c.sensors.cpu_temp = 62.0
    c.sensors.gpu_temp = 71.0
    c.sensors.cpu_load = 45.0
    c.sensors.gpu_load = 88.0
    c.sensors.ram_load = 55.0
    c.sensors.fan_rpm = 1200.0
    c.screen.enabled = True
    rng = np.random.default_rng(7)
    c.screen.image = rng.random((36, 64, 3)).astype(np.float32)
    c.screen.average = np.array([0.3, 0.5, 0.7], dtype=np.float32)
    c.screen.dominant = np.array([0.8, 0.2, 0.4], dtype=np.float32)
    return c


def roda(effect_id, params=None, frames=8, ctx=None):
    d = fx.EFFECTS[effect_id]
    p = d.defaults()
    p.update(params or {})
    ctx = ctx or novo_ctx()
    estado = {}
    saidas = []
    for i in range(frames):
        ctx.t = i / 30.0
        ctx.dt = 1 / 30.0
        ctx.frame = i
        saidas.append(np.asarray(d.fn(ctx, p, estado), dtype=np.float32))
    return ctx, saidas


def extremos(d):
    mini, maxi = {}, {}
    for q in d.params:
        if q["type"] in NUMERICOS:
            mini[q["name"]] = q["min"]
            maxi[q["name"]] = q["max"]
    return mini, maxi


class TestRegistro:

    def test_tem_efeito_registrado(self):
        assert fx.count() > 0
        assert fx.count() == len(fx.EFFECTS)

    def test_id_bate_com_a_chave(self):
        for eid, d in fx.EFFECTS.items():
            assert d.id == eid

    @pytest.mark.parametrize("eid", IDS)
    def test_categoria_conhecida(self, eid):
        assert fx.EFFECTS[eid].category in CATEGORY_ORDER

    @pytest.mark.parametrize("eid", IDS)
    def test_tem_rotulo(self, eid):
        assert fx.EFFECTS[eid].label.strip()

    @pytest.mark.parametrize("eid", IDS)
    def test_parametros_bem_formados(self, eid):
        vistos = set()
        for q in fx.EFFECTS[eid].params:
            assert q["name"] not in vistos, "parametro repetido em %s" % eid
            vistos.add(q["name"])
            assert q["label"].strip()
            assert "default" in q

    @pytest.mark.parametrize("eid", IDS)
    def test_default_dentro_do_limite(self, eid):
        for q in fx.EFFECTS[eid].params:
            if q["type"] in NUMERICOS:
                assert q["min"] <= q["default"] <= q["max"], \
                    "%s.%s fora do limite" % (eid, q["name"])
                assert q["min"] < q["max"]

    @pytest.mark.parametrize("eid", IDS)
    def test_select_tem_default_valido(self, eid):
        for q in fx.EFFECTS[eid].params:
            if q["type"] == "select":
                valores = [o["value"] for o in q["options"]]
                assert q["default"] in valores, "%s.%s" % (eid, q["name"])
                assert len(valores) == len(set(valores))

    @pytest.mark.parametrize("eid", IDS)
    def test_to_json_serializavel(self, eid):
        import json
        json.dumps(fx.EFFECTS[eid].to_json())

    def test_get_encontra_e_erra_com_graca(self):
        assert fx.get(IDS[0]) is not None
        assert fx.get("nao existe") is None

    def test_listas_de_cores_padrao_sao_independentes(self):
        for definition in fx.EFFECTS.values():
            for param in definition.params:
                if isinstance(param["default"], list):
                    defaults = definition.defaults()
                    defaults[param["name"]].append("#123456")
                    assert definition.defaults()[param["name"]] == param["default"]

    def test_catalogo_cobre_todos_os_efeitos(self):
        total = sum(len(g["effects"]) for g in fx.catalog())
        assert total == fx.count()

    def test_catalogo_respeita_a_ordem_das_categorias(self):
        cats = [g["category"] for g in fx.catalog()]
        assert cats == [c for c in CATEGORY_ORDER if c in cats] or "Outros" in cats


class TestSaida:

    @pytest.mark.parametrize("eid", IDS)
    def test_formato_e_uma_cor_por_led(self, eid):
        ctx, saidas = roda(eid, frames=3)
        for out in saidas:
            assert out.shape == (ctx.n, 3), eid

    @pytest.mark.parametrize("eid", IDS)
    def test_nunca_gera_nan_nem_infinito(self, eid):
        _ctx, saidas = roda(eid)
        for i, out in enumerate(saidas):
            assert np.isfinite(out).all(), "%s gerou NaN no frame %d" % (eid, i)

    @pytest.mark.parametrize("eid", IDS)
    def test_fica_dentro_de_zero_e_um(self, eid):
        _ctx, saidas = roda(eid)
        for out in saidas:
            assert out.min() >= -1e-4, "%s abaixo de zero: %.4f" % (eid, out.min())
            assert out.max() <= 1.0 + 1e-3, "%s acima de um: %.4f" % (eid, out.max())

    @pytest.mark.parametrize("eid", IDS)
    def test_deterministico_com_a_mesma_semente(self, eid):
        _a, primeira = roda(eid, frames=4, ctx=novo_ctx())
        _b, segunda = roda(eid, frames=4, ctx=novo_ctx())
        for x, y in zip(primeira, segunda):
            assert np.array_equal(x, y), "%s nao repetiu" % eid

    @pytest.mark.parametrize("eid", IDS)
    def test_parametros_no_minimo(self, eid):
        mini, _ = extremos(fx.EFFECTS[eid])
        _ctx, saidas = roda(eid, mini, frames=4)
        for out in saidas:
            assert np.isfinite(out).all(), "%s no minimo gerou NaN" % eid

    @pytest.mark.parametrize("eid", IDS)
    def test_parametros_no_maximo(self, eid):
        _, maxi = extremos(fx.EFFECTS[eid])
        _ctx, saidas = roda(eid, maxi, frames=4)
        for out in saidas:
            assert np.isfinite(out).all(), "%s no maximo gerou NaN" % eid

    @pytest.mark.parametrize("eid", IDS)
    def test_canvas_vazio_nao_quebra(self, eid):
        ctx = RenderContext(Canvas([]))
        d = fx.EFFECTS[eid]
        out = np.asarray(d.fn(ctx, d.defaults(), {}))
        assert out.shape == (0, 3)


class TestEscopo:

    def ids_com_escopo(self):
        return [e for e in IDS
                if any(q["name"] == "scope" for q in fx.EFFECTS[e].params)]

    def test_existe_efeito_com_escopo(self):
        assert self.ids_com_escopo()

    def test_rotulo_nao_repete_o_campo_de_alvos(self):
        # "Aplicar em" e o campo dos alvos da camada, no mesmo painel
        for e in self.ids_com_escopo():
            q = next(q for q in fx.EFFECTS[e].params if q["name"] == "scope")
            assert q["label"] != "Aplicar em", e

    @pytest.mark.parametrize("eid", sorted(
        e for e in IDS
        if any(q["name"] == "scope" for q in fx.EFFECTS[e].params)))
    def test_escopo_fans_apaga_o_resto(self, eid):
        ctx, saidas = roda(eid, {"scope": "fans"}, frames=3)
        fora = ~ctx.is_fan
        for out in saidas:
            assert np.allclose(out[fora], 0.0), eid

    @pytest.mark.parametrize("eid", sorted(
        e for e in IDS
        if any(q["name"] == "scope" for q in fx.EFFECTS[e].params)))
    def test_escopo_fitas_apaga_o_resto(self, eid):
        ctx, saidas = roda(eid, {"scope": "strips"}, frames=3)
        fora = ~ctx.is_strip
        for out in saidas:
            assert np.allclose(out[fora], 0.0), eid


class TestEixos:

    @pytest.mark.parametrize("eixo", ["x", "y", "radius", "angle", "piece", "strip"])
    def test_todo_eixo_roda(self, eixo):
        alvos = [e for e in IDS
                 if any(q["name"] == "axis" for q in fx.EFFECTS[e].params)]
        assert alvos
        for eid in alvos[:12]:
            _ctx, saidas = roda(eid, {"axis": eixo}, frames=2)
            for out in saidas:
                assert np.isfinite(out).all(), "%s no eixo %s" % (eid, eixo)
