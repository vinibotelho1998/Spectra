import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spectra.core.protocol import OpenRGBClient, OpenRGBError

MAX = 120
CORES = [("VERMELHO", (255, 0, 0)), ("VERDE", (0, 255, 0)), ("AZUL", (0, 0, 255))]


def main():
    c = OpenRGBClient(name="Spectra-headers3")
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

    for d in devs:
        if d.led_count:
            c.set_direct_mode(d.index)
            try:
                c.update_leds(d.index, b"\x00\x00\x00\x00" * d.led_count,
                              d.led_count)
            except OpenRGBError:
                pass
    time.sleep(0.3)

    mobo = next((d for d in devs if "Motherboard" in d.type_name), None)
    if mobo is None:
        print("placa-mae nao encontrada")
        return 1

    headers = [z for z in mobo.zones if z.leds_min != z.leds_max and z.leds_count]
    print(f"\n{mobo.name}\n")
    for i, z in enumerate(headers[:3]):
        nome, rgb = CORES[i]
        try:
            c.update_zone_leds(mobo.index, z.index,
                               bytes(rgb + (0,)) * z.leds_count, z.leds_count)
            print(f"  {z.name:12} -> {nome}   ({z.leds_count} leds)")
        except OpenRGBError as exc:
            print(f"  {z.name:12} -> FALHOU: {exc}")
        time.sleep(0.05)

    print("\nTodo o resto (RAM, mouse, controle, chipset) esta APAGADO.")
    print("Qualquer peca que nao esteja vermelha, verde ou azul nao vem "
          "desses headers.")
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
