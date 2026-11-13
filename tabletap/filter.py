import numpy as np
from scipy.signal import butter, sosfilt, sosfilt_zi


def make_bandpass(low: float, high: float, fs: int, order: int = 4):
    nyq = fs / 2
    low_n = low / nyq
    high_n = high / nyq
    low_n = max(low_n, 0.001)
    high_n = min(high_n, 0.999)
    return butter(order, [low_n, high_n], btype="band", output="sos")


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
        self.calibration_floor_db = None

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

        self.threshold_db = max(
            self.threshold_db, self.min_threshold_db,
            self.calibration_floor_db if self.calibration_floor_db is not None else self.min_threshold_db,
        )

    def is_above(self, db: float) -> bool:
        return db > self.threshold_db

    def set_from_calibration(self, noise_floor_db: float, slam_peak_db: float,
                             threshold_db: float | None = None):
        self.noise_floor_db = noise_floor_db
        self.peak_db = slam_peak_db
        gap = slam_peak_db - noise_floor_db
        if gap >= self.snr_gate_db:
            self.threshold_db = noise_floor_db + gap * 0.35
        else:
            self.threshold_db = noise_floor_db + self.snr_gate_db
        # Saved calibration is a hard floor: adaptive drift must not
        # reclassify quiet keyboard sounds as desk taps.
        if threshold_db is not None:
            self.calibration_floor_db = float(threshold_db)
            self.threshold_db = max(self.threshold_db, self.calibration_floor_db)

    def get_state(self) -> dict:
        return {
            "noise_floor_db": round(self.noise_floor_db, 1),
            "peak_db": round(self.peak_db, 1),
            "threshold_db": round(self.threshold_db, 1),
        }


class ImpactDetector:
    """Require a sharp rise followed by a rapid decay before accepting a tap.

    Slow changes and sounds that stay loud (voices, scraping, music) cannot
    produce a confirmed impact. False positives should fail closed.
    """

    def __init__(self, min_gap_ms: int = 150, max_width_ms: int = 220,
                 min_attack_db: float = 7.0):
        self.min_gap = min_gap_ms / 1000.0
        self.max_width = max_width_ms / 1000.0
        self.min_attack_db = float(min_attack_db)
        self._previous_db = None
        self._pending_since = None
        self._last_accepted_at = float("-inf")
        self._armed = True
        self.rejected_reason = None

    def feed(self, db: float, threshold_db: float, now: float) -> bool:
        self.rejected_reason = None
        rise = 0.0 if self._previous_db is None else db - self._previous_db
        self._previous_db = db
        active = db > threshold_db
        if self._pending_since is not None:
            if active:
                if now - self._pending_since > self.max_width:
                    self.rejected_reason = "sustained noise"
                    self._pending_since = None
                return False
            duration = now - self._pending_since
            self._pending_since = None
            self._armed = True
            if duration > self.max_width:
                self.rejected_reason = "sound too long"
                return False
            if now - self._last_accepted_at < self.min_gap:
                self.rejected_reason = "echo / too close"
                return False
            self._last_accepted_at = now
            return True

        if not active:
            self._armed = True
        elif self._armed:
            self._armed = False
            if rise >= self.min_attack_db:
                self._pending_since = now
            else:
                self.rejected_reason = "slow onset"
        return False
