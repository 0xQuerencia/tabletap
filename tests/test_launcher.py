from unittest.mock import MagicMock, patch
import subprocess

import pytest

from tabletap.action import ActionRunner
from tabletap.launcher import choose_action, menu_command, profile_menu


def test_menu_uses_numbered_actions_and_excludes_recursion():
    actions = {"media": {2: {"name": "Next", "type": "builtin", "value": "media.next"},
                         1: {"name": "Open", "type": "exec", "value": "xdg-open ."},
                         3: {"type": "launcher", "value": "media"}}}
    assert list(profile_menu(actions, "media")) == ["1. Open", "2. Next"]
    with pytest.raises(ValueError):
        profile_menu(actions, "missing")


def test_menu_uses_optional_wayland_program():
    with patch("tabletap.launcher.shutil.which", side_effect=lambda p: "/bin/wofi" if p == "wofi" else None):
        assert menu_command("wayland")[0] == "/bin/wofi"
        with pytest.raises(RuntimeError):
            menu_command("x11")


def fake_process():
    process = MagicMock()
    process.__enter__.return_value = process
    process.returncode = 0
    process.poll.return_value = 0
    return process


def test_arbitrary_typed_text_never_dispatches():
    entries = {"1. Known": {"type": "exec", "value": "true"}}
    process = fake_process()
    process.communicate.return_value = ("unconfigured command\n", "")
    with patch("tabletap.launcher.menu_command", return_value=["menu"]), patch("tabletap.launcher.subprocess.Popen", return_value=process):
        assert choose_action(entries, "wayland", lambda: None) is None


def test_authorization_expiry_closes_open_menu():
    process = fake_process()
    process.poll.return_value = None
    process.communicate.side_effect = [subprocess.TimeoutExpired("menu", .1), ("", "")]
    check = MagicMock(side_effect=[None, None, RuntimeError("expired")])
    with patch("tabletap.launcher.menu_command", return_value=["menu"]), patch("tabletap.launcher.subprocess.Popen", return_value=process):
        with pytest.raises(RuntimeError, match="expired"):
            choose_action({"1. A": {}}, "wayland", check)
    process.terminate.assert_called_once()


def test_runner_executes_selected_action_only():
    mapping = {"media": {1: {"name": "Open", "type": "exec", "value": "true"}}}
    runner = ActionRunner(mapping)
    try:
        with patch("tabletap.action.choose_action", return_value=mapping["media"][1]), patch.object(runner, "_launch") as launch:
            runner._execute_action({"type": "launcher", "value": "media"})
            launch.assert_called_once_with("true")
        with patch("tabletap.action.choose_action", return_value=None), patch.object(runner, "_launch") as launch:
            assert runner._execute_action({"type": "launcher", "value": "media"}) == "dismissed"
            launch.assert_not_called()
    finally:
        runner.shutdown()
