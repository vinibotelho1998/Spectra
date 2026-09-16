from __future__ import annotations

import math

import numpy as np
import pytest

from spectra.engine.canvas import (
    SHAPES,
    Canvas,
    auto_placement,
    device_key,
    shape_cable,
    shape_grid,
    shape_line,
    shape_multi,
    shape_point,
    shape_ring,
    shape_serpentine,
)

from fakes import FakeDevice, FakeZone


class TestDeviceKey:

    def test_usa_o_serial_quando_existe(self):
        a = FakeDevice(0, "Mobo", "Motherboard", [], serial="ABC")
        b = FakeDevice(1, "Mobo", "Motherboard", [], serial="XYZ")
        assert device_key(a) != device_key(b)

    def test_mesmo_serial_gera_a_mesma_chave(self):
        a = FakeDevice(0, "Mobo", "Motherboard", [], serial="ABC")
        b = FakeDevice(9, "Mobo", "Motherboard", [], serial="ABC")
        assert device_key(a) == device_key(b)

    def test_cai_para_location_sem_serial(self):
        d = FakeDevice(0, "Fita", "LED Strip", [], serial=" ", location="USB:3")
        assert device_key(d).startswith("Fita#")

    def test_sem_serial_e_sem_location_usa_so_o_nome(self):
        d = FakeDevice(0, "Fita", "LED Strip", [], serial=" ", location="")
        assert device_key(d) == "Fita"

    def test_nao_vaza_o_serial_em_claro(self):
        d = FakeDevice(0, "Mobo", "Motherboard", [], serial="SEGREDO123")
        assert "SEGREDO123" not in device_key(d)


