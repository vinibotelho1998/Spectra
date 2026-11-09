"""Testes do protocolo do teclado Akko.

Nao tocam em hardware: exercitam so a montagem dos relatorios, que e onde
um erro passaria despercebido ate alguem olhar o teclado.
"""
from __future__ import annotations

import types

import pytest

akko = pytest.importorskip("spectra.core.akko")


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


@pytest.fixture(autouse=True)
def backend_windows_para_testes_existentes(monkeypatch, request):
    if request.cls and request.cls.__name__ in {"TestQueda", "TestEnvio", "TestAbrir"}:
        monkeypatch.setattr(akko, "_WINDOWS", True)
        monkeypatch.setattr(akko.ctypes, "get_last_error", lambda: 5, raising=False)


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


class Relogio:
    """Relogio parado que so anda quando o teste manda."""

    def __init__(self):
        self.agora = 100.0

    def monotonic(self):
        return self.agora

    def sleep(self, s):
        self.agora += s


class TestEnvio:
    """O que sai para o teclado, com o HID trocado por um que so anota."""

    @pytest.fixture
    def kb(self, monkeypatch):
        enviados = []
        falhas = []

        def set_feature(h, buf, n):
            assert n == 65
            dados = bytes(buf.raw)
            assert dados[0] == 0
            enviados.append(dados[1:])
            return 0 if falhas and falhas.pop(0) else 1

        relogio = Relogio()
        monkeypatch.setattr(akko, "_hid", types.SimpleNamespace(
            HidD_SetFeature=set_feature))
        monkeypatch.setattr(akko, "_k32", types.SimpleNamespace(
            CloseHandle=lambda h: None))
        monkeypatch.setattr(akko, "time", relogio)
        k = akko.AkkoKeyboard()
        k._h, k.tamanho, k.caminho = 77, 65, "hid#akko"
        k.enviados, k.falhas, k.relogio = enviados, falhas, relogio
        return k

    def test_cor_fixa_vai_no_relatorio_do_driver(self, kb):
        assert kb.set_cor(10, 20, 30, brilho=2) is True
        assert kb.enviados == [akko.monta(akko.EFEITO_COR_FIXA,
                                          akko.MODO_COR_UNICA, 2, 8, 10, 20, 30)]

    def test_cor_logo_em_seguida_e_segurada(self, kb):
        kb.set_cor(10, 20, 30)
        kb.relogio.agora += akko.INTERVALO_MIN / 2
        assert kb.set_cor(200, 20, 30) is False
        assert len(kb.enviados) == 1

    def test_cor_que_mal_mudou_nao_regrava(self, kb):
        kb.set_cor(10, 20, 30)
        kb.relogio.agora += 1.0
        assert kb.set_cor(11, 21, 31) is False
        assert kb.set_cor(10 + akko.DELTA_MIN, 20, 30) is True
        assert len(kb.enviados) == 2

    def test_so_o_brilho_mudando_tambem_vai(self, kb):
        # o tom vai normalizado: a cena que so escurece muda so o brilho
        kb.set_cor(255, 0, 0, brilho=4)
        kb.relogio.agora += 1.0
        assert kb.set_cor(255, 0, 0, brilho=2) is True
        assert kb.enviados[-1][3] == 2

    def test_brilho_fora_da_escala_e_limitado(self, kb):
        kb.set_cor(1, 2, 3, brilho=9)
        kb.set_cor(1, 2, 3, brilho=-3, forcar=True)
        assert [p[3] for p in kb.enviados] == [akko.BRILHO_MAX, 0]

    def test_apagar_passa_por_cima_da_espera(self, kb):
        kb.set_cor(255, 255, 255)
        assert kb.apagar() is True
        assert kb.enviados[-1][5:8] == b"\x00\x00\x00"

    def test_sem_handle_nada_sai(self, kb):
        kb._h = None
        assert kb.set_cor(1, 2, 3, forcar=True) is False
        assert kb.cor_em_fluxo(1, 2, 3) is False
        assert kb.set_camada({}) is False
        assert kb.enviados == []

    def test_fluxo_entra_no_modo_de_sincronia_uma_vez(self, kb):
        assert kb.cor_em_fluxo(1, 2, 3) is True
        kb.relogio.agora += 1.0
        assert kb.cor_em_fluxo(4, 5, 6) is True
        assert kb.enviados == [
            akko.monta(akko.EFEITO_SINCRONIA_TELA, akko.MODO_COR_UNICA,
                       akko.BRILHO_MAX, 0, 255, 255, 255),
            akko.monta_cor_tela(1, 2, 3),
            akko.monta_cor_tela(4, 5, 6),
        ]

    def test_fluxo_respeita_a_taxa_do_firmware(self, kb):
        kb.cor_em_fluxo(1, 2, 3)
        kb.relogio.agora += 1.0
        kb.cor_em_fluxo(1, 2, 3)
        kb.relogio.agora += 0.5 / akko.FLUXO_HZ
        assert kb.cor_em_fluxo(9, 9, 9) is False
        kb.relogio.agora += 1.0 / akko.FLUXO_HZ
        assert kb.cor_em_fluxo(9, 9, 9) is True
        assert kb.enviados[-1] == akko.monta_cor_tela(9, 9, 9)

    def test_modo_recusado_nao_manda_a_cor_e_tenta_de_novo(self, kb):
        kb.falhas.append(True)
        assert kb.cor_em_fluxo(1, 2, 3) is False
        assert len(kb.enviados) == 1
        kb.relogio.agora += 1.0
        assert kb.cor_em_fluxo(1, 2, 3) is True
        assert kb.enviados[1][1] == akko.EFEITO_SINCRONIA_TELA

    def test_cor_fixa_depois_do_fluxo_volta_a_pedir_o_modo(self, kb):
        kb.cor_em_fluxo(1, 2, 3)
        kb.set_cor(9, 9, 9, forcar=True)
        kb.relogio.agora += 1.0
        kb.cor_em_fluxo(1, 2, 3)
        assert kb.enviados[-2][1] == akko.EFEITO_SINCRONIA_TELA

    def test_camada_liga_o_efeito_personalizado_antes_dos_dados(self, kb):
        assert kb.set_camada({akko.TECLAS["w"]: (255, 0, 0)}) is True
        assert kb.enviados[0][:2] == bytes([akko.CMD_LUZ, akko.EFEITO_PERSONALIZADO])
        assert kb.enviados[1:] == akko.pacotes_camada({akko.TECLAS["w"]: (255, 0, 0)})
        kb.set_camada({})
        assert len(kb.enviados) == 1 + 7 + 7

    def test_camada_que_falha_no_meio_devolve_falso(self, kb):
        kb.set_camada({})
        kb.falhas.extend([False, False, True])
        assert kb.set_camada({}) is False
        assert len(kb.enviados) == 1 + 7 + 3


