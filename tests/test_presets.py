from __future__ import annotations

import json
import re

import pytest

from spectra import presets
from spectra.effects import EFFECTS
from spectra.engine import blend

HEX = re.compile(r"^#[0-9a-f]{3,8}$", re.I)
TODOS = list(presets.PRESETS)
POR_ID = [p.id for p in TODOS]


def camadas(p):
    return p.layers


class TestCatalogo:

    def test_tem_preset(self):
        assert len(TODOS) > 0

    def test_id_unico(self):
        assert len(POR_ID) == len(set(POR_ID))

    @pytest.mark.parametrize("pid", POR_ID)
    def test_by_id_encontra(self, pid):
        assert presets.by_id(pid) is not None

    def test_by_id_desconhecido_devolve_none(self):
        assert presets.by_id("nao existe") is None

    def test_catalogo_cobre_todos(self):
        total = sum(len(g["presets"]) if "presets" in g else len(g.get("items", []))
                    for g in presets.catalog())
        assert total == len(TODOS)

    def test_catalogo_serializavel(self):
        json.dumps(presets.catalog())


class TestConteudo:

    @pytest.mark.parametrize("pid", POR_ID)
    def test_tem_nome_e_descricao(self, pid):
        p = presets.by_id(pid)
        assert p.name.strip()
        assert p.description.strip()

    @pytest.mark.parametrize("pid", POR_ID)
    def test_swatch_em_hex(self, pid):
        p = presets.by_id(pid)
        cores = p.swatch if isinstance(p.swatch, (list, tuple)) else [p.swatch]
        for c in cores:
            assert HEX.match(str(c)), "%s tem swatch invalido %r" % (pid, c)

    @pytest.mark.parametrize("pid", POR_ID)
    def test_tem_pelo_menos_uma_camada(self, pid):
        assert len(camadas(presets.by_id(pid))) >= 1

    @pytest.mark.parametrize("pid", POR_ID)
    def test_efeito_citado_existe(self, pid):
        for c in camadas(presets.by_id(pid)):
            assert c["effect"] in EFFECTS, \
                "%s cita o efeito inexistente %s" % (pid, c["effect"])

    @pytest.mark.parametrize("pid", POR_ID)
    def test_parametro_citado_existe(self, pid):
        for c in camadas(presets.by_id(pid)):
            d = EFFECTS[c["effect"]]
            validos = {q["name"] for q in d.params}
            for nome in c.get("params", {}):
                assert nome in validos, \
                    "%s passa %r para %s, que nao tem esse parametro" % (
                        pid, nome, c["effect"])

    @pytest.mark.parametrize("pid", POR_ID)
    def test_valor_numerico_dentro_do_limite(self, pid):
        for c in camadas(presets.by_id(pid)):
            d = EFFECTS[c["effect"]]
            limites = {q["name"]: q for q in d.params
                       if q["type"] in ("float", "int")}
            for nome, valor in c.get("params", {}).items():
                q = limites.get(nome)
                if q is None or not isinstance(valor, (int, float)):
                    continue
                assert q["min"] <= valor <= q["max"], \
                    "%s manda %s=%r fora de %s..%s" % (
                        pid, nome, valor, q["min"], q["max"])

    @pytest.mark.parametrize("pid", POR_ID)
    def test_opcao_de_select_valida(self, pid):
        for c in camadas(presets.by_id(pid)):
            d = EFFECTS[c["effect"]]
            selects = {q["name"]: [o["value"] for o in q["options"]]
                       for q in d.params if q["type"] == "select"}
            for nome, valor in c.get("params", {}).items():
                if nome in selects:
                    assert valor in selects[nome], \
                        "%s manda %s=%r, fora das opcoes" % (pid, nome, valor)

    @pytest.mark.parametrize("pid", POR_ID)
    def test_blend_conhecido(self, pid):
        for c in camadas(presets.by_id(pid)):
            assert c["blend"] in blend.MODES, \
                "%s usa blend desconhecido %s" % (pid, c["blend"])

    @pytest.mark.parametrize("pid", POR_ID)
    def test_opacidade_entre_zero_e_um(self, pid):
        for c in camadas(presets.by_id(pid)):
            assert 0.0 <= c["opacity"] <= 1.0

    @pytest.mark.parametrize("pid", POR_ID)
    def test_cena_serializavel(self, pid):
        cena = presets.by_id(pid).scene()
        assert "layers" in cena
        json.dumps(cena)

    @pytest.mark.parametrize("pid", POR_ID)
    def test_to_json_expoe_o_essencial(self, pid):
        d = presets.by_id(pid).to_json()
        assert d["id"] == pid
        assert d["layer_count"] == len(camadas(presets.by_id(pid)))
        json.dumps(d)


class TestRefinados:

    def test_agressivos_apontam_para_presets_reais(self):
        for pid in presets.AGRESSIVOS:
            assert pid in POR_ID, "%s esta em AGRESSIVOS mas nao existe" % pid

    def test_agressivo_e_marcado_como_nao_refinado(self):
        for p in TODOS:
            esperado = p.id not in presets.AGRESSIVOS
            assert p.refined is esperado, p.id

    def test_sobra_preset_refinado(self):
        assert sum(1 for p in TODOS if p.refined) > len(TODOS) // 2


class TestExecucao:

    @pytest.mark.parametrize("pid", POR_ID)
    def test_todas_as_camadas_renderizam(self, pid, ctx):
        for c in camadas(presets.by_id(pid)):
            d = EFFECTS[c["effect"]]
            p = d.defaults()
            p.update(c.get("params", {}))
            estado = {}
            import numpy as np
            for i in range(3):
                ctx.t = i / 30.0
                ctx.dt = 1 / 30.0
                out = np.asarray(d.fn(ctx, p, estado), dtype=np.float32)
                assert out.shape == (ctx.n, 3)
                assert np.isfinite(out).all(), \
                    "%s quebrou na camada %s" % (pid, c["effect"])
