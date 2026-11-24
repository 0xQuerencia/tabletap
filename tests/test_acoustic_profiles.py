from unittest.mock import patch
import pytest
from tabletap.acoustic_profiles import device_identity, remember, select, add_feedback, fit_feedback, apply_feedback, rollback, verify_live


def cfg():
    return {"audio":{}, "filter":{}, "calibration":{}, "detection":{"noise_floor_db":-65., "work_peak_db":-50., "slam_peak_db":-20., "threshold_db":-36.}}


def test_microphone_identity_changes_with_capture_settings():
    devices = [{"index":0,"name":"Internal","default":True,"channels":1,"sample_rate":44100},
               {"index":1,"name":"USB","default":False,"channels":1,"sample_rate":44100}]
    config = cfg()
    first = device_identity(config, devices)
    config["audio"]["device_index"] = 1
    assert device_identity(config, devices) != first
    config["audio"]["device_index"] = 0
    assert device_identity(config, devices) == first
    config["audio"]["sample_rate"] = 48000
    assert device_identity(config, devices) != first


def test_profiles_do_not_reuse_unmatched_calibration():
    config = cfg()
    remember(config, "a")
    assert not select(config, "b", "default")
    assert "threshold_db" not in config["detection"]
    with pytest.raises(ValueError, match="needs calibration"):
        verify_live(config)
    assert select(config, "a", "default")
    assert config["detection"]["threshold_db"] == -36.


def test_feedback_is_explicit_and_reversible():
    config = cfg()
    remember(config, "a")
    with patch("tabletap.acoustic_profiles.device_identity", return_value="a"):
        for db in (-40, -41, -42):
            add_feedback(config, "tap", db, False)
        assert config["detection"]["threshold_db"] == -36.
        assert fit_feedback(config)["threshold_db"] == -43.
        assert apply_feedback(config) == -43.
        rollback(config)
        assert config["detection"]["threshold_db"] == -36.


def test_overlapping_feedback_fails_closed():
    config = cfg()
    remember(config, "a")
    with patch("tabletap.acoustic_profiles.device_identity", return_value="a"):
        for db in (-43, -44, -45):
            add_feedback(config, "tap", db, False)
        for db in (-40, -38, -36):
            add_feedback(config, "noise", db, True)
        with pytest.raises(ValueError, match="overlap"):
            apply_feedback(config)
        assert config["detection"]["threshold_db"] == -36.


def test_changed_device_blocks_live():
    config = cfg()
    remember(config, "a")
    with patch("tabletap.acoustic_profiles.device_identity", return_value="b"):
        with pytest.raises(ValueError, match="changed"):
            verify_live(config)
