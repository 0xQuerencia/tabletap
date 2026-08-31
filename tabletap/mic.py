import numpy as np
import time
import logging

try:
    import pyaudio
except ImportError:
    pyaudio = None

from .filter import make_bandpass, apply_bandpass, StatefulBandpass

log = logging.getLogger("tabletap")


class MicDisconnected(Exception):
    pass


class MicCapture:
    def __init__(self, cfg: dict, filter_cfg: dict = None):
        if pyaudio is None:
            raise ImportError("pyaudio required: pip install pyaudio")
        self.cfg = cfg
        self.filter_cfg = filter_cfg
        self.sample_rate = cfg.get("sample_rate", 44100)
        self.channels = cfg.get("channels", 1)
        self.chunk = cfg.get("chunk_size", 1024)
        self.device_index = cfg.get("device_index")

        self.pa = pyaudio.PyAudio()
        self.stream = self._open_stream()

        self._filter = None
        self.sos = None
        if filter_cfg and filter_cfg.get("enabled", True):
            low = filter_cfg.get("low", 20)
            high = filter_cfg.get("high", 200)
            sos = make_bandpass(low, high, self.sample_rate)
            self._filter = StatefulBandpass(sos, channels=self.channels)
            self.sos = sos

    def _open_stream(self):
        return self.pa.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=self.chunk,
        )

    def _reconnect(self, max_retries=3):
        log.warning("Microphone disconnected, attempting to reconnect...")
        
        for attempt in range(max_retries):
            try:
                if self.stream:
                    try:
                        self.stream.close()
                    except Exception:
                        pass
                
                wait_time = 2 ** attempt
                log.info(f"Reconnect attempt {attempt + 1}/{max_retries}, waiting {wait_time}s...")
                time.sleep(wait_time)
                
                self.stream = self._open_stream()
                log.info("Microphone reconnected successfully!")
                return
            except Exception as e:
                log.error(f"Reconnect attempt {attempt + 1} failed: {e}")
        
        raise MicDisconnected("Failed to reconnect microphone after all retries")

    def read_chunk(self) -> np.ndarray:
        max_reconnect_attempts = 3
        
        for attempt in range(max_reconnect_attempts):
            try:
                raw = self.stream.read(self.chunk, exception_on_overflow=False)
                data = np.frombuffer(raw, dtype=np.int16)
                if self.channels > 1:
                    data = data.reshape(-1, self.channels)
                return data
            except (OSError, IOError) as e:
                log.error(f"Audio read error: {e}")
                if attempt < max_reconnect_attempts - 1:
                    self._reconnect()
                else:
                    raise MicDisconnected("Failed to read from microphone after reconnection attempts")

    def read_filtered(self) -> tuple[np.ndarray, np.ndarray]:
        raw = self.read_chunk()
        if self._filter is not None:
            filtered = self._filter.process(raw)
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
    rms = max(rms, 1e-10)
    return 20 * np.log10(rms / 32768.0)


def is_spike(chunk: np.ndarray, threshold_db: float) -> bool:
    return rms_db(chunk) > threshold_db

