"""Regression checks for the terminal integration and action dispatch."""
import json
from unittest.mock import patch

from tabletap.action import ActionRunner
from tabletap.bridge import emit, run_bridge
from tabletap.daemon import Daemon


def test_bridge_emits_machine_readable_json(capsys):
    emit("gesture", pattern="double", action="spotify", dispatched=False)
    message = json.loads(capsys.readouterr().out)
    assert message == {
        "type": "gesture",
        "pattern": "double",
        "action": "spotify",
        "dispatched": False,
    }


def test_bridge_rejects_invalid_profile_before_opening_mic(capsys):
    with patch("tabletap.bridge.load_config", return_value={"actions": {}}):
        code = run_bridge(config_path="/does/not/matter", category="nonexistent")
    assert code == 2
    assert json.loads(capsys.readouterr().out)["type"] == "error"


def test_category_routes_single_to_first_action():
    runner = ActionRunner({
        "media": {
            1: {"type": "key", "value": "XF86AudioPlay"},
            2: {"type": "key", "value": "XF86AudioNext"},
        }
    }, category="media")
    assert runner._get_action("single")["value"] == "XF86AudioPlay"
    assert runner._get_action("double")["value"] == "XF86AudioNext"
    runner.shutdown()


def test_wayland_chords_hold_modifiers_until_target_released():
    runner = ActionRunner({})
    assert runner._convert_to_ydotool_format(["alt", "Tab"]) == [
        "56:1", "15:1", "15:0", "56:0",
    ]
    assert runner._convert_to_ydotool_format(["ctrl", "alt", "t"]) == [
        "29:1", "56:1", "20:1", "20:0", "56:0", "29:0",
    ]
    runner.shutdown()


def test_scripts_split_path_and_arguments_without_shell():
    runner = ActionRunner({})
    with patch("subprocess.Popen") as popen:
        runner._run_script("~/.local/bin/tabletap-lights toggle")
    args = popen.call_args.args[0]
    assert args[0] == "bash"
    assert args[1].endswith("/.local/bin/tabletap-lights")
    assert args[2] == "toggle"
    runner.shutdown()


def test_daemon_accepts_selected_category():
    with patch("tabletap.daemon.PIDLock"):
        daemon = Daemon({"actions": {"media": {1: {"type": "exec", "value": "true"}}}}, category="media")
    assert daemon.action_runner.category == "media"
    daemon.action_runner.shutdown()
