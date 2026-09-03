import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from prism.core.protocol import OpenRGBClient, OpenRGBError

MAX = 120

CORES = [
    ("VERMELHO", (255, 0, 0)),
    ("VERDE", (0, 255, 0)),
    ("AZUL", (0, 40, 255)),
    ("AMARELO", (255, 200, 0)),
    ("CIANO", (0, 255, 220)),
    ("ROSA", (255, 0, 150)),
    ("ROXO", (150, 0, 255)),
    ("LARANJA", (255, 80, 0)),
    ("BRANCO", (255, 255, 255)),
    ("VERDE-AGUA", (0, 255, 120)),
]


def main():
    c = OpenRGBClient(name="Prism-identify")
    try:
        c.connect()
    except OSError as exc:
        print(f"FALHA: OpenRGB nao respondeu ({exc})")
        return 1

    devs = c.load_devices()

    mudou = False
    for d in devs:
        for z in d.zones:
            if z.leds_min != z.leds_max and z.leds_count < min(z.leds_max, MAX):
                try:
                    c.resize_zone(d.index, z.index, min(z.leds_max, MAX))
                    mudou = True
                except OpenRGBError:
                    pass
    if mudou:
        time.sleep(1.0)
        devs = c.load_devices()

    print("\n================ LEGENDA ================")
    i = 0
    plano = []
    for d in devs:
        if d.led_count == 0:
            continue
        c.set_direct_mode(d.index)
        for z in d.zones:
            if z.leds_count == 0:
                continue
            nome, rgb = CORES[i % len(CORES)]
            i += 1
            plano.append((d, z, nome, rgb))
            print(f"  {nome:12} = {d.name} / {z.name}  ({z.leds_count} leds)")

    print("\npintando...")
    for d, z, nome, rgb in plano:
        buf = bytes(rgb + (0,)) * z.leds_count
        try:
            c.update_zone_leds(d.index, z.index, buf, z.leds_count)
        except OpenRGBError as exc:
            print(f"  FALHOU em {z.name}: {exc}")
        time.sleep(0.05)

    print("\nPronto. Olhe o gabinete e diga de que cor ficou cada peca.")
    print("O que NAO assumir nenhuma cor da legenda nao passa pelo OpenRGB.")
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
