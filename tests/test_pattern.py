import pytest
from unittest.mock import patch, MagicMock
from tabletap.pattern import PatternDetector, TapPattern
import time


def test_single_tap_timing():
    detector = PatternDetector(min_gap_ms=100, rhythm_window_ms=800)
    detector._last_tap_time = -1.0
    
    with patch("time.monotonic") as mock_time:
        mock_time.return_value = 0.0
        detector.feed()
        
        mock_time.return_value = 0.16
        detector.on_silence()
        
        mock_time.return_value = 0.85
        event = detector.check_window_timeout()
        
        assert event is not None
        assert event.pattern == TapPattern.SINGLE


def test_double_tap_timing():
    detector = PatternDetector(min_gap_ms=100, rhythm_window_ms=800)
    detector._last_tap_time = -1.0
    
    with patch("time.monotonic") as mock_time:
        mock_time.return_value = 0.0
        detector.feed()
        
        mock_time.return_value = 0.16
        detector.on_silence()
        
        mock_time.return_value = 0.25
        detector.feed()
        
        mock_time.return_value = 0.41
        detector.on_silence()
        
        mock_time.return_value = 1.1
        event = detector.check_window_timeout()
        
        assert event is not None
        assert event.pattern == TapPattern.DOUBLE


def test_triple_tap_timing():
    detector = PatternDetector(min_gap_ms=100, rhythm_window_ms=800)
    detector._last_tap_time = -1.0
    
    with patch("time.monotonic") as mock_time:
        mock_time.return_value = 0.0
        detector.feed()
        
        mock_time.return_value = 0.16
        detector.on_silence()
        
        mock_time.return_value = 0.2
        detector.feed()
        
        mock_time.return_value = 0.36
        detector.on_silence()
        
        mock_time.return_value = 0.4
        detector.feed()
        
        mock_time.return_value = 0.56
        detector.on_silence()
        
        mock_time.return_value = 1.3
        event = detector.check_window_timeout()
        
        assert event is not None
        assert event.pattern == TapPattern.TRIPLE


def test_long_press_detection():
    detector = PatternDetector(
        min_gap_ms=100,
        rhythm_window_ms=800,
        long_press_ms=500
    )
    detector._last_tap_time = -1.0
    
    with patch("time.monotonic") as mock_time:
        mock_time.return_value = 0.0
        detector.feed()
        
        mock_time.return_value = 0.12
        detector.feed()
        
        mock_time.return_value = 0.24
        detector.feed()
        
        mock_time.return_value = 0.90
        event = detector.on_silence()
        
        assert event is not None
        assert event.pattern == TapPattern.LONG


def test_long_press_requires_three_spikes():
    detector = PatternDetector(
        min_gap_ms=100,
        long_press_ms=500
    )
    detector._last_tap_time = -1.0
    
    with patch("time.monotonic") as mock_time:
        mock_time.return_value = 0.0
        detector.feed()
        
        mock_time.return_value = 0.15
        detector.feed()
        
        mock_time.return_value = 0.75
        event = detector.on_silence()
        
        assert event is None


def test_long_press_requires_silence_debounce():
    detector = PatternDetector(
        min_gap_ms=100,
        long_press_ms=500
    )
    detector._last_tap_time = -1.0
    
    with patch("time.monotonic") as mock_time:
        mock_time.return_value = 0.0
        detector.feed()
        
        mock_time.return_value = 0.12
        detector.feed()
        
        mock_time.return_value = 0.24
        detector.feed()
        
        mock_time.return_value = 0.30
        event = detector.on_silence()
        
        assert event is None


def test_rhythm_window_timeout_after_800ms():
    detector = PatternDetector(rhythm_window_ms=800)
    detector._last_tap_time = -1.0
    
    with patch("time.monotonic") as mock_time:
        mock_time.return_value = 0.0
        detector.feed()
        
        mock_time.return_value = 0.16
        detector.on_silence()
        
        mock_time.return_value = 0.85
        event = detector.check_window_timeout()
        
        assert event is not None
        assert event.pattern == TapPattern.SINGLE


def test_no_timeout_within_window():
    detector = PatternDetector(rhythm_window_ms=800)
    detector._last_tap_time = -1.0
    
    with patch("time.monotonic") as mock_time:
        mock_time.return_value = 0.0
        detector.feed()
        
        mock_time.return_value = 0.16
        detector.on_silence()
        
        mock_time.return_value = 0.5
        event = detector.check_window_timeout()
        
        assert event is None


def test_min_gap_prevents_rapid_taps():
    detector = PatternDetector(min_gap_ms=100)
    detector._last_tap_time = -1.0
    
    with patch("time.monotonic") as mock_time:
        mock_time.return_value = 0.0
        detector.feed()
        
        mock_time.return_value = 0.05
        result = detector.feed()
        
        assert result is None


def test_reset_clears_state():
    detector = PatternDetector()
    detector._last_tap_time = -1.0
    
    with patch("time.monotonic") as mock_time:
        mock_time.return_value = 0.0
        detector.feed()
        
        detector.reset()
        
        assert detector._tap_count == 0
        assert not detector._in_hold
        assert detector._hold_spike_count == 0
