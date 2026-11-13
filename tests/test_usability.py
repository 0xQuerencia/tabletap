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
