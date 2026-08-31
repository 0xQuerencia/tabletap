import pytest
from unittest.mock import patch, MagicMock, call
from tabletap.action import ActionRunner, KEY_MAP


def test_press_key_builds_correct_command():
    runner = ActionRunner({"single": {"type": "key", "value": "ctrl+alt+t"}})
    runner.display_server = "x11"
    
    with patch("subprocess.Popen") as mock_popen:
        runner._press_key("ctrl+alt+t")
        
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert args == ["xdotool", "key", "ctrl+alt+t"]


def test_key_name_mapping():
    runner = ActionRunner({})
    runner.display_server = "x11"
    
    with patch("subprocess.Popen") as mock_popen:
        runner._press_key("enter")
        
        args = mock_popen.call_args[0][0]
        assert args == ["xdotool", "key", "Return"]


def test_key_mapping_space():
    runner = ActionRunner({})
    runner.display_server = "x11"
    
    with patch("subprocess.Popen") as mock_popen:
        runner._press_key("space")
        
        args = mock_popen.call_args[0][0]
        assert args == ["xdotool", "key", "space"]


def test_key_mapping_escape():
    runner = ActionRunner({})
    runner.display_server = "x11"
    
    with patch("subprocess.Popen") as mock_popen:
        runner._press_key("escape")
        
        args = mock_popen.call_args[0][0]
        assert args == ["xdotool", "key", "Escape"]


def test_no_shell_true_in_subprocess():
    runner = ActionRunner({})
    runner.display_server = "x11"
    
    with patch("subprocess.Popen") as mock_popen:
        runner._press_key("ctrl+c")
        
        call_kwargs = mock_popen.call_args[1]
        assert "shell" not in call_kwargs or call_kwargs.get("shell") is False


def test_launch_uses_shlex_split():
    runner = ActionRunner({})
    
    with patch("subprocess.Popen") as mock_popen:
        runner._launch("firefox")
        
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert isinstance(args, list)


def test_run_script_uses_bash():
    runner = ActionRunner({})
    
    with patch("subprocess.Popen") as mock_popen:
        runner._run_script("/path/to/script.sh")
        
        args = mock_popen.call_args[0][0]
        assert args[0] == "bash"
        assert args[1] == "/path/to/script.sh"


def test_run_action_dispatches_key():
    actions = {"single": {"type": "key", "value": "ctrl+alt+t"}}
    runner = ActionRunner(actions)
    runner.display_server = "x11"
    
    with patch("subprocess.Popen"):
        runner.run("single")
        runner._executor.shutdown(wait=True)


def test_run_action_dispatches_exec():
    actions = {"double": {"type": "exec", "value": "firefox"}}
    runner = ActionRunner(actions)
    
    with patch("subprocess.Popen"):
        runner.run("double")
        runner._executor.shutdown(wait=True)


def test_run_action_dispatches_script():
    actions = {"triple": {"type": "script", "value": "/tmp/test.sh"}}
    runner = ActionRunner(actions)
    
    with patch("subprocess.Popen"):
        runner.run("triple")
        runner._executor.shutdown(wait=True)


def test_run_action_ignores_unknown_key():
    runner = ActionRunner({})
    
    with patch("subprocess.Popen") as mock_popen:
        runner.run("unknown")
        runner._executor.shutdown(wait=True)
        
        mock_popen.assert_not_called()


def test_run_action_ignores_empty_value():
    actions = {"single": {"type": "key", "value": ""}}
    runner = ActionRunner(actions)
    
    with patch("subprocess.Popen") as mock_popen:
        runner.run("single")
        runner._executor.shutdown(wait=True)
        
        mock_popen.assert_not_called()


def test_modifier_key_normalization():
    runner = ActionRunner({})
    runner.display_server = "x11"
    
    with patch("subprocess.Popen") as mock_popen:
        runner._press_key("control+shift+a")
        
        args = mock_popen.call_args[0][0]
        assert args == ["xdotool", "key", "ctrl+shift+a"]


def test_super_key_mapping():
    runner = ActionRunner({})
    runner.display_server = "x11"
    
    with patch("subprocess.Popen") as mock_popen:
        runner._press_key("super+d")
        
        args = mock_popen.call_args[0][0]
        assert args == ["xdotool", "key", "super+d"]


def test_devnull_stdout_stderr():
    runner = ActionRunner({})
    runner.display_server = "x11"
    
    with patch("subprocess.Popen") as mock_popen:
        runner._press_key("a")
        
        call_kwargs = mock_popen.call_args[1]
        assert "stdout" in call_kwargs
        assert "stderr" in call_kwargs