class TestCorEmFluxo:

    def test_relatorio_do_modo_de_tela(self):
        p = akko.monta_cor_tela(0x12, 0x34, 0x56)
        assert len(p) == 64
        assert list(p[:4]) == [akko.CMD_COR_TELA, 0x12, 0x34, 0x56]
        assert soma_confere(p, 7)
        assert not any(p[8:])

    def test_valor_fora_do_byte_nao_estoura(self):
        p = akko.monta_cor_tela(256 + 7, -1, 255.9)
        assert list(p[1:4]) == [7, 255, 255]


class TestAbrir:

    def _com(self, monkeypatch, achado, handle=55):
        abertos = []

        def create(caminho, *a):
            abertos.append(caminho)
            return handle

        monkeypatch.setattr(akko, "_procura", achado)
        monkeypatch.setattr(akko, "_k32", types.SimpleNamespace(
            CreateFileW=create, CloseHandle=lambda h: None))
        return abertos

    def test_acha_e_abre_a_interface_de_configuracao(self, monkeypatch):
        abertos = self._com(monkeypatch, lambda: ("hid#vid_3151", 65))
        k = akko.AkkoKeyboard()
        assert k.abrir() is True
        assert (k.caminho, k.tamanho, k.conectado) == ("hid#vid_3151", 65, True)
        assert abertos == ["hid#vid_3151"]
        assert k.to_json()["connected"] is True

    def test_ja_aberto_nao_procura_de_novo(self, monkeypatch):
        chamadas = []
        self._com(monkeypatch, lambda: chamadas.append(1) or ("hid#x", 65))
        k = akko.AkkoKeyboard()
        k.abrir()
        k.abrir()
        assert chamadas == [1]

    def test_sem_teclado_diz_que_nao_achou(self, monkeypatch):
        abertos = self._com(monkeypatch, lambda: (None, 0))
        k = akko.AkkoKeyboard()
        assert k.abrir() is False
        assert "nao encontrado" in k.erro
        assert abertos == []
        assert k.to_json()["connected"] is False

    def test_interface_trancada_por_outro_programa(self, monkeypatch):
        self._com(monkeypatch, lambda: ("hid#x", 65), handle=akko.INVALIDO)
        k = akko.AkkoKeyboard()
        assert k.abrir() is False
        assert "sem acesso" in k.erro
        assert k.conectado is False

    def test_erro_do_windows_na_procura_nao_escapa(self, monkeypatch):
        def quebra():
            raise OSError("SetupDi falhou")

        self._com(monkeypatch, quebra)
        k = akko.AkkoKeyboard()
        assert k.abrir() is False
        assert "SetupDi" in k.erro


