"""Teste do instalador sem rede e sem alterar o perfil real do usuário."""
from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys


def test_instalador_cria_atalho_funcional_com_espacos(tmp_path):
    raiz = tmp_path / 'Spectra com espaço %'
    (raiz / 'tools').mkdir(parents=True)
    (raiz / 'assets').mkdir()
    origem = Path(__file__).resolve().parents[1]
    shutil.copy(origem / 'tools/install-linux.sh', raiz / 'tools')
    (raiz / 'assets/spectra.png').touch()
    (raiz / 'requirements.txt').touch()
    (raiz / 'run.py').write_text(
        'import sys\nprint("|".join(sys.argv[1:]))\n', encoding='utf-8')

    # Cria um ambiente falso: o teste exercita a instalação dos atalhos, sem
    # baixar pacotes nem depender dos pacotes instalados na máquina.
    python = tmp_path / 'python-falso'
    python.write_text('''#!/bin/sh
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
    mkdir -p "$4/bin"
    cp "$0" "$4/bin/python"
elif [ "$1" = "-m" ] && [ "$2" = "pip" ]; then
    exit 0
else
    exec ''' + shlex.quote(sys.executable) + ''' "$@"
fi
''', encoding='utf-8')
    python.chmod(0o755)
    home = tmp_path / 'home com espaço'
    env = dict(os.environ, HOME=str(home), PYTHON=str(python),
               XDG_BIN_HOME=str(home / 'bin com espaço'),
               XDG_DATA_HOME=str(home / 'dados com espaço'))
    subprocess.run(['bash', str(raiz / 'tools/install-linux.sh')],
                   env=env, check=True, capture_output=True, text=True)

    launcher = home / 'bin com espaço/spectra'
    result = subprocess.run([str(launcher), '--browser', 'com espaço'],
                            env=env, check=True, capture_output=True, text=True)
    assert result.stdout.strip() == '--browser|com espaço'
    desktop = home / 'dados com espaço/applications/spectra.desktop'
    entry = desktop.read_text(encoding='utf-8')
    exec_line = next(line[5:] for line in entry.splitlines() if line.startswith('Exec='))
    assert shlex.split(exec_line)[0].replace('%%', '%') == str(launcher)
    validator = shutil.which('desktop-file-validate')
    if validator:
        subprocess.run([validator, str(desktop)], check=True, capture_output=True, text=True)
