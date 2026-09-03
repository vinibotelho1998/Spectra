import os, sys, time, traceback
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
from prism import effects as fx
from prism.engine.canvas import Canvas
from prism.engine.context import RenderContext

class FakeZone:
    def __init__(self, i, name, count, t=1):
        self.index=i; self.name=name; self.leds_count=count; self.type=t
        self.leds_min=0; self.leds_max=1024; self.matrix_width=0; self.matrix_height=0
class FakeDev:
    def __init__(self, i, name, tname, zones):
        self.index=i; self.name=name; self.type_name=tname; self.serial=f"S{i}"
        self.location=""; self.zones=zones
        self.led_count=sum(z.leds_count for z in zones)

devs = [
    FakeDev(0, "Mobo", "Motherboard", [FakeZone(0,"ARGB1",24),FakeZone(1,"ARGB2",18),FakeZone(2,"Chipset",1,0)]),
    FakeDev(1, "RAM", "DRAM", [FakeZone(0,"DIMM",8)]),
    FakeDev(2, "Mouse", "Mouse", [FakeZone(0,"Logo",1,0),FakeZone(1,"Wheel",1,0)]),
]
cv = Canvas(devs)
ctx = RenderContext(cv)
ctx.audio.enabled = True
ctx.audio.level=0.5; ctx.audio.bass=0.7; ctx.audio.beat=0.9; ctx.audio.centroid=0.4
ctx.audio.bands = np.abs(np.sin(np.linspace(0,6,24))).astype(np.float32)
ctx.audio.waveform = np.sin(np.linspace(0,20,128)).astype(np.float32)
ctx.sensors.enabled=True; ctx.sensors.cpu_temp=62; ctx.sensors.gpu_temp=71
ctx.sensors.cpu_load=45; ctx.sensors.gpu_load=88; ctx.sensors.ram_load=55
ctx.screen.enabled=True
ctx.screen.image = np.random.random((36,64,3)).astype(np.float32)
ctx.screen.average = np.array([0.3,0.5,0.7],dtype=np.float32)
ctx.screen.dominant = np.array([0.8,0.2,0.4],dtype=np.float32)

print(f"canvas: {cv.n} leds, {len(cv.zone_info)} zonas")
print(f"efeitos registrados: {fx.count()}\n")
bad=[]; slow=[]
for eid, d in fx.EFFECTS.items():
    p = d.defaults(); st = {}
    try:
        t0=time.perf_counter()
        for i in range(30):
            ctx.t = i/30.0; ctx.dt=1/30.0
            out = d.fn(ctx, p, st)
            out = np.asarray(out)
            assert out.shape==(cv.n,3), f"shape {out.shape}"
            assert np.isfinite(out).all(), "NaN/inf"
            assert out.min()>=-1e-4 and out.max()<=1.0+1e-3, f"fora de 0..1: {out.min():.3f}..{out.max():.3f}"
        ms=(time.perf_counter()-t0)/30*1000
        if ms>4.0: slow.append((eid,ms))
    except Exception as e:
        bad.append((eid, f"{type(e).__name__}: {e}"))
        traceback.print_exc(limit=2)

print(f"\nOK: {fx.count()-len(bad)}/{fx.count()}")
if bad:
    print("\nFALHAS:")
    for eid,msg in bad: print(f"  {eid}: {msg}")
if slow:
    print("\nLENTOS (>4ms/frame):")
    for eid,ms in sorted(slow,key=lambda x:-x[1]): print(f"  {eid}: {ms:.1f} ms")
sys.exit(1 if bad else 0)
