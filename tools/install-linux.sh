#!/usr/bin/env bash
# Instala no perfil do usuário; o diretório do repositório deve permanecer no lugar.
set -euo pipefail
if [[ "$(uname -s)" != Linux ]]; then
    echo 'Este instalador é apenas para Linux.' >&2
    exit 1
fi
raiz="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
python="${PYTHON:-python3}"
"$python" -m venv --system-site-packages "$raiz/.venv"
"$raiz/.venv/bin/python" -m pip install -r "$raiz/requirements.txt"

bin="${XDG_BIN_HOME:-$HOME/.local/bin}"
apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$bin" "$apps"
# Um script permite que caminhos com espaços funcionem também no menu gráfico.
{
    printf '#!/usr/bin/env bash\nexec '
    printf '%q ' "$raiz/.venv/bin/python" "$raiz/run.py"
    printf '"$@"\n'
} > "$bin/spectra"
chmod +x "$bin/spectra"
# Desktop Entry exige escapamento próprio para Exec e Icon.
"$raiz/.venv/bin/python" - "$bin/spectra" "$raiz/assets/spectra.png" "$apps/spectra.desktop" <<'PY'
import sys
launcher, icon, dest = sys.argv[1:]
def esc(s):
    return s.replace('%', '%%').replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$')
with open(dest, 'w', encoding='utf-8') as f:
    f.write('[Desktop Entry]\nType=Application\nName=Spectra\nComment=Controlador RGB\n')
    f.write('Exec="' + esc(launcher) + '"\nIcon=' + icon.replace('\\', '\\\\').replace('\n', '\\n') + '\n')
    f.write('Terminal=false\nCategories=Utility;\nStartupNotify=true\nStartupWMClass=spectra\n')
PY
printf 'Spectra instalado. Abra pelo menu ou execute: %s/spectra\n' "$bin"
