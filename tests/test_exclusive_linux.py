"""Garantias de instancia unica e protecao de processos no Linux."""
import os
import subprocess
import sys

import pytest

from spectra.core import exclusive

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="especifico do Linux")


def test_instancia_unica_libera_ao_encerrar(tmp_path):
    env = dict(os.environ, XDG_CACHE_HOME=str(tmp_path))
    codigo = (
        "import sys\n"
        "from spectra.core.exclusive import acquire_single_instance\n"
        "print(acquire_single_instance('teste'), flush=True)\n"
        "sys.stdin.readline()\n"
    )
    dono = subprocess.Popen([sys.executable, "-c", codigo], env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert dono.stdout.readline().strip() == "True"
        tentativa = subprocess.run([sys.executable, "-c", codigo], env=env,
                                   input="\n", capture_output=True, text=True, timeout=5)
        assert tentativa.stdout.strip() == "False"
    finally:
        dono.communicate(input="\n", timeout=5)
    seguinte = subprocess.run([sys.executable, "-c", codigo], env=env,
                             input="\n", capture_output=True, text=True, timeout=5)
    assert seguinte.stdout.strip() == "True"


def test_linux_nao_tenta_encerrar_processos_windows(monkeypatch):
    def proibido(*args, **kwargs):
        pytest.fail("nao deve executar taskkill no Linux")

    monkeypatch.setattr(exclusive.subprocess, "run", proibido)
    assert exclusive.scan() == []
    assert exclusive.enforce() == {"fechados": [], "falhou": [], "total": 0}
