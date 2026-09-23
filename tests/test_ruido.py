"""Testes do ruido coerente que alimenta os efeitos organicos.

O que importa aqui e o contrato: faixa de 0 a 1, repeticao exata do mesmo
instante, continuidade entre vizinhos e periodo de 256 na grade.
"""
from __future__ import annotations

import numpy as np
import pytest

from spectra.engine.noise import (curl_offset, fbm3, turbulence3,
                                  value_noise3)


def _grade(n=400, semente=3):
    rng = np.random.default_rng(semente)
    return (rng.uniform(-50, 50, n).astype(np.float32),
            rng.uniform(-50, 50, n).astype(np.float32),
            rng.uniform(0, 20, n).astype(np.float32))


class TestValor:

    def test_fica_entre_zero_e_um(self):
        v = value_noise3(*_grade())
        assert v.min() >= 0.0 and v.max() <= 1.0

    def test_nao_e_constante(self):
        assert value_noise3(*_grade()).std() > 0.05

    def test_mesmo_ponto_mesmo_valor(self):
        assert np.array_equal(value_noise3(*_grade()), value_noise3(*_grade()))

    def test_curva_suave_achata_no_no_da_grade(self):
        # a curva de Perlin tem derivada zero no no: sair dele um centesimo
        # muda o valor na casa de 1e-5, e nao de 1e-2 como na interpolacao reta
        x = np.arange(0, 40, dtype=np.float32)
        y = np.full_like(x, 4.3)
        z = np.full_like(x, 5.6)
        salto = np.abs(value_noise3(x + 0.01, y, z) - value_noise3(x, y, z))
        assert salto.max() < 2e-5

    def test_continuo_entre_vizinhos(self):
        x = np.linspace(0, 8, 4001, dtype=np.float32)
        v = value_noise3(x, np.full_like(x, 1.3), np.full_like(x, 0.7))
        assert np.abs(np.diff(v)).max() < 0.01

    def test_periodo_de_256(self):
        x, y, z = _grade(50)
        assert value_noise3(x + 256, y, z) == pytest.approx(
            value_noise3(x, y, z), abs=1e-3)

    def test_coordenada_negativa_nao_quebra(self):
        v = value_noise3(np.float32(-1000.5), np.float32(-3.2), np.float32(-7.9))
        assert 0.0 <= float(v) <= 1.0

    def test_formato_acompanha_a_entrada(self):
        x = np.zeros((3, 4), dtype=np.float32)
        assert value_noise3(x, x, x).shape == (3, 4)
        assert value_noise3(x, 0.0, 1.0).dtype == np.float32


class TestOitavas:

    def test_fbm_fica_entre_zero_e_um(self):
        v = fbm3(*_grade(), octaves=5)
        assert v.min() >= 0.0 and v.max() <= 1.0

    def test_fbm_de_uma_oitava_e_o_ruido_puro(self):
        g = _grade()
        assert fbm3(*g, octaves=1) == pytest.approx(value_noise3(*g), abs=1e-6)

    def test_fbm_com_oitava_zero_vira_uma(self):
        g = _grade()
        assert fbm3(*g, octaves=0) == pytest.approx(fbm3(*g, octaves=1), abs=1e-6)

    def test_fbm_soma_ponderada(self):
        g = _grade()
        x, y, z = g
        esperado = (value_noise3(x, y, z) + 0.5 * value_noise3(2 * x, 2 * y, 2 * z)) / 1.5
        assert fbm3(*g, octaves=2) == pytest.approx(esperado, abs=1e-5)

    def test_fbm_ganho_zero_so_a_primeira(self):
        g = _grade()
        assert fbm3(*g, octaves=4, gain=0.0) == pytest.approx(
            value_noise3(*g), abs=1e-6)

    def test_turbulencia_fica_entre_zero_e_um(self):
        v = turbulence3(*_grade(), octaves=5)
        assert v.min() >= 0.0 and v.max() <= 1.0

    def test_turbulencia_de_uma_oitava_dobra_no_meio(self):
        g = _grade()
        esperado = np.abs(value_noise3(*g) - 0.5) * 2.0
        assert turbulence3(*g, octaves=1) == pytest.approx(esperado, abs=1e-6)

    def test_escalar_vira_array(self):
        assert fbm3(0.3, 0.4, 0.5).shape == ()
        assert turbulence3(np.zeros(7), 0.0, 0.0).shape == (7,)


class TestCurl:

    def test_e_perpendicular_ao_gradiente(self):
        x, y, _z = _grade(100)
        t, eps = 2.5, 0.05
        dx = (value_noise3(x + eps, y, t) - value_noise3(x - eps, y, t)) / (2 * eps)
        dy = (value_noise3(x, y + eps, t) - value_noise3(x, y - eps, t)) / (2 * eps)
        ox, oy = curl_offset(x, y, t)
        assert ox * dx + oy * dy == pytest.approx(0.0, abs=1e-3)
        assert ox == pytest.approx(dy, abs=1e-5)
        assert oy == pytest.approx(-dx, abs=1e-5)

    def test_escala_estica_o_campo(self):
        x, y, _z = _grade(50)
        a = curl_offset(x, y, 1.0, scale=2.0, eps=0.05)
        b = curl_offset(2 * x, 2 * y, 1.0, scale=1.0, eps=0.1)
        assert a[0] == pytest.approx(2 * b[0], abs=1e-3)
        assert a[1] == pytest.approx(2 * b[1], abs=1e-3)
