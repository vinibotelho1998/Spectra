import math
import os
import sys

from PIL import Image, ImageDraw

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(RAIZ, "assets")

FUNDO = (11, 14, 20, 255)
ESPECTRO = [
    (255, 45, 85), (255, 138, 30), (255, 214, 0), (124, 255, 0),
    (0, 217, 255), (90, 120, 255), (168, 85, 247),
]


def desenhar(px: int, detalhado: bool) -> Image.Image:
    ss = 8
    n = px * ss
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    r = int(n * 0.22)
    d.rounded_rectangle([0, 0, n - 1, n - 1], radius=r, fill=FUNDO)

    cx, cy = n * 0.46, n * 0.54
    lado = n * 0.52
    alt = lado * math.sqrt(3) / 2
    tri = [(cx, cy - alt * 0.62),
           (cx - lado / 2, cy + alt * 0.38),
           (cx + lado / 2, cy + alt * 0.38)]

    x0, y0 = cx + lado * 0.16, cy + alt * 0.02
    largura = n * 0.085
    for i, cor in enumerate(ESPECTRO):
        t = i / (len(ESPECTRO) - 1)
        ang = math.radians(-16 + t * 42)
        comp = n * 0.52
        x1 = x0 + math.cos(ang) * comp
        y1 = y0 + math.sin(ang) * comp
        d.line([(x0, y0), (x1, y1)], fill=cor + (255,), width=int(largura))

    if detalhado:
        d.line([(n * 0.06, cy - alt * 0.16), (cx - lado * 0.20, cy + alt * 0.02)],
               fill=(255, 255, 255, 235), width=int(n * 0.075))

    d.polygon(tri, fill=FUNDO)
    d.polygon(tri, outline=(236, 242, 255, 255), width=max(int(n * 0.035), 2))

    return img.resize((px, px), Image.LANCZOS)


def main():
    os.makedirs(ASSETS, exist_ok=True)
    tamanhos = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]
    imagens = [desenhar(t, detalhado=t >= 32) for t in tamanhos]

    ico = os.path.join(ASSETS, "prism.ico")
    imagens[-1].save(ico, format="ICO",
                     sizes=[(t, t) for t in tamanhos])
    png = os.path.join(ASSETS, "prism.png")
    imagens[-1].save(png, format="PNG")
    png64 = os.path.join(ASSETS, "prism-64.png")
    desenhar(64, True).save(png64, format="PNG")

    for caminho in (ico, png, png64):
        print(f"  {os.path.basename(caminho):16} {os.path.getsize(caminho):>7} bytes")
    print(f"\nico com {len(tamanhos)} tamanhos: {tamanhos}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
