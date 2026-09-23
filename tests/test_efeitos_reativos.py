"""Testes de comportamento dos efeitos que reagem a audio, sensores e tela.

As fontes sao preenchidas a mao no contexto: nada escuta o som da maquina,
le sensor de verdade ou captura a tela.
"""
from __future__ import annotations

import numpy as np
import pytest

from spectra.effects.base import EFFECTS
from spectra.engine import palette as pal
from spectra.engine.context import RenderContext


def pinta(ctx, eid, st, t=0.0, **params):
    p = EFFECTS[eid].defaults()
    p.update(params)
    ctx.t = t
    return EFFECTS[eid].fn(ctx, p, st)


@pytest.fixture
def quadro(canvas):
    return RenderContext(canvas)


class TestVu:

    def test_sobe_pelo_ataque_e_desce_pela_queda(self, quadro):
        st = {}
        quadro.audio.level = 1.0
        pinta(quadro, "audio_vu", st, attack=0.5, release=0.1)
        assert st["lvl"] == pytest.approx(0.5)
        quadro.audio.level = 0.0
        pinta(quadro, "audio_vu", st, attack=0.5, release=0.1)
        assert st["lvl"] == pytest.approx(0.45)

    def test_ganho_satura_em_um(self, quadro):
        st = {}
        quadro.audio.level = 0.5
        pinta(quadro, "audio_vu", st, gain=6.0, attack=1.0)
        assert st["lvl"] == pytest.approx(1.0)

    def test_preenche_ate_o_nivel_e_deixa_o_fundo(self, quadro):
        st = {"lvl": 0.5}
        quadro.audio.level = 0.5
        out = pinta(quadro, "audio_vu", st, attack=1.0, release=1.0,
                    bg="#000000", axis="x")
        cheio = quadro.x <= 0.5
        assert out[cheio].any(axis=1).all()
        assert not out[~cheio].any()

    def test_silencio_fica_so_o_fundo(self, quadro):
        quadro.audio.level = 0.0
        out = pinta(quadro, "audio_vu", {}, bg="#102030")
        fora = quadro.x > 0
        assert out[fora] == pytest.approx(
            np.tile(pal.hex_to_rgb("#102030"), (fora.sum(), 1)))


class TestPulsoDeGrave:

    def test_abaixo_do_limiar_nao_dispara(self, quadro):
        st = {}
        quadro.audio.bass = 0.1
        pinta(quadro, "audio_bass_pulse", st, gain=1.0, threshold=0.25)
        assert st["lvl"] == 0.0

    def test_acima_do_limiar_dispara_e_decai(self, quadro):
        st = {}
        quadro.audio.bass = 0.8
        pinta(quadro, "audio_bass_pulse", st, gain=1.0, threshold=0.25)
        assert st["lvl"] == pytest.approx(0.8)
        quadro.audio.bass = 0.0
        pinta(quadro, "audio_bass_pulse", st, gain=1.0, decay=6.0)
        assert st["lvl"] == pytest.approx(0.8 * np.exp(-6.0 * quadro.dt))

    def test_sem_expandir_pinta_tudo_igual(self, quadro):
        st = {"lvl": 0.0}
        quadro.audio.bass = 1.0
        out = pinta(quadro, "audio_bass_pulse", st, gain=1.0, from_center=False,
                    color="#ffffff", bg="#000000")
        assert out == pytest.approx(1.0)


class TestEspectro:

    def test_suavizacao_mistura_com_o_anterior(self, quadro):
        st = {}
        quadro.audio.bands[:] = 1.0
        pinta(quadro, "audio_spectrum", st, gain=1.0, smooth=0.5)
        assert st["mag"] == pytest.approx(1.0)
        quadro.audio.bands[:] = 0.0
        pinta(quadro, "audio_spectrum", st, gain=1.0, smooth=0.5)
        assert st["mag"] == pytest.approx(0.5)

    def test_silencio_apaga(self, quadro):
        assert not pinta(quadro, "audio_spectrum", {}).any()


class TestOndasNaBatida:

    def test_batida_ocupa_o_anel_mais_velho(self, quadro):
        st = {}
        quadro.audio.beat = 1.0
        pinta(quadro, "audio_ripple", st, max=2, threshold=0.5)
        assert sorted(st["age"].tolist()) == [0.0, pytest.approx(1e9)]
        pinta(quadro, "audio_ripple", st, max=2, threshold=0.5)
        assert (st["age"] < 1.0).all()

    def test_anel_com_menos_de_012_s_nao_e_reciclado(self, quadro):
        st = {}
        quadro.audio.beat = 1.0
        pinta(quadro, "audio_ripple", st, max=2, threshold=0.5)
        pinta(quadro, "audio_ripple", st, max=2, threshold=0.5)
        antes = st["cx"].copy()
        pinta(quadro, "audio_ripple", st, max=2, threshold=0.5)
        assert np.array_equal(st["cx"], antes)
        assert (st["age"] > 0).all()

    def test_sem_batida_nao_ha_anel(self, quadro):
        st = {}
        quadro.audio.beat = 0.0
        out = pinta(quadro, "audio_ripple", st)
        assert not out.any()
        assert (st["age"] > 1e8).all()

    def test_mudar_o_maximo_recomeca(self, quadro):
        st = {}
        pinta(quadro, "audio_ripple", st, max=3)
        pinta(quadro, "audio_ripple", st, max=5)
        assert len(st["age"]) == 5


