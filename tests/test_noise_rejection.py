"""False-positive guard regressions: typing bursts, speech-like sustained sound and calibration."""
import json
from unittest.mock import patch

import numpy as np
import pytest

from tabletap.filter import AdaptiveThreshold, ImpactDetector
from tabletap.pattern import PatternDetector, TapPattern
from tabletap.calibrate import calibrate


def test_calibrated_floor_does_not_drift_down_after_long_quiet():
    threshold = AdaptiveThreshold(initial_threshold_db=-30)
    threshold.set_from_calibration(-62, -17, threshold_db=-28)
    for _ in range(200):
        threshold.update(-67, is_spike=False)
    assert threshold.threshold_db >= -28


def test_impact_detector_accepts_only_sharp_impulses():
    gate = ImpactDetector(min_gap_ms=150, max_width_ms=220, min_attack_db=7)
    assert not gate.feed(-62, -34, 0.0)
    assert not gate.feed(-14, -34, 0.20)
    assert gate.feed(-60, -34, 0.26)


def test_impact_detector_rejects_sustained_sound():
    gate = ImpactDetector(max_width_ms=220)
    assert not gate.feed(-60, -34, 0.0)
    assert not gate.feed(-18, -34, .20)
    for i in range(1, 16):
        assert not gate.feed(-18, -34, .20 + i * .03)
    assert not gate.feed(-60, -34, .70)
    assert gate.rejected_reason is None


def test_impact_detector_rejects_slow_onset():
    gate = ImpactDetector(min_attack_db=7)
    assert not gate.feed(-50, -34, 0.0)
    assert not gate.feed(-45, -34, .02)
    assert not gate.feed(-39, -34, .04)
    assert not gate.feed(-33, -34, .06)
    assert gate.rejected_reason == "slow onset"
    assert not gate.feed(-20, -34, .08)
    assert not gate.feed(-55, -34, .14)


def test_more_than_four_typing_hits_never_saturate_to_quadruple():
    gate = PatternDetector(min_gap_ms=100, rhythm_window_ms=800, enable_hold=False)
    gate._last_tap_time = -1.0
    with patch("time.monotonic") as clock:
        for at in (0.1, 0.27, 0.44, 0.61, 0.78, 0.95, 1.12):
            clock.return_value = at
            gate.feed()
            clock.return_value = at + 0.16
            gate.on_silence()
        clock.return_value = 2.0
        assert gate.check_window_timeout() is None
        assert gate._overflow is False
        # The detector must re-arm after a quiet period.
        clock.return_value = 2.4
        gate.feed()
        clock.return_value = 2.58
        gate.on_silence()
        clock.return_value = 3.3
        event = gate.check_window_timeout()
        assert event is not None
        assert event.pattern == TapPattern.SINGLE


def test_impact_gate_rejects_echo_in_refractory_window():
    gate = ImpactDetector(min_gap_ms=150)
    assert not gate.feed(-60, -34, 0.0)
    assert not gate.feed(-15, -34, 0.2)
    assert gate.feed(-60, -34, 0.24)
    assert not gate.feed(-15, -34, 0.29)
    assert not gate.feed(-60, -34, 0.33)
    assert gate.rejected_reason == "echo / too close"


def test_calibration_learns_typing_noise_and_sets_floor():
    # Separate quiet / typing / deliberate-tap contexts. Time advances at
    # every microphone frame, independently of actual CI wall time.
    ctx = {"phase": -1, "count": 0, "now": 0.0}

    class FakeMic:
        def __init__(self, *_a):
            ctx["phase"] += 1
            ctx["count"] = 0
        def __enter__(self):
            return self
        def __exit__(self, *_a):
            return False
        def read_filtered(self):
            ctx["now"] += 0.04
            ctx["count"] += 1
            return None, np.zeros(1024)

    def level(_):
        if ctx["phase"] == 0:
            return -63.0
        if ctx["phase"] == 1:
            return -40.0 if ctx["count"] % 3 == 0 else -55.0
        return -16.0 if ctx["count"] % 3 == 0 else -59.0

    with patch("tabletap.calibrate.MicCapture", FakeMic), \
         patch("tabletap.calibrate.rms_db", side_effect=level), \
         patch("tabletap.calibrate.time.monotonic", side_effect=lambda: ctx["now"]), \
         patch("tabletap.calibrate.time.sleep"):
        result = calibrate({}, duration_sec=1)

    assert result["work_peak_db"] == -40.0
    assert result["threshold_db"] >= -36.0
    assert result["threshold_db"] < result["slam_peak_db"] - 2


def test_calibration_fails_closed_when_typing_is_louder_than_taps():
    ctx = {"phase": -1, "now": 0.0}

    class FakeMic:
        def __init__(self, *_a):
            ctx["phase"] += 1
        def __enter__(self):
            return self
        def __exit__(self, *_a):
            return False
        def read_filtered(self):
            ctx["now"] += 0.04
            return None, np.zeros(1024)

    with patch("tabletap.calibrate.MicCapture", FakeMic), \
         patch("tabletap.calibrate.rms_db", side_effect=lambda _: [-60, -18, -19][ctx["phase"]]), \
         patch("tabletap.calibrate.time.monotonic", side_effect=lambda: ctx["now"]), \
         patch("tabletap.calibrate.time.sleep"):
        with pytest.raises(ValueError, match="not clearly louder"):
            calibrate({}, duration_sec=1)


def test_broadband_noise_gate_separates_bright_voice_and_low_thump():
    from tabletap.filter import is_broadband_noise

    fs = 44100
    t = np.arange(1024) / fs
    thump = 16000 * np.sin(2 * np.pi * 185 * t) * np.exp(-t * 35)
    speech = 10000 * np.sin(2 * np.pi * 185 * t) + 6000 * np.sin(2 * np.pi * 1800 * t)
    assert not is_broadband_noise(thump, fs)
    assert is_broadband_noise(speech, fs)


def test_broadband_noise_veto_cancels_pending_impacts_and_holds_off():
    gate = ImpactDetector()
    assert not gate.feed(-60, -32, 0.0)
    assert not gate.feed(-15, -32, 0.2)  # a candidate tap
    assert not gate.feed(-16, -32, 0.23, broadband=True)
    assert not gate.feed(-60, -32, 0.27)  # masked as possible voice
    assert not gate.feed(-60, -32, 0.65)
    assert not gate.feed(-12, -32, 0.80)
    assert gate.feed(-60, -32, 0.86)
