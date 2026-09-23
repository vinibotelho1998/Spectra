"""Testes de comportamento dos efeitos basicos e dos ajudantes de base.

`test_effects` garante que todo efeito devolve algo bem formado; aqui a
pergunta e se ele pinta a cor certa, no instante certo, no LED certo.
"""
from __future__ import annotations

import numpy as np
import pytest

from spectra.effects import base
from spectra.effects.base import EFFECTS, EffectDef
from spectra.engine.context import RenderContext


def pinta(ctx, eid, t=0.0, st=None, **params):
    p = EFFECTS[eid].defaults()
    p.update(params)
    ctx.t = t
    return EFFECTS[eid].fn(ctx, p, {} if st is None else st)


@pytest.fixture
def quadro(canvas):
    return RenderContext(canvas)


class TestCorUnica:

    def test_cor_e_intensidade(self, quadro):
        out = pinta(quadro, "static", color="#ff8000", intensity=0.5)
        assert out.shape == (quadro.n, 3)
        assert out == pytest.approx(np.tile([0.5, 128 / 255 * 0.5, 0.0], (quadro.n, 1)),
                                    abs=1e-3)


class TestRespiracao:

    def test_no_vale_fica_no_brilho_minimo(self, quadro):
        out = pinta(quadro, "breathing", t=0.0, color="#ffffff", floor=0.2)
        assert out == pytest.approx(0.2)

    def test_no_pico_acende_inteiro(self, quadro):
        # seno ao quadrado chega a um quando t * speed * pi = pi / 2
        out = pinta(quadro, "breathing", t=1.25, color="#ffffff", speed=0.4, floor=0.2)
        assert out == pytest.approx(1.0, abs=1e-5)


class TestStrobo:

    def test_aceso_dentro_do_duty(self, quadro):
        out = pinta(quadro, "strobe", t=0.01, color="#ffffff", hz=10.0, duty=0.5)
        assert out == pytest.approx(1.0)

    def test_apagado_fora_do_duty(self, quadro):
        out = pinta(quadro, "strobe", t=0.07, color="#ffffff", hz=10.0, duty=0.5)
        assert not out.any()


class TestWipe:

    def test_vai_e_volta_espelha_a_fase(self, quadro):
        ida = pinta(quadro, "wipe", t=0.3, speed=1.0, bounce=True, soft=0.0)
        volta = pinta(quadro, "wipe", t=1.7, speed=1.0, bounce=True, soft=0.0)
        assert np.array_equal(ida, volta)

    def test_frente_pintada_e_resto_no_fundo(self, quadro):
        out = pinta(quadro, "wipe", t=0.5, speed=1.0, bounce=False, soft=0.0,
                    color="#ffffff", bg="#000000")
        atras = quadro.x < 0.49
        frente = quadro.x > 0.51
        assert atras.any() and frente.any()
        assert out[atras] == pytest.approx(1.0)
        assert not out[frente].any()


class TestViatura:

    def test_metades_trocam_de_cor(self, quadro):
        a = pinta(quadro, "police", t=0.0, hz=1.0, style="split")
        b = pinta(quadro, "police", t=0.6, hz=1.0, style="split")
        esquerda = quadro.x < 0.5
        assert a[esquerda] == pytest.approx(np.tile([1, 0, 0], (esquerda.sum(), 1)))
        assert a[~esquerda][:, 2] == pytest.approx(1.0)
        assert b[esquerda][:, 2] == pytest.approx(1.0)
        assert b[~esquerda][:, 0] == pytest.approx(1.0)
        assert b[~esquerda][:, 2] == pytest.approx(0.0)

    def test_flash_pisca_entre_os_pulsos(self, quadro):
        aceso = pinta(quadro, "police", t=0.05, hz=1.0, style="flash")
        apagado = pinta(quadro, "police", t=0.2, hz=1.0, style="flash")
        assert aceso[:, 0] == pytest.approx(1.0)
        assert not apagado.any()


