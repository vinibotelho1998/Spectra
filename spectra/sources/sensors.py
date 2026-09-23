"""Leitura de temperatura, carga e rotacao, via LibreHardwareMonitor.

A biblioteca e .NET e entra por ponte CLR, entao depende de uma DLL que
nao vem no repositorio. Sem ela, e sem privilegio de administrador para
ler os sensores, a fonte simplesmente fica indisponivel e os efeitos que
dependem dela aparecem marcados na interface.
"""

from __future__ import annotations

import os
import sys
import threading
import time


def _vendor_dll_path() -> str:
    if getattr(sys, "frozen", False):
        root = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
    return os.path.join(root, "vendor", "LibreHardwareMonitorLib.dll")


VENDOR_DLL = _vendor_dll_path()


class _LhmBackend:
    """Ponte com a biblioteca .NET do LibreHardwareMonitor."""

    def __init__(self, dll_path: str = VENDOR_DLL):
        self.dll_path = dll_path
        self.computer = None
        self.error = None

    def open(self) -> bool:
        """Carrega a DLL e liga os sensores, devolvendo se deu certo."""
        if not os.path.isfile(self.dll_path):
            # o caminho inteiro: no app instalado a vendor/ do proprio app
            # fica escondida em _internal, e "vendor/" sozinho nao leva a ela
            self.error = ("LibreHardwareMonitorLib.dll nao encontrada em "
                          + os.path.dirname(self.dll_path))
            return False
        try:
            import clr
            clr.AddReference(self.dll_path)
            from LibreHardwareMonitor.Hardware import Computer
            c = Computer()
            c.IsCpuEnabled = True
            c.IsGpuEnabled = True
            c.IsMemoryEnabled = True
            c.IsMotherboardEnabled = True
            c.IsControllerEnabled = True
            c.IsStorageEnabled = True
            c.Open()
            self.computer = c
            self.error = None
            return True
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            self.computer = None
            return False

    def close(self):
        """Desliga os sensores e solta a biblioteca."""
        try:
            if self.computer:
                self.computer.Close()
        except Exception:
            pass
        self.computer = None

    def read(self) -> dict:
        """Le uma rodada de sensores e devolve os valores por nome."""
        if not self.computer:
            return {}
        out: dict[str, float] = {}
        try:
            for hw in self.computer.Hardware:
                hw.Update()
                for sub in hw.SubHardware:
                    sub.Update()
                    self._collect(sub, out)
                self._collect(hw, out)
        except Exception as exc:
            self.error = str(exc)
        return out

    @staticmethod
    def _collect(hw, out: dict):
        kind = str(hw.HardwareType)
        for s in hw.Sensors:
            if s.Value is None:
                continue
            stype = str(s.SensorType)
            name = str(s.Name)
            val = float(s.Value)
            key = f"{kind}/{name}/{stype}"
            out[key] = val

            is_cpu = "Cpu" in kind
            is_gpu = "Gpu" in kind
            if stype == "Temperature":
                if is_cpu and ("Package" in name or "Tctl" in name or "Core (Tctl" in name):
                    out["cpu_temp"] = max(out.get("cpu_temp", 0.0), val)
                elif is_gpu and ("Core" in name or "Hot" in name or "Edge" in name):
                    out["gpu_temp"] = max(out.get("gpu_temp", 0.0), val)
            elif stype == "Load":
                if is_gpu and "Core" in name:
                    out["gpu_load"] = val
                elif is_cpu and "Total" in name:
                    out["cpu_load"] = val
                elif "Memory" in kind and "Memory" in name:
                    out["ram_load"] = val
            elif stype == "Fan":
                out["fan_rpm"] = max(out.get("fan_rpm", 0.0), val)


class SensorSource:
    """Le os sensores periodicamente e mantem o `SensorState` atualizado.

    Roda em thread propria com intervalo proprio, bem mais lento que o
    render: temperatura nao muda em um sexagesimo de segundo, e ler sensor
    custa caro.
    """

    def __init__(self, state, interval: float = 1.0, dll_path: str = VENDOR_DLL):
        self.state = state
        self.interval = float(interval)
        self.lhm = _LhmBackend(dll_path)
        self.lhm_ok = False
        self.psutil_ok = False
        self._thread = None
        self._stop = threading.Event()
        self.error = None
        self.available: list[str] = []

    def start(self) -> bool:
        """Abre a ponte com a biblioteca e comeca a ler.

        Devolve False quando a biblioteca nao esta presente ou o processo nao
        tem privilegio para ler os sensores.
        """
        if self._thread and self._thread.is_alive():
            return True
        try:
            import psutil
            psutil.cpu_percent(interval=None)
            self.psutil_ok = True
        except Exception as exc:
            self.error = str(exc)
        self.lhm_ok = self.lhm.open()
        if not self.lhm_ok and not self.psutil_ok:
            self.error = self.lhm.error or self.error
            return False
        self._stop.clear()
        self.state.enabled = True
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="spectra-sensors")
        self._thread.start()
        return True

    def stop(self):
        """Para a leitura e fecha a ponte."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self.lhm.close()
        self.state.enabled = False

    @property
    def running(self) -> bool:
        """Diz se a leitura esta ativa."""
        return bool(self._thread and self._thread.is_alive())

    def status(self) -> dict:
        """Descreve a disponibilidade da fonte para a interface."""
        return {"running": self.running, "lhm": self.lhm_ok,
                "psutil": self.psutil_ok, "error": self.lhm.error or self.error,
                "available": self.available, "dll_path": self.lhm.dll_path,
                "dll_present": os.path.isfile(self.lhm.dll_path)}

    def _loop(self):
        while not self._stop.is_set():
            s = self.state
            got = set()
            if self.psutil_ok:
                try:
                    import psutil
                    s.cpu_load = float(psutil.cpu_percent(interval=None))
                    s.ram_load = float(psutil.virtual_memory().percent)
                    got.update({"cpu_load", "ram_load"})
                except Exception:
                    pass
            if self.lhm_ok:
                d = self.lhm.read()
                s.extra = d
                for key in ("cpu_temp", "gpu_temp", "gpu_load", "fan_rpm"):
                    if key in d:
                        setattr(s, key, float(d[key]))
                        got.add(key)
                if "cpu_load" in d and not self.psutil_ok:
                    s.cpu_load = float(d["cpu_load"])
                    got.add("cpu_load")
            self.available = sorted(got)
            self._stop.wait(self.interval)
