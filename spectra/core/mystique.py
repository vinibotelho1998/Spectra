"""Anel de LED do water cooler DeepCool Mystique, pelo servico do visor.

O OpenRGB nao tem driver para esse cooler. Quem fala com ele por USB e o
servico `mystique-lcd`, que desenha o visor e decide de onde vem a cor do
anel: da temperatura da CPU, que e o padrao do firmware, ou do conector
ARGB da placa-mae em que o cabo do cooler esta ligado. So no segundo modo
a cor sai da cena do Spectra.

O servico publica o estado num arquivo e rele o arquivo de controle quando
ele muda, aplicando so as chaves que estao la. Por isso o Spectra grava
apenas `led` e o resto do visor, como rotacao e brilho, fica como esta.
"""

from __future__ import annotations

import json
import os
import tempfile
import time

NOME = "DeepCool Mystique"

CONTROLE = os.path.join(os.path.expanduser("~"), ".config", "deepcool",
                        "control.json")

# Sem atualizacao ha mais que isso, o servico parou. Morrendo sem gravar o
# desconectado, o arquivo de estado fica para tras dizendo que esta tudo bem.
VALIDADE_ESTADO = 30.0

SEGUE_O_SPECTRA = "motherboard"
SEGUE_A_TEMPERATURA = "temperature"
MODOS_DO_ANEL = {SEGUE_O_SPECTRA, SEGUE_A_TEMPERATURA, "picture"}


def caminho_estado() -> str | None:
    """Arquivo onde o servico do visor publica o estado, ou None fora do Linux."""
    if os.name != "posix" or not hasattr(os, "getuid"):
        return None
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.join(base, "deepcool", "status.json")


def estado(agora: float | None = None) -> dict | None:
    """Situacao do cooler para a aba Hardware, ou None sem o servico do visor.

    So campos que mudam quando a pessoa age: a temperatura do arquivo
    mudaria a cada leitura e faria a aba remontar o cartao sem parar.
    """
    caminho = caminho_estado()
    if not caminho:
        return None
    try:
        with open(caminho, encoding="utf-8") as f:
            lido = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(lido, dict):
        return None
    agora = time.time() if agora is None else agora
    try:
        atualizado = float(lido.get("updated") or 0)
    except (TypeError, ValueError):
        atualizado = 0.0
    rodando = agora - atualizado <= VALIDADE_ESTADO
    led = lido.get("led") if lido.get("led") in MODOS_DO_ANEL else None
    return {
        "name": NOME,
        "rodando": rodando,
        "conectado": rodando and bool(lido.get("connected")),
        "led": led,
        "segue": led == SEGUE_O_SPECTRA,
    }


def definir_anel(segue: bool) -> dict:
    """Faz o anel seguir o conector ARGB, ou voltar para a temperatura.

    Mantem as outras chaves do arquivo de controle e troca o arquivo de uma
    vez, para o servico nunca ler um JSON pela metade. Arquivo ilegivel fica
    como esta: ele pode ser de outra ferramenta, e sobrescrever apagaria o
    que ela gravou.
    """
    modo = SEGUE_O_SPECTRA if segue else SEGUE_A_TEMPERATURA
    atual = {}
    try:
        with open(CONTROLE, encoding="utf-8") as f:
            lido = json.load(f)
    except FileNotFoundError:
        lido = {}
    except (OSError, ValueError):
        return {"ok": False, "error": "o arquivo de controle do visor esta ilegivel"}
    if not isinstance(lido, dict):
        return {"ok": False, "error": "o arquivo de controle do visor esta ilegivel"}
    atual.update(lido)
    atual["led"] = modo

    pasta = os.path.dirname(CONTROLE)
    tmp = None
    try:
        os.makedirs(pasta, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=pasta, prefix=".control-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(atual, f)
        os.replace(tmp, CONTROLE)
    except OSError as exc:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return {"ok": False, "error": f"nao consegui gravar o controle do visor: {exc}"}
    return {"ok": True, "led": modo}
