import sys, os, time, struct
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from prism.core.protocol import OpenRGBClient

c = OpenRGBClient(name="Prism-blink")
c.connect()
devs = c.load_devices()

targets = []
for d in devs:
    if d.led_count and c.set_direct_mode(d.index):
        targets.append(d)
        print(f"[{d.index}] {d.name}: Direct ok, {d.led_count} leds")

if not targets:
    print("nenhum device controlavel")
    sys.exit(1)

def paint(dev, rgb):
    payload = bytes(rgb + (0,)) * dev.led_count
    c.update_leds(dev.index, payload, dev.led_count)

seq = [((255, 0, 0), "vermelho"), ((0, 255, 0), "verde"), ((0, 0, 255), "azul"),
       ((255, 255, 255), "branco")]
t0 = time.perf_counter()
for rgb, nome in seq:
    for d in targets:
        paint(d, rgb)
    print(f"  -> {nome}")
    time.sleep(0.8)

n = 300
t0 = time.perf_counter()
for i in range(n):
    v = int(127 + 127 * (i / n))
    for d in targets:
        paint(d, (v, 0, 255 - v))
dt = time.perf_counter() - t0
print(f"\n{n} frames x {len(targets)} devices em {dt:.2f}s = {n/dt:.0f} fps de teto")

for d in targets:
    paint(d, (0, 0, 0))
print("apagado")
c.close()