class TestShapes:

    @pytest.mark.parametrize("nome", sorted(SHAPES))
    @pytest.mark.parametrize("n", [1, 2, 8, 24, 60])
    def test_devolve_um_ponto_por_led(self, nome, n):
        pts = SHAPES[nome](n, {})
        assert pts.shape == (n, 2)
        assert pts.dtype == np.float32
        assert np.isfinite(pts).all()

    @pytest.mark.parametrize("nome", sorted(SHAPES))
    def test_fica_dentro_do_quadro(self, nome):
        pts = SHAPES[nome](32, {})
        assert pts.min() >= -0.05
        assert pts.max() <= 1.05

    def test_point_empilha_todo_mundo_no_mesmo_lugar(self):
        pts = shape_point(5, {"x": 0.3, "y": 0.7})
        assert np.allclose(pts, [[0.3, 0.7]] * 5)

    def test_line_comeca_e_termina_nas_pontas(self):
        pts = shape_line(10, {"x1": 0.0, "y1": 0.2, "x2": 1.0, "y2": 0.2})
        assert pts[0] == pytest.approx([0.0, 0.2], abs=1e-6)
        assert pts[-1] == pytest.approx([1.0, 0.2], abs=1e-6)

    def test_line_espaca_por_igual(self):
        pts = shape_line(11, {"x1": 0.0, "y1": 0.5, "x2": 1.0, "y2": 0.5})
        passos = np.diff(pts[:, 0])
        assert np.allclose(passos, passos[0], atol=1e-6)

    def test_line_com_um_led_fica_no_meio(self):
        pts = shape_line(1, {"x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0})
        assert pts[0] == pytest.approx([0.5, 0.5])

    def test_ring_fica_sobre_o_circulo(self):
        g = {"cx": 0.5, "cy": 0.5, "radius": 0.2}
        pts = shape_ring(12, g)
        d = np.hypot(pts[:, 0] - 0.5, pts[:, 1] - 0.5)
        assert np.allclose(d, 0.2, atol=1e-5)

    def test_ring_completo_nao_repete_o_primeiro_ponto(self):
        pts = shape_ring(12, {"start_deg": 0.0, "end_deg": 360.0})
        assert not np.allclose(pts[0], pts[-1], atol=1e-4)

    def test_ring_distribui_o_angulo_por_igual(self):
        pts = shape_ring(8, {"cx": 0.5, "cy": 0.5, "radius": 0.3})
        ang = np.unwrap(np.arctan2(pts[:, 1] - 0.5, pts[:, 0] - 0.5))
        passos = np.diff(ang)
        assert np.allclose(passos, passos[0], atol=1e-5)

    def test_ring_com_um_led_vira_o_centro(self):
        pts = shape_ring(1, {"cx": 0.4, "cy": 0.6})
        assert pts[0] == pytest.approx([0.4, 0.6])

    def test_grid_preenche_linha_por_linha(self):
        pts = shape_grid(6, {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0,
                             "cols": 3, "rows": 2})
        assert pts[0][1] == pytest.approx(pts[1][1])
        assert pts[3][1] > pts[0][1]

    def test_serpentine_inverte_as_linhas_impares(self):
        g = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "cols": 4, "rows": 2}
        reto = shape_grid(8, g)
        cobra = shape_serpentine(8, g)
        assert np.allclose(cobra[:4], reto[:4])
        assert np.allclose(cobra[4:], reto[4:][::-1])

    def test_cable_separa_as_lanes(self):
        pts = shape_cable(24, {"lanes": 2, "width": 0.4,
                               "x1": 0.0, "y1": 0.5, "x2": 1.0, "y2": 0.5})
        assert not np.allclose(pts[0][1], pts[12][1])

    def test_cable_avanca_ao_longo_do_comprimento(self):
        pts = shape_cable(12, {"lanes": 1, "x1": 0.0, "y1": 0.5,
                               "x2": 1.0, "y2": 0.5})
        assert pts[-1][0] > pts[0][0]

    def test_cable_com_lanes_invalido_nao_divide_por_zero(self):
        pts = shape_cable(10, {"lanes": 0})
        assert np.isfinite(pts).all()

    def test_multi_respeita_a_contagem_de_cada_parte(self):
        g = {"parts": [{"shape": "ring", "count": 12, "radius": 0.1},
                       {"shape": "line", "count": 8}]}
        pts = shape_multi(20, g)
        assert pts.shape == (20, 2)

    def test_multi_completa_o_que_faltar(self):
        pts = shape_multi(20, {"parts": [{"shape": "ring", "count": 12}]})
        assert pts.shape == (20, 2)

    def test_multi_sem_partes_nao_quebra(self):
        assert shape_multi(6, {}).shape == (6, 2)


class TestAutoPlacement:

    def zonas(self, quantas, count=12):
        return [FakeZone(i, "Z%d" % i, count) for i in range(quantas)]

    def test_zonas_irmas_nao_ficam_empilhadas(self):
        dev = FakeDevice(0, "Cooler", "Cooler", self.zonas(3))
        pontos = []
        for zi, z in enumerate(dev.zones):
            g = auto_placement(dev, z, zi, zi, len(dev.zones))
            pontos.append((g.get("cx"), g.get("cy")))
        assert len(set(pontos)) == len(pontos)

    def test_zona_unica_fica_centralizada(self):
        dev = FakeDevice(0, "Cooler", "Cooler", self.zonas(1))
        g = auto_placement(dev, dev.zones[0], 0, 0, 1)
        assert g["cx"] == pytest.approx(0.5, abs=1e-6)

    def test_seis_fans_geram_seis_aneis_distintos(self):
        dev = FakeDevice(0, "Cooler", "Cooler", self.zonas(6))
        cx = [auto_placement(dev, z, i, i, 6)["cx"]
              for i, z in enumerate(dev.zones)]
        assert len(set(cx)) == 6
        assert cx == sorted(cx)

    def test_anel_cabe_dentro_do_quadro(self):
        dev = FakeDevice(0, "Cooler", "Cooler", self.zonas(6))
        for i, z in enumerate(dev.zones):
            g = auto_placement(dev, z, i, i, 6)
            r = g["radius"]
            assert g["cx"] - r >= -1e-6
            assert g["cx"] + r <= 1.0 + 1e-6

    def test_zona_de_um_led_vira_ponto(self):
        dev = FakeDevice(0, "Mouse", "Mouse", [FakeZone(0, "Logo", 1)])
        assert auto_placement(dev, dev.zones[0], 0, 0, 1)["shape"] == "point"

    def test_contagem_de_fan_vira_anel(self):
        dev = FakeDevice(0, "Cooler", "Cooler", [FakeZone(0, "Fan", 12)])
        assert auto_placement(dev, dev.zones[0], 0, 0, 1)["shape"] == "ring"

    def test_contagem_solta_vira_linha(self):
        dev = FakeDevice(0, "Fita", "LED Strip", [FakeZone(0, "Strip", 37)])
        assert auto_placement(dev, dev.zones[0], 0, 0, 1)["shape"] == "line"

    def test_matriz_vira_grid(self):
        z = FakeZone(0, "Tela", 12, matrix_width=4, matrix_height=3)
        dev = FakeDevice(0, "Visor", "Cooler", [z])
        g = auto_placement(dev, z, 0, 0, 1)
        assert g["shape"] == "grid"
        assert (g["cols"], g["rows"]) == (4, 3)

    def test_tipo_desconhecido_nao_quebra(self):
        dev = FakeDevice(0, "Coisa", "Nao Existe", [FakeZone(0, "Z", 30)])
        g = auto_placement(dev, dev.zones[0], 0, 0, 1)
        assert g["shape"] in SHAPES


class TestCanvas:

    def test_conta_todos_os_leds(self, canvas, devices):
        assert canvas.n == sum(d.led_count for d in devices)

    def test_uma_posicao_por_led(self, canvas):
        assert canvas.pos.shape == (canvas.n, 2)

    def test_coordenadas_normalizadas(self, canvas):
        assert canvas.x.min() >= -0.05
        assert canvas.x.max() <= 1.05
        assert canvas.y.min() >= -0.05
        assert canvas.y.max() <= 1.05

    def test_centradas_vao_de_menos_um_a_um(self, canvas):
        assert canvas.cx.min() >= -1.1
        assert canvas.cx.max() <= 1.1

    def test_angulo_normalizado(self, canvas):
        assert canvas.angle01.min() >= 0.0
        assert canvas.angle01.max() <= 1.0

    def test_raio_nunca_negativo(self, canvas):
        assert (canvas.radius >= 0).all()

    def test_tudo_finito(self, canvas):
        for nome in ("x", "y", "cx", "cy", "radius", "theta", "angle01",
                     "strip01", "piece01", "piece_u", "piece_v"):
            assert np.isfinite(getattr(canvas, nome)).all(), nome

    def test_piece_pos_dentro_do_piece_len(self, canvas):
        assert (canvas.piece_pos >= 0).all()
        assert (canvas.piece_pos < canvas.piece_len).all()

    def test_piece01_normalizado(self, canvas):
        assert canvas.piece01.min() >= 0.0
        assert canvas.piece01.max() <= 1.0

    def test_cada_peca_comeca_em_zero_e_termina_em_um(self, canvas):
        for start, count in canvas.pieces:
            if count > 1:
                assert canvas.piece01[start] == pytest.approx(0.0)
                assert canvas.piece01[start + count - 1] == pytest.approx(1.0)

    def test_peca_de_um_led_usa_a_posicao_como_coordenada_local(self, canvas):
        # Sem isso todas as pecas de um LED ficariam com u=0 e v=0.5, com a
        # mesma fase, e os efeitos de peca as fariam piscar juntas fora do
        # compasso do resto do gabinete.
        for start, count in canvas.pieces:
            if count == 1:
                assert canvas.piece_u[start] == pytest.approx(canvas.x[start])
                assert canvas.piece_v[start] == pytest.approx(canvas.y[start])

    def test_pecas_de_um_led_nao_compartilham_fase(self, canvas):
        solos = [start for start, count in canvas.pieces if count == 1]
        assert len(solos) > 1
        assert len({round(float(canvas.piece_u[s]), 4) for s in solos}) > 1

    def test_pecas_cobrem_o_canvas_inteiro(self, canvas):
        assert sum(c for _s, c in canvas.pieces) == canvas.n

    def test_pecas_nao_se_sobrepoem(self, canvas):
        marcado = np.zeros(canvas.n, dtype=int)
        for start, count in canvas.pieces:
            marcado[start:start + count] += 1
        assert (marcado == 1).all()

    def test_fan_e_fita_sao_exclusivos(self, canvas):
        assert not (canvas.is_strip & canvas.is_fan).any()

    def test_fans_marcados_como_fan(self, devices):
        cv = Canvas(devices)
        assert cv.is_fan.sum() > 0

    def test_slices_batem_com_os_dispositivos(self, canvas):
        total = sum(c for _i, _s, c in canvas.slices)
        assert total == canvas.n

    def test_dispositivo_sem_led_e_ignorado(self):
        devs = [FakeDevice(0, "Vazio", "Motherboard", []),
                FakeDevice(1, "Fita", "LED Strip", [FakeZone(0, "S", 10)])]
        cv = Canvas(devs)
        assert cv.n == 10
        assert [d.name for d in cv.devices] == ["Fita"]

    def test_dispositivo_desligado_some_do_canvas(self, devices):
        chave = device_key(devices[1])
        cv = Canvas(devices, enabled={chave: False})
        assert cv.n == sum(d.led_count for d in devices) - devices[1].led_count

    def test_canvas_vazio_nao_quebra(self):
        cv = Canvas([])
        assert cv.n == 0
        assert cv.pos.shape == (0, 2)
        assert cv.piece_count == 0

    def test_config_manual_vence_o_automatico(self, devices):
        chave = device_key(devices[1])
        cfg = {chave: {"zones": {"0": {"shape": "point", "x": 0.11, "y": 0.22}}}}
        cv = Canvas(devices, config=cfg)
        zi = next(z for z in cv.zone_info if z["device_key"] == chave)
        pts = cv.pos[zi["start"]:zi["start"] + zi["count"]]
        assert np.allclose(pts, [[0.11, 0.22]] * zi["count"])

    def test_reverse_inverte_a_zona(self, devices):
        chave = device_key(devices[1])
        base = {"shape": "line", "x1": 0.0, "y1": 0.5, "x2": 1.0, "y2": 0.5}
        reto = Canvas(devices, config={chave: {"zones": {"0": dict(base)}}})
        virado = Canvas(devices, config={
            chave: {"zones": {"0": dict(base, reverse=True)}}})
        zi = next(z for z in reto.zone_info if z["device_key"] == chave)
        a = reto.pos[zi["start"]:zi["start"] + zi["count"]]
        b = virado.pos[zi["start"]:zi["start"] + zi["count"]]
        assert np.allclose(a, b[::-1])

    def test_zone_info_aponta_para_o_trecho_certo(self, canvas):
        for z in canvas.zone_info:
            assert z["start"] + z["count"] <= canvas.n

    def test_to_json_serializavel(self, canvas):
        import json
        d = canvas.to_json()
        assert d["led_count"] == canvas.n
        assert len(d["positions"]) == canvas.n
        json.dumps(d)

    def test_mesmo_layout_gera_o_mesmo_canvas(self, devices):
        a = Canvas(devices)
        b = Canvas(devices)
        assert np.array_equal(a.pos, b.pos)
        assert a.pieces == b.pieces
