"""Testes do caminho elevado do servidor OpenRGB.

Nada aqui cria tarefa, consulta o agendador ou derruba processo de verdade:
`subprocess.run`, a elevacao e a leitura de token sao trocados por falsos
que so anotam o que seria pedido ao Windows.
"""
from __future__ import annotations

import types
import xml.etree.ElementTree as ET

import pytest

admin = pytest.importorskip("spectra.core.admin",
                            reason="modulo so existe no Windows")

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


def _windows_falso(monkeypatch, codigo=0, erro=None, saida=""):
    """Troca o subprocess.run por um que devolve o codigo pedido."""
    pedidos = []

    def run(args, **kw):
        pedidos.append(list(args))
        if erro:
            raise erro
        return types.SimpleNamespace(returncode=codigo, stdout=saida)

    monkeypatch.setattr(admin.subprocess, "run", run)
    return pedidos


class TestTarefaAgendada:

    @pytest.fixture
    def elevacao(self, monkeypatch, tmp_path):
        """Elevacao falsa que guarda o XML que o schtasks receberia."""
        visto = {}
        monkeypatch.setattr(admin.tempfile, "gettempdir", lambda: str(tmp_path))
        monkeypatch.setenv("USERNAME", "ana")
        monkeypatch.setenv("USERDOMAIN", "CASA")
        monkeypatch.setattr(admin, "tarefa_existe", lambda nome: True)

        def executar(exe, args, espera=60.0):
            visto["exe"], visto["args"] = exe, args
            caminho = args[args.index("/xml") + 1]
            with open(caminho, "rb") as f:
                visto["xml"] = f.read()
            return visto.get("resposta", "ok")

        monkeypatch.setattr(admin, "executar_elevado", executar)
        return visto

    def _campo(self, xml, caminho):
        raiz = ET.fromstring(xml)
        return raiz.find(caminho, NS).text

    def test_xml_leva_o_executavel_e_os_argumentos(self, elevacao):
        exe = r"C:\Jogos & RGB\OpenRGB.exe"
        assert admin.criar_tarefa("Spectra - OpenRGB", exe,
                                  ["--server", "--startminimized"]) == "ok"
        xml = elevacao["xml"]
        assert self._campo(xml, ".//t:Command") == exe
        assert self._campo(xml, ".//t:Arguments") == "--server --startminimized"
        assert self._campo(xml, ".//t:WorkingDirectory") == r"C:\Jogos & RGB"
        assert self._campo(xml, ".//t:UserId") == r"CASA\ana"
        assert self._campo(xml, ".//t:RunLevel") == "HighestAvailable"

    def test_pede_ao_schtasks_criar_pelo_nome(self, elevacao):
        admin.criar_tarefa("Spectra - OpenRGB", r"C:\OpenRGB\OpenRGB.exe", [])
        args = elevacao["args"]
        assert elevacao["exe"] == "schtasks.exe"
        assert args[:3] == ["/create", "/tn", "Spectra - OpenRGB"]
        assert args[-1] == "/f"

    def test_arquivo_temporario_nao_fica_para_tras(self, elevacao, tmp_path):
        admin.criar_tarefa("T", r"C:\OpenRGB\OpenRGB.exe", [])
        elevacao["resposta"] = "recusado"
        admin.criar_tarefa("T", r"C:\OpenRGB\OpenRGB.exe", [])
        assert list(tmp_path.iterdir()) == []

    def test_aviso_recusado_volta_como_recusado(self, elevacao):
        elevacao["resposta"] = "recusado"
        assert admin.criar_tarefa("T", r"C:\OpenRGB\OpenRGB.exe", []) == "recusado"

    def test_criada_mas_nao_encontrada_e_erro(self, elevacao, monkeypatch):
        monkeypatch.setattr(admin, "tarefa_existe", lambda nome: False)
        assert admin.criar_tarefa("T", r"C:\OpenRGB\OpenRGB.exe", []) == "erro"

    def test_sem_dominio_vai_so_o_usuario(self, elevacao, monkeypatch):
        monkeypatch.delenv("USERDOMAIN")
        admin.criar_tarefa("T", r"C:\OpenRGB\OpenRGB.exe", [])
        assert self._campo(elevacao["xml"], ".//t:UserId") == "ana"

    def test_sem_usuario_nem_tenta(self, elevacao, monkeypatch):
        monkeypatch.delenv("USERNAME")
        assert admin.criar_tarefa("T", r"C:\OpenRGB\OpenRGB.exe", []) == "erro"
        assert "xml" not in elevacao

    def test_escape_cobre_os_caracteres_do_xml(self):
        assert admin._xml_escape('a&b<c>"d"') == "a&amp;b&lt;c&gt;&quot;d&quot;"


