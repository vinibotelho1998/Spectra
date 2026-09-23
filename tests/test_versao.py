"""A versao do app no topo da interface e no titulo da janela.

O numero sai de `spectra.__version__` na hora de servir a pagina e de abrir
a janela; os testes comparam com a constante, nunca com um numero escrito.
"""
from __future__ import annotations

import os
import re
import types

import pytest

import spectra
from spectra import server as server_mod
from spectra.server import Handler


def _servir(caminho):
    """Entrega um arquivo da interface como o servidor entregaria."""
    r = types.SimpleNamespace(code=None, body=None)

    def enviar(code, body, ctype=""):
        r.code, r.body = code, body

    r._send = enviar
    Handler._static(r, caminho)
    return r.code, r.body.decode("utf-8")


def _topo(pagina):
    return pagina.split('<header class="topbar">', 1)[1].split("</header>", 1)[0]


class TestTopoDaInterface:

    def test_rotulo_ao_lado_do_nome_traz_a_versao(self):
        code, pagina = _servir("/")
        assert code == 200
        marca = re.search(r'<div class="brand">(.*?)</div>', _topo(pagina), re.S)
        assert marca is not None
        assert "SPECTRA" in marca.group(1)
        rotulo = re.search(r'id="versao"[^>]*>([^<]*)<', marca.group(1))
        assert rotulo is not None
        assert rotulo.group(1) == "v" + spectra.__version__

    def test_pedido_pelo_nome_do_arquivo_traz_o_mesmo_topo(self):
        _, raiz = _servir("/")
        _, pelo_nome = _servir("/index.html")
        assert _topo(pelo_nome) == _topo(raiz)

    @pytest.mark.parametrize("caminho", ["/INDEX.HTML", "/Index.html"])
    def test_nome_com_outras_maiusculas_nao_mostra_a_marca(self, caminho):
        # no Windows o disco ignora maiusculas e entrega a mesma pagina; num
        # disco que diferencia, o pedido nem acha o arquivo
        code, pagina = _servir(caminho)
        assert code == 404 or _topo(pagina) == _topo(_servir("/")[1])

    def test_titulo_da_pagina_traz_nome_e_versao(self):
        _, pagina = _servir("/")
        titulo = re.search(r"<title>([^<]*)</title>", pagina)
        assert titulo.group(1) == "Spectra " + spectra.__version__

    def test_nenhuma_marca_sobra_na_pagina(self):
        _, pagina = _servir("/")
        assert "{{" not in pagina

    def test_numero_nao_fica_escrito_no_arquivo(self):
        with open(os.path.join(server_mod.UI_DIR, "index.html"),
                  encoding="utf-8") as f:
            assert spectra.__version__ not in f.read()


class TestTituloDaJanela:

    def test_titulo_traz_nome_e_versao(self):
        import run
        assert run.TITULO == "Spectra " + spectra.__version__
