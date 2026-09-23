from __future__ import annotations

import re

import numpy as np
import pytest

from spectra.engine.palette import (
    PALETTE_LABELS,
    PALETTES,
    get_lut,
    hex_to_rgb,
    hsv_to_rgb,
    palette_preview,
    rgb_to_hex,
    rgb_to_hsv,
    sample,
    sample_clamped,
)

HEX = re.compile(r"^#[0-9a-f]{6}$")


class TestHex:

    def test_converte_as_primarias(self):
        assert hex_to_rgb("#ff0000") == pytest.approx((1.0, 0.0, 0.0))
        assert hex_to_rgb("#00ff00") == pytest.approx((0.0, 1.0, 0.0))
        assert hex_to_rgb("#0000ff") == pytest.approx((0.0, 0.0, 1.0))

    def test_aceita_forma_curta(self):
        assert hex_to_rgb("#f00") == pytest.approx(hex_to_rgb("#ff0000"))

    def test_aceita_sem_cerquilha_e_com_espaco(self):
        assert hex_to_rgb("  ff8800 ") == pytest.approx(hex_to_rgb("#ff8800"))

    def test_ida_e_volta(self):
        for s in ("#000000", "#ffffff", "#123456", "#ff2d55"):
            assert rgb_to_hex(hex_to_rgb(s)) == s

    def test_saida_sempre_no_formato_canonico(self):
        assert HEX.match(rgb_to_hex((0.5, 0.25, 0.75)))

    def test_satura_fora_da_faixa(self):
        assert rgb_to_hex((-1.0, 0.5, 2.0)) == "#0080ff"


class TestHsv:

    def test_matiz_zero_e_vermelho(self):
        assert hsv_to_rgb(0.0, 1.0, 1.0) == pytest.approx([1.0, 0.0, 0.0])

    def test_um_terco_e_verde(self):
        assert hsv_to_rgb(1 / 3, 1.0, 1.0) == pytest.approx([0.0, 1.0, 0.0], abs=1e-6)

    def test_dois_tercos_e_azul(self):
        assert hsv_to_rgb(2 / 3, 1.0, 1.0) == pytest.approx([0.0, 0.0, 1.0], abs=1e-6)

    def test_saturacao_zero_vira_cinza(self):
        c = hsv_to_rgb(0.42, 0.0, 0.6)
        assert c[0] == pytest.approx(c[1]) == pytest.approx(c[2])

    def test_valor_zero_vira_preto(self):
        assert hsv_to_rgb(0.5, 1.0, 0.0) == pytest.approx([0.0, 0.0, 0.0])

    def test_matiz_da_volta(self):
        assert hsv_to_rgb(1.25, 1.0, 1.0) == pytest.approx(hsv_to_rgb(0.25, 1.0, 1.0))

    def test_vetorizado_mantem_o_formato(self):
        h = np.linspace(0, 1, 32, dtype=np.float32)
        out = hsv_to_rgb(h, 1.0, 1.0)
        assert out.shape == (32, 3)
        assert out.dtype == np.float32

    def test_ida_e_volta_preserva_o_matiz(self):
        h = np.linspace(0.02, 0.98, 25, dtype=np.float32)
        rgb = hsv_to_rgb(h, 1.0, 1.0)
        h2, s2, v2 = rgb_to_hsv(rgb)
        assert h2 == pytest.approx(h, abs=1e-4)
        assert s2 == pytest.approx(np.ones_like(h), abs=1e-5)
        assert v2 == pytest.approx(np.ones_like(h), abs=1e-5)

    def test_fica_sempre_entre_zero_e_um(self):
        h = np.linspace(-2, 3, 200, dtype=np.float32)
        out = hsv_to_rgb(h, 0.8, 0.9)
        assert out.min() >= 0.0
        assert out.max() <= 1.0


class TestPaletas:

    def test_o_catalogo_nao_esta_vazio(self):
        assert len(PALETTES) >= 8

    @pytest.mark.parametrize("nome", sorted(PALETTES))
    def test_toda_paleta_tem_rotulo_para_a_interface(self, nome):
        # sem rotulo a tela mostrava o nome interno, como "mono_red"
        assert PALETTE_LABELS.get(nome, "").strip()

    @pytest.mark.parametrize("nome", sorted(PALETTES))
    def test_toda_parada_e_hex_valido(self, nome):
        for stop in PALETTES[nome]:
            assert HEX.match(stop), "%s tem parada invalida %r" % (nome, stop)

    @pytest.mark.parametrize("nome", sorted(PALETTES))
    def test_toda_paleta_tem_pelo_menos_duas_paradas(self, nome):
        assert len(PALETTES[nome]) >= 2

    @pytest.mark.parametrize("nome", sorted(PALETTES))
    def test_lut_no_intervalo(self, nome):
        lut = get_lut(nome)
        assert lut.ndim == 2 and lut.shape[1] == 3
        assert lut.min() >= 0.0
        assert lut.max() <= 1.0
        assert np.isfinite(lut).all()

    def test_nome_desconhecido_cai_no_rainbow(self):
        assert np.array_equal(get_lut("nao existe"), get_lut("rainbow"))

    def test_lista_vazia_cai_no_rainbow(self):
        assert np.array_equal(get_lut([]), get_lut("rainbow"))

    def test_cache_devolve_o_mesmo_objeto(self):
        assert get_lut("fire") is get_lut("fire")

    def test_paradas_avulsas_viram_paleta(self):
        lut = get_lut(["#000000", "#ffffff"])
        assert lut[0] == pytest.approx([0, 0, 0], abs=1e-3)
        assert lut[-1] == pytest.approx([1, 1, 1], abs=1e-3)

    def test_uma_parada_so_vira_cor_chapada(self):
        lut = get_lut(["#ff0000"])
        assert np.allclose(lut, lut[0])

    def test_cache_nao_cresce_sem_teto(self):
        # arrastar o seletor de cor gera uma lista nova a cada passo
        from spectra.engine import palette as pal
        try:
            for i in range(1000):
                get_lut(["#%06x" % i, "#000000"])
            assert len(pal._CACHE) <= 256
            assert get_lut(["#0003e7", "#000000"])[0] == pytest.approx(
                hex_to_rgb("#0003e7"), abs=1e-3)
        finally:
            pal._CACHE.clear()


class TestSample:

    def test_formato_acompanha_a_entrada(self):
        out = sample("rainbow", np.linspace(0, 1, 17))
        assert out.shape == (17, 3)
        assert out.dtype == np.float32

    def test_escalar_devolve_uma_cor(self):
        assert sample("fire", 0.5).shape == (3,)

    def test_sempre_dentro_do_intervalo(self):
        t = np.linspace(-3, 4, 300)
        for nome in PALETTES:
            out = sample(nome, t)
            assert out.min() >= 0.0 and out.max() <= 1.0, nome

    def test_da_a_volta_no_ciclo(self):
        assert sample("rainbow", 0.25) == pytest.approx(sample("rainbow", 1.25), abs=1e-5)

    def test_clamped_nao_da_a_volta(self):
        assert sample_clamped("fire", 2.0) == pytest.approx(sample_clamped("fire", 1.0))
        assert sample_clamped("fire", -1.0) == pytest.approx(sample_clamped("fire", 0.0))

    def test_clamped_bate_com_as_pontas_da_paleta(self):
        assert sample_clamped("ice", 0.0) == pytest.approx(
            np.array(hex_to_rgb(PALETTES["ice"][0])), abs=1e-3)

    def test_preview_devolve_hex(self):
        cores = palette_preview("aurora", 12)
        assert len(cores) == 12
        assert all(HEX.match(c) for c in cores)