class TestLinuxHid:
    def test_abre_somente_interface_vendor_e_envia_feature_report(self, monkeypatch):
        import sys
        reports = []
        closed = []
        class Device:
            def open_path(self, path):
                assert path == b"/dev/hidraw9"
            def send_feature_report(self, data):
                reports.append(data)
                return len(data)
            def close(self):
                closed.append(True)
        hid = types.SimpleNamespace(
            enumerate=lambda vid, pid: [
                {"usage_page": 1, "usage": 6, "path": b"/dev/hidraw8"},
                {"usage_page": 0xffff, "usage": 2, "path": b"/dev/hidraw9"}],
            device=Device)
        monkeypatch.setitem(sys.modules, "hidraw", hid)
        monkeypatch.setattr(akko, "_WINDOWS", False)
        kb = akko.AkkoKeyboard()
        assert kb.abrir()
        assert kb.to_json()["path"] == "/dev/hidraw9"
        assert kb.set_cor(1, 2, 3)
        assert reports == [b"\x00" + akko.monta(1, 4, 4, 8, 1, 2, 3)]
        kb.fechar()
        assert closed == [True]

    def test_sem_permissao_retorna_erro(self, monkeypatch):
        import sys
        class Device:
            def open_path(self, path):
                raise OSError("permission denied")
            def close(self):
                pass
        monkeypatch.setitem(sys.modules, "hidraw", types.SimpleNamespace(
            enumerate=lambda *args: [{"usage_page": 0xffff, "usage": 2, "path": b"x"}],
            device=Device))
        monkeypatch.setattr(akko, "_WINDOWS", False)
        kb = akko.AkkoKeyboard()
        assert not kb.abrir()
        assert "permission denied" in kb.erro

    def test_interface_sem_descritor_nao_e_aberta(self, monkeypatch):
        import sys
        monkeypatch.setattr(akko, "_WINDOWS", False)
        monkeypatch.setitem(sys.modules, "hidraw", types.SimpleNamespace(
            enumerate=lambda *args: [{"usage_page": 0, "usage": 0, "path": b"x"}],
            device=lambda: pytest.fail("colecao nao identificada nao deve ser aberta")))
        kb = akko.AkkoKeyboard()
        assert not kb.abrir()
        assert "permissoes hidraw" in kb.erro

    def test_envio_curto_e_desconexao_permite_reconectar(self, monkeypatch):
        import sys
        monkeypatch.setattr(akko, "_WINDOWS", False)
        handles = []
        class Device:
            def __init__(self):
                self.closed = False
                handles.append(self)
            def open_path(self, path):
                pass
            def send_feature_report(self, data):
                return 0 if len(handles) == 1 else len(data)
            def close(self):
                self.closed = True
        monkeypatch.setitem(sys.modules, "hidraw", types.SimpleNamespace(
            enumerate=lambda *args: [{"usage_page": akko.USAGE_PAGE,
                                      "usage": akko.USAGE, "path": b"x"}],
            device=Device))
        kb = akko.AkkoKeyboard()
        assert kb.abrir()
        for _ in range(akko.FALHAS_MAX):
            assert not kb._envia(bytes(64))
        assert not kb.conectado and handles[0].closed
        assert kb.abrir()
        assert kb._envia(bytes(64))
        kb.fechar()
        assert handles[1].closed

    def test_fecha_handle_se_abertura_falha(self, monkeypatch):
        import sys
        monkeypatch.setattr(akko, "_WINDOWS", False)
        closed = []
        class Device:
            def open_path(self, path):
                raise OSError("dispositivo removido")
            def close(self):
                closed.append(True)
        monkeypatch.setitem(sys.modules, "hidraw", types.SimpleNamespace(
            enumerate=lambda *args: [{"usage_page": akko.USAGE_PAGE,
                                      "usage": akko.USAGE, "path": b"x"}],
            device=Device))
        kb = akko.AkkoKeyboard()
        assert not kb.abrir()
        assert closed == [True]
