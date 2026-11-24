import json
import threading
from unittest.mock import patch
import pytest
from tabletap.action import ActionRunner
from tabletap.workflow import parse_workflow


def workflow(*steps):
    return json.dumps([{"type": kind, "value": value} for kind, value in steps])


def test_sequence_validates_before_dispatch():
    runner = ActionRunner({})
    try:
        with patch.object(runner, "_launch") as launch:
            with pytest.raises(ValueError):
                runner._run_workflow(workflow(("exec", "first"), ("workflow", "[]")))
            launch.assert_not_called()
    finally:
        runner.shutdown()


def test_sequence_order_and_fail_fast():
    runner = ActionRunner({})
    try:
        with patch.object(runner, "_launch", side_effect=[None, RuntimeError("missing")]) as launch:
            with pytest.raises(RuntimeError, match="step 2"):
                runner._run_workflow(workflow(("exec", "first"), ("exec", "second"), ("exec", "third")))
            assert [c.args[0] for c in launch.call_args_list] == ["first", "second"]
    finally:
        runner.shutdown()


def test_cancel_stops_wait_and_future_steps():
    runner = ActionRunner({"single": {"type": "workflow", "value": workflow(("exec", "first"), ("wait", 10000), ("exec", "never"))}})
    started = threading.Event()
    try:
        with patch.object(runner, "_launch", side_effect=lambda _: started.set()) as launch:
            task = runner.run("single")
            assert started.wait(2)
            runner.cancel()
            with pytest.raises(RuntimeError, match="cancelled"):
                task.result(timeout=2)
            launch.assert_called_once_with("first")
    finally:
        runner.shutdown()


def test_expired_authorization_refuses_action():
    runner = ActionRunner({})
    runner.deadline = 0
    try:
        with patch.object(runner, "_launch") as launch:
            with pytest.raises(RuntimeError, match="expired"):
                runner._execute_action({"type": "exec", "value": "never"})
            launch.assert_not_called()
    finally:
        runner.shutdown()


@pytest.mark.parametrize("value", ["[]", '[{"type":"wait","value":NaN}]', '[{"type":"wait","value":true}]', '[{"type":"builtin","value":"missing"}]'])
def test_invalid_workflow(value):
    with pytest.raises(ValueError):
        parse_workflow(value)


@pytest.mark.parametrize("kind", ["parallel", "if"])
def test_removed_workflow_blocks_rejected_before_any_dispatch(kind):
    runner = ActionRunner({})
    try:
        with patch.object(runner, "_launch") as launch:
            with pytest.raises(ValueError, match="unsupported action"):
                runner._run_workflow(workflow(("exec", "first"), (kind, [])))
            launch.assert_not_called()
    finally:
        runner.shutdown()
