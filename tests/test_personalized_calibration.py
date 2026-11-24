import pytest
from tabletap.calibrate import fit_personalized_threshold


def trace(peaks):
    samples = [(0.0, -65.0, False)]
    for index, peak in enumerate(peaks):
        t = .5 + index * .4
        samples.extend([(t-.02, -65.0, False), (t, peak, False), (t+.06, -65.0, False)])
    return samples


def test_personalized_learns_soft_examples_above_work_floor():
    reference, threshold, count = fit_personalized_threshold(-65, -48, trace([-34, -33, -32, -20, -12, -10]), {})
    assert count == 6
    assert reference == pytest.approx(-33)
    assert -44 <= threshold < -34


def test_personalized_refuses_overlapping_work_noise():
    with pytest.raises(ValueError, match="previous calibration preserved"):
        fit_personalized_threshold(-65, -30, trace([-34, -33, -32, -20, -12, -10]), {})


def test_personalized_does_not_learn_speech_or_sustained_noise():
    samples = trace([-20] * 5)
    samples.extend([(3.0, -65, False), (3.1, -15, True), (3.6, -65, False),
                    (4.0, -20, False), (4.3, -20, False), (4.4, -65, False)])
    with pytest.raises(ValueError, match="Only 5"):
        fit_personalized_threshold(-65, -48, samples, {})
