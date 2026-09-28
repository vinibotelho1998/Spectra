"""O que o build e o script de administrador deixam na maquina."""
from __future__ import annotations

import os
import re

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ler(*partes):
    with open(os.path.join(RAIZ, *partes), encoding="utf-8") as f:
        return f.read()


def test_exe_sai_em_pasta_e_nao_em_arquivo_unico():
    # no exe unico o processo pai so desempacota e espera, e ele tambem
    # segurava o desligamento do Windows
    spec = _ler("spectra.spec")
    bloco = re.search(r"exe = EXE\((.*?)\n\)", spec, re.S).group(1)
    assert "exclude_binaries=True" in bloco
    assert "a.binaries" not in bloco
    assert "a.datas" not in bloco
    assert "COLLECT(" in spec


def test_tarefa_do_openrgb_nao_sobe_sozinha_no_logon():
    # quem sobe o servidor e o Spectra; com gatilho de logon eram dois
    script = _ler("tools", "setup-admin.ps1")
    assert "-AtLogOn" not in script
    assert "-Trigger" not in script
