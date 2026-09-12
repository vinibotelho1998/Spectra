"""Controla o teclado Akko direto, fora do OpenRGB.

    python tools/akko.py cor ff8800        pinta o teclado inteiro
    python tools/akko.py apaga             apaga tudo
    python tools/akko.py wasd              destaca WASD e as setas
    python tools/akko.py teclas w=ff0000 seta_cima=0000ff

O destaque grava camada na memoria do teclado e fica depois de fechar o
programa. A cor unica nao grava, e some quando outro programa pintar por
cima.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from prism.core.akko import TECLAS, AkkoKeyboard


def cor_de(texto: str) -> tuple:
    t = texto.lstrip("#")
    if len(t) != 6:
        raise SystemExit("cor invalida: %r, use rrggbb" % texto)
    return tuple(int(t[i:i + 2], 16) for i in (0, 2, 4))


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    kb = AkkoKeyboard()
    if not kb.abrir():
        print("FALHA:", kb.erro)
        return 1
    print("teclado aberto em", kb.caminho)

    acao = sys.argv[1]
    try:
        if acao == "cor":
            r, g, b = cor_de(sys.argv[2])
            ok = kb.set_cor(r, g, b, forcar=True)
            print("cor #%02x%02x%02x ->" % (r, g, b), "ok" if ok else "falhou")
        elif acao == "apaga":
            print("apagando ->", "ok" if kb.apagar() else "falhou")
        elif acao == "wasd":
            cores = {TECLAS[k]: (255, 40, 0) for k in ("w", "a", "s", "d")}
            cores.update({TECLAS[k]: (0, 120, 255) for k in TECLAS
                          if k.startswith("seta_")})
            print("destaque ->", "ok" if kb.set_camada(cores) else "falhou")
        elif acao == "teclas":
            cores = {}
            for par in sys.argv[2:]:
                nome, _, valor = par.partition("=")
                if nome not in TECLAS:
                    raise SystemExit("tecla desconhecida: %s (tenho %s)"
                                     % (nome, ", ".join(sorted(TECLAS))))
                cores[TECLAS[nome]] = cor_de(valor)
            print("camada ->", "ok" if kb.set_camada(cores) else "falhou")
        else:
            print(__doc__)
            return 2
    finally:
        kb.fechar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
