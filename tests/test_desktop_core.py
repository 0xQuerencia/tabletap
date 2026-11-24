import pytest
from unittest.mock import patch
from tabletap.desktop_core import DesktopSession, profiles, rows, validate_action
from tabletap.config import load_config


def session(tmp_path):
    return DesktopSession(tmp_path / "config.yaml")


def test_desktop_edits_preserve_other_actions(tmp_path):
    s = session(tmp_path)
    original = s.config()["actions"]["single"]
    with patch.object(s, "stop"), patch("tabletap.desktop_core.PIDLock") as lock:
        lock.return_value.acquire.return_value = True
        s.mapping("default", "double", {"name":"Mute", "type":"builtin", "value":"audio.mic_toggle"})
        assert s.config()["actions"]["single"] == original
        assert s.config()["actions"]["double"]["value"] == "audio.mic_toggle"
        assert s.path.with_suffix(".yaml.bak").exists()
        s.new_profile("coding")
        s.mapping("coding", 1, {"name":"Terminal", "type":"exec", "value":"foot"})
        assert "coding" in profiles(s.config())
        assert rows(s.config(), "coding")[0][1]["value"] == "foot"


def test_edit_refuses_running_listener(tmp_path):
    s = session(tmp_path)
    with patch.object(s, "stop"), patch("tabletap.desktop_core.PIDLock") as lock:
        lock.return_value.acquire.return_value = False
        with pytest.raises(RuntimeError):
            s.new_profile("coding")
    assert "coding" not in profiles(s.config())


def test_removed_features_rejected():
    for value in ("home.light_toggle:light.desk", "obs.record_toggle"):
        with pytest.raises(ValueError):
            validate_action({"name":"Old", "type":"builtin", "value":value}, {})
    with pytest.raises(ValueError):
        validate_action({"name":"Bad", "type":"workflow", "value":'[{"type":"parallel","value":[]}]'}, {})


def test_arm_only_same_config_preview(tmp_path):
    s = session(tmp_path)
    with patch.object(s, "status", return_value={"state":{"type":"ready","dry_run":True,"config_path":str(s.path)}}), patch.object(s, "_request") as req:
        s.arm()
        req.assert_called_once_with("arm", seconds=600)
    with patch.object(s, "status", return_value={"state":{"type":"ready","dry_run":True,"config_path":"/other.yaml"}}):
        with pytest.raises(RuntimeError):
            s.arm()


def test_onboarding_saves_only_chosen_mapping(tmp_path):
    s = session(tmp_path)
    before = s.config()["actions"]["single"]
    with patch.object(s, "stop"), patch("tabletap.desktop_core.PIDLock") as lock:
        lock.return_value.acquire.return_value = True
        s.complete_onboarding({"name":"Play music", "type":"builtin", "value":"media.play_pause"})
    cfg = load_config(s.path)
    assert cfg["desktop"]["onboarded"] is True
    assert cfg["actions"]["single"] == before
    assert cfg["actions"]["double"]["value"] == "media.play_pause"
