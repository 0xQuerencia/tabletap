import time
from enum import Enum
from typing import Optional


class TapPattern(Enum):
    SINGLE = "single"
    DOUBLE = "double"
    TRIPLE = "triple"
    QUADRUPLE = "quadruple"
    LONG = "long"
    MEDIUM_HOLD = "medium"
    LONG_HOLD = "extended"
    HOLD_REPEAT = "repeat"


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
    def __init__(self, 
                 min_gap_ms: int = 100, 
                 rhythm_window_ms: int = 800, 
                 long_press_ms: int = 500,
                 medium_hold_ms: int = 2000,
                 long_hold_ms: int = 4000,
                 hold_repeat_ms: int = 500,
                 hold_timeout_ms: int = 2000,
                 enable_hold: bool = True):
        self.min_gap = min_gap_ms / 1000.0
        self.rhythm_window = rhythm_window_ms / 1000.0
        self.long_press = long_press_ms / 1000.0
        self.medium_hold = medium_hold_ms / 1000.0
        self.long_hold = long_hold_ms / 1000.0
        self.hold_repeat = hold_repeat_ms / 1000.0
        self.hold_timeout = hold_timeout_ms / 1000.0
        self.enable_hold = enable_hold

        self._tap_count = 0
        self._first_tap_time: float = 0.0
        self._last_tap_time: float = 0.0
        self._last_spike_time: float = 0.0
        self._hold_spike_count = 0
        self._hold_start_time: float = 0.0
        self._in_hold: bool = False
        self._last_repeat_time: float = 0.0
        self._overflow = False
        self._last_overflow_tap = float('-inf')

    def feed(self) -> Optional[TapEvent]:
        now = time.monotonic()

        if self._overflow:
            self._last_overflow_tap = now
            return None
        if now - self._last_tap_time < self.min_gap:
            return None
        
        spike_gap_threshold = 0.15
        time_since_last_spike = now - self._last_spike_time if self._last_spike_time >= 0 else 999
        
        self._last_tap_time = now
        self._last_spike_time = now

        if self._in_hold and time_since_last_spike <= spike_gap_threshold:
            self._hold_spike_count += 1
        elif self._in_hold and time_since_last_spike > spike_gap_threshold:
            self._in_hold = False
            self._hold_spike_count = 0
        else:
            self._in_hold = True
            self._hold_spike_count = 1
            self._hold_start_time = now

        self._tap_count += 1
        if self._tap_count > 4:
            # Five or more hits is typical of typing, not a deliberate four-tap.
            # Discard the entire burst; only re-arm after a quiet interval.
            self._overflow = True
            self._last_overflow_tap = now
            self._in_hold = False
            self._tap_count = 0
            return None
        if self._tap_count == 1:
            self._first_tap_time = now

        return None

    def on_silence(self):
        if not self._in_hold:
            return None
        
        now = time.monotonic()
        silence_duration = now - self._last_spike_time
        
        if silence_duration < 0.15:
            return None
        
        hold_duration = now - self._hold_start_time
        
        if self.enable_hold and self._hold_spike_count >= 3:
            self._in_hold = False
            self._hold_spike_count = 0
            self._tap_count = 0
            
            if hold_duration >= self.long_hold:
                return TapEvent(TapPattern.LONG_HOLD)
            elif hold_duration >= self.medium_hold:
                return TapEvent(TapPattern.MEDIUM_HOLD)
            elif hold_duration >= self.long_press:
                return TapEvent(TapPattern.LONG)
        
        self._in_hold = False
        self._hold_spike_count = 0
        
        return None

    def check_hold_repeat(self) -> Optional[TapEvent]:
        if not self.enable_hold or not self._in_hold:
            return None
        
        now = time.monotonic()
        hold_duration = now - self._hold_start_time
        
        if hold_duration < self.long_press:
            return None
        
        if now - self._last_repeat_time >= self.hold_repeat:
            self._last_repeat_time = now
            return TapEvent(TapPattern.HOLD_REPEAT)
        
        return None

    def check_window_timeout(self) -> Optional[TapEvent]:
        now = time.monotonic()

        if self._overflow:
            if now - self._last_overflow_tap >= 0.45:
                self.reset()
            return None
        if self._in_hold:
            hold_duration = now - self._hold_start_time
            if hold_duration > self.hold_timeout:
                self._in_hold = False
                self._hold_spike_count = 0
                self._tap_count = 0
                return None
            return None
        
        if self._tap_count == 0:
            return None

        elapsed = now - self._first_tap_time

        if elapsed > self.rhythm_window:
            count = self._tap_count
            self._tap_count = 0

            if count == 1:
                return TapEvent(TapPattern.SINGLE)
            elif count == 2:
                return TapEvent(TapPattern.DOUBLE)
            elif count == 3:
                return TapEvent(TapPattern.TRIPLE)
            else:
                return TapEvent(TapPattern.QUADRUPLE)

        return None

    def reset(self):
        self._overflow = False
        self._last_overflow_tap = float('-inf')
        self._tap_count = 0
        self._in_hold = False
        self._hold_spike_count = 0

