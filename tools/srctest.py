import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
from prism.engine.context import AudioState, ScreenState, SensorState

print("=========== AUDIO ===========")
from prism.sources.audio import AudioSource
devs, err = AudioSource.list_devices()
print(f"dispositivos de loopback: {len(devs)}" + (f"  (erro: {err})" if err else ""))
for d in devs[:6]:
    print(f"  [{d['index']}] {d['name']}  {d['channels']}ch @ {d['rate']}Hz")
ast = AudioState()
a = AudioSource(ast)
if a.start():
    print(f"capturando de: {a.device_name}")
    for i in range(5):
        time.sleep(0.7)
        print(f"  t={i}  nivel={ast.level:.3f} grave={ast.bass:.3f} "
              f"medio={ast.mid:.3f} agudo={ast.treble:.3f} "
              f"batida={ast.beat:.2f} centroide={ast.centroid:.3f}")
    print(f"  bandas nao-zero: {int((ast.bands > 0.001).sum())}/{len(ast.bands)}")
    a.stop()
    print("  OK (se tudo veio zero, e porque nao havia som tocando)")
else:
    print(f"  FALHOU: {a.error}")

print("\n=========== TELA ===========")
from prism.sources.screen import ScreenSource
outs, err = ScreenSource.list_outputs()
print(f"saidas: {len(outs)}" + (f"  (erro: {err})" if err else ""))
for o in outs: print(f"  [{o['index']}] {o['name']}")
sst = ScreenState()
sc = ScreenSource(sst, output_idx=0, fps=30)
if sc.start():
    time.sleep(2.5)
    print(f"  fps real: {sc.actual_fps:.1f}")
    print(f"  miniatura: {sst.image.shape}, faixa {sst.image.min():.3f}..{sst.image.max():.3f}")
    print(f"  media    : {np.round(sst.average,3).tolist()}")
    print(f"  dominante: {np.round(sst.dominant,3).tolist()}")
    ok = sst.image.max() > 0.001
    print("  OK" if ok else "  ATENCAO: imagem toda preta")
    sc.stop()
else:
    print(f"  FALHOU: {sc.error}")

print("\n=========== SENSORES ===========")
from prism.sources.sensors import SensorSource
sen_st = SensorState()
sn = SensorSource(sen_st, interval=0.5)
if sn.start():
    time.sleep(2.0)
    st = sn.status()
    print(f"  psutil={st['psutil']}  LHM={st['lhm']}  dll_presente={st['dll_present']}")
    if st['error']: print(f"  erro: {st['error']}")
    print(f"  disponiveis: {st['available']}")
    print(f"  cpu_load={sen_st.cpu_load:.1f}%  ram_load={sen_st.ram_load:.1f}%  "
          f"cpu_temp={sen_st.cpu_temp:.1f}C  gpu_temp={sen_st.gpu_temp:.1f}C  "
          f"gpu_load={sen_st.gpu_load:.1f}%")
    sn.stop()
else:
    print(f"  FALHOU: {sn.error}")