class TestAgendador:

    def test_tarefa_existe_pelo_codigo_do_schtasks(self, monkeypatch):
        pedidos = _windows_falso(monkeypatch, codigo=0)
        assert admin.tarefa_existe("Minha") is True
        assert pedidos == [["schtasks", "/query", "/tn", "Minha"]]
        _windows_falso(monkeypatch, codigo=1)
        assert admin.tarefa_existe("Minha") is False

    def test_rodar_tarefa(self, monkeypatch):
        pedidos = _windows_falso(monkeypatch, codigo=0)
        assert admin.rodar_tarefa("Minha") is True
        assert pedidos == [["schtasks", "/run", "/tn", "Minha"]]
        _windows_falso(monkeypatch, codigo=2)
        assert admin.rodar_tarefa("Minha") is False

    def test_schtasks_que_nao_responde_conta_como_nao(self, monkeypatch):
        _windows_falso(monkeypatch, erro=OSError("schtasks travou"))
        assert admin.tarefa_existe("Minha") is False
        assert admin.rodar_tarefa("Minha") is False

    def test_encerrar_derruba_so_o_openrgb(self, monkeypatch):
        pedidos = _windows_falso(monkeypatch, codigo=0)
        assert admin.encerrar_openrgb() is True
        assert pedidos == [["taskkill", "/IM", "OpenRGB.exe", "/T", "/F"]]
        _windows_falso(monkeypatch, codigo=128)
        assert admin.encerrar_openrgb() is False
        _windows_falso(monkeypatch, erro=OSError("negado"))
        assert admin.encerrar_openrgb() is False

    def test_linhas_estranhas_do_tasklist_sao_puladas(self, monkeypatch):
        _windows_falso(monkeypatch, saida=(
            '"OpenRGB.exe","12"\r\n'
            '"OpenRGB.exe","nao e numero"\r\n'
            '"explorer.exe","99"\r\n'
            'lixo sem aspas\r\n'
            '"openrgb.exe","34"\r\n'))
        assert admin._pids_openrgb() == [12, 34]

    def test_tasklist_que_falha_nao_lista_nada(self, monkeypatch):
        _windows_falso(monkeypatch, erro=OSError("sem tasklist"))
        assert admin._pids_openrgb() == []


class TestServidorElevado:

    def test_primeiro_processo_que_responde_decide(self, monkeypatch):
        monkeypatch.setattr(admin, "_pids_openrgb", lambda: [7, 8, 9])
        respostas = {7: None, 8: False, 9: True}
        monkeypatch.setattr(admin, "processo_elevado", respostas.get)
        assert admin.openrgb_elevado() is False

    def test_sem_processo_nao_sabe(self, monkeypatch):
        monkeypatch.setattr(admin, "_pids_openrgb", lambda: [])
        assert admin.openrgb_elevado() is None

    def test_token_ilegivel_em_todos_nao_sabe(self, monkeypatch):
        monkeypatch.setattr(admin, "_pids_openrgb", lambda: [7, 8])
        monkeypatch.setattr(admin, "processo_elevado", lambda pid: None)
        assert admin.openrgb_elevado() is None

    def test_pawnio_pela_pasta_de_instalacao(self, monkeypatch, tmp_path):
        monkeypatch.setattr(admin, "PAWNIO_DIRS", [str(tmp_path / "nao"),
                                                   str(tmp_path / "PawnIO")])
        assert admin.pawnio_instalado() is False
        (tmp_path / "PawnIO").mkdir()
        assert admin.pawnio_instalado() is True
