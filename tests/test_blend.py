from __future__ import annotations

import numpy as np
import pytest

from prism.engine import blend

BRANCO = np.ones((8, 3), dtype=np.float32)
PRETO = np.zeros((8, 3), dtype=np.float32)


@pytest.fixture
def par():
    rng = np.random.default_rng(3)
    base = rng.random((8, 3)).astype(np.float32)
    top = rng.random((8, 3)).astype(np.float32)
    return base, top


class TestCatalogo:

    def test_tem_os_doze_modos(self):
        assert len(blend.MODES) == 12

    def test_todo_rotulo_aponta_para_um_modo(self):
        for nome, _label in blend.LABELS:
            assert nome in blend.MODES

    def test_todo_modo_tem_rotulo(self):
        rotulados = {n for n, _ in blend.LABELS}
        assert set(blend.MODES) == rotulados


class TestModos:

    @pytest.mark.parametrize("nome", sorted(blend.MODES))
    def test_preserva_o_formato(self, nome, par):
        base, top = par
        out = blend.MODES[nome](base, top)
        assert out.shape == base.shape
        assert np.isfinite(out).all()

    def test_normal_ignora_a_base(self, par):
        base, top = par
        assert np.array_equal(blend.normal(base, top), top)

    def test_multiply_por_branco_devolve_a_base(self, par):
        base, _ = par
        assert blend.multiply(base, BRANCO) == pytest.approx(base)

    def test_multiply_por_preto_apaga(self, par):
        base, _ = par
        assert blend.multiply(base, PRETO) == pytest.approx(PRETO)

    def test_screen_com_preto_devolve_a_base(self, par):
        base, _ = par
        assert blend.screen(base, PRETO) == pytest.approx(base, abs=1e-6)

    def test_screen_com_branco_estoura(self, par):
        base, _ = par
        assert blend.screen(base, BRANCO) == pytest.approx(BRANCO)

    def test_add_soma(self, par):
        base, top = par
        assert blend.add(base, top) == pytest.approx(base + top)

    def test_subtract_subtrai(self, par):
        base, top = par
        assert blend.subtract(base, top) == pytest.approx(base - top)

    def test_difference_nunca_negativa(self, par):
        base, top = par
        assert (blend.difference(base, top) >= 0).all()

    def test_difference_e_simetrica(self, par):
        base, top = par
        assert blend.difference(base, top) == pytest.approx(
            blend.difference(top, base))

    def test_lighten_pega_o_maior(self, par):
        base, top = par
        out = blend.lighten(base, top)
        assert (out >= base).all() and (out >= top).all()

    def test_darken_pega_o_menor(self, par):
        base, top = par
        out = blend.darken(base, top)
        assert (out <= base).all() and (out <= top).all()

    def test_mask_com_preto_apaga(self, par):
        base, _ = par
        assert blend.mask(base, PRETO) == pytest.approx(PRETO)

    def test_mask_com_branco_devolve_a_base(self, par):
        base, _ = par
        assert blend.mask(base, BRANCO) == pytest.approx(base, abs=1e-5)

    def test_alpha_over_com_preto_mantem_a_base(self, par):
        base, _ = par
        assert blend.alpha_over(base, PRETO) == pytest.approx(base)

    def test_alpha_over_com_branco_cobre(self, par):
        base, _ = par
        assert blend.alpha_over(base, BRANCO) == pytest.approx(BRANCO, abs=1e-5)


class TestApply:

    def test_opacidade_um_e_o_modo_puro(self, par):
        base, top = par
        assert blend.apply("multiply", base, top, 1.0) == pytest.approx(
            blend.multiply(base, top))

    def test_opacidade_zero_mantem_a_base(self, par):
        base, top = par
        assert blend.apply("add", base, top, 0.0) == pytest.approx(base)

    def test_opacidade_meio_fica_no_meio(self, par):
        base, top = par
        meio = blend.apply("normal", base, top, 0.5)
        assert meio == pytest.approx((base + top) / 2, abs=1e-6)

    def test_modo_desconhecido_cai_no_normal(self, par):
        base, top = par
        assert blend.apply("inexistente", base, top) == pytest.approx(top)

    @pytest.mark.parametrize("nome", sorted(blend.MODES))
    def test_nenhum_modo_gera_nan(self, nome, par):
        base, top = par
        assert np.isfinite(blend.apply(nome, base, top, 0.7)).all()

    @pytest.mark.parametrize("nome", sorted(blend.MODES))
    def test_extremos_nao_geram_nan(self, nome):
        for a in (PRETO, BRANCO):
            for b in (PRETO, BRANCO):
                assert np.isfinite(blend.apply(nome, a, b)).all()
