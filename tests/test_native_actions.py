from unittest.mock import patch
import pytest
from tabletap.action import ActionRunner
from tabletap.native_actions import execute_native


def test_mic_toggle_uses_system_state():
    with patch("tabletap.native_actions.shutil.which", return_value="/usr/bin/pactl"), patch("tabletap.native_actions.subprocess.run") as run:
        runner = ActionRunner({"single": {"type": "builtin", "value": "audio.mic_toggle"}})
        try:
            runner.run("single").result(timeout=2)
        finally:
            runner.shutdown()
        assert run.call_args.args[0] == ["pactl", "set-source-mute", "@DEFAULT_SOURCE@", "toggle"]
        assert run.call_args.kwargs["check"] is True


def test_unknown_builtin_fails_closed():
    with patch("tabletap.native_actions.subprocess.run") as run:
        with pytest.raises(ValueError, match="Unknown built-in"):
            execute_native("sh -c arbitrary")
        run.assert_not_called()


def test_missing_dependency():
    with patch("tabletap.native_actions.shutil.which", return_value=None), patch("tabletap.native_actions.subprocess.run") as run:
        with pytest.raises(RuntimeError, match="playerctl"):
            execute_native("media.play_pause")
        run.assert_not_called()
