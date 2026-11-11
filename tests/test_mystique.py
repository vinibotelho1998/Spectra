"""Anel do water cooler pelo servico do visor, sem cooler nem servico."""

from __future__ import annotations

import json
import os

from spectra.core import mystique


def _publica(pasta, **campos):
    pasta.mkdir(parents=True, exist_ok=True)
    dados = {"connected": True, "led": "temperature", "updated": 1000, "cpuTemp": 55.0}
    dados.update(campos)
    (pasta / "status.json").write_text(json.dumps(dados), encoding="utf-8")


def _controle(pasta):
    return json.loads((pasta / "control.json").read_text(encoding="utf-8"))


class TestEstado:

    def test_sem_servico_nao_ha_cartao(self, cooler_isolado):
        assert mystique.estado(agora=1000) is None

    def test_servico_no_ar_e_anel_na_temperatura(self, cooler_isolado):
        _publica(cooler_isolado)
        assert mystique.estado(agora=1005) == {
            "name": "DeepCool Mystique", "rodando": True, "conectado": True,
            "led": "temperature", "segue": False}

    def test_anel_no_conector_segue_o_spectra(self, cooler_isolado):
        _publica(cooler_isolado, led="motherboard")
        assert mystique.estado(agora=1005)["segue"] is True

    def test_estado_velho_e_servico_parado(self, cooler_isolado):
        _publica(cooler_isolado)
        e = mystique.estado(agora=1000 + mystique.VALIDADE_ESTADO + 1)
        assert (e["rodando"], e["conectado"]) == (False, False)

    def test_cooler_desconectado_com_servico_no_ar(self, cooler_isolado):
        _publica(cooler_isolado, connected=False)
        e = mystique.estado(agora=1001)
        assert (e["rodando"], e["conectado"]) == (True, False)

    def test_arquivo_ilegivel_ou_modo_estranho(self, cooler_isolado):
        cooler_isolado.mkdir(parents=True)
        (cooler_isolado / "status.json").write_text("{", encoding="utf-8")
        assert mystique.estado(agora=1000) is None
        _publica(cooler_isolado, led="arco-iris", updated="x")
        e = mystique.estado(agora=1000)
        assert (e["led"], e["segue"], e["rodando"]) == (None, False, False)


class TestDefinirAnel:

    def test_cria_o_controle_so_com_o_anel(self, cooler_isolado):
        assert mystique.definir_anel(True) == {"ok": True, "led": "motherboard"}
        assert _controle(cooler_isolado) == {"led": "motherboard"}

    def test_mantem_as_outras_chaves_do_visor(self, cooler_isolado):
        cooler_isolado.mkdir(parents=True)
        (cooler_isolado / "control.json").write_text(
            json.dumps({"rotation": 270, "brightness": 50, "led": "motherboard"}),
            encoding="utf-8")
        assert mystique.definir_anel(False)["led"] == "temperature"
        assert _controle(cooler_isolado) == {
            "rotation": 270, "brightness": 50, "led": "temperature"}

    def test_controle_ilegivel_fica_como_esta(self, cooler_isolado):
        cooler_isolado.mkdir(parents=True)
        (cooler_isolado / "control.json").write_text("[1, 2", encoding="utf-8")
        assert mystique.definir_anel(True)["ok"] is False
        assert (cooler_isolado / "control.json").read_text(encoding="utf-8") == "[1, 2"

    def test_controle_que_nao_e_objeto_fica_como_esta(self, cooler_isolado):
        cooler_isolado.mkdir(parents=True)
        (cooler_isolado / "control.json").write_text("[1]", encoding="utf-8")
        assert mystique.definir_anel(True)["ok"] is False

    def test_nao_deixa_arquivo_temporario(self, cooler_isolado):
        mystique.definir_anel(True)
        mystique.definir_anel(False)
        assert sorted(os.listdir(cooler_isolado)) == ["control.json"]
