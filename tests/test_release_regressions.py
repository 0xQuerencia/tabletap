"""Release regressions for background parity, invalid config and service installation."""
import json
from unittest.mock import patch

import pytest

from tabletap.bridge import run_bridge, run_calibration
from tabletap.calibrate import calibrate
from tabletap.config import load_config
from tabletap.mic import MicDisconnected
from tabletap.service import install_user_service, render_user_service


def test_invalid_empty_yaml_has_actionable_error(tmp_path):
    target = tmp_path / "config.yaml"
    target.write_text("")
    with pytest.raises(ValueError, match="mapping"):
        load_config(target)


def test_invalid_config_section_is_rejected(tmp_path):
    target = tmp_path / "config.yaml"
    target.write_text("actions: []\n")
    with pytest.raises(ValueError, match="actions"):
        load_config(target)


def test_invalid_bridge_config_still_returns_json_error(capsys):
    with patch("tabletap.bridge.load_config", side_effect=ValueError("bad YAML")):
        code = run_bridge(config_path="/invalid")
    assert code == 2
    event = json.loads(capsys.readouterr().out)
    assert event["type"] == "error"
    assert "bad YAML" in event["message"]


def test_calibration_disconnect_is_machine_readable(capsys):
    cfg = {"audio": {}, "filter": {}}
    with patch("tabletap.bridge.load_config", return_value=cfg), \
         patch("tabletap.bridge.PIDLock") as lock, \
         patch("tabletap.bridge.device_identity", return_value="fake-device"), \
         patch("tabletap.calibrate.calibrate", side_effect=MicDisconnected("USB mic removed")):
        lock.return_value.acquire.return_value = True
        result = run_calibration(config_path="/synthetic")
    assert result == 1
    message = json.loads(capsys.readouterr().out)
    assert message["type"] == "error"
    assert "USB mic removed" in message["message"]
    lock.return_value.release.assert_called_once()


def test_calibration_rejects_zero_and_negative_duration():
    for duration in (0, -1):
        with pytest.raises(ValueError, match="greater than zero"):
            calibrate({}, duration_sec=duration)



def test_user_service_uses_invoking_python_and_no_fake_display(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    venv_python = "/home/wizrizz/tabletap/.venv/bin/python"
    content = render_user_service(venv_python)
    assert f'ExecStart="{venv_python}" -m tabletap start' in content
    assert " start --preview" in content
    assert " start --preview" not in render_user_service(venv_python, live=True)
    assert "DISPLAY=:0" not in content
    assert "WAYLAND_DISPLAY=wayland-0" not in content
    unit = install_user_service(venv_python)
    assert unit.is_file()
    assert unit.read_text() == content
    assert unit.stat().st_mode & 0o077 == 0


def test_service_refuses_relative_interpreter():
    with pytest.raises(ValueError, match="absolute"):
        render_user_service("python")


def test_cached_ui_includes_native_catalog(tmp_path, monkeypatch):
    import json
    from tabletap.__main__ import _prepare_ui
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    cache = _prepare_ui()
    actions = json.loads((cache / "native-actions.json").read_text())
    assert any(item["id"] == "audio.mic_toggle" for item in actions)


def test_cli_init_and_preview_dispatch(tmp_path, monkeypatch):
    import sys
    from tabletap.__main__ import main, preview_cmd
    target = tmp_path / "new.yaml"
    monkeypatch.setattr(sys, "argv", ["tabletap","init","--path",str(target)])
    main()
    assert target.exists()
    with patch("tabletap.bridge.run_bridge", return_value=0) as bridge:
        assert preview_cmd(str(target), 5) == 0
    assert bridge.call_args.kwargs["dry_run"] is True
    assert bridge.call_args.kwargs["duration"] == 5