class TestAlternado:

    def test_grupos_intercalados(self, quadro):
        out = pinta(quadro, "alternating", colors=["#ff0000", "#0000ff"], group=3)
        vermelho = out[:, 0] > 0.5
        assert vermelho[:6].tolist() == [True] * 3 + [False] * 3

    def test_lista_vazia_apaga(self, quadro):
        assert not pinta(quadro, "alternating", colors=[]).any()

    def test_rolar_desloca_o_padrao(self, quadro):
        tres = ["#ff0000", "#00ff00", "#0000ff"]
        parado = pinta(quadro, "alternating", colors=tres, group=1, speed=0.0)
        rolado = pinta(quadro, "alternating", colors=tres, group=1, speed=1.0, t=0.1)
        assert np.array_equal(rolado[:-1], parado[1:])


class TestChase:

    def test_lista_vazia_apaga(self, quadro):
        assert not pinta(quadro, "chase", colors=[]).any()

    def test_so_usa_as_cores_da_lista(self, quadro):
        out = pinta(quadro, "chase", colors=["#ff0000", "#00ff00"], t=0.3)
        linhas = {tuple(np.round(c, 3)) for c in out}
        assert linhas <= {(1.0, 0.0, 0.0), (0.0, 1.0, 0.0)}
        assert len(linhas) == 2


class TestAleatorio:

    def test_suaviza_ate_o_alvo(self, quadro):
        st = {}
        primeiro = pinta(quadro, "random_leds", st=st, t=0.0, hz=1.0, fade=0.5)
        assert primeiro == pytest.approx(st["target"] * 0.5)
        segundo = pinta(quadro, "random_leds", st=st, t=0.1, hz=1.0, fade=0.5)
        assert segundo == pytest.approx(st["target"] * 0.75)

    def test_sorteia_de_novo_so_quando_o_passo_muda(self, quadro):
        st = {}
        pinta(quadro, "random_leds", st=st, t=0.0, hz=1.0)
        alvo = st["target"].copy()
        pinta(quadro, "random_leds", st=st, t=0.9, hz=1.0)
        assert np.array_equal(st["target"], alvo)
        pinta(quadro, "random_leds", st=st, t=1.1, hz=1.0)
        assert not np.array_equal(st["target"], alvo)


class TestAjudantes:

    def test_escopo(self, quadro):
        out = np.ones((quadro.n, 3), dtype=np.float32)
        fans = base.apply_scope(quadro, out, {"scope": "fans"})
        fitas = base.apply_scope(quadro, out, {"scope": "strips"})
        assert np.array_equal(fans[:, 0], quadro.is_fan.astype(np.float32))
        assert np.array_equal(fitas[:, 0], quadro.is_strip.astype(np.float32))
        assert base.apply_scope(quadro, out, {}) is out

    @pytest.mark.parametrize("eixo,campo", [
        ("x", "x"), ("y", "y"), ("radius", "radius"), ("angle", "angle01"),
        ("piece", "piece01"), ("strip", "strip01"), ("desconhecido", "x"),
    ])
    def test_eixo_escolhido(self, quadro, eixo, campo):
        assert base.axis_values(quadro, {"axis": eixo}) is getattr(quadro, campo)

    def test_categoria_fora_da_ordem_vai_para_outros(self, monkeypatch):
        monkeypatch.setitem(EFFECTS, "teste_avulso", EffectDef(
            "teste_avulso", "Avulso", "Inventada", "", [], lambda c, p, s: None))
        cats = base.catalog()
        assert cats[-1]["category"] == "Outros"
        assert [e["id"] for e in cats[-1]["effects"]] == ["teste_avulso"]

    def test_decorador_registra_com_os_padroes(self, monkeypatch):
        monkeypatch.setattr(base, "EFFECTS", dict(EFFECTS))

        @base.effect("teste_reg", "Reg", "Basicos", "d",
                     [base.num("a", "A", 0.3), base.boolean("b", "B", True)],
                     needs=("audio",))
        def _fn(ctx, p, st):
            return None

        d = base.EFFECTS["teste_reg"]
        assert d.fn is _fn
        assert d.defaults() == {"a": 0.3, "b": True}
        assert d.to_json()["needs"] == ["audio"]
