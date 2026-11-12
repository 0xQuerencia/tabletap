import numpy as np
from scipy.signal import butter, sosfilt, sosfiltfilt, sosfilt_zi


def make_bandpass(low: float, high: float, fs: int, order: int = 4):
    nyq = fs / 2
    low_n = low / nyq
    high_n = high / nyq
    low_n = max(low_n, 0.001)
    high_n = min(high_n, 0.999)
    return butter(order, [low_n, high_n], btype="band", output="sos")


def apply_bandpass(chunk: np.ndarray, sos, prev_tail: np.ndarray = None):
    if chunk.ndim > 1:
        filtered = np.zeros_like(chunk, dtype=np.float64)
        for ch in range(chunk.shape[1]):
            filtered[:, ch] = sosfilt(sos, chunk[:, ch].astype(np.float64))
        return filtered
    else:
        return sosfilt(sos, chunk.astype(np.float64))


class StatefulBandpass:
    def __init__(self, sos, channels=1):
        self.sos = sos
        self.channels = channels
        zi_base = sosfilt_zi(sos) * 0
        
        if channels > 1:
            self.zi = [zi_base.copy() for _ in range(channels)]
        else:
            self.zi = zi_base
        
    def process(self, chunk: np.ndarray) -> np.ndarray:
        chunk_float = chunk.astype(np.float64)
        
        if chunk.ndim > 1:
            filtered = np.zeros_like(chunk_float)
            for ch in range(chunk.shape[1]):
                filtered[:, ch], self.zi[ch] = sosfilt(
                    self.sos, chunk_float[:, ch], zi=self.zi[ch]
                )
            return filtered
        else:
            filtered, self.zi = sosfilt(self.sos, chunk_float, zi=self.zi)
            return filtered


class AdaptiveThreshold:
    def __init__(
        self,
        initial_threshold_db: float = -30,
        noise_alpha: float = 0.05,
        peak_alpha: float = 0.1,
        snr_gate_db: float = 6.0,
        min_threshold_db: float = -60,
    ):
        self.noise_floor_db = initial_threshold_db - 10
        self.peak_db = initial_threshold_db + 5
        self.threshold_db = initial_threshold_db
        self.noise_alpha = noise_alpha
        self.peak_alpha = peak_alpha
        self.snr_gate_db = snr_gate_db
        self.min_threshold_db = min_threshold_db
        self._active = False

    def update(self, db: float, is_spike: bool):
        if is_spike:
            self.peak_db = self.peak_db + self.peak_alpha * (db - self.peak_db)
            self._active = True
        else:
            self.noise_floor_db = self.noise_floor_db + self.noise_alpha * (db - self.noise_floor_db)
            self._active = False

        gap = self.peak_db - self.noise_floor_db
        if gap >= self.snr_gate_db and self._active:
            self.threshold_db = self.noise_floor_db + gap * 0.35
        else:
            self.threshold_db = self.noise_floor_db + self.snr_gate_db

        self.threshold_db = max(self.threshold_db, self.min_threshold_db)

    def is_above(self, db: float) -> bool:
        return db > self.threshold_db

    def set_from_calibration(self, noise_floor_db: float, slam_peak_db: float):
        self.noise_floor_db = noise_floor_db
        self.peak_db = slam_peak_db
        gap = slam_peak_db - noise_floor_db
        if gap >= self.snr_gate_db:
            self.threshold_db = noise_floor_db + gap * 0.35
        else:
            self.threshold_db = noise_floor_db + self.snr_gate_db

    def get_state(self) -> dict:
        return {
            "noise_floor_db": round(self.noise_floor_db, 1),
            "peak_db": round(self.peak_db, 1),
            "threshold_db": round(self.threshold_db, 1),
        }


class OnsetDetector:
    def __init__(self, min_gap_ms: int = 80):
        self.min_gap = min_gap_ms / 1000.0
        self._prev_energy = 0.0
        self._prev_deriv = 0.0
        self._last_onset_time = 0.0

    def feed(self, energy_db: float, now: float, active: bool = True) -> bool:
        delta = energy_db - self._prev_energy
        self._prev_energy = energy_db

        deriv_delta = delta - self._prev_deriv
        self._prev_deriv = delta

        # Quiet fluctuations update the derivative baseline but must never
        # consume the tap refractory window before a genuine impact.
        if not active:
            return False

        if (now - self._last_onset_time) < self.min_gap:
            return False

        if delta > 2.0 and deriv_delta > 0.5:
            self._last_onset_time = now
            return True

        return False