class TestSensores:

    def test_primeiro_quadro_ja_mostra_o_valor(self, quadro):
        st = {}
        quadro.sensors.cpu_temp = 60.0
        pinta(quadro, "temp_gradient", st, lo=40.0, hi=80.0, smooth=0.9)
        assert st["v"] == pytest.approx(0.5)

    def test_temperatura_suaviza_a_mudanca(self, quadro):
        st = {"v": 0.0}
        quadro.sensors.cpu_temp = 80.0
        pinta(quadro, "temp_gradient", st, lo=40.0, hi=80.0, smooth=0.9)
        assert st["v"] == pytest.approx(0.1)

    def test_cor_sai_da_paleta_pela_leitura(self, quadro):
        quadro.sensors.gpu_temp = 85.0
        out = pinta(quadro, "temp_gradient", {}, sensor="gpu_temp", lo=35.0,
                    hi=85.0, palette="thermal", spread=0.0)
        assert out[0] == pytest.approx(pal.sample_clamped("thermal", np.float32(1.0)))

    def test_barra_de_carga_enche_de_baixo(self, quadro):
        quadro.sensors.cpu_load = 50.0
        out = pinta(quadro, "load_bar", {}, bg="#000000", axis="y")
        baixo = (1.0 - quadro.y) <= 0.5
        assert out[baixo].any(axis=1).all()
        assert not out[~baixo].any()

    def test_alarme_calmo_abaixo_da_faixa(self, quadro):
        quadro.sensors.cpu_temp = 50.0
        out = pinta(quadro, "thermal_alarm", {}, threshold=80.0, window=10.0,
                    ok="#0000ff", alarm="#ff0000")
        assert out == pytest.approx(np.tile([0, 0, 1], (quadro.n, 1)))

    def test_alarme_acima_do_limite_puxa_para_o_vermelho(self, quadro):
        quadro.sensors.cpu_temp = 95.0
        # no pico do seno a pulsacao vale um e a mistura e total
        out = pinta(quadro, "thermal_alarm", {}, t=1 / 12, hz=3.0,
                    threshold=80.0, window=10.0, ok="#0000ff", alarm="#ff0000")
        assert out[0] == pytest.approx([1, 0, 0], abs=1e-4)

    def test_cpu_de_um_lado_e_gpu_do_outro(self, quadro):
        quadro.sensors.cpu_temp = 35.0
        quadro.sensors.gpu_temp = 85.0
        out = pinta(quadro, "dual_sensor", {}, split="x", blend=0.0,
                    palette="thermal")
        frio = pal.sample_clamped("thermal", np.float32(0.0))
        quente = pal.sample_clamped("thermal", np.float32(1.0))
        assert out[quadro.x < 0.45] == pytest.approx(
            np.tile(frio, ((quadro.x < 0.45).sum(), 1)))
        assert out[quadro.x > 0.55] == pytest.approx(
            np.tile(quente, ((quadro.x > 0.55).sum(), 1)))


class TestTela:

    @pytest.fixture
    def tela(self, quadro):
        quadro.screen.image = np.zeros((2, 2, 3), dtype=np.float32)
        quadro.screen.image[:, 0] = (1.0, 0.0, 0.0)
        quadro.screen.image[:, 1] = (0.0, 0.0, 1.0)
        return quadro

    def test_neutro_copia_a_tela(self, tela):
        out = pinta(tela, "ambilight", {}, saturation=1.0, gamma=1.0,
                    smooth=0.0, zoom=1.0)
        assert out == pytest.approx(tela.screen.sample(tela.x, tela.y), abs=1e-6)

    def test_suaviza_entre_quadros(self, tela):
        st = {}
        antes = pinta(tela, "ambilight", st, saturation=1.0, gamma=1.0, smooth=0.5)
        tela.screen.image[:] = 0.0
        out = pinta(tela, "ambilight", st, saturation=1.0, gamma=1.0, smooth=0.5)
        assert antes.any()
        assert out == pytest.approx(antes * 0.5)

    def test_so_bordas_empurra_para_a_margem(self, tela):
        out = pinta(tela, "ambilight", {}, saturation=1.0, gamma=1.0,
                    smooth=0.0, edges=True, edge_depth=0.1)
        meio_esq = (tela.x > 0.3) & (tela.x < 0.5)
        assert meio_esq.any()
        assert (out[meio_esq][:, 0] > 0.8).all()

    def test_media_ou_dominante(self, quadro):
        quadro.screen.average = np.array([0.0, 0.5, 0.0], dtype=np.float32)
        quadro.screen.dominant = np.array([0.5, 0.0, 0.0], dtype=np.float32)
        dom = pinta(quadro, "screen_average", {}, dominant=True,
                    saturation=1.0, boost=1.0)
        med = pinta(quadro, "screen_average", {}, dominant=False,
                    saturation=1.0, boost=1.0)
        assert dom[0] == pytest.approx([0.5, 0.0, 0.0], abs=1e-5)
        assert med[0] == pytest.approx([0.0, 0.5, 0.0], abs=1e-5)

    def test_realce_clareia_ate_o_teto(self, quadro):
        quadro.screen.dominant = np.array([0.8, 0.0, 0.0], dtype=np.float32)
        out = pinta(quadro, "screen_average", {}, saturation=1.0, boost=4.0)
        assert out[0] == pytest.approx([1.0, 0.0, 0.0], abs=1e-5)
