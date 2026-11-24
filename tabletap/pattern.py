import time
from enum import Enum
from typing import Optional


class TapPattern(Enum):
    SINGLE = "single"
    DOUBLE = "double"
    TRIPLE = "triple"
    QUADRUPLE = "quadruple"


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
    def __init__(self, min_gap_ms: int = 100, rhythm_window_ms: int = 800):
        self.min_gap = min_gap_ms / 1000.0
        self.rhythm_window = rhythm_window_ms / 1000.0
        self._last_tap_time = float("-inf")
        self.reset()

    def feed(self):
        now = time.monotonic()
        if self._overflow:
            self._last_overflow_tap = now
            return
        if now - self._last_tap_time < self.min_gap:
            return
        self._last_tap_time = now
        self._tap_count += 1
        if self._tap_count > 4:
            self._overflow = True
            self._last_overflow_tap = now
            self._tap_count = 0
        elif self._tap_count == 1:
            self._first_tap_time = now

    def check_window_timeout(self) -> Optional[TapEvent]:
        now = time.monotonic()
        if self._overflow:
            if now - self._last_overflow_tap >= 0.45:
                self.reset()
            return None
        if (not self._tap_count or now - self._last_tap_time < 0.15
                or now - self._first_tap_time <= self.rhythm_window):
            return None
        pattern = (TapPattern.SINGLE, TapPattern.DOUBLE,
                   TapPattern.TRIPLE, TapPattern.QUADRUPLE)[self._tap_count - 1]
        self._tap_count = 0
        return TapEvent(pattern)

    def reset(self):
        self._overflow = False
        self._last_overflow_tap = float("-inf")
        self._tap_count = 0
        self._first_tap_time = 0.0
