import pytest
from tabletap.filter import AdaptiveThreshold, effective_threshold

def test_loud_taps_do_not_undo_personalized_soft_threshold():
    threshold = AdaptiveThreshold(use_calibrated_floor=True)
    threshold.set_from_calibration(-65, -10, -52)
    assert threshold.threshold_db == -52
    for _ in range(50):
        threshold.update(-5, True)
    assert threshold.threshold_db == -52
    for _ in range(100):
        threshold.update(-40, False)
    assert threshold.threshold_db > -40

def test_managed_offset_cannot_bypass_work_noise_margin():
    detection = {"noise_floor_db": -65, "work_peak_db": -48}
    assert effective_threshold(-40, -20, detection, True) == -44
    assert effective_threshold(-40, -20, detection, False) == -60
    assert effective_threshold(-40, 2, detection, True) == -38
