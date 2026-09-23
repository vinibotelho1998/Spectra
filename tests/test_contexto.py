"""Testes do contexto de quadro: espectro, sensores, tela e eixo girado.

Sao as leituras que todo efeito reativo faz; erro aqui aparece como LED
com cor trocada ou efeito que estoura quando a fonte esta fora.
"""
from __future__ import annotations

import numpy as np
import pytest

from spectra.engine.context import (AudioState, RenderContext, ScreenState,
                                    SensorState)


class TestEspectro:

    @pytest.fixture
    def audio(self):
        a = AudioState(bands=5)
        a.bands = np.array([0.0, 0.2, 0.4, 0.6, 1.0], dtype=np.float32)
        return a

    def test_pontas_leem_a_primeira_e_a_ultima_banda(self, audio):
        assert audio.band_at(0.0) == pytest.approx(0.0)
        assert audio.band_at(1.0) == pytest.approx(1.0)

    def test_centro_da_banda_le_ela_mesma(self, audio):
        assert audio.band_at(0.25) == pytest.approx(0.2)
        assert audio.band_at(0.5) == pytest.approx(0.4)

    def test_entre_bandas_interpola(self, audio):
        assert audio.band_at(0.125) == pytest.approx(0.1)
        assert audio.band_at(0.875) == pytest.approx(0.8)

    def test_fora_da_faixa_fica_na_ponta(self, audio):
        assert audio.band_at(-3.0) == pytest.approx(0.0)
        assert audio.band_at(7.0) == pytest.approx(1.0)

    def test_vetorizado(self, audio):
        u = np.array([[0.0, 0.5], [0.75, 1.0]], dtype=np.float32)
        out = audio.band_at(u)
        assert out.shape == (2, 2)
        assert out == pytest.approx(np.array([[0.0, 0.4], [0.6, 1.0]]))

    def test_estado_novo_e_silencio(self):
        a = AudioState()
        assert a.enabled is False
        assert len(a.bands) == 24
        assert not a.band_at(np.linspace(0, 1, 9)).any()


class TestSensores:

    def test_le_pelo_nome(self):
        s = SensorState()
        s.cpu_temp, s.gpu_load, s.fan_rpm = 55.0, 30.0, 900.0
        assert s.value("cpu_temp") == 55.0
        assert s.value("gpu_load") == 30.0
        assert s.value("fan_rpm") == 900.0

    def test_extra_e_desconhecido(self):
        s = SensorState()
        s.extra["vrm_temp"] = 80.0
        assert s.value("vrm_temp") == 80.0
        assert s.value("nao_existe") == 0.0

    def test_nome_fixo_ganha_do_extra(self):
        s = SensorState()
        s.cpu_temp = 40.0
        s.extra["cpu_temp"] = 99.0
        assert s.value("cpu_temp") == 40.0

    def test_normaliza_dentro_da_faixa(self):
        s = SensorState()
        s.cpu_temp = 60.0
        assert s.normalized("cpu_temp", 40.0, 80.0) == pytest.approx(0.5)

    def test_normaliza_satura_nas_pontas(self):
        s = SensorState()
        s.cpu_temp = 20.0
        assert s.normalized("cpu_temp", 40.0, 80.0) == 0.0
        s.cpu_temp = 120.0
        assert s.normalized("cpu_temp", 40.0, 80.0) == 1.0

    @pytest.mark.parametrize("lo,hi", [(80.0, 40.0), (50.0, 50.0)])
    def test_faixa_invertida_ou_vazia_devolve_zero(self, lo, hi):
        s = SensorState()
        s.cpu_temp = 60.0
        assert s.normalized("cpu_temp", lo, hi) == 0.0


class TestTela:

    @pytest.fixture
    def tela(self):
        t = ScreenState(h=2, w=2)
        t.image = np.array([[[0, 0, 0], [1, 0, 0]],
                            [[0, 1, 0], [0, 0, 1]]], dtype=np.float32)
        return t

    def test_cantos_leem_o_pixel_do_canto(self, tela):
        assert tela.sample(0.0, 0.0) == pytest.approx([0, 0, 0])
        assert tela.sample(1.0, 0.0) == pytest.approx([1, 0, 0])
        assert tela.sample(0.0, 1.0) == pytest.approx([0, 1, 0])
        assert tela.sample(1.0, 1.0) == pytest.approx([0, 0, 1])

    def test_centro_mistura_os_quatro(self, tela):
        assert tela.sample(0.5, 0.5) == pytest.approx([0.25, 0.25, 0.25])

    def test_meio_da_borda_mistura_dois(self, tela):
        assert tela.sample(0.5, 0.0) == pytest.approx([0.5, 0.0, 0.0])
        assert tela.sample(0.0, 0.5) == pytest.approx([0.0, 0.5, 0.0])

    def test_fora_da_tela_fica_na_borda(self, tela):
        assert tela.sample(-1.0, 5.0) == pytest.approx([0, 1, 0])

    def test_vetorizado_da_uma_cor_por_ponto(self, tela):
        out = tela.sample(np.array([0.0, 1.0, 0.5]), np.array([0.0, 1.0, 0.5]))
        assert out.shape == (3, 3)
        assert out.dtype == np.float32
        assert out[1] == pytest.approx([0, 0, 1])


class TestContexto:

    def test_repassa_as_coordenadas_do_canvas(self, canvas):
        c = RenderContext(canvas)
        assert c.n == canvas.n
        assert c.x is canvas.x
        assert c.y is canvas.y
        assert c.piece_id is canvas.piece_id

    def test_zeros_e_um_quadro_preto(self, canvas):
        z = RenderContext(canvas).zeros()
        assert z.shape == (canvas.n, 3)
        assert z.dtype == np.float32
        assert not z.any()

    def test_eixo_girado(self, canvas):
        c = RenderContext(canvas)
        assert c.rotated(0.0) == pytest.approx(canvas.x, abs=1e-6)
        assert c.rotated(90.0) == pytest.approx(canvas.y, abs=1e-6)
        assert c.rotated(180.0) == pytest.approx(-canvas.x, abs=1e-6)
        assert c.rotated(45.0) == pytest.approx(
            (canvas.x + canvas.y) / np.sqrt(2), abs=1e-5)

    def test_gerador_semeado_repete(self, canvas):
        a = RenderContext(canvas).rng.random(4)
        b = RenderContext(canvas).rng.random(4)
        assert np.array_equal(a, b)
