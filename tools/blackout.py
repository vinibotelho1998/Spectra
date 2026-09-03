import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from prism.core.protocol import OpenRGBClient, OpenRGBError

MAX = 120


def main():
    restore = "--restore" in sys.argv
    c = OpenRGBClient(name="Prism-blackout")
    try:
        c.connect()
    except OSError as exc:
        print(f"FALHA: OpenRGB nao respondeu ({exc})")
        return 1

    devs = c.load_devices()
    print(f"conectado (protocolo v{c.protocol}) — {len(devs)} controlador(es)\n")

    resizable = []
    for d in devs:
        for z in d.zones:
            if z.leds_min != z.leds_max:
                resizable.append((d, z))

    if resizable:
        alvo = 0 if restore else MAX
        print(f"{'Devolvendo' if restore else 'Expandindo'} "
              f"{len(resizable)} header(s) para {alvo} LEDs:")
        for d, z in resizable:
            size = min(z.leds_max, alvo)
            try:
                c.resize_zone(d.index, z.index, size)
                print(f"  {d.name} / {z.name}: {z.leds_count} -> {size}")
            except OpenRGBError as exc:
                print(f"  {d.name} / {z.name}: FALHOU ({exc})")
        time.sleep(1.0)
        devs = c.load_devices()
        print()

    print("Armando modo Direct e zerando:")
    total = 0
    for d in devs:
        if d.led_count == 0:
            print(f"  {d.name}: 0 leds, nada a fazer")
            continue
        ok = c.set_direct_mode(d.index)
        time.sleep(0.05)
        for _ in range(2):
            c.update_leds(d.index, b"\x00\x00\x00\x00" * d.led_count, d.led_count)
            time.sleep(0.05)
        total += d.led_count
        print(f"  {d.name}: {d.led_count} leds apagados"
              f"{'' if ok else '  (SEM modo Direct - pode ignorar)'}")

    print(f"\n{total} LEDs zerados em {len(devs)} controlador(es).")
    if not restore:
        print("\nO que AINDA estiver aceso nao passa pelo OpenRGB.")
        print("Candidatos: RAM (SMBus), water cooler (USB), GPU (I2C)")
        print("-- todos exigem o servidor do OpenRGB rodando ELEVADO.")
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
