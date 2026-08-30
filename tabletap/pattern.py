import time
from enum import Enum
from typing import Optional


class TapPattern(Enum):
    SINGLE = "single"
    DOUBLE = "double"
    TRIPLE = "triple"
    LONG = "long"


class TapEvent:
    __slots__ = ("pattern", "timestamp")

    def __init__(self, pattern: TapPattern):
        self.pattern = pattern
        self.timestamp = time.monotonic()

    def key(self) -> str:
        return self.pattern.value

    def __repr__(self):
        return f"TapEvent({self.pattern.value})"


class PatternDetector:
    def __init__(self, min_gap_ms: int = 100, rhythm_window_ms: int = 800, long_press_ms: int = 500):
        self.min_gap = min_gap_ms / 1000.0
        self.rhythm_window = rhythm_window_ms / 1000.0
        self.long_press = long_press_ms / 1000.0

        self._tap_count = 0
        self._first_tap_time: float = 0.0
        self._last_tap_time: float = 0.0
        self._hold_spike_count = 0
        self._hold_start_time: float = 0.0
        self._in_hold: bool = False

    def feed(self) -> Optional[TapEvent]:
        now = time.monotonic()

        if now - self._last_tap_time < self.min_gap:
            return None
        self._last_tap_time = now

        if self._in_hold:
            self._hold_spike_count += 1
        else:
            self._in_hold = True
            self._hold_spike_count = 1
            self._hold_start_time = now

        self._tap_count += 1
        if self._tap_count == 1:
            self._first_tap_time = now

        return None

    def on_silence(self):
        if self._in_hold:
            self._in_hold = False
            if self._hold_spike_count >= 3:
                duration = time.monotonic() - self._hold_start_time
                if duration >= self.long_press:
                    self._tap_count = 0
                    self._hold_spike_count = 0
                    return TapEvent(TapPattern.LONG)
        self._hold_spike_count = 0
        return None

    def check_window_timeout(self) -> Optional[TapEvent]:
        if self._tap_count == 0:
            return None

        now = time.monotonic()
        elapsed = now - self._first_tap_time

        if elapsed > self.rhythm_window and not self._in_hold:
            count = min(self._tap_count, 3)
            self._tap_count = 0

            if count == 1:
                return TapEvent(TapPattern.SINGLE)
            elif count == 2:
                return TapEvent(TapPattern.DOUBLE)
            else:
                return TapEvent(TapPattern.TRIPLE)

        return None

    def reset(self):
        self._tap_count = 0
        self._in_hold = False
        self._hold_spike_count = 0
