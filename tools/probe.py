import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spectra.core.protocol import OpenRGBClient, OpenRGBError

def main():
    c = OpenRGBClient(name="Spectra-probe")
    for attempt in range(20):
        try:
            c.connect()
            break
        except OSError:
            time.sleep(1.5)
    else:
        print("FALHA: servidor OpenRGB nao respondeu em 127.0.0.1:6742")
        return 1

    print(f"conectado | protocolo negociado = v{c.protocol}")
    devs = c.load_devices()
    print(f"{len(devs)} controladores\n")
    total = 0
    for d in devs:
        dm = d.direct_mode()
        total += d.led_count
        print(f"[{d.index}] {d.name}")
        print(f"     tipo={d.type_name}  leds={d.led_count}  local={d.location}")
        print(f"     modos={[m.name for m in d.modes]}")
        print(f"     direct={'SIM -> ' + dm.name if dm else 'NAO'}")
        for z in d.zones:
            mtx = f" matriz {z.matrix_width}x{z.matrix_height}" if z.matrix_width else ""
            rz = " (redimensionavel %d..%d)" % (z.leds_min, z.leds_max) if z.leds_min != z.leds_max else ""
            print(f"       zona {z.index}: {z.name!r} {z.type_name} {z.leds_count} leds{mtx}{rz}")
        print()
    print(f"TOTAL DE LEDS CONTROLAVEIS: {total}")
    c.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())
