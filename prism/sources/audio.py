from __future__ import annotations

import threading
import time

import numpy as np

CHUNK = 1024
BANDS = 24


class AudioSource:
    def __init__(self, state, device_index=None, fft_size: int = 2048):
        self.state = state
        self.device_index = device_index
        self.fft_size = fft_size
        self._stream = None
        self._pa = None
        self._thread = None
        self._stop = threading.Event()
        self._buf = np.zeros(fft_size, dtype=np.float32)
        self._rate = 48000
        self._channels = 2
        self._window = np.hanning(fft_size).astype(np.float32)
        self._band_idx = None
        self._bass_hist = np.zeros(43, dtype=np.float32)
        self._hist_i = 0
        self._agc = 0.25
        self.agc_enabled = True
        self.error = None
        self.device_name = ""

    @staticmethod
    def list_devices():
        try:
            import pyaudiowpatch as pa
        except Exception as exc:
            return [], str(exc)
        out = []
        p = pa.PyAudio()
        try:
            for info in p.get_loopback_device_info_generator():
                out.append({"index": info["index"], "name": info["name"],
                            "channels": info["maxInputChannels"],
                            "rate": int(info["defaultSampleRate"]),
                            "loopback": True})
        except Exception as exc:
            return [], str(exc)
        finally:
            p.terminate()
        return out, None

    def _default_loopback(self, p):
        import pyaudiowpatch as pa
        api = p.get_host_api_info_by_type(pa.paWASAPI)
        spk = p.get_device_info_by_index(api["defaultOutputDevice"])
        if spk.get("isLoopbackDevice"):
            return spk
        for lb in p.get_loopback_device_info_generator():
            if spk["name"] in lb["name"]:
                return lb
        raise RuntimeError("nenhum dispositivo de loopback casou com a saida padrao")

    def start(self):
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        try:
            import pyaudiowpatch as pa
        except Exception as exc:
            self.error = f"pyaudiowpatch indisponivel: {exc}"
            return False
        try:
            self._pa = pa.PyAudio()
            if self.device_index is None:
                info = self._default_loopback(self._pa)
            else:
                info = self._pa.get_device_info_by_index(int(self.device_index))
            self._rate = int(info["defaultSampleRate"])
            self.device_name = info["name"]
            ch = max(1, int(info["maxInputChannels"]))
            self._channels = ch
            self._stream = self._pa.open(
                format=pa.paFloat32, channels=ch, rate=self._rate, input=True,
                input_device_index=int(info["index"]), frames_per_buffer=CHUNK,
                stream_callback=self._callback)
            self._build_bands()
            self._stream.start_stream()
            self.state.enabled = True
            self.error = None
            self._thread = threading.Thread(target=self._decay_loop, daemon=True)
            self._thread.start()
            return True
        except Exception as exc:
            self.error = str(exc)
            self.stop()
            return False

    def stop(self):
        self._stop.set()
        try:
            if self._stream:
                self._stream.stop_stream()
                self._stream.close()
        except Exception:
            pass
        self._stream = None
        try:
            if self._pa:
                self._pa.terminate()
        except Exception:
            pass
        self._pa = None
        self.state.enabled = False

    @property
    def running(self) -> bool:
        return self._stream is not None

    def _build_bands(self):
        nyq = self._rate / 2.0
        edges = np.geomspace(30.0, min(16000.0, nyq * 0.95), BANDS + 1)
        freqs = np.fft.rfftfreq(self.fft_size, 1.0 / self._rate)
        self._band_idx = [
            (np.searchsorted(freqs, edges[i]), max(np.searchsorted(freqs, edges[i + 1]),
                                                   np.searchsorted(freqs, edges[i]) + 1))
            for i in range(BANDS)
        ]
        self._freqs = freqs

    def _callback(self, in_data, frame_count, time_info, status):
        import pyaudiowpatch as pa
        try:
            samples = np.frombuffer(in_data, dtype=np.float32)
            if samples.size == 0:
                return (None, pa.paContinue)
            if self._channels > 1:
                usable = (samples.size // self._channels) * self._channels
                frames = samples[:usable].reshape(-1, self._channels)
                samples = frames[:, :2].mean(axis=1)
            k = min(len(samples), self.fft_size)
            self._buf = np.roll(self._buf, -k)
            self._buf[-k:] = samples[-k:]
            self._analyze()
        except Exception as exc:
            self.error = str(exc)
        return (None, pa.paContinue)

    def _analyze(self):
        s = self.state
        buf = self._buf
        rms = float(np.sqrt(np.mean(buf * buf)))
        level = 0.0 if rms < 1e-6 else max(0.0, min(1.0, (20 * np.log10(rms) + 60) / 60))

        spec = np.abs(np.fft.rfft(buf * self._window)) / (self.fft_size / 2)
        spec = np.log1p(spec * 120.0) / np.log1p(120.0)

        bands = np.empty(BANDS, dtype=np.float32)
        for i, (a, b) in enumerate(self._band_idx):
            bands[i] = spec[a:b].max() if b > a else 0.0
        bands = np.clip(bands, 0.0, 1.0)

        if self.agc_enabled:
            peak = float(bands.max())
            self._agc = max(peak, self._agc * 0.9985)
            bands = np.clip(bands / max(self._agc, 0.06), 0.0, 1.0)

        prev = s.bands
        s.bands = (prev * 0.55 + bands * 0.45).astype(np.float32) if len(prev) == BANDS else bands

        s.bass = float(s.bands[:4].mean())
        s.mid = float(s.bands[4:14].mean())
        s.treble = float(s.bands[14:].mean())
        s.level = float(s.level * 0.6 + level * 0.4)
        s.peak = max(s.peak * 0.97, s.level)

        tot = float(spec.sum())
        if tot > 1e-6:
            s.centroid = float(min(1.0, (spec @ self._freqs) / tot / 8000.0))

        self._bass_hist[self._hist_i % len(self._bass_hist)] = s.bass
        self._hist_i += 1
        avg = float(self._bass_hist.mean())
        if s.bass > avg * 1.45 and s.bass > 0.12:
            s.beat = 1.0

        step = max(1, len(buf) // len(s.waveform))
        s.waveform = np.clip(buf[::step][:len(s.waveform)], -1.0, 1.0).astype(np.float32)

    def _decay_loop(self):
        while not self._stop.is_set():
            self.state.beat *= 0.82
            if self.state.beat < 0.01:
                self.state.beat = 0.0
            time.sleep(1 / 60)
