from tabletap.filter import ImpactDetector


def test_soft_candidate_is_diagnostic_only():
    detector = ImpactDetector()
    assert not detector.feed(-60, -30, 0)
    assert not detector.feed(-34, -30, .1)
    assert detector.near_miss == {"db": -34, "threshold_db": -30, "attack_db": 26}
    assert not detector.feed(-60, -30, .12)
    assert detector.near_miss is None


def test_broadband_and_distant_noise_do_not_create_candidate():
    detector = ImpactDetector()
    detector.feed(-60, -30, 0)
    detector.feed(-45, -30, .1)
    assert detector.near_miss is None
    detector.feed(-60, -30, .2)
    detector.feed(-33, -30, .3, broadband=True)
    assert detector.near_miss is None
    detector.feed(-60, -30, .4)
    detector.feed(-33, -30, .5)
    assert detector.near_miss is None


def test_confirmed_tap_unchanged():
    detector = ImpactDetector()
    detector.feed(-60, -30, 0)
    assert not detector.feed(-20, -30, .1)
    assert detector.near_miss is None
    assert detector.feed(-60, -30, .15)
