import numpy as np

try:
    import pyaudio
except ImportError:
    pyaudio = None

from .filter import make_bandpass, apply_bandpass


class MicCapture:
    def __init__(self, cfg: dict, filter_cfg: dict = None):
        if pyaudio is None:
            raise ImportError("pyaudio required: pip install pyaudio")
        self.sample_rate = cfg.get("sample_rate", 44100)
        self.channels = cfg.get("channels", 1)
        self.chunk = cfg.get("chunk_size", 1024)
        self.device_index = cfg.get("device_index")

        self.pa = pyaudio.PyAudio()
        self.stream = self.pa.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=self.chunk,
        )

        self.sos = None
        if filter_cfg and filter_cfg.get("enabled", True):
            low = filter_cfg.get("low", 20)
            high = filter_cfg.get("high", 200)
            self.sos = make_bandpass(low, high, self.sample_rate)

    def read_chunk(self) -> np.ndarray:
        raw = self.stream.read(self.chunk, exception_on_overflow=False)
        data = np.frombuffer(raw, dtype=np.int16)
        if self.channels > 1:
            data = data.reshape(-1, self.channels)
        return data

    def read_filtered(self) -> tuple[np.ndarray, np.ndarray]:
        raw = self.read_chunk()
        if self.sos is not None:
            filtered = apply_bandpass(raw, self.sos)
            return raw, filtered
        return raw, raw.astype(np.float64)

    def close(self):
        self.stream.stop_stream()
        self.stream.close()
        self.pa.terminate()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def rms_db(chunk: np.ndarray) -> float:
    rms = np.sqrt(np.mean(chunk.astype(np.float64) ** 2))
    if rms < 1:
        return -120.0
    return 20 * np.log10(rms / 32768.0)


def is_spike(chunk: np.ndarray, threshold_db: float) -> bool:
    return rms_db(chunk) > threshold_db
