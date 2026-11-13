"""Regression tests for safe action dispatch and listener resource locking."""
import os
from unittest.mock import patch

import pytest

from tabletap.action import ActionRunner
from tabletap.lock import PIDLock


def test_empty_category_never_falls_back_to_default_action():
    runner = ActionRunner({
        "single": {"type": "exec", "value": "echo DANGEROUS"},
        "empty": {},
    }, category="empty")
    try:
        assert runner._get_action("single") is None
        assert runner.run("single") is None
    finally:
        runner.shutdown()


def test_missing_category_mapping_does_not_run_unrelated_actions():
    runner = ActionRunner({
        "single": {"type": "exec", "value": "echo DANGEROUS"},
        "media": {2: {"type": "exec", "value": "echo double"}},
    }, category="media")
    try:
        assert runner._get_action("single") is None
        assert runner._get_action("double")["value"] == "echo double"
    finally:
        runner.shutdown()


def test_action_launch_failure_reported_without_stdout_corruption(capsys):
    outcomes = []
    runner = ActionRunner({
        "single": {"type": "exec", "value": "missing-app"},
    }, on_result=lambda key, status, message: outcomes.append((key, status, message)))
    try:
        with patch("subprocess.Popen", side_effect=FileNotFoundError("not installed")):
            task = runner.run("single")
            with pytest.raises(RuntimeError, match="Command launch failed"):
                task.result(timeout=3)
        assert outcomes and outcomes[0][0:2] == ("single", "failed")
        assert "not installed" in outcomes[0][2]
        assert capsys.readouterr().out == ""
    finally:
        runner.shutdown()


def test_action_success_reported_as_launched_not_completed():
    outcomes = []
    runner = ActionRunner({
        "double": {"type": "exec", "value": "firefox"},
    }, on_result=lambda key, status, message: outcomes.append((key, status, message)))
    try:
        with patch("subprocess.Popen"):
            task = runner.run("double")
            task.result(timeout=3)
        assert outcomes == [("double", "launched", "")]
    finally:
        runner.shutdown()


def test_empty_action_value_is_not_reported_as_dispatched():
    outcomes = []
    runner = ActionRunner({"single": {"type": "exec", "value": "   "}},
                          on_result=lambda *args: outcomes.append(args))
    try:
        assert runner.run("single") is None
        assert outcomes == []
    finally:
        runner.shutdown()


def test_pid_lock_contender_cannot_truncate_current_owners_pid(tmp_path):
    path = tmp_path / "daemon.pid"
    first = PIDLock(path)
    second = PIDLock(path)
    try:
        assert first.acquire() is True
        assert path.read_text() == str(os.getpid())
        assert second.acquire() is False
        assert path.read_text() == str(os.getpid())
    finally:
        second.release()
        first.release()
    assert path.read_text() == ""
    third = PIDLock(path)
    assert third.acquire() is True
    third.release()


def test_failed_mic_open_releases_portaudio():
    from unittest.mock import MagicMock
    from tabletap.mic import MicCapture

    pa = MagicMock()
    pa.open.side_effect = OSError("No input device")
    with patch("tabletap.mic.pyaudio") as audio:
        audio.PyAudio.return_value = pa
        with pytest.raises(OSError, match="No input device"):
            MicCapture({"sample_rate": 44100}, {"enabled": True})
    pa.terminate.assert_called_once()


def test_close_mic_is_idempotent():
    from unittest.mock import MagicMock
    from tabletap.mic import MicCapture

    pa = MagicMock()
    stream = MagicMock()
    pa.open.return_value = stream
    with patch("tabletap.mic.pyaudio") as audio:
        audio.PyAudio.return_value = pa
        mic = MicCapture({"sample_rate": 44100}, {"enabled": False})
    mic.close()
    mic.close()
    stream.close.assert_called_once()
    pa.terminate.assert_called_once()


def test_calibration_preserves_config_comments_and_external_edits(tmp_path):
    from tabletap.config import save_calibration

    path = tmp_path / "config.yaml"
    original = """# user comments matter
audio:
  sample_rate: 44100 # user preferred mic
actions:
  single:
    type: exec
    value: firefox # user choice
detection:
  threshold_db: -30.0 # previous value
"""
    path.write_text(original)
    stale_cfg = {"audio": {"sample_rate": 48000}, "actions": {"single": {"value": "spotify"}}}
    save_calibration(stale_cfg, {
        "noise_floor_db": -46.0, "slam_peak_db": -19.0, "threshold_db": -36.0,
    }, path)
    changed = path.read_text()
    assert "# user comments matter" in changed
    assert "# user preferred mic" in changed
    assert "# user choice" in changed
    assert "firefox" in changed and "spotify" not in changed
    assert path.with_suffix(".yaml.bak").read_text() == original
    assert "threshold_db: -36.0" in changed


def test_microphone_enumeration_only_returns_input_devices():
    from unittest.mock import MagicMock
    from tabletap.mic import list_input_devices

    pa = MagicMock()
    pa.get_device_count.return_value = 3
    pa.get_default_input_device_info.return_value = {"index": 2}
    pa.get_device_info_by_index.side_effect = [
        {"name": "Output only", "maxInputChannels": 0},
        {"name": "Built-in Mic", "maxInputChannels": 1, "defaultSampleRate": 44100},
        {"name": "USB Mic", "maxInputChannels": 2, "defaultSampleRate": 48000},
    ]
    with patch("tabletap.mic.pyaudio") as lib:
        lib.PyAudio.return_value = pa
        devices = list_input_devices()
    assert [dev["index"] for dev in devices] == [1, 2]
    assert devices[0]["default"] is False
    assert devices[1]["default"] is True
    assert devices[1]["sample_rate"] == 48000
    pa.terminate.assert_called_once()


def test_devices_cli_returns_parseable_json(monkeypatch, capsys):
    import json
    import sys
    from tabletap.__main__ import main

    monkeypatch.setattr(sys, "argv", ["tabletap", "devices", "--json"])
    with patch("tabletap.mic.list_input_devices", return_value=[
        {"index": 4, "name": "Test Mic", "default": True, "channels": 1, "sample_rate": 44100},
    ]):
        main()
    assert json.loads(capsys.readouterr().out)["devices"][0]["index"] == 4
