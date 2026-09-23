"""Testes do protocolo do teclado Akko.

Nao tocam em hardware: exercitam so a montagem dos relatorios, que e onde
um erro passaria despercebido ate alguem olhar o teclado.
"""
from __future__ import annotations

import types

import pytest

akko = pytest.importorskip("spectra.core.akko",
                           reason="modulo so existe no Windows")


def soma_confere(pacote, fim):
    """O checksum e 0xFF menos a soma dos bytes anteriores."""
    return pacote[fim] == (0xFF - (sum(pacote[:fim]) & 0xFF)) & 0xFF


class TestCorUnica:

    def test_tamanho_do_relatorio(self):
        p = akko.monta(akko.EFEITO_COR_FIXA, akko.MODO_COR_UNICA,
                       4, 8, 255, 255, 255)
        assert len(p) == 64

    def test_campos_na_ordem_certa(self):
        p = akko.monta(akko.EFEITO_COR_FIXA, akko.MODO_COR_UNICA,
                       4, 8, 0x12, 0x34, 0x56)
        assert p[0] == akko.CMD_LUZ
        assert p[1] == akko.EFEITO_COR_FIXA
        assert p[2] == akko.MODO_COR_UNICA
        assert p[3] == 4
        assert (p[5], p[6], p[7]) == (0x12, 0x34, 0x56)

    def test_checksum(self):
        p = akko.monta(akko.EFEITO_COR_FIXA, akko.MODO_COR_UNICA,
                       4, 8, 255, 255, 255)
        assert soma_confere(p, 8)

    def test_bate_com_o_capturado_do_driver_oficial(self):
        # Quadro que o driver da Akko manda para branco, observado na rede
        # HID: serve de ancora para qualquer mexida futura no formato.
        p = akko.monta(akko.EFEITO_COR_FIXA, akko.MODO_COR_UNICA,
                       4, 8, 255, 255, 255)
        assert list(p[:9]) == [0x07, 0x01, 0x04, 0x04, 0x08,
                               0xFF, 0xFF, 0xFF, 0xEA]


class TestCamada:

    def test_sete_pacotes(self):
        ps = akko.pacotes_camada({})
        assert len(ps) == 7

    def test_tamanhos_e_marcador_de_fim(self):
        ps = akko.pacotes_camada({})
        assert [p[4] for p in ps] == [56, 56, 56, 56, 56, 56, 42]
        assert [p[5] for p in ps] == [0, 0, 0, 0, 0, 0, 1]

    def test_cobre_os_126_leds(self):
        ps = akko.pacotes_camada({})
        assert sum(p[4] for p in ps) == akko.LEDS * 3

    def test_indices_em_ordem(self):
        ps = akko.pacotes_camada({})
        assert [p[3] for p in ps] == list(range(7))

    def test_checksum_de_cada_pacote(self):
        for p in akko.pacotes_camada({akko.TECLAS["w"]: (255, 0, 0)}):
            assert soma_confere(p, 7)

    def test_cor_cai_no_lugar_certo(self):
        ps = akko.pacotes_camada({akko.TECLAS["w"]: (0x11, 0x22, 0x33)})
        dados = b"".join(p[8:8 + p[4]] for p in ps)
        i = akko.TECLAS["w"] * 3
        assert dados[i:i + 3] == bytes([0x11, 0x22, 0x33])

    def test_resto_fica_apagado(self):
        ps = akko.pacotes_camada({akko.TECLAS["w"]: (255, 255, 255)})
        dados = b"".join(p[8:8 + p[4]] for p in ps)
        acesos = [i for i in range(akko.LEDS)
                  if dados[i * 3:i * 3 + 3] != b"\x00\x00\x00"]
        assert acesos == [akko.TECLAS["w"]]

    def test_todos_os_pacotes_tem_64_bytes(self):
        assert all(len(p) == 64 for p in akko.pacotes_camada({}))


class TestMatriz:

    def test_indice_anda_pela_coluna(self):
        # W em cima de S, na mesma coluna, sao vizinhos no indice
        assert akko.TECLAS["s"] - akko.TECLAS["w"] == 1

    def test_formula_bate_com_as_teclas_conhecidas(self):
        assert akko.indice(0, 0) == akko.TECLAS["esc"]
        assert akko.indice(2, 2) == akko.TECLAS["w"]
        assert akko.indice(2, 3) == akko.TECLAS["s"]
        assert akko.indice(3, 3) == akko.TECLAS["d"]
        assert akko.indice(13, 4) == akko.TECLAS["seta_cima"]
        assert akko.indice(13, 5) == akko.TECLAS["seta_baixo"]

    def test_matriz_fecha_nos_126(self):
        assert akko.LINHAS * akko.COLUNAS == akko.LEDS == 126


class TestQueda:
    """Teclado que sai do USB, com as chamadas do Windows trocadas por falsas."""

    def _teclado(self, monkeypatch, respostas):
        fechados = []
        it = iter(respostas)
        monkeypatch.setattr(akko, "_hid", types.SimpleNamespace(
            HidD_SetFeature=lambda h, buf, n: next(it)))
        monkeypatch.setattr(akko, "_k32", types.SimpleNamespace(
            CloseHandle=fechados.append))
        k = akko.AkkoKeyboard()
        k._h, k.tamanho, k.caminho = 77, 65, "hid#akko"
        return k, fechados

    def test_envio_falhando_seguido_fecha_o_handle(self, monkeypatch):
        k, fechados = self._teclado(monkeypatch, [0] * 100)
        for _ in range(100):
            k._envia(bytes(64))
        assert k.conectado is False
        assert fechados == [77]
        assert k.erro

    def test_falha_isolada_nao_derruba(self, monkeypatch):
        k, fechados = self._teclado(monkeypatch, [0, 1] * 100)
        for _ in range(200):
            k._envia(bytes(64))
        assert k.conectado is True
        assert fechados == []

    def test_ao_fechar_esquece_o_modo_de_fluxo(self, monkeypatch):
        # o aparelho reaberto pode ter sido religado e estar no efeito salvo
        k, _ = self._teclado(monkeypatch, [])
        k._modo = akko.EFEITO_SINCRONIA_TELA
        k.fechar()
        assert k._modo is None
        assert k.conectado is False
