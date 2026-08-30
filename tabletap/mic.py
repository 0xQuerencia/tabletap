import numpy as np

try:
    import pyaudio
except ImportError:
    pyaudio = None


class MicCapture:
    def __init__(self, cfg: dict):
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

    def read_chunk(self) -> np.ndarray:
        raw = self.stream.read(self.chunk, exception_on_overflow=False)
        data = np.frombuffer(raw, dtype=np.int16)
        if self.channels > 1:
            data = data.reshape(-1, self.channels)
        return data

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
