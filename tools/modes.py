import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spectra.core.protocol import OpenRGBClient, OpenRGBError


def show(devs, titulo):
    print(f"\n=== {titulo} ===")
    ruins = []
    for d in devs:
        modo = (d.modes[d.active_mode].name
                if 0 <= d.active_mode < len(d.modes) else "?")
        dm = d.direct_mode()
        alvo = dm.name if dm else "(nenhum)"
        ok = dm is not None and d.active_mode == dm.index
        marca = "OK " if ok else "NAO"
        print(f"  [{marca}] {d.name:26} modo atual = {modo!r:18} "
              f"(direto seria {alvo!r})")
        if not ok:
            ruins.append(d)
    return ruins


def main():
    fix = "--fix" in sys.argv
    c = OpenRGBClient(name="Spectra-modes")
    try:
        c.connect()
    except OSError as exc:
        print(f"FALHA: OpenRGB nao respondeu ({exc})")
        return 1

    devs = c.load_devices()
    ruins = show(devs, f"{len(devs)} devices, protocolo v{c.protocol}")

    if not ruins:
        print("\nTodos em modo direto. Se ainda pisca, a fonte esta fora do "
              "alcance do OpenRGB.")
    else:
        print(f"\n{len(ruins)} device(s) NAO estao em modo direto -- esses "
              "animam sozinhos e ignoram o que o Spectra envia.")

    if fix:
        print("\nforcando Direct em todos...")
        for d in devs:
            try:
                ok = c.set_direct_mode(d.index)
                print(f"  {d.name}: {'ok' if ok else 'sem modo direto'}")
            except OpenRGBError as exc:
                print(f"  {d.name}: FALHOU ({exc})")
        time.sleep(1.0)
        devs = c.load_devices()
        resto = show(devs, "depois do --fix")
        for d in devs:
            if d.led_count:
                try:
                    c.update_leds(d.index, b"\x00\x00\x00\x00" * d.led_count,
                                  d.led_count)
                except OpenRGBError:
                    pass
        print("\nTudo apagado. O que continuar piscando agora nao passa pelo "
              "OpenRGB.")
        c.close()
        return 1 if resto else 0

    c.close()
    return 1 if ruins else 0


if __name__ == "__main__":
    sys.exit(main())
