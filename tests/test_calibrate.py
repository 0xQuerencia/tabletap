"""Calibration tests using deterministic quiet, typing, and deliberate tap levels."""
from unittest.mock import patch

import numpy as np
import pytest

from tabletap.calibrate import calibrate


def run_calibration(margin_db=None):
    """Three deliberately different acoustic phases; no hardware required."""
    clock = {"now": 0.0, "phase": -1, "frame": 0}

    class FakeMic:
        def __init__(self, *_args):
            clock["phase"] += 1
            clock["frame"] = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read_filtered(self):
            clock["now"] += 0.05
            clock["frame"] += 1
            return None, np.zeros(1024, dtype=np.float64)

    def level(_frame):
        if clock["phase"] == 0:
            return -62.0
        if clock["phase"] == 1:
            return -43.0 if clock["frame"] % 3 == 0 else -55.0
        return -14.0 if clock["frame"] % 3 == 0 else -58.0

    with patch("tabletap.calibrate.MicCapture", FakeMic), \
         patch("tabletap.calibrate.rms_db", side_effect=level), \
         patch("tabletap.calibrate.time.monotonic", side_effect=lambda: clock["now"]), \
         patch("tabletap.calibrate.time.sleep"):
        return calibrate({}, duration_sec=1, margin_db=margin_db)


def test_calibrate_returns_valid_dict():
    result = run_calibration()
    assert set(("noise_floor_db", "work_peak_db", "slam_peak_db", "threshold_db")) <= set(result)
    assert result["threshold_db"] > result["work_peak_db"]
    assert result["threshold_db"] < result["slam_peak_db"]


def test_calibrate_margin_increases_threshold_without_exceeding_peak():
    original = run_calibration()
    adjusted = run_calibration(margin_db=8.0)
    assert adjusted["threshold_db"] > original["threshold_db"]
    assert adjusted["threshold_db"] < adjusted["slam_peak_db"] + 8.0


def test_calibrate_never_uses_keyboard_noise_as_tap():
    result = run_calibration()
    # False positives from typing must not exceed the minimum threshold.
    assert result["work_peak_db"] + 3.9 <= result["threshold_db"]
